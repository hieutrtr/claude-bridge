# Tmux Research Documentation Index

This folder contains comprehensive research on using **tmux for persistent Claude Code session management** in Claude Bridge.

## 📚 Documents (Read in This Order)

### 1. **TMUX_RESEARCH_SUMMARY.md** ⭐ START HERE
   - **Purpose:** Overview and quick navigation
   - **Length:** 15 KB, 10 minutes read
   - **Contains:**
     - Quick answers to all research questions
     - Key findings summary
     - Architecture recommendation
     - Implementation roadmap
     - Trade-offs decision matrix
   - **Best for:** Team overview, executive summary, quick reference

### 2. **tmux-quick-reference.md** 🚀 QUICK LOOKUP
   - **Purpose:** Command reference for copy-paste
   - **Length:** 4.6 KB, 5 minutes read
   - **Contains:**
     - Bash command syntax
     - Python wrapper functions
     - Target format examples
     - Minimal working example
   - **Best for:** During implementation, quick lookup while coding

### 3. **tmux-session-management-research.md** 📖 DEEP DIVE
   - **Purpose:** Comprehensive technical research
   - **Length:** 30 KB, 45 minutes read
   - **Contains:**
     - Tmux fundamentals (1)
     - Full command reference (2)
     - Python integration patterns (3)
     - Output capture & ANSI stripping (5)
     - Long-running task handling (6)
     - Permission relay integration (7)
     - Code examples & appendix (11)
   - **Best for:** Understanding the approach deeply, implementation guidance

### 4. **tmux-task-routing-guide.md** 🎯 IMPLEMENTATION GUIDE
   - **Purpose:** Prevent message interleaving, task queueing
   - **Length:** 20 KB, 30 minutes read
   - **Contains:**
     - Interleaving problem explanation
     - TaskRouter architecture (complete code)
     - AgentSession wrapper (complete code)
     - Integration patterns
     - Testing scenarios
   - **Best for:** Implementing the router, understanding task ordering

### 5. **tmux-trade-offs-analysis.md** ⚖️ DECISION JUSTIFICATION
   - **Purpose:** Why tmux over fresh process or process pool
   - **Length:** 15 KB, 25 minutes read
   - **Contains:**
     - Attribute-by-attribute comparison
     - Pros/cons for each approach
     - Real-world impact analysis
     - Scalability considerations
     - MVP decision justification
   - **Best for:** Justifying decisions to stakeholders, Phase 2 planning

---

## 🎯 Quick Navigation by Use Case

### "I need a quick summary"
→ Read: TMUX_RESEARCH_SUMMARY.md (sections 1-2)

### "I need to implement this"
→ Read: tmux-quick-reference.md + tmux-session-management-research.md (sections 2-3)

### "I'm implementing TaskRouter"
→ Read: tmux-task-routing-guide.md (sections 1-3)

### "I need to explain this to the team"
→ Read: tmux-trade-offs-analysis.md (sections 1-2)

### "I need complete working code"
→ Read: tmux-task-routing-guide.md (section 2) + tmux-session-management-research.md (section 3 + appendix)

### "I need to debug a problem"
→ Read: tmux-quick-reference.md (Troubleshooting section)

---

## 🔑 Key Answers (TL;DR)

### Q: How do you send commands to a tmux pane?
```bash
tmux send-keys -t SESSION:WINDOW.PANE "command arg" Enter
```
**Python:** `subprocess.run(["tmux", "send-keys", "-t", target, "cmd", "Enter"])`

### Q: Can you capture output in real-time?
**Yes, via polling:** `tmux capture-pane -t SESSION:WINDOW.PANE -p -S -300`
**Real-time:** Use incremental capture (track line count, get diffs)

### Q: How do you prevent message interleaving?
**Use TaskRouter with per-agent queue + asyncio.Lock():**
- One worker coroutine per agent
- Tasks queued sequentially
- Lock protects queue access
- Output captured atomically after task completes

### Q: Is tmux reliable for long-running tasks?
**Yes, with mitigations:**
- Health check: `tmux has-session -t NAME`
- Timeout: `asyncio.wait_for()` with Ctrl+C
- Recovery: Auto-respawn if dead
- Output: Strip ANSI codes via regex

### Q: Pros/Cons: visibility vs automation vs complexity?

| Aspect | Winner | Why |
|--------|--------|-----|
| **User visibility** | Tmux | Can `tmux attach` and debug live |
| **Automation simplicity** | Fresh process | Fewer steps (pipe I/O) |
| **Overall** | **Tmux** | Benefits outweigh ~140 LOC complexity |

---

## 📊 Document Map

```
Claude Bridge Tmux Research
│
├─ TMUX_RESEARCH_SUMMARY.md ⭐
│  └─ Entry point, quick overview
│
├─ tmux-quick-reference.md 🚀
│  └─ Commands & Python functions (copy-paste ready)
│
├─ tmux-session-management-research.md 📖
│  ├─ Section 1: Fundamentals
│  ├─ Section 2: Command reference
│  ├─ Section 3: Python integration
│  ├─ Sections 4-7: Advanced topics
│  └─ Section 11: Complete code skeleton
│
├─ tmux-task-routing-guide.md 🎯
│  ├─ Problem statement (interleaving)
│  ├─ Solution architecture (TaskRouter)
│  ├─ Complete implementation (ready to use)
│  ├─ Integration patterns
│  └─ Testing scenarios
│
└─ tmux-trade-offs-analysis.md ⚖️
   ├─ Vs Fresh Process
   ├─ Vs Process Pool
   ├─ Scalability analysis
   └─ Phase 2 considerations
```

---

## 🚀 Implementation Checklist

Use this to track progress:

```
Phase 1: Core Infrastructure
  [ ] Read tmux-quick-reference.md
  [ ] Implement AgentSession class (from tmux-task-routing-guide.md)
  [ ] Implement TaskRouter class (from tmux-task-routing-guide.md)
  [ ] Write unit tests (mocked tmux)
  [ ] Write integration test (real tmux)
  [ ] Verify startup <1ms per task, no interleaving

Phase 2: Reliability
  [ ] Session crash recovery
  [ ] Timeout + Ctrl+C handling
  [ ] Incremental output streaming
  [ ] Permission relay integration

Phase 3: Polish
  [ ] User /attach command
  [ ] Task history logging
  [ ] Performance monitoring
  [ ] Documentation for team
```

---

## 📝 Key Sections by Document

### TMUX_RESEARCH_SUMMARY.md
- Section 1: Research questions answered
- Section 2: Key findings summary
- Section 4: Implementation roadmap
- Section 7: Trade-offs decision matrix

### tmux-quick-reference.md
- Session lifecycle commands
- Sending commands & capturing output
- Python wrapper functions
- Target format reference
- Minimal working example

### tmux-session-management-research.md
- Section 2: Complete tmux command reference
- Section 3: Python integration (send, capture, detect)
- Section 4: ANSI stripping
- Section 5: Timeout handling
- Appendix A: Complete code skeleton

### tmux-task-routing-guide.md
- Section 1: Problem (interleaving)
- Section 2: TaskRouter + AgentSession implementation
- Section 3: Execution flow & guarantees
- Section 5: Testing scenarios

### tmux-trade-offs-analysis.md
- Section 1: Executive summary (quick comparison table)
- Sections 2-7: Detailed analysis (one criterion per section)
- Section 11: Conclusion (MVP decision)

---

## 🔗 Related Files in Repo

- **DESIGN.md** — System design (mentions tmux, this research validates it)
- **specs/04-agent-lifecycle.md** — Agent states & process management
- **specs/07-channels.md** — Task routing & message flow
- **docs/daemon-architecture.md** — High-level daemon architecture

---

## 📊 Statistics

| Document | Size | Read Time | Code Examples |
|----------|------|-----------|---|
| TMUX_RESEARCH_SUMMARY.md | 15 KB | 10 min | 8 |
| tmux-quick-reference.md | 4.6 KB | 5 min | 4 |
| tmux-session-management-research.md | 30 KB | 45 min | 25 |
| tmux-task-routing-guide.md | 20 KB | 30 min | 10 |
| tmux-trade-offs-analysis.md | 15 KB | 25 min | 2 |
| **Total** | **85 KB** | **115 min** | **49** |

---

## ✅ Recommendation: PROCEED WITH TMUX

**Why:** Research validates tmux is the right approach for Claude Bridge MVP

**Key Benefits:**
- Network resilience (sessions survive SSH drops)
- User visibility (can `tmux attach` and debug)
- Memory efficiency (one Claude per agent, not per task)
- No startup overhead (3-4s saved per task)

**Manageable Complexity:**
- ~140 lines of core logic (AgentSession + TaskRouter)
- Solvable problems (ANSI stripping, prompt detection, output capture)
- Encapsulated in reusable classes

**Next Step:** Start with Phase 1 implementation using code from tmux-task-routing-guide.md

---

## 📞 Questions?

Refer to the relevant document:
- **"How do I...?"** → tmux-quick-reference.md
- **"Why this approach?"** → tmux-trade-offs-analysis.md
- **"How does it work?"** → tmux-session-management-research.md
- **"How do I implement it?"** → tmux-task-routing-guide.md
- **"What's the big picture?"** → TMUX_RESEARCH_SUMMARY.md

---

**Research Date:** March 26, 2026
**Status:** Complete & Ready for Implementation
**Recommendation:** ✅ Proceed with Tmux Approach
