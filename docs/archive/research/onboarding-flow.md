# Onboarding Flow — Claude Bridge

## Triết lý: 3 câu hỏi, đủ dùng ngay

Onboarding phải đủ nhanh để user không nản. Profile sẽ tự hoàn thiện qua thời gian.

---

## Flow: /new-agent

```
User: /new-agent

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bridge: Tạo agent mới — 3 câu hỏi thôi 👋

        1️⃣ Agent làm việc ở đâu?
           Gửi path hoặc drag folder vào chat.
           (ví dụ: ~/projects/my-app)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
User: ~/projects/my-app

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bridge: 🔍 Đang scan ~/projects/my-app...
        
        Phát hiện: Next.js · TypeScript · Prisma · Docker
        
        2️⃣ Vai trò chính của agent là gì?
        
        [💻 Coder]    [🔍 Researcher]
        [📝 Writer]   [⚙️ DevOps]
        [👁️ Reviewer] [📊 Analyst]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
User: [tap 💻 Coder]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bridge: 3️⃣ Một điều QUAN TRỌNG nhất cần biết?
        
        Ví dụ:
        • "Không được sửa /payments"
        • "Luôn tạo PR, không push thẳng main"
        • "Test coverage phải > 80%"
        • Hoặc gõ "skip" nếu chưa có gì

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
User: Không push thẳng lên main, luôn tạo PR

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bridge: ✅ Agent "coder-my-app" sẵn sàng!
        
        📋 Profile khởi tạo:
        ├─ Role: Senior Coder
        ├─ Project: ~/projects/my-app
        ├─ Stack: Next.js · TypeScript · Prisma
        ├─ Rule cứng: không push thẳng main
        └─ Skills: /review /test /commit
        
        💡 Profile sẽ tự hoàn thiện qua thời gian.
        
        Giao việc đầu tiên ngay đi:
        "Fix the login bug in auth module"
```

---

## Project Scanner

Khi nhận được project path, Bridge chạy analyzer:

```python
class ProjectScanner:
    def scan(self, path: str) -> ProjectContext:
        return ProjectContext(
            stack=self._detect_stack(path),
            conventions=self._detect_conventions(path),
            structure=self._detect_structure(path),
            existing_docs=self._read_existing_docs(path),
        )
    
    def _detect_stack(self, path):
        # package.json → JS/TS frameworks
        # requirements.txt / pyproject.toml → Python
        # go.mod → Go
        # Dockerfile → container setup
        # docker-compose.yml → services (postgres, redis...)
        pass
    
    def _detect_conventions(self, path):
        # .eslintrc → JS linting rules
        # .prettierrc → formatting
        # pyproject.toml [tool.ruff] → Python linting
        # .github/workflows → CI commands
        # Makefile → build commands
        pass
    
    def _detect_structure(self, path):
        # Top-level dirs → project architecture
        # Test dirs → testing setup
        # Docs dirs → documentation
        pass
    
    def _read_existing_docs(self, path):
        # README.md → project overview
        # CLAUDE.md nếu đã có → kế thừa
        # docs/ → additional context
        pass
```

---

## Generated Profile từ Onboarding

```yaml
name: coder-my-app
version: 1
created: 2026-03-25
base_template: coder-fullstack

identity:
  role: coder
  project: ~/projects/my-app

context:
  stack: [nextjs, typescript, prisma]    # auto-detected
  key_dirs: [src/, tests/, prisma/]      # auto-detected
  critical_files: []                     # empty — sẽ fill dần

rules:
  hard:
    - "Không push thẳng main — luôn tạo PR"   # từ câu hỏi 3
  soft: []                                      # empty — sẽ learn dần

tools:
  mcp_servers: [filesystem, github]     # detect từ stack
  bash_blocklist:
    - "git push origin main"            # từ hard rule

skills: [review, test, commit]

memory:
  learned_patterns: []
  frequent_tasks: []
  known_issues: []
```

---

## Quick Spawn (bypass onboarding)

Cho advanced users:

```
/spawn coder --project ~/my-app
/spawn researcher
/spawn devops --project ~/infra --name "infra-agent"
```

Bridge dùng default template, không hỏi gì. Profile vẫn enhance theo thời gian.

---

## Post-onboarding: First Task UX

Sau khi tạo agent, Bridge guide user task đầu tiên:

```
Bridge: Agent sẵn sàng. Bạn có thể:
        
        Nói chuyện trực tiếp:
        → Gửi task bất kỳ ngay bây giờ
        
        Hoặc dùng slash commands:
        /review  → review code hiện tại
        /test    → chạy và fix tests
        /commit  → tạo commit
        
        Gõ /help để xem tất cả commands.
```
