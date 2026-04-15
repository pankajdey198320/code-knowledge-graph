"""Tree-sitter based C# source parser."""

from __future__ import annotations

from pathlib import Path

import tree_sitter_c_sharp as tscsharp
from tree_sitter import Language, Parser, Node

from kg_rag.models import (
    CodeEntityType,
    CodeRelationType,
    Entity,
    KnowledgeGraph,
    Relation,
)
from kg_rag.parsers.base import BaseCodeParser

CSHARP_LANGUAGE = Language(tscsharp.language())


class CSharpParser(BaseCodeParser):
    language = "csharp"

    def __init__(self) -> None:
        self._parser = Parser(CSHARP_LANGUAGE)

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
            if child.type == "using_directive":
                self._handle_using(child, source, rel_path, kg, parent_key)
            elif child.type in ("namespace_declaration", "file_scoped_namespace_declaration"):
                self._handle_namespace(child, source, rel_path, kg, parent_key)
            elif child.type == "class_declaration":
                self._handle_class(child, source, rel_path, kg, parent_key)
            elif child.type == "struct_declaration":
                self._handle_struct(child, source, rel_path, kg, parent_key)
            elif child.type == "interface_declaration":
                self._handle_interface(child, source, rel_path, kg, parent_key)
            elif child.type == "enum_declaration":
                self._handle_enum(child, source, rel_path, kg, parent_key)
            elif child.type == "method_declaration":
                self._handle_method(child, source, rel_path, kg, parent_key, class_name)
            elif child.type == "constructor_declaration":
                self._handle_method(child, source, rel_path, kg, parent_key, class_name)
            elif child.type == "property_declaration":
                self._handle_property(child, source, rel_path, kg, parent_key, class_name)

    # --- using directives -------------------------------------------------

    def _handle_using(
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
        ns_name = source[name_node.start_byte : name_node.end_byte].decode() if name_node else "<global>"

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

        # Walk body declarations
        body = node.child_by_field_name("body")
        container = body if body else node
        self._walk(container, source, rel_path, kg, parent_key=ent.qualified_key)

    # --- classes ----------------------------------------------------------

    def _handle_class(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        cls_name = source[name_node.start_byte : name_node.end_byte].decode()

        first_line = source[node.start_byte : node.end_byte].decode(errors="replace").split("\n")[0]
        docstring = self._get_xml_doc(node, source)

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

        # Base types
        bases = node.child_by_field_name("bases")
        if bases:
            for child in bases.children:
                if child.type not in (":", ",", "{", "}"):
                    base_name = source[child.start_byte : child.end_byte].decode(errors="replace")
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

    # --- structs ----------------------------------------------------------

    def _handle_struct(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        struct_name = source[name_node.start_byte : name_node.end_byte].decode()
        ent = Entity(
            name=struct_name,
            entity_type=CodeEntityType.STRUCT,
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
            self._walk(body, source, rel_path, kg, parent_key=ent.qualified_key, class_name=struct_name)

    # --- interfaces -------------------------------------------------------

    def _handle_interface(
        self, node: Node, source: bytes, rel_path: str, kg: KnowledgeGraph, parent_key: str
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        iface_name = source[name_node.start_byte : name_node.end_byte].decode()
        ent = Entity(
            name=iface_name,
            entity_type=CodeEntityType.INTERFACE,
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
            self._walk(body, source, rel_path, kg, parent_key=ent.qualified_key, class_name=iface_name)

    # --- methods ----------------------------------------------------------

    def _handle_method(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        class_name: str,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        method_name = source[name_node.start_byte : name_node.end_byte].decode()
        qualified = f"{class_name}.{method_name}" if class_name else method_name

        first_line = source[node.start_byte : node.end_byte].decode(errors="replace").split("\n")[0]
        docstring = self._get_xml_doc(node, source)

        ent = Entity(
            name=qualified,
            entity_type=CodeEntityType.METHOD,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=first_line.strip(),
            docstring=docstring,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.CONTAINS)
        )

        # Extract calls
        body = node.child_by_field_name("body")
        if body:
            self._extract_calls(body, source, ent.qualified_key, kg)

    # --- properties -------------------------------------------------------

    def _handle_property(
        self,
        node: Node,
        source: bytes,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        class_name: str,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        prop_name = source[name_node.start_byte : name_node.end_byte].decode()
        qualified = f"{class_name}.{prop_name}" if class_name else prop_name

        ent = Entity(
            name=qualified,
            entity_type=CodeEntityType.PROPERTY,
            language=self.language,
            file_path=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(source=parent_key, target=ent.qualified_key, relation_type=CodeRelationType.CONTAINS)
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

    def _extract_calls(self, node: Node, source: bytes, caller_key: str, kg: KnowledgeGraph) -> None:
        if node.type == "invocation_expression":
            func = node.child_by_field_name("function")
            if func:
                callee = source[func.start_byte : func.end_byte].decode(errors="replace")
                kg.add_relation(
                    Relation(source=caller_key, target=callee, relation_type=CodeRelationType.CALLS)
                )
        for child in node.children:
            self._extract_calls(child, source, caller_key, kg)

    @staticmethod
    def _get_xml_doc(node: Node, source: bytes) -> str:
        """Extract XML doc comments (/// ...) preceding a node."""
        # Look at sibling nodes before this one for comment nodes
        if node.prev_named_sibling and node.prev_named_sibling.type == "comment":
            return source[
                node.prev_named_sibling.start_byte : node.prev_named_sibling.end_byte
            ].decode(errors="replace").strip()
        return ""
