"""Tree-sitter based TypeScript / JavaScript parser.

Handles .ts, .tsx, .js, .jsx files. Extracts classes, functions/arrow functions,
imports, exports, interfaces (TS), and call expressions.
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser, Node

from kg_rag.models import (
    CodeEntityType,
    CodeRelationType,
    Entity,
    KnowledgeGraph,
    Relation,
)
from kg_rag.parsers.base import BaseCodeParser

JS_LANGUAGE = Language(tsjs.language())
TS_LANGUAGE = Language(tsts.language_typescript())
TSX_LANGUAGE = Language(tsts.language_tsx())


class TypeScriptParser(BaseCodeParser):
    language = "typescript"

    def __init__(self, variant: str = "typescript") -> None:
        if variant == "javascript":
            self._parser = Parser(JS_LANGUAGE)
            self.language = "javascript"
        elif variant == "tsx":
            self._parser = Parser(TSX_LANGUAGE)
        else:
            self._parser = Parser(TS_LANGUAGE)

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
        class_name: str = "",
    ) -> None:
        for child in node.children:
            if child.type in ("import_statement", "import"):
                self._handle_import(child, source, rel_path, kg, parent_key)
            elif child.type == "class_declaration":
                self._handle_class(child, source, rel_path, kg, parent_key)
            elif child.type == "interface_declaration":
                self._handle_interface(child, source, rel_path, kg, parent_key)
            elif child.type in ("function_declaration", "generator_function_declaration"):
                self._handle_function(child, source, rel_path, kg, parent_key, class_name)
            elif child.type == "method_definition":
                self._handle_method(child, source, rel_path, kg, parent_key, class_name)
            elif child.type in ("lexical_declaration", "variable_declaration"):
                self._handle_variable_decl(child, source, rel_path, kg, parent_key, class_name)
            elif child.type == "export_statement":
                # Walk inside exports
                self._walk(child, source, rel_path, kg, parent_key, class_name)
            elif child.type == "enum_declaration":
                self._handle_enum(child, source, rel_path, kg, parent_key)
            elif child.type == "class_body":
                self._walk(child, source, rel_path, kg, parent_key, class_name)

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------

    def _handle_import(
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
    # Classes
    # ------------------------------------------------------------------

    def _handle_class(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        name = self._find_child_text(node, "type_identifier", source)
        if not name:
            name = self._find_child_text(node, "identifier", source)
        if not name:
            return

        sig = self._first_line(node, source)
        ent = Entity(
            name=name,
            entity_type=CodeEntityType.CLASS,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.DEFINES)
        )

        # Inheritance (extends / implements)
        self._extract_heritage(node, source, ent.qualified_key, kg)

        # Walk class body
        body = self._find_child_node(node, "class_body")
        if body:
            self._walk(body, source, rel_path, kg, parent_key=ent.qualified_key, class_name=name)

    # ------------------------------------------------------------------
    # Interfaces (TypeScript)
    # ------------------------------------------------------------------

    def _handle_interface(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        name = self._find_child_text(node, "type_identifier", source)
        if not name:
            name = self._find_child_text(node, "identifier", source)
        if not name:
            return

        sig = self._first_line(node, source)
        ent = Entity(
            name=name,
            entity_type=CodeEntityType.INTERFACE,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.DEFINES)
        )

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
        class_name: str,
    ) -> None:
        func_name = self._find_child_text(node, "identifier", source)
        if not func_name:
            return

        qualified = f"{class_name}.{func_name}" if class_name else func_name
        sig = self._first_line(node, source)
        etype = CodeEntityType.METHOD if class_name else CodeEntityType.FUNCTION

        ent = Entity(
            name=qualified,
            entity_type=etype,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
        )
        kg.add_entity(ent)

        rel_type = CodeRelationType.CONTAINS if class_name else CodeRelationType.DEFINES
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=rel_type)
        )

        # Extract calls
        body = self._find_child_node(node, "statement_block")
        if body:
            self._extract_calls(body, source, kg, ent.qualified_key)

    # ------------------------------------------------------------------
    # Methods (inside class body)
    # ------------------------------------------------------------------

    def _handle_method(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        class_name: str,
    ) -> None:
        # method name can be property_identifier or computed_property_name
        name = self._find_child_text(node, "property_identifier", source)
        if not name:
            name = self._find_child_text(node, "identifier", source)
        if not name:
            return

        qualified = f"{class_name}.{name}" if class_name else name
        sig = self._first_line(node, source)

        ent = Entity(
            name=qualified,
            entity_type=CodeEntityType.METHOD,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.CONTAINS)
        )

        body = self._find_child_node(node, "statement_block")
        if body:
            self._extract_calls(body, source, kg, ent.qualified_key)

    # ------------------------------------------------------------------
    # Variable declarations (catches arrow functions: const foo = () => {})
    # ------------------------------------------------------------------

    def _handle_variable_decl(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        class_name: str,
    ) -> None:
        for child in node.children:
            if child.type == "variable_declarator":
                name_node = self._find_child_node(child, "identifier")
                value_node = self._find_child_node(child, "arrow_function")
                if not value_node:
                    value_node = self._find_child_node(child, "function_expression")
                if name_node and value_node:
                    func_name = self._node_text(name_node, source)
                    qualified = f"{class_name}.{func_name}" if class_name else func_name
                    sig = self._first_line(node, source)

                    ent = Entity(
                        name=qualified,
                        entity_type=CodeEntityType.FUNCTION,
                        language=self.language,
                        file_path=rel_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        signature=sig,
                    )
                    kg.add_entity(ent)
                    kg.add_relation(
                        Relation(
                            source=parent_key,
                            target=ent.qualified_key,
                            relation_type=CodeRelationType.DEFINES,
                        )
                    )

                    body = self._find_child_node(value_node, "statement_block")
                    if body:
                        self._extract_calls(body, source, kg, ent.qualified_key)

    # ------------------------------------------------------------------
    # Enums (TypeScript)
    # ------------------------------------------------------------------

    def _handle_enum(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        name = self._find_child_text(node, "identifier", source)
        if not name:
            return
        ent = Entity(
            name=name,
            entity_type=CodeEntityType.ENUM,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=self._first_line(node, source),
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.DEFINES)
        )

    # ------------------------------------------------------------------
    # Inheritance / heritage
    # ------------------------------------------------------------------

    def _extract_heritage(
        self, node: Node, source: bytes, entity_key: str, kg: KnowledgeGraph
    ) -> None:
        """Extract extends/implements from class_heritage node."""
        for child in node.children:
            if child.type in ("class_heritage", "extends_clause"):
                for inner in child.children:
                    if inner.type in ("type_identifier", "identifier"):
                        base = self._node_text(inner, source)
                        kg.add_relation(
                            Relation(
                                source=entity_key,
                                target=base,
                                relation_type=CodeRelationType.INHERITS,
                            )
                        )
            elif child.type == "implements_clause":
                for inner in child.children:
                    if inner.type in ("type_identifier", "identifier"):
                        iface = self._node_text(inner, source)
                        kg.add_relation(
                            Relation(
                                source=entity_key,
                                target=iface,
                                relation_type=CodeRelationType.IMPLEMENTS,
                            )
                        )

    # ------------------------------------------------------------------
    # Call extraction
    # ------------------------------------------------------------------

    def _extract_calls(
        self, node: Node, source: bytes, kg: KnowledgeGraph, caller_key: str
    ) -> None:
        for child in node.children:
            if child.type == "call_expression":
                callee = self._get_call_name(child, source)
                if callee:
                    kg.add_relation(
                        Relation(
                            source=caller_key,
                            target=callee,
                            relation_type=CodeRelationType.CALLS,
                        )
                    )
            if child.type not in ("class_declaration", "function_declaration", "arrow_function"):
                self._extract_calls(child, source, kg, caller_key)

    @staticmethod
    def _get_call_name(call_node: Node, source: bytes) -> str:
        for child in call_node.children:
            if child.type == "identifier":
                return source[child.start_byte : child.end_byte].decode(errors="replace")
            if child.type == "member_expression":
                return source[child.start_byte : child.end_byte].decode(errors="replace")
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
