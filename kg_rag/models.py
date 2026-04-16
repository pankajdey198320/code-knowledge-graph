"""Knowledge-graph data models for source-code entities and relations."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ======================================================================
# Entity types specific to source code
# ======================================================================


class CodeEntityType(str, Enum):
    FILE = "file"
    MODULE = "module"           # Python module / C# namespace
    NAMESPACE = "namespace"     # C++ / C# namespace
    CLASS = "class"
    STRUCT = "struct"
    INTERFACE = "interface"
    ENUM = "enum"
    FUNCTION = "function"
    METHOD = "method"
    PROPERTY = "property"
    VARIABLE = "variable"
    PARAMETER = "parameter"
    IMPORT = "import"
    PACKAGE = "package"         # top-level project / assembly
    # Git-history entities
    COMMIT = "commit"
    AUTHOR = "author"
    WORK_ITEM = "work_item"


class CodeRelationType(str, Enum):
    DEFINES = "DEFINES"             # file/class → symbol it defines
    CONTAINS = "CONTAINS"           # class → method, namespace → class
    CALLS = "CALLS"                 # function → function
    IMPORTS = "IMPORTS"             # file → module / symbol
    INHERITS = "INHERITS"          # class → base class
    IMPLEMENTS = "IMPLEMENTS"       # class → interface
    USES_TYPE = "USES_TYPE"        # function → type (param / return)
    OVERRIDES = "OVERRIDES"        # method → base method
    DEPENDS_ON = "DEPENDS_ON"      # file → file
    BELONGS_TO = "BELONGS_TO"      # symbol → namespace / module
    # Git-history relations
    MODIFIED_BY = "MODIFIED_BY"    # file → author (weighted by commit count)
    COMMITTED_IN = "COMMITTED_IN"  # file → commit
    CO_CHANGED = "CO_CHANGED"      # file ↔ file (same-commit co-occurrence)
    LINKED_TO = "LINKED_TO"        # commit → work_item


# ======================================================================
# Core models
# ======================================================================


class Entity(BaseModel):
    """A node in the code knowledge graph."""

    name: str = Field(..., description="Qualified symbol name")
    entity_type: CodeEntityType = Field(default=CodeEntityType.FILE)
    language: str = Field(default="", description="Source language (python, cpp, csharp)")
    file_path: str = Field(default="", description="Relative path inside the repo")
    line_start: int = Field(default=0)
    line_end: int = Field(default=0)
    signature: str = Field(default="", description="Function/method signature or class header")
    docstring: str = Field(default="", description="Doc-comment or summary")
    metadata: dict[str, str] = Field(default_factory=dict)

    def __hash__(self) -> int:
        return hash((self.name, self.file_path, self.line_start))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Entity):
            return (
                self.name == other.name
                and self.file_path == other.file_path
                and self.line_start == other.line_start
            )
        return NotImplemented

    @property
    def qualified_key(self) -> str:
        """Unique key for dedup. Includes file + name + line."""
        return f"{self.file_path}::{self.name}@{self.line_start}"


class Relation(BaseModel):
    """A directed edge between two code entities."""

    source: str = Field(..., description="Source entity qualified_key or name")
    target: str = Field(..., description="Target entity qualified_key or name")
    relation_type: CodeRelationType = Field(default=CodeRelationType.DEPENDS_ON)
    metadata: dict[str, str] = Field(default_factory=dict)


class KnowledgeGraph(BaseModel):
    """Container for code entities and relations."""

    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)

    # Fast lookup caches (excluded from serialization)
    _entity_map: dict[str, Entity] = {}

    def model_post_init(self, _context: object) -> None:
        self._entity_map = {e.qualified_key: e for e in self.entities}

    def add_entity(self, entity: Entity) -> None:
        key = entity.qualified_key
        if key not in self._entity_map:
            self.entities.append(entity)
            self._entity_map[key] = entity

    def add_relation(self, relation: Relation) -> None:
        self.relations.append(relation)

    def get_entity(self, key: str) -> Entity | None:
        return self._entity_map.get(key)

    def find_entities(
        self,
        name: str | None = None,
        entity_type: CodeEntityType | None = None,
        file_path: str | None = None,
    ) -> list[Entity]:
        """Filter entities by optional criteria."""
        results = self.entities
        if name is not None:
            name_lower = name.lower()
            results = [e for e in results if name_lower in e.name.lower()]
        if entity_type is not None:
            results = [e for e in results if e.entity_type == entity_type]
        if file_path is not None:
            fp_lower = file_path.lower().replace("\\", "/")
            results = [
                e for e in results if fp_lower in e.file_path.lower().replace("\\", "/")
            ]
        return results

    def get_neighbors(self, entity_key: str, hops: int = 1) -> list[Relation]:
        """Return relations within *hops* of the given entity key."""
        visited: set[str] = {entity_key}
        frontier: set[str] = {entity_key}
        result: list[Relation] = []

        for _ in range(hops):
            next_frontier: set[str] = set()
            for rel in self.relations:
                if rel.source in frontier:
                    result.append(rel)
                    if rel.target not in visited:
                        next_frontier.add(rel.target)
                elif rel.target in frontier:
                    result.append(rel)
                    if rel.source not in visited:
                        next_frontier.add(rel.source)
            visited |= next_frontier
            frontier = next_frontier

        return result
