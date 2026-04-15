"""End-to-end pipeline: index repo → build graph → query with LLM."""

from __future__ import annotations

from pathlib import Path

from openai import OpenAI

from kg_rag.config import settings
from kg_rag.embeddings import KGEmbedder
from kg_rag.indexer import index_repo, load_graph, save_graph
from kg_rag.models import KnowledgeGraph
from kg_rag.retriever import GraphRetriever, RetrievedContext

RAG_SYSTEM_PROMPT = """\
You are a senior software engineer assistant.  Answer the user's question using
ONLY the code knowledge-graph context provided below.  Reference specific files,
classes, functions, and line numbers when relevant.  If the context does not
contain enough information, say so rather than guessing.

{context}
"""


class CodeGraphRAG:
    """High-level facade: index a repo, query the graph, generate answers."""

    def __init__(
        self,
        repo_root: Path | None = None,
        embedder: KGEmbedder | None = None,
        client: OpenAI | None = None,
        top_k: int = 5,
        hops: int = 2,
    ) -> None:
        self.repo_root = (repo_root or settings.REPO_ROOT).resolve()
        self.embedder = embedder or KGEmbedder()
        self.client = client or OpenAI(
            base_url=settings.OLLAMA_BASE_URL, api_key="ollama"
        )
        self.top_k = top_k
        self.hops = hops

        self.kg: KnowledgeGraph | None = None
        self.retriever: GraphRetriever | None = None

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index(self, force: bool = False) -> KnowledgeGraph:
        """Index the repo (or load from cache)."""
        cache = settings.GRAPH_CACHE_PATH
        if not force and cache.exists():
            self.kg = load_graph(cache)
        else:
            self.kg = index_repo(self.repo_root, show_progress=True)
            save_graph(self.kg, cache)

        self.retriever = GraphRetriever(
            kg=self.kg, embedder=self.embedder, top_k=self.top_k, hops=self.hops
        )
        return self.kg

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(self, query: str) -> RetrievedContext:
        if self.retriever is None:
            self.index()
        assert self.retriever is not None
        return self.retriever.retrieve(query)

    # ------------------------------------------------------------------
    # Generation (RAG)
    # ------------------------------------------------------------------

    def query(self, question: str) -> str:
        """Retrieve relevant code context, then ask the LLM."""
        ctx = self.retrieve(question)
        system = RAG_SYSTEM_PROMPT.format(context=ctx.subgraph_text)

        response = self.client.chat.completions.create(
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
        )
        return response.choices[0].message.content or ""
