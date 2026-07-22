# test_search_quick.py
from kg_rag.models import KnowledgeGraph, Entity, CodeEntityType
from kg_rag.embeddings import KGEmbedder
from kg_rag.retriever import GraphRetriever
import numpy as np

def fake_embed(texts):
    # deterministic tiny embeddings
    return np.asarray([[sum(map(ord, t)) % 100 / 100.0 for _ in range(8)] for t in texts], dtype=np.float32)

kg = KnowledgeGraph()
kg.entities = [
    Entity(name="parse_json", entity_type=CodeEntityType.FUNCTION, file_path="src/utils.py", line_start=10, signature="(s)", docstring="Parse JSON string"),
    Entity(name="write_file", entity_type=CodeEntityType.FUNCTION, file_path="src/io.py", line_start=5, signature="(p)", docstring="Write bytes to file"),
]

embedder = KGEmbedder(embed_fn=fake_embed)
retriever = GraphRetriever(kg=kg, embedder=embedder, top_k=2, hops=1)
ctx = retriever.retrieve("parse json")
print(ctx.subgraph_text)