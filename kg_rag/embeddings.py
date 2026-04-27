"""Embedding utilities for code entities."""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

from kg_rag.config import settings
from kg_rag.models import Entity, KnowledgeGraph


class KGEmbedder:
    """Wraps a sentence-transformer to embed code KG elements."""

    def __init__(self, model_name: str | None = None) -> None:
        model_name = model_name or settings.EMBEDDING_MODEL
        # Prefer local copy under models/ for faster startup
        local_path = settings.MODELS_DIR / model_name
        if local_path.exists():
            model_name = str(local_path)
            print(f"[kg-embedder] Loading local model from {local_path}", file=sys.stderr)
        else:
            print(f"[kg-embedder] Downloading model '{model_name}' from HuggingFace (this may take a while)...", file=sys.stderr)
        
        self.model = SentenceTransformer(model_name)
        print("[kg-embedder] Model loaded successfully", file=sys.stderr)
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

    def embed_graph(
        self,
        kg: KnowledgeGraph,
        skip_entity_types: set[str] | None = None,
        batch_size: int = 100,
        show_progress: bool = True,
    ) -> dict[str, NDArray[np.float32]]:
        """Embed all entities in a KG. Returns dict keyed by qualified_key.
        
        Args:
            kg: The knowledge graph to embed.
            skip_entity_types: Entity types to skip (e.g., {'file', 'import', 'variable'}).
            batch_size: Number of entities to encode at once.
            show_progress: Whether to show a progress bar.
        """
        # Filter entities to embed
        if skip_entity_types is None:
            skip_entity_types = {'file', 'import', 'variable'}  # Skip low-value entities by default
        
        entities_to_embed = [
            ent for ent in kg.entities
            if ent.entity_type.value not in skip_entity_types
        ]
        
        skipped_count = len(kg.entities) - len(entities_to_embed)
        if skipped_count > 0:
            print(
                f"[kg-embedder] Skipping {skipped_count} low-value entities "
                f"({', '.join(sorted(skip_entity_types))})",
                file=sys.stderr,
            )
        
        total_batches = (len(entities_to_embed) + batch_size - 1) // batch_size
        print(f"[kg-embedder] Embedding {len(entities_to_embed)} entities in {total_batches} batches of {batch_size}...", file=sys.stderr)
        
        entity_embs: dict[str, NDArray[np.float32]] = {}
        
        # Process in batches for efficiency
        import time
        start_time = time.time()
        
        for batch_idx, i in enumerate(range(0, len(entities_to_embed), batch_size)):
            batch = entities_to_embed[i:i + batch_size]
            texts = [self._entity_to_text(ent) for ent in batch]
            embeddings = self.embed_texts(texts)
            
            for ent, emb in zip(batch, embeddings):
                entity_embs[ent.qualified_key] = emb
                self._cache[ent.qualified_key] = emb
            
            # Progress logging every 10 batches or at specific milestones
            if show_progress and (batch_idx + 1) % 10 == 0:
                elapsed = time.time() - start_time
                progress = (batch_idx + 1) / total_batches * 100
                entities_done = min((batch_idx + 1) * batch_size, len(entities_to_embed))
                rate = entities_done / elapsed if elapsed > 0 else 0
                eta = (len(entities_to_embed) - entities_done) / rate if rate > 0 else 0
                print(
                    f"[kg-embedder] Progress: {progress:.1f}% ({entities_done:,}/{len(entities_to_embed):,} entities, "
                    f"{rate:.0f} entities/sec, ETA: {eta:.0f}s)",
                    file=sys.stderr,
                )
        
        elapsed = time.time() - start_time
        print(f"[kg-embedder] Completed embedding {len(entities_to_embed)} entities in {elapsed:.1f}s", file=sys.stderr)
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

    # ------------------------------------------------------------------
    # Disk caching
    # ------------------------------------------------------------------

    def save_cache(self, cache_path: Path) -> None:
        """Persist the embedding cache to disk."""
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "wb") as f:
            pickle.dump(self._cache, f)
        print(f"[kg-embedder] Saved {len(self._cache)} embeddings to {cache_path}", file=sys.stderr)

    def load_cache(self, cache_path: Path) -> bool:
        """Load embedding cache from disk. Returns True if successful."""
        if not cache_path.exists():
            return False
        try:
            with open(cache_path, "rb") as f:
                self._cache = pickle.load(f)
            print(f"[kg-embedder] Loaded {len(self._cache)} embeddings from {cache_path}", file=sys.stderr)
            return True
        except Exception as e:
            print(f"[kg-embedder] Failed to load cache from {cache_path}: {e}", file=sys.stderr)
            return False
