"""Embedding utilities for code entities."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

from kg_rag.config import settings
from kg_rag.models import Entity, KnowledgeGraph


class KGEmbedder:
    """Wraps a sentence-transformer to embed code KG elements."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model = SentenceTransformer(model_name or settings.EMBEDDING_MODEL)
        self._cache: dict[str, NDArray[np.float32]] = {}

    # ------------------------------------------------------------------
    # Core embedding
    # ------------------------------------------------------------------

    def embed_texts(self, texts: list[str]) -> NDArray[np.float32]:
        """Embed a list of plain-text strings."""
        return self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    def embed_entity(self, entity: Entity) -> NDArray[np.float32]:
        key = entity.qualified_key
        if key not in self._cache:
            text = self._entity_to_text(entity)
            self._cache[key] = self.embed_texts([text])[0]
        return self._cache[key]

    @staticmethod
    def _entity_to_text(entity: Entity) -> str:
        """Build a natural-language description of a code entity for embedding."""
        parts = [f"{entity.entity_type.value}: {entity.name}"]
        if entity.signature:
            parts.append(f"signature: {entity.signature}")
        if entity.docstring:
            parts.append(entity.docstring)
        if entity.file_path:
            parts.append(f"in {entity.file_path}")
        return ". ".join(parts)

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def embed_graph(self, kg: KnowledgeGraph) -> dict[str, NDArray[np.float32]]:
        """Embed all entities in a KG. Returns dict keyed by qualified_key."""
        entity_embs: dict[str, NDArray[np.float32]] = {}
        for ent in kg.entities:
            entity_embs[ent.qualified_key] = self.embed_entity(ent)
        return entity_embs

    # ------------------------------------------------------------------
    # Similarity search
    # ------------------------------------------------------------------

    @staticmethod
    def cosine_similarity(a: NDArray[np.float32], b: NDArray[np.float32]) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def find_similar_entities(
        self,
        query: str,
        kg: KnowledgeGraph,
        top_k: int = 5,
    ) -> list[tuple[Entity, float]]:
        """Return the top-k most similar entities to *query*."""
        query_emb = self.embed_texts([query])[0]
        scored: list[tuple[Entity, float]] = []
        for ent in kg.entities:
            ent_emb = self.embed_entity(ent)
            score = self.cosine_similarity(query_emb, ent_emb)
            scored.append((ent, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
