from __future__ import annotations

from kg_rag.mcp_server import graph_stats
from kg_rag.models import (
    CodeEntityType,
    CodeRelationType,
    Entity,
    GraphMetadata,
    KnowledgeGraph,
    Relation,
)


def test_graph_stats_reports_history_and_work_items(monkeypatch) -> None:
    kg = KnowledgeGraph(
        entities=[
            Entity(name="module.py", entity_type=CodeEntityType.FILE, file_path="module.py"),
            Entity(name="abc123", entity_type=CodeEntityType.COMMIT, file_path="", metadata={"sha": "abc123"}),
            Entity(name="dev@example.com", entity_type=CodeEntityType.AUTHOR, file_path=""),
            Entity(
                name="Work item 42",
                entity_type=CodeEntityType.WORK_ITEM,
                file_path="",
                metadata={"id": "42"},
            ),
        ],
        relations=[
            Relation(source="module.py", target="abc123", relation_type=CodeRelationType.COMMITTED_IN),
            Relation(source="module.py", target="dev@example.com", relation_type=CodeRelationType.MODIFIED_BY),
            Relation(source="module.py", target="other.py", relation_type=CodeRelationType.CO_CHANGED),
            Relation(source="abc123", target="42", relation_type=CodeRelationType.LINKED_TO),
        ],
    )
    metadata = GraphMetadata(
        project_name="demo",
        repo_root="C:/repo",
        scope_paths=["."],
        has_git_history=True,
        has_work_items=True,
        git_since="4 years ago",
    )

    monkeypatch.setattr("kg_rag.mcp_server._kg", kg)
    monkeypatch.setattr("kg_rag.mcp_server._active_project", "demo")
    monkeypatch.setattr("kg_rag.mcp_server._metadata", metadata)

    result = graph_stats()

    assert "Historical changes:" in result
    assert "  Indexed: yes (since 4 years ago)" in result
    assert "  Commits: 1" in result
    assert "  Authors: 1" in result
    assert "  File change links: 1" in result
    assert "  Ownership links: 1" in result
    assert "  Co-change links: 1" in result
    assert "Work items:" in result
    assert "  Indexed: yes" in result
    assert "  Work item entities: 1" in result
    assert "  Commit links: 1" in result