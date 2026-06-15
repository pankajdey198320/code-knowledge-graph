# Dragon's Den Hackathon Proposal

## Proposal Title

**KG Copilot for Enterprise Codebases**  
Turn a large, mixed-language repository into a queryable knowledge graph that any AI agent can use through MCP.

## The 60-Second Pitch

Every large engineering team has the same hidden tax: developers, reviewers, and AI assistants waste time trying to understand unfamiliar code. Text search helps find strings. Traditional code browsing helps trace symbols. Neither reliably answers the real questions:

- What does this code do?
- What else will break if I change it?
- Who knows this area best?
- Why was this added in the first place?

Our project turns a mono-repo into a **knowledge graph of code, dependencies, history, and work-item intent**, then exposes it through **MCP tools** that plug directly into AI development workflows.

The result is a practical developer intelligence layer: grounded, explainable, and reusable across repositories without rebuilding bespoke copilots for each team.

## The Problem

In a real enterprise repo:

- code spans multiple languages and frameworks
- architecture knowledge is fragmented across people, commits, and work items
- onboarding is slow
- change impact analysis is manual and error-prone
- AI coding tools are often blind to repository structure and team context

That creates measurable cost:

- slower delivery
- longer incident resolution
- duplicated investigation work
- higher risk when modifying legacy or shared code

## Our Solution

This project packages a reusable Python service, `kg-code-rag`, that:

1. Parses mixed-language repositories into entities and relations.
2. Builds a knowledge graph covering files, classes, functions, methods, imports, inheritance, and call relationships.
3. Adds semantic embeddings so natural-language questions can find relevant code.
4. Enriches the graph with git history, ownership, co-change patterns, and linked work items.
5. Exposes the result as an MCP server that AI agents and IDE integrations can query directly.

This means an assistant can ask the graph questions such as:

- show me the call graph around this feature
- which files usually change together
- who owns this area
- what work item or bug drove these changes
- give me the relevant code context before I generate a change

## Why This Is Different

Most solutions stop at one layer.

- Search tools find text.
- Static analyzers find structure.
- Vector databases find semantically similar snippets.
- Repo assistants answer questions, but often without strong grounding.

We combine all four strengths:

- **structure** through parsers and graph relationships
- **semantics** through embeddings
- **history** through git enrichment
- **intent** through work-item linkage

And we deliver it in a format that modern AI tooling can actually consume: **MCP-native tools**.

## Why Now

AI-assisted development is moving from chat to agentic workflows. The limiting factor is no longer model capability alone. It is **context quality**.

Teams do not need another generic chatbot. They need a reliable context layer that makes AI useful inside their real codebase.

This project is well-timed because it addresses the current bottleneck:

- enterprises already have repositories, tickets, and commit history
- MCP is becoming the integration layer for tool-enabled assistants
- teams want faster delivery without sacrificing code confidence

## What Already Exists In This Project

This is not a slideware concept. The current repo already includes:

- a packaged Python distribution with CLI and MCP entry points
- mixed-language parsing for Python, C++, C#, and additional languages
- graph construction and local caching
- semantic retrieval over graph entities
- MCP tools for search, symbol lookup, file overview, call graph, inheritance, and graph stats
- multi-project and scoped MCP deployment patterns
- git-history enrichment for ownership, churn, and co-change analysis
- work-item hydration support for adding delivery intent
- stdio, SSE, and streamable HTTP transport options

## The Hackathon Demo

### Demo scenario

Use the existing KG project to index a real enterprise-style repository or scoped project area. Then show an AI assistant answering progressively harder questions with grounded tool calls.

### Demo flow

1. Ask a plain-English question about a feature area.
2. Use semantic search to find the right entry points.
3. Expand to call graph and inheritance context.
4. Show ownership and co-change signals for impact analysis.
5. Link the answer back to work items to explain intent.
6. Finish with a concrete developer outcome such as safer code review, faster onboarding, or targeted change planning.

### The judge moment

The reveal is simple: the assistant is no longer guessing from prompts alone. It is operating against a structured, explainable model of the codebase.

## Value Proposition

### For developers

- faster onboarding into unfamiliar systems
- better understanding before editing code
- less time spent chasing context across files, history, and tickets

### For tech leads and reviewers

- better impact analysis
- clearer ownership and change coupling
- improved confidence in proposed changes

### For the business

- reduced engineering friction
- lower regression risk in legacy systems
- better leverage from existing AI tooling investments

## Commercial And Strategic Potential

This can evolve beyond a hackathon artifact into an internal platform capability.

Potential rollout path:

1. Start with one or two high-value repositories.
2. Package the server once and configure multiple project scopes.
3. Integrate with VS Code and internal AI workflows.
4. Add operational metrics such as query volume, time saved, and reduction in investigation effort.

Strategically, this creates a reusable foundation for:

- repository-aware AI copilots
- engineering knowledge retention
- safer modernization of legacy codebases
- faster incident and bug triage

## Moat

The defensibility is not in a generic chat UI. It is in the combination of:

- graph-based code understanding
- enterprise repository scoping
- historical and delivery-context enrichment
- MCP-native integration with agent tooling
- reusable packaging model for many repos

That makes this more than a one-off demo. It is a scalable developer-context platform.

## The Ask

If this were a Dragon's Den pitch, our ask would be:

**Give us backing to turn this from a strong technical prototype into a team-ready developer product.**

Specifically, we want support for:

- hackathon sponsorship and judging recognition
- time to productionize deployment and onboarding
- one pilot team with a real repo and real usage scenarios
- lightweight success metrics around time saved and confidence improved

## Success Criteria For The Hackathon

We should win if we can demonstrate:

- a real repository indexed and queryable
- grounded answers through live MCP tool usage
- at least one example where history or work-item context changes the quality of the answer
- a credible path from demo to internal adoption

## Delivery Plan

### During the hackathon

- tighten the demo script
- ensure one polished repository configuration
- validate the most compelling MCP queries end to end
- prepare a concise before-and-after story: AI without repo context vs AI with KG context

### Immediately after

- harden packaging and setup
- add a small set of showcase queries and benchmarks
- capture pilot feedback from one engineering team

## Risks And How We Handle Them

### Risk: indexing large repos can be slow

Mitigation: use project scopes, shared cache directories, and precomputed embeddings.

### Risk: answers could become too verbose or noisy

Mitigation: keep MCP tools bounded, focused, and grounded in graph entities and relations.

### Risk: adoption fails if setup is complex

Mitigation: package once, configure via MCP environment settings, and standardize a small number of proven deployment patterns.

## Closing Line

We are not pitching another chatbot. We are pitching the missing context layer that makes AI genuinely useful inside a complex engineering estate.

If search helped developers find code, and copilots helped them write code, this project helps them **understand code with evidence**.

That is a hackathon demo worth backing and a product worth growing.

## Optional 2-Minute Spoken Version

"Imagine asking an AI assistant about a legacy feature and getting more than a plausible answer. Instead, it shows the exact files, the call graph, the inheritance chain, the developer who changed it most, the files that usually move with it, and the work item that explains why it exists. That is what this project does.

We have built a code knowledge graph and exposed it through MCP so any agent can query a real repository with grounded context. This is not limited to one language or one repo. It is packaged, scoped, and reusable.

The commercial value is simple: less time lost understanding code, safer changes in complex systems, and better returns from AI tooling already being adopted across engineering teams.

Back this project, and we turn AI from a clever assistant into a repository-aware engineering partner." 