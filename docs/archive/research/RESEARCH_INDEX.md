# Claude Bridge Remote Trigger Research - Complete Index

**Completed:** March 26, 2026
**Status:** Ready for Implementation
**Scope:** Comprehensive evaluation of remote task dispatch mechanisms for Claude Code

---

## Documents Created

### 1. REMOTE_TRIGGER_RESEARCH.md ⭐ (Start here)
**Length:** ~32 KB | **Sections:** 13
**Purpose:** Comprehensive research document answering all investigation questions

**Contents:**
- Executive summary of findings
- RemoteTrigger API support analysis (YES - undocumented)
- Channels (MCP) deep dive (RECOMMENDED)
- Multi-session & port management
- Latency analysis (Channels: 2-5s, RemoteTrigger: 5-30s est.)
- Reliability & error handling
- 6 recommended architectures
- Security & isolation
- HTTP API design
- Comparison tables
- Final recommendations

**Key Takeaway:**
→ Claude Code supports remote triggers via both **Channels (official)** and **RemoteTrigger API (undocumented)**. Channels is recommended for MVP.

---

### 2. ARCHITECTURE_DECISION.md ⭐⭐ (Read second)
**Length:** ~16 KB | **Format:** ADR (Architecture Decision Record)
**Purpose:** Formal decision on which approach to use

**Contents:**
- Context & problem statement
- Decision: Use Channels (MCP) for MVP
- Detailed pros/cons of each approach
- Comparison table (Channels vs RemoteTrigger vs Custom HTTP)
- Implementation plan (Phases 1-4)
- Trade-offs & risk mitigation
- Alternatives considered & rejected
- Success metrics
- Rollback plan

**Key Takeaway:**
→ **Decided:** Use Channels + tmux + Python daemon for Phase 1 MVP (2-3 weeks)

---

### 3. IMPLEMENTATION_GUIDE.md ⭐⭐⭐ (Read third)
**Length:** ~15 KB | **Format:** Practical how-to guide
**Purpose:** Step-by-step implementation instructions

**Contents:**
- 5-step quick start (5-30 minutes)
- Minimal Bridge daemon code (ready to use)
- Manual testing checklist
- Architecture diagram
- Deployment options
- File structure
- Success criteria
- Troubleshooting guide with solutions

**Key Takeaway:**
→ Ready to code. Follow the 5 steps to get Channels working with bridge daemon.

---

### 4. RESEARCH_SUMMARY.txt
**Length:** ~4 KB | **Format:** Quick reference
**Purpose:** One-page summary of research

**Contents:**
- Quick facts about each approach
- Key findings summary
- Critical success factors
- Implementation path overview
- Next steps

**Use When:** You need a quick refresher on the research findings.

---

## Quick Reference

### Questions & Answers

**Q1: Does Claude Code support remote triggers?**
→ **YES**, via two mechanisms:
- Channels (MCP) - Official, documented, recommended
- RemoteTrigger API - Undocumented, internal, for Phase 2+

**Q2: Can you have multiple Claude Code sessions listening on different ports?**
→ **YES, but Channels don't need ports**
- Channels use outbound polling (no ports)
- If needed: tmux sessions with unique names
- Desktop app: automatic Git worktree isolation

**Q3: What's the latency from trigger to execution?**
→ **2-5 seconds** (Channels polling)
- 1-2s MCP communication
- 2s polling interval (configurable to 1s)
- Total: typically 2-5 seconds for real-world dispatch

**Q4: How reliable is HTTP vs Unix sockets?**
→ **Channels wins:**
- Uses stdio (MCP proven)
- No HTTP infrastructure needed
- No port conflicts, firewall issues, NAT problems
- Outbound polling = inherent reliability

**Q5: Can you implement a lightweight HTTP server in Claude Code hooks?**
→ **YES, but not needed for MVP**
- Phase 2: Custom MCP webhook server on localhost:8788
- Example: Full working code in channels-reference.md
- Would use for CI webhooks, not for main dispatch

**Q6: Loose coupling vs infrastructure overhead?**
→ **Channels provides both:**
- Very loose coupling (MCP protocol)
- Zero infrastructure overhead (polling only)
- Better than HTTP server approach

---

## Implementation Roadmap

### Phase 1: MVP with Channels (2-3 weeks)
```
✓ Create Telegram bot (@BotFather)
✓ Install Telegram plugin (in Claude Code)
✓ Write Bridge daemon (Python, ~100 lines)
✓ Spawn agents with --channels flag
✓ Test task dispatch from Telegram
✓ Test permission relay (approve from phone)
✓ Validate multi-agent isolation
```
**Output:** Basic bridge daemon, manual testing works

### Phase 2: Enhancement System (4-6 weeks)
```
✓ Profile system (YAML loading)
✓ CLAUDE.md auto-generation
✓ Signal accumulation
✓ Enhancement proposals
```
**Output:** Agents get smarter over time

### Phase 2.5: Webhook Support (optional)
```
✓ Custom MCP webhook channel
✓ CI/monitoring integration
✓ Permission relay for webhooks
```
**Output:** Can integrate with CI/alerts

### Phase 3+: Advanced (if needed)
```
✓ RemoteTrigger API exploration
✓ Cloud-based dispatcher
✓ Multi-machine coordination
```
**Output:** Scalable multi-machine setup

---

## Key Files to Reference

| Need | Document | Section |
|------|----------|---------|
| **API Design** | REMOTE_TRIGGER_RESEARCH.md | Section 9 |
| **Endpoint Examples** | REMOTE_TRIGGER_RESEARCH.md | Section 1.2 |
| **Session Management** | REMOTE_TRIGGER_RESEARCH.md | Section 3 |
| **Reliability** | REMOTE_TRIGGER_RESEARCH.md | Section 5 |
| **Security** | REMOTE_TRIGGER_RESEARCH.md | Section 7 |
| **Decision Rationale** | ARCHITECTURE_DECISION.md | All sections |
| **Code to Copy** | IMPLEMENTATION_GUIDE.md | Section 2 |
| **Step-by-Step** | IMPLEMENTATION_GUIDE.md | Section 1 |
| **Testing** | IMPLEMENTATION_GUIDE.md | Section 3 |

---

## Getting Started

### For Understanding
1. Read this index (you are here) - 5 min
2. Read RESEARCH_SUMMARY.txt - 5 min
3. Skim REMOTE_TRIGGER_RESEARCH.md - 15 min

### For Decision-Making
1. Read ARCHITECTURE_DECISION.md carefully - 20 min
2. Review comparison tables - 5 min
3. Understand trade-offs section - 10 min

### For Implementation
1. Follow IMPLEMENTATION_GUIDE.md step-by-step - 30 min total
2. Copy daemon code from Section 2 - 5 min
3. Test using checklist in Section 3 - 20 min

---

## Critical Concepts

### Channels (MCP)
- **What:** MCP servers that push events into Claude Code sessions
- **How:** stdio-based communication (subprocess IPC)
- **Platforms:** Telegram, Discord, iMessage, custom webhooks
- **Best For:** Interactive mobile dispatch, permission relay
- **Latency:** 2-5 seconds (polling-based)

### RemoteTrigger API
- **What:** Undocumented REST API for triggering Claude Code
- **Endpoints:** `/v1/code/triggers`, `/run`
- **Status:** Internal, unsupported, may change
- **Best For:** Phase 2+ research, cloud dispatcher
- **Latency:** 5-30 seconds (estimated)

### Bridge Daemon
- **What:** Python process that spawns Claude Code agents
- **How:** subprocess.Popen with environment setup
- **Responsibilities:** Agent lifecycle, monitoring, logging
- **Size:** ~100-200 lines for MVP

### Permission Relay
- **What:** Mobile user approves tool use without terminal access
- **How:** Inline button in Telegram → sends verdict to Claude Code
- **Critical For:** Unattended operation (big advantage over RemoteTrigger)
- **Security:** request_id signing prevents spoofing

---

## Success Criteria

### MVP (Phase 1) Complete When:
- [x] Research complete
- [x] Architecture decided
- [x] Code examples ready
- [ ] Telegram bot created
- [ ] Bridge daemon implemented
- [ ] Task dispatch working
- [ ] Permission relay working
- [ ] Multiple agents running
- [ ] No conflicts or crashes
- [ ] Documentation complete

---

## Troubleshooting Quick Links

**Problem:** "Channels not documented"
→ See REMOTE_TRIGGER_RESEARCH.md Section 2

**Problem:** "Which approach should I pick?"
→ Read ARCHITECTURE_DECISION.md (full decision analysis)

**Problem:** "How do I implement this?"
→ Follow IMPLEMENTATION_GUIDE.md Section 2 (code provided)

**Problem:** "What about latency?"
→ See REMOTE_TRIGGER_RESEARCH.md Section 4

**Problem:** "What about reliability?"
→ See REMOTE_TRIGGER_RESEARCH.md Section 5

**Problem:** "Can I use HTTP servers?"
→ See REMOTE_TRIGGER_RESEARCH.md Section 9 + Section 6.2

---

## Related Documentation

**In this repo:**
- DESIGN.md - Overall Claude Bridge vision
- SPECS.md - Technical specifications
- README.md - Project overview

**External references:**
- [Claude Code Channels](https://code.claude.com/docs/en/channels)
- [Channels Reference](https://code.claude.com/docs/en/channels-reference)
- [Claude Desktop](https://code.claude.com/docs/en/desktop)
- [Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)
- [MCP Protocol](https://modelcontextprotocol.io)

---

## Document Statistics

| Document | Size | Sections | Focus |
|----------|------|----------|-------|
| REMOTE_TRIGGER_RESEARCH.md | 32 KB | 13 | Comprehensive research |
| ARCHITECTURE_DECISION.md | 16 KB | Multiple | Decision rationale |
| IMPLEMENTATION_GUIDE.md | 15 KB | 7 | Practical how-to |
| RESEARCH_SUMMARY.txt | 4 KB | N/A | Quick reference |

**Total:** ~67 KB of research documentation

---

## Timeline Estimate

**Reading:**
- Executive summary: 5 min
- All documents: 1-2 hours
- Implementation code only: 15 min

**Implementation:**
- Setup (Telegram bot): 5 min
- Bridge daemon: 1-2 hours
- Testing: 1 hour
- **Total MVP:** 2-4 hours of work

**Full Phase 1:**
- Research to deployment: 2-3 weeks (including proper testing)

---

## Next Action

→ **Start here:** REMOTE_TRIGGER_RESEARCH.md (sections 1-3)

→ **Then read:** ARCHITECTURE_DECISION.md (entire document)

→ **Then implement:** IMPLEMENTATION_GUIDE.md (follow steps)

---

**Research Completed:** 2026-03-26
**Status:** Ready for Development
**Confidence Level:** High (comprehensive research, official docs reviewed, multiple examples analyzed)

---

*This research package provides everything needed to implement Phase 1 of Claude Bridge using Channels (MCP) for task dispatch. All critical questions answered, all trade-offs documented, code examples provided.*
