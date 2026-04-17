# From Structure to Intent: Building a Code Knowledge Graph as a Developer Journey

Most code search tools are good at one of two things: finding text, or answering narrow structural questions. This project started from a more ambitious developer need: make a large codebase understandable enough that a human or an AI agent can ask higher-level questions and still get grounded answers.

That is the through-line of this repository. It is not just a parser collection, and it is not just an MCP server. It is a layered attempt to turn source code into a knowledge graph, retrieve the right slice of that graph, and expose it through tools that fit naturally into an LLM-driven workflow.

## The First Problem: Text Search Was Not Enough

The foundation of the project is straightforward: take a mono-repo, walk its files, parse supported languages, and represent the result as entities and relations. But the intent is more specific than indexing files. The code is trying to answer questions such as:

- What classes and functions exist in this project?
- What calls what?
- Where are the inheritance edges?
- Which parts of the code are relevant to a natural-language question?

That motivation shows up immediately in the core data model in `kg_rag/models.py`. The project does not settle for a file list. It defines first-class code entities such as files, modules, namespaces, classes, functions, methods, properties, imports, and later even commits, authors, and work items. The relations are equally deliberate: `DEFINES`, `CONTAINS`, `CALLS`, `IMPORTS`, `INHERITS`, `IMPLEMENTS`, `USES_TYPE`, `OVERRIDES`, `DEPENDS_ON`, and `BELONGS_TO`.

That choice matters because it turns the repository into something that can be traversed, not just searched.

## The First Working Shape: Parse, Merge, Persist

The indexing path is intentionally simple.

`kg_rag/indexer.py` discovers files, filters by supported extensions, routes each file to the correct parser, and merges every per-file graph into one `KnowledgeGraph`. It is a pragmatic implementation: one bad file does not kill the whole run, and the graph is serialized as a local pickle rather than pushed immediately into an external database.

That tells you a lot about the intended development experience. The project is optimized for local iteration first. You can point it at a repository, build a graph, cache it, and move on. The entry point in `kg_rag/cli.py` reinforces that approach by making indexing the first-class user action. The command line supports full-repo indexing, project-scoped indexing, custom paths, git-history enrichment, and optional Azure DevOps hydration.

This is the phase where the project establishes its contract:

1. Source code becomes structured entities.
2. Structured entities become a graph.
3. The graph becomes a reusable local artifact.

That is the minimum viable product, but it is already enough to move beyond grep.

## Language Support Became a Product Decision

The parser router in `kg_rag/parsers/router.py` makes another important design choice visible: this project is for mixed-language codebases, not just Python projects. The extension map covers Python, C and C++ headers and sources, C#, Fortran, Kotlin, PowerShell, TypeScript, TSX, JavaScript, and JSX.

That is a practical concession to how real mono-repos look. If the tool only worked for one language, it would solve a smaller problem than the one the repository is clearly trying to address. The architecture therefore standardizes on a single graph model while allowing language-specific parsers underneath it.

This is one of the more credible parts of the codebase: it keeps the high-level abstractions stable while letting language-specific extraction evolve independently.

## Retrieval Was the Real Leap

A graph alone is useful, but it does not automatically answer developer questions. The real leap in the repo happens when embeddings and graph traversal are combined.

`kg_rag/retriever.py` is where the project stops being only a structural analysis tool and becomes a retrieval system. `GraphRetriever` takes a natural-language query, uses the embedder to find the most similar entities, and then expands outward by graph hops to collect local neighborhood context. The result is not a flat list of matches. It is a shaped subgraph with both entities and relations.

That design is more interesting than a pure vector search setup. A semantic match alone might find the right function name but miss the surrounding relationships. A graph traversal alone might stay structurally correct but fail to find the right entry point from a fuzzy question. Combining both is the key architectural idea in the repository.

It also reveals a mature instinct: retrieval quality depends on both relevance and structure.

## The Project Needed a Facade, Not Just Components

Once indexing and retrieval existed, `kg_rag/pipeline.py` introduced `CodeGraphRAG`, a façade that ties together indexing, caching, retrieval, and LLM completion. This is the point where the repository becomes approachable as a tool rather than a collection of modules.

The class does three jobs:

- load or rebuild the graph
- initialize the retriever
- turn retrieved context into an LLM prompt

That may sound routine, but it is a useful step in the developer journey. Projects often become hard to adopt when their core ideas are spread across too many low-level modules. `CodeGraphRAG` is the codebase acknowledging that it needs an end-to-end story.

The examples in `examples/demo.py` and `examples/demo_offline.py` build on exactly that. One shows the full loop with an LLM client, the other validates the indexing and retrieval path without requiring an external model API. That split is practical. It lowers the friction for testing the architecture locally.

## MCP Changed the Shape of the Project

The most consequential turn in the repository is `kg_rag/mcp_server.py`. Once the graph is exposed through FastMCP tools, the project stops being only a library and starts acting like infrastructure for agents.

This is where the design becomes explicitly tool-oriented:

- `search_code`
- `lookup_symbol`
- `file_overview`
- `list_classes`
- `list_functions`
- `call_graph`
- `inheritance_tree`
- `graph_stats`
- project management tools such as `list_projects`, `switch_project`, and `index_project`

That tool surface says a lot about the expected user. The user is no longer only a Python developer importing a package. The user is also an AI coding assistant, an IDE integration, or an automation flow that needs bounded, composable capabilities.

Several engineering decisions in this file also reflect experience with real MCP behavior:

- graph state is cached globally so subsequent tool calls stay fast
- the embedder is loaded lazily so MCP startup is not blocked by sentence-transformer initialization
- large text responses are truncated to keep stdio transports stable
- project scopes are reloaded from configuration when needed rather than assumed static

Those are not cosmetic details. They are the kind of decisions that usually appear only after a first working version meets real usage constraints.

## Project Scoping Solved the Mono-Repo Reality

`kg_rag/projects.py` adds another sign of maturity. The repository recognizes that indexing an entire mono-repo is often the wrong unit of work. Teams want named scopes, separate caches, and faster targeted queries.

That is why `projects.json` exists and why the CLI and MCP server both understand project names. It is a good example of the codebase becoming more operational without becoming more complicated than necessary.

This is also one of the points where the project starts to feel shaped by actual developer workflow rather than purely by technical curiosity.

## Then the Project Asked a Better Question

The initial system answers structural questions well: what exists, where it lives, and how it connects. But developers eventually ask a different class of question:

- Why was this code added?
- Who usually changes it?
- What other files move with it?
- Which work item or bug was this tied to?

That shift is visible in `TODO.md`, and much of it is already reflected in code under `kg_rag/git_history.py`, `kg_rag/workitems.py`, and `kg_rag/enrichment.py`.

This is the most interesting stage of the repository’s journey because it widens the graph from code structure into engineering history and intent.

`kg_rag/git_history.py` extracts commit history, authorship, co-change relationships, and work-item references from git. `kg_rag/workitems.py` hydrates work-item metadata from Azure DevOps and caches it locally. `kg_rag/enrichment.py` then folds those signals back into enriched descriptions so embeddings can reflect not only what code is called, but what that code has historically meant in the life of the project.

That is a strong idea. It moves the graph closer to answering why-questions instead of just what-questions.

## The Design Bias Is Pragmatic Throughout

One of the better qualities of the codebase is that its ambition is balanced by restraint.

The project does not overcomplicate storage on day one. It keeps a local cache. It uses Pydantic models and straightforward merge logic. It offers an in-memory `NetworkXGraphStore` extension point in `kg_rag/graph_store.py` without forcing all graph operations through a heavier backend immediately. It keeps the command-line flow simple even while adding project scopes and enrichment flags.

You can read that as a consistent engineering position:

- make it useful locally first
- keep the graph model explicit
- accept that retrieval and MCP ergonomics matter as much as parsing accuracy
- add temporal and intent layers only after the structural layer is stable enough to support them

That sequencing is sensible. Many projects try to solve architecture, embeddings, agent integration, and productization all at once. This one appears to have grown in layers.

## What the Repository Is Really Building

At a glance, the repo looks like a code indexing project. In practice, it is building a machine-readable developer context layer.

The important outcome is not only that the code can list classes or trace call graphs. The outcome is that an LLM or developer can interrogate a codebase through a representation that is both structural and increasingly historical.

That is why the MCP server matters. That is why project scopes matter. That is why work-item hydration matters. Each step pushes the repository toward a system that can support real development conversations:

- explain this module
- show me related code
- tell me what changed with it
- help me understand the intent behind it

That is a much stronger target than code search alone.

## Lessons from the Journey

If you read the repository as a developer journey, a few lessons stand out.

First, the graph model had to come before the agent interface. Without stable entities and relations, the MCP layer would have been shallow.

Second, retrieval quality depends on more than vector similarity. The graph neighborhood is what gives the answer context.

Third, operational details shape product quality. Lazy model loading, bounded MCP output, local caches, and scoped indexing are all implementation details, but they are also what make the tool usable.

Fourth, the most valuable code understanding systems do not stop at syntax. They eventually need ownership, churn, and work-item intent.

## Where This Naturally Goes Next

The roadmap suggests the next stage clearly: deepen the history-and-intent layer and make those signals first-class in retrieval and MCP tools. The existing code already points there with ownership, co-change, work-item linking, and blame-style context.

That next phase matters because it completes the original premise. A truly helpful developer context system should answer not only what the code is, but what it has been doing over time and why anyone changed it.

That is the real arc of this codebase: from structure, to retrieval, to tooling, to intent.

And that is a credible developer journey because each step is already visible in the repository.
