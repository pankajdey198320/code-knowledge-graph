# Dragon's Den Hackathon Proposal

## KG Copilot for Enterprise Codebases

### The idea

Turn a large codebase into a queryable knowledge graph that AI agents can use through MCP.

### The problem

Developers and AI tools struggle with real enterprise repositories because context is scattered across:

- source code
- dependencies and call chains
- git history
- work items and delivery intent

This slows onboarding, increases change risk, and reduces the value of AI coding tools.

### The solution

Our project builds a **code knowledge graph** from a mixed-language repository and exposes it through an **MCP server**.

It can answer questions like:

- what does this feature touch?
- what calls this code?
- who owns it?
- what files usually change together?
- which work item explains why it exists?

### Why it stands out

This is not just search and not just a chatbot.

It combines:

- structural code analysis
- semantic retrieval
- git history and ownership
- work-item context
- MCP-native integration for AI assistants

### Demo

Show an AI assistant using live MCP tools to:

1. find relevant code from a natural-language question
2. expand into call graph and inheritance context
3. show ownership and co-change risk
4. connect the answer to work-item intent

### Value

- faster onboarding
- safer code changes
- better code review context
- stronger ROI from AI tooling

### The ask

Support this as a hackathon winner and pilot it with a real engineering team.

### Closing line

We are not building another chatbot. We are building the missing context layer that makes AI useful in complex codebases.