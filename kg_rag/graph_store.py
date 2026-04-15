"""Abstract graph store and NetworkX implementation for code KG."""

from __future__ import annotations

from abc import ABC, abstractmethod

import networkx as nx

from kg_rag.models import CodeEntityType, Entity, KnowledgeGraph, Relation


# ======================================================================
# Abstract base
# ======================================================================


class GraphStore(ABC):
    """Persistence layer for a code KnowledgeGraph."""

    @abstractmethod
    def upsert_entity(self, entity: Entity) -> None: ...

    @abstractmethod
    def upsert_relation(self, relation: Relation) -> None: ...

    @abstractmethod
    def get_neighbors(self, entity_key: str, hops: int = 1) -> list[Relation]: ...

    @abstractmethod
    def get_entity(self, key: str) -> Entity | None: ...

    @abstractmethod
    def to_knowledge_graph(self) -> KnowledgeGraph: ...

    @abstractmethod
    def find_entities(
        self,
        name: str | None = None,
        entity_type: CodeEntityType | None = None,
        file_path: str | None = None,
    ) -> list[Entity]: ...


# ======================================================================
# In-memory store backed by NetworkX
# ======================================================================


class NetworkXGraphStore(GraphStore):
    """In-memory graph store using NetworkX."""

    def __init__(self) -> None:
        self._graph = nx.DiGraph()
        self._entities: dict[str, Entity] = {}

    def upsert_entity(self, entity: Entity) -> None:
        key = entity.qualified_key
        self._entities[key] = entity
        self._graph.add_node(key)

    def upsert_relation(self, relation: Relation) -> None:
        self._graph.add_edge(
            relation.source,
            relation.target,
            relation_type=relation.relation_type.value
            if hasattr(relation.relation_type, "value")
            else str(relation.relation_type),
            metadata=relation.metadata,
        )

    def get_entity(self, key: str) -> Entity | None:
        return self._entities.get(key)

    def find_entities(
        self,
        name: str | None = None,
        entity_type: CodeEntityType | None = None,
        file_path: str | None = None,
    ) -> list[Entity]:
        results = list(self._entities.values())
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
        if entity_key not in self._graph:
            return []

        visited: set[str] = {entity_key}
        frontier: set[str] = {entity_key}
        relations: list[Relation] = []

        for _ in range(hops):
            next_frontier: set[str] = set()
            for node in frontier:
                for _, target, data in self._graph.out_edges(node, data=True):
                    relations.append(
                        Relation(
                            source=node,
                            target=target,
                            relation_type=data.get("relation_type", "DEPENDS_ON"),
                        )
                    )
                    if target not in visited:
                        next_frontier.add(target)
                for source, _, data in self._graph.in_edges(node, data=True):
                    relations.append(
                        Relation(
                            source=source,
                            target=node,
                            relation_type=data.get("relation_type", "DEPENDS_ON"),
                        )
                    )
                    if source not in visited:
                        next_frontier.add(source)
            visited |= next_frontier
            frontier = next_frontier

        return relations

    def to_knowledge_graph(self) -> KnowledgeGraph:
        kg = KnowledgeGraph()
        for ent in self._entities.values():
            kg.add_entity(ent)
        for src, tgt, data in self._graph.edges(data=True):
            kg.add_relation(
                Relation(
                    source=src,
                    target=tgt,
                    relation_type=data.get("relation_type", "DEPENDS_ON"),
                )
            )
        return kg

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    @property
    def relation_count(self) -> int:
        return self._graph.number_of_edges()
