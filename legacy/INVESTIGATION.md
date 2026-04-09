# Investigation: Response/Output Length Limits

Date: 2026-04-07

Toàn bộ các chỗ giới hạn độ dài response/output trong codebase claude-bridge.

---

## 1. Telegram Message Chunking

**File:** `channel/format.ts` — Lines 8, 139–197

```typescript
const CHUNK_LIMIT = 4000;  // line 8
function chunkTelegramMessage(html, limit = 4000)  // line 139
```

- Telegram API giới hạn 4096 chars/message → code dùng 4000 để có buffer
- Logic split: ưu tiên `\n\n` (paragraph) → `\n` (line break) → hard split
- Fence-aware: không split trong `<pre><code>` blocks
- **Đây là giới hạn cứng từ Telegram API, không thể nới rộng hơn 4096**
- **Đề xuất:** Giữ nguyên

---

## 2. Loop Orchestrator — Nhiều lớp truncation

**File:** `src/claude_bridge/loop_orchestrator.py`

| Line(s) | Biến | Limit | Ghi chú |
|---------|------|-------|---------|
| 211–214 | stack trace | 2000 chars | `trace[:1997] + "..."` |
| 217–229 | feedback tổng | 2000 chars | `_truncate_feedback()` function |
| 254–255 | iteration summary | 500 chars | `summary[:500] + "...[truncated]"` |
| 269–274 | test failures | 5 items, trace 300 chars | `failures[:5]`, `trace[:300]` |
| 282 | feedback context | 2000 chars | Truyền vào claude prompt |
| 588 | result_summary | 1000 chars | `result_summary[:1000] + "...[truncated]"` |
| 718, 820 | error in finish_reason | 200 chars | `str(e)[:200]` |
| 909 | goal (loop list display) | 60 chars | UI display only |
| 935 | goal (loop history) | 80 chars | UI display only |
| 963 | iteration summary display | 100 chars | UI display only |

**Vấn đề nghiêm trọng:**
- Line 588: `result_summary` (kết quả thực tế từ claude) bị cắt ở **1000 chars** trước khi lưu vào DB → mất thông tin quan trọng
- Line 282: Feedback context bị cắt ở 2000 chars → context truyền cho vòng lặp tiếp theo bị incomplete

**Đề xuất:**
- Line 588: Tăng lên 10000 hoặc bỏ limit (kết quả task nên được giữ đầy đủ)
- Line 282: Tăng lên 5000 nếu context window cho phép

---

## 3. on_complete.py — Task Result Truncation

**File:** `src/claude_bridge/on_complete.py`

| Line(s) | Biến | Limit | Ghi chú |
|---------|------|-------|---------|
| 84 | sub-task summary (team mode) | 100 chars | Aggregation display |
| 92 | aggregated_summary | 500 chars | `aggregated_summary[:500]` |
| 225 | summary in report | 200 chars | `summary[:200]` |
| 230 | error in report | 200 chars | `error[:200]` |

**Vấn đề:**
- Line 225: Summary trong completion report chỉ 200 chars — quá ngắn cho kết quả task phức tạp
- Line 92: Aggregated summary 500 chars có thể mất nhiều sub-task results

**Đề xuất:**
- Line 225: Tăng lên 5000 chars
- Line 92: Tăng lên 2000 chars

---

## 4. notify.py — Notification Content Limits

**File:** `src/claude_bridge/notify.py`

| Line(s) | Biến | Limit | Ghi chú |
|---------|------|-------|---------|
| 74 | prompt display | 80 chars + first line only | `prompt[:80].split("\n")[0]` |
| 98 | result_summary trong notification | 2000 chars | `summary[:2000]` |
| 107 | error message | 500 chars | `error[:500]` |

**Nhận xét:**
- Line 98: 2000 chars cho summary là reasonable cho Telegram notification
- Line 74: Chỉ lấy first line của prompt → mất context nếu prompt multi-line (display only)
- Line 107: 500 chars cho error message — có thể quá ngắn nếu error có traceback dài

**Đề xuất:**
- Line 107: Tăng lên 1000 chars

---

## 5. MCP Tools — Tool Response Truncation

**File:** `src/claude_bridge/mcp_tools.py`

| Line(s) | Biến | Limit | Ghi chú |
|---------|------|-------|---------|
| 61, 72, 151 | task prompt trong history | 100 chars | `task["prompt"][:100]` |
| 155, 258–259 | result_summary trong details | 200 chars | `(t["result_summary"] or "")[:200]` |
| 346, 354 | loop goal | 200 chars | `entry["goal"][:200] + "...[truncated]"` |
| 431 | loop list goal | 100 chars | `(loop.get("goal") or "")[:100]` |
| 456, 518 | loop iteration summary | 200–300 chars | Display truncation |
| 627 | slug generation | 20 chars | Internal naming |

**Vấn đề nghiêm trọng:**
- Line 155, 258–259: `result_summary` trong MCP tool responses chỉ **200 chars** → Claude (bot) nhận được thông tin bị cắt khi query task status → Bot không thể hiểu task đã làm gì để reply lại user

**Đề xuất:**
- Line 155, 258–259: Tăng lên 5000 chars
- Line 61, 72, 151: Tăng lên 300 chars

---

## 6. watcher.py — Task Result Parsing

**File:** `src/claude_bridge/watcher.py`

| Line(s) | Biến | Limit | Ghi chú |
|---------|------|-------|---------|
| 50, 119, 129 | result parse | 500 chars | `str(result.get("result", ""))[:500]` |
| 189 | result_summary in report | 200 chars | Display |
| 193 | error_message in report | 200 chars | Display |

**Vấn đề:**
- Line 50, 119, 129: Khi watcher parse kết quả từ file JSON, chỉ lấy **500 chars** → **mất data khi lưu vào DB**
- Đây là fallback path (khi stop hook không trigger), nhưng vẫn bị truncate nghiêm trọng

**Đề xuất:**
- Line 50, 119, 129: Bỏ limit hoặc tăng lên 50000 chars (đây là lần đầu lưu vào DB)

---

## 7. telegram_loop.py — Loop Notifications

**File:** `src/claude_bridge/telegram_loop.py`

| Line(s) | Biến | Limit | Ghi chú |
|---------|------|-------|---------|
| 44–45 | goal trong progress | 80 chars | Display only |
| 45 | summary trong progress | 200 chars | Notification text |
| 86 | goal trong done | 80 chars | Display only |
| 147–148 | goal + summary trong approval | 80 + 300 chars | Approval request |
| 181 | goal trong started | 80 chars | Display only |

**Nhận xét:** Chỉ ảnh hưởng đến Telegram notification display, không ảnh hưởng data storage.
**Đề xuất:** Giữ nguyên (display only)

---

## 8. loop_evaluator.py — Evaluator Output

**File:** `src/claude_bridge/loop_evaluator.py`

| Line(s) | Biến | Limit | Ghi chú |
|---------|------|-------|---------|
| 189 | command output | 500 chars | Kết quả chạy command |
| 269 | LLM judge feedback | 3000 chars | `result_summary[:3000]` |
| 298, 310, 313 | error/ambiguous output | 100–200 chars | Parse errors |

**Đề xuất:**
- Line 189: Tăng lên 2000 chars

---

## 9. CLI Display — Display-only

**File:** `src/claude_bridge/cli.py`

Tất cả truncation trong CLI là display-only (terminal tables). Không ảnh hưởng data. Giữ nguyên.

---

## 10. dispatcher.py — Không có limit

**File:** `src/claude_bridge/dispatcher.py` — Lines 60–64

- Stdout/stderr ghi ra files trên disk, không có size limit
- Kết quả parse từ JSON files
- **Không có vấn đề ở đây**

---

## Tổng Hợp — Các Vấn Đề Ảnh Hưởng Data Integrity

Theo thứ tự ưu tiên (chỉ các chỗ ảnh hưởng đến dữ liệu thực, không chỉ display):

| Priority | File | Line(s) | Limit hiện tại | Đề xuất | Tác động |
|----------|------|---------|----------------|---------|---------|
| 🔴 Critical | `watcher.py` | 50, 119, 129 | 500 chars | Bỏ limit | Mất task result khi lưu DB qua watcher path |
| 🔴 Critical | `mcp_tools.py` | 155, 258–259 | 200 chars | 5000 chars | Bot nhận result bị cắt khi query task status |
| 🟠 High | `loop_orchestrator.py` | 588 | 1000 chars | 10000 chars | Mất kết quả task trong loop |
| 🟠 High | `on_complete.py` | 225 | 200 chars | 5000 chars | Completion report bị cắt |
| 🟡 Medium | `loop_orchestrator.py` | 282 | 2000 chars | 5000 chars | Loop feedback context incomplete |
| 🟡 Medium | `loop_evaluator.py` | 189 | 500 chars | 2000 chars | Command output bị cắt |
| 🟡 Medium | `notify.py` | 107 | 500 chars | 1000 chars | Error traceback bị cắt trong notification |
| 🟢 Low | `on_complete.py` | 92 | 500 chars | 2000 chars | Team aggregation summary bị cắt |
| 🟢 Low | `mcp_tools.py` | 61, 72, 151 | 100 chars | 300 chars | Task prompt trong history bị cắt |

---

## Không Có Vấn Đề

- `channel/format.ts`: Telegram chunking đúng và cần thiết (API hard limit 4096)
- `dispatcher.py`: Không có limit trên file I/O
- `cli.py`: Chỉ display, không ảnh hưởng data
- `telegram_loop.py`: Chỉ notification display
- `session.py`, `permission_relay.py`, `tmux_session.py`: Internal naming, không ảnh hưởng data
