# Error Handling & Resilience Specification

## Philosophy

**Resilience over correctness.** The system should:
- Fail gracefully, not catastrophically
- Log what went wrong and why
- Attempt recovery automatically when possible
- Fall back to safe state, not crash
- Never lose user data
- Enable debugging with detailed context

---

## 1. Error Categories

### 1.1 By Severity

| Severity | Example | Recovery | User Impact |
|----------|---------|----------|-------------|
| **Critical** | Profile corrupted | Restore from backup | Agent can't start |
| **Major** | Plugin install fails | Skip plugin, continue | Missing features |
| **Minor** | CLAUDE.md rendering slow | Use cache | Small delay |
| **Info** | Plugin update available | Suggest to user | None |

### 1.2 By Component

```
ProfileSystem
├── ProfileNotFound(path)
├── ProfileInvalid(path, errors)
├── ValidationFailed(field, reason)
└── CorruptedProfile(path, attempted_recovery)

ProjectScanner
├── ProjectNotFound(path)
├── InvalidProjectStructure(path, reason)
├── StackDetectionFailed(path, errors)
└── ScanTimeout(path, duration)

ClaudeMdGenerator
├── TemplateNotFound(template_name)
├── RenderFailed(template, variables, error)
├── MultiLayerGenerationPartial(layers_failed, layers_succeeded)
└── FileWriteFailed(path, reason, recovery_attempted)

AgentManager
├── AgentNotFound(agent_name)
├── SpawnFailed(project_path, error)
├── ProcessDied(agent_name, pid, signal)
├── PermissionDenied(action, reason)
└── TaskTimeout(agent_name, task_id, duration)

PluginSystem
├── PluginNotFound(plugin_name, source)
├── DependencyNotMet(plugin_name, missing_deps)
├── DependencyConflict(plugin_name, conflicts)
├── PluginHookFailed(plugin_name, hook_name, error)
├── MCP_ServerFailedToStart(mcp_name, error)
└── PluginInstallFailed(plugin_name, error, recovery)

EnhancementSystem
├── SignalLoggingFailed(task_id, signal_type, error)
├── AccumulatorCorrupted(path, attempted_recovery)
└── EnhancementApplicationFailed(proposals, failed_indices)

TelegramChannel
├── BotTokenInvalid()
├── MessageSendFailed(chat_id, error, retry_count)
├── PermissionTimeoutExpired(req_id)
└── CallbackParsingFailed(callback_data)
```

---

## 2. Recovery Strategies

### 2.1 Backup & Restore

```python
class BackupManager:
    """Create and restore from backups for critical operations."""

    def backup_before_operation(operation_name: str,
                               target_files: list[str]) -> BackupId:
        """
        Create backup before risky operation.

        Returns:
            BackupId that can be passed to restore()

        Examples:
            - Before profile update → backup profile.yaml
            - Before CLAUDE.md regen → backup all CLAUDE.md files
            - Before plugin install → backup settings.json
        """
        pass

    def restore(backup_id: BackupId,
                confirm: bool = True) -> bool:
        """
        Restore from backup.

        Args:
            confirm: If True, ask user before restoring

        Returns:
            True if restored, False if cancelled

        Process:
            1. Verify backup exists
            2. Optionally ask user to confirm
            3. Restore all files from backup
            4. Verify integrity (checksums)
            5. Log restore
            6. Return success
        """
        pass

    def list_backups(agent_name: str) -> list[Backup]:
        """List available backups with timestamps and operation names."""
        pass

    def prune_old_backups(keep_count: int = 10) -> None:
        """Delete old backups, keep most recent N."""
        pass
```

### 2.2 Idempotent Operations

Every state-changing operation must be **idempotent** (safe to retry):

```python
# BAD: Not idempotent
def save_profile(profile):
    profile.version += 1  # ← If called twice, version increments twice!
    write_yaml(profile)

# GOOD: Idempotent
def save_profile(profile):
    existing = load_profile_safe(profile.name)
    if existing and existing.version >= profile.version:
        return False  # Already saved

    profile.version = max(profile.version, existing.version + 1)
    write_yaml(profile)
    return True
```

**Idempotency checklist:**
- `save_profile()` → check if already latest version
- `install_plugin()` → check if already installed
- `apply_enhancement()` → check if already applied
- `generate_claude_md()` → compare with previous, skip if identical

### 2.3 Partial Success Handling

Some operations have multiple steps. Fail gracefully if part succeeds:

```python
class MultiLayerGenerator:
    """Generate CLAUDE.md at multiple layers."""

    def generate_all(agent_name) -> GenerationResult:
        """
        Generate CLAUDE.md at all layers.

        Returns:
            GenerationResult with:
            - succeeded: [project/, src/auth/, src/payments/]
            - failed: [(src/payments/, reason), ...]
            - partial: True if some succeeded

        Behavior:
            - If 1 layer fails → continue with others
            - Never lose existing CLAUDE.md files
            - Report which succeeded/failed to user
        """
        result = GenerationResult()

        # Project level (mandatory)
        try:
            generate_project_level()
            result.succeeded.append("project/")
        except Exception as e:
            result.failed.append(("project/", str(e)))
            # Log critical error, but don't crash

        # Layer-specific (optional)
        for layer_path in profile.sensitive_dirs:
            try:
                generate_layer_specific(layer_path)
                result.succeeded.append(layer_path)
            except Exception as e:
                result.failed.append((layer_path, str(e)))
                # Log warning, continue

        if result.failed:
            logger.warning(f"CLAUDE.md generation partial: {result.failed}")

        return result
```

---

## 3. Validation Checkpoints

### 3.1 Before Operations (Input Validation)

```python
class InputValidator:
    """Validate inputs before operations."""

    def validate_profile_yaml(path: str) -> ValidationResult:
        """
        Validate YAML syntax and schema.

        Checks:
            - File readable and valid YAML 1.2
            - Required fields present
            - Types match schema
            - Paths reference valid locations
            - No circular dependencies
        """
        pass

    def validate_project_path(path: str) -> ValidationResult:
        """
        Validate project path.

        Checks:
            - Path exists and is directory
            - Git repo detected
            - Has package.json / pyproject.toml / etc.
            - Not symlink to itself (infinite loop)
            - Readable by current user
        """
        pass

    def validate_plugin_source(source: str) -> ValidationResult:
        """
        Validate plugin source format.

        Accepts: "name@marketplace", "github:user/repo", "./local/path"
        Rejects: malformed URLs, non-existent paths
        """
        pass
```

### 3.2 After Operations (Output Validation)

```python
class OutputValidator:
    """Validate outputs after operations."""

    def validate_profile_save(path: str) -> ValidationResult:
        """
        After saving profile.yaml, verify:

        Checks:
            - File exists and readable
            - YAML parses correctly
            - All required fields present
            - Version incremented correctly
            - Checksum matches (detect corruption)
        """
        pass

    def validate_claude_md_generation(layer: str) -> ValidationResult:
        """
        After generating CLAUDE.md, verify:

        Checks:
            - File exists at expected location
            - Contains expected sections
            - Markdown is valid (no syntax errors)
            - Not empty (template failure)
        """
        pass

    def validate_settings_json(path: str) -> ValidationResult:
        """
        After updating settings.json, verify:

        Checks:
            - Valid JSON
            - All hooks point to existing files
            - All MCP commands are valid
            - No duplicate entries
        """
        pass
```

---

## 4. Logging & Diagnostics

### 4.1 Structured Logging

```python
import logging
from enum import Enum

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

def log_operation(
    operation: str,
    status: str,  # started | succeeded | failed
    context: dict = None,
    error: Exception = None
):
    """
    Log operation with full context.

    Examples:
        log_operation("profile_save", "started",
                     {"agent": "coder-my-app"})

        log_operation("profile_save", "succeeded",
                     {"agent": "coder-my-app", "version": 2})

        log_operation("profile_save", "failed",
                     {"agent": "coder-my-app"},
                     error=IOError("disk full"))
    """
    pass
```

### 4.2 Log Locations

```
~/.claude-bridge/
├── logs/
│   ├── daemon.log              # Main daemon log
│   ├── agent-coder-my-app.log  # Per-agent log
│   └── plugin-install.log      # Plugin operations
```

### 4.3 Debug Mode

```bash
# Start daemon with debug logging
CLAUDE_BRIDGE_DEBUG=1 claude-bridge start

# Tail logs
tail -f ~/.claude-bridge/logs/daemon.log

# Export logs for issue report
claude-bridge logs export
```

---

## 5. State Recovery

### 5.1 Corrupted Profile Recovery

```python
def load_profile_safe(agent_name: str) -> Profile:
    """
    Load profile, attempt recovery if corrupted.

    Process:
    1. Try load profile.yaml
    2. If YAML invalid:
       - Check if backup exists
       - Restore from latest backup
       - Log recovery attempt
       - Alert user
    3. If profile incomplete (missing required fields):
       - Load from backup and merge
       - Warn user about missing data
    4. If version mismatch (corrupted version number):
       - Reset version to max(backups) + 1
       - Log anomaly
    """
    pass
```

### 5.2 Enhancement Accumulator Recovery

```python
def load_accumulator_safe(agent_name: str) -> Accumulator:
    """
    Load accumulator, attempt recovery if corrupted.

    If YAML invalid:
    - Check backup (kept per session)
    - Start fresh if no backup (signals lost, but agent works)
    - Log loss
    """
    pass
```

---

## 6. Permission & Access Errors

### 6.1 Handling Permission Denied

```python
try:
    profile.save()
except PermissionError as e:
    logger.error(f"Cannot write profile: {e}")

    # Attempt recovery
    if can_write_to_temp():
        save_to_temp()
        logger.warn("Saved to temp location instead. Check permissions.")
        suggest_fix("Run: chmod u+w ~/.claude-bridge/agents/*")
    else:
        raise  # Can't write anywhere, crash
```

### 6.2 Handling Missing Dependencies

```python
def check_dependencies() -> DependencyStatus:
    """
    Check if required tools are available:
    - claude CLI
    - tmux
    - git
    - python3
    """

    missing = []
    if not is_installed("claude"):
        missing.append("claude (install from https://...)")
    if not is_installed("tmux"):
        missing.append("tmux (brew install tmux)")

    if missing:
        raise DependencyError(f"Missing: {missing}")
```

---

## 7. Timeout Handling

### 7.1 Operation Timeouts

```python
def operation_with_timeout(func, timeout_seconds: int, default_return=None):
    """
    Execute function with timeout.

    If timeout expires:
    - Log timeout
    - Return default_return if provided
    - Raise TimeoutError if not

    Usage:
        result = operation_with_timeout(
            generate_claude_md,
            timeout_seconds=30,
            default_return=use_cached_version
        )
    """
    pass
```

### 7.2 Permission Request Timeout

```python
async def wait_for_permission(req_id: str, timeout: int = 300):
    """
    Wait for user permission via Telegram.

    If timeout expires:
    - Default to DENY (safe)
    - Log timeout
    - Suggest user check Telegram
    """
    pass
```

---

## 8. Debugging Helpers

### 8.1 Diagnostics Command

```bash
claude-bridge diagnose

Output:
✓ Claude CLI installed (v2.1.80)
✓ Profiles directory readable
✗ Telegram token invalid (missing bot token)
⚠ Plugins: 2 failed to load
  - typescript-linter: hook script missing
  - custom-reviewer: MCP server timeout
```

### 8.2 Profile Validation Command

```bash
claude-bridge validate coder-my-app

Output:
Profile: coder-my-app
Version: 5
Status: ✓ Valid

Issues found: 1 warning
⚠ File path "docs/payment-flow.md" doesn't exist (but that's ok)
```

### 8.3 Repair Command

```bash
claude-bridge repair coder-my-app

Process:
1. Load profile
2. Validate all fields
3. Check CLAUDE.md consistency
4. Verify all plugin installations
5. Regenerate settings.json
6. Report what was fixed
```

---

## 9. Success Criteria

Error handling is complete when:

- [x] All error categories documented
- [x] Recovery strategies defined for each error
- [x] Backup/restore system implemented
- [x] All operations idempotent
- [x] Partial success handled gracefully
- [x] Validation before and after operations
- [x] Structured logging implemented
- [x] Debug mode available
- [x] State recovery for corruption
- [x] Diagnostics and repair commands working
- [x] User can understand and fix errors
- [x] No silent data loss (always logged if lost)

