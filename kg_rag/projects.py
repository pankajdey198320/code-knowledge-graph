"""Project scoping for repo indexing and MCP runtime configuration."""

from __future__ import annotations

import json
import os
from hashlib import sha1
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
    cache_dir: str = ""
    projects: dict[str, ProjectScope] = Field(default_factory=dict)

    # ---- persistence ----

    @classmethod
    def load(cls, path: Path | None = None) -> "ProjectsConfig":
        """Load config from MCP env first, then optional JSON file fallback."""
        env_cfg = cls._load_from_environment()
        if env_cfg is not None:
            return env_cfg

        path = path or _default_config_path()
        if not path.exists():
            return cls()
        data = _read_json_file(path)
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

    @classmethod
    def _load_from_environment(cls) -> "ProjectsConfig | None":
        raw_json = os.getenv("KG_PROJECTS_JSON", "").strip()
        if raw_json:
            return cls(**json.loads(raw_json))

        raw_file = os.getenv("KG_PROJECTS_FILE", "").strip()
        if raw_file:
            return cls(**_read_json_file(Path(raw_file)))

        repo_root = os.getenv("KG_REPO_ROOT", "").strip()
        scope_paths = _parse_scope_paths(os.getenv("KG_SCOPE_PATHS", ""))
        if not repo_root and not scope_paths:
            return None

        project_name = (
            os.getenv("KG_PROJECT_NAME", "").strip()
            or os.getenv("ACTIVE_PROJECT", "").strip()
            or "default"
        )
        description = os.getenv(
            "KG_PROJECT_DESCRIPTION",
            "Configured from MCP server environment",
        ).strip()
        cache_dir = os.getenv("KG_CACHE_DIR", "").strip()

        return cls(
            repo_root=repo_root or str(settings.REPO_ROOT),
            cache_dir=cache_dir,
            projects={
                project_name: ProjectScope(
                    description=description,
                    paths=scope_paths or ["."],
                )
            },
        )

    def get_repo_root(self) -> Path:
        """Resolve repo root — from config or fallback to settings."""
        if self.repo_root:
            return Path(self.repo_root).resolve()
        return settings.REPO_ROOT

    def default_project_name(self, preferred: str | None = None) -> str:
        """Return the best project name to activate for the current runtime."""
        if preferred and preferred in self.projects:
            return preferred
        if settings.ACTIVE_PROJECT in self.projects:
            return settings.ACTIVE_PROJECT
        if "_full_" in self.projects:
            return "_full_"
        if self.projects:
            return next(iter(self.projects))
        return preferred or settings.ACTIVE_PROJECT

    def resolve_paths(self, project_name: str) -> list[Path]:
        """Return absolute paths for a project scope."""
        scope = self.projects.get(project_name)
        if scope is None:
            raise KeyError(f"Unknown project: '{project_name}'")
        root = self.get_repo_root()
        return [root / p for p in scope.paths]

    def graph_cache_path(self, project_name: str) -> Path:
        """Return the pickle cache path for a given project."""
        cache_root = Path(self.cache_dir).resolve() if self.cache_dir else settings.DATA_DIR
        cache_root.mkdir(parents=True, exist_ok=True)
        repo_hash = sha1(str(self.get_repo_root()).encode("utf-8")).hexdigest()[:10]
        safe_name = _sanitize_cache_name(project_name)
        return cache_root / f"{safe_name}-{repo_hash}.pkl"

    def list_project_names(self) -> list[str]:
        return list(self.projects.keys())


def _default_config_path() -> Path:
    return settings.PROJECT_ROOT / "projects.json"


def _read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_scope_paths(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []

    if raw.startswith("["):
        values = json.loads(raw)
        if not isinstance(values, list):
            raise ValueError("KG_SCOPE_PATHS JSON value must be a list of strings")
        return [str(value).strip() for value in values if str(value).strip()]

    if os.pathsep in raw:
        parts = raw.split(os.pathsep)
    elif "," in raw:
        parts = raw.split(",")
    else:
        parts = raw.splitlines()

    return [part.strip() for part in parts if part.strip()]


def _sanitize_cache_name(value: str) -> str:
    safe = [ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value]
    return "".join(safe).strip("-") or "project"
