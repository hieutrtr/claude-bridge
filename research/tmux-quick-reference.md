# Tmux Quick Reference for Claude Bridge

## Session Lifecycle

```bash
# Create detached session
tmux new-session -d -s SESSION_NAME -c /working/dir

# Kill session
tmux kill-session -t SESSION_NAME

# Check exists
tmux has-session -t SESSION_NAME && echo "exists"

# List all
tmux list-sessions
```

## Sending Commands

```bash
# Send command with Enter
tmux send-keys -t SESSION:WINDOW.PANE "command arg1 arg2" Enter

# Send raw keys (Ctrl+C, arrows, etc.)
tmux send-keys -t SESSION:WINDOW.PANE "C-c"
```

## Capturing Output

```bash
# Capture visible + scrollback (last N lines)
tmux capture-pane -t SESSION:WINDOW.PANE -p -S -300

# Capture to file
tmux capture-pane -t SESSION:WINDOW.PANE -p > output.txt

# Get pane dimensions
tmux display-message -t SESSION:WINDOW.PANE -p "#{pane_width}x#{pane_height}"
```

## Python Wrapper Functions

```python
import subprocess
import re

def send_command(session: str, window: int, pane: int, cmd: str) -> bool:
    """Send command to pane."""
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{session}:{window}.{pane}", cmd, "Enter"],
            check=True, capture_output=True
        )
        return True
    except subprocess.CalledProcessError:
        return False

def capture_output(session: str, window: int, pane: int, lines: int = 300) -> str:
    """Capture pane output."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", f"{session}:{window}.{pane}", "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, check=True
        )
        # Strip ANSI codes
        return re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', result.stdout).strip()
    except subprocess.CalledProcessError:
        return ""

def is_alive(session: str) -> bool:
    """Check if session exists."""
    return subprocess.run(
        ["tmux", "has-session", "-t", session], capture_output=True
    ).returncode == 0

def kill_session(session: str):
    """Kill session."""
    subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)
```

## Target Format

All commands use the target format: `session:window.pane`

- `session`: Session name (e.g., `claude-bridge-coder-my-app`)
- `window`: Window index (0, 1, 2, ...)
- `pane`: Pane index within window (usually 0)

Example: `claude-bridge-coder-my-app:0.0`

## Key Design Decisions

| Aspect | Solution |
|--------|----------|
| **Persistence** | One tmux session per agent, survives network interruption |
| **Interleaving** | TaskRouter with per-agent queue + asyncio Lock |
| **Output capture** | `capture-pane -p -S -N` for last N lines |
| **ANSI codes** | `re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', output)` |
| **Task completion** | Poll for prompt regex: `>>> $` or `$ $` |
| **Timeout** | `asyncio.wait_for()` + `send-keys C-c` |
| **User visibility** | User can `tmux attach -t session-name` anytime |

## Advantages

✅ Sessions persist across SSH disconnects
✅ No startup overhead for subsequent tasks
✅ User can manually debug via tmux attach
✅ Built-in scrollback history
✅ Proven in production systems

## Complexity Points

⚠️ Must parse pane buffer + strip escape codes
⚠️ Output capture not real-time (polling interval)
⚠️ Detecting task completion requires prompt regex
⚠️ Session cleanup must be explicit or use timeout

## Minimal Working Example

```python
import time
import subprocess

# Create session
subprocess.run(["tmux", "new-session", "-d", "-s", "my-agent", "-c", "/home/user/projects/my-app"])

# Send command
subprocess.run(["tmux", "send-keys", "-t", "my-agent:0.0", "echo hello", "Enter"])

# Wait a moment
time.sleep(1)

# Capture output
result = subprocess.run(
    ["tmux", "capture-pane", "-t", "my-agent:0.0", "-p", "-S", "-50"],
    capture_output=True, text=True
)
print(result.stdout)

# Kill session
subprocess.run(["tmux", "kill-session", "-t", "my-agent"])
```

## Common Tasks

```python
# Create agent with Claude Code
subprocess.run([
    "tmux", "new-session", "-d", "-s", "coder-my-app",
    "-c", "/path/to/project",
    "claude --project /path/to/project --print"
])

# Send task
send_command("coder-my-app", 0, 0, "Fix the login bug")

# Wait for completion (simple polling)
for _ in range(300):  # 5-minute timeout
    output = capture_output("coder-my-app", 0, 0)
    if ">>> " in output or "$ " in output:  # Prompt found
        break
    time.sleep(1)

# Get results
final_output = capture_output("coder-my-app", 0, 0, lines=500)
print(final_output)

# Cleanup
kill_session("coder-my-app")
```

---

For detailed research, implementation patterns, and trade-offs, see **`tmux-session-management-research.md`**.
