"""Parser for NAnt build files.

Extracts targets, tasks, properties, and dependencies from .build files.
NAnt is a .NET build tool similar to Ant for Java.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from kg_rag.models import (
    CodeEntityType,
    CodeRelationType,
    Entity,
    KnowledgeGraph,
    Relation,
)
from kg_rag.parsers.base import BaseCodeParser


class NAntParser(BaseCodeParser):
    language = "nant"

    def parse_file(self, file_path: Path, repo_root: Path) -> KnowledgeGraph:
        source = self._read_source(file_path).decode("utf-8", errors="replace")
        rel_path = self._relative(file_path, repo_root)

        kg = KnowledgeGraph()
        file_ent = self._make_file_entity(rel_path)
        kg.add_entity(file_ent)

        try:
            root = ET.fromstring(source)
        except ET.ParseError as e:
            # If XML parsing fails, still return the file entity
            return kg

        # Extract project metadata
        project_name = root.get("name", "")
        default_target = root.get("default", "")
        
        if project_name:
            file_ent.metadata = {
                "project": project_name,
                "default_target": default_target,
            }

        # Extract properties
        self._extract_properties(root, rel_path, kg, file_ent)

        # Extract targets
        self._extract_targets(root, rel_path, kg, file_ent)

        return kg

    # ------------------------------------------------------------------
    # Property extraction
    # ------------------------------------------------------------------

    def _extract_properties(
        self,
        root: ET.Element,
        rel_path: str,
        kg: KnowledgeGraph,
        file_ent: Entity,
    ) -> None:
        """Extract <property> declarations."""
        for prop in root.findall(".//property"):
            prop_name = prop.get("name", "")
            prop_value = prop.get("value", "")
            
            if not prop_name:
                continue

            # Find line number (approximate - XML parser doesn't provide line info)
            ent = Entity(
                name=prop_name,
                entity_type=CodeEntityType.VARIABLE,
                language=self.language,
                file_path=rel_path,
                line_start=1,
                line_end=1,
                signature=f'property name="{prop_name}" value="{prop_value}"',
                metadata={"value": prop_value, "kind": "property"},
            )
            kg.add_entity(ent)
            kg.add_relation(
                Relation(
                    source=file_ent.qualified_key,
                    target=ent.qualified_key,
                    relation_type=CodeRelationType.DEFINES,
                )
            )

    # ------------------------------------------------------------------
    # Target extraction
    # ------------------------------------------------------------------

    def _extract_targets(
        self,
        root: ET.Element,
        rel_path: str,
        kg: KnowledgeGraph,
        file_ent: Entity,
    ) -> None:
        """Extract <target> elements with their tasks and dependencies."""
        for target in root.findall(".//target"):
            target_name = target.get("name", "")
            depends = target.get("depends", "")
            description = target.get("description", "")
            
            if not target_name:
                continue

            # Create target entity
            sig = f'target name="{target_name}"'
            if depends:
                sig += f' depends="{depends}"'
            
            metadata = {}
            if description:
                metadata["description"] = description
            if depends:
                metadata["depends"] = depends

            ent = Entity(
                name=target_name,
                entity_type=CodeEntityType.FUNCTION,
                language=self.language,
                file_path=rel_path,
                line_start=1,
                line_end=1,
                signature=sig,
                docstring=description,
                metadata=metadata,
            )
            kg.add_entity(ent)
            kg.add_relation(
                Relation(
                    source=file_ent.qualified_key,
                    target=ent.qualified_key,
                    relation_type=CodeRelationType.DEFINES,
                )
            )

            # Extract dependencies
            if depends:
                for dep in [d.strip() for d in depends.split(",")]:
                    if dep:
                        kg.add_relation(
                            Relation(
                                source=ent.qualified_key,
                                target=dep,
                                relation_type=CodeRelationType.CALLS,
                            )
                        )

            # Extract tasks within this target
            self._extract_tasks(target, kg, ent)

    # ------------------------------------------------------------------
    # Task extraction
    # ------------------------------------------------------------------

    def _extract_tasks(
        self,
        target: ET.Element,
        kg: KnowledgeGraph,
        target_ent: Entity,
    ) -> None:
        """Extract task calls within a target."""
        # Common NAnt tasks
        common_tasks = {
            "exec", "csc", "copy", "delete", "mkdir", "move", "touch", 
            "zip", "unzip", "mail", "echo", "fail", "if", "foreach",
            "call", "nant", "solution", "msbuild", "assemblinfo",
            "resgen", "ndoc", "nunit2", "ilasm", "al", "vbc", "jsc",
            "get", "xmlpoke", "xmlpeek", "script", "sleep", "tstamp",
            "loadtasks", "loadfile", "style", "property", "include",
        }

        for child in target:
            task_name = child.tag
            
            # Skip non-task elements
            if task_name in ("description",):
                continue
            
            # Record the task call
            if task_name in common_tasks:
                # Get task attributes for context
                task_attrs = " ".join([f'{k}="{v}"' for k, v in child.attrib.items()])
                task_sig = f"{task_name}"
                if task_attrs:
                    task_sig = f"{task_name}({task_attrs[:50]}...)" if len(task_attrs) > 50 else f"{task_name}({task_attrs})"
                
                kg.add_relation(
                    Relation(
                        source=target_ent.qualified_key,
                        target=task_name,
                        relation_type=CodeRelationType.CALLS,
                        metadata={"task": task_name, "signature": task_sig},
                    )
                )
            
            # Handle <call> tasks (calling other targets)
            if task_name == "call":
                called_target = child.get("target", "")
                if called_target:
                    kg.add_relation(
                        Relation(
                            source=target_ent.qualified_key,
                            target=called_target,
                            relation_type=CodeRelationType.CALLS,
                        )
                    )
            
            # Handle <nant> tasks (calling other build files)
            if task_name == "nant":
                buildfile = child.get("buildfile", "")
                target_attr = child.get("target", "")
                if buildfile:
                    kg.add_relation(
                        Relation(
                            source=target_ent.qualified_key,
                            target=buildfile,
                            relation_type=CodeRelationType.IMPORTS,
                            metadata={"buildfile": buildfile, "target": target_attr},
                        )
                    )
