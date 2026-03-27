# Architecture Decision Record: Remote Trigger Approach

**Date:** 2026-03-26
**Status:** Decided
**Decision:** Use Channels (MCP) for MVP, explore RemoteTrigger API in Phase 2
**Impact:** Core architecture choice for task dispatch

---

## Context

Claude Bridge needs a mechanism to:
1. Accept tasks from mobile (Telegram, Discord, etc.)
2. Route to appropriate Claude Code agent session
3. Relay permission requests back to mobile for approval
4. Return results to mobile

**Three approaches evaluated:**

1. **Channels (MCP)** - Official, documented, production preview
2. **RemoteTrigger API** - Undocumented, internal Anthropic API
3. **Custom HTTP Server** - Build our own webhook listener

---

## Decision: Use Channels for MVP

### ✅ Recommended Approach: Channels

**Reasoning:**

1. **Official & Documented**
   - Research preview status (rolling out, stable)
   - Full documentation at code.claude.com/docs/en/channels
   - Multiple working implementations (Telegram, Discord, iMessage)

2. **Permission Relay (Critical Feature)**
   - Mobile user can approve/deny tool use without terminal access
   - Built-in, no extra code needed
   - Secure: request_id signing prevents spoofing

3. **No Infrastructure Overhead**
   - Outbound polling only (no incoming HTTP ports)
   - Works behind NAT, firewalls
   - No port allocation conflicts between agents

4. **Fast Latency (2-5 seconds)**
   - Good enough for interactive use
   - Dominated by polling interval (default 2s, configurable to 1s)
   - MCP stdio connection is instant

5. **Proven Track Record**
   - Telegram, Discord, iMessage channels actively maintained
   - Used in production by early adopters
   - GitHub issues indicate stability

6. **Tight Integration with Claude Code**
   - Runs as subprocess with full MCP support
   - Session receives events in structured `<channel>` tags
   - Reply tools expose Claude's responses back through channel

### ❌ Not Recommended: RemoteTrigger API (for MVP)

**Why not:**

1. **Undocumented & Unsupported**
   - Internal Anthropic API, no public documentation
   - May change without notice
   - No SLA or stability guarantee
   - Requires reverse-engineering from RemoteTrigger tool

2. **No Permission Relay**
   - Can't ask for approval remotely
   - Would need custom workflow (manual callback, polling)
   - Breaks MVP goal of "approve from phone"

3. **Unknown Latency & Reliability**
   - Estimated 5-30 seconds (speculation)
   - No SLO guarantees
   - Failure modes unknown (what happens if trigger expires?)

4. **Weak Bidirectional Support**
   - No built-in reply mechanism
   - Would need separate callback/webhook
   - Adds infrastructure complexity

5. **Not Session-Specific**
   - Triggers are global (user-level)
   - Harder to route to specific agent
   - Would need custom routing layer

### ❌ Not Recommended: Custom HTTP Server (for MVP)

**Why not:**

1. **Significant Development Effort**
   - 1-2 weeks to build, test, deploy
   - Need to handle: binding, routing, auth, TLS, etc.
   - Adds operational complexity

2. **Port Management Complexity**
   - Each agent needs unique port (8001, 8002, etc.)
   - Risk of conflicts, NAT issues, firewall rules
   - Channels (polling) has none of this

3. **No Approval Flow**
   - Would need to implement permission relay ourselves
   - Requires secure request_id generation, validation
   - Channels has this built-in

4. **Extra Infrastructure**
   - Requires daemon to manage HTTP server
   - Need monitoring, health checks, rate limiting
   - Channels reuses existing MCP infrastructure

**However:** Custom HTTP is valuable as **Phase 2 enhancement** for webhook support (CI, monitoring events).

---

## Decision Table

| Criteria | Channels | RemoteTrigger | Custom HTTP |
|----------|----------|---|---|
| **Official Support** | ✅ Yes (preview) | ❌ No (internal) | ❌ No |
| **Documentation** | ✅ Excellent | ❌ None | ❌ Self-written |
| **Permission Relay** | ✅ Built-in | ❌ No | ⚠️ Manual |
| **Latency** | ✅ 2-5s | ⚠️ 5-30s? | ⚠️ 3-10s |
| **No Ports/NAT** | ✅ Yes | ⚠️ Unknown | ❌ Requires ports |
| **Bidirectional** | ✅ Yes | ❌ No | ✅ Yes |
| **Development Time** | ✅ <1 week | ⚠️ Unknown | ❌ 1-2 weeks |
| **Complexity** | ✅ Low | ⚠️ Unknown | ⚠️ Medium |
| **Multi-Session** | ✅ Good | ⚠️ Unknown | ⚠️ Needs routing |
| **Production Ready** | ✅ Yes | ❌ No | ✅ Yes (if done) |

---

## Implementation Plan

### Phase 1 (Weeks 1-3): MVP with Channels

**What:**
- Bridge daemon that spawns Claude Code sessions with Telegram plugin
- Session monitoring and restart on crash
- Manual testing of task dispatch and approval flow

**Code:**
```python
# claude_bridge/daemon/agent_manager.py
class AgentManager:
    def spawn_agent(name, project, prompt):
        cmd = [
            "claude",
            "--project", project,
            "--channels", "plugin:telegram@claude-plugins-official",
            "-p", prompt
        ]
        return subprocess.Popen(cmd)
```

**Result:**
- User sends task via Telegram → arrives in Claude Code session
- Agent executes, calls reply tool
- Result sent back to Telegram
- If permission needed: inline button in Telegram, user taps ✅/❌

**Success Criteria:**
- [ ] Task dispatch working
- [ ] Permission relay working
- [ ] Multiple agents running
- [ ] No conflicts or crashes

### Phase 2 (Weeks 4-6): Profile System + Enhancements

**What:**
- Load agent profiles from YAML (identity, rules, context)
- Generate CLAUDE.md from profile
- Track signals during execution
- Accumulate enhancement proposals

**Why Channels Still Good:**
- Channels don't care about profile complexity
- Profile is just a system prompt passed to Claude Code
- Reply tools return unstructured text (Bridge parses it)

### Phase 2.5 (Optional): Custom Webhook Channel

**What:**
- Build MCP webhook server for CI/monitoring events
- Listen on localhost:8788
- Route to appropriate session

**Code Pattern (from official docs):**
```typescript
const mcp = new Server(
  { name: 'webhook', version: '0.0.1' },
  {
    capabilities: {
      experimental: {
        'claude/channel': {},
        'claude/channel/permission': {}  // relay approvals
      },
      tools: {}  // for replies
    }
  }
)

Bun.serve({
  port: 8788,
  async fetch(req) {
    const body = await req.text()
    await mcp.notification({
      method: 'notifications/claude/channel',
      params: { content: body, meta: { source: 'webhook' } }
    })
    return new Response('ok')
  }
})
```

### Phase 3+ (Optional): RemoteTrigger Exploration

**What:**
- Document undocumented RemoteTrigger API
- Build optional HTTP→RemoteTrigger bridge
- Use for cloud-based dispatcher (if Anthropic stabilizes API)

**Why Wait:**
- Channels sufficient for MVP
- RemoteTrigger API status unclear
- More learning value after Phase 1 success

---

## Trade-offs

### What We Gain (Channels)

✅ **Fast Time to MVP** (1-2 weeks)
- Minimal code, plugin does heavy lifting
- Official support & examples
- No infrastructure to build

✅ **Permission Relay** (Critical for unattended use)
- User approves from phone
- Built-in, secure request_id validation
- Same as interactive terminal (but via mobile)

✅ **No Infrastructure Overhead**
- No HTTP server to manage
- No port conflicts
- Works behind NAT/firewall automatically

✅ **Proven Technology**
- Channels in production use
- Multiple implementations working
- Official documentation and support

### What We Trade Off (vs RemoteTrigger)

❌ **Slightly Higher Latency** (2-5s vs unknown)
- Polling adds delay
- But: usually acceptable for development tasks
- Can optimize: reduce poll_interval_seconds

❌ **Polling Overhead** (small constant cost)
- Periodic API calls to Telegram/Discord
- Minimal: ~1 request per 2 seconds per session
- Well within free tier limits

❌ **Tight Coupling to Chat Platforms**
- Task must come from Telegram/Discord/iMessage
- (Phase 2 webhook channel solves this)
- Can't easily add custom dispatch protocols

---

## Risk Mitigation

### Risk: Channels in "Research Preview"

**Mitigation:**
- Status indicates rolling out, not experimental
- Multiple channels (Telegram, Discord, iMessage) already working
- Documented with full API reference
- Used by early adopters without major issues
- **Action:** Monitor GitHub issues, plan Phase 1 as 2-week sprint to get feedback early

### Risk: Latency Too High (2-5s)

**Mitigation:**
- 2-5s is acceptable for non-interactive tasks
- Typical task: fix bug, run tests (minutes of work)
- 2-5s initial latency is negligible
- **Action:** Monitor real usage in Phase 1, optimize poll interval if needed

### Risk: Poll Interval Causes Message Loss

**Mitigation:**
- Telegram/Discord queue messages server-side
- Next poll will retrieve them
- No messages are lost (unlike webhooks)
- **Action:** Verify with live testing in Phase 1

### Risk: Permission Relay Doesn't Work as Expected

**Mitigation:**
- Official docs are comprehensive
- Example code provided in channels-reference.md
- Can fallback to terminal approval (slower but works)
- **Action:** Implement early in Phase 1, test thoroughly

---

## Alternatives Considered (and Rejected)

### Option A: CloudFlare Workers + RemoteTrigger

**Concept:** Cloud-based dispatcher using undocumented RemoteTrigger API

**Rejected because:**
- Requires documenting internal API
- Adds cloud infrastructure (cost, complexity)
- No permission relay support
- Higher latency (5-30s estimated)
- Less reliable than Channels

### Option B: Self-Hosted Webhook Server + Custom Auth

**Concept:** Build HTTP server, route to agents via channel events

**Rejected because:**
- Significant development effort
- Port allocation complexity
- Permission relay would be custom-built
- Not production-ready for MVP timeline

### Option C: SSH Tunneling + Remote Claude Code

**Concept:** SSH into remote machines, spawn Claude Code sessions

**Rejected because:**
- Requires SSH access to each machine
- High latency (network roundtrip)
- Complex key management
- Less reliable than local sessions

### Option D: Claude.ai Web + Dispatch API

**Concept:** Use Claude Desktop's built-in Dispatch feature

**Rejected because:**
- Dispatch is for Claude Desktop, not CLI
- Not suitable for backend automation
- Would require Desktop app on server (expensive)
- Not headless-friendly

---

## Success Metrics (Phase 1)

- [ ] Task dispatch latency < 10 seconds (measured)
- [ ] Permission relay works from mobile (tested)
- [ ] Multiple agents don't interfere (tested)
- [ ] 99% uptime over 1-week trial (monitored)
- [ ] Zero message loss (logged)
- [ ] User satisfaction: can develop features productively

---

## Rollback Plan

If Channels prove inadequate in Phase 1:

1. **Fallback to Terminal Approval** (immediate)
   - Keep Channels, but run agents in foreground terminal
   - User at desk can manually approve
   - Less convenient but functional

2. **Add Custom Webhook Channel** (Phase 2)
   - Provides webhook alternative to Telegram polling
   - Still uses Channels infrastructure

3. **Implement RemoteTrigger HTTP Bridge** (Phase 3)
   - If Anthropic documents API and guarantees stability
   - Acts as secondary dispatch mechanism
   - Optional, not blocking MVP

---

## Dependencies

**Required:**
- Claude Code v2.1.80+ (for Channels support)
- Bun or Node.js (for Telegram plugin)
- Python 3.8+ (for Bridge daemon)
- Telegram Bot (created with @BotFather)

**Optional (Phase 2+):**
- Anthropic RemoteTrigger API (if documented)
- Custom webhook infrastructure
- Discord/Slack bots (if expanding channels)

---

## Architecture Diagram (Decision Outcome)

```
┌─────────────────────────────────────────────┐
│ Mobile User (Telegram)                      │
│ Message: "Fix the login bug"                │
└────────────────┬────────────────────────────┘
                 │
                 ├─ Telegram Bot API
                 │  (polls every 2s)
                 ▼
┌─────────────────────────────────────────────────────┐
│ Local Machine: Bridge Daemon + Claude Code          │
│                                                     │
│ ┌─ Claude Code Session (Agent 1) ─────────────┐   │
│ │ ├─ Project: ~/backend                       │   │
│ │ ├─ Telegram Plugin (MCP)                    │   │
│ │ ├─ System Prompt: "Backend engineer"        │   │
│ │ └─ Listens for <channel> events             │   │
│ │    ↓ (MCP stdio)                            │   │
│ │    Receives: "Fix login bug"                │   │
│ │    ↓                                         │   │
│ │    Executes task...                         │   │
│ │    ↓                                         │   │
│ │    Calls: reply tool (returns to Telegram)  │   │
│ └─────────────────────────────────────────────┘   │
│                                                     │
│ ┌─ Claude Code Session (Agent 2) ─────────────┐   │
│ │ ├─ Project: ~/frontend                      │   │
│ │ ├─ Telegram Plugin (MCP)                    │   │
│ │ ├─ System Prompt: "Frontend engineer"       │   │
│ │ └─ (similar architecture)                   │   │
│ └─────────────────────────────────────────────┘   │
│                                                     │
│ ┌─ Bridge Daemon (Python) ──────────────────────┐  │
│ │ ├─ Spawns/monitors agents                    │  │
│ │ ├─ Logs execution history                    │  │
│ │ ├─ Tracks enhancement signals (Phase 2)      │  │
│ │ └─ Health checks                             │  │
│ └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                 │
                 ├─ Telegram Bot API
                 │  (reply tool sends back)
                 ▼
┌─────────────────────────────────────────┐
│ Mobile User (Telegram)                  │
│ Message: "Fixed! Lines 42-56 in auth.ts"│
└─────────────────────────────────────────┘
```

---

## Conclusion

**Decision: Use Channels (MCP) for Phase 1 MVP**

This approach:
1. ✅ Gets MVP working in 2-3 weeks
2. ✅ Provides permission relay (critical feature)
3. ✅ Requires minimal infrastructure
4. ✅ Is officially supported and documented
5. ✅ Can be extended with custom channels in Phase 2

If problems arise, we can:
- Add webhook channels (Phase 2)
- Explore RemoteTrigger API (Phase 3, if documented)
- Fallback to terminal approval (always works)

**Next Steps:**
1. Create Telegram bot
2. Implement Bridge daemon
3. Test task dispatch
4. Test permission relay
5. Declare MVP complete

---

**Document Version:** 1.0
**Status:** Approved for Development
**Last Updated:** 2026-03-26
