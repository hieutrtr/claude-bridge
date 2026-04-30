# Tính năng Lấy Cảm Hứng từ oh-my-claudecode (OMC)

> Phân tích và đề xuất các tính năng OMC phù hợp để tích hợp vào claude-bridge.
> Viết ngày 2026-03-30.

---

## Tóm tắt nhanh

| Tính năng OMC | Adopt? | Priority | Ghi chú |
|---|---|---|---|
| Autopilot pipeline | ✅ Adopt | P0 | Core value-add cho bridge |
| Persistence / Ralph loop | ✅ Adopt | P0 | Task không bao giờ lost |
| Quality gates (QA agent) | ✅ Adopt | P1 | Verification sau execution |
| Smart model routing | ✅ Adopt | P1 | Haiku/Sonnet/Opus theo task |
| Notepad wisdom | ✅ Adopt | P1 | Per-task learnings tracking |
| Rich notifications | ✅ Adopt | P2 | Progress mid-task via Telegram |
| Cost tracking / Analytics | ✅ Adopt | P2 | Đã có cơ bản, cần mở rộng |
| Agent specialization | ✅ Adapt | P2 | Adapt cho bridge majors |
| Multi-agent pipeline | ✅ Adapt | P3 | Team coordination nâng cao |
| HUD statusline | ⚠️ Adapt | P3 | Telegram-native thay terminal |
| CCG (tri-model) | ❌ Skip | — | Phụ thuộc Codex/Gemini CLI |
| Deep-interview | ❌ Skip | — | Interactive flow, không phù hợp mobile |
| tmux workers | ❌ Skip | — | Bridge dùng subprocess model khác |
| SWE-bench benchmark | ❌ Skip | — | Infrastructure tooling, không phù hợp |

---

## 1. Tính năng nên Adopt vs. Không

### ✅ Nên Adopt

#### 1.1 Autopilot Pipeline
**Lý do:** OMC's autopilot là pipeline 5 giai đoạn tự động hóa toàn bộ quy trình từ ý tưởng → code hoàn chỉnh. Đây là giá trị cốt lõi nhất để claude-bridge vượt lên khỏi "wrapper đơn giản". Khi user dispatch từ Telegram, họ muốn *kết quả chất lượng cao*, không chỉ là "task đã chạy".

**Khác biệt với OMC:** OMC là local pipeline trong một session. Bridge pipeline cần chạy *distributed* — mỗi stage có thể là một task riêng, kết quả lưu vào SQLite.

#### 1.2 Persistence / Ralph Loop
**Lý do:** OMC's ralph đảm bảo "không dừng cho đến khi task verified done". Bridge có cron watcher nhưng đó là fallback reactive. Cần persistence proactive: retry khi fail, checkpoint khi dài, resume khi restart.

#### 1.3 Quality Gates (QA Agent)
**Lý do:** Hiện tại bridge tasks không có verification — executor chạy xong là "done". OMC's ultraqa/verifier là key insight: *completion ≠ correctness*. Bridge cần spawn QA sub-agent sau execution.

#### 1.4 Smart Model Routing
**Lý do:** Không phải task nào cũng cần Claude Opus. OMC tự động route: haiku cho lookup đơn giản, sonnet cho implementation, opus cho architecture/review phức tạp. Bridge hiện set model cứng per-agent — lãng phí.

#### 1.5 Notepad Wisdom
**Lý do:** OMC's notepad ghi lại learnings/decisions/issues *per task* theo cấu trúc. Bridge chỉ có task summary dạng plain text. Structured notepad giúp bridge bot và user hiểu "tại sao" không chỉ "cái gì".

#### 1.6 Rich Notifications
**Lý do:** Hiện tại bridge chỉ notify khi task *hoàn thành*. OMC notify ở nhiều lifecycle events. User dispatch task từ mobile, muốn biết: task đang ở giai đoạn nào? có blocker không? ETA?

#### 1.7 Agent Specialization (adapted)
**Lý do:** OMC có 19 specialized agents. Bridge có concept "majors" (backend, frontend...). Cần thêm specialized sub-agents: planner, executor, reviewer, qa-tester — được spawn tự động trong pipeline, không chỉ top-level agents.

### ❌ Không nên Adopt

#### CCG (Claude-Codex-Gemini)
**Lý do:** CCG yêu cầu `codex` và `gemini` CLIs được cài trên máy. claude-bridge là remote dispatch tool — user có thể dispatch từ iPhone, không kiểm soát được local CLIs. Thêm vào là tăng dependency complexity không cần thiết cho MVP.

#### Deep-Interview
**Lý do:** Deep-interview là Socratic questioning *interactive* — hỏi đáp 10+ turns trước khi code. Trên Telegram thì ổn, nhưng nó biến "dispatch nhanh từ mobile" thành "conversation dài". Bridge đặt cược vào *speed of dispatch*. Nếu cần clarification, bridge bot có thể hỏi 1-2 câu targeted, không cần full Socratic pipeline.

#### tmux workers
**Lý do:** OMC dùng tmux để spawn Codex/Gemini workers trong split-panes terminal. Bridge dùng `subprocess.Popen` với `start_new_session=True`. Hai model hoàn toàn khác nhau. Bridge không cần tmux.

#### SWE-bench Benchmarks
**Lý do:** Infrastructure tool cho OMC developers tự đánh giá quality. Không liên quan đến bridge use case.

#### HUD Statusline (terminal)
**Lý do:** OMC's HUD là terminal statusline. Bridge chạy headless. "HUD" của bridge phải là Telegram messages, không phải terminal — xem mục Observability.

---

## 2. Autopilot Pipeline cho Bridge Tasks

### 2.1 Hiện tại vs. Mục tiêu

```
Hiện tại:
dispatch("add pagination to /users endpoint")
    → claude --agent backend--my-api -p "add pagination..."
    → done/failed
    → notify user: "Task done: [summary]"

Mục tiêu:
dispatch("add pagination to /users endpoint")
    → Stage 1: EXPAND  — clarify & expand requirements
    → Stage 2: PLAN    — break down into subtasks, estimate
    → Stage 3: EXECUTE — implement
    → Stage 4: QA      — verify correctness, run tests
    → Stage 5: REPORT  — structured report về Telegram
    → notify user: rich report với kết quả từng stage
```

### 2.2 Thiết kế Pipeline

```
User dispatch: "add pagination to /users endpoint"
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│  Stage 1: EXPAND (Haiku/Sonnet — fast)                   │
│  Prompt: "Analyze this task. Identify:                    │
│   - What files will be changed                           │
│   - What edge cases exist                                │
│   - Any dependencies or risks                            │
│  Output: expanded_spec.md in workspace"                  │
│  Duration: ~30s                                          │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│  Stage 2: PLAN (Sonnet)                                  │
│  Input: expanded_spec.md                                 │
│  Prompt: "Create an implementation plan with steps       │
│   ordered by dependency. Max 5 steps."                   │
│  Output: plan.md in workspace                            │
│  Duration: ~45s                                          │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│  Stage 3: EXECUTE (Sonnet/Opus theo complexity)          │
│  Input: plan.md + original prompt                        │
│  Prompt: "Execute this plan. Follow the steps exactly."  │
│  Output: code changes + execution_summary.md             │
│  Duration: 2-10 phút                                     │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│  Stage 4: QA (Sonnet)                                    │
│  Input: execution_summary.md + expanded_spec.md          │
│  Prompt: "Verify the implementation:                     │
│   1. Does it match the spec?                             │
│   2. Are there obvious bugs?                             │
│   3. Run tests if available.                             │
│  Output: qa_report.md — PASS/FAIL + details"             │
│  Duration: ~60s                                          │
│  If FAIL: → trigger retry hoặc flag for human           │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│  Stage 5: REPORT                                         │
│  Compile kết quả từ workspace files → Telegram message   │
│  Format: structured report với emoji + sections          │
└──────────────────────────────────────────────────────────┘
```

### 2.3 Pipeline Mode vs. Standard Mode

Không phải task nào cũng cần 5 stages. Bridge cần support:

| Mode | Khi nào dùng | Trigger |
|---|---|---|
| `fast` | Quick tasks: "run tests", "show status" | Default khi task ngắn <50 chars |
| `standard` | Phần lớn tasks | Default |
| `autopilot` | Complex feature work | User gõ `autopilot:` prefix |
| `qa-only` | Verify existing work | User gõ `verify:` prefix |

**Ví dụ dispatch từ Telegram:**
```
/dispatch backend add pagination        → standard mode
autopilot: add OAuth2 authentication    → autopilot mode (full 5 stages)
verify: check if the auth PR is correct → qa-only mode
```

### 2.4 Data Model cho Pipeline

Thêm vào `tasks` table:
```sql
ALTER TABLE tasks ADD COLUMN pipeline_mode TEXT DEFAULT 'standard';
ALTER TABLE tasks ADD COLUMN pipeline_stage TEXT;  -- 'expand'|'plan'|'execute'|'qa'|'report'
ALTER TABLE tasks ADD COLUMN pipeline_state TEXT;  -- JSON: {expanded_spec, plan, qa_result}
ALTER TABLE tasks ADD COLUMN parent_pipeline_id TEXT;  -- nếu là sub-task của pipeline
```

Workspace layout mới:
```
~/.claude-bridge/workspaces/{session_id}/tasks/task-{id}/
  expanded_spec.md
  plan.md
  execution_summary.md
  qa_report.md
  notepad/
    learnings.md
    decisions.md
    issues.md
```

---

## 3. Persistence & Recovery

### 3.1 Vấn đề Hiện Tại

Bridge có `watcher.py` chạy cron 5 phút — đây là **reactive fallback**, không phải proactive persistence. Nếu:
- Process crash sau 1 phút → task lost 4 phút trước watcher phát hiện
- Claude Code rate limit → task failed, không retry
- Machine restart → tất cả running tasks mất context

### 3.2 Ralph-Inspired Persistence Layer

**Nguyên tắc từ OMC ralph:** *Một task không bao giờ "truly failed" cho đến khi human quyết định abandon nó.*

**Bridge Persistence Protocol:**

```
Task dispatched
    │
    ├─► Checkpoint #1: task_id lưu vào DB với status=running, pid, stage
    │
    ├─► On failure/crash:
    │       ├─ Rate limit? → Wait + auto-retry (max 3 lần, backoff)
    │       ├─ Process crash? → Restart từ last checkpoint
    │       ├─ Timeout? → Notify user + ask: retry? abandon?
    │       └─ Unknown error? → Log + notify user với details
    │
    └─► Completion verified (QA pass) → mark truly_done=True
```

**Retry Policy:**
```python
RETRY_POLICY = {
    'rate_limit': {'max': 5, 'backoff': 'exponential', 'base_delay': 60},
    'process_crash': {'max': 3, 'backoff': 'fixed', 'base_delay': 30},
    'timeout': {'max': 1, 'ask_user': True},
    'qa_fail': {'max': 2, 'escalate_model': True},  # lần retry dùng model cao hơn
}
```

**Checkpoint System:**

Thay vì chỉ ghi `status=running`, ghi cả *stage progress*:
```json
{
  "task_id": "abc123",
  "pipeline_stage": "execute",
  "checkpoint_at": "2026-03-30T14:32:00Z",
  "stage_outputs": {
    "expand": "~/.claude-bridge/workspaces/.../expanded_spec.md",
    "plan": "~/.claude-bridge/workspaces/.../plan.md"
  },
  "resume_prompt": "Continue from plan.md. Stages expand+plan already complete."
}
```

Khi restart, không chạy lại từ đầu — resume từ stage cuối cùng đã checkpoint.

### 3.3 Watcher Enhancements

Watcher hiện tại chỉ detect dead PIDs. Nâng cấp:

```python
class EnhancedWatcher:
    def run_cycle(self):
        for task in db.get_running_tasks():
            if self.is_rate_limited(task):
                self.schedule_retry(task, reason='rate_limit')
            elif self.is_pid_dead(task):
                if task.retry_count < MAX_RETRIES:
                    self.resume_from_checkpoint(task)
                else:
                    self.mark_failed_notify_user(task)
            elif self.is_timeout(task):
                self.notify_user_ask_retry(task)
            elif self.is_stuck(task):  # running >30m, no output
                self.notify_user_progress_check(task)
```

---

## 4. Multi-Agent Coordination

### 4.1 Hiện Tại

Bridge có `teams` table và `create-team` command nhưng agents về cơ bản *độc lập*. Team task = lead agent nhận task, tự phân chia. Không có shared context thực sự.

### 4.2 OMC Team Pipeline (adapted for bridge)

OMC dùng: `team-plan → team-prd → team-exec → team-verify → team-fix`

Bridge adaptation — **4 coordination patterns**:

#### Pattern A: Sequential Pipeline (Pipeline Tasks)
```
Task: "Build user authentication feature"
    │
    ├─► Planner agent → plan.md
    │       ↓
    ├─► Executor agent (reads plan.md) → code changes
    │       ↓
    ├─► Reviewer agent (reads changes) → review_notes.md
    │       ↓
    └─► QA agent (reads review_notes.md) → qa_report.md
```
*Shared context via workspace files, không phải shared memory.*

#### Pattern B: Parallel + Aggregate (Ultrawork-style)
```
Task: "Review entire codebase for security issues"
    │
    ├─► Security agent (auth module) ─────────────────┐
    ├─► Security agent (API endpoints) ───────────────┤
    └─► Security agent (database layer) ──────────────┤
                                                       ▼
                                            Aggregator agent
                                            (combines 3 reports)
                                                       ↓
                                               Final report
```

#### Pattern C: Dependency Chain (cho feature work)
```python
# bridge-cli chain "build user auth"
tasks = [
    {"id": "t1", "prompt": "Design auth schema", "deps": []},
    {"id": "t2", "prompt": "Implement models", "deps": ["t1"]},
    {"id": "t3", "prompt": "Implement API endpoints", "deps": ["t2"]},
    {"id": "t4", "prompt": "Write tests", "deps": ["t3"]},
    {"id": "t5", "prompt": "Security review", "deps": ["t3"]},
]
# t4 và t5 run parallel vì cùng dep t3
```

#### Pattern D: Expert Consultation (CCG-inspired, nhưng dùng Claude models)
```
Main executor agent đang làm task
    → Gặp vấn đề phức tạp về security
    → Spawn security-reviewer sub-agent với context cụ thể
    → Security agent trả lời, executor tiếp tục
```
*Không cần Codex/Gemini — dùng different prompts/models trong cùng Claude ecosystem.*

### 4.3 Shared Context Protocol

**Vấn đề:** Mỗi agent có context window riêng. Làm sao share context?

**Giải pháp — Workspace Files as Shared Memory:**
```
~/.claude-bridge/workspaces/{session_id}/tasks/task-{id}/
  context.md          ← shared read/write file
  handoff.md          ← từ agent trước sang agent sau
  constraints.md      ← bất biến (không được thay đổi)
  stage_outputs/
    expand.md
    plan.md
    execute_summary.md
    qa_report.md
```

Mỗi agent khi dispatch nhận thêm:
```
prompt: "Your task: [task].
Context from previous stages: [read context.md]
Constraints: [read constraints.md]
Write your output to: [handoff.md]"
```

### 4.4 Data Model

```sql
-- Thêm vào tasks table
ALTER TABLE tasks ADD COLUMN coordination_pattern TEXT;  -- 'pipeline'|'parallel'|'chain'|'consult'
ALTER TABLE tasks ADD COLUMN pipeline_position INTEGER;  -- vị trí trong chain
ALTER TABLE tasks ADD COLUMN workspace_context_path TEXT;  -- shared context file

-- Task dependencies
CREATE TABLE task_dependencies (
    task_id TEXT NOT NULL,
    depends_on_task_id TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (task_id, depends_on_task_id)
);
```

---

## 5. Quality Gates

### 5.1 Vấn đề

Hiện tại `done` chỉ nghĩa là "claude process exited 0". Không biết:
- Code có compile không?
- Tests có pass không?
- Requirement có được fulfill không?
- Có regression không?

### 5.2 QA Layer Design

**Nguyên tắc:** Sau mỗi execution task (ở bất kỳ mode nào), bridge spawn một QA sub-agent nhỏ.

```python
QA_PROMPT_TEMPLATE = """
You are a QA verifier. Do NOT make any changes to the code.

Task that was executed: {original_task}
Agent that executed it: {agent_name}
Execution summary: {read execution_summary.md}

Your job:
1. Run the test suite if it exists: `pytest` or `npm test` or equivalent
2. Check if the task requirements were actually met
3. Look for obvious bugs or regressions
4. Check for any TODO/FIXME left behind

Output a QA report to qa_report.md with:
- VERDICT: PASS | FAIL | PARTIAL
- Test results: [pass/fail/skip counts]
- Requirements met: [list each requirement and ✓/✗]
- Issues found: [list issues with severity]
- Recommendation: [approve | retry | escalate]
"""
```

**QA Outcomes → Actions:**

| QA Verdict | Action |
|---|---|
| PASS | Mark task `done`, notify user với success report |
| PARTIAL | Notify user với details, ask: accept? retry? |
| FAIL | Retry với executor (max 2 lần), escalate to user nếu vẫn fail |
| QA timeout/error | Skip QA, mark `done_unverified`, notify user |

### 5.3 QA Tiers (theo task complexity)

Không phải mọi task đều cần QA nặng:

| Tier | Khi nào | QA Action |
|---|---|---|
| `skip` | Read-only tasks ("explain this code", "show me the logs") | No QA |
| `light` | Small changes (<50 lines) | Chỉ check test suite |
| `standard` | Feature tasks | Full QA prompt |
| `deep` | `autopilot:` mode, security-related | Full QA + security scan |

**Auto-detect tier từ task:**
```python
def detect_qa_tier(task_prompt: str) -> str:
    if is_read_only(task_prompt):
        return 'skip'
    if is_security_related(task_prompt):
        return 'deep'
    if estimated_complexity(task_prompt) < 50:
        return 'light'
    return 'standard'
```

### 5.4 QA Cost

QA sub-agent dùng Haiku (nhanh + rẻ) trừ `deep` tier thì dùng Sonnet.

---

## 6. Observability

### 6.1 OMC HUD → Bridge Telegram HUD

OMC có HUD trong terminal statusline. Bridge không có terminal — "HUD" là các Telegram messages có cấu trúc.

**Thiết kế Bridge Telegram HUD:**

```
📋 Task #abc123 — backend/my-api
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 Task: add pagination to /users
👤 Agent: backend--my-api (Sonnet)
🔄 Pipeline: autopilot mode

Stage Progress:
  ✅ Expand    (23s)
  ✅ Plan      (41s)
  🔵 Execute  [████████░░] ~3min left
  ⬜ QA
  ⬜ Report

💰 Cost so far: $0.08 / ~$0.15 estimated
⏱️  Running: 4m 12s
```

**Khi nào gửi progress update:**
- Task bắt đầu: initial HUD message
- Mỗi stage hoàn thành: update message (edit, không tạo message mới)
- Blocker / error: ping user ngay
- Completion: replace HUD với final report

**Implementation:** Dùng Telegram `editMessageText` để update *cùng một message*, không spam chat.

### 6.2 Progress Tracking

Thêm event log per task:

```sql
CREATE TABLE task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- 'stage_start'|'stage_complete'|'retry'|'error'|'cost_update'
    event_data TEXT,  -- JSON
    created_at TEXT DEFAULT (datetime('now'))
);
```

Bridge bot có thể query: `bridge_events <task_id>` → hiển thị timeline đầy đủ.

### 6.3 Cost Tracking

Hiện tại bridge lưu `cost_usd` per task. Nâng cấp:

```python
class CostTracker:
    def record(self, task_id: str, stage: str, input_tokens: int,
               output_tokens: int, model: str):
        # Lưu breakdown chi tiết
        # Tính running total
        # Alert nếu task vượt threshold

    def daily_summary(self) -> dict:
        # Total spend hôm nay
        # By agent breakdown
        # Most expensive tasks

    def estimate_remaining(self, task_id: str) -> float:
        # Dựa trên stages còn lại + historical data
```

**Telegram command mới:** `/cost` → báo cáo chi phí hôm nay / tuần / tháng.

### 6.4 Anomaly Detection

Dựa trên historical task data:

```python
def detect_anomalies(task: Task) -> list[str]:
    warnings = []
    avg_duration = db.get_avg_duration(task.agent_name, task.complexity_tier)

    if task.duration > avg_duration * 3:
        warnings.append(f"⚠️ Task running unusually long ({task.duration}m vs avg {avg_duration}m)")

    if task.cost_usd > DAILY_BUDGET * 0.5:
        warnings.append(f"💸 This single task = 50% of daily budget")

    if task.retry_count > 2:
        warnings.append(f"🔁 Task has retried {task.retry_count} times — may need human review")

    return warnings
```

---

## 7. Implementation Roadmap

### Phase 1 — Foundation for Intelligence (2-3 tuần)
*Không thay đổi UX, chỉ build infrastructure.*

**P1.1 — Workspace & Notepad System**
- Chuẩn hóa workspace layout với stage_outputs/
- Implement notepad (learnings.md, decisions.md, issues.md per task)
- Refactor on_complete.py để ghi vào notepad

**P1.2 — Enhanced Task Data Model**
- Thêm `pipeline_mode`, `pipeline_stage`, `pipeline_state` vào tasks
- Thêm `task_events` table
- Thêm `task_dependencies` table
- Migration script

**P1.3 — Cost Tracking Nâng Cao**
- Stage-level cost breakdown
- Daily/weekly summary
- Budget alerts

**Deliverable:** Infrastructure sẵn sàng cho Phase 2. Không thay đổi behavior với user.

---

### Phase 2 — QA Layer (1-2 tuần)
*User bắt đầu nhận được verified results.*

**P2.1 — QA Agent**
- Implement QA sub-agent spawn sau mỗi execution
- Auto-detect QA tier (skip/light/standard)
- QA report format + lưu vào workspace

**P2.2 — QA Outcomes → Actions**
- PASS: update task status, notify
- FAIL: retry logic (max 2 lần)
- PARTIAL: notify user với details

**P2.3 — QA Metrics**
- Track QA pass rate per agent
- Track common failure reasons
- Expose via `bridge_status` MCP tool

**Deliverable:** Tasks có QA verification. User nhận report có độ tin cậy cao hơn.

---

### Phase 3 — Autopilot Pipeline (2-3 tuần)
*Full 5-stage pipeline cho complex tasks.*

**P3.1 — Stage Dispatching**
- Implement stage runner: expand → plan → execute → qa → report
- Stage prompt templates
- Stage-to-stage handoff via workspace files

**P3.2 — Mode Detection**
- Auto-detect mode từ task prompt
- Support explicit prefix: `autopilot:`, `verify:`, `fast:`
- Mode config per agent (default mode)

**P3.3 — Mid-Task Notifications**
- Progress HUD via Telegram edit message
- Stage completion pings
- Error alerts

**Deliverable:** `autopilot: build me X` từ Telegram → full pipeline → rich report.

---

### Phase 4 — Persistence & Recovery (1-2 tuần)
*Tasks không bao giờ lost.*

**P4.1 — Checkpoint System**
- Ghi checkpoint sau mỗi stage
- Resume logic trong dispatcher
- Checkpoint format và validation

**P4.2 — Smart Retry**
- Retry policy per error type
- Rate limit detection + auto-wait
- Model escalation khi retry (Haiku → Sonnet → Opus)

**P4.3 — Watcher Enhancements**
- Detect stuck tasks (running nhưng không có output)
- Rate limit detection
- User ask-to-retry flow

**Deliverable:** Không có "mystery failures" — mọi task đều có clear lifecycle cho đến khi human quyết định abandon.

---

### Phase 5 — Multi-Agent Coordination (3-4 tuần)
*Parallel execution và team coordination.*

**P5.1 — Sequential Pipeline Pattern**
- Planner → Executor → Reviewer → QA chain
- Workspace-based handoff

**P5.2 — Parallel + Aggregate Pattern**
- Fan-out: spawn N parallel sub-agents
- Fan-in: aggregator agent tổng hợp kết quả
- Bridge UI: progress tracking cho parallel tasks

**P5.3 — Dependency Chain**
- `bridge-cli chain` command
- Dependency graph execution
- Parallel execution của independent tasks

**Deliverable:** `autopilot: build fulltext search feature` → tự động tạo dependency chain và execute parallel.

---

### Phase 6 — Smart Model Routing (1 tuần)
*Đúng model cho đúng task.*

**P6.1 — Complexity Analyzer**
- Estimate task complexity từ prompt
- Classify: quick / standard / complex / critical

**P6.2 — Model Router**
- Route dựa trên complexity + agent type
- Override manual từ user: `model=opus: ...`

**P6.3 — Cost Optimization**
- Track cost per model tier per agent
- Suggest model adjustments nếu thấy pattern

**Deliverable:** 30-50% giảm cost (tương tự OMC's claim) nhờ dùng Haiku cho tasks đơn giản.

---

## 8. Tham Khảo Thiết Kế Từ OMC

### Nguyên Tắc Cốt Lõi Nên Áp Dụng

1. **"Completion ≠ Correctness"** — OMC's verifier insight. Bridge phải luôn verify trước khi báo `done`.

2. **"Pipeline over monolith"** — Chia nhỏ thay vì một task prompt khổng lồ. Mỗi stage focused, có output cụ thể.

3. **"Shared state via files, not memory"** — OMC agents không share context window. Bridge nên dùng workspace files làm "shared memory" giữa stages.

4. **"Smart routing > fixed model"** — Model tốt nhất cho từng task type, không phải một model cho tất cả.

5. **"Don't stop until verified"** — OMC's ralph principle. Bridge adaptation: retry smartly, checkpoint aggressively, escalate gracefully.

6. **"Observability first"** — User cần biết *gì đang xảy ra*, không chỉ kết quả cuối. Progress updates là feature, không phải nice-to-have.

### Điều OMC Làm Khác Với Bridge

| Chiều | OMC | Claude Bridge |
|---|---|---|
| Interface | Local terminal / slash commands | Remote Telegram messages |
| Execution | Interactive sessions | Fire-and-forget subprocesses |
| Context | In-memory session | Persistent SQLite + workspace files |
| User presence | User ở local, có thể watch terminal | User ở xa, có thể offline khi task chạy |
| Failure mode | User thấy ngay, có thể intervene | User không biết cho đến notification |
| Multi-agent | Native Task tool trong Claude Code | Separate subprocess per agent |
| State persistence | .omc/ directory per project | ~/.claude-bridge/ centralized |

*Khác biệt này định hình mọi design decision: bridge cần nhiều persistence hơn, ít interactivity hơn, nhiều async communication hơn.*

---

## 9. Quick Wins (Có Thể Implement Ngay)

Các tính năng nhỏ có value cao, không đòi hỏi refactor lớn:

1. **Progress message edit** — Khi task bắt đầu, gửi "🔄 Running..." message. Khi xong, edit message đó thành kết quả. (Không spam chat.)

2. **Cost per task trong notification** — Thêm `💰 Cost: $0.12` vào mọi completion notification. (Đã có data, chỉ cần format.)

3. **Task ETA** — Dựa trên historical data của agent, estimate thời gian còn lại.

4. **Simple QA check** — Sau execution, chạy `pytest` hoặc `npm test` (nếu có), include kết quả trong notification.

5. **Retry command** — User nhận notification "Task failed" → reply `/retry <task_id>` → bridge tự dispatch lại.

6. **Stage prefix** — Support `fast:` prefix để bypass staging cho simple tasks.

---

*Document này là living spec — cập nhật khi implementation tiến triển và khi user feedback thay đổi priorities.*
