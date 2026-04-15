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
# Singleton graph state — eagerly loaded at import time so MCP tool
# calls don't block for 15+ seconds on first invocation.
# ======================================================================

_kg: KnowledgeGraph | None = None
_retriever: GraphRetriever | None = None
_embedder_loaded = False
_active_project: str = settings.ACTIVE_PROJECT
_projects_cfg: ProjectsConfig = ProjectsConfig.load()


def _cache_path_for(project: str) -> Path:
    """Return the pickle cache path for a project name."""
    if _projects_cfg.projects:
        return _projects_cfg.graph_cache_path(project)
    return settings.GRAPH_CACHE_PATH


def _load_graph(project: str | None = None) -> KnowledgeGraph:
    """Load (or build) the graph for a project. Called once at startup."""
    global _kg, _active_project
    project = project or _active_project

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


# --- Eager startup load (graph + embedding model) ---------------------
_load_graph()
_ensure_retriever()


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
def search_code(query: str, top_k: int = 10) -> str:
    """Semantic search over the code knowledge graph.

    Finds entities (classes, functions, methods, …) whose names, signatures or
    docstrings are most similar to the natural-language *query*.

    Args:
        query: Natural-language description of what you're looking for.
        top_k: Number of results to return (default 10).
    """
    retriever = _ensure_retriever()
    ctx = retriever.retrieve(query)
    return ctx.subgraph_text


# --- Tool: lookup by name ------------------------------------------------


@mcp.tool()
def lookup_symbol(name: str) -> str:
    """Find code entities whose name contains *name* and return their neighbourhood.

    Args:
        name: Partial or full symbol name to search for (case-insensitive).
    """
    kg = _get_kg()
    matches = kg.find_entities(name=name)
    if not matches:
        return f"No entities found matching '{name}'."
    lines: list[str] = []
    for ent in matches:
        loc = f" ({ent.file_path}:{ent.line_start})" if ent.file_path else ""
        sig = f" — {ent.signature}" if ent.signature else ""
        lines.append(f"- [{ent.entity_type.value}] {ent.name}{loc}{sig}")
        # Show immediate relations
        for rel in kg.relations:
            if rel.source == ent.qualified_key:
                lines.append(f"    --[{rel.relation_type.value}]--> {rel.target}")
            elif rel.target == ent.qualified_key:
                lines.append(f"    <--[{rel.relation_type.value}]-- {rel.source}")
    return "\n".join(lines)


# --- Tool: file overview --------------------------------------------------


@mcp.tool()
def file_overview(file_path: str) -> str:
    """List all code entities defined in a specific file.

    Args:
        file_path: Relative path of the file inside the repo (e.g. "src/utils.py").
    """
    kg = _get_kg()
    matches = kg.find_entities(file_path=file_path)
    if not matches:
        return f"No entities found in '{file_path}'."
    lines = [f"File: {file_path} — {len(matches)} entities\n"]
    for ent in matches:
        sig = f" — {ent.signature}" if ent.signature else ""
        lines.append(f"- [{ent.entity_type.value}] {ent.name} (L{ent.line_start}){sig}")
    return "\n".join(lines)


# --- Tool: list classes ---------------------------------------------------


@mcp.tool()
def list_classes(name_filter: str = "") -> str:
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
    lines = [f"Found {len(classes)} class(es):\n"]
    for c in classes:
        loc = f"  ({c.file_path}:{c.line_start})" if c.file_path else ""
        lines.append(f"- {c.name}{loc}")
        if c.signature:
            lines.append(f"  {c.signature}")
    return "\n".join(lines)


# --- Tool: list functions -------------------------------------------------


@mcp.tool()
def list_functions(name_filter: str = "") -> str:
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
    lines = [f"Found {len(funcs)} function(s):\n"]
    for f in funcs:
        loc = f"  ({f.file_path}:{f.line_start})" if f.file_path else ""
        lines.append(f"- {f.name}{loc}")
        if f.signature:
            lines.append(f"  {f.signature}")
    return "\n".join(lines)


# --- Tool: call graph -----------------------------------------------------


@mcp.tool()
def call_graph(function_name: str) -> str:
    """Show what a function/method calls and what calls it.

    Args:
        function_name: Name (or partial name) of the function to inspect.
    """
    kg = _get_kg()
    # Find matching entities
    funcs = kg.find_entities(name=function_name)
    if not funcs:
        return f"No entity found matching '{function_name}'."

    lines: list[str] = []
    for func in funcs:
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
            for r in calls_out:
                lines.append(f"    → {r.target}")
        if called_by:
            lines.append("  Called by:")
            for r in called_by:
                lines.append(f"    ← {r.source}")
        if not calls_out and not called_by:
            lines.append("  (no call relationships found)")
        lines.append("")
    return "\n".join(lines)


# --- Tool: inheritance tree -----------------------------------------------


@mcp.tool()
def inheritance_tree(class_name: str) -> str:
    """Show the inheritance hierarchy for a class.

    Args:
        class_name: Name (or partial name) of the class to inspect.
    """
    kg = _get_kg()
    classes = kg.find_entities(name=class_name, entity_type=CodeEntityType.CLASS)
    if not classes:
        return f"No class found matching '{class_name}'."

    lines: list[str] = []
    for cls in classes:
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
            for r in inherits:
                lines.append(f"    ↑ {r.target}")
        if inherited_by:
            lines.append("  Inherited by:")
            for r in inherited_by:
                lines.append(f"    ↓ {r.source}")
        if not inherits and not inherited_by:
            lines.append("  (no inheritance relationships found)")
        lines.append("")
    return "\n".join(lines)


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
    """List all configured project scopes from projects.json.

    Shows each project name, description, paths, and whether a cached index
    exists.  The currently active project is marked with *.
    """
    cfg = ProjectsConfig.load()  # re-read in case file was edited
    if not cfg.projects:
        return "No projects configured. Edit projects.json to add scopes."
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
        project_name: Name of a project defined in projects.json.
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
        project_name: Name of a project defined in projects.json.
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


# ======================================================================
# Entry-point
# ======================================================================


def main() -> None:
    """Run the MCP server on stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
