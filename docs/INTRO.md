# Claude Bridge — Coding agent của bạn, gọi từ điện thoại

> Tài liệu giới thiệu cho developer / product người mới biết Claude Code. Phù hợp dùng làm blog post, README mở rộng hoặc opening của một slide deck.

---

## 1. Tại sao quan tâm Claude Code (và tại sao có claude-bridge)

Claude Code đang dần trở thành nền tảng mặc định cho coding agent — và bằng chứng không nằm ở blog hype, mà ở dòng tiền của hai cloud lớn nhất hành tinh đặt cược vào Anthropic, công ty đứng sau Claude.

Phía Amazon, AWS chuyển từ "đối tác đám mây" sang "primary cloud and training partner" của Anthropic. Khoản đầu tư đi qua ba đợt: $1.25B tháng 9/2023, +$2.75B tháng 3/2024, rồi +$4B tháng 11/2024 — tổng cộng **$8 tỷ** ([TechCrunch](https://techcrunch.com/2024/11/22/anthropic-raises-an-additional-4b-from-amazon-makes-aws-its-primary-cloud-partner/), [GeekWire](https://www.geekwire.com/2024/amazon-boosts-total-anthropic-investment-to-8b-deepens-ai-partnership-with-claude-maker/)). Tới 2026, Amazon công bố cam kết thêm **tối đa $25 tỷ** nữa để xây hạ tầng AI dùng chip Trainium/Inferentia ([CNBC](https://www.cnbc.com/2026/04/20/amazon-invest-up-to-25-billion-in-anthropic-part-of-ai-infrastructure.html), [Anthropic blog](https://www.anthropic.com/news/anthropic-amazon-trainium)).

Phía Google, lộ trình đầu tư còn dày hơn: $300M ban đầu năm 2023, +$2B cùng năm, thêm $1B đầu 2025 ([CNBC](https://www.cnbc.com/2025/01/22/google-agrees-to-new-1-billion-investment-in-anthropic.html)). Tháng 4/2026, Google công bố vòng tiếp theo có thể chạm **$40 tỷ** ($10B trả ngay, $30B theo milestone) ở mức định giá $380B của Anthropic ([Bloomberg](https://www.bloomberg.com/news/articles/2026-04-24/google-plans-to-invest-up-to-40-billion-in-anthropic), [TechCrunch](https://techcrunch.com/2026/04/24/google-to-invest-up-to-40b-in-anthropic-in-cash-and-compute/)). Hai cloud cùng đặt cược, và phần đáng chú ý của lợi nhuận AI quý gần nhất của Google + Amazon thực ra đến từ **stake trong Anthropic**, không phải sản phẩm AI tự xây ([Fortune](https://fortune.com/2026/04/30/google-amazon-ai-profits-anthropic-stake-bubble-earnings-2026/)).

Trong số sản phẩm Anthropic ship, Claude Code là cái đang lan nhanh nhất trong dev workflow — nó không chỉ là một chat UI mà là một bộ primitive: `--agent` để scope hành vi, `--session-id` để giữ ngữ cảnh, `isolation: worktree` để cô lập, Auto Memory để học pattern, Stop hook để báo xong việc, prompt caching để cắt chi phí. Mỗi cái đều mạnh. Nhưng để **nối chúng lại** thành workflow bạn thật sự muốn — agent riêng cho từng repo, retry-until-pass, lịch chạy hằng giờ, dispatch từ điện thoại — thì bạn vẫn phải tự nối tay, từng project một.

**claude-bridge là bộ nối đó.** Mục tiêu không phải thay thế Claude Code, mà giúp bạn dùng được hết các primitive của nó với một command, một câu chat, không phải mở terminal nữa.

---

## 2. claude-bridge là cái gì

Trong hai câu: claude-bridge là một **thin orchestrator** đứng giữa channel chat (Telegram hôm nay, Discord/Slack sắp có) và Claude Code CLI cục bộ. Bạn nhắn một câu vào bot, nó parse thành tool call, spawn `claude` đúng project, rồi ping ngược kết quả về cho bạn — y như có một con junior dev luôn sẵn sàng.

### High-level flow

```
[ User trên Telegram ] ⇄ [ Bridge MCP server ] ⇄ [ Claude Code agents ] ⇄ [ Project dirs ]
                                  │
                                  ├── Queue + Watcher (lifecycle các task đang chạy)
                                  ├── Loop + Schedule (orchestration nâng cao)
                                  └── Stop hook + Notification (báo xong việc)
```

### Các module high-level

- **Channel adapter (Telegram)** — Lớp ngoài cùng. Poll inbound message, đẩy vào session của bot, drain notification ngược ra. Lý do tồn tại: Claude Code chưa có UI di động native; bạn cần một cửa vào từ điện thoại mà không đụng terminal.
- **Bridge MCP server** — Đăng ký 24 tool (`bridge_dispatch`, `bridge_status`, `bridge_loop`, ...) cho Claude Code session của con bot gọi. Đây là lớp protocol giữa "ngôn ngữ tự nhiên người dùng nhập" và "lệnh hệ thống claude-bridge".
- **Agent registry** — Map `name → project_dir + model + purpose + tools`. Mỗi agent là một file `.claude/agents/bridge--{name}.md` đã có sẵn `isolation: worktree` và `memory: enabled`. Lý do tồn tại: bạn không phải `cd` qua lại giữa repo, không phải nhớ flag, chỉ cần nói tên agent.
- **Dispatcher + queue** — Spawn `claude` qua `Bun.spawn`, track PID, atomic check-and-create để task thứ hai trên cùng agent tự động xếp hàng thay vì giẫm lên nhau. Stop hook fire xong là dequeue tiếp.
- **Watcher** — Vòng polling 30 giây, fallback khi Stop hook không bắn (process bị kill cứng, máy reboot giữa task...). Đảm bảo state trong DB không kẹt mãi ở `running`.
- **Loop orchestrator + Evaluator** — Engine cho "retry-until-X". Bạn khai done-condition theo 5 kiểu (`command:`, `file_exists:`, `file_contains:`, `llm_judge:`, `manual:`), engine lo iteration, max-cost, max-iter, give-up sau N lỗi liên tiếp.
- **Scheduler** — Cron-lite: chạy task định kỳ (mỗi N phút), exponential backoff khi fail. Thiết kế để bạn gõ "every hour, sweep linter warnings" và quên nó đi.
- **Notification system** — Vòng 5 giây drain bảng notification từ SQLite, đẩy về channel. Tại sao cần lớp này: hook viết DB là một process khác với bot daemon, dùng SQLite WAL làm kênh chung là cách an toàn nhất.

Tất cả state nằm trong SQLite (`bridge.db`), survive reboot qua launchd (macOS) / systemd user unit (Linux). Cố ý chọn thin: phần lớn "công nghệ" đã có sẵn trong Claude Code — Bridge chỉ wire chúng lại.

---

## 3. Demo — ba use case thường gặp

### Demo 1: Dispatch một task đơn giản

> **You** *(Telegram)***:** backend, fix CI lỗi linting
>
> **Bot:** Dispatched to `backend`. Tôi sẽ ping khi xong.
>
> *(8 phút sau, bot tự nhắn lại)*
>
> **Bot:** ✅ `backend` xong rồi — sửa 14 lint error trong `src/api/*`, commit `fix(lint): resolve eslint warnings`. Cost $0.21.

Bên trong: bot parse intent → gọi `bridge_dispatch(agent="backend", prompt="fix CI lỗi linting")` → CLI spawn `claude --agent bridge--backend --session-id ... -p "fix CI..."` trong worktree riêng. Stop hook fire → DB cập nhật → notifier đẩy message về Telegram. Bạn không phải mở laptop.

### Demo 2: Multi-agent orchestration

Bạn có 2 agent: `news-analyst` (cho project đọc tin tài chính) và `vn-trader` (cho project sinh báo cáo). Cả hai dispatch song song, không đụng nhau vì khác `project_dir` khác `session_id`.

> **You:** news-analyst, tổng hợp news Fed tuần này. vn-trader, dựa trên output đó viết morning brief.
>
> **Bot:** Đã dispatch `news-analyst`. Khi xong sẽ chuyển tiếp prompt sang `vn-trader`.
>
> *(12 phút sau)*
>
> **Bot:** ✅ `news-analyst` xong → ghi `output/fed-week-summary.md`. Đang dispatch `vn-trader` với context đó.
>
> *(7 phút sau)*
>
> **Bot:** ✅ `vn-trader` xong → `output/morning-brief.md`, $0.34.

Mỗi agent có Auto Memory riêng nên `vn-trader` lần sau biết "à, news-analyst hay drop file vào `output/` ở repo bên kia" mà không cần bạn nhắc lại.

### Demo 3: Goal loop — "fix until tests pass"

> **You:** loop trên backend: fix all flaky tests, dừng khi `bun test` passed, max 5 vòng.
>
> **Bot:** Loop `abc12345` started. Done-condition: `command:bun test`. Iteration 1 đang chạy.
>
> **Bot:** Iter 1 xong (4m, $0.18). `bun test` exit 1 → tiếp iter 2.
>
> **Bot:** Iter 2 xong (3m, $0.15). `bun test` exit 1 → tiếp iter 3.
>
> **Bot:** ✅ Iter 3 xong (5m, $0.22). `bun test` exit 0. **Loop done.** Tổng 3 iter, $0.55.

Nếu bạn muốn human-in-the-loop, đổi thành `--done-when "manual:review trước khi tiếp"` — bot sẽ nhắn xin approve sau mỗi vòng. Nếu muốn LLM judge, dùng `llm_judge:Code có tests, error handling, và docs`. Cùng một dispatch path bên dưới, chỉ khác evaluator.

---

## 4. Pain points — sống chung với coding agent thật ra mệt thế nào

Phần này viết từ trải nghiệm gõ Claude Code mỗi ngày trong vài tháng — không phải brochure. Đây là những bottleneck đã đẩy mình tự build claude-bridge thay vì dùng nó như tool ra sẵn.

> **1. Phải ngồi nhìn terminal chạy**
> Trước khi có claude-bridge, mỗi prompt đưa vào Claude Code mình phải ngồi nhìn agent gõ. Chuyển tab sang Stack Overflow là sợ miss câu hỏi xác nhận. Task 20–30 phút như "review toàn bộ test suite" kéo cả buổi sáng — không phải vì nó lâu, mà vì mình bị chôn ở ghế. Bridge giải quyết bằng dispatch + notification: gõ task xong đi pha cà phê, agent xong nó ping qua Telegram. Mình không còn là người babysit nữa.

> **2. Switch context giữa các project**
> Mỗi coding agent cần biết file paths, env vars, git state đúng của project nó đang vào. Mỗi lần đổi repo là một lần `cd`, một lần check `git status`, một lần load lại memory. Bridge gắn agent vào `project_dir` cố định và cô lập bằng `isolation: worktree` — lệnh `backend, ...` luôn vào đúng `~/projects/my-api`, không bao giờ ngẫu nhiên dính vào repo khác đang mở.

> **3. Long-running task không có progress**
> Loop `claude` 10–30 phút mà không có tín hiệu giữa chừng là cảm giác như commit blind. Bridge có watcher 30s và per-iteration notify cho loop, nên mỗi vòng lặp bạn đều thấy "iter 2 xong, exit 1, đang chạy iter 3". Khi nào nên hủy, khi nào nên đợi — ra quyết định trên dữ liệu thật chứ không phải linh tính.

> **4. Tool refusal / policy error giữa task**
> Agent đang chạy thì gặp một command bị policy chặn, fail giữa chừng, và bạn mất state. Bridge log đầy đủ exit code + cost mỗi lần fail; bạn có thể retry với prompt narrower (tránh đụng tool đó) mà không mất Auto Memory đã tích luỹ. Quan trọng hơn: cost lần fail cũng được tính — không bị hidden cost.

> **5. Cost monitoring**
> Claude Code in cost từng invocation ra stdout, nhưng nếu bạn chạy 30 task/ngày thì tự cộng tay là không tưởng. Bridge parse `total_cost_usd` từ `--output-format json` mỗi task, aggregate theo agent / loop / period. *"how much have I spent this week?"* trả lời được bằng một câu chat. Chi phí không còn là ẩn số đến cuối tháng.

> **6. Multi-agent coordination**
> Khi cần 3–4 agent chạy song song (research + code + review), Claude Code không có UI tự nhiên cho việc đó — bạn phải mở 3 tmux pane. Bridge có queue + status tracking, nên *"status"* hiển thị "backend (running, 2m), news-analyst (queued), vn-trader (idle)" trong một câu reply. Cảm giác giống dashboard hơn là 3 con cú nhồi vào cùng terminal.

> **7. Mobile interaction**
> Claude Code chỉ chạy trên máy có terminal. Đi cafe, đi họp, đi bộ — bạn không bấm `claude -p` được. Bridge qua Telegram nên dispatch / check status / approve tool call đều làm từ điện thoại. Lần đầu mình gõ "kill backend" trên metro vì agent đang đốt $ vô ích là lúc thấy giá trị thật của lớp channel này.

> **8. Loop control**
> Tự viết "repeat until tests pass" bằng shell script là dễ vô hạn loop — quên break điều kiện, agent cứ commit chồng commit. Bridge có max_iterations, max_cost, manual approve mode, và auto give-up sau N consecutive failures. Bạn khai ý định ("fix until X, max $5"), engine lo phần kỷ luật. Đây là phần claude-bridge rộng hơn Claude Code raw nhất — nó gắn safety rails lên một cái primitive vốn rất "dài tay".

---

## What's next

- Đọc kiến trúc layer-by-layer ở [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — data model, runtime flow (dispatch / stop hook / loop iter / schedule tick / MCP call / startup), extension points.
- Setup nhanh trong 60 giây xem [`README.md`](../README.md) — install + scaffold bot + nói chuyện qua Telegram.
- Source code: [github.com/hieutrtr/claude-bridge](https://github.com/hieutrtr/claude-bridge). Issue & PR welcome.

claude-bridge không cố thay Claude Code — nó chỉ kéo các primitive đã tốt sẵn ra khỏi terminal, đặt lên đầu ngón tay bạn ở bất cứ đâu có sóng. Đó là toàn bộ idea.
