"""Wiki memory — compounding knowledge layer across agents.

Implements M23.T1: wiki home directory helper plus path-boundary-safe
read/write primitives. Later wiki tasks (ingest/query/lint) build on top of
these helpers and must never write outside `wiki_home()`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import date
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from . import get_bridge_home
from . import memory

if TYPE_CHECKING:
    from .db import BridgeDB


class SourceRecord(TypedDict):
    """One agent's Auto Memory snapshot — input to wiki ingest."""

    agent: str
    project_dir: str
    session_id: str
    found: bool
    memory_dir: str | None
    main_memory: str
    topics: list[dict]
    source_mtime: float | None


class IngestResult(TypedDict):
    """Outcome of one `ingest()` call."""

    skipped: bool
    sources_count: int
    pages_changed: list[str]
    cost_usd: float
    duration_ms: int
    exit_code: int
    stderr: str


class RetrievedPage(TypedDict):
    """One ranked page returned from retrieve()."""

    path: str
    score: float
    title: str
    excerpt: str


class QueryResult(TypedDict):
    """Outcome of one `query()` call."""

    answer: str
    sources_cited: list[str]
    pages_retrieved: list[str]
    cost_usd: float
    duration_ms: int
    exit_code: int
    stderr: str
    empty: bool


_OPERATIONAL_PAGES = frozenset({"schema.md", "index.md", "log.md"})

_STOPWORDS = frozenset({
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "do", "does",
    "for", "from", "has", "have", "how", "if", "in", "is", "it", "its",
    "of", "on", "or", "our", "that", "the", "their", "this", "to", "was",
    "we", "what", "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your",
})


_INDEX_TEMPLATE = """\
# Wiki Index

> Content catalog for the Bridge Wiki. Last updated: {today}
> See `schema.md` for operating instructions and `log.md` for history.

---

## Entity Pages

| Page | Description |
|------|-------------|

_No entity pages yet. Run `bridge-cli wiki ingest` to synthesize from agent memories._
"""

_LOG_TEMPLATE = """\
# Wiki Log

> Append-only chronological record of all Ingest, Query, and Lint operations.
> Format: `YYYY-MM-DD | OPERATION | details`

---
"""


def wiki_home() -> Path:
    """Return the wiki home directory, initializing it on first access.

    Creates `<bridge_home>/wiki/` and seeds `schema.md`, `index.md`, and an
    empty `log.md` if they do not already exist. Idempotent — existing files
    are never overwritten.
    """
    home = get_bridge_home() / "wiki"
    home.mkdir(parents=True, exist_ok=True)

    schema_path = home / "schema.md"
    if not schema_path.exists():
        schema_path.write_text(_load_schema_template(), encoding="utf-8")

    index_path = home / "index.md"
    if not index_path.exists():
        index_path.write_text(
            _INDEX_TEMPLATE.format(today=date.today().isoformat()),
            encoding="utf-8",
        )

    log_path = home / "log.md"
    if not log_path.exists():
        log_path.write_text(_LOG_TEMPLATE, encoding="utf-8")

    return home


def safe_write(relative_path: str, content: str, *, overwrite: bool = False) -> Path:
    """Write content to a file inside the wiki home.

    Raises ValueError if `relative_path` resolves outside `wiki_home()`
    (after symlink resolution). Raises FileExistsError if the target exists
    and `overwrite` is False. Creates parent directories as needed.
    """
    resolved = _assert_inside_wiki(relative_path, must_exist=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with open(resolved, mode, encoding="utf-8") as f:
        f.write(content)
    return resolved


def safe_read(relative_path: str) -> str:
    """Read a file inside the wiki home. Raises ValueError if outside."""
    resolved = _assert_inside_wiki(relative_path, must_exist=True)
    with open(resolved, "r", encoding="utf-8") as f:
        return f.read()


def _assert_inside_wiki(relative_path: str, *, must_exist: bool) -> Path:
    """Resolve `relative_path` against the wiki home and assert it stays inside.

    Uses `Path.resolve()` so symlinks pointing outside the wiki are rejected.
    Absolute paths are permitted only if they resolve under the wiki home.
    """
    wiki = wiki_home().resolve()
    candidate = Path(relative_path)
    raw = candidate if candidate.is_absolute() else wiki / candidate
    resolved = raw.resolve()
    try:
        resolved.relative_to(wiki)
    except ValueError as exc:
        raise ValueError(
            f"Path {relative_path!r} resolves to {resolved} which is outside "
            f"wiki home {wiki}"
        ) from exc
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(f"No such wiki file: {relative_path!r}")
    return resolved


def _load_template(name: str) -> str:
    """Load a bundled prompt template by filename via importlib.resources."""
    return (
        resources.files("claude_bridge.prompts")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def _load_schema_template() -> str:
    """Load the seed schema template (kept as a named helper for M23.T1)."""
    return _load_template("wiki_schema_template.md")


def _load_ingest_template() -> str:
    """Load the static portion of the ingest prompt (consumed by M24.T2)."""
    return _load_template("wiki_ingest.md")


def _load_query_template() -> str:
    """Load the static portion of the query prompt (consumed by M25.T2)."""
    return _load_template("wiki_query.md")


def collect_sources(
    agent_filter: str | None = None,
    db: "BridgeDB | None" = None,
) -> list[SourceRecord]:
    """Collect Auto Memory sources across agents for wiki ingest.

    Iterates every registered agent (optionally narrowed by `agent_filter`)
    and reads its Auto Memory via `memory.read_memory`. Computes a
    `source_mtime` as the max mtime of `*.md` files under the memory
    directory; staleness checking in later ingest uses this to skip
    unchanged agents.

    When `db` is None, a `BridgeDB()` is created and closed inside the
    function. An injected `db` is used as-is and never closed.

    Never writes under `~/.claude/projects/*` — the Auto Memory layer is
    strictly read-only from Bridge's perspective.
    """
    from .db import BridgeDB

    owned_db = db is None
    if db is None:
        db = BridgeDB()

    try:
        rows = db.list_agents()
    finally:
        if owned_db:
            db.close()

    records: list[SourceRecord] = []
    for row in rows:
        name = row["name"]
        if agent_filter is not None and name != agent_filter:
            continue
        project_dir = row["project_dir"]
        session_id = row["session_id"]
        mem = memory.read_memory(project_dir)
        records.append(
            {
                "agent": name,
                "project_dir": project_dir,
                "session_id": session_id,
                "found": bool(mem.get("found")),
                "memory_dir": mem.get("memory_dir"),
                "main_memory": mem.get("main", "") or "",
                "topics": mem.get("topics", []) or [],
                "source_mtime": _max_mtime(mem.get("memory_dir")),
            }
        )
    return records


def ingest(
    agent_filter: str | None = None,
    db: "BridgeDB | None" = None,
    source_filter=None,
) -> IngestResult:
    """Run one ingest: collect sources, synthesize via claude -p, log the run.

    Skipped (no subprocess, no row) when the max source mtime has not
    advanced past the last successful ingest's recorded mtime. Failure
    runs (non-zero exit from claude) still write a row so the operation
    is auditable.

    `source_filter` is an optional callable applied after collection.
    It receives the raw SourceRecord list and returns the filtered list.
    Used by the CLI to honor `.bridgewiki-ignore`.
    """
    from .db import BridgeDB

    owned_db = db is None
    if db is None:
        db = BridgeDB()

    try:
        sources = collect_sources(agent_filter=agent_filter, db=db)

        if source_filter is not None:
            sources = source_filter(sources)

        if not sources:
            return _empty_result(skipped=True)

        current_max_mtime = max((s["source_mtime"] or 0.0) for s in sources)
        last_mtime = _last_successful_source_mtime(db)
        if last_mtime is not None and current_max_mtime <= last_mtime:
            return _empty_result(skipped=True)

        home = wiki_home()
        pre_snapshot = _snapshot_wiki_files(home)

        prompt = _assemble_ingest_prompt(sources)
        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "json",
            "--dangerously-skip-permissions",
        ]

        t0 = time.time()
        completed = subprocess.run(
            cmd,
            cwd=str(home),
            capture_output=True,
            text=True,
            timeout=600,
        )
        wall_duration_ms = int((time.time() - t0) * 1000)

        cost_usd, reported_duration_ms = _parse_claude_json(completed.stdout)
        duration_ms = reported_duration_ms or wall_duration_ms

        post_snapshot = _snapshot_wiki_files(home)
        pages_changed = _diff_snapshots(pre_snapshot, post_snapshot)

        _record_operation(
            db,
            operation="INGEST",
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            sources_count=len(sources),
            pages_changed=pages_changed,
            agent_filter=agent_filter,
            exit_code=completed.returncode,
            stderr=completed.stderr,
            last_source_mtime=current_max_mtime,
        )

        return {
            "skipped": False,
            "sources_count": len(sources),
            "pages_changed": pages_changed,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
            "exit_code": completed.returncode,
            "stderr": completed.stderr or "",
        }
    finally:
        if owned_db:
            db.close()


def _empty_result(*, skipped: bool) -> IngestResult:
    return {
        "skipped": skipped,
        "sources_count": 0,
        "pages_changed": [],
        "cost_usd": 0.0,
        "duration_ms": 0,
        "exit_code": 0,
        "stderr": "",
    }


def _assemble_ingest_prompt(sources: list[SourceRecord]) -> str:
    """Build the full ingest prompt: static template + runtime context."""
    template = _load_ingest_template()
    home = wiki_home()

    schema_md = (home / "schema.md").read_text(encoding="utf-8")
    index_md = (home / "index.md").read_text(encoding="utf-8")

    entity_blocks: list[str] = []
    for path in sorted(home.glob("*.md")):
        if path.name in {"schema.md", "index.md", "log.md"}:
            continue
        body = path.read_text(encoding="utf-8").splitlines()[:120]
        entity_blocks.append(f"### {path.name}\n```\n" + "\n".join(body) + "\n```")

    entities_section = (
        "\n\n".join(entity_blocks)
        if entity_blocks
        else "_No entity pages yet._"
    )

    sources_json = json.dumps(sources, indent=2, default=str)

    return (
        f"{template}\n\n---\n\n"
        f"## Current Schema\n\n{schema_md}\n\n"
        f"## Current Index\n\n{index_md}\n\n"
        f"## Existing Entity Pages\n\n{entities_section}\n\n"
        f"## New Sources\n\n```json\n{sources_json}\n```\n\n"
        f"---\n\n"
        f"Now synthesize. Begin by calling Read on any pages you need to update.\n"
    )


def _parse_claude_json(stdout: str) -> tuple[float, int]:
    """Extract (cost_usd, duration_ms) from claude -p JSON stdout."""
    if not stdout:
        return 0.0, 0
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return 0.0, 0
    cost = float(payload.get("total_cost_usd", 0.0) or 0.0)
    duration = int(payload.get("duration_ms", 0) or 0)
    return cost, duration


def _snapshot_wiki_files(home: Path) -> dict[str, float]:
    """Map wiki-relative .md paths to mtimes for change detection."""
    snapshot: dict[str, float] = {}
    for path in home.rglob("*.md"):
        rel = str(path.relative_to(home))
        snapshot[rel] = path.stat().st_mtime
    return snapshot


def _diff_snapshots(
    pre: dict[str, float], post: dict[str, float]
) -> list[str]:
    """Return paths that were created or whose mtime advanced."""
    changed: list[str] = []
    for path, mtime in post.items():
        if path not in pre or mtime > pre[path]:
            changed.append(path)
    return sorted(changed)


def _last_successful_source_mtime(db: "BridgeDB") -> float | None:
    row = db.conn.execute(
        "SELECT MAX(last_source_mtime) AS m FROM wiki_operations "
        "WHERE operation = 'INGEST' AND exit_code = 0"
    ).fetchone()
    if row is None:
        return None
    return row["m"]


def _record_operation(
    db: "BridgeDB",
    *,
    operation: str,
    duration_ms: int,
    cost_usd: float,
    sources_count: int,
    pages_changed: list[str],
    agent_filter: str | None,
    exit_code: int,
    stderr: str,
    last_source_mtime: float,
) -> None:
    db.conn.execute(
        """INSERT INTO wiki_operations (
               operation, duration_ms, cost_usd, sources_count,
               pages_changed, agent_filter, exit_code, stderr,
               last_source_mtime
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            operation,
            duration_ms,
            cost_usd,
            sources_count,
            json.dumps(pages_changed),
            agent_filter,
            exit_code,
            stderr or "",
            last_source_mtime,
        ),
    )
    db.conn.commit()


def retrieve(question: str, top_k: int = 5) -> list[RetrievedPage]:
    """Rank wiki entity pages by token overlap with `question`.

    Score per page = sum over question tokens of `(3 if in title, else
    2 if in any header, else 1 if in body, else 0)`. Ties broken by
    newer mtime. Operational pages (schema/index/log) are excluded.
    Returns [] when no tokens remain after stopword stripping or no
    page scores above 0.
    """
    q_tokens = _tokenize(question)
    if not q_tokens:
        return []

    home = wiki_home()
    scored: list[tuple[float, float, RetrievedPage]] = []
    for path in home.glob("*.md"):
        if path.name in _OPERATIONAL_PAGES:
            continue
        content = path.read_text(encoding="utf-8")
        score, title, excerpt = _score_page(content, q_tokens, path)
        if score <= 0:
            continue
        mtime = path.stat().st_mtime
        scored.append((score, mtime, {
            "path": path.name,
            "score": score,
            "title": title,
            "excerpt": excerpt,
        }))

    # Sort by score desc, then mtime desc (newer first on ties)
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [entry for _, _, entry in scored[:top_k]]


def _tokenize(text: str) -> set[str]:
    """Lowercase + split on word boundaries + drop stopwords and <2-char tokens."""
    raw = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
    return {t for t in raw if len(t) >= 2 and t not in _STOPWORDS}


def _score_page(
    content: str, q_tokens: set[str], path: Path
) -> tuple[float, str, str]:
    """Score a page and pick a title + excerpt.

    Returns (score, title, excerpt). Score is:
        sum over question tokens of max(3 if in title, 2 if in any header,
        1 if in body).
    Title: first H1 line, or filename stem if no H1.
    Excerpt: first 2 non-empty lines under the header that matched the
        most question tokens; falls back to title + first body line.
    """
    lines = content.splitlines()

    title_line = ""
    header_lines: list[str] = []  # (line_index, line_text) pairs
    header_positions: list[tuple[int, str]] = []
    body_tokens: set[str] = set()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# ") and not title_line:
            title_line = stripped[2:].strip()
        elif stripped.startswith(("## ", "### ", "#### ")):
            header_positions.append((i, stripped.lstrip("#").strip()))
            header_lines.append(stripped)
        else:
            body_tokens |= _tokenize(line)

    title_tokens = _tokenize(title_line)
    header_tokens = set()
    for _, h_text in header_positions:
        header_tokens |= _tokenize(h_text)

    score = 0.0
    for tok in q_tokens:
        if tok in title_tokens:
            score += 3
        elif tok in header_tokens:
            score += 2
        elif tok in body_tokens:
            score += 1

    title = title_line or path.stem.replace("-", " ").title()
    excerpt = _pick_excerpt(lines, header_positions, q_tokens, title_line)
    return score, title, excerpt


def _pick_excerpt(
    lines: list[str],
    header_positions: list[tuple[int, str]],
    q_tokens: set[str],
    title_line: str,
) -> str:
    """Return the first 2 non-empty lines under the best-matching header."""
    best_idx: int | None = None
    best_overlap = 0
    for i, h_text in header_positions:
        overlap = len(_tokenize(h_text) & q_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_idx = i

    if best_idx is not None:
        return _first_n_nonempty(lines[best_idx + 1:], 2)

    # Fallback: title line + first non-empty body line
    first_body = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        first_body = stripped
        break
    pieces = [p for p in (title_line, first_body) if p]
    return "\n".join(pieces)


_CITATION_RE = re.compile(r"\[Source:\s*([^\]]+?\.md)\s*\]")


def query(
    question: str,
    top_k: int = 5,
    db: "BridgeDB | None" = None,
) -> QueryResult:
    """Answer a question from wiki content, with inline citations.

    Pipeline: retrieve → assemble prompt → `claude -p` → parse answer +
    citations. Logs to `wiki_operations` with operation='QUERY'. When no
    pages match the question, returns a helpful empty-state answer
    without invoking the subprocess.
    """
    from .db import BridgeDB

    pages = retrieve(question, top_k=top_k)
    if not pages:
        return {
            "answer": (
                "The wiki does not yet contain an answer to this question. "
                "Run `bridge-cli wiki ingest` to synthesize agent memories."
            ),
            "sources_cited": [],
            "pages_retrieved": [],
            "cost_usd": 0.0,
            "duration_ms": 0,
            "exit_code": 0,
            "stderr": "",
            "empty": True,
        }

    owned_db = db is None
    if db is None:
        db = BridgeDB()

    try:
        home = wiki_home()
        prompt = _assemble_query_prompt(question, pages)
        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "json",
            "--dangerously-skip-permissions",
        ]

        t0 = time.time()
        completed = subprocess.run(
            cmd,
            cwd=str(home),
            capture_output=True,
            text=True,
            timeout=300,
        )
        wall_ms = int((time.time() - t0) * 1000)

        answer, cost_usd, reported_ms = _parse_claude_query_json(completed.stdout)
        duration_ms = reported_ms or wall_ms
        retrieved_paths = [p["path"] for p in pages]
        sources_cited = _extract_citations(answer, allowed_pages=retrieved_paths)

        _record_operation(
            db,
            operation="QUERY",
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            sources_count=len(pages),
            pages_changed=[],  # query is read-only
            agent_filter=None,
            exit_code=completed.returncode,
            stderr=completed.stderr or "",
            last_source_mtime=0.0,  # unused for QUERY
        )

        return {
            "answer": answer if completed.returncode == 0 else "",
            "sources_cited": sources_cited,
            "pages_retrieved": [p["path"] for p in pages],
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
            "exit_code": completed.returncode,
            "stderr": completed.stderr or "",
            "empty": False,
        }
    finally:
        if owned_db:
            db.close()


def _assemble_query_prompt(question: str, pages: list[RetrievedPage]) -> str:
    """Build the full query prompt: static template + runtime context."""
    template = _load_query_template()
    home = wiki_home()

    page_blocks: list[str] = []
    for p in pages:
        full = (home / p["path"]).read_text(encoding="utf-8")
        page_blocks.append(f"### {p['path']}\n```\n{full}\n```")

    pages_section = "\n\n".join(page_blocks)

    return (
        f"{template}\n\n---\n\n"
        f"## Question\n\n{question}\n\n"
        f"## Retrieved Pages\n\n{pages_section}\n\n"
        f"---\n\n"
        f"Answer now. Remember: inline [Source: filename.md] citations required.\n"
    )


def _parse_claude_query_json(stdout: str) -> tuple[str, float, int]:
    """Extract (answer, cost_usd, duration_ms) from claude -p JSON stdout."""
    if not stdout:
        return "", 0.0, 0
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout, 0.0, 0
    answer = str(payload.get("result", "") or "")
    cost = float(payload.get("total_cost_usd", 0.0) or 0.0)
    duration = int(payload.get("duration_ms", 0) or 0)
    return answer, cost, duration


def _extract_citations(
    answer: str, allowed_pages: list[str] | None = None
) -> list[str]:
    """Return unique [Source: foo.md] filenames, preserving first-occurrence order.

    When `allowed_pages` is provided, filenames not in the set are dropped —
    this guards against false positives when Claude's answer echoes a
    literal `[Source: page.md]` example from inside a code fence rather
    than citing a real retrieved page.
    """
    allowed = set(allowed_pages) if allowed_pages is not None else None
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _CITATION_RE.findall(answer):
        name = match.strip()
        if allowed is not None and name not in allowed:
            continue
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _first_n_nonempty(lines: list[str], n: int) -> str:
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            break  # hit next header
        out.append(stripped)
        if len(out) == n:
            break
    return "\n".join(out)


def _max_mtime(memory_dir: str | None) -> float | None:
    """Return the newest mtime across `*.md` files in memory_dir, else None."""
    if not memory_dir:
        return None
    if not os.path.isdir(memory_dir):
        return None
    best: float | None = None
    for entry in os.listdir(memory_dir):
        if not entry.endswith(".md"):
            continue
        path = os.path.join(memory_dir, entry)
        if not os.path.isfile(path):
            continue
        mtime = os.path.getmtime(path)
        best = mtime if best is None else max(best, mtime)
    return best
