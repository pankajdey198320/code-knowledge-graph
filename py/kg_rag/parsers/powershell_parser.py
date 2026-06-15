"""Tree-sitter based PowerShell source parser.

Extracts functions, commands/cmdlet calls, parameters, and script structure
from .ps1 and .psm1 files.
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_powershell as tsps
from tree_sitter import Language, Parser, Node

from kg_rag.models import (
    CodeEntityType,
    CodeRelationType,
    Entity,
    KnowledgeGraph,
    Relation,
)
from kg_rag.parsers.base import BaseCodeParser

PS_LANGUAGE = Language(tsps.language())


class PowerShellParser(BaseCodeParser):
    language = "powershell"

    def __init__(self) -> None:
        self._parser = Parser(PS_LANGUAGE)

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
    ) -> None:
        for child in node.children:
            if child.type == "function_statement":
                self._handle_function(child, source, rel_path, kg, parent_key)
            elif child.type == "statement_list":
                self._walk(child, source, rel_path, kg, parent_key)

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
    ) -> None:
        func_name = self._find_child_text(node, "function_name", source)
        if not func_name:
            return

        sig = self._first_line(node, source)

        # Check for param block to build a richer signature
        script_block = self._find_child_node(node, "script_block")
        params = self._extract_params(script_block, source) if script_block else []
        if params:
            sig = f"function {func_name}({', '.join(params)})"

        # Check for CmdletBinding attribute
        metadata: dict[str, str] = {}
        if script_block:
            attrs = self._extract_attributes(script_block, source)
            if attrs:
                metadata["attributes"] = ", ".join(attrs)

        ent = Entity(
            name=func_name,
            entity_type=CodeEntityType.FUNCTION,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            metadata=metadata,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.DEFINES)
        )

        # Extract command calls inside function body
        if script_block:
            self._extract_calls(script_block, source, kg, ent.qualified_key)

    # ------------------------------------------------------------------
    # Parameter extraction
    # ------------------------------------------------------------------

    def _extract_params(self, node: Node, source: bytes) -> list[str]:
        """Extract parameter names from a param_block inside a script_block."""
        params: list[str] = []
        self._find_params_recursive(node, source, params)
        return params

    def _find_params_recursive(self, node: Node, source: bytes, params: list[str]) -> None:
        if node.type == "script_parameter":
            var = self._find_child_node(node, "variable")
            if var:
                params.append(self._node_text(var, source))
            return
        for child in node.children:
            if child.type in ("param_block", "parameter_list", "script_parameter"):
                self._find_params_recursive(child, source, params)

    # ------------------------------------------------------------------
    # Attribute extraction
    # ------------------------------------------------------------------

    def _extract_attributes(self, node: Node, source: bytes) -> list[str]:
        """Find [CmdletBinding()], [Parameter()] etc."""
        attrs: list[str] = []
        self._find_attrs_recursive(node, source, attrs, depth=0)
        return attrs

    def _find_attrs_recursive(self, node: Node, source: bytes, attrs: list[str], depth: int) -> None:
        if depth > 4:
            return
        if node.type == "attribute":
            name_node = self._find_child_node(node, "attribute_name")
            if name_node:
                attrs.append(self._node_text(name_node, source))
            return
        for child in node.children:
            self._find_attrs_recursive(child, source, attrs, depth + 1)

    # ------------------------------------------------------------------
    # Command/call extraction
    # ------------------------------------------------------------------

    def _extract_calls(
        self, node: Node, source: bytes, kg: KnowledgeGraph, caller_key: str
    ) -> None:
        """Recursively find command invocations (cmdlet/function calls)."""
        for child in node.children:
            if child.type == "command":
                cmd_name = self._get_command_name(child, source)
                if cmd_name:
                    kg.add_relation(
                        Relation(
                            source=caller_key,
                            target=cmd_name,
                            relation_type=CodeRelationType.CALLS,
                        )
                    )
            elif child.type == "invokation_expression":
                callee = self._get_invocation_name(child, source)
                if callee:
                    kg.add_relation(
                        Relation(
                            source=caller_key,
                            target=callee,
                            relation_type=CodeRelationType.CALLS,
                        )
                    )
            # Recurse but don't enter nested function definitions
            if child.type != "function_statement":
                self._extract_calls(child, source, kg, caller_key)

    @staticmethod
    def _get_command_name(cmd_node: Node, source: bytes) -> str:
        """Extract command name from a command node."""
        for child in cmd_node.children:
            if child.type == "command_name":
                return source[child.start_byte : child.end_byte].decode(errors="replace").strip()
            if child.type == "command_name_expr":
                return source[child.start_byte : child.end_byte].decode(errors="replace").strip()
        return ""

    @staticmethod
    def _get_invocation_name(inv_node: Node, source: bytes) -> str:
        """Extract target from an invokation_expression (& or .)."""
        for child in inv_node.children:
            if child.type in ("command_name", "command_name_expr", "variable", "member_access"):
                return source[child.start_byte : child.end_byte].decode(errors="replace").strip()
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
