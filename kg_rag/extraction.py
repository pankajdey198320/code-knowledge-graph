"""LLM-based enrichment for the code knowledge graph (optional).

This module provides optional LLM calls to summarize or explain code entities.
The primary KG is built via tree-sitter parsers (see kg_rag.parsers), but this
module can add natural-language summaries for richer semantic search.
"""

from __future__ import annotations

from openai import OpenAI

from kg_rag.config import settings
from kg_rag.models import Entity, KnowledgeGraph

SUMMARIZE_PROMPT = """\
You are a senior software engineer. Given the following code entity details,
write a concise 1-2 sentence summary of what it does.

Entity: {name}
Type: {entity_type}
File: {file_path}
Signature: {signature}
Docstring: {docstring}
"""


def summarize_entity(
    entity: Entity,
    client: OpenAI | None = None,
    model: str | None = None,
) -> str:
    """Call an LLM to generate a summary for a code entity."""
    client = client or OpenAI(
        base_url=settings.OLLAMA_BASE_URL, api_key="ollama"
    )
    model = model or settings.LLM_MODEL

    prompt = SUMMARIZE_PROMPT.format(
        name=entity.name,
        entity_type=entity.entity_type.value,
        file_path=entity.file_path,
        signature=entity.signature,
        docstring=entity.docstring,
    )

    response = client.chat.completions.create(
        model=model,
        temperature=settings.LLM_TEMPERATURE,
        messages=[{"role": "user", "content": prompt}],
    )
    return (response.choices[0].message.content or "").strip()


def enrich_graph_with_summaries(
    kg: KnowledgeGraph,
    client: OpenAI | None = None,
    model: str | None = None,
) -> int:
    """Add LLM-generated docstrings to entities that lack one.

    Returns the number of entities enriched.
    """
    count = 0
    for ent in kg.entities:
        if not ent.docstring and ent.signature:
            ent.docstring = summarize_entity(ent, client=client, model=model)
            count += 1
    return count
