# Claude Bridge — Brainstorm & Design Notes

## Session 1 — 2026-03-26

### Vision
Agent orchestration runtime dùng Claude Code làm execution engine.
Điều khiển từ Telegram/Discord/Slack qua Channels MCP.

### Key Decisions
- Telegram bot là control center (đơn giản nhất để start)
- Profile = living document, evolve qua thời gian
- CLAUDE.md được generate từ profile (không phải tách rời)
- Onboarding: 3 câu hỏi → đủ dùng ngay
- Enhancement: passive observe → suggest → user approve 1 tap

### Open Questions
- [ ] Data model của session log (signals để enhance)
- [ ] Cơ chế Bridge detect "user correction" trong conversation
- [ ] Multi-agent coordination: agents communicate với nhau thế nào?
- [ ] Session persistence strategy (tmux vs systemd vs pm2)
- [ ] Profile versioning — rollback nếu enhance làm hỏng?

### Next Steps
- [ ] Design session log schema
- [ ] Design /enhance command UI flow chi tiết
- [ ] Prototype project scanner
- [ ] Prototype CLAUDE.md generator
