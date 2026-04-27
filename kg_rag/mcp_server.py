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
from kg_rag.indexer import (
    index_repo,
    list_indexed_projects,
    load_graph,
    load_graph_with_metadata,
    save_graph,
)
from kg_rag.models import CodeEntityType, Entity, GraphMetadata, KnowledgeGraph
from kg_rag.projects import ProjectsConfig
from kg_rag.retriever import GraphRetriever

logger = logging.getLogger(__name__)

# ======================================================================
# Singleton graph state for the active MCP project.
# ======================================================================

_kg: KnowledgeGraph | None = None
_metadata: GraphMetadata | None = None
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
    global _kg, _metadata, _active_project
    project = _projects_cfg.default_project_name(project or _active_project)

    if _kg is not None and project == _active_project:
        return _kg

    cache = _cache_path_for(project)
    if cache.exists():
        print(f"[kg-mcp] Loading '{project}' graph from {cache} ...", file=sys.stderr)
        _kg, _metadata = load_graph_with_metadata(cache)
    else:
        # Try to build the project scope
        repo_root = _projects_cfg.get_repo_root()
        scope = _projects_cfg.projects.get(project)
        scope_paths = _projects_cfg.resolve_paths(project) if scope else None
        print(f"[kg-mcp] No cache – indexing project '{project}' ...", file=sys.stderr)
        _kg = index_repo(repo_root, show_progress=True, scope_paths=scope_paths)
        
        # Track git/ado flags for metadata
        has_git = False
        has_workitems = False
        
        # Add git history (enabled by default, can opt-out via env)
        enable_git = settings.REPO_ROOT.exists()  # Only if in a git repo
        if enable_git:
            try:
                from kg_rag.git_history import build_git_history_graph, merge_git_layer
                print("[kg-mcp] Extracting git history ...", file=sys.stderr)
                git_kg = build_git_history_graph(
                    repo_root=repo_root,
                    scope_paths=scope_paths,
                    since="4 years ago",
                    index_extensions=settings.INDEX_EXTENSIONS,
                )
                merge_git_layer(_kg, git_kg)
                print(f"[kg-mcp] Git layer: {len(git_kg.entities)} entities, {len(git_kg.relations)} relations", file=sys.stderr)
                has_git = True
            except Exception as e:
                print(f"[kg-mcp] Warning: Git history extraction failed: {e}", file=sys.stderr)
        
        # Hydrate work items if ADO credentials are available
        if settings.ADO_ORG and settings.ADO_PAT:
            try:
                from kg_rag.workitems import hydrate_work_items
                print("[kg-mcp] Hydrating work items from Azure DevOps ...", file=sys.stderr)
                count = hydrate_work_items(_kg)
                print(f"[kg-mcp] Hydrated {count} work item(s)", file=sys.stderr)
                has_workitems = count > 0
            except Exception as e:
                print(f"[kg-mcp] Warning: Work item hydration failed: {e}", file=sys.stderr)
        
        # Create metadata for this index
        _metadata = GraphMetadata(
            project_name=project,
            repo_root=str(repo_root),
            scope_paths=[str(p.relative_to(repo_root)) for p in scope_paths] if scope_paths else ["."],
            has_git_history=has_git,
            has_work_items=has_workitems,
            git_since="4 years ago" if has_git else "",
        )
        save_graph(_kg, cache, metadata=_metadata)

    _active_project = project
    print(
        f"[kg-mcp] Graph ready ({project}): {len(_kg.entities)} entities, "
        f"{len(_kg.relations)} relations",
        file=sys.stderr,
    )
    if _metadata:
        print(f"[kg-mcp] Indexed: {_metadata.indexed_at}", file=sys.stderr)
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
    """Lazily create the retriever (loads embedding model on first call).
    
    Note: This may take 30-60 seconds on first run to download the model from HuggingFace.
    """
    global _retriever, _embedder_loaded
    if _retriever is not None:
        return _retriever

    kg = _load_graph()
    print("[kg-mcp] Loading embedding model (this may take 30-60 seconds on first run)...", file=sys.stderr)
    from kg_rag.embeddings import KGEmbedder

    embedder = KGEmbedder()
    
    # Try to load cached embeddings
    cache_dir = _cache_path_for(_active_project).parent
    embeddings_cache = cache_dir / f"{_active_project}_embeddings.pkl"
    
    cache_loaded = embedder.load_cache(embeddings_cache)
    
    # Pre-compute embeddings if not cached or if explicitly requested
    import os
    if os.getenv("KG_PRELOAD_EMBEDDINGS", "").strip().lower() in ("1", "true", "yes"):
        if cache_loaded:
            print(f"[kg-mcp] Embeddings cache loaded from disk ({len(embedder._cache)} entities).", file=sys.stderr)
        else:
            # Determine which entity types to skip
            # Use aggressive filtering for huge codebases (skip methods too, keep only classes/functions)
            if os.getenv("KG_AGGRESSIVE_EMBEDDING", "").strip().lower() in ("1", "true", "yes"):
                skip_types = {'file', 'import', 'variable', 'method', 'property', 'field', 'enum', 'struct'}
                filtering_mode = "aggressive (classes/functions/namespaces only)"
            else:
                skip_types = {'file', 'import', 'variable'}
                filtering_mode = "standard"
            
            # Count entities that will be embedded
            embed_count = sum(1 for e in kg.entities if e.entity_type.value not in skip_types)
            print(
                f"[kg-mcp] Pre-computing embeddings for {embed_count:,} entities "
                f"(skipping {len(kg.entities) - embed_count:,} low-value entities, mode: {filtering_mode})...",
                file=sys.stderr,
            )
            print(f"[kg-mcp] This will take approximately {embed_count // 1000} seconds (batch size: 500).", file=sys.stderr)
            embedder.embed_graph(kg, skip_entity_types=skip_types, batch_size=500, show_progress=True)
            embedder.save_cache(embeddings_cache)
            print("[kg-mcp] All embeddings pre-computed and cached to disk.", file=sys.stderr)
    elif not cache_loaded:
        print("[kg-mcp] Embeddings will be computed on-demand (first search may be slow).", file=sys.stderr)
        print("[kg-mcp] Set KG_PRELOAD_EMBEDDINGS=true to pre-compute all embeddings at startup.", file=sys.stderr)
    
    _retriever = GraphRetriever(kg=kg, embedder=embedder)
    _embedder_loaded = True
    print("[kg-mcp] Embedder ready. Semantic search is now available.", file=sys.stderr)
    return _retriever


def _get_kg() -> KnowledgeGraph:
    """Return the graph (already loaded at startup)."""
    if _kg is None:
        _load_graph()
    assert _kg is not None
    return _kg


def _resolve_file_path(file_path: str, kg: KnowledgeGraph) -> str | None:
    """Resolve a file path to an exact match in the graph.
    
    Tries:
    1. Exact match (user provided full path relative to repo root)
    2. Suffix match (user provided path relative to scope folder)
    
    Returns the canonical path from the graph, or None if not found.
    Raises ValueError if multiple matches are found (ambiguous).
    """
    # Normalize to forward slashes
    file_path = file_path.replace("\\", "/")
    
    # Try exact match first
    file_entities = [e for e in kg.entities if e.entity_type.value == "file" and e.file_path == file_path]
    if file_entities:
        return file_path
    
    # Try suffix match (e.g., user provided "src/File.cs" but graph has "BladedX/Workflow/src/File.cs")
    matches = [
        e.file_path for e in kg.entities 
        if e.entity_type.value == "file" and e.file_path and e.file_path.endswith("/" + file_path)
    ]
    
    if not matches:
        return None
    
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous path '{file_path}' matches multiple files:\n" + 
            "\n".join(f"  - {m}" for m in matches[:10]) +
            f"\n... ({len(matches)} total). Please provide a more specific path."
        )
    
    return matches[0]


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


# --- Tool: keyword search (fast) -----------------------------------------


@mcp.tool()
def search_keywords(query: str, max_results: int = 50) -> str:
    """Fast keyword-based search across entity names, signatures, and docstrings.

    Use this for quick searches when you know specific keywords or names.
    For semantic/conceptual searches, use search_code instead (slower but smarter).

    Args:
        query: Keywords to search for (space-separated, case-insensitive).
        max_results: Maximum number of results (default 50).
    """
    kg = _get_kg()
    keywords = query.lower().split()
    
    matches: list[tuple[Entity, int]] = []
    for ent in kg.entities:
        score = 0
        searchable = (
            f"{ent.name} {ent.signature or ''} {ent.docstring or ''} "
            f"{ent.file_path or ''}"
        ).lower()
        
        for kw in keywords:
            if kw in searchable:
                score += searchable.count(kw)
        
        if score > 0:
            matches.append((ent, score))
    
    if not matches:
        return f"No entities found matching keywords: {query}"
    
    matches.sort(key=lambda x: x[1], reverse=True)
    shown = matches[:max_results]
    
    lines = [
        f"Found {len(matches)} entities matching keywords: {query}",
        f"Showing top {len(shown)} by relevance:\n",
    ]
    
    for ent, score in shown:
        loc = f" ({ent.file_path}:{ent.line_start})" if ent.file_path else ""
        sig = f" — {ent.signature[:80]}" if ent.signature else ""
        lines.append(f"[{ent.entity_type.value}] {ent.name}{loc}{sig}")
    
    return _truncate_text("\n".join(lines))


# --- Tool: semantic search (slower, uses embeddings) ----------------------


@mcp.tool()
def search_code(query: str, top_k: int = 10, max_chars: int = _DEFAULT_TEXT_LIMIT) -> str:
    """Semantic search over the code knowledge graph using AI embeddings.

    Finds entities (classes, functions, methods, …) whose names, signatures or
    docstrings are most similar to the natural-language *query*.

    NOTE: First call may take 30-60 seconds to load the embedding model.
    For faster keyword-based search, use search_keywords instead.

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

    rel_counts: dict[str, int] = {}
    for rel in kg.relations:
        key = rel.relation_type.value if hasattr(rel.relation_type, "value") else str(rel.relation_type)
        rel_counts[key] = rel_counts.get(key, 0) + 1

    commit_count = type_counts.get(CodeEntityType.COMMIT.value, 0)
    author_count = type_counts.get(CodeEntityType.AUTHOR.value, 0)
    work_item_count = type_counts.get(CodeEntityType.WORK_ITEM.value, 0)
    committed_in_count = rel_counts.get("COMMITTED_IN", 0)
    modified_by_count = rel_counts.get("MODIFIED_BY", 0)
    co_changed_count = rel_counts.get("CO_CHANGED", 0)
    linked_to_count = rel_counts.get("LINKED_TO", 0)

    has_git_history = (
        (_metadata.has_git_history if _metadata is not None else False)
        or commit_count > 0
        or author_count > 0
        or committed_in_count > 0
        or modified_by_count > 0
        or co_changed_count > 0
    )
    has_work_items = (
        (_metadata.has_work_items if _metadata is not None else False)
        or work_item_count > 0
        or linked_to_count > 0
    )
    git_window = _metadata.git_since if _metadata and _metadata.git_since else ""
    git_status = "yes"
    if git_window:
        git_status += f" (since {git_window})"
    if not has_git_history:
        git_status = "no"

    lines = [
        f"Active project: {_active_project}",
        f"Total entities: {len(kg.entities)}",
        f"Total relations: {len(kg.relations)}",
        "",
        "Historical changes:",
        f"  Indexed: {git_status}",
        f"  Commits: {commit_count}",
        f"  Authors: {author_count}",
        f"  File change links: {committed_in_count}",
        f"  Ownership links: {modified_by_count}",
        f"  Co-change links: {co_changed_count}",
        "",
        "Work items:",
        f"  Indexed: {'yes' if has_work_items else 'no'}",
        f"  Work item entities: {work_item_count}",
        f"  Commit links: {linked_to_count}",
        "",
        "Entity types:",
    ]
    for etype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {etype}: {count}")

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
    global _kg, _metadata, _retriever, _embedder_loaded
    root = Path(repo_path).resolve() if repo_path else _projects_cfg.get_repo_root()

    scope = _projects_cfg.projects.get(_active_project)
    scope_paths = _projects_cfg.resolve_paths(_active_project) if scope else None

    _kg = index_repo(root, show_progress=False, scope_paths=scope_paths)
    
    # Create metadata
    _metadata = GraphMetadata(
        project_name=_active_project,
        repo_root=str(root),
        scope_paths=[str(p.relative_to(root)) for p in scope_paths] if scope_paths else ["."],
    )
    save_graph(_kg, _cache_path_for(_active_project), metadata=_metadata)

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
    lines: list[str] = []
    
    if cfg.projects:
        lines.append(f"📁 Configured projects (repo root: {cfg.get_repo_root()})\n")
        for name, scope in cfg.projects.items():
            marker = " *" if name == _active_project else ""
            cached = "cached" if cfg.graph_cache_path(name).exists() else "not cached"
            lines.append(f"- {name}{marker}  ({cached})")
            if scope.description:
                lines.append(f"    {scope.description}")
            lines.append(f"    paths: {', '.join(scope.paths)}")
    else:
        lines.append("No projects configured. Supply MCP env config or add projects.json.")
    
    # Also show indexed projects from registry
    indexed = list_indexed_projects()
    if indexed:
        lines.append(f"\n📊 Indexed graphs in registry ({len(indexed)}):")
        for info in indexed:
            marker = " *" if info.get('project_name') == _active_project else ""
            lines.append(f"\n- {info['project_name'] or '(unnamed)'}{marker}")
            lines.append(f"    Entities: {info['entity_count']}, Relations: {info['relation_count']}")
            lines.append(f"    Indexed: {info['indexed_at']}")
            if info.get('has_git_history'):
                lines.append(f"    Git history: ✓")
            if info.get('has_work_items'):
                lines.append(f"    Work items: ✓")
            if info['scope_paths']:
                lines.append(f"    Scope: {', '.join(info['scope_paths'])}")
    
    return "\n".join(lines)


# --- Tool: switch project -------------------------------------------------


@mcp.tool()
def switch_project(project_name: str) -> str:
    """Switch the active project scope and load its knowledge graph.

    If the project has not been indexed yet, it will be indexed on the fly.

    Args:
        project_name: Name of a project from MCP config or projects.json.
    """
    global _kg, _metadata, _retriever, _embedder_loaded, _active_project, _projects_cfg
    _projects_cfg = ProjectsConfig.load()  # re-read

    if project_name not in _projects_cfg.projects:
        available = ", ".join(_projects_cfg.list_project_names())
        return f"Unknown project '{project_name}'. Available: {available}"

    _retriever = None
    _embedder_loaded = False
    _kg = None
    _metadata = None

    _load_graph(project_name)
    result = (
        f"Switched to project '{project_name}'. "
        f"{len(_kg.entities)} entities, {len(_kg.relations)} relations."
    )
    if _metadata and _metadata.indexed_at:
        result += f"\nIndexed: {_metadata.indexed_at}"
    return result


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
    
    # Create metadata for this index
    from kg_rag.models import GraphMetadata
    metadata = GraphMetadata(
        project_name=project_name,
        repo_root=str(root),
        scope_paths=[str(p.relative_to(root)) for p in scope_paths] if scope_paths else ["."],
    )

    kg = index_repo(root, show_progress=False, scope_paths=scope_paths)
    cache = _cache_path_for(project_name)
    save_graph(kg, cache, metadata=metadata)

    # If this is the active project, reload it
    if project_name == _active_project:
        global _kg, _metadata, _retriever, _embedder_loaded
        _kg = kg
        _metadata = metadata
        _retriever = None
        _embedder_loaded = False

    return (
        f"Indexed project '{project_name}'. "
        f"{len(kg.entities)} entities, {len(kg.relations)} relations. "
        f"Cached to {cache}"
    )

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

# --- Tool: get project metadata --------------------------------------------


@mcp.tool()
def get_project_metadata() -> str:
    """Get detailed metadata about the currently active project.
    
    Returns information about when it was indexed, what paths were included,
    whether git history and work items were indexed, etc.
    """
    if _metadata is None:
        return f"No metadata available for project '{_active_project}'."
    
    lines = [
        f"📊 Project Metadata: {_metadata.project_name or _active_project}",
        "",
        f"Repository: {_metadata.repo_root}",
        f"Indexed at: {_metadata.indexed_at or 'unknown'}",
        f"Entities: {_metadata.entity_count}",
        f"Relations: {_metadata.relation_count}",
        "",
        f"Scope paths:",
    ]
    for p in _metadata.scope_paths:
        lines.append(f"  - {p}")
    
    if _metadata.extensions:
        lines.append(f"\nFile extensions: {', '.join(_metadata.extensions)}")
    
    features = []
    if _metadata.has_git_history:
        git_info = f"Git history (since {_metadata.git_since})" if _metadata.git_since else "Git history"
        features.append(git_info)
    if _metadata.has_work_items:
        features.append("Work items from ADO")
    
    if features:
        lines.append(f"\nFeatures: {', '.join(features)}")
    
    return "\n".join(lines)


@mcp.tool()
def get_indexed_project_info(project_name: str) -> str:
    """Get detailed information about any indexed project from the registry.
    
    Args:
        project_name: Name of the project to query (can be partial match).
    """
    indexed = list_indexed_projects()
    if not indexed:
        return "No indexed projects found in the registry."
    
    # Find matching projects (partial name match)
    name_lower = project_name.lower()
    matches = [
        p for p in indexed 
        if name_lower in (p.get('project_name') or '').lower()
    ]
    
    if not matches:
        all_names = [p.get('project_name', '(unnamed)') for p in indexed]
        return f"No projects matching '{project_name}'. Available: {', '.join(all_names)}"
    
    if len(matches) > 1:
        names = [p.get('project_name', '(unnamed)') for p in matches]
        return f"Multiple matches found: {', '.join(names)}. Please be more specific."
    
    info = matches[0]
    lines = [
        f"📊 Project: {info.get('project_name') or '(unnamed)'}",
        "",
        f"Repository: {info['repo_root']}",
        f"Indexed at: {info['indexed_at']}",
        f"Entities: {info['entity_count']}",
        f"Relations: {info['relation_count']}",
        "",
        f"Graph file: {info['graph_path']}",
    ]
    
    if info.get('scope_paths'):
        lines.append("\nScope paths:")
        for p in info['scope_paths']:
            lines.append(f"  - {p}")
    
    features = []
    if info.get('has_git_history'):
        features.append("Git history")
    if info.get('has_work_items'):
        features.append("Work items")
    
    if features:
        lines.append(f"\nFeatures: {', '.join(features)}")
    
    return "\n".join(lines)

# --- Tool: code ownership -------------------------------------------------


@mcp.tool()
def code_ownership(file_path: str) -> str:
    """Show who most frequently modifies a file, ranked by commit count.

    Args:
        file_path: Relative path of the file inside the repo.
    """
    kg = _get_kg()
    
    # Resolve the file path (handles both exact and suffix matches)
    try:
        resolved_path = _resolve_file_path(file_path, kg)
    except ValueError as e:
        return str(e)
    
    if not resolved_path:
        return f"No file found matching '{file_path}'. Run indexing with --git to include git history."
    normalized_input = file_path.replace("\\", "/")
    if resolved_path != normalized_input:
        logger.info(
            "Resolved file path for code_ownership: input='%s' -> resolved='%s'",
            normalized_input,
            resolved_path,
        )
    else:
        logger.info("Resolved file path for code_ownership: '%s'", resolved_path)
    mods = [
        r for r in kg.relations
        if r.source == resolved_path
        and r.relation_type.value == "MODIFIED_BY"
    ]
    if not mods:
        return f"No ownership data for '{resolved_path}'. Run indexing with --git to include git history."
    # Sort by commit count descending
    mods.sort(
        key=lambda r: int(r.metadata.get("commit_count", "0")),
        reverse=True,
    )
    lines = [f"Ownership for {resolved_path}:\n"]
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
    
    # Resolve the file path (handles both exact and suffix matches)
    try:
        resolved_path = _resolve_file_path(file_path, kg)
    except ValueError as e:
        return str(e)
    
    if not resolved_path:
        return f"No file found matching '{file_path}'."
    
    # CO_CHANGED edges go both directions
    coupled: list[tuple[str, int]] = []
    for r in kg.relations:
        if r.relation_type.value != "CO_CHANGED":
            continue
        cnt = int(r.metadata.get("co_change_count", "0"))
        if cnt < min_count:
            continue
        if r.source == resolved_path:
            coupled.append((r.target, cnt))
        elif r.target == resolved_path:
            coupled.append((r.source, cnt))
    if not coupled:
        return f"No co-change data for '{resolved_path}'. Run indexing with --git to include git history."
    coupled.sort(key=lambda x: x[1], reverse=True)
    lines = [f"Files that frequently change with {resolved_path}:\n"]
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
    
    # Resolve the file path (handles both exact and suffix matches)
    try:
        resolved_path = _resolve_file_path(file_path, kg)
    except ValueError as e:
        return str(e)
    
    if not resolved_path:
        return f"No file found matching '{file_path}'."
    
    # Find commits that touched this file
    commit_keys = [
        r.target
        for r in kg.relations
        if r.source == resolved_path and r.relation_type.value == "COMMITTED_IN"
    ]
    if not commit_keys:
        return f"No commit data for '{resolved_path}'."

    # Find work items linked from those commits
    wi_map: dict[str, list[str]] = {}  # wid → list of commit shas
    for r in kg.relations:
        if r.relation_type.value == "LINKED_TO" and r.source in commit_keys:
            wid = r.metadata.get("work_item_id", "?")
            wi_map.setdefault(wid, []).append(r.source)

    if not wi_map:
        return f"No work items linked to '{resolved_path}' via commit messages."

    # Try to include hydrated details
    kg_wi = {e.metadata.get("id", ""): e for e in kg.entities if e.entity_type.value == "work_item"}

    lines = [f"Work items linked to {resolved_path}:\n"]
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
    # Eagerly load the graph at startup (instead of waiting for first tool call)
    print("[kg-mcp] Starting server, loading graph...", file=sys.stderr)
    _load_graph()
    print("[kg-mcp] Server ready.", file=sys.stderr)
    
    # Optionally pre-load embeddings at startup (default: lazy load on first search)
    # Set KG_PRELOAD_EMBEDDINGS=1 to download/load the model at startup
    import os
    if os.getenv("KG_PRELOAD_EMBEDDINGS", "").strip() in ("1", "true", "yes"):
        print("[kg-mcp] Pre-loading embedding model (this may take 30-60 seconds)...", file=sys.stderr)
        try:
            _ensure_retriever()
            print("[kg-mcp] Embedding model pre-loaded.", file=sys.stderr)
        except Exception as e:
            print(f"[kg-mcp] Warning: Failed to pre-load embeddings: {e}", file=sys.stderr)
    
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
