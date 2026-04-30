# Profile System — Claude Bridge

## Profile Schema

```yaml
# ~/.claude-bridge/agents/{agent-name}/profile.yaml

# ── Metadata ──────────────────────────────────────
name: coder-my-app
version: 1                    # tăng mỗi lần enhance
created: 2026-03-25
last_enhanced: 2026-03-25
base_template: coder-fullstack

# ── Identity ──────────────────────────────────────
identity:
  role: coder                 # coder | researcher | reviewer | devops | writer | analyst
  display_name: "Senior Coder"
  project: ~/projects/my-app
  description: "Full-stack dev cho my-app"

# ── Context ───────────────────────────────────────
context:
  stack: [nextjs, typescript, prisma, react-query, zod]
  
  key_dirs:
    - path: src/auth/
      note: "Authentication logic, hay có bugs ở session.ts"
    - path: src/api/
      note: "API endpoints"
    - path: src/payments/
      note: "⚠️ SENSITIVE — confirm trước khi sửa"
      sensitive: true
  
  critical_files:
    - path: prisma/schema.prisma
      reason: "DB schema — agent hỏi 7 lần"
      auto_added: true
    - path: .env.example
      reason: "Env variables — agent hỏi 4 lần"
      auto_added: true
    - path: docs/payment-flow.md
      reason: "Business logic của payment"
      auto_added: false       # user manually added

# ── Rules ─────────────────────────────────────────
rules:
  hard:                       # User-defined, bất khả xâm phạm
    - "Không push thẳng main — luôn tạo PR"
    - "Không sửa /src/payments/** mà không confirm"
  
  soft:                       # Learned qua thời gian, có thể evolve
    - text: "Dùng Zod cho validation, không dùng Joi"
      learned_from: "session_003"
      confidence: high
    - text: "Dùng React Query, không dùng SWR"
      learned_from: "session_005"
      confidence: high
    - text: "Không dùng 'any' trong TypeScript"
      learned_from: "session_007"
      confidence: high
    - text: "Chạy npm test sau khi sửa bất kỳ file nào"
      learned_from: "pattern_detection"
      confidence: medium

# ── Tools ─────────────────────────────────────────
tools:
  mcp_servers:
    - filesystem
    - github
    - postgres           # detected từ Prisma
  
  allowed_tools: [read, write, bash, browser]
  
  restricted_tools: []
  
  bash_blocklist:
    - "rm -rf"
    - "git push origin main"
    - "git push --force"
    - "prisma migrate"   # requires explicit confirm

# ── Skills ────────────────────────────────────────
skills:
  - review              # code review checklist
  - test                # run + fix failing tests
  - commit              # conventional commits
  - explain             # giải thích code

# ── Hooks ─────────────────────────────────────────
hooks:
  session_start:
    - load_dev_docs: true
    - inject_git_status: true
  
  pre_tool_use:
    bash:
      - block_pattern: "rm -rf"
        message: "Blocked: rm -rf không được phép"
      - relay_permission:
          pattern: "prisma migrate"
          message: "Agent muốn chạy migration — approve?"
    write:
      - confirm_if_path_matches: "src/payments/**"
  
  post_tool_use:
    write:
      - run: "npx eslint --fix {file}"
        async: true
  
  stop:
    - check_tests_written: true
      message: "Nhắc agent: đã viết tests chưa?"
  
  pre_compact:
    - update_dev_docs: true

# ── Reporting ─────────────────────────────────────
reporting:
  channel: telegram
  style: summary              # brief | summary | detailed
  
  on_complete:
    include: [summary, files_changed, test_results]
  
  on_error:
    include: [error_message, what_was_tried, suggested_fix]
  
  on_permission_needed:
    include: [action_description, risk_level, file_preview]
  
  on_progress:              # cho long-running tasks
    interval_minutes: 5
    include: [current_step, percent_complete]

# ── Memory ────────────────────────────────────────
memory:
  learned_patterns:
    - "Auth bugs thường nằm ở src/auth/session.ts"
    - "DB errors thường do schema mismatch với Prisma client"
  
  frequent_tasks:
    - task: "fix auth bugs"
      count: 4
    - task: "add API endpoints"
      count: 3
    - task: "write tests"
      count: 3
  
  known_issues:
    - "Payment webhook hay timeout sau 30s"
    - "Test environment cần POSTGRES_TEST_URL"

# ── Dev Docs ──────────────────────────────────────
dev_docs:
  enabled: true
  auto_update_before_compact: true
  dir: .bridge/dev/
  files:
    plan: plan.md
    context: context.md
    tasks: tasks.md
```

---

## Template: coder-fullstack

```yaml
# profiles/templates/coder-fullstack.yaml
# Base template — Bridge customize theo project thực tế

identity:
  role: coder
  display_name: "Senior Full-stack Developer"
  description: "Clean code, test coverage, no shortcuts"

rules:
  hard: []          # user sẽ điền lúc onboarding
  soft:
    - "Viết tests trước hoặc ngay sau khi implement"
    - "Commit sau mỗi feature nhỏ với conventional commit format"
    - "Hỏi lại nếu task mơ hồ hoặc có risk cao"

tools:
  mcp_servers: [filesystem, github]
  allowed_tools: [read, write, bash, browser]

skills: [review, test, commit, explain]

hooks:
  pre_tool_use:
    bash:
      - block_pattern: "rm -rf"
      - block_pattern: "git push --force"
  post_tool_use:
    write:
      - run_linter: true
  stop:
    - check_incomplete_work: true

reporting:
  style: summary
```

## Available Templates

| Template | Role | Key Skills |
|---|---|---|
| `coder-fullstack` | Senior dev, full-stack | review, test, commit |
| `coder-focused` | Bug fixer, scope hẹp | fix, test, explain |
| `researcher` | Web research + synthesis | search, summarize, cite |
| `reviewer` | Code review only, không sửa | review, annotate |
| `devops` | Infra + deployment | deploy, monitor, rollback |
| `writer` | Docs + content | draft, edit, format |
| `analyst` | Data analysis + reporting | query, chart, report |

---

## CLAUDE.md — Generated Output

Từ profile trên, Bridge generate:

```markdown
# Agent: coder-my-app
<!-- generated by claude-bridge v1 — đừng sửa tay -->
<!-- last updated: 2026-03-25 -->

## 🎭 Vai trò
Bạn là Senior Full-stack Developer làm việc tại ~/projects/my-app.
Stack: Next.js 15, TypeScript, Prisma, React Query, Zod.

## 📁 Project Structure
- `src/auth/`     → Authentication logic (hay có bugs ở session.ts)
- `src/api/`      → API endpoints
- `src/payments/` → ⚠️ VÙNG NHẠY CẢM — confirm với user trước khi sửa

## 📎 Files quan trọng
Đọc các files này trước khi bắt đầu task:
- `prisma/schema.prisma` — DB schema hiện tại
- `.env.example` — danh sách env variables cần thiết
- `docs/payment-flow.md` — business logic của payment

## 🔒 Rules bất biến — KHÔNG BAO GIỜ VI PHẠM
1. Không push thẳng lên main — luôn tạo PR
2. Không sửa `/src/payments/**` mà không confirm với user trước

## 📐 Conventions
- Dùng **Zod** cho validation — không dùng Joi
- Dùng **React Query** — không dùng SWR
- Không dùng `any` trong TypeScript
- Chạy `npm test` sau khi sửa bất kỳ file nào

## 📣 Reporting
- Khi xong: summary + files changed + test results
- Khi cần permission: mô tả action + risk level
- Khi lỗi: error + đã thử gì + hướng fix

## 🧠 Context đã học
- Auth bugs thường ở `src/auth/session.ts`
- DB errors thường do schema mismatch với Prisma client
- Payment webhook hay timeout sau 30s

## 📋 Nếu session bị compact
Đọc `.bridge/dev/context.md` để resume đúng chỗ.
```

---

## Enhancement Flow

### Micro-enhancement (sau mỗi session)

Bridge phân tích session log và suggest:

```
Signals → Analysis → Suggestions → User approve → Profile update → CLAUDE.md re-gen
```

**Signal types Bridge theo dõi:**
- `agent_asked_clarification`: agent hỏi về topic gì → có thể thêm vào context
- `user_corrected`: user sửa agent → có thể thành soft rule
- `hook_fired`: hook block gì → validate rules đang hoạt động
- `files_touched`: files nào hay được sửa → key dirs candidates
- `task_pattern`: tasks lặp lại → frequent_tasks memory

### Macro-enhancement (/enhance)

Phân tích nhiều sessions, output:
- 🔴 Friction points (agent hay bị chậm/hỏi)
- 🟡 Patterns phát hiện
- 🟢 Rules đang hoạt động tốt
- Batch suggestions với inline keyboard approve
