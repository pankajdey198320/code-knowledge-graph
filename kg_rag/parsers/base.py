"""Abstract base for language-specific code parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from kg_rag.models import Entity, KnowledgeGraph, Relation


class BaseCodeParser(ABC):
    """Parse a single source file and return entities + relations."""

    language: str = ""

    @abstractmethod
    def parse_file(self, file_path: Path, repo_root: Path) -> KnowledgeGraph:
        """Parse *file_path* and return a sub-graph."""
        ...

    # ----- helpers --------------------------------------------------------

    @staticmethod
    def _relative(file_path: Path, repo_root: Path) -> str:
        try:
            return str(file_path.relative_to(repo_root)).replace("\\", "/")
        except ValueError:
            return str(file_path).replace("\\", "/")

    @staticmethod
    def _read_source(file_path: Path) -> bytes:
        return file_path.read_bytes()

    def _make_file_entity(self, rel_path: str) -> Entity:
        from kg_rag.models import CodeEntityType

        return Entity(
            name=rel_path,
            entity_type=CodeEntityType.FILE,
            language=self.language,
            file_path=rel_path,
        )
