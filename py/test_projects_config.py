from __future__ import annotations

import json
from pathlib import Path

from kg_rag.projects import ProjectsConfig


def test_load_uses_single_project_environment(monkeypatch) -> None:
    monkeypatch.setenv("KG_REPO_ROOT", "C:/repos/example")
    monkeypatch.setenv("KG_PROJECT_NAME", "Upgrader")
    monkeypatch.setenv("KG_SCOPE_PATHS", "src/Upgrader")
    monkeypatch.delenv("KG_PROJECTS_JSON", raising=False)
    monkeypatch.delenv("KG_PROJECTS_FILE", raising=False)

    cfg = ProjectsConfig.load(Path("does-not-matter.json"))

    assert cfg.get_repo_root() == Path("C:/repos/example").resolve()
    assert cfg.list_project_names() == ["Upgrader"]
    assert cfg.projects["Upgrader"].paths == ["src/Upgrader"]


def test_load_uses_inline_json_before_file(monkeypatch, tmp_path: Path) -> None:
    external_path = tmp_path / "projects.json"
    external_path.write_text(
        json.dumps(
            {
                "repo_root": "C:/repos/external",
                "projects": {"External": {"paths": ["src"]}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KG_PROJECTS_FILE", str(external_path))
    monkeypatch.setenv(
        "KG_PROJECTS_JSON",
        json.dumps(
            {
                "repo_root": "C:/repos/inline",
                "projects": {"Inline": {"paths": ["app"]}},
            }
        ),
    )

    cfg = ProjectsConfig.load()

    assert cfg.get_repo_root() == Path("C:/repos/inline").resolve()
    assert cfg.list_project_names() == ["Inline"]


def test_cache_path_is_scoped_by_repo_and_project(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("KG_PROJECTS_JSON", raising=False)
    monkeypatch.delenv("KG_PROJECTS_FILE", raising=False)
    monkeypatch.delenv("KG_REPO_ROOT", raising=False)
    monkeypatch.delenv("KG_SCOPE_PATHS", raising=False)

    cfg = ProjectsConfig(
        repo_root="C:/repos/example",
        cache_dir=str(tmp_path),
        projects={"Frontend App": {"paths": ["src/Frontend"]}},
    )

    cache_path = cfg.graph_cache_path("Frontend App")

    assert cache_path.parent == tmp_path.resolve()
    assert cache_path.name.startswith("Frontend-App-")
    assert cache_path.suffix == ".pkl"


def test_default_project_name_prefers_explicit_match() -> None:
    cfg = ProjectsConfig(
        repo_root="C:/repos/example",
        projects={
            "Upgrader": {"paths": ["src/Upgrader"]},
            "Frontend": {"paths": ["src/Frontend"]},
        },
    )

    assert cfg.default_project_name("Frontend") == "Frontend"