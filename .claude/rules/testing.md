---
description: Testing conventions for Claude Bridge
paths: ["tests/**/*.py"]
---

# Testing Rules

- Use pytest with tmp_path fixture for database tests
- Never hit the real `claude` CLI in tests — mock subprocess calls
- Test database operations with in-memory or tmp_path SQLite
- Test session derivation with pure functions (no I/O)
- Test agent .md generation by checking content strings
- Group tests by class (TestAgentCRUD, TestTaskCRUD, etc.)
