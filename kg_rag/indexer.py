"""Repo indexer – crawl a mono-repo, parse all source files, build the KG."""

from __future__ import annotations

import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

from kg_rag.config import settings
from kg_rag.models import GraphMetadata, KnowledgeGraph, PersistedGraph
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


def save_graph(
    kg: KnowledgeGraph,
    path: Path | None = None,
    metadata: GraphMetadata | None = None,
) -> Path:
    """Persist the KG with metadata to a pickle file."""
    path = path or settings.GRAPH_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create metadata if not provided
    if metadata is None:
        metadata = GraphMetadata(
            indexed_at=datetime.now(timezone.utc).isoformat(),
            entity_count=len(kg.entities),
            relation_count=len(kg.relations),
        )
    else:
        # Update counts
        metadata.entity_count = len(kg.entities)
        metadata.relation_count = len(kg.relations)
        if not metadata.indexed_at:
            metadata.indexed_at = datetime.now(timezone.utc).isoformat()
    
    persisted = PersistedGraph(metadata=metadata, graph=kg)
    
    with open(path, "wb") as f:
        pickle.dump(persisted.model_dump(), f)
    
    # Update the project registry
    _update_registry(path, metadata)
    
    return path


def load_graph(path: Path | None = None) -> KnowledgeGraph:
    """Load a previously saved KG from disk.
    
    Supports both new format (with metadata) and legacy format (raw KG).
    """
    path = path or settings.GRAPH_CACHE_PATH
    with open(path, "rb") as f:
        data = pickle.load(f)  # noqa: S301 – trusted local file
    
    # Handle legacy format (raw KG dict) vs new format (PersistedGraph dict)
    if "graph" in data and "metadata" in data:
        # New format with metadata
        persisted = PersistedGraph(**data)
        return persisted.graph
    else:
        # Legacy format - raw KG
        return KnowledgeGraph(**data)


def load_graph_with_metadata(path: Path | None = None) -> tuple[KnowledgeGraph, GraphMetadata]:
    """Load a KG and its metadata from disk."""
    path = path or settings.GRAPH_CACHE_PATH
    with open(path, "rb") as f:
        data = pickle.load(f)  # noqa: S301 – trusted local file
    
    # Handle legacy format
    if "graph" in data and "metadata" in data:
        persisted = PersistedGraph(**data)
        return persisted.graph, persisted.metadata
    else:
        # Legacy format - create default metadata
        kg = KnowledgeGraph(**data)
        metadata = GraphMetadata(
            entity_count=len(kg.entities),
            relation_count=len(kg.relations),
        )
        return kg, metadata


# ======================================================================
# Project Registry
# ======================================================================


def _get_registry_path() -> Path:
    """Return path to the project registry file (in cache directory)."""
    # Ensure cache directory exists
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return settings.DATA_DIR / "project_registry.json"


def _update_registry(graph_path: Path, metadata: GraphMetadata) -> None:
    """Update the project registry with information about this indexed graph."""
    registry_path = _get_registry_path()
    
    # Load existing registry
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            registry = {}
    else:
        registry = {}
    
    # Add/update entry
    key = str(graph_path.resolve())
    registry[key] = {
        "project_name": metadata.project_name,
        "repo_root": metadata.repo_root,
        "scope_paths": metadata.scope_paths,
        "indexed_at": metadata.indexed_at,
        "entity_count": metadata.entity_count,
        "relation_count": metadata.relation_count,
        "has_git_history": metadata.has_git_history,
        "has_work_items": metadata.has_work_items,
        "graph_path": key,
    }
    
    # Save registry
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def list_indexed_projects() -> list[dict]:
    """Return list of all indexed projects from the registry."""
    registry_path = _get_registry_path()
    if not registry_path.exists():
        return []
    
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        # Filter to only existing graph files
        return [
            info for path, info in registry.items()
            if Path(path).exists()
        ]
    except (json.JSONDecodeError, OSError):
        return []
