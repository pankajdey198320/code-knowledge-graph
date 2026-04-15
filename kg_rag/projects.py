"""Project scoping — manage named subsets of a mono-repo for focused indexing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from kg_rag.config import settings


class ProjectScope(BaseModel):
    """A named subset of the mono-repo to index."""

    description: str = ""
    paths: list[str] = Field(default_factory=lambda: ["."])


class ProjectsConfig(BaseModel):
    """Top-level config holding all defined project scopes."""

    repo_root: str = ""
    projects: dict[str, ProjectScope] = Field(default_factory=dict)

    # ---- persistence ----

    @classmethod
    def load(cls, path: Path | None = None) -> "ProjectsConfig":
        """Load from *projects.json*. Returns empty config if file missing."""
        path = path or _default_config_path()
        if not path.exists():
            return cls()
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    def save(self, path: Path | None = None) -> Path:
        """Persist to *projects.json*."""
        path = path or _default_config_path()
        path.write_text(
            json.dumps(self.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    # ---- helpers ----

    def get_repo_root(self) -> Path:
        """Resolve repo root — from config or fallback to settings."""
        if self.repo_root:
            return Path(self.repo_root).resolve()
        return settings.REPO_ROOT

    def resolve_paths(self, project_name: str) -> list[Path]:
        """Return absolute paths for a project scope."""
        scope = self.projects.get(project_name)
        if scope is None:
            raise KeyError(f"Unknown project: '{project_name}'")
        root = self.get_repo_root()
        return [root / p for p in scope.paths]

    def graph_cache_path(self, project_name: str) -> Path:
        """Return the pickle cache path for a given project."""
        return settings.DATA_DIR / f"{project_name}.pkl"

    def list_project_names(self) -> list[str]:
        return list(self.projects.keys())


def _default_config_path() -> Path:
    return settings.PROJECT_ROOT / "projects.json"
