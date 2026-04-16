"""Enrich code-entity descriptions with git-history context for better embeddings."""

from __future__ import annotations

from collections import defaultdict

from kg_rag.models import CodeEntityType, CodeRelationType, KnowledgeGraph


def build_enriched_descriptions(kg: KnowledgeGraph) -> dict[str, str]:
    """Build enriched text descriptions for every file entity in *kg*.

    The returned dict maps ``entity.qualified_key`` → enriched text string
    that combines structural info with git-history context (ownership,
    co-change files, linked work items).

    These descriptions can replace the raw entity text before embedding so
    that semantic search understands *purpose* and *context*, not just names.
    """

    # Pre-index relations by source and target for fast lookup
    rels_by_source: dict[str, list[tuple[str, str, dict[str, str]]]] = defaultdict(list)
    rels_by_target: dict[str, list[tuple[str, str, dict[str, str]]]] = defaultdict(list)
    for rel in kg.relations:
        rt = rel.relation_type.value if hasattr(rel.relation_type, "value") else str(rel.relation_type)
        rels_by_source[rel.source].setdefault(rt, [])  # type: ignore[arg-type]
        rels_by_source[rel.source].append((rt, rel.target, rel.metadata))
        rels_by_target[rel.target].append((rt, rel.source, rel.metadata))

    # Build an entity-key → entity lookup
    entity_map = {e.qualified_key: e for e in kg.entities}

    # Also build a file_path → entity key lookup for linking git relations
    # (git relations use bare file paths as source, not qualified keys)
    file_entities: dict[str, str] = {}
    for e in kg.entities:
        if e.entity_type == CodeEntityType.FILE and e.file_path:
            file_entities[e.file_path] = e.qualified_key

    descriptions: dict[str, str] = {}

    for entity in kg.entities:
        if entity.entity_type in (
            CodeEntityType.COMMIT,
            CodeEntityType.AUTHOR,
            CodeEntityType.WORK_ITEM,
        ):
            continue  # skip git-layer meta-entities

        parts: list[str] = []

        # Base description
        parts.append(
            f"[{entity.entity_type.value}] {entity.name}"
        )
        if entity.file_path:
            parts.append(f"in {entity.file_path}")
        if entity.signature:
            parts.append(f"signature: {entity.signature}")
        if entity.docstring:
            parts.append(entity.docstring)

        # --- Structural neighbours ---
        key = entity.qualified_key
        out_rels = rels_by_source.get(key, [])
        in_rels = rels_by_target.get(key, [])

        inherits = [t for rt, t, _ in out_rels if rt == "INHERITS"]
        if inherits:
            parts.append(f"inherits: {', '.join(inherits)}")

        implements = [t for rt, t, _ in out_rels if rt == "IMPLEMENTS"]
        if implements:
            parts.append(f"implements: {', '.join(implements)}")

        # --- Git-history context (linked via file_path) ---
        fp = entity.file_path
        if fp:
            # Ownership
            modified_by = [
                (meta.get("email", "?"), meta.get("commit_count", "?"))
                for rt, _, meta in rels_by_source.get(fp, [])
                if rt == "MODIFIED_BY"
            ]
            if modified_by:
                # Sort by commit count desc
                modified_by.sort(key=lambda x: int(x[1]) if x[1].isdigit() else 0, reverse=True)
                top3 = modified_by[:3]
                owners = ", ".join(f"{email} ({cnt} commits)" for email, cnt in top3)
                parts.append(f"modified by: {owners}")

            # Co-change
            cochanged = [
                (target, meta.get("co_change_count", "?"))
                for rt, target, meta in rels_by_source.get(fp, [])
                if rt == "CO_CHANGED"
            ]
            # Also check reverse direction
            cochanged += [
                (source, meta.get("co_change_count", "?"))
                for rt, source, meta in rels_by_target.get(fp, [])
                if rt == "CO_CHANGED"
            ]
            if cochanged:
                cochanged.sort(key=lambda x: int(x[1]) if x[1].isdigit() else 0, reverse=True)
                top5 = cochanged[:5]
                coupled = ", ".join(f"{f} ({cnt}x)" for f, cnt in top5)
                parts.append(f"often changes with: {coupled}")

            # Linked work items (transitive: file → commit → work_item)
            commit_keys = [
                target
                for rt, target, _ in rels_by_source.get(fp, [])
                if rt == "COMMITTED_IN"
            ]
            wi_ids: list[str] = []
            for ck in commit_keys:
                for rt, target, meta in rels_by_source.get(ck, []):
                    if rt == "LINKED_TO":
                        wid = meta.get("work_item_id", "")
                        if wid and wid not in wi_ids:
                            wi_ids.append(wid)
            if wi_ids:
                parts.append(f"linked work items: {', '.join(f'#{w}' for w in wi_ids[:10])}")

        descriptions[key] = "\n".join(parts)

    return descriptions
