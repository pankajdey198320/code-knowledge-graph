from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from kg_rag.mcp_server import _transport_security_for_host, graph_stats, main
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


def test_main_defaults_to_stdio_and_eagerly_initializes(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    def fake_load_graph() -> None:
        calls.append(("load_graph", None))

    def fake_ensure_retriever(*_args: object, **_kwargs: object) -> None:
        calls.append(("ensure_retriever", None))

    def fake_run(*, transport: str, mount_path: str | None = None) -> None:
        calls.append(("run", (transport, mount_path)))

    monkeypatch.setattr("kg_rag.mcp_server._load_graph", fake_load_graph)
    monkeypatch.setattr("kg_rag.mcp_server._ensure_retriever", fake_ensure_retriever)
    monkeypatch.setattr("kg_rag.mcp_server.mcp.run", fake_run)

    main([])

    assert calls == [
        ("load_graph", None),
        ("ensure_retriever", None),
        ("run", ("stdio", None)),
    ]


def test_main_runs_sse_transport_with_cli_settings(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    def fake_load_graph() -> None:
        calls.append(("load_graph", None))

    def fake_ensure_retriever(*_args: object, **_kwargs: object) -> None:
        calls.append(("ensure_retriever", None))

    def fake_run(*, transport: str, mount_path: str | None = None) -> None:
        calls.append(("run", (transport, mount_path)))

    monkeypatch.setattr("kg_rag.mcp_server._load_graph", fake_load_graph)
    monkeypatch.setattr("kg_rag.mcp_server._ensure_retriever", fake_ensure_retriever)
    monkeypatch.setattr("kg_rag.mcp_server.mcp.run", fake_run)

    main([
        "--transport",
        "sse",
        "--host",
        "0.0.0.0",
        "--port",
        "9000",
        "--mount-path",
        "/kg",
        "--sse-path",
        "/events",
        "--message-path",
        "/posts/",
    ])

    assert calls == [
        ("load_graph", None),
        ("ensure_retriever", None),
        ("run", ("sse", "/kg")),
    ]
    from kg_rag.mcp_server import mcp

    assert mcp.settings.host == "0.0.0.0"
    assert mcp.settings.port == 9000
    assert mcp.settings.mount_path == "/kg"
    assert mcp.settings.sse_path == "/events"
    assert mcp.settings.message_path == "/posts/"
    assert mcp.settings.transport_security is None


def test_main_runs_streamable_http_transport(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    def fake_load_graph() -> None:
        calls.append(("load_graph", None))

    def fake_ensure_retriever(*_args: object, **_kwargs: object) -> None:
        calls.append(("ensure_retriever", None))

    def fake_run(*, transport: str, mount_path: str | None = None) -> None:
        calls.append(("run", (transport, mount_path)))

    monkeypatch.setattr("kg_rag.mcp_server._load_graph", fake_load_graph)
    monkeypatch.setattr("kg_rag.mcp_server._ensure_retriever", fake_ensure_retriever)
    monkeypatch.setattr("kg_rag.mcp_server.mcp.run", fake_run)

    main([
        "--transport",
        "streamable-http",
        "--host",
        "127.0.0.1",
        "--port",
        "8123",
        "--streamable-http-path",
        "/kg-mcp",
    ])

    assert calls == [
        ("load_graph", None),
        ("ensure_retriever", None),
        ("run", ("streamable-http", None)),
    ]
    from kg_rag.mcp_server import mcp

    assert mcp.settings.host == "127.0.0.1"
    assert mcp.settings.port == 8123
    assert mcp.settings.streamable_http_path == "/kg-mcp"
    assert mcp.settings.transport_security is not None


def test_transport_security_defaults_follow_selected_host() -> None:
    localhost_security = _transport_security_for_host("127.0.0.1")

    assert localhost_security is not None
    assert localhost_security.enable_dns_rebinding_protection is True
    assert "127.0.0.1:*" in localhost_security.allowed_hosts
    assert "http://127.0.0.1:*" in localhost_security.allowed_origins

    assert _transport_security_for_host("0.0.0.0") is None


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _fetch_graph_stats_over_streamable_http(url: str) -> tuple[list[str], str]:
    async with streamable_http_client(url) as streams:
        read_stream, write_stream, _ = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("graph_stats")

    tool_names = [tool.name for tool in tools.tools]
    text_chunks = [block.text for block in result.content if getattr(block, "type", None) == "text"]
    return tool_names, "\n".join(text_chunks)


def test_streamable_http_e2e_serves_tool_calls(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "example.py").write_text(
        "def hello(name: str) -> str:\n    return f'hello {name}'\n",
        encoding="utf-8",
    )

    cache_dir = tmp_path / "cache"
    port = _find_free_port()
    url = f"http://127.0.0.1:{port}/mcp"

    env = os.environ.copy()
    env.update(
        {
            "KG_REPO_ROOT": str(repo_root),
            "KG_PROJECT_NAME": "e2e",
            "KG_SCOPE_PATHS": ".",
            "KG_CACHE_DIR": str(cache_dir),
        }
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "kg_rag.mcp_server",
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=Path(__file__).resolve().parent,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        deadline = time.time() + 120
        last_error: Exception | None = None

        while time.time() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=5)
                raise AssertionError(
                    "MCP server exited before becoming ready.\n"
                    f"stdout:\n{stdout}\n"
                    f"stderr:\n{stderr}"
                )

            try:
                tool_names, graph_stats_text = anyio.run(_fetch_graph_stats_over_streamable_http, url)
                break
            except Exception as exc:
                last_error = exc
                time.sleep(1)
        else:
            process.terminate()
            stdout, stderr = process.communicate(timeout=10)
            raise AssertionError(
                "Timed out waiting for streamable HTTP MCP server to accept requests.\n"
                f"Last error: {last_error}\n"
                f"stdout:\n{stdout}\n"
                f"stderr:\n{stderr}"
            )

        assert "graph_stats" in tool_names
        assert "Active project: e2e" in graph_stats_text
        assert "Total entities:" in graph_stats_text
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=10)