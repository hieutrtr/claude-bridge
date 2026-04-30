# Claude Bridge Phase 1: Implementation Guide

**Status:** Ready for Development
**Target Timeline:** 2-3 weeks (full-time) or 6-8 weeks (part-time)
**Architecture:** Channels (MCP) + tmux + Python daemon

---

## Quick Start (5 Steps)

### 1. Create Telegram Bot

```bash
# Open Telegram, find @BotFather
/newbot
# Name: Claude Backend  (or your choice)
# Username: claude_backend_bot (must end with _bot)
# Copy token: 123456:ABC-DEF1234ghIkl...

export TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl..."
```

### 2. Install Claude Code (if not already)

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude --version  # Should be v2.1.80+
```

### 3. Install Telegram Plugin

```bash
claude  # Start any session
/plugin install telegram@claude-plugins-official
/reload-plugins
exit
```

### 4. Configure Token

```bash
# Set environment variable (temporary)
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."

# Or permanent (add to ~/.zshrc or ~/.bashrc)
echo 'export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."' >> ~/.zshrc
```

### 5. Run Bridge Daemon

```bash
cd /Users/hieutran/projects/claude-bridge
python3 -m claude_bridge.daemon
```

---

## Minimal Bridge Daemon (Phase 1)

**File: `claude_bridge/daemon/__init__.py`**
```python
"""Bridge daemon: spawns and monitors Claude Code agents."""
```

**File: `claude_bridge/daemon/agent_manager.py`**
```python
import subprocess
import time
import os
from pathlib import Path
from datetime import datetime


class AgentManager:
    """Manage agent lifecycles."""

    def __init__(self):
        self.sessions = {}  # agent_name -> Popen

    def spawn_agent(self, agent_name, project_path, profile_prompt=""):
        """Spawn a Claude Code session with Telegram channel.

        Args:
            agent_name: Name of agent (e.g. "coder-backend")
            project_path: Path to project directory
            profile_prompt: System prompt / role description

        Returns:
            True if spawned successfully, False otherwise
        """
        env = os.environ.copy()
        # Ensure token is set
        if "TELEGRAM_BOT_TOKEN" not in env:
            print("ERROR: TELEGRAM_BOT_TOKEN not set")
            return False

        system_prompt = profile_prompt or f"You are {agent_name}"

        cmd = [
            "claude",
            "--project", str(Path(project_path).expanduser().resolve()),
            "--channels", "plugin:telegram@claude-plugins-official",
            "-p", system_prompt,
        ]

        print(f"[{datetime.now().isoformat()}] Spawning agent: {agent_name}")
        print(f"  Project: {project_path}")
        print(f"  Command: {' '.join(cmd)}")

        try:
            session = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            # Give it time to initialize
            time.sleep(2)

            # Health check: did it crash immediately?
            if session.poll() is not None:
                exit_code = session.returncode
                stderr = session.stderr.read() if session.stderr else "unknown error"
                print(f"ERROR: Agent {agent_name} failed (exit code {exit_code})")
                print(f"  Stderr: {stderr[:200]}")
                return False

            self.sessions[agent_name] = session
            print(f"✓ Agent {agent_name} running (PID: {session.pid})")
            return True

        except Exception as e:
            print(f"ERROR: Failed to spawn {agent_name}: {e}")
            return False

    def monitor_sessions(self):
        """Monitor all sessions and log failures."""
        print("\nMonitoring sessions... (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(5)
                for name, session in list(self.sessions.items()):
                    returncode = session.poll()
                    if returncode is not None:
                        stderr = session.stderr.read() if session.stderr else ""
                        print(f"\n[{datetime.now().isoformat()}] Agent {name} crashed (exit code {returncode})")
                        if stderr:
                            print(f"  Last stderr:\n{stderr[:500]}")
                        # Optional: restart
                        # self.spawn_agent(name, ...)
                        del self.sessions[name]
        except KeyboardInterrupt:
            self.shutdown()

    def shutdown(self):
        """Gracefully shut down all sessions."""
        print("\n\nShutting down Bridge daemon...")
        for name, session in self.sessions.items():
            try:
                print(f"  Stopping {name}...")
                session.terminate()
                session.wait(timeout=5)
                print(f"  ✓ Stopped {name}")
            except subprocess.TimeoutExpired:
                session.kill()
                print(f"  ✓ Killed {name} (timeout)")
        print("Bridge shutdown complete")


def main():
    """Main entry point for Bridge daemon."""
    manager = AgentManager()

    # Load configuration from file or hardcode for MVP
    agents_config = [
        {
            "name": "coder-backend",
            "project": "~/projects/my-app",
            "prompt": "You are a senior backend engineer. Fix bugs, write features, run tests.",
        },
        {
            "name": "coder-frontend",
            "project": "~/projects/my-app",
            "prompt": "You are a senior frontend engineer. React, TypeScript, responsive design.",
        },
    ]

    # Spawn all agents
    print("Claude Bridge Daemon Starting")
    print("=" * 50)
    for config in agents_config:
        manager.spawn_agent(
            agent_name=config["name"],
            project_path=config["project"],
            profile_prompt=config["prompt"],
        )

    # Monitor
    manager.monitor_sessions()


if __name__ == "__main__":
    main()
```

**File: `claude_bridge/daemon/__main__.py`**
```python
from claude_bridge.daemon.agent_manager import main

if __name__ == "__main__":
    main()
```

**Run:**
```bash
export TELEGRAM_BOT_TOKEN="your_token_here"
python3 -m claude_bridge.daemon
```

---

## Manual Testing Checklist

### Before Running Daemon:

- [ ] Claude Code installed (`claude --version` shows v2.1.80+)
- [ ] Telegram plugin installed (`/plugin list` shows `telegram`)
- [ ] Bot token created (@BotFather)
- [ ] Token in environment (`echo $TELEGRAM_BOT_TOKEN`)

### Start Bridge Daemon:

```bash
python3 -m claude_bridge.daemon
```

**Expected Output:**
```
Claude Bridge Daemon Starting
==================================================
[2026-03-26T10:15:00] Spawning agent: coder-backend
  Project: /Users/hieutran/projects/my-app
  Command: claude --project ... --channels plugin:telegram ...
✓ Agent coder-backend running (PID: 12345)

[2026-03-26T10:15:03] Spawning agent: coder-frontend
  Project: /Users/hieutran/projects/my-app
  Command: claude --project ... --channels plugin:telegram ...
✓ Agent coder-frontend running (PID: 12346)

Monitoring sessions... (Ctrl+C to stop)
```

### Test from Telegram:

1. Open Telegram on phone
2. Find your bot (@claude_backend_bot or whatever username you chose)
3. Send: `"Hello"`
4. Bot should reply with a **pairing code**

**Expected:**
```
Pairing code: abc123
To allow me to receive messages, run this in Claude Code:
/telegram:access pair abc123
```

5. In Claude Code session (terminal), run:
```
/telegram:access pair abc123
/telegram:access policy allowlist
```

6. Send again from Telegram:
```
"What files are in this directory?"
```

7. Claude should respond in Telegram chat with the answer

### Approval Flow Test:

1. Send from Telegram:
```
"Run: npm test"
```

2. Claude Code will ask for permission:
```
<channel source="telegram" chat_id="123">
Run: npm test
</channel>

Claude: "I'll run npm test for you. First, I need your approval."
[Telegram shows inline buttons: ✅ Approve | ❌ Deny]
```

3. Tap ✅ in Telegram

4. Claude runs the command and sends result back

---

## Architecture Diagram (Phase 1)

```
┌─────────────────────────────────────────────────────────────┐
│                  Your Local Machine                         │
│                                                             │
│  Bridge Daemon (Python)                                    │
│  ├─ AgentManager                                           │
│  │  └─ spawn_agent("coder-backend", "~/projects/my-app")  │
│  │  └─ spawn_agent("coder-frontend", "~/projects/my-app") │
│  │  └─ monitor_sessions() [running...]                    │
│  │                                                          │
│  ├─ Claude Code (Process 1)                               │
│  │  ├─ Project: ~/projects/my-app                         │
│  │  ├─ Telegram Plugin (polling every 2s)                 │
│  │  └─ System Prompt: "You are a backend engineer..."     │
│  │                                                          │
│  └─ Claude Code (Process 2)                               │
│     ├─ Project: ~/projects/my-app                         │
│     ├─ Telegram Plugin (polling every 2s)                 │
│     └─ System Prompt: "You are a frontend engineer..."    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
            ↕ Telegram Bot API (outbound polling)
┌─────────────────────────────────────────────────────────────┐
│                    Telegram (Cloud)                         │
│                                                             │
│  Bot: @claude_backend_bot                                  │
│  User: (on phone)                                          │
│  DMs: "Fix the login bug" → Message #1                     │
│  DMs: "Approve" (permission prompt) → Verdict              │
└─────────────────────────────────────────────────────────────┘
```

---

## Deployment Checklist

### Development (Single Machine)

- [ ] Telegram bot created
- [ ] Token in environment
- [ ] Claude Code v2.1.80+ installed
- [ ] Telegram plugin installed
- [ ] Bridge daemon code written
- [ ] Manual testing passed
- [ ] Pairing successful
- [ ] Permission relay working

### Production (Always-On Server)

- [ ] Run as systemd service or tmux session
- [ ] Monitor crashes with healthcheck endpoint (Phase 2)
- [ ] Log to file for debugging
- [ ] Setup backup tokens (Phase 2)
- [ ] Rate limiting on Telegram (handled by Telegram)

---

## Phase 2 Enhancements (After MVP Works)

### Priority 1: Persistence & Monitoring

- [ ] Add HTTP healthcheck endpoint
- [ ] Add restart logic (auto-restart crashed agents)
- [ ] Add systemd service file
- [ ] Add logging to `~/.claude-bridge/logs/`

### Priority 2: Configuration

- [ ] Load agents from `YAML` config file
- [ ] Support multiple profiles per agent
- [ ] Add `/spawn` command via Telegram to create agents dynamically

### Priority 3: Enhancement Accumulation

- [ ] Track signals during execution (file changes, corrections, etc.)
- [ ] Accumulate signals in `enhancement-accumulator.yaml`
- [ ] Trigger enhancement proposals at thresholds

### Priority 4: Advanced Features

- [ ] Custom webhook channel (localhost:8788)
- [ ] Permission relay handling
- [ ] Multi-project support
- [ ] Discord/Slack channels

---

## File Structure (Phase 1 Complete)

```
claude-bridge/
├── claude_bridge/
│   ├── __init__.py
│   └── daemon/
│       ├── __init__.py
│       ├── __main__.py
│       └── agent_manager.py
├── REMOTE_TRIGGER_RESEARCH.md      ← You are here
├── IMPLEMENTATION_GUIDE.md          ← This file
├── setup.py                         ← Optional: for pip install
└── README.md
```

---

## Success Criteria (Phase 1 MVP)

- [x] Channels documentation reviewed
- [ ] Telegram bot created and tested
- [ ] Bridge daemon spawns agents with Telegram channel
- [ ] Manual Telegram message delivery working
- [ ] Permission relay working (user can approve from phone)
- [ ] Multiple agents running in parallel
- [ ] Agent crashes detected and logged
- [ ] No file corruption or git conflicts between agents

---

## Quick Reference: Common Commands

```bash
# Start bridge
export TELEGRAM_BOT_TOKEN="..."
python3 -m claude_bridge.daemon

# Stop bridge (Ctrl+C)

# Check token
echo $TELEGRAM_BOT_TOKEN

# Check Claude Code version
claude --version

# Check if plugin installed
# (In Claude Code:)
/plugin list

# Pair Telegram (in Claude Code session:)
/telegram:access pair <code>

# Lock down access (only you)
/telegram:access policy allowlist

# View current access policy
/telegram:access policy
```

---

## Troubleshooting

### "Plugin not found" Error

**Solution:** Update marketplace
```bash
claude
/plugin marketplace update claude-plugins-official
/plugin install telegram@claude-plugins-official
/reload-plugins
exit
```

### "TELEGRAM_BOT_TOKEN not set" Error

**Solution:** Set environment variable
```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
python3 -m claude_bridge.daemon
```

### Agent spawns but doesn't receive messages

**Check:**
1. Is Claude Code actually running? (in another terminal, try `pgrep claude`)
2. Is the Telegram channel plugin listening? (should show in `/mcp` status)
3. Have you paired with Telegram? (/telegram:access pair ...)
4. Is token valid? (try running `claude` manually with `--channels` flag)

### Permission prompts not relaying to Telegram

**Note:** This is automatic once you enable `--channels`. If it's not working:
1. Upgrade Claude Code to v2.1.81+ (permission relay added in .81)
2. Check that you're using `plugin:telegram@claude-plugins-official` (includes relay)
3. Verify allowlist is set (only you can approve/deny)

---

## Next Steps

1. **Create Telegram bot** (5 minutes)
2. **Install plugin** (5 minutes)
3. **Run bridge daemon** (1 minute)
4. **Test from Telegram** (5 minutes)
5. **Celebrate MVP complete!** 🎉

**Estimated total time:** ~30-60 minutes for first test.

---

## Support

- **Claude Code Docs:** https://code.claude.com/docs/en/channels
- **Telegram Plugin:** https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins/telegram
- **Claude Bridge Vision:** See DESIGN.md in this repo

---

**Document Version:** 1.0
**Status:** Ready for Development
**Last Updated:** 2026-03-26
