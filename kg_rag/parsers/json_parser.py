"""Parser for JSON and JSON Schema files.

Extracts schema definitions, object properties, types, enums, and $ref relationships
from .json files, particularly JSON Schema documents.
"""

from __future__ import annotations

import json
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


class JSONParser(BaseCodeParser):
    language = "json"

    def parse_file(self, file_path: Path, repo_root: Path) -> KnowledgeGraph:
        source = self._read_source(file_path).decode("utf-8", errors="replace")
        rel_path = self._relative(file_path, repo_root)

        kg = KnowledgeGraph()
        file_ent = self._make_file_entity(rel_path)
        kg.add_entity(file_ent)

        try:
            data = json.loads(source)
        except json.JSONDecodeError:
            # Not valid JSON, just return the file entity
            return kg

        # Detect if this is a JSON Schema
        is_schema = self._is_json_schema(data)

        if is_schema:
            self._parse_json_schema(data, rel_path, kg, file_ent)
        else:
            self._parse_generic_json(data, rel_path, kg, file_ent)

        return kg

    # ------------------------------------------------------------------
    # Schema detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_json_schema(data: dict) -> bool:
        """Check if this looks like a JSON Schema document."""
        if not isinstance(data, dict):
            return False
        
        # Common JSON Schema indicators
        indicators = [
            "$schema" in data,
            "$id" in data,
            "definitions" in data,
            "properties" in data and "type" in data,
            "$defs" in data,
            "allOf" in data or "anyOf" in data or "oneOf" in data,
        ]
        
        return any(indicators)

    # ------------------------------------------------------------------
    # JSON Schema parsing
    # ------------------------------------------------------------------

    def _parse_json_schema(
        self,
        data: dict,
        rel_path: str,
        kg: KnowledgeGraph,
        file_ent: Entity,
    ) -> None:
        """Parse JSON Schema document."""
        # Extract schema metadata
        schema_id = data.get("$id") or data.get("id") or rel_path
        schema_title = data.get("title", "")
        schema_desc = data.get("description", "")
        
        # Create schema entity
        schema_ent = Entity(
            name=schema_title or schema_id,
            entity_type=CodeEntityType.INTERFACE,
            language=self.language,
            file_path=rel_path,
            line_start=1,
            line_end=1,
            signature=f"Schema: {schema_title or schema_id}",
            docstring=schema_desc,
            metadata={
                "$schema": data.get("$schema", ""),
                "type": data.get("type", ""),
            },
        )
        kg.add_entity(schema_ent)
        kg.add_relation(
            Relation(
                source=file_ent.qualified_key,
                target=schema_ent.qualified_key,
                relation_type=CodeRelationType.DEFINES,
            )
        )

        # Parse definitions/defs
        definitions = data.get("definitions") or data.get("$defs") or {}
        for def_name, def_schema in definitions.items():
            self._parse_schema_definition(
                def_name, def_schema, rel_path, kg, schema_ent.qualified_key
            )

        # Parse top-level properties if present
        if "properties" in data:
            self._parse_properties(
                data.get("properties", {}),
                rel_path,
                kg,
                schema_ent.qualified_key,
                parent_name=schema_title or "root",
            )

        # Extract $ref relationships
        self._extract_refs(data, kg, schema_ent.qualified_key)

    def _parse_schema_definition(
        self,
        name: str,
        schema: dict,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
    ) -> None:
        """Parse a schema definition (from definitions or $defs)."""
        if not isinstance(schema, dict):
            return

        schema_type = schema.get("type", "object")
        description = schema.get("description", "")
        title = schema.get("title", name)

        # Determine entity type based on schema type
        if schema_type == "object" or "properties" in schema:
            entity_type = CodeEntityType.CLASS
        elif schema_type == "string" and "enum" in schema:
            entity_type = CodeEntityType.ENUM
        else:
            entity_type = CodeEntityType.STRUCT

        ent = Entity(
            name=name,
            entity_type=entity_type,
            language=self.language,
            file_path=rel_path,
            line_start=1,
            line_end=1,
            signature=f"{title}: {schema_type}",
            docstring=description,
            metadata={
                "schema_type": schema_type,
                "required": schema.get("required", []),
            },
        )
        kg.add_entity(ent)
        kg.add_relation(
            Relation(
                source=parent_key,
                target=ent.qualified_key,
                relation_type=CodeRelationType.DEFINES,
            )
        )

        # Parse properties if it's an object
        if "properties" in schema:
            self._parse_properties(
                schema["properties"], rel_path, kg, ent.qualified_key, parent_name=name
            )

        # Parse enum values
        if "enum" in schema:
            enum_values = schema["enum"]
            ent.metadata["enum_values"] = enum_values

    def _parse_properties(
        self,
        properties: dict,
        rel_path: str,
        kg: KnowledgeGraph,
        parent_key: str,
        parent_name: str = "",
    ) -> None:
        """Parse object properties in a schema."""
        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                continue

            prop_type = prop_schema.get("type", "any")
            prop_desc = prop_schema.get("description", "")
            
            # Handle array types
            if prop_type == "array" and "items" in prop_schema:
                items = prop_schema["items"]
                if isinstance(items, dict):
                    item_type = items.get("type", "object")
                    prop_type = f"array<{item_type}>"

            ent = Entity(
                name=f"{parent_name}.{prop_name}" if parent_name else prop_name,
                entity_type=CodeEntityType.PROPERTY,
                language=self.language,
                file_path=rel_path,
                line_start=1,
                line_end=1,
                signature=f"{prop_name}: {prop_type}",
                docstring=prop_desc,
                metadata={
                    "property_type": prop_type,
                    "required": prop_name in prop_schema.get("required", []),
                },
            )
            kg.add_entity(ent)
            kg.add_relation(
                Relation(
                    source=parent_key,
                    target=ent.qualified_key,
                    relation_type=CodeRelationType.CONTAINS,
                )
            )

    def _extract_refs(
        self,
        data: dict | list,
        kg: KnowledgeGraph,
        source_key: str,
    ) -> None:
        """Recursively extract $ref references."""
        if isinstance(data, dict):
            if "$ref" in data:
                ref_target = data["$ref"]
                # Extract the name from the reference (e.g., "#/definitions/MyType" -> "MyType")
                ref_name = ref_target.split("/")[-1] if "/" in ref_target else ref_target
                kg.add_relation(
                    Relation(
                        source=source_key,
                        target=ref_name,
                        relation_type=CodeRelationType.IMPORTS,
                        metadata={"$ref": ref_target},
                    )
                )
            
            for value in data.values():
                self._extract_refs(value, kg, source_key)
        
        elif isinstance(data, list):
            for item in data:
                self._extract_refs(item, kg, source_key)

    # ------------------------------------------------------------------
    # Generic JSON parsing
    # ------------------------------------------------------------------

    def _parse_generic_json(
        self,
        data: dict,
        rel_path: str,
        kg: KnowledgeGraph,
        file_ent: Entity,
    ) -> None:
        """Parse generic JSON file (config, data, etc.)."""
        # Extract top-level keys as properties
        if isinstance(data, dict):
            for key, value in data.items():
                value_type = type(value).__name__
                
                # Determine if it's a complex structure
                if isinstance(value, dict):
                    sig = f"{key}: object ({len(value)} keys)"
                elif isinstance(value, list):
                    sig = f"{key}: array ({len(value)} items)"
                else:
                    sig = f"{key}: {value_type}"
                
                ent = Entity(
                    name=key,
                    entity_type=CodeEntityType.VARIABLE,
                    language=self.language,
                    file_path=rel_path,
                    line_start=1,
                    line_end=1,
                    signature=sig,
                    metadata={"value_type": value_type},
                )
                kg.add_entity(ent)
                kg.add_relation(
                    Relation(
                        source=file_ent.qualified_key,
                        target=ent.qualified_key,
                        relation_type=CodeRelationType.DEFINES,
                    )
                )
