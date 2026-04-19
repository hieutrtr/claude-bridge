# Wiki Schema — Operating Manual

> This file is the operating manual for Claude (or any AI assistant) maintaining
> this wiki. Follow these instructions precisely for all Ingest, Query, and Lint
> operations.

Inspired by [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

---

## What Is This Wiki?

A **compounding knowledge base** synthesized from raw agent memories into
cross-referenced entity pages. Raw per-agent memory files are immutable source
documents. Wiki pages are synthesized artifacts that grow richer with every
ingest.

The wiki has **three layers**:

1. **Raw sources** — `~/.claude/projects/*/memory/` (read-only; Bridge never
   writes here).
2. **Wiki** — this directory. Mutable. Owned by Bridge.
3. **Schema** — this file. The operating manual every agent reads before
   touching the wiki.

---

## Page Template

Every entity page must follow this structure:

```markdown
# [Entity Name]

> Last updated: YYYY-MM-DD | Sources: [comma-separated agent + project pairs]

## Summary

[2-4 paragraph synthesis — the "what and why" of this entity]

## Key Facts

- Bullet points of core, stable knowledge
- Include numbers, versions, and names where concrete
- Prefer claims backed by multiple sources

## Cross-references

- [[other-page-name]] — one sentence on how the two relate

## Open Questions

- Flagged contradictions between sources
- Claims that may be stale and need verification
- Questions the sources did not answer
```

---

## Operations

### INGEST

Run when new agent memory has appeared since the last ingest.

1. Read each new source file in full.
2. Identify which wiki entity pages it touches (may be multiple).
3. For each touched page:
   - Update **Summary** if the source adds new context.
   - Add new bullets to **Key Facts**.
   - Add or update **Cross-references**.
   - Flag any **Contradictions** in **Open Questions**.
   - Update the `Last updated` date and append to Sources.
4. If the source introduces a new entity that fits no existing page, create a
   new page following the template above and add a row to `index.md`.
5. Append to `log.md`:
   ```
   YYYY-MM-DD | INGEST | <source-summary> → updated <pages-touched>
   ```

### QUERY

Run when answering a knowledge question against the wiki.

1. Search the wiki first — grep for key terms across all entity pages.
2. Synthesize an answer with inline citations (`[Source: wiki/page.md]`).
3. If the answer reveals something novel not yet in the wiki:
   - Update the relevant entity page.
   - Append to `log.md`:
     ```
     YYYY-MM-DD | QUERY | "<question>" → updated <pages>
     ```

### LINT

Run weekly or on demand.

1. Scan all entity pages for:
   - **Orphaned cross-references** — `[[page-name]]` that does not exist.
   - **Stale dates** — `Last updated` older than 60 days when newer source data
     exists.
   - **Missing sources** — agents with memory not yet reflected anywhere.
   - **Contradictions** — claims that conflict between pages (deep lint only).
2. Append findings to `log.md`:
   ```
   YYYY-MM-DD | LINT | <findings summary>
   ```

---

## Cross-reference Conventions

- Use `[[page-name]]` format (filename without `.md`).
- Always follow with `— ` and a one-sentence reason.
- Example: `[[api-conventions]] — rate-limit middleware is defined here`.

---

## Naming Conventions

- All page filenames: `kebab-case.md`.
- All dates: `YYYY-MM-DD` (ISO 8601).
- Entity names in page titles: Title Case.
- Source references: `agent-name @ project-basename` (one line per source).

---

## Boundaries

- Bridge writes **only** inside this wiki directory.
- Bridge never edits files under `~/.claude/projects/*/memory/`.
- The Bridge Bot reads the wiki via the `wiki_query` tool. It does not write
  to the wiki — only the `bridge-cli wiki ingest` command does.
