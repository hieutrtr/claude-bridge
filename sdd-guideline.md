# Software Design & Development Guideline for Claude Code Projects

A step-by-step process for taking a project from idea to implementation using Claude Code as your development partner. Based on the Claude Bridge project experience.

---

## 1. Overview

This guideline captures a 7-stage process that produces production-quality software with Claude Code:

```
Stage 1: Brainstorm & Research      → Explore the problem space in parallel
Stage 2: High-Level Architecture    → Define system boundaries and data flows
Stage 3: Detailed Architecture      → Write implementation-ready component docs
Stage 4: Project Scaffold           → Create source tree, CLAUDE.md, rules, tests
Stage 5: Implementation Plan        → Break work into phases, milestones, tasks
Stage 6: Phase Plan Approach        → Define the TDD workflow and review process
Stage 7: Phase Development          → Execute tasks following the workflow exactly
```

**When to use this:** Any greenfield project built with Claude Code where you want structured, test-driven development with traceable decisions.

**Key principle:** Invest heavily in Stages 1-6 (documentation and planning) so that Stage 7 (implementation) is mechanical. Claude Code executes faster and more accurately when architecture docs and rules constrain its decisions.

---

## 2. Stage 1: Brainstorm & Research

**Goal:** Explore the problem space broadly before committing to any approach.

### Process

1. **Identify 3-5 architectural approaches** worth exploring. For Claude Bridge, these were: daemon process, task queue, subprocess management, tmux sessions, and remote triggers.

2. **Launch parallel subagents** to research each approach independently. Each subagent writes a focused research document covering:
   - How the approach works
   - Pros and cons
   - Complexity estimate
   - Fit with existing tools (Claude Code features, OS capabilities)
   - Recommendation

3. **Consolidate findings** into a single vision document that:
   - States the problem clearly
   - Summarizes each approach (1 paragraph each)
   - Declares which approach to use and why
   - Defines user journeys (2-3 scenarios end-to-end)

4. **Research competitive landscape** to avoid building what already exists.

5. **Write detailed specs** — an MVP document with:
   - Scope boundaries (what is in, what is out)
   - Acceptance criteria per feature
   - Data structures (schemas, file formats)
   - CLI commands or API surface
   - Success criteria for the whole MVP

### Output Files

```
research/                           # Raw research docs (one per approach)
  daemon-research.md
  queue-research.md
  ...
specs/
  vision.md                        # Problem statement + user journeys
  mvp.md                           # MVP scope, data structures, CLI, acceptance criteria
```

### Tips

- Subagents are cheap — use 5 in parallel rather than researching sequentially.
- Give each subagent a narrow focus. "Research tmux session management for long-running CLI processes" is better than "research how to manage sessions."
- The vision doc is for humans. Keep it readable, not exhaustive.
- The MVP spec is for Claude Code. Be precise about field names, types, and behaviors.

---

## 3. Stage 2: High-Level Architecture

**Goal:** Define the system in a single document that answers "what are we building and how do the pieces fit together?"

### What the HLA Document Should Contain

1. **System overview diagram** — ASCII art showing all components and their connections. Include the user, external services, and your code.

2. **Component architecture** — Table of every component with:
   - What it does
   - Whether you build it or leverage an existing tool
   - Its input/output

3. **Session/identity model** — How entities are identified and related. For Claude Bridge: `agent + project = session`, with `session_id = "name--project_basename"`.

4. **Data flows** — Step-by-step sequences for the 2-3 most important operations. Example: "User dispatches a task" as a numbered list from trigger to completion.

5. **File system layout** — Every directory and file, with ownership boundaries (what your code owns vs. what external tools own).

6. **Security model** — Permissions, isolation, trust boundaries.

7. **Build vs. leverage summary** — Explicit list of what you build vs. what you reuse from existing tools. This prevents over-engineering.

8. **Phase 2+ extensions** — Brief notes on what the architecture supports in the future without requiring a rewrite.

### Output Files

```
plan/architecture/
  high-level-architecture.md       # The single HLA document
```

### Template

```markdown
# {Project Name} — High-Level Architecture

> {One-line description}

## 1. System Overview
{ASCII diagram}

## 2. Component Architecture
| Component | Purpose | Build / Leverage |
|-----------|---------|------------------|

## 3. {Domain} Model
{Identity scheme, relationships, constraints}

## 4. Data Flows
### 4.1 {Primary Operation}
1. {Step}
2. {Step}

## 5. File System Layout
{Tree with ownership annotations}

## 6. Security Model
{Permissions, isolation, trust boundaries}

## 7. Build vs. Leverage
| We Build | We Leverage |
|----------|-------------|

## 8. Future Extensions
{Phase 2+ notes}
```

---

## 4. Stage 3: Detailed Architecture

**Goal:** Break the HLA into component-level documents with implementation-ready pseudocode.

### Process

1. **Identify 3-5 component boundaries** from the HLA. Each component should map to one or more source modules.

2. **Launch parallel subagents** to write one detailed doc per component. Each doc covers:
   - Responsibility and scope
   - Interface (functions, CLI commands, or API endpoints)
   - Internal logic with pseudocode
   - Error handling
   - Dependencies on other components
   - Data formats (JSON schemas, file formats, DB queries)

3. **Cross-reference** — each doc should reference the HLA sections it implements.

### Output Files

```
plan/architecture/
  high-level-architecture.md       # From Stage 2
  component-a.md                   # Detailed doc per component
  component-b.md
  component-c.md
  ...
```

### Tips

- Pseudocode should be close enough to real code that implementation is a translation exercise, not a design exercise.
- Include exact function signatures, parameter names, and return types.
- Specify error messages verbatim — these are part of the interface.
- Each doc should be self-contained enough that a subagent can implement it without reading the others (though cross-references help).

### Claude Bridge Example

```
plan/architecture/
  bridge-cli.md                    # CLI interface, argument parsing, SQLite module
  bridge-bot.md                    # Telegram MCP, CLAUDE.md command router
  completion-system.md             # Stop hook + watcher fallback, result parsing
  data-and-sessions.md             # Session model, SQLite schema, workspace structure
```

---

## 5. Stage 4: Project Scaffold

**Goal:** Create the source tree, configuration, and rules so Claude Code has full context before writing any implementation code.

### What to Create

#### 5.1 Source Code Scaffold

Create all modules as files with:
- Module docstring explaining its purpose
- Import statements
- Function stubs with signatures, type hints, and docstrings
- No implementation (or minimal placeholder logic)

```
src/{package}/
  __init__.py
  module_a.py                     # Stubs only
  module_b.py
  ...
```

#### 5.2 CLAUDE.md (Project Root)

The most important file for Claude Code. It should contain:

```markdown
# {Project Name}

{One-line description}

## Architecture
{3-5 line summary of how the system works, end to end}

## Project Structure
{File tree with one-line descriptions}

## Key Concepts
{3-5 domain concepts Claude Code must understand}

## Build & Test
{Exact commands to build, test, run}

## Dependencies
{Language version, external tools, runtime requirements}

## Conventions
{Coding style rules — one bullet per rule}

## Development Workflow
{Reference to .claude/rules/ for TDD process}
```

#### 5.3 .claude/rules/ (Claude Code Rules)

Create focused rule files that Claude Code loads contextually:

| File | Purpose | paths filter |
|------|---------|-------------|
| `architecture.md` | Ownership boundaries, session model, DB rules | `src/**/*.py` |
| `code-style.md` | Language style, stdlib-only, type hints, error handling | `src/**/*.py`, `tests/**/*.py` |
| `testing.md` | pytest conventions, mock rules, fixture patterns | `tests/**/*.py` |

Each rule file uses frontmatter to scope when it activates:

```yaml
---
description: Architecture rules and boundaries
paths: ["src/**/*.py"]
---
```

Keep rules concise (10-20 lines each). Claude Code reads them on every prompt — verbose rules waste context.

#### 5.4 Test Scaffold

```
tests/
  __init__.py
  test_module_a.py                # Empty test files
  test_module_b.py
  ...
```

#### 5.5 Project Configuration

- `pyproject.toml` or equivalent build config
- `.gitignore` with language-appropriate patterns
- Initial git commit

### Claude Bridge Example

```
CLAUDE.md                          # Architecture summary, commands, conventions
.claude/rules/
  architecture.md                  # Ownership boundaries, session model, DB rules
  code-style.md                    # Python 3.11+, stdlib only, type hints
  testing.md                       # pytest, tmp_path, mock subprocess
src/claude_bridge/
  cli.py, db.py, session.py, agent_md.py, dispatcher.py,
  on_complete.py, watcher.py, memory.py, claude_md_init.py
tests/
  test_cli.py, test_db.py, test_session.py, ...
pyproject.toml
.gitignore
```

---

## 6. Stage 5: Implementation Plan

**Goal:** Break all work into phases, milestones, and tasks with effort estimates and dependencies.

### Structure

```
Phase (1-3 weeks)
  └── Milestone (1-2 days, 3-5 tasks)
       └── Task (1-4 hours, single module focus)
```

### Implementation Plan Document

A high-level overview with:
- Prerequisites (tools, accounts, versions)
- Development approach (principles)
- Per-phase: goals, components, dependencies, risks, success criteria
- Timeline overview
- File system at each phase

### Per-Phase Task Files

One file per phase with detailed task definitions:

```markdown
## Milestone {N}: {Title} (Day X-Y)

### Task {N}.{T}: {Title}
- **Description:** {What to do, precisely}
- **Effort:** {hours}
- **Dependencies:** Task {N}.{T-1} (if any)
- **Acceptance Criteria:**
  - [ ] {Testable criterion}
  - [ ] {Testable criterion}
- **Files Touched:**
  - `src/{package}/{module}.py`
```

### Output Files

```
plan/implementation/
  implementation-plan.md           # High-level overview
  phase-1-tasks.md                 # Detailed tasks per phase
  phase-2-tasks.md
  phase-3-tasks.md
```

### Tips

- Target 1-4 hours per task. Larger tasks should be split.
- Every task should touch at most 2-3 files. If it touches more, split it.
- Acceptance criteria must be testable — "works correctly" is not a criterion; "returns exit code 0 and prints agent name to stdout" is.
- Dependencies should be explicit. If Task 2.3 requires Task 2.1, say so.
- Include effort estimates even if rough. They help prioritize and detect scope creep.

### Claude Bridge Example

Phase 1 had 6 milestones, 26 tasks, estimated at ~43 hours total:

```
Milestone 1: Foundation (Day 1-2) — project structure, SQLite, agent CRUD
Milestone 2: CLAUDE.md Init (Day 3) — purpose-driven project scanning
Milestone 3: Task Dispatch (Day 4-5) — subprocess, PID tracking, status
Milestone 4: Completion System (Day 6-7) — Stop hook, watcher, cron
Milestone 5: Telegram Integration (Day 8-9) — Bridge Bot, MCP
Milestone 6: Polish (Day 10) — history, memory, edge cases
```

---

## 7. Stage 6: Phase Plan Approach

**Goal:** Define the exact workflow Claude Code follows for every task. This is the most important stage for code quality.

### The TDD Workflow (5 Steps Per Task)

#### Step 1: Task Spec (before any code)

Create `specs/tasks/M{M}-T{T}.md`:

```markdown
# M{M}.T{T}: {title}

## Refs
- Architecture: plan/architecture/{doc}.md, section {N}
- Task def: plan/implementation/phase-{P}-tasks.md, Task {M.T}
- Modules: src/{package}/{module}.py
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
- {what the current scaffold does NOT handle}
```

**Why this matters:** The task spec forces Claude Code to read the architecture docs and identify gaps BEFORE writing code. Without it, Claude Code may implement something that contradicts the architecture.

#### Step 2: Write Tests First (TDD)

- Add tests to `tests/test_{module}.py`
- Follow existing test patterns (fixtures, class grouping)
- Mock external dependencies (subprocess, network, file system where appropriate)
- Run tests — expect failures against scaffold code

#### Step 3: Fix/Enhance Code

- Modify source to pass all tests
- Only touch code for the current task
- Keep changes minimal

#### Step 4: Code Review Checklist

Run through a checklist after code passes tests:

```markdown
## Architecture Compliance
- [ ] Matches architecture doc (ownership boundaries respected)
- [ ] State transitions follow defined state machine
- [ ] File paths use expanduser(), no hardcoded paths

## Code Quality
- [ ] Type hints on all function signatures
- [ ] Docstrings on all public functions
- [ ] Errors to stderr, output to stdout
- [ ] No bare except blocks

## Edge Cases
- [ ] Handles missing/empty input
- [ ] Handles missing files gracefully
- [ ] Handles concurrent access (if applicable)
- [ ] Idempotent where specified

## Tests
- [ ] All tests pass
- [ ] Happy path covered
- [ ] At least 2 edge cases covered
- [ ] Error conditions covered
- [ ] External calls mocked
```

#### Step 5: Commit

```
git commit -m "M{M}.T{T}: {short description}

- Tests: {N} added/updated in test_{module}.py
- Gaps fixed: {brief list or 'none'}"
```

### Per-Milestone: Report

After all tasks in a milestone, write `specs/reports/milestone-{N}-report.md`:

```markdown
# Milestone {N}: {title} — Report

**Date:** {date}
**Status:** COMPLETE / PARTIAL / BLOCKED

## Task Summary
| Task | Status | Tests | Gaps Fixed | Notes |
|------|--------|-------|------------|-------|
| M{N}.T1 | done | 8/8 | 2 | ... |

## Gaps Discovered and Fixed
- {what TDD caught that the scaffold missed}

## Blockers
- {issues blocking next milestone, or "none"}

## Architecture Deviations
- {where implementation differs from architecture docs, and why}

## Next Milestone Readiness
{1-2 sentences}
```

### Rule Files to Create

Add these to `.claude/rules/`:

| File | Content |
|------|---------|
| `phase-plan-approach.md` | The 5-step per-task workflow above |
| `code-review.md` | The checklist above, adapted to your project |

### Output Files

```
.claude/rules/
  phase-plan-approach.md           # TDD workflow
  code-review.md                   # Review checklist
specs/
  tasks/                           # Created during Stage 7
  reports/                         # Created during Stage 7
```

---

## 8. Stage 7: Phase Development

**Goal:** Execute the implementation plan following the TDD workflow exactly.

### Process

1. **Work through tasks sequentially** within each milestone. Follow the 5-step workflow for every task without exception.

2. **Run the full test suite** after each milestone to catch regressions.

3. **Write the milestone report** — this forces you to reflect on gaps found, architecture deviations, and readiness for the next milestone.

4. **Update CLAUDE.md and rules** as new patterns emerge. During Claude Bridge development, we added:
   - PYTHONPATH prefix instructions to the Bridge Bot CLAUDE.md
   - Clarified CLI flag names after finding mismatches
   - Added new conventions as the codebase matured

5. **Do not skip the task spec step.** It is tempting when a task seems simple. The task spec is where Claude Code catches architecture mismatches — skipping it leads to bugs that are harder to find later.

### Tracking Progress

```
specs/tasks/M1-T1.md               # Task spec (created in Step 1)
specs/tasks/M1-T2.md
specs/tasks/M1-T3.md
specs/reports/milestone-1-report.md # Milestone report (created after all tasks)
specs/reports/milestone-2-report.md
```

### When Things Go Wrong

- **Test reveals a bug in architecture:** Fix the architecture doc, update the task spec, then fix the code. Keep the architecture docs as the source of truth.
- **Task is bigger than estimated:** Split it into sub-tasks (M1.T3a, M1.T3b) rather than cramming everything into one commit.
- **Tests pass but behavior is wrong:** Your test plan missed a case. Add the missing test, watch it fail, then fix.

---

## 9. Templates

### 9.1 CLAUDE.md Template

```markdown
# {Project Name}

{One-line description}

## Architecture
{End-to-end flow in 3-5 lines}

## Project Structure
```
src/{package}/
  module_a.py       {description}
  module_b.py       {description}
tests/
plan/
specs/
```

## Key Concepts
- **{Concept}:** {definition}

## Build & Test
```bash
pip install -e .
pytest
python -m {package}.cli {command}
```

## Dependencies
{Language version, external tools}

## Conventions
- {Rule 1}
- {Rule 2}

## Development Workflow
Implementation follows `.claude/rules/phase-plan-approach.md`.
**Per task:** task spec -> write tests -> fix code -> code review -> commit
**Per milestone:** full suite -> milestone report
```

### 9.2 Architecture Rule Template (.claude/rules/architecture.md)

```yaml
---
description: Architecture rules and boundaries for {project}
paths: ["src/**/*.py"]
---
```

```markdown
# Architecture Rules

## Ownership Boundaries
- {Your code} OWNS: {paths}
- {Your code} GENERATES: {paths}
- {Your code} READS ONLY: {paths}
- {External tool} OWNS: {paths}

## {Domain} Model
- {Identity rule}
- {Relationship rule}
- {Constraint}

## Database
- {Engine + mode}
- {Key constraints}
- {Cascade rules}

## Subprocess Management
- {Spawn rules}
- {Kill sequence}
```

### 9.3 Task Spec Template (specs/tasks/M{M}-T{T}.md)

See Stage 6, Step 1.

### 9.4 Milestone Report Template (specs/reports/milestone-{N}-report.md)

See Stage 6, Per-Milestone section.

### 9.5 Code Review Checklist Template (.claude/rules/code-review.md)

See Stage 6, Step 4.

---

## 10. Lessons Learned from Claude Bridge

### TDD Caught Real Bugs

Claude Bridge completed Phase 1-2 with 175 tests across 9 milestones. TDD caught 8 bugs that would have shipped otherwise:

| Bug | What Happened | How TDD Caught It |
|-----|---------------|-------------------|
| Silent kill on delete | `delete-agent` killed running tasks silently instead of erroring | Test asserted that delete-agent with running task raises an error |
| Wrong exception name | Code caught `ProcessNotFoundError` instead of `ProcessLookupError` | Test mocked a dead PID, code crashed with NameError |
| Wrong agent state on failure | `watcher.py` set agent state to `"failed"` instead of `"idle"` (3 occurrences) | Test checked agent state after task failure |
| Shared connection closed | `on_complete.py` called `db.close()` which closed the shared test connection | Test using in-memory DB failed on second operation |
| Wrong CLI flags | Code used `--channel` but spec said `--channels`, `--project-dir` but spec said positional arg | Tests used the correct flags from the spec, code failed to parse |

### Subagents Save Time

Using 5 parallel subagents for research (Stage 1) and detailed architecture (Stage 3) cut those stages from days to hours. The key is giving each subagent a narrow, well-defined scope.

### CLAUDE.md Is the Highest-Leverage File

Every minute spent on CLAUDE.md pays back tenfold. Claude Code reads it on every prompt. A good CLAUDE.md means:
- Claude Code follows your conventions without reminders
- New subagents understand the project immediately
- Architecture decisions are visible, not hidden in chat history

### Rules Should Be Short

The `.claude/rules/` files should be 10-30 lines each. Claude Code reads them on every matching prompt. Verbose rules waste context and get ignored. If a rule needs explanation, put the explanation in the architecture doc and keep the rule file as a concise checklist.

### Task Specs Prevent Architecture Drift

The task spec (Step 1) is the single most valuable step in the workflow. It forces Claude Code to:
- Re-read the architecture doc before writing code
- Identify gaps between the scaffold and the architecture
- Plan tests before implementation

Without task specs, Claude Code tends to implement what seems logical rather than what the architecture specifies. This leads to subtle inconsistencies that compound over time.

### Update Docs During Development

Architecture docs are living documents. When implementation reveals that the architecture was wrong or incomplete, update the architecture doc first, then the code. This keeps the docs trustworthy for future milestones.

In Claude Bridge, we updated CLAUDE.md 4 times during Phase 1 to add conventions that emerged during development (e.g., PYTHONPATH prefix for subprocesses, exact CLI flag names).

### Commit Format Enables Navigation

The `M{M}.T{T}: {description}` commit format makes git log readable:

```
M6.T3: history command with filtering
M6.T2: memory reader integration
M6.T1: NLP-style task dispatch
M5.T3: Bridge Bot CLAUDE.md and command routing
M5.T2: Telegram notification on completion
...
```

You can find exactly when a feature was added, what tests were included, and what gaps were fixed — all from the commit message.

---

## Quick Start Checklist

For a new project, work through these stages in order:

- [ ] **Stage 1:** Write vision doc + MVP spec (use subagents for research)
- [ ] **Stage 2:** Write high-level architecture doc
- [ ] **Stage 3:** Write detailed architecture docs (use subagents, one per component)
- [ ] **Stage 4:** Create source scaffold, CLAUDE.md, .claude/rules/, test scaffold, pyproject.toml
- [ ] **Stage 5:** Write implementation plan + per-phase task files
- [ ] **Stage 6:** Create phase-plan-approach.md and code-review.md rules
- [ ] **Stage 7:** Execute tasks: spec -> tests -> code -> review -> commit -> milestone report
