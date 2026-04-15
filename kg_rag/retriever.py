"""Graph RAG retriever – combines KG traversal with embedding similarity for code."""

from __future__ import annotations

from dataclasses import dataclass, field

from kg_rag.embeddings import KGEmbedder
from kg_rag.models import CodeEntityType, Entity, KnowledgeGraph, Relation


@dataclass
class RetrievedContext:
    """Bundle of code-graph context returned by the retriever."""

    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    subgraph_text: str = ""


class GraphRetriever:
    """Retrieve relevant code subgraph context for a query.

    Strategy:
    1. Embed the query and find the top-k most similar code entities.
    2. For each seed entity, traverse *hops* edges to gather local context.
    3. Format the subgraph as natural-language text.
    """

    def __init__(
        self,
        kg: KnowledgeGraph,
        embedder: KGEmbedder | None = None,
        top_k: int = 5,
        hops: int = 2,
    ) -> None:
        self.kg = kg
        self.embedder = embedder or KGEmbedder()
        self.top_k = top_k
        self.hops = hops

    def retrieve(self, query: str) -> RetrievedContext:
        # 1. Semantic entity search
        similar = self.embedder.find_similar_entities(query, self.kg, top_k=self.top_k)
        seed_entities = [ent for ent, _score in similar]

        # 2. Graph traversal
        all_relations: list[Relation] = []
        seen_keys: set[str] = set()
        for ent in seed_entities:
            seen_keys.add(ent.qualified_key)
            neighbors = self.kg.get_neighbors(ent.qualified_key, hops=self.hops)
            all_relations.extend(neighbors)
            for rel in neighbors:
                seen_keys.add(rel.source)
                seen_keys.add(rel.target)

        # Deduplicate relations
        unique_rels: list[Relation] = list(
            {
                f"{r.source}|{r.relation_type}|{r.target}": r
                for r in all_relations
            }.values()
        )

        # Gather entity objects
        entities: list[Entity] = []
        for key in seen_keys:
            ent = self.kg.get_entity(key)
            if ent:
                entities.append(ent)

        # 3. Format
        text = self._format_subgraph(entities, unique_rels)
        return RetrievedContext(entities=entities, relations=unique_rels, subgraph_text=text)

    def retrieve_by_name(self, name: str) -> RetrievedContext:
        """Exact-name search + neighbourhood context."""
        matches = self.kg.find_entities(name=name)
        if not matches:
            return RetrievedContext(subgraph_text=f"No entities found matching '{name}'.")

        all_rels: list[Relation] = []
        seen_keys: set[str] = set()
        for ent in matches:
            seen_keys.add(ent.qualified_key)
            neighbors = self.kg.get_neighbors(ent.qualified_key, hops=self.hops)
            all_rels.extend(neighbors)
            for rel in neighbors:
                seen_keys.add(rel.source)
                seen_keys.add(rel.target)

        unique_rels = list(
            {f"{r.source}|{r.relation_type}|{r.target}": r for r in all_rels}.values()
        )
        entities = [e for k in seen_keys if (e := self.kg.get_entity(k)) is not None]
        text = self._format_subgraph(entities, unique_rels)
        return RetrievedContext(entities=entities, relations=unique_rels, subgraph_text=text)

    def retrieve_by_file(self, file_path: str) -> RetrievedContext:
        """Retrieve all entities defined in a given file."""
        matches = self.kg.find_entities(file_path=file_path)
        rels: list[Relation] = []
        for ent in matches:
            rels.extend(self.kg.get_neighbors(ent.qualified_key, hops=1))
        unique_rels = list(
            {f"{r.source}|{r.relation_type}|{r.target}": r for r in rels}.values()
        )
        text = self._format_subgraph(matches, unique_rels)
        return RetrievedContext(entities=matches, relations=unique_rels, subgraph_text=text)

    def list_entity_types(self) -> dict[str, int]:
        """Count entities by type."""
        counts: dict[str, int] = {}
        for ent in self.kg.entities:
            key = ent.entity_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    # ------------------------------------------------------------------

    @staticmethod
    def _format_subgraph(entities: list[Entity], relations: list[Relation]) -> str:
        lines: list[str] = ["### Code Entities"]
        for ent in entities:
            loc = f" ({ent.file_path}:{ent.line_start})" if ent.file_path else ""
            sig = f" — `{ent.signature}`" if ent.signature else ""
            doc = f"  {ent.docstring}" if ent.docstring else ""
            lines.append(f"- [{ent.entity_type.value}] {ent.name}{loc}{sig}{doc}")
        lines.append("\n### Relations")
        for rel in relations:
            lines.append(f"- {rel.source} --[{rel.relation_type}]--> {rel.target}")
        return "\n".join(lines)
