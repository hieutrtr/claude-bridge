# Phase 6: Wiki Memory — Compounding Knowledge Layer

**Goal:** Synthesize learnings across all agents into a cross-referenced, human- and agent-readable knowledge base that compounds over time. Turn Bridge from a dispatcher into a measurable, learning system.

**Status:** [ ] Not started

**Estimated effort:** ~18 hours

**Dependencies:** Phase 1 complete (agents + Auto Memory reader). Works standalone from Phases 2–5.

**Inspired by:**
- [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — three-layer architecture (raw sources / wiki / schema)
- Hieu Dao's personal wiki at `~/workspace/notes.hieutrungdao/wiki/` — concrete instantiation of the pattern with ingest/query/lint operations that has been running for 6+ months

---

## Why This Phase

Today every agent has **isolated** Auto Memory under `~/.claude/projects/<project>/memory/`. Insights learned by the `backend` agent on project A are invisible to the `frontend` agent on project B. `memory.py` reads these files verbatim — there is no synthesis, no cross-agent search, no contradiction detection.

The Bridge Bot cannot answer "how did we handle X across any project?" It cannot reuse what was learned last week. Each new task re-discovers prior knowledge.

A wiki layer fixes this by **synthesizing** the raw per-agent memories into cross-referenced entity pages that the bot can query.

---

## Key Change

```
Before (Phase 1):
  Agent A memory  ──┐
  Agent B memory  ──┼──>  memory.py reads, returns verbatim
  Agent C memory  ──┘

After (Phase 6):
  Agent A memory  ──┐
  Agent B memory  ──┼──>  wiki ingest ──>  ~/.claude-bridge/wiki/*.md
  Agent C memory  ──┘                         │
                                              ├──>  wiki query "<q>"  (CLI + MCP tool)
                                              ├──>  wiki lint
                                              └──>  wiki index.md + log.md
```

---

## Architecture — Three Layers (Karpathy)

**Layer 1 — Raw sources (immutable, read-only):**
- `~/.claude/projects/<project>/memory/MEMORY.md` + topic files for every agent
- Agent `.md` definitions at `~/.claude/agents/bridge--*.md`
- Bridge NEVER writes to these paths (matches `.claude/rules/architecture.md`)

**Layer 2 — Wiki (Bridge owns, mutable):**
- Location: `~/.claude-bridge/wiki/`
- `wiki/index.md` — catalog of entity pages
- `wiki/log.md` — append-only record of ingest/query/lint operations
- `wiki/<entity>.md` — entity pages (per-project, per-domain, per-concept)
- `wiki/schema.md` — operating manual (seeded on first init, editable)
- Bridge owns writes; outside this directory is off-limits

**Layer 3 — Schema (operating manual):**
- Page template: Summary / Key Facts / Cross-references / Open Questions
- Cross-refs: `[[page-name]] — one-sentence reason`
- Dates: ISO 8601 (`YYYY-MM-DD`)
- Filenames: `kebab-case.md`
- Log format: `YYYY-MM-DD | OPERATION | details`

---

## Three Operations

### `bridge-cli wiki ingest [--agent NAME] [--project PATH]`
Scan Auto Memory for one or all agents → synthesize into entity pages → update index and log.

Uses `claude -p` as the synthesis worker (Bridge already shells out to `claude` for agent tasks — same pattern). The synthesis prompt includes the schema, current wiki state, and new sources; Claude writes updated pages via Read/Edit tools bounded to `~/.claude-bridge/wiki/`.

### `bridge-cli wiki query "<question>"`
Grep + rank wiki pages → pass top-N to `claude -p` → return synthesized answer with `[Source: wiki/page.md]` citations. Also exposed as MCP tool `wiki_query` so the Bridge Bot can answer user questions from the wiki automatically.

### `bridge-cli wiki lint`
Stdlib-only checks (no LLM by default):
- Orphaned `[[xref]]` → page doesn't exist
- Stale pages → `Last updated` > 60 days + newer source files
- Missing sources → agent memory newer than any ingested page
- Optional `--deep` flag runs contradiction detection via `claude -p`

---

## Demo Scenario

After this phase:

```
$ bridge-cli list-agents
backend   /projects/my-api      running
frontend  /projects/my-web      idle
devops    /projects/infra       idle

$ bridge-cli wiki ingest
[ingest] backend: 3 sources, 2 new insights
[ingest] frontend: 5 sources, 1 new insight
[ingest] devops: 2 sources, 1 new insight
Created: wiki/auth-patterns.md
Updated: wiki/api-conventions.md, wiki/deployment.md
Logged: 2026-04-19 | INGEST | 3 agents → 3 pages touched

$ bridge-cli wiki query "how do we handle rate limiting?"
Across projects, rate limiting uses a token-bucket middleware installed at the
gateway layer [Source: wiki/api-conventions.md]. The backend agent's project
uses 60rpm per key; the devops agent's project enforces global 10krpm at the
ingress [Source: wiki/deployment.md]. Contradiction flagged: backend doc says
"per IP" but devops doc says "per key" — needs reconciliation
[Source: wiki/api-conventions.md#open-questions].

$ bridge-cli wiki lint
✓ No orphaned cross-references
⚠ wiki/legacy-auth.md last updated 2026-01-12, but backend memory changed 2026-04-18
✓ No missing sources
```

From Telegram, the Bridge Bot uses `wiki_query` automatically:

```
User: any prior art on debouncing user events?
Bot:  [calls wiki_query("debouncing user events")]
      Yes — the frontend agent settled on a 250ms trailing-edge debounce in
      useSearch hook [Source: wiki/react-patterns.md]. Rationale was API
      cost, not perceived latency. Open question: should native-app agents
      use the same window?
```

---

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Storage format | Flat markdown files | Human-readable, grep-able, diffable. Matches Karpathy's "small wikis don't need search engines." |
| Synthesis engine | Subprocess `claude -p` | Matches existing Bridge pattern (dispatcher.py). Zero new deps. |
| Search backend | Grep + rank (stdlib) | Start simple; Karpathy explicitly: "index file may be all you need." Add SQLite FTS only if corpus grows past a few hundred pages. |
| Write boundary | `~/.claude-bridge/wiki/` only | Respects `.claude/rules/architecture.md` ownership rules. |
| Privacy | `--project-scope` flag on ingest | Some users won't want cross-project synthesis. Default: all projects; opt-out per project via `.bridgewiki-ignore`. |
| Cost visibility | Track in `wiki_operations` SQLite table | Users see what ingest costs; matches existing `cost` command pattern. |

---

## What This Phase Does NOT Do

- **Does not modify Auto Memory.** Strict read-only on `~/.claude/projects/*/memory/`.
- **Does not replace Auto Memory.** Agents still use native memory for per-session learning. Wiki is a synthesis layer on top.
- **No embeddings / vector store.** Stdlib-only rule. If corpus grows beyond what grep can handle, a future phase can add SQLite FTS5 (stdlib-compatible).
- **No real-time updates.** Ingest is manual or scheduled (cron), not hook-driven. Auto Memory churns too often to re-synthesize live.
- **No multi-user wikis.** Single-user Bridge → single wiki. Team sharing is out of scope.

---

## Milestones & Tasks

See [`plan/implementation/phase-6-tasks.md`](../../implementation/phase-6-tasks.md).

| Milestone | Focus | Tasks | Hours |
|---|---|---|---|
| 23 | Wiki skeleton + schema | 2 | 3 |
| 24 | Ingest pipeline | 3 | 5 |
| 25 | Query + MCP tool | 3 | 5 |
| 26 | Lint + scheduling | 3 | 3 |
| 27 | Bot integration + docs | 2 | 2 |

---

## Success Criteria

- [ ] `bridge-cli wiki ingest` produces a coherent wiki from a multi-agent setup in < 2 minutes per agent
- [ ] `bridge-cli wiki query` returns cited answers in < 10 seconds for a typical 20-page corpus
- [ ] Bridge Bot uses `wiki_query` unprompted when answering knowledge questions from Telegram
- [ ] Lint catches ≥ 90% of synthetic contradictions in a seeded test corpus
- [ ] Zero writes observed outside `~/.claude-bridge/wiki/` (verified by path audit in tests)
- [ ] End-to-end integration test with real `claude` CLI (guarded, opt-in) passes

---

## Open Questions (to resolve during implementation)

- Where to store **task transcripts** for richer synthesis? Currently the JSONL lives in `~/.claude/projects/<project>/<session>.jsonl`. Include in sources or stick to Auto Memory only? (Lean: Auto Memory only for v1 — simpler boundary.)
- Should `wiki ingest` be **idempotent** within a session? If run twice in a row with no new source data, should the second run be a no-op? (Lean: yes — check source mtimes against last-ingest timestamp.)
- How do we handle **conflicting insights** across agents? Current plan: surface in `## Open Questions` on the entity page. Alternative: auto-resolve with recency bias. (Lean: surface, don't auto-resolve — matches Karpathy's "contradictions are data.")
