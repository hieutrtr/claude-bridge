# Phase 6: Wiki Memory — Task Breakdown

See [`plan/phases/phase-6-wiki-memory/README.md`](../phases/phase-6-wiki-memory/README.md) for architecture and rationale.

Tasks follow the standard workflow in `.claude/rules/phase-plan-approach.md`:
task spec → write tests → fix code → code review → commit. Task specs live at
`specs/tasks/M{N}-T{N}.md`, created before any code is written.

---

### Milestone 23: Wiki Skeleton + Schema

#### Task 6.1: Wiki home + schema seed
- **Description:** Create `src/claude_bridge/wiki.py` with `wiki_home()` helper. On first access, initialize `~/.claude-bridge/wiki/` with `schema.md`, `index.md`, and empty `log.md`. Seed `schema.md` from a template bundled in the package (adapted from Karpathy + the reference wiki at `notes.hieutrungdao/wiki/schema.md`).
- **Effort:** 1.5 hours
- **Dependencies:** Phase 1 `get_bridge_home()` helper
- **Acceptance Criteria:**
  - [ ] `wiki.wiki_home() -> Path` returns `~/.claude-bridge/wiki/` (respects `CLAUDE_BRIDGE_HOME`)
  - [ ] Idempotent init — re-running never overwrites existing files
  - [ ] `schema.md` seeded with Karpathy 3-layer model + Summary/Key Facts/Cross-references/Open Questions template + `[[page]]` convention + ISO-date rules
  - [ ] `index.md` seeded with header + empty catalog table
  - [ ] `log.md` empty (append-only)
  - [ ] Path-boundary guard: `wiki.write(relative_path, content)` rejects any path that resolves outside wiki home (symlink attack test)
  - [ ] Tests use `tmp_path` and `CLAUDE_BRIDGE_HOME` override

#### Task 6.2: Source collector
- **Description:** In `wiki.py`, add `collect_sources(agent_filter: str | None = None) -> list[SourceRecord]`. Iterates all agents from `BridgeDB`, reuses `memory.read_memory()`, returns a list of dicts: `{agent, project_dir, main_memory, topics, source_mtime}`.
- **Effort:** 1.5 hours
- **Dependencies:** Task 6.1, existing `memory.py`, existing `db.list_agents()`
- **Acceptance Criteria:**
  - [ ] Returns empty list when no agents
  - [ ] Returns empty source record (not error) for agents with no Auto Memory yet
  - [ ] `agent_filter` narrows to a single agent
  - [ ] `source_mtime` is max mtime across MEMORY.md + topic files (used for staleness)
  - [ ] Never writes to `~/.claude/projects/` — verified by monkey-patched `open` in test
  - [ ] Tests mock `memory.read_memory` and `db.list_agents`

---

### Milestone 24: Ingest Pipeline

#### Task 6.3: Synthesis prompt template
- **Description:** Author the ingest prompt that instructs `claude -p` to synthesize sources into wiki pages. The prompt must include: the schema verbatim, current `index.md`, relevant existing entity pages, new source bundles, and the expected output contract (pages to create/update, log entry text). Store as `src/claude_bridge/prompts/wiki_ingest.md`.
- **Effort:** 1.5 hours
- **Dependencies:** Task 6.1
- **Acceptance Criteria:**
  - [ ] Prompt file exists and is importable via `importlib.resources`
  - [ ] Prompt instructs Claude to use Read/Edit tools only, and only within wiki home
  - [ ] Prompt specifies log entry format `YYYY-MM-DD | INGEST | <sources> → <pages-touched>`
  - [ ] Prompt includes examples of good and bad synthesis (2 each)
  - [ ] Snapshot test pins the prompt content (guards against accidental edits)

#### Task 6.4: Ingest runner
- **Description:** `wiki.ingest(agent_filter: str | None = None, project_scope: str | None = None) -> IngestResult`. Spawns `claude -p` with the ingest prompt, restricted tools (`Read,Edit,Write`), and working directory = wiki home. Captures which pages changed, parses new log entry, records cost in a new `wiki_operations` SQLite table.
- **Effort:** 2 hours
- **Dependencies:** Task 6.2, Task 6.3, existing `dispatcher.py` subprocess patterns
- **Acceptance Criteria:**
  - [ ] New `wiki_operations` table: `id, operation, started_at, duration_ms, cost_usd, sources_count, pages_changed, agent_filter, exit_code`
  - [ ] Non-zero exit propagates with stderr preserved
  - [ ] Idempotent when sources haven't changed (compares `source_mtime` vs last-ingest timestamp — skips with "up to date" message)
  - [ ] Writes limited to wiki home (integration test with a watchdog asserting no writes to `~/.claude/projects/`)
  - [ ] Cost extracted from `claude -p --output-format json`
  - [ ] All `claude` subprocess calls mocked in unit tests
  - [ ] One opt-in integration test (`@pytest.mark.integration`) that invokes real `claude` CLI

#### Task 6.5: CLI `wiki ingest` command
- **Description:** Wire `wiki ingest` subcommand in `cli.py` with flags: `--agent NAME`, `--project PATH`, `--project-scope PATH`, `--dry-run`.
- **Effort:** 1.5 hours
- **Dependencies:** Task 6.4
- **Acceptance Criteria:**
  - [ ] `bridge-cli wiki ingest` with no args runs across all agents
  - [ ] `--dry-run` prints what would change without invoking `claude -p`
  - [ ] Progress output to stdout: `[ingest] <agent>: N sources, M pages touched`
  - [ ] Errors to stderr, exit code non-zero on failure
  - [ ] Respects `.bridgewiki-ignore` in any scanned project dir (opt-out per project)

---

### Milestone 25: Query + MCP Tool

#### Task 6.6: Retrieval (grep + rank)
- **Description:** `wiki.retrieve(question: str, top_k: int = 5) -> list[RetrievedPage]`. Tokenizes the question (lowercase, strip punctuation, remove stopwords from a small hardcoded set), scores each `wiki/*.md` page by token overlap with title + body headers, returns top-K with paths and excerpts. Stdlib only.
- **Effort:** 1.5 hours
- **Dependencies:** Task 6.1
- **Acceptance Criteria:**
  - [ ] Returns top-K pages by overlap score (ties broken by recent `Last updated`)
  - [ ] Excludes `schema.md`, `index.md`, `log.md` from scoring
  - [ ] Empty wiki → returns `[]` (caller handles)
  - [ ] Excerpt = first 2 lines after matched header
  - [ ] Unit tests cover: single match, multi-match tie, zero match, unicode content

#### Task 6.7: Synthesis + citations
- **Description:** `wiki.query(question: str) -> QueryResult`. Calls `retrieve`, then `claude -p` with a synthesis prompt at `prompts/wiki_query.md` that requires inline `[Source: wiki/page.md]` citations. If the answer introduces a novel synthesis, Claude is instructed to write it back into the relevant wiki page and append to `log.md`.
- **Effort:** 2 hours
- **Dependencies:** Task 6.6, Task 6.3 (prompt pattern)
- **Acceptance Criteria:**
  - [ ] Prompt file `prompts/wiki_query.md` mirrors ingest prompt structure
  - [ ] Result includes: answer text, cited pages, cost, whether wiki was updated
  - [ ] Zero retrieved pages → short-circuit with "no wiki content found, try `wiki ingest`"
  - [ ] Writes confined to wiki home
  - [ ] Subprocess mocked in unit tests, opt-in integration test with real `claude`

#### Task 6.8: CLI + MCP tool surfaces
- **Description:** Add `bridge-cli wiki query "<q>"` subcommand. Add `wiki_query(question: str) -> dict` MCP tool in `mcp_tools.py` so the Bridge Bot can call it from Telegram sessions.
- **Effort:** 1.5 hours
- **Dependencies:** Task 6.7, existing `mcp_tools.py` registration pattern
- **Acceptance Criteria:**
  - [ ] CLI output: answer first, then `Sources:` list, then cost
  - [ ] MCP tool returns structured JSON matching existing `mcp_tools.py` conventions
  - [ ] MCP tool input schema validates question is non-empty string
  - [ ] Tool registered in `mcp_server.py` alongside existing bridge_* tools
  - [ ] Integration test: bot-shaped caller invokes `wiki_query` and gets cited answer

---

### Milestone 26: Lint + Scheduling

#### Task 6.9: Stdlib lint checks
- **Description:** `wiki.lint() -> LintReport`. Pure-Python checks: orphaned `[[xref]]`, stale pages (`Last updated` > 60d AND source `source_mtime` newer), missing sources (agent has memory but no wiki mentions it), malformed headers, broken relative links.
- **Effort:** 1.5 hours
- **Dependencies:** Task 6.1
- **Acceptance Criteria:**
  - [ ] Each check returns `(severity, page, message)` tuples
  - [ ] Exit code non-zero if any `error` severity; `warning`-only is still exit 0
  - [ ] Unit tests cover each check with synthetic wikis in `tmp_path`
  - [ ] No LLM calls in `lint()` default path

#### Task 6.10: `--deep` contradiction detection
- **Description:** Optional `wiki.lint(deep=True)` invokes `claude -p` with `prompts/wiki_lint.md` to detect semantic contradictions between pages. Cost logged in `wiki_operations`.
- **Effort:** 1 hour
- **Dependencies:** Task 6.9
- **Acceptance Criteria:**
  - [ ] Prompt asks for structured list: `{page_a, page_b, claim_a, claim_b, confidence}`
  - [ ] Result merged into `LintReport` with severity `contradiction`
  - [ ] Skipped silently if wiki has < 2 entity pages
  - [ ] Subprocess mocked in unit tests

#### Task 6.11: CLI + optional scheduler
- **Description:** `bridge-cli wiki lint [--deep]`. Add opt-in cron entry generator `bridge-cli wiki schedule --weekly` that emits a crontab line for weekly ingest + lint (does not install automatically — prints for the user to install).
- **Effort:** 0.5 hours
- **Dependencies:** Task 6.9, Task 6.10
- **Acceptance Criteria:**
  - [ ] Human-readable lint report with grouped severities
  - [ ] `--json` flag emits machine-readable output
  - [ ] `wiki schedule --weekly` prints crontab line; does NOT modify crontab
  - [ ] Cron line references `$(which bridge-cli)` to survive venv changes

---

### Milestone 27: Bot Integration + Docs

#### Task 6.12: Bridge Bot prompt update
- **Description:** Update `bridge_bot_claude_md.py` to teach the bot about the wiki. New section in the generated `CLAUDE.md` explaining: (1) the wiki exists, (2) call `wiki_query` before answering knowledge questions, (3) the schema at `~/.claude-bridge/wiki/schema.md` is authoritative, (4) the bot should NEVER edit the wiki directly — only `wiki ingest` writes to it.
- **Effort:** 1 hour
- **Dependencies:** Task 6.8
- **Acceptance Criteria:**
  - [ ] Generator produces a `## Wiki` section in the bot CLAUDE.md
  - [ ] Section includes exact tool names and example calls
  - [ ] Snapshot test pins the generated CLAUDE.md
  - [ ] Does not add the section when `wiki/` is empty (fresh install UX)

#### Task 6.13: Documentation
- **Description:** Update root `README.md` with a Wiki Memory section. Add `docs/wiki.md` covering setup, operations, schema, and FAQ (privacy, cost, boundary rules). Cross-link from `CLAUDE.md` (project root).
- **Effort:** 1 hour
- **Dependencies:** Task 6.12
- **Acceptance Criteria:**
  - [ ] README has a "Wiki Memory" row in the features section
  - [ ] `docs/wiki.md` covers: what, why, operations, schema, privacy, cost, troubleshooting
  - [ ] Links back to Karpathy's gist and acknowledges the pattern
  - [ ] `CLAUDE.md` gains a one-paragraph entry pointing to `docs/wiki.md`

---

## Test Strategy Summary

- Unit tests per module in `tests/test_wiki.py` — stdlib only, mocked `claude` subprocess
- One opt-in integration test per milestone that invokes real `claude` CLI (guarded by `@pytest.mark.integration`), skipped in default `pytest` run
- Path-boundary test uses a monkey-patched `open` / `os.write` to assert no filesystem writes land outside `~/.claude-bridge/wiki/`
- Prompt files pinned with snapshot tests (small, deterministic — catches accidental edits in review)

## Commit Format

Per `.claude/rules/phase-plan-approach.md`: `M{N}.T{N}: {short description}` with tests-added + gaps-fixed summary. Each task = one commit.

## Milestone Reports

After M23, M24, M25, M26, M27 complete, write `specs/reports/milestone-{N}-report.md` following the standard template.
