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
    ".f": "fortran",
    ".f90": "fortran",
    ".f95": "fortran",
    ".f03": "fortran",
    ".f08": "fortran",
    ".for": "fortran",
    ".fpp": "fortran",
    # Kotlin (TeamCity DSL etc.)
    ".kt": "kotlin",
    ".kts": "kotlin",
    # PowerShell
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".psd1": "powershell",
    # TypeScript / JavaScript
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
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
    elif lang == "fortran":
        from kg_rag.parsers.fortran_parser import FortranParser
        return FortranParser()
    elif lang == "kotlin":
        from kg_rag.parsers.kotlin_parser import KotlinParser
        return KotlinParser()
    elif lang == "powershell":
        from kg_rag.parsers.powershell_parser import PowerShellParser
        return PowerShellParser()
    elif lang == "typescript":
        from kg_rag.parsers.typescript_parser import TypeScriptParser
        return TypeScriptParser("typescript")
    elif lang == "tsx":
        from kg_rag.parsers.typescript_parser import TypeScriptParser
        return TypeScriptParser("tsx")
    elif lang == "javascript":
        from kg_rag.parsers.typescript_parser import TypeScriptParser
        return TypeScriptParser("javascript")
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
