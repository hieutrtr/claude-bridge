---
description: Code review checklist applied after each task implementation
paths: ["src/**/*.py", "tests/**/*.py"]
---

# Code Review Checklist

Run this checklist after Step 3 (code passes tests) and before Step 5 (commit).

## Architecture Compliance
- [ ] Matches architecture doc for this module (ownership boundaries respected)
- [ ] State transitions follow: created → idle → running → idle (agent); pending → running → done/failed/timeout/killed (task)
- [ ] SQLite: WAL mode, foreign keys ON, CASCADE where specified
- [ ] Session ID uses `--` separator (double-dash)
- [ ] File paths use `os.path.expanduser()`, no hardcoded home directories
- [ ] Bridge never writes to Auto Memory (read-only)

## Code Quality
- [ ] Type hints on all function signatures
- [ ] Docstrings on all public functions
- [ ] Errors to stderr (`print(..., file=sys.stderr)`), output to stdout
- [ ] No external dependencies (stdlib only)
- [ ] No bare `except:` blocks — catch specific exceptions
- [ ] Exit code 0 = success, non-zero = error

## Edge Cases
- [ ] Handles missing/empty input
- [ ] Handles missing files gracefully (no unhandled FileNotFoundError)
- [ ] Handles already-dead PIDs (ProcessNotFoundError caught)
- [ ] Handles concurrent SQLite access (WAL mode + transactions)
- [ ] Idempotent where specified (schema init, workspace creation)

## Tests
- [ ] All tests pass: `pytest tests/test_{module}.py -v`
- [ ] Happy path covered
- [ ] At least 2 edge cases covered
- [ ] Error conditions covered
- [ ] Subprocess calls mocked (never calls real `claude` CLI)
- [ ] Uses `tmp_path` for database and file operations
