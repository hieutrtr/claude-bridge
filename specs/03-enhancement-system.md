# Enhancement System Specification

## Overview

Enhancement is how Bridge **learns** from tasks and proposes improvements to profiles.

**Key principle:** Enhancement is **passive by default**. Bridge accumulates signals, proposes changes only when threshold is met, user always approves before applying.

---

## 1. Signal System

### 1.1 Signal Types

```python
class SignalType(Enum):
    """Types of signals that accumulate."""

    USER_CORRECTED = "user_corrected"
    # User had to fix/correct agent's work
    # Example: Agent used Joi, user changed to Zod
    # Proposed: Add "Use Zod not Joi" to soft rules

    AGENT_ASKED = "agent_asked"
    # Agent repeatedly asked about something
    # Example: Agent asked "What's the payment flow?" 5 times
    # Proposed: Add docs/payment-flow.md to critical_files

    HOOK_BLOCKED = "hook_blocked"
    # Hook blocked an action
    # Example: Hook blocked "rm -rf" 3 times
    # Proposed: Validate rule is working (don't add new rule, just confirm)

    PATTERN_DETECTED = "pattern_detected"
    # Detected repeated behavior
    # Example: Agent always runs "npm test" after changes
    # Proposed: Add rule "Always run npm test"

    FILES_TOUCHED = "files_touched"
    # Agent frequently edits certain files
    # Example: Agent edited src/auth/session.ts in 4 tasks
    # Proposed: Add to key_files with "frequently edited"

    TASK_PATTERN = "task_pattern"
    # Similar tasks keep coming up
    # Example: "fix auth bugs" appeared 5 times
    # Proposed: Add to memory.frequent_tasks with pattern

    PERMISSION_REQUESTED = "permission_requested"
    # Agent needed permission multiple times for same action
    # Example: Agent asked to run "prisma migrate" 3 times
    # Proposed: Add to hooks or clarify in rules

    PLUGIN_SUGGESTED = "plugin_suggested"
    # User approved plugin suggestion
    # Example: User installed typescript-linter plugin
    # Proposed: Remember to suggest to others with similar stack
```

### 1.2 Signal Data Structure

```python
@dataclass
class Signal:
    type: SignalType
    task_id: str                      # Which task generated this
    timestamp: datetime               # When occurred
    content: str                      # Description of what happened
    proposed_change: str              # What to suggest to user
    confidence: str                   # high | medium | low
    supporting_evidence: list[str]    # Additional context

    # Metadata
    created_at: datetime
    version: int                      # 1 (for future upgrades)
```

### 1.3 Enhancement Accumulator Schema

**Location:** `~/.claude-bridge/agents/{agent-name}/enhancement-accumulator.yaml`

```yaml
# ══════════════════════════════════════════════════════════════
# SIGNALS — Accumulated during task execution
# ══════════════════════════════════════════════════════════════

signals:
  user_corrected:
    - task_001:
        content: "User changed Joi to Zod"
        proposed_change: "Add rule: Use Zod for validation"
        confidence: high
    - task_003:
        content: "User fixed state management approach"
        proposed_change: "Add rule: Use React Query for data"
        confidence: high
    # ... more signals
    # When count >= 5 → Enhancement triggered!

  agent_asked:
    - task_002:
        content: "Agent asked: What's the payment flow?"
        proposed_change: "Add docs/payment-flow.md to key_files"
        confidence: medium
    # ... more signals
    # When count >= 5 → Enhancement triggered!

  hook_blocked:
    - task_004:
        content: "Hook blocked: rm -rf pattern"
        type: validation                # Just validating existing rule
        confidence: high
    # These don't propose changes, just confirm rules work

  pattern_detected:
    - task_005:
        content: "Agent ran npm test 4 times"
        proposed_change: "Add rule: Always run npm test after changes"
        confidence: medium
    # ... more signals

  files_touched:
    - task_006:
        files: [src/auth/session.ts, src/auth/guards.ts]
        count: 4
        proposed_change: "Add src/auth/ to key_files"
        confidence: high

  task_pattern:
    - pattern: "fix auth bugs"
        count: 5
        proposed_change: "Add to memory.frequent_tasks"
        confidence: high

  plugin_suggested:
    - plugin: typescript-linter
        count: 2                          # User approved 2 times
        proposed_change: "Suggest to others"
        confidence: high

# ══════════════════════════════════════════════════════════════
# ENHANCEMENT STATE
# ══════════════════════════════════════════════════════════════

last_enhancement: 2026-03-26T10:00:00    # When last enhancement was applied
last_signal: 2026-03-26T15:30:00         # Most recent signal

pending_proposals: []                    # Proposals waiting for user

applied_signals:                         # Which signals were applied
  - user_corrected: 3                    # 3 user_corrected signals applied
  - agent_asked: 1                       # 1 agent_asked signal applied
  # Used for deduplication (don't re-propose same change)

skipped_signals:                         # User rejected these
  - task_010:
      type: user_corrected
      reason: user_rejected
      rejected_date: 2026-03-26T14:00:00
```

---

## 2. Signal Accumulator

### 2.1 Accumulator Class

```python
class EnhancementAccumulator:
    """Log and manage signals."""

    def log_signal(agent_name: str,
                   signal: Signal) -> None:
        """
        Log a signal during task execution.

        Args:
            agent_name: Which agent this is for
            signal: Signal object

        Process:
            1. Load accumulator.yaml
            2. Add signal to appropriate type
            3. Save accumulator.yaml
            4. Check if any type hit 5+ threshold
            5. If yes, trigger enhancement (async)
            6. Log operation

        Raises:
            AccumulatorError if can't save
        """
        pass

    def load_accumulator(agent_name: str) -> Accumulator:
        """
        Load accumulator.yaml.

        Returns:
            Accumulator object

        Raises:
            FileNotFoundError: If accumulator doesn't exist (create new)
            CorruptedAccumulator: If YAML invalid
        """
        pass

    def save_accumulator(agent_name: str,
                        accumulator: Accumulator) -> None:
        """Save accumulator.yaml with backup."""
        pass

    def get_signals_by_type(agent_name: str,
                           signal_type: SignalType) -> list[Signal]:
        """Get all signals of a specific type."""
        pass

    def count_by_type(agent_name: str) -> dict[SignalType, int]:
        """
        Count signals by type.

        Returns:
            { USER_CORRECTED: 5, AGENT_ASKED: 3, ... }
        """
        pass

    def check_thresholds(agent_name: str) -> list[SignalType]:
        """
        Check if any signal type hit 5+ threshold.

        Returns:
            List of signal types that should trigger enhancement
        """
        pass

    def clear_applied_signals(agent_name: str,
                             signal_types: list[SignalType]) -> None:
        """
        Remove signals that were applied to profile.

        Updates applied_signals counter.
        """
        pass

    def mark_rejected(agent_name: str,
                     task_id: str,
                     reason: str) -> None:
        """User rejected a proposal, mark signal as skipped."""
        pass
```

---

## 3. Enhancement Engine

### 3.1 Proposal Generation

```python
class EnhancementEngine:
    """Analyze signals and generate proposals."""

    def generate_proposals(agent_name: str,
                          signal_types: list[SignalType] = None) -> list[Proposal]:
        """
        Analyze signals and generate enhancement proposals.

        Args:
            signal_types: Specific types to analyze (or all if None)

        Returns:
            list[Proposal] with specific change recommendations

        Process:
            For each signal_type with signals:
            1. Load all signals of that type
            2. Group by theme/content
            3. Identify common pattern
            4. Create Proposal with:
               - type: Which signal type
               - signals_count: How many signals support this
               - proposed_text: What to add to profile
               - proposed_location: Where in profile (rules, key_files, etc.)
               - confidence: high | medium | low
               - supporting_evidence: Links to signals
            5. Deduplicate (don't propose same change twice)

        Returns:
            Sorted by confidence (high first)
        """
        pass

    def generate_proposal_for_user_corrected(signals: list[Signal]) -> list[Proposal]:
        """
        Generate proposals from user_corrected signals.

        These are often code style rules.

        Example input:
        - User changed Joi to Zod (task_001)
        - User changed Joi to Zod (task_003)
        - User changed Joi to Zod (task_005)
        - User changed Joi to Zod (task_007)
        - User changed Joi to Zod (task_009)

        Output:
        Proposal(
            type: USER_CORRECTED,
            signals_count: 5,
            proposed_text: "Use Zod not Joi",
            proposed_location: rules.soft,
            confidence: high,
            evidence: [task_001, 003, 005, 007, 009]
        )
        """
        pass

    def generate_proposal_for_agent_asked(signals: list[Signal]) -> list[Proposal]:
        """
        Generate proposals from agent_asked signals.

        These are often missing context/docs.

        Example: Agent asked "What's payment flow?" 5 times
        Proposal: Add docs/payment-flow.md to critical_files
        """
        pass

    def generate_proposal_for_pattern_detected(signals: list[Signal]) -> list[Proposal]:
        """
        Generate proposals from pattern_detected signals.

        These are often missing rules/conventions.

        Example: Agent ran "npm test" after every change 4 times
        Proposal: Add rule "Always run npm test after changes"
        """
        pass

    def generate_proposal_for_files_touched(signals: list[Signal]) -> list[Proposal]:
        """
        Generate proposals from files_touched signals.

        These are often missing key_files entries.

        Example: Agent edited src/auth/session.ts 4 times
        Proposal: Add src/auth/session.ts to critical_files
        """
        pass

    def deduplicate_proposals(proposals: list[Proposal]) -> list[Proposal]:
        """
        Remove duplicate proposals.

        Check if proposal already applied (in profile.applied_signals).
        Check if proposal text already exists in profile.
        """
        pass
```

### 3.2 Proposal Data Structure

```python
@dataclass
class Proposal:
    type: SignalType                  # Which signal type
    signals_count: int                # How many signals support this
    proposed_text: str                # What to add to profile
    proposed_location: str            # rules.soft | key_files | conventions
    confidence: str                   # high | medium | low
    supporting_evidence: list[str]    # Task IDs: [task_001, task_003, ...]

    # For display
    explanation: str                  # Human-readable reason
    example: str                      # Example from user's code
```

---

## 4. Proposal Application

### 4.1 Apply Proposals to Profile

```python
class ProposalApplier:
    """Apply user-approved proposals to profile."""

    def apply_proposals(agent_name: str,
                       proposals: list[Proposal],
                       approved_indices: list[int]) -> ApplyResult:
        """
        Apply user-approved proposals to profile.

        Args:
            proposals: All proposals (user selected which to approve)
            approved_indices: Indices of approved proposals

        Returns:
            ApplyResult with:
            - success: bool
            - applied_count: int
            - failed: [str]
            - profile_version_before: int
            - profile_version_after: int

        Process:
            1. Load profile
            2. Create backup
            3. For each approved proposal:
               - Add to appropriate location in profile
               - Update _internal.enhancement_history
            4. Increment version
            5. Save profile
            6. Regenerate CLAUDE.md
            7. Clear applied signals from accumulator
            8. Log enhancement

        Rollback on failure: restore from backup
        """
        pass

    def apply_single_proposal(profile: Profile,
                             proposal: Proposal) -> bool:
        """
        Apply a single proposal to profile.

        Returns True if applied, False if skipped (e.g., already exists)

        Location-based application:
        - rules.soft → append to soft rules
        - key_files → add to key_files with reason
        - conventions → append to learned_patterns
        - memory → add to known_issues or frequent_tasks
        """
        pass

    def check_already_applied(profile: Profile,
                             proposal: Proposal) -> bool:
        """Check if this proposal was already applied."""
        pass
```

---

## 5. Enhancement Flow

### 5.1 Automatic Trigger

When threshold is met (5+ signals of same type):

```
Task completes
  ↓
Signal logged
  ↓
Check: total signals of this type >= 5?
  ↓ YES
Trigger enhancement (async)
  ↓
Generate proposals
  ↓
Send to user (Telegram)
  ↓
User reviews + approves
  ↓
Apply to profile
  ↓
Regenerate CLAUDE.md
  ↓
Notify user: "Profile enhanced!"
```

### 5.2 Manual Trigger

User can manually request enhancement:

```
User: /enhance
  ↓
Generate proposals from all signals (regardless of threshold)
  ↓
Send to user
  ↓
User approves
  ↓
Apply + regenerate + notify
```

### 5.3 Enhancement Proposal Message

Sent via Telegram:

```
Found enhancements based on {{ count }} signals:

🔴 Code Style (5 signals)
   • Use Zod not Joi
     Evidence: tasks 001, 003, 005, 007, 009
     Example: You changed Joi → Zod in schema validation

   • Always run npm test after changes
     Evidence: Pattern detected in 4 tasks
     Example: Agent ran npm test after every file change

🟡 Documentation (3 signals)
   • Add docs/payment-flow.md to critical files
     Evidence: Agent asked "What's payment flow?" 3 times
     Impact: Agent will read this file on future tasks

[✅ Apply All] [👁️ Review Each] [❌ Skip]
```

---

## 6. User Interaction

### 6.1 Review Each Proposal

User can selectively approve/reject:

```
Proposal 1 of 3:

Use Zod not Joi

Evidence: User corrected in 5 tasks
Confidence: high

[✅ Approve] [❌ Reject] [💭 Explain more] [⏭️ Next]
```

### 6.2 Explain More

If user taps "Explain more":

```
Why this matters:
- Zod provides better TypeScript integration
- Reduces runtime errors
- Matches team's chosen library

Tasks where detected:
- task_001: Auth validation
- task_003: API request validation
- task_005: Form validation
- task_007: Database schema validation
- task_009: Webhook validation

Still want to add? [✅ Yes] [❌ No]
```

---

## 7. Enhancement History & Audit

### 7.1 Track Enhancements

```yaml
# In profile._internal
enhancement_history:
  - version: 2
    date: 2026-03-26T10:00:00
    changes:
      - "Added rule: Use Zod not Joi"
      - "Added key_file: docs/payment-flow.md"
    triggered_by: "threshold"           # threshold | manual | admin
    signal_types: [user_corrected, agent_asked]
    approved_by: "user"                 # user | auto (future)

  - version: 3
    date: 2026-03-27T14:30:00
    changes:
      - "Added rule: Always run npm test"
    triggered_by: "manual"
    approved_by: "user"
```

### 7.2 User Can See History

```bash
claude-bridge enhancement-history coder-my-app

Version 1 → 2 (2026-03-26 10:00 UTC)
  + "Use Zod not Joi" (5 signals, high confidence)
  + "docs/payment-flow.md" (3 signals, medium confidence)

Version 2 → 3 (2026-03-27 14:30 UTC)
  + "Always run npm test" (pattern detected, high confidence)
  - Removed: none
```

---

## 8. Error Handling

| Error | Recovery |
|---|---|
| Accumulator corrupted | Load from backup, continue logging |
| Proposal generation fails | Return what succeeded, log failures |
| Application fails | Rollback profile from backup |
| CLAUDE.md regen fails | Use previous version, log error |
| Telegram send fails | Queue and retry, inform user |

---

## 9. Testing

### 9.1 Unit Tests
- Signal logging and accumulation
- Threshold detection
- Proposal generation (each type)
- Deduplication
- Profile application

### 9.2 Integration Tests
- Task → signals → proposals → application → CLAUDE.md regeneration
- User approval flow
- Rollback on failure
- Multi-signal proposal batching

### 9.3 Test Fixtures
- Sample profiles with various states
- Real signal sequences
- Edge cases (conflicting proposals, etc.)

---

## 10. Success Criteria

Enhancement complete when:

- [x] Signals logged correctly during task execution
- [x] Threshold detection works (5+ per type)
- [x] Proposals generated intelligently
- [x] User can approve/reject proposals
- [x] Approved proposals apply to profile correctly
- [x] Profile version increments
- [x] CLAUDE.md regenerates after enhancement
- [x] Deduplication prevents duplicate proposals
- [x] Enhancement history tracked
- [x] Rollback works on failure
- [x] Accumulator persists correctly

