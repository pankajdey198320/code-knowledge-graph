# Building a Code Knowledge Graph for Real Developer Questions

I have been working on a project that turns a codebase into a knowledge graph and exposes it through MCP tools.

The original problem was simple:

Code search is good at finding text.

But developers usually need answers to harder questions:

- What calls what?
- Which class owns this behavior?
- What files change together?
- Why was this code added in the first place?

That pushed this project beyond plain search.

## What I built

The system parses a mixed-language repository, extracts code entities and relations, stores them as a knowledge graph, and makes them queryable through an MCP server.

At the core, it models things like:

- files
- modules and namespaces
- classes
- functions and methods
- imports
- commits, authors, and work items

And it connects them with relations such as:

- `DEFINES`
- `CONTAINS`
- `CALLS`
- `IMPORTS`
- `INHERITS`
- `IMPLEMENTS`

## The architecture evolved in layers

### 1. Parse and index the repo

The first step was turning source files into a structured graph.

`kg_rag/indexer.py` walks the repo, routes each file to the right parser, and merges the result into one `KnowledgeGraph`.

That gave me a solid structural foundation.

### 2. Add semantic retrieval

A graph alone is useful, but not enough for natural-language questions.

So `kg_rag/retriever.py` combines:

- embedding-based similarity to find relevant entities
- graph traversal to pull the local neighborhood around those entities

That combination turned the project from a parser/indexer into a retrieval system.

### 3. Add an end-to-end workflow

`CodeGraphRAG` in `kg_rag/pipeline.py` became the simple façade that ties together:

- indexing
- caching
- retrieval
- LLM prompting

That made the project easier to use as a tool, not just a set of modules.

### 4. Expose it through MCP

The biggest shift came with `kg_rag/mcp_server.py`.

Once the graph was exposed as MCP tools like:

- `search_code`
- `lookup_symbol`
- `file_overview`
- `call_graph`
- `inheritance_tree`

the project started feeling less like a library and more like agent-ready infrastructure.

## The engineering lessons were practical

A few decisions mattered more than I expected:

- lazy-loading the embedder so MCP startup stays responsive
- capping large tool outputs so stdio clients do not choke
- supporting project scopes because mono-repos are rarely queried as one giant unit
- keeping storage local and simple first, instead of overbuilding the backend

Those details are small individually, but they make the difference between a demo and something you can actually work with.

## The next step is the most interesting one

The first version answered structural questions:

- what exists
- where it lives
- how it connects

Now the system is moving toward intent and history.

That means pulling in:

- git history
- authorship
- co-change patterns
- linked work items from Azure DevOps

The goal is to answer better questions:

- Who usually changes this code?
- What changed with it before?
- Which work item or bug drove this implementation?
- Why does this code exist?

## What I learned building it

The biggest takeaway is that developer understanding needs more than syntax.

If you want a system to help engineers or AI agents reason about a codebase, you need at least four layers:

1. structure
2. retrieval
3. usable tooling
4. history and intent

That is the journey this project has taken so far.

From source files, to graph structure, to semantic retrieval, to MCP tools, and now toward code history and work-item context.

That shift feels important because it moves the system closer to how developers actually think.

Not just:

"What is this code?"

But also:

"Why is this here, and what should I know before I touch it?"

Hashtags: #SoftwareEngineering #AI #MCP #DeveloperTools #CodeSearch #KnowledgeGraph #LLM #Architecture
