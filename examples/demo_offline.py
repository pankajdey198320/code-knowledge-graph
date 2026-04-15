"""Offline demo – index this project's own source code and query the graph.

No OpenAI key needed. Tests parsing, embedding, and retrieval only.
"""

from pathlib import Path

from kg_rag.embeddings import KGEmbedder
from kg_rag.indexer import index_repo
from kg_rag.retriever import GraphRetriever


def main() -> None:
    print("=== Offline Code KG Demo (no LLM needed) ===\n")

    # Index this project itself
    repo_root = Path(__file__).resolve().parent.parent
    print(f"Indexing {repo_root} ...")
    kg = index_repo(repo_root, show_progress=True)
    print(f"\nGraph: {len(kg.entities)} entities, {len(kg.relations)} relations\n")

    # Show entity type breakdown
    type_counts: dict[str, int] = {}
    for ent in kg.entities:
        key = ent.entity_type.value
        type_counts[key] = type_counts.get(key, 0) + 1
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")
    print()

    # Retrieve context for queries
    embedder = KGEmbedder()
    retriever = GraphRetriever(kg=kg, embedder=embedder, top_k=5, hops=2)

    queries = [
        "How are Python files parsed?",
        "What MCP tools are available?",
        "class inheritance",
        "function call graph",
    ]

    for query in queries:
        print(f"[Q] {query}")
        ctx = retriever.retrieve(query)
        print(f"    Entities: {len(ctx.entities)}, Relations: {len(ctx.relations)}")
        # Show top entities only
        for ent in ctx.entities[:5]:
            print(f"      - [{ent.entity_type.value}] {ent.name} ({ent.file_path}:{ent.line_start})")
        print()


if __name__ == "__main__":
    main()
