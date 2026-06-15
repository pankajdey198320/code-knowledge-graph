"""Tree-sitter based Python source parser."""

from __future__ import annotations

from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node

from kg_rag.models import (
    CodeEntityType,
    CodeRelationType,
    Entity,
    KnowledgeGraph,
    Relation,
)
from kg_rag.parsers.base import BaseCodeParser

PY_LANGUAGE = Language(tspython.language())


class PythonParser(BaseCodeParser):
    language = "python"

    def __init__(self) -> None:
        self._parser = Parser(PY_LANGUAGE)

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

    def _walk(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        class_name: str = "",
    ) -> None:
        for child in node.children:
            if child.type == "import_statement" or child.type == "import_from_statement":
                self._handle_import(child, source, rel_path, kg, parent_key)
            elif child.type == "class_definition":
                self._handle_class(child, source, rel_path, kg, parent_key)
            elif child.type == "function_definition":
                self._handle_function(child, source, rel_path, kg, parent_key, class_name)
            elif child.type == "decorated_definition":
                # unwrap decorator – the actual definition is the last child
                for sub in child.children:
                    if sub.type in ("class_definition", "function_definition"):
                        if sub.type == "class_definition":
                            self._handle_class(sub, source, rel_path, kg, parent_key)
                        else:
                            self._handle_function(sub, source, rel_path, kg, parent_key, class_name)

    # --- imports ----------------------------------------------------------

    def _handle_import(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        text = source[node.start_byte : node.end_byte].decode(errors="replace")
        ent = Entity(
            name=text.strip(),
            entity_type=CodeEntityType.IMPORT,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=text.strip(),
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.IMPORTS)
        )

    # --- classes ----------------------------------------------------------

    def _handle_class(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        cls_name = source[name_node.start_byte : name_node.end_byte].decode()

        # Extract base classes
        bases: list[str] = []
        arg_list = node.child_by_field_name("superclasses")
        if arg_list:
            for arg in arg_list.children:
                if arg.type not in ("(", ")", ","):
                    bases.append(source[arg.start_byte : arg.end_byte].decode())

        # First line as signature
        first_line = source[node.start_byte : node.end_byte].decode(errors="replace").split("\n")[0]
        docstring = self._extract_docstring(node, source)

        ent = Entity(
            name=cls_name,
            entity_type=CodeEntityType.CLASS,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=first_line.strip(),
            docstring=docstring,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.DEFINES)
        )

        # Inheritance
        for base in bases:
            kg.add_relation(
                Relation(source=ent.qualified_key, target=base, relation_type=CodeRelationType.INHERITS)
            )

        # Walk children for methods
        body = node.child_by_field_name("body")
        if body:
            self._walk(body, source, rel_path, kg, parent_key=ent.qualified_key, class_name=cls_name)

    # --- functions / methods ---------------------------------------------

    def _handle_function(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        class_name: str,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        func_name = source[name_node.start_byte : name_node.end_byte].decode()
        qualified = f"{class_name}.{func_name}" if class_name else func_name

        first_line = source[node.start_byte : node.end_byte].decode(errors="replace").split("\n")[0]
        docstring = self._extract_docstring(node, source)

        etype = CodeEntityType.METHOD if class_name else CodeEntityType.FUNCTION
        ent = Entity(
            name=qualified,
            entity_type=etype,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=first_line.strip(),
            docstring=docstring,
        )
        kg.add_entity(ent)

        rel_type = CodeRelationType.CONTAINS if class_name else CodeRelationType.DEFINES
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=rel_type)
        )

        # Detect calls inside function body
        body = node.child_by_field_name("body")
        if body:
            self._extract_calls(body, source, ent.qualified_key, kg)

    # --- utilities --------------------------------------------------------

    def _extract_calls(
        self, node: Node, source: bytes, caller_key: str, kg: KnowledgeGraph
    ) -> None:
        """Walk the AST to find function/method calls."""
        if node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee = source[func_node.start_byte : func_node.end_byte].decode(errors="replace")
                kg.add_relation(
                    Relation(
                        source=caller_key,
                        target=callee,
                        relation_type=CodeRelationType.CALLS,
                    )
                )
        for child in node.children:
            self._extract_calls(child, source, caller_key, kg)

    @staticmethod
    def _extract_docstring(node: Node, source: bytes) -> str:
        body = node.child_by_field_name("body")
        if body and body.children:
            first = body.children[0]
            if first.type == "expression_statement" and first.children:
                expr = first.children[0]
                if expr.type == "string":
                    raw = source[expr.start_byte : expr.end_byte].decode(errors="replace")
                    return raw.strip("\"'").strip()
        return ""
