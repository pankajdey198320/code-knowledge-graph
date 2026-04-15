# Code Knowledge Graph + MCP Query Tool

Build a **knowledge graph from source code** (Python, C++, C#) in a mono-repo, then query it via an **MCP server** that any LLM agent can call.

## Architecture

```
Mono-repo                            MCP Server
   │                                    │
   ├─ .py files ──► PythonParser ─┐     ├─ search_code       (semantic search)
   ├─ .cpp/.h   ──► CppParser    ├──►  KG  ├─ lookup_symbol      (name search)
   └─ .cs files ──► CSharpParser ─┘  (entities   ├─ file_overview       (per-file)
                                    + relations)  ├─ list_classes        (filter)
   Sentence-Transformer embeddings ◄───┘          ├─ list_functions      (filter)
                                                  ├─ call_graph          (who calls what)
   Query ──► Embed ──► Top-K entities             ├─ inheritance_tree    (class hierarchy)
                  └──► Subgraph traversal         ├─ graph_stats         (summary)
                       └──► Context for LLM       └─ reindex_repo        (rebuild)
```

### Entity types

`file` · `module` · `namespace` · `class` · `struct` · `interface` · `enum` · `function` · `method` · `property` · `import` · `package`

### Relation types

`DEFINES` · `CONTAINS` · `CALLS` · `IMPORTS` · `INHERITS` · `IMPLEMENTS` · `USES_TYPE` · `OVERRIDES` · `DEPENDS_ON` · `BELONGS_TO`

## Project Structure

```
KG/
├── kg_rag/
│   ├── __init__.py
│   ├── config.py              # Settings from .env
│   ├── models.py              # Entity, Relation, KnowledgeGraph (Pydantic)
│   ├── embeddings.py          # KGEmbedder (sentence-transformers)
│   ├── extraction.py          # Optional LLM enrichment
│   ├── graph_store.py         # NetworkX in-memory graph store
│   ├── retriever.py           # Embedding + graph traversal retriever
│   ├── pipeline.py            # End-to-end CodeGraphRAG
│   ├── indexer.py             # Repo crawler + graph builder
│   ├── cli.py                 # CLI entry-points
│   ├── mcp_server.py          # ★ MCP server with query tools
│   └── parsers/
│       ├── __init__.py
│       ├── base.py            # Abstract BaseCodeParser
│       ├── router.py          # Extension → parser routing
│       ├── python_parser.py   # Tree-sitter Python parser
│       ├── cpp_parser.py      # Tree-sitter C++ parser
│       └── csharp_parser.py   # Tree-sitter C# parser
├── examples/
│   ├── demo.py                # Full demo (LLM + RAG)
│   └── demo_offline.py        # Offline demo (no API key)
├── data/                      # Cached graph index
├── pyproject.toml
├── .env.example
└── README.md
```

## Quickstart

### 1. Install

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -e ".[dev]"
```

### 2. Configure

```bash
copy .env.example .env
# Edit .env – set REPO_ROOT to your mono-repo path
# Default LLM is Ollama (llama3) at localhost:11434
```

Make sure Ollama is running with a model pulled:
```bash
ollama pull llama3
ollama serve
```

### 3. Index your repo

```bash
# Via CLI
kg-index "C:\path\to\monorepo"

# Or from Python
from kg_rag.indexer import index_repo, save_graph
kg = index_repo(Path("C:/path/to/monorepo"))
save_graph(kg)
```

### 4. Run the offline demo (no API key)

```bash
python examples/demo_offline.py
```

### 5. Start the MCP server

```bash
# stdio transport (for agent/IDE integration)
kg-mcp
# or
python -m kg_rag.mcp_server
```

## Using with VS Code / Copilot

Add to your MCP settings (`.vscode/mcp.json` or user settings):

```json
{
  "servers": {
    "code-knowledge-graph": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "kg_rag.mcp_server"],
      "cwd": "C:\\path\\to\\KG",
      "env": {
        "REPO_ROOT": "C:\\path\\to\\monorepo"
      }
    }
  }
}
```

## MCP Tools Reference

| Tool | Description |
|------|-------------|
| `search_code` | Semantic search — find entities by natural-language query |
| `lookup_symbol` | Find entities by name (partial match) + neighbourhood |
| `file_overview` | List all entities defined in a specific file |
| `list_classes` | List all classes, optionally filtered by name |
| `list_functions` | List all top-level functions, optionally filtered |
| `call_graph` | Show what a function calls and what calls it |
| `inheritance_tree` | Show class inheritance hierarchy |
| `graph_stats` | Summary statistics of the indexed graph |
| `reindex_repo` | Re-index the repo and rebuild the graph |

## Extending

- **Add languages** — create a new parser in `kg_rag/parsers/`, register its extension in `router.py`.
- **Neo4j backend** — install `pip install kg-code-rag[neo4j]` and swap in `Neo4jGraphStore`.
- **Vector index** — replace brute-force cosine search with FAISS/Qdrant for large repos.
- **LLM enrichment** — use `kg_rag.extraction.enrich_graph_with_summaries()` to add AI-generated docstrings.
