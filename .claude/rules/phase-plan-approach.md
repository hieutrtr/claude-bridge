---
description: Reusable TDD workflow for implementing phased tasks. Apply whenever working on tasks from plan/implementation/phase-*-tasks.md.
paths: ["src/**/*.py", "tests/**/*.py", "specs/**/*.md"]
---

# Phase Development Approach

This workflow applies to every task in every phase. Follow it exactly.

## Per-Task Workflow (5 Steps)

### Step 1: Task Spec (before any code)

Create `specs/tasks/M{M}-T{T}.md` using this template:

```markdown
# M{M}.T{T}: {title}

## Refs
- Architecture: plan/architecture/{doc}.md, section {N}
- Task def: plan/implementation/phase-{P}-tasks.md, Task {M.T}
- Modules: src/claude_bridge/{module}.py
- Dependencies: M{M}.T{prev} (if any)

## What This Task Does
{1-2 sentences}

## Key Architecture Constraints
- {constraint from architecture doc}
- {constraint from architecture doc}

## Test Plan
Happy path:
- {test case}

Edge cases:
- {test case}

Errors:
- {test case}

## Gaps in Existing Code
- {what the current code does NOT handle that architecture requires}
```

### Step 2: Write Tests First

- Add tests to `tests/test_{module}.py`
- Follow patterns: pytest, tmp_path for DB/files, class grouping
- Mock subprocess — never call real `claude` CLI
- Run tests: `pytest tests/test_{module}.py -v`
- Expect some failures against existing scaffold code

### Step 3: Fix/Enhance Code

- Modify `src/claude_bridge/{module}.py` to pass all tests
- Only touch code for the current task
- Keep changes minimal

### Step 4: Code Review

Run through `.claude/rules/code-review.md` checklist.
Note any findings in the task spec or fix immediately.

### Step 5: Commit

```
git commit -m "M{M}.T{T}: {short description}

- Tests: {N} added/updated in test_{module}.py
- Gaps fixed: {brief list or 'none'}

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

## Per-Milestone: Report

After all tasks in a milestone are done, write `specs/reports/milestone-{N}-report.md`:

```markdown
# Milestone {N}: {title} — Report

**Date:** {date}
**Status:** COMPLETE / PARTIAL / BLOCKED

## Task Summary

| Task | Status | Tests | Gaps Fixed | Notes |
|------|--------|-------|------------|-------|
| M{N}.T1 | done | 8/8 | 2 | ... |

## Gaps Discovered and Fixed
- {what TDD caught that scaffold missed}

## Blockers
- {issues blocking next milestone, or "none"}

## Architecture Deviations
- {where implementation differs from architecture docs, and why}

## Next Milestone Readiness
{1-2 sentences}
```

## File Locations

```
specs/tasks/M1-T1.md      # Task specs (one per task, created before implementation)
specs/tasks/M1-T2.md
specs/reports/milestone-1-report.md   # Milestone reports (one per milestone)
```

## Reuse Across Phases

This workflow applies identically to Phase 2 and Phase 3.
Just change the phase-tasks reference file.
No modifications to this rule needed.
