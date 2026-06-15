# Code Knowledge Graph (KG)

Build a **knowledge graph from source code** and query it via an **MCP server** that any LLM agent can call.

## Repository layout

```
KG/
├── py/          Python implementation (FastMCP, sentence-transformers, networkx)
│   ├── kg_rag/           core library
│   ├── examples/         usage demos
│   ├── docs/             design docs
│   └── pyproject.toml    package definition
└── dotnet/      C# implementation (.NET 8, Roslyn, Ollama)
    ├── src/
    │   ├── KgCodeRag/          core library (parsers, graph, embeddings)
    │   ├── KgCodeRag.Mcp/      MCP server (stdio + HTTP transports)
    │   └── KgCodeRag.Cli/      indexer CLI  (kg-index)
    └── KgCodeRag.slnx          solution file
```

## Quick start — Python

```bash
cd py
pip install -e .
kg-index --repo <path> --project myproject
kg-mcp --transport stdio
```

## Quick start — .NET

```powershell
cd dotnet
dotnet build KgCodeRag.slnx
dotnet run --project src/KgCodeRag.Mcp -- --transport stdio
```

## MCP tools (both implementations expose the same 22 tools)

`search_code` · `search_keywords` · `lookup_symbol` · `file_overview` · `list_classes` · `list_functions` · `call_graph` · `inheritance_tree` · `graph_stats` · `reindex_repo` · `list_projects` · `switch_project` · `index_project` · `get_project_metadata` · `get_indexed_project_info` · `code_ownership` · `change_coupling` · `hot_spots` · `work_items_for_code` · `code_for_work_item` · `work_item_details` · `blame_context`

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
# stdio transport (default; for agent/IDE integration)
kg-mcp
# or
python -m kg_rag.mcp_server

# HTTP via SSE transport
python -m kg_rag.mcp_server --transport sse --host 127.0.0.1 --port 8000
# then connect to GET http://127.0.0.1:8000/sse and POST http://127.0.0.1:8000/messages/

# HTTP via Streamable MCP transport
python -m kg_rag.mcp_server --transport streamable-http --host 127.0.0.1 --port 8000
# then connect to http://127.0.0.1:8000/mcp
```

The server now eagerly loads both the graph and embeddings before it reports ready. Expect a slower startup on first run, especially if embeddings need to be computed and cached.
If you browse to `http://127.0.0.1:8000/`, a `404 Not Found` is expected because the MCP endpoints are mounted under `/sse`, `/messages/`, or `/mcp`, not at the site root.

## Using with VS Code / Copilot

Add to your MCP settings (`.vscode/mcp.json` or user settings):

```json
{
  "servers": {
    "kg-upgrader": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "kg_rag.mcp_server"],
      "cwd": "C:\\path\\to\\KG",
      "env": {
        "KG_REPO_ROOT": "C:\\path\\to\\Bladed",
        "KG_PROJECT_NAME": "Upgrader",
        "KG_SCOPE_PATHS": "BladedX/Upgrader",
        "KG_CACHE_DIR": "C:\\path\\to\\KG\\data"
      }
    },
    "kg-bladedng": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "kg_rag.mcp_server"],
      "cwd": "C:\\path\\to\\KG",
      "env": {
        "KG_REPO_ROOT": "C:\\path\\to\\Bladed",
        "KG_PROJECT_NAME": "BladedNG",
        "KG_SCOPE_PATHS": "BladedX",
        "KG_CACHE_DIR": "C:\\path\\to\\KG\\data"
      }
    }
  }
}
```

If you want to expose the same packaged server over HTTP outside an MCP host that manages stdio, pass transport flags directly:

```bash
kg-mcp --transport sse --host 127.0.0.1 --port 8000
kg-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Use these endpoints after startup:

- SSE transport: `GET /sse` and `POST /messages/`
- Streamable HTTP transport: `POST /mcp` with the MCP client transport

For a multi-project server, prefer pointing MCP at a config file rather than embedding a large JSON string in the settings:

```json
{
  "servers": {
    "kg-multi": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "kg_rag.mcp_server"],
      "cwd": "C:\\path\\to\\KG",
      "env": {
        "ACTIVE_PROJECT": "Workflow",
        "KG_PROJECTS_FILE": "C:\\path\\to\\KG\\projects.sample.json"
      }
    }
  }
}
```

See [projects.sample.json](projects.sample.json) for the expected file schema.

`projects.json` is now optional. MCP runtime configuration takes precedence in this order:

1. `KG_PROJECTS_JSON` — inline JSON config for multiple named scopes.
2. `KG_PROJECTS_FILE` — path to a JSON config file outside the package source tree.
3. `KG_REPO_ROOT` + `KG_PROJECT_NAME` + `KG_SCOPE_PATHS` — single-project MCP server config.
4. `projects.json` — legacy fallback for local development.

### MCP config variables

| Variable | Purpose |
|------|-------------|
| `KG_REPO_ROOT` | Repository root to index |
| `KG_PROJECT_NAME` | Active project name exposed by the server |
| `KG_SCOPE_PATHS` | Scope paths relative to `KG_REPO_ROOT`; accepts JSON array, `;`, or `,` separated values |
| `KG_PROJECT_DESCRIPTION` | Optional description shown by `list_projects` |
| `KG_CACHE_DIR` | Optional cache directory for pickled graph files |
| `KG_PROJECTS_JSON` | Full inline JSON config with `repo_root`, optional `cache_dir`, and `projects` |
| `KG_PROJECTS_FILE` | Path to a JSON config file with the same schema as `KG_PROJECTS_JSON`; recommended for multi-project MCP setups |

### Packaging pattern for many MCP servers

Package one reusable `kg-code-rag` distribution and configure many MCP server entries around it.

- Keep the package generic; do not bake repo-specific `projects.json` into the wheel.
- Install the package once in a shared virtual environment.
- Define one MCP server entry per repo or per focused scope by setting env vars in MCP config.
- Share a cache directory across servers; cache file names are repo-hashed to avoid collisions.
- Prefer `KG_PROJECTS_FILE` when one server needs multiple switchable scopes; use `KG_PROJECTS_JSON` only for small self-contained configs.

See `docs/mcp-packaging.md` for a concrete packaging plan.

## Build And Distribute

This repo already uses `pyproject.toml`, so the standard Python packaging flow is:

### 1. Install build tooling

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

### 2. Build a wheel and source distribution

```bash
python -m build
```

That creates:

- `dist/kg_code_rag-<version>-py3-none-any.whl`
- `dist/kg_code_rag-<version>.tar.gz`

### 3. Validate package metadata

```bash
python -m twine check dist/*
```

### 4. Test install the built wheel

```bash
pip install dist/kg_code_rag-<version>-py3-none-any.whl
```

### 5. Publish

For PyPI:

```bash
python -m twine upload dist/*
```

For a private package index:

```bash
python -m twine upload --repository-url https://your-package-feed.example.com/simple/ dist/*
```

### Distribution notes for this repo

- The package code is `kg_rag`; the distribution name is `kg-code-rag`.
- MCP runtime config should come from MCP env vars, not from a packaged `projects.json`.
- Large local runtime folders such as `data/`, `Neo4_data/`, and local virtualenv content should not be part of your distribution workflow.
- The local `models/` directory is treated as an optional runtime optimization. Distributed installs should normally let `sentence-transformers` download the embedding model instead of bundling model weights into the wheel.

If you want a private, team-distributed package, the practical path is: build one wheel, publish it to your internal feed, then configure per-repo MCP servers using MCP env variables.

For a release-ready internal publishing flow, see [docs/private-release-checklist.md](docs/private-release-checklist.md).

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
