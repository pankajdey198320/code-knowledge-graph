"""Full demo – index a repo and ask questions via LLM (requires OpenAI key)."""

from pathlib import Path

from kg_rag.pipeline import CodeGraphRAG


def main() -> None:
    print("=== Code Knowledge Graph + Graph RAG Demo ===\n")

    # Point at this project itself as a sample repo
    repo_root = Path(__file__).resolve().parent.parent

    pipeline = CodeGraphRAG(repo_root=repo_root)

    # 1. Index
    print("[1] Indexing repository...")
    kg = pipeline.index(force=True)
    print(f"    {len(kg.entities)} entities, {len(kg.relations)} relations\n")

    # 2. Ask questions
    questions = [
        "What classes are defined in this project?",
        "How does the MCP server expose the knowledge graph?",
        "What does the PythonParser class do?",
    ]

    for q in questions:
        print(f"[Q] {q}")
        answer = pipeline.query(q)
        print(f"[A] {answer}\n")


if __name__ == "__main__":
    main()
