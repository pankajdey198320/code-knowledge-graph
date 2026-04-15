"""CLI entry-points for indexing a repo and launching the MCP server."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_rag.config import settings


def main_index() -> None:
    """Index a repository (or a project scope) and save the graph to disk."""
    parser = argparse.ArgumentParser(description="Index a code repository into a knowledge graph")
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=None,
        help="Path to the mono-repo root (default: from projects.json or REPO_ROOT)",
    )
    parser.add_argument(
        "-p", "--project",
        default=None,
        help="Name of a project scope defined in projects.json (indexes only those paths)",
    )
    parser.add_argument(
        "--paths",
        default=None,
        help="Comma-separated sub-directory paths to index (relative to repo root)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output path for the pickled graph (auto-derived from project name if omitted)",
    )
    parser.add_argument(
        "--extensions",
        default=",".join(settings.INDEX_EXTENSIONS),
        help="Comma-separated file extensions to index",
    )
    parser.add_argument(
        "--list-projects",
        action="store_true",
        help="List configured projects and exit",
    )
    args = parser.parse_args()

    from kg_rag.indexer import index_repo, save_graph
    from kg_rag.projects import ProjectsConfig

    cfg = ProjectsConfig.load()

    # --list-projects
    if args.list_projects:
        if not cfg.projects:
            print("No projects configured. Edit projects.json to add scopes.")
        else:
            print(f"Repo root: {cfg.get_repo_root()}\n")
            for name, scope in cfg.projects.items():
                cached = "cached" if cfg.graph_cache_path(name).exists() else "not cached"
                print(f"  {name}  ({cached})")
                if scope.description:
                    print(f"    {scope.description}")
                print(f"    paths: {', '.join(scope.paths)}")
        return

    # Determine repo root
    repo = Path(args.repo_root).resolve() if args.repo_root else cfg.get_repo_root()

    # Determine scope paths and output
    scope_paths: list[Path] | None = None
    project_name = args.project

    if project_name:
        if project_name not in cfg.projects:
            print(f"Error: unknown project '{project_name}'.", file=sys.stderr)
            print(f"Available: {', '.join(cfg.list_project_names())}", file=sys.stderr)
            sys.exit(1)
        scope_paths = cfg.resolve_paths(project_name)
        output = Path(args.output) if args.output else cfg.graph_cache_path(project_name)
    elif args.paths:
        scope_paths = [repo / p.strip() for p in args.paths.split(",")]
        output = Path(args.output) if args.output else settings.GRAPH_CACHE_PATH
    else:
        output = Path(args.output) if args.output else settings.GRAPH_CACHE_PATH

    extensions = [e.strip() for e in args.extensions.split(",")]

    label = f"project '{project_name}'" if project_name else str(repo)
    print(f"Indexing {label} ...")
    if scope_paths:
        print(f"  Scope paths: {[str(p) for p in scope_paths]}")

    kg = index_repo(repo, extensions=extensions, show_progress=True, scope_paths=scope_paths)
    out = save_graph(kg, output)
    print(f"\nDone. {len(kg.entities)} entities, {len(kg.relations)} relations")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main_index()
