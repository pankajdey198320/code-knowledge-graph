# TODO: Enrich KG with Commit History & Work Item Context

## Goal

Add **temporal** (git history) and **intent** (user stories / bugs) layers on top of
the existing **structural** knowledge graph so we can answer "why / who / when"
questions — not just "what / how".

---

## New Entity & Relation Types

### Entities
- `commit` — sha, message, author, date, branch
- `author` — name, email
- `work_item` — id, title, description, type (story/bug/task), state, tags, area_path

### Relations
- `MODIFIED_BY` — file/function → author (weighted by commit count)
- `COMMITTED_IN` — file → commit
- `CO_CHANGED` — file ↔ file (same-commit co-occurrence, weighted by frequency)
- `IMPLEMENTS` — commit → work_item (from commit message `#1234` / `AB#1234`)
- `FIXES` — commit → work_item (when type = Bug)

---

## New Components

| File | Purpose |
|---|---|
| `kg_rag/git_history.py` | Parse `git log`, extract commits, authors, co-change pairs, work item IDs |
| `kg_rag/workitems.py` | ADO / Jira API client to hydrate work item entities |
| `kg_rag/enrichment.py` | Merge temporal + intent layers into graph; build enriched entity descriptions |

---

## New MCP Tools

| Tool | Purpose |
|---|---|
| `code_ownership` | Who owns / frequently modifies this file or function? |
| `change_coupling` | What files always change together with X? |
| `work_items_for_code` | What user stories / bugs are linked to this file/class? |
| `code_for_work_item` | What code was changed for story #1234? |
| `hot_spots` | Which files have the most churn (commits × complexity)? |
| `blame_context` | Why was this code written? Who wrote it and for what purpose? |

---

## Implementation Phases

### Phase 1 — Git History (no external deps)

- [x] **1a.** `git_history.py` — parse `git log` output into commit / author entities + relations
  - Command: `git log --name-only --no-merges --pretty=format:"COMMIT|%H|%an|%ae|%ad|%s" -- <scope_paths>`
  - Extract: commit entity, author entity, COMMITTED_IN and MODIFIED_BY relations
  - Support `--since` time window and project scope_paths filtering
- [x] **1b.** Co-change analysis — build `CO_CHANGED` edges
  - Skip commits touching > 50 files (noise from large refactors)
  - Only create edge when files co-occur in ≥ 3 commits
  - Store frequency weight on relation metadata
- [x] **1c.** Add MCP tools: `code_ownership`, `change_coupling`, `hot_spots`
- [x] **1d.** Enriched entity descriptions → re-embed
  - Append ownership + co-change + commit frequency info to entity text
  - Re-run embedding so semantic search understands context

### Phase 2 — Work Item Linking (commit message parsing, no API)

- [x] **2a.** Regex extraction of work item IDs from commit messages
  - Patterns: `#\d+`, `AB#\d+`, `JIRA-\d+` (configurable)
  - Create `work_item` entity (id only) + `IMPLEMENTS` / `FIXES` relations
- [x] **2b.** Add MCP tools: `work_items_for_code`, `code_for_work_item`
- [x] **2c.** Include linked work item IDs in enriched entity descriptions

### Phase 3 — Work Item Hydration (requires API access)

- [ ] **3a.** ADO / Jira API client with local cache (JSON or SQLite)
  - Config: `ADO_ORG`, `ADO_PROJECT`, `ADO_PAT` in `.env`
  - Batch fetch, cache to `data/workitems_cache.json`
- [ ] **3b.** Hydrate `work_item` entities with title, description, type, tags
- [ ] **3c.** Embed work item descriptions → semantic search over intent
- [ ] **3d.** Add MCP tool: `blame_context` (full "why" answers combining all layers)

---

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Git granularity | File-level first, function-level opt-in | `git log --name-only` is fast; `git log -L` per function is expensive |
| Co-change threshold | ≥ 3 commits, skip commits > 50 files | Reduces noise from bulk refactors |
| Merge commits | Skip (`--no-merges`) | Avoids inflated co-change counts |
| Time window | Configurable `--since` (default 1 year) | Keeps graph size manageable for large repos |
| Work item cache | Local JSON file | No database dep; simple invalidation by re-fetch |
| Enriched descriptions | Append to existing entity text before embedding | Single embedding space; no separate index needed |

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Large repos → millions of commits → memory | Scope by project paths + `--since` time window |
| Dense co-change graph from big commits | Skip commits touching > 50 files; require ≥ 3 co-occurrences |
| Work item API rate limits | Cache aggressively; batch requests |
| Commit messages don't reference work items | Phase 2 degrades gracefully — git history still provides value |
| Graph size grows significantly | Keep commit/author entities lightweight; co-change as weighted edges only |

---

## Queries This Enables

| Question | Data path |
|---|---|
| "Why was this class changed?" | file → commit → work_item |
| "Who knows this code best?" | `MODIFIED_BY` frequency ranking |
| "What files always change together?" | `CO_CHANGED` edges |
| "What was the purpose of this function?" | file → commit → work_item description |
| "What's the blast radius of changing X?" | structural neighbors ∪ co-change neighbors |
| "Which files were affected by bug #1234?" | work_item → commits → files |
| "Find code related to 'turbine loading'" | Semantic search over enriched descriptions (code + work item text) |
| "What are the hot spots / risk areas?" | Commit frequency × structural complexity |
