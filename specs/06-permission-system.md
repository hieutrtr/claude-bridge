# Permission & Relay System Specification

## Overview

Permission system controls what agent can do. When agent tries forbidden action, Bridge intercepts and asks user for approval via Telegram.

**Key principle:** Safe by default. Dangerous actions require explicit permission.

---

## 1. Permission Model

### 1.1 Permissions

```yaml
permissions:
  allow_bash: boolean               # Can run shell commands? (default: true)
  allow_write: boolean              # Can write files? (default: true)
  allow_network: boolean            # Can make HTTP requests? (default: true)

  restrictions:                     # Specific restrictions
    bash_blocklist:
      - "rm -rf"
      - "git push --force"
      - "git push origin main"
      - "dd if=/dev/zero"
      - ": > /etc/passwd"           # Destructive commands

    paths_require_confirmation:
      - path: "src/payments/**"
        reason: "Sensitive payment logic"
      - path: ".env"
        reason: "Credentials"
      - path: "package.json"
        reason: "Dependencies"

    tools_restricted:
      - "execute_shell_command"
      - "delete_directory"
```

### 1.2 Permission Request

```python
@dataclass
class PermissionRequest:
    id: str                           # UUID
    agent_name: str
    action_type: str                  # bash | write | network
    action_detail: str                # "rm -rf /", "write /payments/webhook.ts"
    risk_level: str                   # critical | high | medium | low
    reason: str                       # Why blocked
    file_preview: str                 # If write action (show what file)
    confirmation_text: str            # What user needs to confirm

    timestamp: datetime
    timeout_seconds: int              # When does approval expire?
    created_at: datetime

    # Response
    approved: bool | None
    approved_at: datetime | None
    approved_by: str                  # user ID from Telegram
```

---

## 2. Hook Integration

Hooks intercept tool calls and request permission:

### 2.1 Hook Flow

```
Agent runs bash command
  ↓
PreToolUse[bash] hook fires
  ↓
Check if matches blocklist
  ├─ YES: Create PermissionRequest
  │        ↓
  │   Send to Telegram
  │        ↓
  │   Wait for user response
  │        ↓
  │   Exit code 0 (allow) or 2 (deny)
  │        ↓
  │   Agent continues or stops
  │
  └─ NO: Pass through (no approval needed)
```

### 2.2 Hook Script (Python)

```python
# ~/.claude-bridge/agents/{agent-name}/hooks/pre_bash_check.py

import sys
import json
from permission_relay import PermissionHandler

def main():
    # Claude Code passes action details via stdin
    action = json.load(sys.stdin)

    # action = {
    #   "type": "bash",
    #   "command": "rm -rf node_modules"
    # }

    handler = PermissionHandler()

    # Check if blocked
    if is_blocked(action):
        # Request permission from user
        req = handler.request(
            action_type="bash",
            action_detail=action["command"],
            risk_level="critical",
            reason="Destructive command"
        )

        if req.approved:
            sys.exit(0)  # Allow
        else:
            sys.exit(2)  # Deny
    else:
        sys.exit(0)  # Allow (not blocked)

def is_blocked(action):
    blocklist = [
        "rm -rf",
        "git push --force",
        "git push origin main",
    ]
    return any(pattern in action["command"] for pattern in blocklist)
```

---

## 3. Permission Handler

### 3.1 Handler Class

```python
class PermissionHandler:
    """Handle permission requests via Telegram."""

    def request(action_type: str,
                action_detail: str,
                risk_level: str = "medium",
                reason: str = None,
                file_preview: str = None,
                timeout_seconds: int = 300) -> PermissionRequest:
        """
        Request permission from user via Telegram.

        Args:
            action_type: bash | write | network
            action_detail: What's being done
            risk_level: critical | high | medium | low
            reason: Why blocked
            file_preview: Content preview (for writes)
            timeout_seconds: When to default to deny

        Returns:
            PermissionRequest (with approved = True/False)

        Process:
            1. Create PermissionRequest
            2. Send to Telegram with inline buttons
            3. Wait for user response (up to timeout)
            4. Return request with approved/rejected

        If timeout:
            - Default to DENY (safe)
            - Log timeout
            - Notify user
        """
        pass

    def send_telegram_message(req: PermissionRequest) -> bool:
        """
        Send formatted permission request to Telegram.

        Format:
        ```
        ⚠️ Agent requested permission

        Action: {{ action_detail }}
        Risk: {{ risk_level }}
        Reason: {{ reason }}

        [✅ Approve] [❌ Deny] [👁️ Preview]
        ```
        """
        pass

    def handle_callback(callback_id: str,
                       button_pressed: str) -> None:
        """
        Handle button tap from Telegram.

        Args:
            button_pressed: "approve" | "deny" | "preview"

        Process:
            1. Look up PermissionRequest by ID
            2. Update request.approved
            3. Return to waiting hook via return code
            4. Log decision
        """
        pass

    def wait_for_response(req_id: str,
                         timeout: int) -> PermissionRequest:
        """
        Wait for user to respond to permission request.

        Process:
            1. Start timer
            2. Poll for response (blocking)
            3. If response: return updated request
            4. If timeout: set approved=False, return

        Returns:
            PermissionRequest with approved status
        """
        pass

    def get_risk_level(action_type: str,
                      action_detail: str) -> str:
        """
        Auto-determine risk level based on action.

        Risk levels:
        - critical: rm -rf, dd, format disk
        - high: git push --force, drop database
        - medium: git push, delete file
        - low: read file, run test

        Returns: critical | high | medium | low
        """
        pass
```

### 3.2 Response Storage

Requests stored in:
```
~/.claude-bridge/agents/{agent-name}/
├── permission-requests.yaml       # Current pending requests
├── permission-history.yaml        # Past approvals/denials
```

---

## 4. Hook Integration Points

### 4.1 Pre-Tool Hooks

```python
# In profile.yaml hooks section:
hooks:
  pre_tool_use:
    bash:
      - relay_permission: "rm -rf"
        reason: "Destructive command"
      - relay_permission: "git push --force"
        reason: "Force push risk"
      - relay_permission: "git push origin main"
        reason: "Should use PR"
      - relay_permission: "prisma migrate"
        reason: "Database change"

    write:
      - relay_permission: ".env*"
        reason: "Credentials file"
      - relay_permission: "src/payments/**"
        reason: "Sensitive area"
      - relay_permission: "package.json"
        reason: "Dependencies change"

    browser:
      - relay_permission: "POST https://api.external.com/**"
        reason: "External API call"
```

### 4.2 Inline Keyboard UI

```
⚠️ Agent needs approval

Command: git push --force origin feature-branch
Reason: Force push is risky
Risk: high

[✅ Approve]  [❌ Deny]  [👁️ See commit]
```

When user taps "See commit":
```
Last commit:
- fix: resolve merge conflicts in auth module
- Files: 3 changed, 12 insertions

Still want to allow? [✅ Yes] [❌ No]
```

---

## 5. Audit & Logging

### 5.1 Permission History

```yaml
# ~/.claude-bridge/agents/{agent-name}/permission-history.yaml

approvals:
  - id: perm_abc123
    timestamp: 2026-03-26T10:15:00
    action: "bash: git push"
    approved_by: "user"
    result: "success"

  - id: perm_def456
    timestamp: 2026-03-26T10:20:00
    action: "write: src/payments/webhook.ts"
    approved_by: "user"
    result: "success"

denials:
  - id: perm_ghi789
    timestamp: 2026-03-26T10:25:00
    action: "bash: rm -rf /"
    denied_by: "user"
    reason: "user_rejected"

  - id: perm_jkl012
    timestamp: 2026-03-26T10:30:00
    action: "bash: sudo reboot"
    denied_by: "timeout"
    reason: "user_no_response"
```

### 5.2 Audit Commands

```bash
# Show permission history
claude-bridge permission-history coder-my-app

# Show pending requests
claude-bridge permission-pending coder-my-app

# Approve/deny pending request
claude-bridge permission-approve <request-id>
claude-bridge permission-deny <request-id>
```

---

## 6. Error Handling

| Error | Recovery |
|---|---|
| Permission request fails | Default to DENY (safe) |
| Telegram unreachable | Queue request, retry on next check |
| User doesn't respond | Default to DENY after timeout |
| Invalid hook response | Log error, allow (assume user approved manually) |
| Database corruption | Restore from backup |

---

## 7. Testing

### 7.1 Unit Tests
- Risk level detection
- Request creation/storage
- Timeout handling
- Hook integration

### 7.2 Integration Tests
- Agent tries blocked action → permission requested → user approves → action allowed
- Timeout expires → default to deny → action blocked
- Multiple simultaneous requests → all queued correctly

---

## 8. Success Criteria

Permission system complete when:

- [x] Blocklist enforced
- [x] Permission requests sent to Telegram
- [x] User can approve/deny via buttons
- [x] Timeout defaults to DENY
- [x] Risk levels determined correctly
- [x] History logged
- [x] Hooks properly integrated
- [x] No approval leaks (can't bypass)

