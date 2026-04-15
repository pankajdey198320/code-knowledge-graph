"""Repo indexer – crawl a mono-repo, parse all source files, build the KG."""

from __future__ import annotations

import pickle
from pathlib import Path

from tqdm import tqdm

from kg_rag.config import settings
from kg_rag.models import KnowledgeGraph
from kg_rag.parsers.router import language_for_extension, parse_file


def discover_files(
    repo_root: Path,
    extensions: list[str] | None = None,
    skip_dirs: set[str] | None = None,
    scope_paths: list[Path] | None = None,
) -> list[Path]:
    """Walk *repo_root* (or scoped sub-dirs) and collect matching source files.

    Args:
        scope_paths: If provided, only search within these directories instead
            of the full *repo_root*.
    """
    extensions = extensions or settings.INDEX_EXTENSIONS
    skip_dirs = skip_dirs or settings.SKIP_DIRS

    roots = scope_paths if scope_paths else [repo_root]

    matched: list[Path] = []
    for root in roots:
        root = root.resolve()
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_dir():
                continue
            # Skip excluded directories
            if skip_dirs and any(part in skip_dirs for part in path.parts):
                continue
            if path.suffix in extensions and language_for_extension(path.suffix) is not None:
                matched.append(path)
    return sorted(set(matched))


def index_repo(
    repo_root: Path | None = None,
    extensions: list[str] | None = None,
    skip_dirs: set[str] | None = None,
    show_progress: bool = True,
    scope_paths: list[Path] | None = None,
) -> KnowledgeGraph:
    """Parse every supported source file and merge into one KG.

    Args:
        scope_paths: If provided, only index these sub-directories.
    """
    repo_root = (repo_root or settings.REPO_ROOT).resolve()
    files = discover_files(
        repo_root, extensions=extensions, skip_dirs=skip_dirs, scope_paths=scope_paths,
    )

    kg = KnowledgeGraph()
    iterator = tqdm(files, desc="Indexing", disable=not show_progress)

    for file_path in iterator:
        try:
            sub_kg = parse_file(file_path, repo_root)
            if sub_kg:
                for ent in sub_kg.entities:
                    kg.add_entity(ent)
                for rel in sub_kg.relations:
                    kg.add_relation(rel)
        except Exception as exc:
            # Log but don't stop – one bad file shouldn't block the whole index
            if show_progress:
                tqdm.write(f"  WARN: {file_path}: {exc}")

    return kg


def save_graph(kg: KnowledgeGraph, path: Path | None = None) -> Path:
    """Persist the KG to a pickle file."""
    path = path or settings.GRAPH_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(kg.model_dump(), f)
    return path


def load_graph(path: Path | None = None) -> KnowledgeGraph:
    """Load a previously saved KG from disk."""
    path = path or settings.GRAPH_CACHE_PATH
    with open(path, "rb") as f:
        data = pickle.load(f)  # noqa: S301 – trusted local file
    return KnowledgeGraph(**data)
