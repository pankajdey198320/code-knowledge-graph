"""Extract commit history, authorship, co-change, and work-item links from git."""

from __future__ import annotations

import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from kg_rag.models import (
    CodeEntityType,
    CodeRelationType,
    Entity,
    KnowledgeGraph,
    Relation,
)

# ---------------------------------------------------------------------------
# Configurable patterns for extracting work-item IDs from commit messages
# ---------------------------------------------------------------------------
_WORKITEM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:AB)?#(\d{4,})"),      # #12345 or AB#12345
    re.compile(r"([A-Z]+-\d+)"),           # JIRA-1234
]

# Separator used by our custom --pretty format
_SEP = "|"
_COMMIT_PREFIX = "COMMIT"


# ======================================================================
# Raw git log parsing
# ======================================================================

def _run_git_log(
    repo_root: Path,
    scope_paths: list[Path] | None = None,
    since: str | None = None,
    max_count: int | None = None,
) -> str:
    """Run ``git log`` and return raw stdout."""
    cmd: list[str] = [
        "git", "-C", str(repo_root),
        "log",
        "--no-merges",
        "--name-only",
        f"--pretty=format:{_COMMIT_PREFIX}{_SEP}%H{_SEP}%an{_SEP}%ae{_SEP}%aI{_SEP}%s",
    ]
    if since:
        cmd.append(f"--since={since}")
    if max_count:
        cmd.extend(["--max-count", str(max_count)])
    cmd.append("--")
    if scope_paths:
        for p in scope_paths:
            # Make path relative to repo root for git
            try:
                rel = p.resolve().relative_to(repo_root.resolve())
                cmd.append(str(rel))
            except ValueError:
                cmd.append(str(p))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    return result.stdout


class _CommitRecord:
    """Internal parsed representation of a single git commit."""

    __slots__ = ("sha", "author_name", "author_email", "date", "message", "files")

    def __init__(
        self,
        sha: str,
        author_name: str,
        author_email: str,
        date: str,
        message: str,
    ):
        self.sha = sha
        self.author_name = author_name
        self.author_email = author_email
        self.date = date
        self.message = message
        self.files: list[str] = []


def _parse_git_log(raw: str) -> list[_CommitRecord]:
    """Parse the structured ``git log`` output into commit records."""
    commits: list[_CommitRecord] = []
    current: _CommitRecord | None = None

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(_COMMIT_PREFIX + _SEP):
            parts = line.split(_SEP, 5)
            if len(parts) < 6:
                continue
            current = _CommitRecord(
                sha=parts[1],
                author_name=parts[2],
                author_email=parts[3],
                date=parts[4],
                message=parts[5],
            )
            commits.append(current)
        elif current is not None:
            # Lines after the COMMIT header are changed file paths
            current.files.append(line)

    return commits


# ======================================================================
# Work-item ID extraction
# ======================================================================

def _extract_workitem_ids(message: str) -> list[str]:
    """Return unique work-item IDs found in a commit *message*."""
    ids: list[str] = []
    for pat in _WORKITEM_PATTERNS:
        ids.extend(pat.findall(message))
    return list(dict.fromkeys(ids))  # dedupe, preserve order


# ======================================================================
# KG construction from git history
# ======================================================================

def build_git_history_graph(
    repo_root: Path,
    scope_paths: list[Path] | None = None,
    since: str | None = "2 years ago",
    max_count: int | None = None,
    max_files_per_commit: int = 50,
    co_change_threshold: int = 3,
    index_extensions: list[str] | None = None,
) -> KnowledgeGraph:
    """Build a KG layer from git commit history.

    Returns a :class:`KnowledgeGraph` containing commit, author, and
    work_item entities plus COMMITTED_IN, MODIFIED_BY, CO_CHANGED, and
    LINKED_TO relations.

    Args:
        repo_root: Path to the git repository root.
        scope_paths: Limit to commits touching these sub-directories.
        since: ``git log --since`` value (e.g. "1 year ago"). *None* = all.
        max_count: Cap the number of commits retrieved.
        max_files_per_commit: Skip commits touching more files (noise filter).
        co_change_threshold: Minimum co-occurrence count to create a CO_CHANGED edge.
        index_extensions: If set, only include files with these extensions.
    """
    raw = _run_git_log(repo_root, scope_paths, since, max_count)
    commits = _parse_git_log(raw)

    kg = KnowledgeGraph()
    seen_authors: set[str] = set()
    seen_workitems: set[str] = set()

    # Counters for weighted relations
    author_file_counts: Counter[tuple[str, str]] = Counter()  # (author_email, file) → count
    co_change_counts: Counter[tuple[str, str]] = Counter()    # (file_a, file_b) → count

    allowed_exts = set(index_extensions) if index_extensions else None

    for commit in commits:
        # Filter files to indexed extensions only
        files = commit.files
        if allowed_exts:
            files = [f for f in files if Path(f).suffix in allowed_exts]

        # Skip oversized commits (noise)
        if len(files) > max_files_per_commit:
            continue

        # --- Commit entity ---
        commit_entity = Entity(
            name=commit.sha[:8],
            entity_type=CodeEntityType.COMMIT,
            metadata={
                "sha": commit.sha,
                "author": commit.author_name,
                "email": commit.author_email,
                "date": commit.date,
                "message": commit.message,
            },
        )
        kg.add_entity(commit_entity)

        # --- Author entity ---
        author_key = commit.author_email.lower()
        if author_key not in seen_authors:
            seen_authors.add(author_key)
            kg.add_entity(Entity(
                name=commit.author_name,
                entity_type=CodeEntityType.AUTHOR,
                metadata={"email": author_key},
            ))

        # --- COMMITTED_IN relations (file → commit) ---
        for fpath in files:
            kg.add_relation(Relation(
                source=fpath,
                target=commit_entity.qualified_key,
                relation_type=CodeRelationType.COMMITTED_IN,
            ))
            # Track author-file for MODIFIED_BY
            author_file_counts[(author_key, fpath)] += 1

        # --- Co-change pairs ---
        sorted_files = sorted(set(files))
        for i, fa in enumerate(sorted_files):
            for fb in sorted_files[i + 1:]:
                co_change_counts[(fa, fb)] += 1

        # --- Work-item IDs ---
        wids = _extract_workitem_ids(commit.message)
        for wid in wids:
            if wid not in seen_workitems:
                seen_workitems.add(wid)
                kg.add_entity(Entity(
                    name=f"WI#{wid}",
                    entity_type=CodeEntityType.WORK_ITEM,
                    metadata={"id": wid},
                ))
            kg.add_relation(Relation(
                source=commit_entity.qualified_key,
                target=f"::WI#{wid}@0",
                relation_type=CodeRelationType.LINKED_TO,
                metadata={"work_item_id": wid},
            ))

    # --- MODIFIED_BY (file → author, with weight) ---
    for (author_email, fpath), count in author_file_counts.items():
        kg.add_relation(Relation(
            source=fpath,
            target=f"::{_author_name_for(seen_authors, author_email, commits)}@0",
            relation_type=CodeRelationType.MODIFIED_BY,
            metadata={"commit_count": str(count), "email": author_email},
        ))

    # --- CO_CHANGED (file ↔ file, with weight, thresholded) ---
    for (fa, fb), count in co_change_counts.items():
        if count >= co_change_threshold:
            kg.add_relation(Relation(
                source=fa,
                target=fb,
                relation_type=CodeRelationType.CO_CHANGED,
                metadata={"co_change_count": str(count)},
            ))

    return kg


def _author_name_for(
    seen: set[str], email: str, commits: list[_CommitRecord],
) -> str:
    """Look up the display name for an author email."""
    for c in commits:
        if c.author_email.lower() == email:
            return c.author_name
    return email


# ======================================================================
# Public helpers
# ======================================================================

def merge_git_layer(
    code_kg: KnowledgeGraph,
    git_kg: KnowledgeGraph,
) -> None:
    """Merge git-history entities & relations into an existing code KG *in place*."""
    for ent in git_kg.entities:
        code_kg.add_entity(ent)
    for rel in git_kg.relations:
        code_kg.add_relation(rel)
