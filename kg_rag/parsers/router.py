"""Router that selects the right parser for each file extension."""

from __future__ import annotations

from pathlib import Path

from kg_rag.models import KnowledgeGraph
from kg_rag.parsers.base import BaseCodeParser

_EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".c": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
}


def _get_parser(lang: str) -> BaseCodeParser:
    if lang == "python":
        from kg_rag.parsers.python_parser import PythonParser
        return PythonParser()
    elif lang == "cpp":
        from kg_rag.parsers.cpp_parser import CppParser
        return CppParser()
    elif lang == "csharp":
        from kg_rag.parsers.csharp_parser import CSharpParser
        return CSharpParser()
    raise ValueError(f"No parser for language: {lang}")


def language_for_extension(ext: str) -> str | None:
    return _EXTENSION_MAP.get(ext.lower())


def parse_file(file_path: Path, repo_root: Path) -> KnowledgeGraph | None:
    """Parse a single file using the appropriate language parser."""
    lang = language_for_extension(file_path.suffix)
    if lang is None:
        return None
    parser = _get_parser(lang)
    return parser.parse_file(file_path, repo_root)
