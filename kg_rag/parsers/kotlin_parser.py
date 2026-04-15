"""Tree-sitter based Kotlin source parser.

Extracts classes, objects, interfaces, functions, properties, imports,
and inheritance/delegation — suitable for TeamCity Kotlin DSL configs
and general Kotlin code.
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_kotlin as tskotlin
from tree_sitter import Language, Parser, Node

from kg_rag.models import (
    CodeEntityType,
    CodeRelationType,
    Entity,
    KnowledgeGraph,
    Relation,
)
from kg_rag.parsers.base import BaseCodeParser

KOTLIN_LANGUAGE = Language(tskotlin.language())


class KotlinParser(BaseCodeParser):
    language = "kotlin"

    def __init__(self) -> None:
        self._parser = Parser(KOTLIN_LANGUAGE)

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
            if child.type == "package_header":
                self._handle_package(child, source, rel_path, kg, parent_key)
            elif child.type == "import":
                self._handle_import(child, source, rel_path, kg, parent_key)
            elif child.type == "class_declaration":
                self._handle_class(child, source, rel_path, kg, parent_key)
            elif child.type == "object_declaration":
                self._handle_object(child, source, rel_path, kg, parent_key)
            elif child.type == "function_declaration":
                self._handle_function(child, source, rel_path, kg, parent_key, class_name)
            elif child.type == "property_declaration":
                self._handle_property(child, source, rel_path, kg, parent_key, class_name)

    # ------------------------------------------------------------------
    # Package
    # ------------------------------------------------------------------

    def _handle_package(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        pkg_name = self._find_identifier(node, source)
        if not pkg_name:
            return
        ent = Entity(
            name=pkg_name,
            entity_type=CodeEntityType.PACKAGE,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.BELONGS_TO)
        )

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------

    def _handle_import(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        text = self._node_text(node, source)
        # Extract the import path (after "import ")
        import_path = text.replace("import ", "").strip()
        ent = Entity(
            name=import_path,
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
    # Classes / interfaces / enums
    # ------------------------------------------------------------------

    def _handle_class(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        name = self._find_child_text(node, "identifier", source)
        if not name:
            return

        # Determine kind: class, interface, enum
        etype = CodeEntityType.CLASS
        for child in node.children:
            if child.type == "interface":
                etype = CodeEntityType.INTERFACE
                break
            if child.type == "enum":
                etype = CodeEntityType.ENUM
                break

        sig = self._first_line(node, source)
        ent = Entity(
            name=name,
            entity_type=etype,
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

        # Inheritance / delegation
        self._extract_supertypes(node, source, ent.qualified_key, kg)

        # Walk class body
        body = self._find_child_node(node, "class_body")
        if not body:
            body = self._find_child_node(node, "enum_class_body")
        if body:
            self._walk(body, source, rel_path, kg, parent_key=ent.qualified_key, class_name=name)

    # ------------------------------------------------------------------
    # Objects (Kotlin object declarations — singletons)
    # ------------------------------------------------------------------

    def _handle_object(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
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
            metadata={"kind": "object"},
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.DEFINES)
        )

        self._extract_supertypes(node, source, ent.qualified_key, kg)

        body = self._find_child_node(node, "class_body")
        if body:
            self._walk(body, source, rel_path, kg, parent_key=ent.qualified_key, class_name=name)

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

        # Extract calls in function body
        body = self._find_child_node(node, "function_body")
        if body:
            self._extract_calls(body, source, kg, ent.qualified_key)

    # ------------------------------------------------------------------
    # Properties (val / var)
    # ------------------------------------------------------------------

    def _handle_property(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        class_name: str,
    ) -> None:
        # Get the variable name from variable_declaration child
        var_decl = self._find_child_node(node, "variable_declaration")
        if not var_decl:
            return
        prop_name = self._find_child_text(var_decl, "identifier", source)
        if not prop_name:
            return

        qualified = f"{class_name}.{prop_name}" if class_name else prop_name
        sig = self._first_line(node, source)

        ent = Entity(
            name=qualified,
            entity_type=CodeEntityType.PROPERTY,
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

    # ------------------------------------------------------------------
    # Inheritance extraction
    # ------------------------------------------------------------------

    def _extract_supertypes(
        self, node: Node, source: bytes, entity_key: str, kg: KnowledgeGraph
    ) -> None:
        """Extract supertype references from delegation_specifiers."""
        for child in node.children:
            if child.type == "delegation_specifiers":
                for spec in child.children:
                    if spec.type == "delegation_specifier":
                        # Get the type name
                        for inner in spec.children:
                            if inner.type == "user_type":
                                type_name = self._node_text(inner, source)
                                kg.add_relation(
                                    Relation(
                                        source=entity_key,
                                        target=type_name,
                                        relation_type=CodeRelationType.INHERITS,
                                    )
                                )
                            elif inner.type == "constructor_invocation":
                                ctor_type = self._find_child_node(inner, "user_type")
                                if ctor_type:
                                    type_name = self._node_text(ctor_type, source)
                                    kg.add_relation(
                                        Relation(
                                            source=entity_key,
                                            target=type_name,
                                            relation_type=CodeRelationType.INHERITS,
                                        )
                                    )

    # ------------------------------------------------------------------
    # Call extraction
    # ------------------------------------------------------------------

    def _extract_calls(
        self, node: Node, source: bytes, kg: KnowledgeGraph, caller_key: str
    ) -> None:
        """Recursively find call_expression nodes."""
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
            # Recurse but don't enter nested class/function declarations
            if child.type not in ("class_declaration", "object_declaration", "function_declaration"):
                self._extract_calls(child, source, kg, caller_key)

    @staticmethod
    def _get_call_name(call_node: Node, source: bytes) -> str:
        """Extract function name from a call_expression."""
        for child in call_node.children:
            if child.type == "identifier":
                return source[child.start_byte : child.end_byte].decode(errors="replace")
            if child.type == "navigation_expression":
                return source[child.start_byte : child.end_byte].decode(errors="replace")
        return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_identifier(self, node: Node, source: bytes) -> str:
        """Find a qualified_identifier or identifier in children."""
        for child in node.children:
            if child.type == "qualified_identifier":
                return self._node_text(child, source)
            if child.type == "identifier":
                return self._node_text(child, source)
        return ""

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
