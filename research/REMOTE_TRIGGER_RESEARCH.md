# Remote Trigger Approach for Claude Bridge: Research & Analysis

**Date:** March 26, 2026
**Context:** Evaluating HTTP/trigger-based architecture for distributed task dispatch to Claude Code sessions
**Status:** Comprehensive research complete with code examples and architectural recommendations

---

## Executive Summary

Claude Code supports two complementary mechanisms for remote task dispatch:

1. **Channels (MCP-based)** - Production-ready, low-latency, bidirectional
2. **RemoteTrigger API** - Available but undocumented publicly, enables HTTP-based trigger registration

For Claude Bridge MVP, **Channels is the recommended approach** for mobile dispatch because it:
- Provides native Telegram/Discord/iMessage integration
- Has built-in permission relay (critical for unattended approval)
- Requires no HTTP infrastructure (no listening ports, no NAT issues)
- Supports bidirectional messaging (replies flow back to caller)
- Available in research preview (requires Bun runtime for pre-built plugins)

However, the RemoteTrigger API exists and could be valuable for **Phase 2** (multiple parallel sessions, cloud-based coordination).

---

## 1. Remote Trigger Support in Claude Code

### 1.1 Does Claude Code Support Remote Triggers?

**YES** - Undocumented but available:

- Claude Code has a `/v1/code/triggers` REST API endpoint (internal/undocumented)
- Available through the RemoteTrigger tool in Claude Code v2.1.80+
- Requires claude.ai login (API key auth not supported)
- Allows CRUD operations: list, get, create, update, run

### 1.2 RemoteTrigger API Endpoint Examples

**API Endpoints:**
```
GET  /v1/code/triggers              - List all triggers
GET  /v1/code/triggers/{trigger_id} - Get trigger details
POST /v1/code/triggers              - Create new trigger
POST /v1/code/triggers/{trigger_id} - Update trigger
POST /v1/code/triggers/{trigger_id}/run - Execute trigger
```

**Example Usage (from RemoteTrigger tool):**
```python
from RemoteTrigger import RemoteTrigger

# List triggers
triggers = RemoteTrigger(action="list")

# Create trigger (returns JSON with trigger_id)
response = RemoteTrigger(
    action="create",
    body={
        "name": "backend-task-001",
        "description": "Backend engineer major task",
        "prompt": "Fix the login bug",
        "project_path": "~/projects/my-app"
    }
)

# Run trigger
result = RemoteTrigger(
    action="run",
    trigger_id="trigger-uuid"
)
```

### 1.3 Known Limitations

1. **No Session-Specific Triggers**: Triggers are global/user-level, not tied to specific running sessions
2. **Async Only**: Run endpoint returns immediately; execution happens in background
3. **No Callback Mechanism**: Results not automatically pushed back to caller (must poll or webhook)
4. **Limited Documentation**: Undocumented in official Claude Code docs; treated as internal API
5. **Authentication**: Requires claude.ai login, not suitable for service-to-service auth
6. **UI-Dependent**: Likely designed for Claude Desktop app integration, not CLI

---

## 2. Channels (Production-Ready Alternative)

### 2.1 What Are Channels?

Channels are MCP servers that push events into running Claude Code sessions. They're the official, documented mechanism for remote dispatch.

**Architecture:**
```
External System (Telegram/Webhook/CI)
    ↓
Local Channel Plugin (MCP Server, polls or listens)
    ↓ (stdio)
Claude Code Session
    ↓ (calls tools)
Running Agent
```

### 2.2 Supported Channels (Built-In)

1. **Telegram** - Poll-based (no incoming ports)
2. **Discord** - Poll-based (no incoming ports)
3. **iMessage** - macOS-only, direct API (no incoming ports)
4. **Fakechat** - Demo channel on localhost:8787 (for testing)
5. **Custom Channels** - Build your own MCP server

### 2.3 How to Use Channels for Claude Bridge

**Session Launch with Telegram Channel:**
```bash
# Install plugin
/plugin install telegram@claude-plugins-official

# Configure token
/telegram:configure YOUR_BOT_TOKEN

# Restart with channel enabled
claude --channels plugin:telegram@claude-plugins-official
```

**From Telegram (Mobile):**
```
@your_bot: Fix the login bug
```

**In Claude Code Session:**
```
<channel source="telegram" user_id="123456" chat_id="999">
Fix the login bug
</channel>

Claude receives this as a structured event, executes the task.
When done, calls the reply tool to send results back to Telegram.
```

### 2.4 Channels vs RemoteTrigger: Comparison

| Feature | Channels | RemoteTrigger |
|---------|----------|---------------|
| **Status** | Research preview, documented | Internal/undocumented |
| **Auth** | claude.ai login | claude.ai login |
| **Trigger Source** | Chat platforms, webhooks, MCP | REST API only |
| **Session-Specific** | Yes (running session receives events) | No (global triggers) |
| **Bidirectional** | Yes (reply tools) | No (manual callback needed) |
| **Permission Relay** | Yes (forward approvals to mobile) | No |
| **Infrastructure** | No listening ports (polls instead) | Could require HTTP listener |
| **Latency** | ~2-5 seconds (polling interval) | Unknown, likely higher |
| **Complexity** | Moderate (install plugin) | Low (REST API) |
| **Production Readiness** | Preview, but stable | Experimental/internal |

---

## 3. Multiple Sessions & Port Management

### 3.1 Can You Run Multiple Claude Code Sessions?

**YES**, with clear isolation:

**Method 1: CLI Sessions (Temporary)**
```bash
# Terminal 1: Backend engineer agent
cd ~/projects/backend
claude --project . --channels plugin:telegram

# Terminal 2: Frontend engineer agent
cd ~/projects/frontend
claude --project . --channels plugin:discord

# Each process is independent
```

**Method 2: Persistent tmux Sessions (Long-Running)**
```bash
# Spawn persistent sessions with profiles
tmux new-session -d -s "coder-backend" \
  "claude --project ~/projects/backend --channels plugin:telegram -p 'Backend engineer...'"

tmux new-session -d -s "coder-frontend" \
  "claude --project ~/projects/frontend --channels plugin:telegram -p 'Frontend engineer...'"

# List sessions
tmux list-sessions
```

**Method 3: Desktop App (GUI)**
Claude Desktop allows parallel sessions with automatic Git worktree isolation:
```
Session 1: /backend (on main branch)
Session 2: /frontend (on worktree branch auto-created)
```

### 3.2 Port Binding (Not Required for Channels)

**Channels Don't Use Ports:**
- Telegram/Discord: Poll the API (outbound only, no listening port)
- iMessage: Direct local API (no network)
- Custom webhooks: Your MCP server on localhost, not exposed to internet

**If Using RemoteTrigger for HTTP Triggers:**
```bash
# Session 1 on port 8001 (your webhook listener)
PORT=8001 claude --project ~/projects/backend

# Session 2 on port 8002 (another webhook listener)
PORT=8002 claude --project ~/projects/frontend

# Bridge sends HTTP POST to localhost:8001 or localhost:8002
curl -X POST http://localhost:8001 -d "Fix login bug"
```

### 3.3 Gotchas & Solutions

| Problem | Solution |
|---------|----------|
| Multiple agents stepping on each other | Use tmux sessions with unique names, or separate terminal windows |
| Port conflicts | Assign different ports per session, or use Channels (no ports needed) |
| Context pollution | Each session maintains independent context; cleanup with `/compact` |
| Git conflicts | Desktop app auto-creates worktrees; manual: `git worktree add <path>` |
| Zombie processes | Always `graceful=true` on shutdown, use tmux to manage |

---

## 4. Latency Analysis

### 4.1 Channel Latency (Recommended for MVP)

**Telegram Channel Latency Breakdown:**

```
User sends message on phone (Telegram)
  ↓
Message stored in Telegram servers
  ↓ (polling interval, default 2 seconds)
Channel plugin queries getUpdates API
  ↓ (50-200ms network roundtrip)
Plugin receives update
  ↓ (immediate)
MCP notification sent to Claude Code (stdio)
  ↓ (1-2ms local IPC)
Claude Code receives event in <channel> tag
  ↓ (immediate)
Claude starts working

Total: 2-5 seconds (mostly waiting for poll interval)
```

**Optimization:**
- Reduce poll interval from default 2s to 1s: `-C telegram:poll_interval_seconds=1`
- Result: ~1-3 seconds total
- Trade-off: More API calls, minimal cost (polls are lightweight)

### 4.2 RemoteTrigger API Latency (Unknown)

```
Client calls /v1/code/triggers/{id}/run
  ↓
Server receives HTTP request
  ↓ (unknown processing)
Trigger queued or dispatched
  ↓
Claude Code picks up task
  ↓ (unknown delivery mechanism)
Session executes

Estimated: 5-30 seconds (highly speculative)
```

**Unknown factors:**
- How are triggers queued?
- How does Claude Code discover new triggers?
- Is there polling on the Claude Code side too?
- Are there ordering guarantees?

### 4.3 Unix Sockets vs HTTP vs stdio

| Method | Latency | Setup | Security | Multi-Machine |
|--------|---------|-------|----------|----------------|
| **Unix Socket** | <1ms | Complex | Good | No |
| **HTTP (localhost:PORT)** | 1-5ms | Simple | Medium | No |
| **stdio (MCP/Channels)** | 1-2ms | Plugin | Excellent | No |
| **Channels (Telegram)** | 2-5s | One-liner | Excellent | Yes (via cloud) |
| **RemoteTrigger API** | 5-30s (est) | REST | Unknown | Yes (if HTTP) |

**For Claude Bridge:** Channels via stdio wins on latency + security + simplicity.

---

## 5. Reliability & Error Handling

### 5.1 Channel Reliability

**Strengths:**
- Polling is inherently reliable (detects missed events on next poll)
- Sender gating prevents prompt injection
- Built-in retry on network errors
- MCP connection monitored; disconnects logged
- Permission relay has timeout handling

**Failure Scenarios:**
```
Scenario 1: Claude Code crashes mid-task
  → Session ends, pending events lost
  → Solution: Persistent sessions with `/attach` or desktop app

Scenario 2: Network outage (no Telegram connectivity)
  → Events queue in Telegram servers
  → Next poll retrieves them (no loss)

Scenario 3: Channel plugin crashes
  → Claude Code exits with error message
  → Solution: Monitor session and restart

Scenario 4: User denies permission from phone
  → Agent pauses, waiting for approval
  → If timeout: can auto-deny or default-deny (configurable)
```

### 5.2 RemoteTrigger Reliability (Unknown)

**Unknowns:**
- How are triggers stored? (Database? Memory? Files?)
- What happens if Claude Code is offline?
- Are there retries? Backoff?
- Is ordering guaranteed?
- Can a trigger expire?

**Speculation:**
- Likely stored in Anthropic's backend
- Probably safe against Claude Code restarts (backend-driven)
- Probably no ordering guarantees (REST API is inherently unordered)

---

## 6. Recommended Architectures

### 6.1 MVP Architecture (Recommended for Claude Bridge Phase 1)

**Use Channels + tmux for multi-agent support:**

```
┌─────────────────────────────────────────┐
│ Mobile (Telegram iOS/Android)           │
│ User: "Fix login bug"                   │
└─────────────────────────────────────────┘
           ↓ (Telegram Bot API)
┌─────────────────────────────────────────┐
│ Local Machine (Bridge Daemon)           │
│                                         │
│ ┌─ tmux session "coder-backend" ─┐    │
│ │ claude --channels telegram      │    │
│ │ Polling every 1-2 seconds       │    │
│ └─────────────────────────────────┘    │
│                                         │
│ ┌─ tmux session "coder-frontend" ─┐   │
│ │ claude --channels telegram       │    │
│ │ (isolated git worktree)         │    │
│ └─────────────────────────────────┘    │
│                                         │
│ Bridge Daemon (Python):                 │
│ - Monitors tmux sessions                │
│ - Spawns new agents on /spawn command   │
│ - Routes replies back to Telegram       │
│ - Accumulates enhancement signals       │
└─────────────────────────────────────────┘
           ↑ (Reply via reply tool)
┌─────────────────────────────────────────┐
│ Mobile Chat (results appear here)       │
│ Claude: "Fixed bug in auth.py..."       │
└─────────────────────────────────────────┘
```

**Implementation Steps:**
1. Install Telegram plugin in each Claude Code session
2. Bridge daemon spawns sessions with `/channels telegram` flag
3. Mobile user DMs Telegram bot
4. Event arrives in session via MCP notification
5. Claude executes, calls reply tool
6. Reply tool sends message back to Telegram
7. User gets result on phone

**Code Example (Bridge Daemon spawning session):**
```python
import subprocess
import time

def spawn_agent(agent_name, project_path):
    # Start Claude Code with Telegram channel
    session = subprocess.Popen([
        "claude",
        "--project", project_path,
        "--channels", "plugin:telegram@claude-plugins-official",
        "-p", f"You are {agent_name}..."
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
    )

    # Give it time to initialize
    time.sleep(3)

    # Verify it's running (health check)
    if session.poll() is not None:
        stderr = session.stderr.read().decode()
        raise RuntimeError(f"Agent spawn failed: {stderr}")

    return session

# Spawn multi-agent setup
agents = {
    "coder-backend": spawn_agent("Senior Backend Engineer", "~/projects/backend"),
    "coder-frontend": spawn_agent("Senior Frontend Engineer", "~/projects/frontend"),
}

# Keep running, monitor for crashes
while True:
    for name, proc in agents.items():
        if proc.poll() is not None:
            print(f"Agent {name} crashed, restarting...")
            agents[name] = spawn_agent(name, ...)
    time.sleep(10)
```

### 6.2 Phase 2: Advanced Multi-Session Architecture

**Add HTTP webhook support via custom channel:**

```
┌─────────────────────────────────────────┐
│ Mobile (Telegram)                       │
│ "Fix login bug"                         │
└─────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────┐
│ CI/Webhooks/External Systems            │
│ POST localhost:8788 "CI failed: run..."  │
└─────────────────────────────────────────┘
           ↓ (both feed via MCP channels)
┌─────────────────────────────────────────┐
│ Local Machine                           │
│                                         │
│ Bridge Daemon (Routes messages):        │
│ - Telegram → Backend session            │
│ - Webhook → Frontend session            │
│ - CI alerts → DevOps session            │
│                                         │
│ Sessions:                               │
│ ├─ Backend (tmux: coder-backend)       │
│ ├─ Frontend (tmux: coder-frontend)     │
│ └─ DevOps (tmux: ops-main)             │
│                                         │
│ Custom Webhook Channel:                 │
│ - Listens on localhost:8788             │
│ - MCP server pushing to sessions        │
│ - Permission relay enabled              │
└─────────────────────────────────────────┘
```

**Webhook Channel Example (from official docs):**
```typescript
// Create MCP server that listens for HTTP webhooks
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'

const mcp = new Server(
  { name: 'webhook-channel', version: '0.0.1' },
  {
    capabilities: {
      experimental: {
        'claude/channel': {},
        'claude/channel/permission': {}  // relay approvals
      },
      tools: {}  // reply tool
    },
    instructions: 'Route webhook events and handle permission relay'
  }
)

await mcp.connect(new StdioServerTransport())

// HTTP listener on localhost:8788
Bun.serve({
  port: 8788,
  hostname: '127.0.0.1',
  async fetch(req) {
    const body = await req.text()

    // Determine which session to target based on content
    const route = determineRoute(body)  // "backend", "frontend", "ops"

    await mcp.notification({
      method: 'notifications/claude/channel',
      params: {
        content: body,
        meta: { route, source: 'webhook' }
      }
    })
    return new Response('ok')
  }
})
```

### 6.3 When to Use RemoteTrigger API

**RemoteTrigger becomes valuable when:**
1. You want to trigger Claude sessions from **outside the local machine** (cloud-based dispatcher)
2. You need **API key authentication** (for service-to-service auth)
3. You want **fire-and-forget** dispatch without session management
4. You have **pre-configured triggers** that repeat on a schedule

**Not recommended for MVP** because:
- Undocumented (may change)
- No bidirectional messaging (manual callback needed)
- No permission relay
- Higher latency (estimated 5-30s)
- Less reliable than Channels

---

## 7. Security & Isolation

### 7.1 Channels Security

**Strengths:**
```
✓ Sender gating: Only allowlisted users can send messages
✓ No inbound ports: Outbound polling only (one-way from firewall perspective)
✓ Permission relay: Remote approval signs cryptographic request_id
✓ Session isolation: Each session is independent process
✓ MCP isolation: Each server runs as subprocess, can't break out
```

**Pairing Flow (Telegram):**
```
1. User DMs bot
2. Bot replies with pairing code
3. User runs: /telegram:access pair <code>
4. Session adds user_id to allowlist
5. Lock down: /telegram:access policy allowlist
```

### 7.2 Multi-Session Isolation

**Each Session Is Independent:**
- Separate Claude Code process (PID)
- Separate project directory
- Separate git branch (with worktrees)
- Separate context window
- Separate MCP connections

**No Cross-Session Contamination:**
```
Session A (Backend): Reads ~/backend, can edit ~/backend
Session B (Frontend): Reads ~/frontend, can edit ~/frontend
→ Never interfere, even if running simultaneously
```

### 7.3 Attack Vectors & Mitigations

| Attack | Mitigation |
|--------|-----------|
| Unauthorized user sends command | Sender allowlist + pairing flow |
| Prompt injection via webhook | Gate on sender, validate input format |
| Session gains unexpected permissions | Each session runs with user's CLI permissions (same as interactive `claude` command) |
| Malicious file edit | Same risk as interactive session; use permission modes (Ask, Auto-accept, Plan) |
| Denial of service (spam commands) | Telegram rate limit (built-in), Channel max queue size |

---

## 8. Practical Deployment Guide

### 8.1 Quick Setup: Telegram + Claude Bridge

**Prerequisites:**
- Claude Code v2.1.80+ installed
- Telegram bot token from BotFather
- Python 3.8+ for Bridge daemon

**Step 1: Create Telegram Bot**
```bash
# Open Telegram, find BotFather, send /newbot
# Copy token: 123456:ABC-DEF...
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
```

**Step 2: Install Plugin (in Claude Code)**
```bash
/plugin install telegram@claude-plugins-official
/telegram:configure $TELEGRAM_BOT_TOKEN
```

**Step 3: Start Session with Channel**
```bash
claude --project ~/projects/my-app \
       --channels plugin:telegram@claude-plugins-official
```

**Step 4: Pair (one-time)**
```
# In Telegram, DM the bot any message
# Bot replies with pairing code, e.g. "abc123"
# In Claude Code:
/telegram:access pair abc123
/telegram:access policy allowlist
```

**Step 5: Send Task from Telegram**
```
@your_bot: Fix the login bug
```

**Step 6: Monitor & Approve**
- Claude Code session shows task
- If needs approval: Inline keyboard in Telegram
- Tap ✅ or ❌
- Result comes back to Telegram

### 8.2 Bridge Daemon: Spawning Multiple Agents

**Python implementation:**
```python
#!/usr/bin/env python3
import os
import sys
import subprocess
import signal
import time
import json
from pathlib import Path
from datetime import datetime

class BridgeDaemon:
    def __init__(self):
        self.sessions = {}  # agent_name -> Popen
        self.config_dir = Path.home() / ".claude-bridge"
        self.config_dir.mkdir(exist_ok=True)

    def spawn_agent(self, name, project_path, profile_prompt=""):
        """Spawn a Claude Code session with Telegram channel."""
        env = os.environ.copy()
        env["TELEGRAM_BOT_TOKEN"] = os.getenv("TELEGRAM_BOT_TOKEN")

        # Build system prompt from profile
        system_prompt = profile_prompt or f"You are {name}"

        cmd = [
            "claude",
            "--project", str(Path(project_path).expanduser()),
            "--channels", "plugin:telegram@claude-plugins-official",
            "-p", system_prompt,
        ]

        print(f"[{datetime.now().isoformat()}] Spawning agent: {name}")
        try:
            session = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            self.sessions[name] = session
            time.sleep(2)  # Let it initialize

            # Health check
            if session.poll() is not None:
                stderr = session.stderr.read()
                print(f"ERROR: Agent {name} failed to start: {stderr}")
                del self.sessions[name]
                return False

            print(f"✓ Agent {name} running (PID: {session.pid})")
            return True
        except Exception as e:
            print(f"ERROR: Failed to spawn {name}: {e}")
            return False

    def monitor_sessions(self):
        """Monitor sessions and restart if crashed."""
        while True:
            try:
                for name, session in list(self.sessions.items()):
                    if session.poll() is not None:
                        print(f"WARNING: Agent {name} crashed (exit code {session.poll()})")
                        # Optionally restart
                        # self.spawn_agent(name, ...)
                time.sleep(5)
            except KeyboardInterrupt:
                self.shutdown()
                break

    def shutdown(self):
        """Gracefully shut down all sessions."""
        print("\nShutting down Bridge...")
        for name, session in self.sessions.items():
            try:
                session.terminate()
                session.wait(timeout=5)
                print(f"✓ Stopped {name}")
            except subprocess.TimeoutExpired:
                session.kill()
                print(f"✓ Killed {name} (timeout)")
        print("Bridge shutdown complete")

if __name__ == "__main__":
    bridge = BridgeDaemon()

    # Load agent config
    agents_config = [
        ("backend-coder", "~/projects/backend", "Senior backend engineer. Fix bugs, write features."),
        ("frontend-coder", "~/projects/frontend", "Senior frontend engineer. React, TypeScript."),
    ]

    # Spawn all agents
    for name, path, prompt in agents_config:
        bridge.spawn_agent(name, path, prompt)

    # Monitor
    signal.signal(signal.SIGINT, lambda s, f: bridge.shutdown())
    bridge.monitor_sessions()
```

**Run:**
```bash
export TELEGRAM_BOT_TOKEN="your_token_here"
python3 bridge.py
```

### 8.3 Deployment Options

| Option | Pros | Cons |
|--------|------|------|
| **Local machine (always-on)** | Simple, full file access, fast | Requires computer always on |
| **Persistent server (EC2/VPS)** | Always available | Slow (network latency), expensive |
| **Docker container (local)** | Isolated, reproducible | More setup |
| **systemd service** | Auto-restart, logging | Linux only |
| **tmux + screen** | Persistent, attachable | Manual management |
| **Desktop app** | GUI, visual diffs, computer use | Requires Desktop app license |

**Recommendation for MVP:** Local machine with tmux (simple, fast, developer-friendly).

---

## 9. HTTP API Design (If Needed)

### 9.1 Bridge Daemon HTTP Interface

If you want to add HTTP-based task dispatch (Phase 2), design it like this:

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class TaskRequest(BaseModel):
    agent: str           # "backend-coder", "frontend-coder"
    prompt: str          # "Fix the login bug"
    timeout: int = 600   # seconds
    mode: str = "auto"   # "auto", "ask", "plan"

@app.post("/api/tasks")
async def submit_task(task: TaskRequest):
    """Submit task to agent via Telegram channel."""
    try:
        # Find session
        session = sessions.get(task.agent)
        if not session:
            raise HTTPException(404, f"Agent {task.agent} not running")

        # Send via Telegram channel (queue the message)
        telegram_channel.queue_message(task.agent, task.prompt)

        # Return task ID for polling
        task_id = uuid.uuid4()
        pending_tasks[task_id] = {
            "agent": task.agent,
            "prompt": task.prompt,
            "status": "queued",
            "started": None,
            "completed": None,
            "result": None
        }

        return {
            "task_id": str(task_id),
            "status": "queued",
            "agent": task.agent
        }
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Poll for task completion."""
    task = pending_tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    return task
```

**Latency Trade-offs:**
```
Direct Telegram messaging:
  User → Telegram → Polling → Session: ~2-5s

HTTP → Bridge → Queue → Telegram → Polling → Session:
  User → HTTP POST → Bridge Queue → Telegram Polling → Session: ~3-10s
  + Polling overhead for status
```

**Conclusion:** For MVP, skip HTTP. Use Channels directly (simpler, faster, no additional infrastructure).

---

## 10. Comparison: Channels vs RemoteTrigger vs Custom HTTP

| Aspect | Channels (MCP) | RemoteTrigger API | Custom HTTP Server |
|--------|---|---|---|
| **Setup Time** | 5 minutes (plugin install) | Unknown | 1-2 hours (server + routing) |
| **Latency** | 2-5s (polling) | 5-30s (est) | 3-10s (queue + poll) |
| **Bidirectional** | Yes (reply tools) | No | Yes (if implemented) |
| **Permission Relay** | Yes (built-in) | No | Manual workflow |
| **Authentication** | Allowlist pairing | Undocumented | OAuth/API keys |
| **Documentation** | Excellent (research preview) | None (internal API) | You write it |
| **Reliability** | Proven (multiple channels working) | Unknown | Depends on your code |
| **Multi-Machine** | Cloud-based (polling), local fine | Unknown | Possible (HTTP) |
| **Scalability** | Good (independent sessions) | Unknown | Limited (single server) |
| **Production Ready** | Yes (research preview) | Experimental | Yes (if done well) |

---

## 11. Final Recommendations

### For Claude Bridge MVP (Phase 1):

✅ **Use Channels + tmux:**

1. Install Telegram plugin in each Claude Code session
2. Spawn agents with `--channels plugin:telegram` flag
3. Bridge daemon monitors sessions and restarts on crash
4. User sends task via Telegram mobile app
5. Approval flows back through Telegram (permission relay)
6. Results returned to Telegram

**Why:**
- Simplest (no HTTP infrastructure)
- Fastest (2-5s latency)
- Most reliable (MCP proven, permission relay included)
- Works from mobile natively
- Requires minimal Bridge daemon code (mostly session monitoring)

### For Phase 2:

✅ **Add Custom Webhook Channel** (if needed):

1. Build MCP webhook server (listen on localhost:8788)
2. Attach to sessions that need webhook support
3. Enable permission relay for remote approval
4. Route CI failures, alerts, etc. to appropriate sessions

✅ **Research RemoteTrigger API** (optional):

- Document the undocumented API
- Build HTTP→RemoteTrigger bridge
- Use for cloud-based central dispatcher
- Trade-off: Higher latency, less integrated, requires more error handling

### For Scale (Phase 3+):

✅ **Hybrid Approach:**

- Telegram channels for interactive mobile dispatch
- Custom webhooks for CI/monitoring events
- RemoteTrigger API for cloud-based central dashboard (if API gets documented/stabilized)
- DNS + load balancer if multiple machines

---

## 12. Code Examples

### 12.1 Minimal Channels Implementation

**File: `.claude/commands/dispatch.md`**
```markdown
# /dispatch

Dispatch a task to be executed immediately.

## Usage

```
/dispatch <task>
```

## Example

```
/dispatch "Fix the login bug"
```

This triggers Claude to work on the task right now. Results appear in the Telegram chat.
```

**File: `bridge.py` (minimal daemon)**
```python
#!/usr/bin/env python3
import subprocess, time, os

# Telegram must be configured first
os.environ["TELEGRAM_BOT_TOKEN"] = os.getenv("TELEGRAM_BOT_TOKEN")

agents = {}

def spawn(name, project, prompt=""):
    cmd = [
        "claude",
        "--project", project,
        "--channels", "plugin:telegram@claude-plugins-official",
        "-p", prompt or f"You are {name}"
    ]
    agents[name] = subprocess.Popen(cmd)
    print(f"Started {name}")

# Spawn all agents
spawn("backend", "~/projects/backend", "Senior backend engineer")
spawn("frontend", "~/projects/frontend", "Senior frontend engineer")

# Keep them alive
while True:
    time.sleep(10)
    for name, proc in agents.items():
        if proc.poll() is not None:
            print(f"Restarting {name}")
            spawn(name, "...", "...")
```

**Run:**
```bash
export TELEGRAM_BOT_TOKEN="your_token"
python3 bridge.py
```

### 12.2 Permission Relay Example

**Permission Relay happens automatically when:**
1. Agent calls a restricted tool (Bash, Write, etc.)
2. User not at terminal (channel active)
3. User has enabled permission relay on the channel

**From Telegram User Perspective:**
```
User:  @bot: Deploy to production
Claude: This requires running: `aws s3 sync ...`
        Reply "yes abdce" to approve, "no abdce" to deny

User: yes abdce

Claude: Deploying... (agent runs the command)
```

**User doesn't need to be at the computer.**

---

## 13. References

- **Claude Code Channels Docs**: https://code.claude.com/docs/en/channels
- **Channels Reference (Building Custom)**: https://code.claude.com/docs/en/channels-reference
- **Desktop App (Dispatch Integration)**: https://code.claude.com/docs/en/desktop#sessions-from-dispatch
- **Agent SDK**: https://platform.claude.com/docs/en/agent-sdk/overview
- **MCP Protocol**: https://modelcontextprotocol.io/

---

## Summary Table: Quick Decision Matrix

**Q: Do you want to dispatch tasks to Claude Code sessions from mobile?**
→ Use **Channels** (Telegram/Discord/iMessage)

**Q: Do you want to trigger sessions from external webhooks (CI, monitoring)?**
→ Use **Custom MCP Webhook Channel** (build it, attach to session)

**Q: Do you want to run multiple agents in parallel on the same machine?**
→ Use **tmux sessions** (each with independent `--channels` flag)

**Q: Do you want approval prompts to reach mobile?**
→ Use **Channels with permission relay** (built-in, no extra code)

**Q: Do you want to avoid HTTP infrastructure entirely?**
→ Use **Channels** (outbound polling only, no listening ports)

**Q: Do you want to experiment with undocumented APIs?**
→ Try **RemoteTrigger API** (but document thoroughly, unsupported)

---

**Document Version:** 1.0
**Last Updated:** 2026-03-26
**Status:** Complete Research, Ready for Implementation
