# Claude Bridge 🌉

> Control your Claude Code agents from anywhere — via Telegram, Discord, or Slack.

Claude Bridge là một **agent orchestration runtime** cho phép bạn điều khiển Claude Code agents từ điện thoại thông qua Channels MCP. Không chỉ là chat interface — đây là một thực thể tự động hóa thực sự trên máy tính, dùng Claude Code làm execution engine với toàn bộ hệ sinh thái skills và MCP.

## Tại sao Claude Bridge?

| | OpenClaw / alternatives | Claude Bridge |
|---|---|---|
| Model | Models rẻ (Qwen, GLM...) | Claude Code — agent thực |
| Execution | Trả lời text | Chạy code, edit file, dùng tools |
| Skills/MCP | Không có | Toàn bộ hệ sinh thái Claude Code |
| Multi-agent | Khó config | `/spawn` là xong |
| Agent memory | Stateless | Profile tiến hóa theo thời gian |
| Setup | Phức tạp | Onboarding 3 câu hỏi |

## Kiến trúc

```
[Telegram / Discord / Slack]   ← Control Center (phone)
            ↕  Channels MCP
    [Claude Bridge Daemon]     ← Orchestration layer
       ↙        ↓        ↘
  [Agent 1]  [Agent 2]  [Agent 3]   ← mỗi agent = Claude Code session
  coder      researcher  reviewer      với profile + CLAUDE.md riêng
```

## Tính năng cốt lõi

### 🤖 Agent Modes
- **Mode 1 — Headless Task Runner**: Giao task → Bridge spawn subagents → nhận kết quả
- **Mode 2 — Persistent Agent**: Session sống lâu dài, trao đổi nhiều vòng, giữ context

### 🧬 Living Profiles
Profile không phải config tĩnh — nó **tiến hóa** qua 3 giai đoạn:
1. **Onboarding**: 3 câu hỏi, đủ dùng ngay
2. **Làm việc**: Bridge im lặng quan sát, tích lũy signals
3. **Tăng cường**: Tự động đề xuất improvements sau mỗi session

### 📄 Auto CLAUDE.md Generation
Bridge tự động:
- Scan project (stack, conventions, structure)
- Generate CLAUDE.md phù hợp với project thực tế
- Sync CLAUDE.md mỗi khi profile thay đổi
- Quản lý multi-layer: global → project → sub-directory

### ✅ Remote Permission Relay
- Agent cần approve tool call → ping Telegram
- Inline keyboard: ✅ Approve / ❌ Deny / 👁️ Xem trước
- Timeout tự động (configurable)

## Quick Start

```bash
# Install
pip install claude-bridge

# Start với Telegram
claude-bridge start --platform telegram

# Tạo agent mới (onboarding flow trên Telegram)
/new-agent

# Hoặc spawn trực tiếp
/spawn coder --project ~/my-app
```

## Project Structure

```
claude-bridge/
├── claude_bridge/
│   ├── daemon/          # Orchestration, agent lifecycle
│   ├── channels/        # MCP Channel plugins (Telegram, Discord, Slack)
│   └── cli/             # claude-bridge CLI
├── profiles/
│   └── templates/       # Preset profile templates
└── docs/                # Architecture & design decisions
```

## Roadmap

- [ ] Phase 1: Bridge daemon + Telegram channel
- [ ] Phase 2: Agent spawn + profile onboarding
- [ ] Phase 3: Profile enhancement engine
- [ ] Phase 4: CLAUDE.md auto-generation
- [ ] Phase 5: Multi-agent coordination
- [ ] Phase 6: Discord + Slack channels

## Status

🚧 **Early design phase** — Đang trong quá trình thiết kế kiến trúc.

---

*Built on top of [Claude Code Channels](https://code.claude.com/docs/en/channels-reference) — research preview feature requiring Claude Code v2.1.80+*
# claude-bridge
