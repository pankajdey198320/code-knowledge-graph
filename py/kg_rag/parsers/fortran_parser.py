"""Tree-sitter based Fortran source parser.

Extracts modules, subroutines, functions, USE statements, CALL statements,
and BIND(C) interop annotations that link Fortran to C/C++ code.
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_fortran as tsfortran
from tree_sitter import Language, Parser, Node

from kg_rag.models import (
    CodeEntityType,
    CodeRelationType,
    Entity,
    KnowledgeGraph,
    Relation,
)
from kg_rag.parsers.base import BaseCodeParser

FORTRAN_LANGUAGE = Language(tsfortran.language())


class FortranParser(BaseCodeParser):
    language = "fortran"

    def __init__(self) -> None:
        self._parser = Parser(FORTRAN_LANGUAGE)

    def parse_file(self, file_path: Path, repo_root: Path) -> KnowledgeGraph:
        source = self._read_source(file_path)
        tree = self._parser.parse(source)
        rel_path = self._relative(file_path, repo_root)

        kg = KnowledgeGraph()
        file_ent = self._make_file_entity(rel_path)
        kg.add_entity(file_ent)

        self._walk(tree.root_node, source, rel_path, kg, parent_key=file_ent.qualified_key)
        return kg

    # ------------------------------------------------------------------
    # AST walking
    # ------------------------------------------------------------------

    def _walk(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        module_name: str = "",
    ) -> None:
        for child in node.children:
            if child.type == "module":
                self._handle_module(child, source, rel_path, kg, parent_key)
            elif child.type == "subroutine":
                self._handle_subroutine(child, source, rel_path, kg, parent_key, module_name)
            elif child.type == "function":
                self._handle_function(child, source, rel_path, kg, parent_key, module_name)
            elif child.type == "use_statement":
                self._handle_use(child, source, rel_path, kg, parent_key)
            elif child.type in ("preproc_include", "preproc_call"):
                self._handle_include(child, source, rel_path, kg, parent_key)

    # ------------------------------------------------------------------
    # Modules
    # ------------------------------------------------------------------

    def _handle_module(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        mod_name = self._find_child_text(node, "name", source) or "<unnamed>"

        ent = Entity(
            name=mod_name,
            entity_type=CodeEntityType.MODULE,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.DEFINES)
        )

        # Walk children for subroutines, functions, USE statements inside module
        self._walk(node, source, rel_path, kg, parent_key=ent.qualified_key, module_name=mod_name)

    # ------------------------------------------------------------------
    # Subroutines
    # ------------------------------------------------------------------

    def _handle_subroutine(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        module_name: str,
    ) -> None:
        sub_name = self._find_child_text(node, "name", source)
        if not sub_name:
            # Try from subroutine_statement child
            stmt = self._find_child_node(node, "subroutine_statement")
            if stmt:
                sub_name = self._find_child_text(stmt, "name", source)
        if not sub_name:
            return

        qualified = f"{module_name}::{sub_name}" if module_name else sub_name
        sig = self._first_line(node, source)

        # Detect BIND(C) for native interop
        bind_name = self._extract_bind_c_name(node, source)
        metadata: dict[str, str] = {}
        if bind_name:
            metadata["bind_c"] = bind_name

        ent = Entity(
            name=qualified,
            entity_type=CodeEntityType.FUNCTION,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            metadata=metadata,
        )
        kg.add_entity(ent)

        rel_type = CodeRelationType.CONTAINS if module_name else CodeRelationType.DEFINES
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=rel_type)
        )

        # If BIND(C), create a CALLS relation to the C name so the graph links
        # Fortran ↔ C/C++ code
        if bind_name:
            kg.add_relation(
                Relation(
                    source=ent.qualified_key,
                    target=bind_name,
                    relation_type=CodeRelationType.CALLS,
                    metadata={"interop": "bind_c"},
                )
            )

        # Extract USE statements and CALL statements inside the subroutine
        self._extract_uses(node, source, rel_path, kg, ent.qualified_key)
        self._extract_calls(node, source, kg, ent.qualified_key)

    # ------------------------------------------------------------------
    # Functions
    # ------------------------------------------------------------------

    def _handle_function(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        module_name: str,
    ) -> None:
        func_name = self._find_child_text(node, "name", source)
        if not func_name:
            stmt = self._find_child_node(node, "function_statement")
            if stmt:
                func_name = self._find_child_text(stmt, "name", source)
        if not func_name:
            return

        qualified = f"{module_name}::{func_name}" if module_name else func_name
        sig = self._first_line(node, source)

        bind_name = self._extract_bind_c_name(node, source)
        metadata: dict[str, str] = {}
        if bind_name:
            metadata["bind_c"] = bind_name

        ent = Entity(
            name=qualified,
            entity_type=CodeEntityType.FUNCTION,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            metadata=metadata,
        )
        kg.add_entity(ent)

        rel_type = CodeRelationType.CONTAINS if module_name else CodeRelationType.DEFINES
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=rel_type)
        )

        if bind_name:
            kg.add_relation(
                Relation(
                    source=ent.qualified_key,
                    target=bind_name,
                    relation_type=CodeRelationType.CALLS,
                    metadata={"interop": "bind_c"},
                )
            )

        self._extract_uses(node, source, rel_path, kg, ent.qualified_key)
        self._extract_calls(node, source, kg, ent.qualified_key)

    # ------------------------------------------------------------------
    # USE statements (module imports)
    # ------------------------------------------------------------------

    def _handle_use(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        mod_name_node = self._find_child_node(node, "module_name")
        if not mod_name_node:
            return
        mod_name = source[mod_name_node.start_byte : mod_name_node.end_byte].decode(errors="replace").strip()

        ent = Entity(
            name=mod_name,
            entity_type=CodeEntityType.IMPORT,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=self._node_text(node, source),
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.IMPORTS)
        )
        # Also add an IMPORTS relation to the module name itself (for cross-linking)
        kg.add_relation(
            Relation(source=parent_key, target=mod_name, relation_type=CodeRelationType.IMPORTS)
        )

    def _extract_uses(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        """Find all USE statements inside a subroutine/function body."""
        for child in node.children:
            if child.type == "use_statement":
                self._handle_use(child, source, rel_path, kg, parent_key)

    # ------------------------------------------------------------------
    # #include directives
    # ------------------------------------------------------------------

    def _handle_include(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        text = self._node_text(node, source)
        ent = Entity(
            name=text,
            entity_type=CodeEntityType.IMPORT,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=text,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.IMPORTS)
        )

    # ------------------------------------------------------------------
    # CALL / call_expression extraction
    # ------------------------------------------------------------------

    def _extract_calls(
        self, node: Node, source: bytes, kg: KnowledgeGraph, caller_key: str
    ) -> None:
        """Recursively find CALL statements and function-call expressions."""
        for child in node.children:
            if child.type == "subroutine_call":
                callee = self._get_call_name(child, source)
                if callee:
                    kg.add_relation(
                        Relation(
                            source=caller_key,
                            target=callee,
                            relation_type=CodeRelationType.CALLS,
                        )
                    )
            elif child.type == "call_expression":
                callee = self._get_call_expr_name(child, source)
                if callee:
                    kg.add_relation(
                        Relation(
                            source=caller_key,
                            target=callee,
                            relation_type=CodeRelationType.CALLS,
                        )
                    )
            # Recurse into compound statements (if, do, etc.)
            if child.type not in ("subroutine", "function", "module"):
                self._extract_calls(child, source, kg, caller_key)

    # ------------------------------------------------------------------
    # BIND(C) interop detection
    # ------------------------------------------------------------------

    def _extract_bind_c_name(self, node: Node, source: bytes) -> str:
        """If a subroutine/function has BIND(C, NAME='...'), return the C name."""
        for child in node.children:
            if child.type == "language_binding":
                return self._parse_bind_name(child, source)
            # Also check inside subroutine_statement / function_statement
            if child.type in ("subroutine_statement", "function_statement"):
                for grandchild in child.children:
                    if grandchild.type == "language_binding":
                        return self._parse_bind_name(grandchild, source)
        return ""

    def _parse_bind_name(self, binding_node: Node, source: bytes) -> str:
        """Extract the NAME= value from a language_binding node."""
        for child in binding_node.children:
            if child.type == "keyword_argument":
                # keyword_argument: identifier = string_literal
                for gc in child.children:
                    if gc.type == "string_literal":
                        raw = source[gc.start_byte : gc.end_byte].decode(errors="replace")
                        return raw.strip("'\"")
        # BIND(C) without explicit NAME= — the C name is the Fortran name lowercased
        text = self._node_text(binding_node, source).upper()
        if "BIND" in text and "NAME" not in text.upper():
            # Just BIND(C) — return empty, caller should use Fortran name
            return ""
        return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_child_node(node: Node, child_type: str) -> Node | None:
        for c in node.children:
            if c.type == child_type:
                return c
        return None

    @staticmethod
    def _find_child_text(node: Node, child_type: str, source: bytes) -> str:
        for c in node.children:
            if c.type == child_type:
                return source[c.start_byte : c.end_byte].decode(errors="replace").strip()
        return ""

    @staticmethod
    def _node_text(node: Node, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode(errors="replace").strip()

    @staticmethod
    def _first_line(node: Node, source: bytes) -> str:
        text = source[node.start_byte : node.end_byte].decode(errors="replace")
        return text.split("\n")[0].strip()

    @staticmethod
    def _get_call_name(call_node: Node, source: bytes) -> str:
        """Extract the callee name from a subroutine_call node (CALL FOO(...))."""
        for child in call_node.children:
            if child.type == "identifier":
                return source[child.start_byte : child.end_byte].decode(errors="replace").strip()
        return ""

    @staticmethod
    def _get_call_expr_name(call_expr_node: Node, source: bytes) -> str:
        """Extract the function name from a call_expression node (FOO(...))."""
        for child in call_expr_node.children:
            if child.type == "identifier":
                return source[child.start_byte : child.end_byte].decode(errors="replace").strip()
            if child.type == "derived_type_member_expression":
                return source[child.start_byte : child.end_byte].decode(errors="replace").strip()
        return ""
