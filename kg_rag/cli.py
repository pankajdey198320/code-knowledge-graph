"""CLI entry-points for indexing a repo and launching the MCP server."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_rag.config import settings


def main_index() -> None:
    """Index a repository and save the graph to disk."""
    parser = argparse.ArgumentParser(description="Index a code repository into a knowledge graph")
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=str(settings.REPO_ROOT),
        help="Path to the mono-repo root (default: REPO_ROOT from .env)",
    )
    parser.add_argument(
        "-o", "--output",
        default=str(settings.GRAPH_CACHE_PATH),
        help="Output path for the pickled graph",
    )
    parser.add_argument(
        "--extensions",
        default=",".join(settings.INDEX_EXTENSIONS),
        help="Comma-separated file extensions to index",
    )
    args = parser.parse_args()

    from kg_rag.indexer import index_repo, save_graph

    repo = Path(args.repo_root).resolve()
    extensions = [e.strip() for e in args.extensions.split(",")]

    print(f"Indexing {repo} ...")
    kg = index_repo(repo, extensions=extensions, show_progress=True)
    out = save_graph(kg, Path(args.output))
    print(f"\nDone. {len(kg.entities)} entities, {len(kg.relations)} relations")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main_index()
