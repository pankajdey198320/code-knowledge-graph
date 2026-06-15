"""Parser for Pascal and InnoSetup scripts.

Extracts procedures, functions, units, and program structure from .pas, .pp, .dpr,
.lpr (Pascal), and .iss (InnoSetup) files.
"""

from __future__ import annotations

import re
from pathlib import Path

from kg_rag.models import (
    CodeEntityType,
    CodeRelationType,
    Entity,
    KnowledgeGraph,
    Relation,
)
from kg_rag.parsers.base import BaseCodeParser


class PascalParser(BaseCodeParser):
    language = "pascal"

    def parse_file(self, file_path: Path, repo_root: Path) -> KnowledgeGraph:
        source = self._read_source(file_path).decode("utf-8", errors="replace")
        rel_path = self._relative(file_path, repo_root)

        kg = KnowledgeGraph()
        file_ent = self._make_file_entity(rel_path)
        kg.add_entity(file_ent)

        # Determine if this is an InnoSetup script
        is_innosetup = file_path.suffix.lower() == ".iss"

        if is_innosetup:
            self._parse_innosetup(source, rel_path, kg, file_ent)
        else:
            self._parse_pascal(source, rel_path, kg, file_ent)

        return kg

    # ------------------------------------------------------------------
    # Pascal parsing
    # ------------------------------------------------------------------

    def _parse_pascal(
        self,
        source: str,
        rel_path: str,
        kg: KnowledgeGraph,
        file_ent: Entity,
    ) -> None:
        """Parse standard Pascal/Delphi source files."""
        lines = source.split("\n")

        # Extract unit/program name
        unit_match = re.search(r"^\s*(?:unit|program|library)\s+(\w+)", source, re.IGNORECASE | re.MULTILINE)
        if unit_match:
            unit_name = unit_match.group(1)
            line_num = source[:unit_match.start()].count("\n") + 1
            
            unit_ent = Entity(
                name=unit_name,
                entity_type=CodeEntityType.MODULE,
                language=self.language,
                file_path=rel_path,
                line_start=line_num,
                line_end=line_num,
                signature=f"unit {unit_name}",
            )
            kg.add_entity(unit_ent)
            kg.add_relation(
                Relation(
                    source=file_ent.qualified_key,
                    target=unit_ent.qualified_key,
                    relation_type=CodeRelationType.DEFINES,
                )
            )
            parent_key = unit_ent.qualified_key
        else:
            parent_key = file_ent.qualified_key

        # Extract functions and procedures
        self._extract_functions_procedures(source, rel_path, kg, parent_key)

        # Extract classes and records
        self._extract_classes_records(source, rel_path, kg, parent_key)

        # Extract uses clauses (imports)
        self._extract_uses(source, kg, parent_key)

    def _extract_functions_procedures(
        self,
        source: str,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
    ) -> None:
        """Extract function and procedure declarations."""
        # Regex to match function/procedure declarations
        # Handles: function Name(...): Type; procedure Name(...);
        pattern = re.compile(
            r"^\s*(function|procedure)\s+(\w+(?:\.\w+)?)\s*(\([^)]*\))?\s*(?::\s*(\w+(?:\.\w+)?))?\s*;",
            re.IGNORECASE | re.MULTILINE,
        )

        for match in pattern.finditer(source):
            kind = match.group(1).lower()
            name = match.group(2)
            params = match.group(3) or "()"
            return_type = match.group(4) or ""
            line_num = source[:match.start()].count("\n") + 1

            # Build signature
            if kind == "function" and return_type:
                sig = f"function {name}{params}: {return_type}"
            else:
                sig = f"{kind} {name}{params}"

            ent = Entity(
                name=name,
                entity_type=CodeEntityType.FUNCTION,
                language=self.language,
                file_path=rel_path,
                line_start=line_num,
                line_end=line_num,
                signature=sig,
                metadata={"kind": kind},
            )
            kg.add_entity(ent)
            kg.add_relation(
                Relation(
                    source=parent_key,
                    target=ent.qualified_key,
                    relation_type=CodeRelationType.DEFINES,
                )
            )

            # Extract calls within this function/procedure body
            self._extract_calls_in_routine(source, match.end(), name, kg, ent.qualified_key)

    def _extract_classes_records(
        self,
        source: str,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
    ) -> None:
        """Extract class and record type declarations."""
        # Match: TClassName = class ... end;
        pattern = re.compile(
            r"^\s*(\w+)\s*=\s*(class|record|interface)\s*(?:\([^)]*\))?",
            re.IGNORECASE | re.MULTILINE,
        )

        for match in pattern.finditer(source):
            name = match.group(1)
            kind = match.group(2).lower()
            line_num = source[:match.start()].count("\n") + 1

            # Find the end of the class/record
            end_match = re.search(r"\bend\s*;", source[match.end():], re.IGNORECASE)
            end_line = line_num
            if end_match:
                end_line = source[:match.end() + end_match.end()].count("\n") + 1

            entity_type = CodeEntityType.CLASS if kind == "class" else CodeEntityType.STRUCT
            if kind == "interface":
                entity_type = CodeEntityType.INTERFACE

            ent = Entity(
                name=name,
                entity_type=entity_type,
                language=self.language,
                file_path=rel_path,
                line_start=line_num,
                line_end=end_line,
                signature=f"{name} = {kind}",
                metadata={"kind": kind},
            )
            kg.add_entity(ent)
            kg.add_relation(
                Relation(
                    source=parent_key,
                    target=ent.qualified_key,
                    relation_type=CodeRelationType.DEFINES,
                )
            )

    def _extract_uses(
        self,
        source: str,
        kg: KnowledgeGraph,
        parent_key: str,
    ) -> None:
        """Extract uses clauses (similar to imports)."""
        # Match: uses Unit1, Unit2 in 'file.pas', Unit3;
        pattern = re.compile(
            r"^\s*uses\s+([\w\s,.']+?);",
            re.IGNORECASE | re.MULTILINE,
        )

        for match in pattern.finditer(source):
            uses_clause = match.group(1)
            # Split by comma and extract unit names
            units = re.findall(r"(\w+)", uses_clause)
            for unit in units:
                if unit and unit.lower() not in ("in",):
                    kg.add_relation(
                        Relation(
                            source=parent_key,
                            target=unit,
                            relation_type=CodeRelationType.IMPORTS,
                        )
                    )

    def _extract_calls_in_routine(
        self,
        source: str,
        start_pos: int,
        routine_name: str,
        kg: KnowledgeGraph,
        caller_key: str,
    ) -> None:
        """Extract function/procedure calls within a routine body."""
        # Find the begin...end block for this routine
        begin_match = re.search(r"\bbegin\b", source[start_pos:], re.IGNORECASE)
        if not begin_match:
            return

        begin_pos = start_pos + begin_match.start()
        
        # Find matching end (simplified - doesn't handle nested begin/end perfectly)
        end_match = re.search(r"\bend\s*;", source[begin_pos:], re.IGNORECASE)
        if not end_match:
            return

        end_pos = begin_pos + end_match.end()
        body = source[begin_pos:end_pos]

        # Extract function calls (simplified pattern)
        # Matches: FunctionName(...) or ObjectName.MethodName(...)
        call_pattern = re.compile(r"\b(\w+(?:\.\w+)?)\s*\(", re.IGNORECASE)
        
        for call_match in call_pattern.finditer(body):
            called_name = call_match.group(1)
            # Filter out common keywords
            if called_name.lower() not in ("if", "while", "for", "case", "repeat", "with"):
                kg.add_relation(
                    Relation(
                        source=caller_key,
                        target=called_name,
                        relation_type=CodeRelationType.CALLS,
                    )
                )

    # ------------------------------------------------------------------
    # InnoSetup parsing
    # ------------------------------------------------------------------

    def _parse_innosetup(
        self,
        source: str,
        rel_path: str,
        kg: KnowledgeGraph,
        file_ent: Entity,
    ) -> None:
        """Parse InnoSetup script files (.iss)."""
        # InnoSetup scripts have sections like [Setup], [Files], [Code]
        # The [Code] section contains Pascal code
        
        # Extract [Code] section
        code_match = re.search(r"\[Code\]\s*\n(.*?)(?=\n\[|\Z)", source, re.IGNORECASE | re.DOTALL)
        if code_match:
            code_section = code_match.group(1)
            line_offset = source[:code_match.start()].count("\n") + 1
            
            # Parse Pascal code within [Code] section
            self._extract_innosetup_functions(code_section, rel_path, kg, file_ent, line_offset)

        # Extract other sections as metadata
        sections = re.findall(r"\[(\w+)\]", source, re.IGNORECASE)
        if sections:
            file_ent.metadata = {"sections": ", ".join(sections)}

    def _extract_innosetup_functions(
        self,
        code_section: str,
        rel_path: str,
        kg: KnowledgeGraph,
        file_ent: Entity,
        line_offset: int,
    ) -> None:
        """Extract functions from InnoSetup [Code] section."""
        # InnoSetup uses Pascal syntax in [Code] section
        pattern = re.compile(
            r"^\s*(function|procedure)\s+(\w+)\s*(\([^)]*\))?\s*(?::\s*(\w+))?\s*;",
            re.IGNORECASE | re.MULTILINE,
        )

        for match in pattern.finditer(code_section):
            kind = match.group(1).lower()
            name = match.group(2)
            params = match.group(3) or "()"
            return_type = match.group(4) or ""
            line_num = line_offset + code_section[:match.start()].count("\n")

            # Build signature
            if kind == "function" and return_type:
                sig = f"function {name}{params}: {return_type}"
            else:
                sig = f"{kind} {name}{params}"

            ent = Entity(
                name=name,
                entity_type=CodeEntityType.FUNCTION,
                language="innosetup",
                file_path=rel_path,
                line_start=line_num,
                line_end=line_num,
                signature=sig,
                metadata={"kind": kind, "context": "innosetup"},
            )
            kg.add_entity(ent)
            kg.add_relation(
                Relation(
                    source=file_ent.qualified_key,
                    target=ent.qualified_key,
                    relation_type=CodeRelationType.DEFINES,
                )
            )
