"""MCP server exposing the code Knowledge Graph as query tools.

Run with:
    python -m kg_rag.mcp_server          # stdio transport (for IDE/agent integration)
    kg-mcp                                # same, via the entry-point
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from kg_rag.config import settings
from kg_rag.indexer import index_repo, load_graph, save_graph
from kg_rag.models import CodeEntityType, KnowledgeGraph
from kg_rag.projects import ProjectsConfig
from kg_rag.retriever import GraphRetriever

logger = logging.getLogger(__name__)

# ======================================================================
# Singleton graph state for the active MCP project.
# ======================================================================

_kg: KnowledgeGraph | None = None
_retriever: GraphRetriever | None = None
_embedder_loaded = False
_projects_cfg: ProjectsConfig = ProjectsConfig.load()
_active_project: str = _projects_cfg.default_project_name(settings.ACTIVE_PROJECT)
_DEFAULT_LIST_LIMIT = 100
_DEFAULT_MATCH_LIMIT = 25
_DEFAULT_RELATION_LIMIT = 50
_DEFAULT_TEXT_LIMIT = 12000


def _cache_path_for(project: str) -> Path:
    """Return the pickle cache path for a project name."""
    if _projects_cfg.projects:
        return _projects_cfg.graph_cache_path(project)
    return settings.GRAPH_CACHE_PATH


def _load_graph(project: str | None = None) -> KnowledgeGraph:
    """Load (or build) the graph for a project. Called once at startup."""
    global _kg, _active_project
    project = _projects_cfg.default_project_name(project or _active_project)

    if _kg is not None and project == _active_project:
        return _kg

    cache = _cache_path_for(project)
    if cache.exists():
        print(f"[kg-mcp] Loading '{project}' graph from {cache} ...", file=sys.stderr)
        _kg = load_graph(cache)
    else:
        # Try to build the project scope
        repo_root = _projects_cfg.get_repo_root()
        scope = _projects_cfg.projects.get(project)
        scope_paths = _projects_cfg.resolve_paths(project) if scope else None
        print(f"[kg-mcp] No cache – indexing project '{project}' ...", file=sys.stderr)
        _kg = index_repo(repo_root, show_progress=True, scope_paths=scope_paths)
        save_graph(_kg, cache)

    _active_project = project
    print(
        f"[kg-mcp] Graph ready ({project}): {len(_kg.entities)} entities, "
        f"{len(_kg.relations)} relations",
        file=sys.stderr,
    )
    return _kg


def _truncate_text(text: str, limit: int = _DEFAULT_TEXT_LIMIT) -> str:
    """Trim large MCP responses so stdio clients don't choke on giant payloads."""
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n\n... truncated {omitted} characters ..."


def _summarize_matches(total: int, shown: int, noun: str) -> str:
    if total <= shown:
        return f"Found {total} {noun}."
    return f"Found {total} {noun}; showing first {shown}."


def _ensure_retriever() -> GraphRetriever:
    """Lazily create the retriever (loads embedding model on first call)."""
    global _retriever, _embedder_loaded
    if _retriever is not None:
        return _retriever

    kg = _load_graph()
    print("[kg-mcp] Loading embedding model (first semantic query) ...", file=sys.stderr)
    from kg_rag.embeddings import KGEmbedder

    _retriever = GraphRetriever(kg=kg, embedder=KGEmbedder())
    _embedder_loaded = True
    print("[kg-mcp] Embedder ready.", file=sys.stderr)
    return _retriever


def _get_kg() -> KnowledgeGraph:
    """Return the graph (already loaded at startup)."""
    if _kg is None:
        _load_graph()
    assert _kg is not None
    return _kg


# ======================================================================
# MCP server
# ======================================================================

mcp = FastMCP(
    "code-knowledge-graph",
    instructions=(
        "Tools for querying a source-code knowledge graph built from a mono-repo. "
        "The graph contains entities such as files, classes, functions, methods, "
        "namespaces, imports, and their relationships (DEFINES, CONTAINS, CALLS, "
        "IMPORTS, INHERITS, etc.)."
    ),
)


# --- Tool: semantic search ------------------------------------------------


@mcp.tool()
def search_code(query: str, top_k: int = 10, max_chars: int = _DEFAULT_TEXT_LIMIT) -> str:
    """Semantic search over the code knowledge graph.

    Finds entities (classes, functions, methods, …) whose names, signatures or
    docstrings are most similar to the natural-language *query*.

    Args:
        query: Natural-language description of what you're looking for.
        top_k: Number of results to return (default 10).
    """
    retriever = _ensure_retriever()
    if top_k != retriever.top_k:
        retriever = GraphRetriever(
            kg=_get_kg(),
            embedder=retriever.embedder,
            top_k=top_k,
            hops=retriever.hops,
        )
    ctx = retriever.retrieve(query)
    return _truncate_text(ctx.subgraph_text, max_chars)


# --- Tool: lookup by name ------------------------------------------------


@mcp.tool()
def lookup_symbol(
    name: str,
    max_matches: int = _DEFAULT_MATCH_LIMIT,
    max_relations_per_match: int = _DEFAULT_RELATION_LIMIT,
) -> str:
    """Find code entities whose name contains *name* and return their neighbourhood.

    Args:
        name: Partial or full symbol name to search for (case-insensitive).
    """
    kg = _get_kg()
    matches = kg.find_entities(name=name)
    if not matches:
        return f"No entities found matching '{name}'."
    shown_matches = matches[:max_matches]
    lines: list[str] = [_summarize_matches(len(matches), len(shown_matches), "matching entities"), ""]
    for ent in shown_matches:
        loc = f" ({ent.file_path}:{ent.line_start})" if ent.file_path else ""
        sig = f" — {ent.signature}" if ent.signature else ""
        lines.append(f"- [{ent.entity_type.value}] {ent.name}{loc}{sig}")
        # Show immediate relations
        relation_count = 0
        for rel in kg.relations:
            if rel.source == ent.qualified_key:
                lines.append(f"    --[{rel.relation_type.value}]--> {rel.target}")
                relation_count += 1
            elif rel.target == ent.qualified_key:
                lines.append(f"    <--[{rel.relation_type.value}]-- {rel.source}")
                relation_count += 1
            if relation_count >= max_relations_per_match:
                lines.append(f"    ... relation output capped at {max_relations_per_match} ...")
                break
    return _truncate_text("\n".join(lines))


# --- Tool: file overview --------------------------------------------------


@mcp.tool()
def file_overview(file_path: str, max_entities: int = _DEFAULT_LIST_LIMIT) -> str:
    """List all code entities defined in a specific file.

    Args:
        file_path: Relative path of the file inside the repo (e.g. "src/utils.py").
    """
    kg = _get_kg()
    matches = kg.find_entities(file_path=file_path)
    if not matches:
        return f"No entities found in '{file_path}'."
    shown_matches = matches[:max_entities]
    lines = [f"File: {file_path} — {len(matches)} entities", _summarize_matches(len(matches), len(shown_matches), "entities"), ""]
    for ent in shown_matches:
        sig = f" — {ent.signature}" if ent.signature else ""
        lines.append(f"- [{ent.entity_type.value}] {ent.name} (L{ent.line_start}){sig}")
    return _truncate_text("\n".join(lines))


# --- Tool: list classes ---------------------------------------------------


@mcp.tool()
def list_classes(name_filter: str = "", limit: int = _DEFAULT_LIST_LIMIT) -> str:
    """List all classes in the codebase, optionally filtered by name.

    Args:
        name_filter: Only include classes whose name contains this string.
    """
    kg = _get_kg()
    classes = kg.find_entities(
        name=name_filter or None, entity_type=CodeEntityType.CLASS
    )
    if not classes:
        return "No classes found."
    shown_classes = classes[:limit]
    lines = [_summarize_matches(len(classes), len(shown_classes), "class(es)"), ""]
    for c in shown_classes:
        loc = f"  ({c.file_path}:{c.line_start})" if c.file_path else ""
        lines.append(f"- {c.name}{loc}")
        if c.signature:
            lines.append(f"  {c.signature}")
    return _truncate_text("\n".join(lines))


# --- Tool: list functions -------------------------------------------------


@mcp.tool()
def list_functions(name_filter: str = "", limit: int = _DEFAULT_LIST_LIMIT) -> str:
    """List all top-level functions in the codebase, optionally filtered by name.

    Args:
        name_filter: Only include functions whose name contains this string.
    """
    kg = _get_kg()
    funcs = kg.find_entities(
        name=name_filter or None, entity_type=CodeEntityType.FUNCTION
    )
    if not funcs:
        return "No functions found."
    shown_funcs = funcs[:limit]
    lines = [_summarize_matches(len(funcs), len(shown_funcs), "function(s)"), ""]
    for f in shown_funcs:
        loc = f"  ({f.file_path}:{f.line_start})" if f.file_path else ""
        lines.append(f"- {f.name}{loc}")
        if f.signature:
            lines.append(f"  {f.signature}")
    return _truncate_text("\n".join(lines))


# --- Tool: call graph -----------------------------------------------------


@mcp.tool()
def call_graph(
    function_name: str,
    max_matches: int = _DEFAULT_MATCH_LIMIT,
    max_relations_per_match: int = _DEFAULT_RELATION_LIMIT,
) -> str:
    """Show what a function/method calls and what calls it.

    Args:
        function_name: Name (or partial name) of the function to inspect.
    """
    kg = _get_kg()
    # Find matching entities
    funcs = kg.find_entities(name=function_name)
    if not funcs:
        return f"No entity found matching '{function_name}'."

    shown_funcs = funcs[:max_matches]
    lines: list[str] = [_summarize_matches(len(funcs), len(shown_funcs), "matching entities"), ""]
    for func in shown_funcs:
        lines.append(f"### {func.name} ({func.entity_type.value}) — {func.file_path}:{func.line_start}")
        calls_out = [
            r for r in kg.relations
            if r.source == func.qualified_key and r.relation_type.value == "CALLS"
        ]
        called_by = [
            r for r in kg.relations
            if r.target == func.qualified_key and r.relation_type.value == "CALLS"
        ]
        if calls_out:
            lines.append("  Calls:")
            for r in calls_out[:max_relations_per_match]:
                lines.append(f"    → {r.target}")
            if len(calls_out) > max_relations_per_match:
                lines.append(f"    ... {len(calls_out) - max_relations_per_match} more ...")
        if called_by:
            lines.append("  Called by:")
            for r in called_by[:max_relations_per_match]:
                lines.append(f"    ← {r.source}")
            if len(called_by) > max_relations_per_match:
                lines.append(f"    ... {len(called_by) - max_relations_per_match} more ...")
        if not calls_out and not called_by:
            lines.append("  (no call relationships found)")
        lines.append("")
    return _truncate_text("\n".join(lines))


# --- Tool: inheritance tree -----------------------------------------------


@mcp.tool()
def inheritance_tree(
    class_name: str,
    max_matches: int = _DEFAULT_MATCH_LIMIT,
    max_relations_per_match: int = _DEFAULT_RELATION_LIMIT,
) -> str:
    """Show the inheritance hierarchy for a class.

    Args:
        class_name: Name (or partial name) of the class to inspect.
    """
    kg = _get_kg()
    classes = kg.find_entities(name=class_name, entity_type=CodeEntityType.CLASS)
    if not classes:
        return f"No class found matching '{class_name}'."

    shown_classes = classes[:max_matches]
    lines: list[str] = [_summarize_matches(len(classes), len(shown_classes), "matching classes"), ""]
    for cls in shown_classes:
        lines.append(f"### {cls.name} — {cls.file_path}:{cls.line_start}")
        inherits = [
            r for r in kg.relations
            if r.source == cls.qualified_key and r.relation_type.value == "INHERITS"
        ]
        inherited_by = [
            r for r in kg.relations
            if r.target == cls.qualified_key and r.relation_type.value == "INHERITS"
        ]
        if inherits:
            lines.append("  Inherits from:")
            for r in inherits[:max_relations_per_match]:
                lines.append(f"    ↑ {r.target}")
            if len(inherits) > max_relations_per_match:
                lines.append(f"    ... {len(inherits) - max_relations_per_match} more ...")
        if inherited_by:
            lines.append("  Inherited by:")
            for r in inherited_by[:max_relations_per_match]:
                lines.append(f"    ↓ {r.source}")
            if len(inherited_by) > max_relations_per_match:
                lines.append(f"    ... {len(inherited_by) - max_relations_per_match} more ...")
        if not inherits and not inherited_by:
            lines.append("  (no inheritance relationships found)")
        lines.append("")
    return _truncate_text("\n".join(lines))


# --- Tool: graph stats ----------------------------------------------------


@mcp.tool()
def graph_stats() -> str:
    """Return summary statistics about the indexed code knowledge graph."""
    kg = _get_kg()
    type_counts: dict[str, int] = {}
    for ent in kg.entities:
        key = ent.entity_type.value
        type_counts[key] = type_counts.get(key, 0) + 1
    lines = [
        f"Active project: {_active_project}",
        f"Total entities: {len(kg.entities)}",
        f"Total relations: {len(kg.relations)}",
        "",
        "Entity types:",
    ]
    for etype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {etype}: {count}")

    # Count relation types
    rel_counts: dict[str, int] = {}
    for r in kg.relations:
        rt = r.relation_type.value if hasattr(r.relation_type, "value") else str(r.relation_type)
        rel_counts[rt] = rel_counts.get(rt, 0) + 1
    lines.append("\nRelation types:")
    for rtype, count in sorted(rel_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {rtype}: {count}")
    return "\n".join(lines)


# --- Tool: reindex --------------------------------------------------------


@mcp.tool()
def reindex_repo(repo_path: str = "") -> str:
    """Re-index the current active project and rebuild its knowledge graph.

    Args:
        repo_path: Path to the repo root. Uses configured repo root if empty.
    """
    global _kg, _retriever, _embedder_loaded
    root = Path(repo_path).resolve() if repo_path else _projects_cfg.get_repo_root()

    scope = _projects_cfg.projects.get(_active_project)
    scope_paths = _projects_cfg.resolve_paths(_active_project) if scope else None

    _kg = index_repo(root, show_progress=False, scope_paths=scope_paths)
    save_graph(_kg, _cache_path_for(_active_project))

    # Reset the retriever so it picks up the new graph
    _retriever = None
    _embedder_loaded = False
    return (
        f"Re-indexed project '{_active_project}'. "
        f"{len(_kg.entities)} entities, {len(_kg.relations)} relations."
    )


# --- Tool: list projects --------------------------------------------------


@mcp.tool()
def list_projects() -> str:
    """List all configured project scopes from MCP config or projects.json fallback.

    Shows each project name, description, paths, and whether a cached index
    exists.  The currently active project is marked with *.
    """
    cfg = ProjectsConfig.load()  # re-read in case file was edited
    if not cfg.projects:
        return "No projects configured. Supply MCP env config or add projects.json."
    lines: list[str] = [f"Repo root: {cfg.get_repo_root()}\n"]
    for name, scope in cfg.projects.items():
        marker = " *" if name == _active_project else ""
        cached = "cached" if cfg.graph_cache_path(name).exists() else "not cached"
        lines.append(f"- {name}{marker}  ({cached})")
        if scope.description:
            lines.append(f"    {scope.description}")
        lines.append(f"    paths: {', '.join(scope.paths)}")
    return "\n".join(lines)


# --- Tool: switch project -------------------------------------------------


@mcp.tool()
def switch_project(project_name: str) -> str:
    """Switch the active project scope and load its knowledge graph.

    If the project has not been indexed yet, it will be indexed on the fly.

    Args:
        project_name: Name of a project from MCP config or projects.json.
    """
    global _kg, _retriever, _embedder_loaded, _active_project, _projects_cfg
    _projects_cfg = ProjectsConfig.load()  # re-read

    if project_name not in _projects_cfg.projects:
        available = ", ".join(_projects_cfg.list_project_names())
        return f"Unknown project '{project_name}'. Available: {available}"

    _retriever = None
    _embedder_loaded = False
    _kg = None

    _load_graph(project_name)
    return (
        f"Switched to project '{project_name}'. "
        f"{len(_kg.entities)} entities, {len(_kg.relations)} relations."
    )


# --- Tool: index project --------------------------------------------------


@mcp.tool()
def index_project(project_name: str) -> str:
    """Index (or re-index) a specific project scope and cache the result.

    Args:
        project_name: Name of a project from MCP config or projects.json.
    """
    global _kg, _retriever, _embedder_loaded, _active_project, _projects_cfg
    _projects_cfg = ProjectsConfig.load()

    if project_name not in _projects_cfg.projects:
        available = ", ".join(_projects_cfg.list_project_names())
        return f"Unknown project '{project_name}'. Available: {available}"

    root = _projects_cfg.get_repo_root()
    scope_paths = _projects_cfg.resolve_paths(project_name)

    print(f"[kg-mcp] Indexing project '{project_name}' ...", file=sys.stderr)
    kg = index_repo(root, show_progress=False, scope_paths=scope_paths)
    cache = _cache_path_for(project_name)
    save_graph(kg, cache)

    # If this is the active project, reload it
    if project_name == _active_project:
        _kg = kg
        _retriever = None
        _embedder_loaded = False

    return (
        f"Indexed project '{project_name}': "
        f"{len(kg.entities)} entities, {len(kg.relations)} relations. "
        f"Cached to {cache}."
    )


# --- Tool: code ownership -------------------------------------------------


@mcp.tool()
def code_ownership(file_path: str) -> str:
    """Show who most frequently modifies a file, ranked by commit count.

    Args:
        file_path: Relative path of the file inside the repo.
    """
    kg = _get_kg()
    mods = [
        r for r in kg.relations
        if r.source == file_path
        and r.relation_type.value == "MODIFIED_BY"
    ]
    if not mods:
        return f"No ownership data for '{file_path}'. Run indexing with --git to include git history."
    # Sort by commit count descending
    mods.sort(
        key=lambda r: int(r.metadata.get("commit_count", "0")),
        reverse=True,
    )
    lines = [f"Ownership for {file_path}:\n"]
    for r in mods:
        email = r.metadata.get("email", "?")
        count = r.metadata.get("commit_count", "?")
        lines.append(f"  {email}: {count} commits")
    return "\n".join(lines)


# --- Tool: change coupling ------------------------------------------------


@mcp.tool()
def change_coupling(file_path: str, min_count: int = 3) -> str:
    """Show files that frequently change together with a given file.

    Args:
        file_path: Relative path of the file inside the repo.
        min_count: Minimum co-change count to include (default 3).
    """
    kg = _get_kg()
    # CO_CHANGED edges go both directions
    coupled: list[tuple[str, int]] = []
    for r in kg.relations:
        if r.relation_type.value != "CO_CHANGED":
            continue
        cnt = int(r.metadata.get("co_change_count", "0"))
        if cnt < min_count:
            continue
        if r.source == file_path:
            coupled.append((r.target, cnt))
        elif r.target == file_path:
            coupled.append((r.source, cnt))
    if not coupled:
        return f"No co-change data for '{file_path}'. Run indexing with --git to include git history."
    coupled.sort(key=lambda x: x[1], reverse=True)
    lines = [f"Files that frequently change with {file_path}:\n"]
    for partner, cnt in coupled[:20]:
        lines.append(f"  {partner}: {cnt} co-changes")
    return "\n".join(lines)


# --- Tool: hot spots -------------------------------------------------------


@mcp.tool()
def hot_spots(top_n: int = 20) -> str:
    """Show files with the highest commit churn (most COMMITTED_IN relations).

    High-churn files are potential complexity or risk hotspots.

    Args:
        top_n: Number of results to return (default 20).
    """
    kg = _get_kg()
    from collections import Counter
    file_counts: Counter[str] = Counter()
    for r in kg.relations:
        if r.relation_type.value == "COMMITTED_IN":
            file_counts[r.source] += 1
    if not file_counts:
        return "No commit history data. Run indexing with --git to include git history."
    lines = [f"Top {top_n} hot spots (files by commit count):\n"]
    for fpath, cnt in file_counts.most_common(top_n):
        lines.append(f"  {fpath}: {cnt} commits")
    return "\n".join(lines)


# --- Tool: work items for code --------------------------------------------


@mcp.tool()
def work_items_for_code(file_path: str) -> str:
    """Find work items (user stories / bugs) linked to a file via git history.

    Follows the chain: file → COMMITTED_IN → commit → LINKED_TO → work_item.

    Args:
        file_path: Relative path of the file inside the repo.
    """
    kg = _get_kg()
    # Find commits that touched this file
    commit_keys = [
        r.target
        for r in kg.relations
        if r.source == file_path and r.relation_type.value == "COMMITTED_IN"
    ]
    if not commit_keys:
        return f"No commit data for '{file_path}'."

    # Find work items linked from those commits
    wi_map: dict[str, list[str]] = {}  # wid → list of commit shas
    for r in kg.relations:
        if r.relation_type.value == "LINKED_TO" and r.source in commit_keys:
            wid = r.metadata.get("work_item_id", "?")
            wi_map.setdefault(wid, []).append(r.source)

    if not wi_map:
        return f"No work items linked to '{file_path}' via commit messages."

    # Try to include hydrated details
    kg_wi = {e.metadata.get("id", ""): e for e in kg.entities if e.entity_type.value == "work_item"}

    lines = [f"Work items linked to {file_path}:\n"]
    for wid, commits in sorted(wi_map.items()):
        wi_ent = kg_wi.get(wid)
        if wi_ent and wi_ent.metadata.get("title"):
            wi_type = wi_ent.metadata.get("work_item_type", "")
            title = wi_ent.metadata["title"]
            state = wi_ent.metadata.get("state", "")
            lines.append(f"  #{wid} [{wi_type}] {title} ({state}) — {len(commits)} commit(s)")
        else:
            lines.append(f"  #{wid} — {len(commits)} commit(s)")
    return "\n".join(lines)


# --- Tool: code for work item ---------------------------------------------


@mcp.tool()
def code_for_work_item(work_item_id: str) -> str:
    """Find all files changed for a given work item ID.

    Follows: work_item ← LINKED_TO ← commit → COMMITTED_IN → file.

    Args:
        work_item_id: The numeric work item ID (e.g. "111863").
    """
    kg = _get_kg()
    wid = work_item_id.lstrip("#")

    # Find commits linked to this work item
    commit_keys = [
        r.source
        for r in kg.relations
        if r.relation_type.value == "LINKED_TO"
        and r.metadata.get("work_item_id") == wid
    ]
    if not commit_keys:
        return f"No commits found linked to work item #{wid}."

    # Get commit messages for context
    commit_entities = {
        e.qualified_key: e
        for e in kg.entities
        if e.entity_type.value == "commit"
    }

    # Find files from those commits
    from collections import Counter
    file_counts: Counter[str] = Counter()
    for r in kg.relations:
        if r.relation_type.value == "COMMITTED_IN" and r.target in commit_keys:
            file_counts[r.source] += 1

    if not file_counts:
        return f"No files found for work item #{wid}."

    lines = [f"Files changed for work item #{wid} ({len(commit_keys)} commits):\n"]
    for fpath, cnt in file_counts.most_common():
        lines.append(f"  {fpath} ({cnt} commits)")

    # Show commit messages for context
    lines.append(f"\nCommit messages:")
    for ck in commit_keys[:10]:
        ce = commit_entities.get(ck)
        if ce:
            msg = ce.metadata.get("message", "")
            sha = ce.metadata.get("sha", "")[:8]
            lines.append(f"  {sha}: {msg}")

    return "\n".join(lines)


# --- Tool: work item details -----------------------------------------------


@mcp.tool()
def work_item_details(work_item_id: str) -> str:
    """Show full details of a work item (title, type, state, description, tags).

    Requires the graph to have been indexed with --git --ado flags.

    Args:
        work_item_id: The numeric work item ID (e.g. "111863").
    """
    kg = _get_kg()
    wid = work_item_id.lstrip("#")

    wi_ent = next(
        (e for e in kg.entities
         if e.entity_type.value == "work_item" and e.metadata.get("id") == wid),
        None,
    )
    if wi_ent is None:
        return f"Work item #{wid} not found in the graph."

    meta = wi_ent.metadata
    title = meta.get("title", "(not hydrated)")
    wi_type = meta.get("work_item_type", "?")
    state = meta.get("state", "?")
    tags = meta.get("tags", "")
    area = meta.get("area_path", "")
    desc = meta.get("description", "")

    lines = [
        f"Work Item #{wid}",
        f"  Type: {wi_type}",
        f"  Title: {title}",
        f"  State: {state}",
    ]
    if tags:
        lines.append(f"  Tags: {tags}")
    if area:
        lines.append(f"  Area Path: {area}")
    if desc:
        lines.append(f"  Description: {desc[:500]}")

    return "\n".join(lines)


# --- Tool: blame context --------------------------------------------------


@mcp.tool()
def blame_context(file_path: str) -> str:
    """Provide a rich "why/who/when" summary for a file.

    Combines ownership, co-change, and work-item data into one view.

    Args:
        file_path: Relative path of the file inside the repo.
    """
    parts = [f"=== Blame context for {file_path} ===\n"]

    parts.append(code_ownership(file_path))
    parts.append("")
    parts.append(change_coupling(file_path))
    parts.append("")
    parts.append(work_items_for_code(file_path))

    return "\n".join(parts)


# ======================================================================
# Entry-point
# ======================================================================


def main() -> None:
    """Run the MCP server on stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
