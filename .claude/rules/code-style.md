---
description: Code style and conventions for Claude Bridge
paths: ["src/**/*.py", "tests/**/*.py"]
---

# Code Style

- Python 3.11+, use modern syntax (match, `str | None`, etc.)
- stdlib only — no pip dependencies for core package
- Type hints on all function signatures
- Docstrings on all public functions (one-line or Google style)
- No classes unless state management is needed — prefer functions
- Error messages to stderr (`print(..., file=sys.stderr)`), normal output to stdout
- Exit code 0 = success, non-zero = error
- Import from package (`from .db import BridgeDB`), not relative file paths
