"""Tree-sitter based C++ source parser."""

from __future__ import annotations

from pathlib import Path

import tree_sitter_cpp as tscpp
from tree_sitter import Language, Parser, Node

from kg_rag.models import (
    CodeEntityType,
    CodeRelationType,
    Entity,
    KnowledgeGraph,
    Relation,
)
from kg_rag.parsers.base import BaseCodeParser

CPP_LANGUAGE = Language(tscpp.language())


class CppParser(BaseCodeParser):
    language = "cpp"

    def __init__(self) -> None:
        self._parser = Parser(CPP_LANGUAGE)

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
            if child.type == "preproc_include":
                self._handle_include(child, source, rel_path, kg, parent_key)
            elif child.type == "namespace_definition":
                self._handle_namespace(child, source, rel_path, kg, parent_key)
            elif child.type in ("class_specifier", "struct_specifier"):
                self._handle_class(child, source, rel_path, kg, parent_key)
            elif child.type == "function_definition":
                self._handle_function(child, source, rel_path, kg, parent_key, class_name)
            elif child.type == "declaration":
                # Could be a forward declaration or a function declaration
                self._handle_declaration(child, source, rel_path, kg, parent_key, class_name)
            elif child.type == "enum_specifier":
                self._handle_enum(child, source, rel_path, kg, parent_key)

    # --- includes ---------------------------------------------------------

    def _handle_include(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        text = source[node.start_byte : node.end_byte].decode(errors="replace").strip()
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

    # --- namespaces -------------------------------------------------------

    def _handle_namespace(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        name_node = node.child_by_field_name("name")
        ns_name = source[name_node.start_byte : name_node.end_byte].decode() if name_node else "<anonymous>"

        ent = Entity(
            name=ns_name,
            entity_type=CodeEntityType.NAMESPACE,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.DEFINES)
        )

        body = node.child_by_field_name("body")
        if body:
            self._walk(body, source, rel_path, kg, parent_key=ent.qualified_key)

    # --- classes / structs ------------------------------------------------

    def _handle_class(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        cls_name = source[name_node.start_byte : name_node.end_byte].decode()
        etype = CodeEntityType.STRUCT if node.type == "struct_specifier" else CodeEntityType.CLASS

        first_line = source[node.start_byte : node.end_byte].decode(errors="replace").split("\n")[0]

        ent = Entity(
            name=cls_name,
            entity_type=etype,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=first_line.strip(),
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.DEFINES)
        )

        # Base classes
        for child in node.children:
            if child.type == "base_class_clause":
                for base in child.children:
                    if base.type == "type_identifier":
                        base_name = source[base.start_byte : base.end_byte].decode()
                        kg.add_relation(
                            Relation(
                                source=ent.qualified_key,
                                target=base_name,
                                relation_type=CodeRelationType.INHERITS,
                            )
                        )

        body = node.child_by_field_name("body")
        if body:
            self._walk(body, source, rel_path, kg, parent_key=ent.qualified_key, class_name=cls_name)

    # --- functions --------------------------------------------------------

    def _handle_function(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        class_name: str,
    ) -> None:
        declarator = node.child_by_field_name("declarator")
        func_name = self._extract_function_name(declarator, source)
        if not func_name:
            return

        qualified = f"{class_name}::{func_name}" if class_name else func_name
        first_line = source[node.start_byte : node.end_byte].decode(errors="replace").split("\n")[0]

        etype = CodeEntityType.METHOD if class_name else CodeEntityType.FUNCTION
        ent = Entity(
            name=qualified,
            entity_type=etype,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=first_line.strip(),
        )
        kg.add_entity(ent)

        rel_type = CodeRelationType.CONTAINS if class_name else CodeRelationType.DEFINES
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=rel_type)
        )

        # Extract calls in body
        body = node.child_by_field_name("body")
        if body:
            self._extract_calls(body, source, ent.qualified_key, kg)

    # --- declarations -----------------------------------------------------

    def _handle_declaration(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        class_name: str,
    ) -> None:
        # Check if this is a function declaration (has a function_declarator child)
        declarator = node.child_by_field_name("declarator")
        if declarator and self._has_function_declarator(declarator):
            func_name = self._extract_function_name(declarator, source)
            if func_name:
                qualified = f"{class_name}::{func_name}" if class_name else func_name
                first_line = source[node.start_byte : node.end_byte].decode(errors="replace").split("\n")[0]
                etype = CodeEntityType.METHOD if class_name else CodeEntityType.FUNCTION
                ent = Entity(
                    name=qualified,
                    entity_type=etype,
                    language=self.language,
                    file_path=rel_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    signature=first_line.strip(),
                )
                kg.add_entity(ent)
                rel_type = CodeRelationType.CONTAINS if class_name else CodeRelationType.DEFINES
                kg.add_relation(
                    Relation(source=parent_key, target=ent.qualified_key, relation_type=rel_type)
                )

    # --- enums ------------------------------------------------------------

    def _handle_enum(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        ent = Entity(
            name=source[name_node.start_byte : name_node.end_byte].decode(),
            entity_type=CodeEntityType.ENUM,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.DEFINES)
        )

    # --- utilities --------------------------------------------------------

    def _extract_function_name(self, node: Node | None, source: bytes) -> str:
        if node is None:
            return ""
        if node.type == "function_declarator":
            name_node = node.child_by_field_name("declarator")
            if name_node:
                return source[name_node.start_byte : name_node.end_byte].decode(errors="replace")
        # Recurse into pointer/reference declarators
        for child in (node.children if node else []):
            name = self._extract_function_name(child, source)
            if name:
                return name
        return ""

    @staticmethod
    def _has_function_declarator(node: Node) -> bool:
        if node.type == "function_declarator":
            return True
        return any(CppParser._has_function_declarator(c) for c in node.children)

    def _extract_calls(self, node: Node, source: bytes, caller_key: str, kg: KnowledgeGraph) -> None:
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func:
                callee = source[func.start_byte : func.end_byte].decode(errors="replace")
                kg.add_relation(
                    Relation(source=caller_key, target=callee, relation_type=CodeRelationType.CALLS)
                )
        for child in node.children:
            self._extract_calls(child, source, caller_key, kg)
