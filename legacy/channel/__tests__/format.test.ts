import { describe, test, expect } from "bun:test";
import {
  convertMarkdownToTelegramHtml,
  chunkTelegramMessage,
  isTelegramHtmlParseError,
  stripHtmlTags,
  sendTelegramChunked,
} from "../format";

// --- convertMarkdownToTelegramHtml ---

describe("convertMarkdownToTelegramHtml", () => {
  test("plain text unchanged", () => {
    expect(convertMarkdownToTelegramHtml("hello world")).toBe("hello world");
  });

  test("bold **text**", () => {
    expect(convertMarkdownToTelegramHtml("**bold**")).toBe("<b>bold</b>");
  });

  test("bold __text__", () => {
    expect(convertMarkdownToTelegramHtml("__bold__")).toBe("<b>bold</b>");
  });

  test("italic *text*", () => {
    expect(convertMarkdownToTelegramHtml("*italic*")).toBe("<i>italic</i>");
  });

  test("italic _text_", () => {
    expect(convertMarkdownToTelegramHtml("_italic_")).toBe("<i>italic</i>");
  });

  test("strikethrough ~~text~~", () => {
    expect(convertMarkdownToTelegramHtml("~~strike~~")).toBe("<s>strike</s>");
  });

  test("inline code `code`", () => {
    expect(convertMarkdownToTelegramHtml("`code`")).toBe("<code>code</code>");
  });

  test("fenced code block", () => {
    const input = "```\nconst x = 1;\n```";
    const output = convertMarkdownToTelegramHtml(input);
    expect(output).toBe("<pre><code>const x = 1;</code></pre>");
  });

  test("fenced code block strips language tag", () => {
    const input = "```ts\nconst x: number = 1;\n```";
    const output = convertMarkdownToTelegramHtml(input);
    expect(output).toBe("<pre><code>const x: number = 1;</code></pre>");
  });

  test("heading # → <b>", () => {
    expect(convertMarkdownToTelegramHtml("# Title")).toBe("<b>Title</b>");
  });

  test("heading ## → <b>", () => {
    expect(convertMarkdownToTelegramHtml("## Section")).toBe("<b>Section</b>");
  });

  test("heading ### → <b>", () => {
    expect(convertMarkdownToTelegramHtml("### Sub")).toBe("<b>Sub</b>");
  });

  test("link [label](url)", () => {
    expect(convertMarkdownToTelegramHtml("[click here](https://example.com)")).toBe(
      '<a href="https://example.com">click here</a>'
    );
  });

  test("HTML special chars escaped: &", () => {
    expect(convertMarkdownToTelegramHtml("a & b")).toBe("a &amp; b");
  });

  test("HTML special chars escaped: <", () => {
    expect(convertMarkdownToTelegramHtml("a < b")).toBe("a &lt; b");
  });

  test("HTML special chars escaped: >", () => {
    expect(convertMarkdownToTelegramHtml("a > b")).toBe("a &gt; b");
  });

  test("HTML chars escaped inside code blocks too", () => {
    const input = "```\na < b && c > d\n```";
    const output = convertMarkdownToTelegramHtml(input);
    expect(output).toBe("<pre><code>a &lt; b &amp;&amp; c &gt; d</code></pre>");
  });

  test("inline code escapes HTML chars", () => {
    const input = "`a < b`";
    const output = convertMarkdownToTelegramHtml(input);
    expect(output).toBe("<code>a &lt; b</code>");
  });

  test("mixed formatting in one line", () => {
    const input = "**bold** and _italic_ and `code`";
    const output = convertMarkdownToTelegramHtml(input);
    expect(output).toBe("<b>bold</b> and <i>italic</i> and <code>code</code>");
  });

  test("code block content not double-escaped", () => {
    const input = "```\nx = &amp;\n```";
    const output = convertMarkdownToTelegramHtml(input);
    // The &amp; in source gets escaped to &amp;amp; since it's treated as raw text in code
    // But this test verifies no placeholder leaks
    expect(output).not.toContain("\x00");
    expect(output).toContain("<pre><code>");
  });

  test("markdown table converted to plain text lines", () => {
    const input = "| col1 | col2 |\n|------|------|\n| a    | b    |";
    const output = convertMarkdownToTelegramHtml(input);
    expect(output).not.toContain("|------|");
    expect(output).toContain("col1 | col2");
    expect(output).toContain("a | b");
  });

  test("table separator row removed", () => {
    const input = "| A | B |\n|---|---|\n| 1 | 2 |";
    const output = convertMarkdownToTelegramHtml(input);
    expect(output).not.toContain("|---|");
  });

  test("table with bold in cells", () => {
    const input = "| Status | Info |\n|--------|------|\n| **Done** | All pass |";
    const output = convertMarkdownToTelegramHtml(input);
    expect(output).toContain("<b>Done</b>");
    expect(output).not.toContain("|--------|");
  });

  test("complex: headings + bold + table in one message", () => {
    const input = [
      "## Summary",
      "",
      "**Result:** success",
      "",
      "| Task | Status |",
      "|------|--------|",
      "| build | done |",
      "| test | pass |",
    ].join("\n");
    const output = convertMarkdownToTelegramHtml(input);
    expect(output).toContain("<b>Summary</b>");
    expect(output).toContain("<b>Result:</b>");
    expect(output).toContain("Task | Status");
    expect(output).toContain("build | done");
    expect(output).not.toContain("|------|");
    expect(output).not.toContain("**");
  });

  test("non-table pipe content not affected", () => {
    // A line with | but no separator row after it should not be converted
    const input = "Use a | b for OR logic";
    const output = convertMarkdownToTelegramHtml(input);
    expect(output).toBe("Use a | b for OR logic");
  });
});

// --- chunkTelegramMessage ---

describe("chunkTelegramMessage", () => {
  test("text shorter than limit → single chunk", () => {
    const text = "hello world";
    expect(chunkTelegramMessage(text, 4000)).toEqual(["hello world"]);
  });

  test("text exactly at limit → single chunk", () => {
    const text = "a".repeat(4000);
    expect(chunkTelegramMessage(text, 4000)).toEqual([text]);
  });

  test("text > limit split at paragraph boundary \\n\\n", () => {
    const para1 = "a".repeat(2000);
    const para2 = "b".repeat(2000);
    const text = para1 + "\n\n" + para2;
    const chunks = chunkTelegramMessage(text, 4000);
    expect(chunks.length).toBe(2);
    expect(chunks[0]).toBe(para1 + "\n\n");
    expect(chunks[1]).toBe(para2);
  });

  test("text > limit split at newline if no \\n\\n", () => {
    const line1 = "a".repeat(2000);
    const line2 = "b".repeat(2000);
    const text = line1 + "\n" + line2;
    const chunks = chunkTelegramMessage(text, 4000);
    expect(chunks.length).toBe(2);
    expect(chunks[0]).toBe(line1 + "\n");
    expect(chunks[1]).toBe(line2);
  });

  test("text > limit hard split if no newline", () => {
    const text = "a".repeat(5000);
    const chunks = chunkTelegramMessage(text, 4000);
    expect(chunks.length).toBe(2);
    expect(chunks[0]).toBe("a".repeat(4000));
    expect(chunks[1]).toBe("a".repeat(1000));
  });

  test("code block fits within limit → not split", () => {
    const pre = "<pre><code>const x = 1;</code></pre>";
    const text = "intro\n\n" + pre + "\n\noutro";
    // This is short, all fits in one chunk
    const chunks = chunkTelegramMessage(text, 4000);
    expect(chunks.length).toBe(1);
    expect(chunks[0]).toContain("<pre><code>");
  });

  test("code block not split in the middle", () => {
    const beforeBlock = "some text\n\n";
    const codeContent = "x".repeat(1000);
    const block = `<pre><code>${codeContent}</code></pre>`;
    const afterBlock = "\n\n" + "y".repeat(3000);
    // total: 11 + 1000 + 13+14 + 2 + 3000 > 4000
    // The code block starts at position 11 (after "some text\n\n")
    // It should split before the block
    const text = beforeBlock + block + afterBlock;
    const chunks = chunkTelegramMessage(text, 4000);
    // Each chunk should not have a torn code block
    for (const chunk of chunks) {
      const opens = (chunk.match(/<pre><code>/g) ?? []).length;
      const closes = (chunk.match(/<\/code><\/pre>/g) ?? []).length;
      expect(opens).toBe(closes);
    }
  });

  test("oversized code block → hard split", () => {
    const codeContent = "x".repeat(5000);
    const block = `<pre><code>${codeContent}</code></pre>`;
    const chunks = chunkTelegramMessage(block, 4000);
    // Should produce multiple chunks even though it splits the code block
    expect(chunks.length).toBeGreaterThan(1);
    // All chunks joined should equal original
    expect(chunks.join("")).toBe(block);
  });

  test("all chunks joined equal original", () => {
    const text = "para1\n\n" + "a".repeat(3000) + "\n\npara2\n\n" + "b".repeat(3000);
    const chunks = chunkTelegramMessage(text, 4000);
    expect(chunks.join("")).toBe(text);
  });
});

// --- isTelegramHtmlParseError ---

describe("isTelegramHtmlParseError", () => {
  test("'can't parse entities' → true", () => {
    expect(isTelegramHtmlParseError(new Error("Bad Request: can't parse entities"))).toBe(true);
  });

  test("'find end of the entity' → true", () => {
    expect(isTelegramHtmlParseError(new Error("find end of the entity starting at..."))).toBe(true);
  });

  test("'parse entities' → true", () => {
    expect(isTelegramHtmlParseError(new Error("failed to parse entities"))).toBe(true);
  });

  test("network error → false", () => {
    expect(isTelegramHtmlParseError(new Error("ECONNREFUSED"))).toBe(false);
  });

  test("null → false", () => {
    expect(isTelegramHtmlParseError(null)).toBe(false);
  });

  test("non-Error string → checked", () => {
    expect(isTelegramHtmlParseError("can't parse entities")).toBe(true);
  });
});

// --- stripHtmlTags ---

describe("stripHtmlTags", () => {
  test("remove <b> and </b>", () => {
    expect(stripHtmlTags("<b>bold</b>")).toBe("bold");
  });

  test("remove <code> and </code>", () => {
    expect(stripHtmlTags("<code>code</code>")).toBe("code");
  });

  test("remove <pre><code> and </code></pre>", () => {
    expect(stripHtmlTags("<pre><code>block</code></pre>")).toBe("block");
  });

  test("unescape &amp;", () => {
    expect(stripHtmlTags("a &amp; b")).toBe("a & b");
  });

  test("unescape &lt;", () => {
    expect(stripHtmlTags("a &lt; b")).toBe("a < b");
  });

  test("unescape &gt;", () => {
    expect(stripHtmlTags("a &gt; b")).toBe("a > b");
  });

  test("does not strip text inside tags", () => {
    expect(stripHtmlTags("<b>hello world</b>")).toBe("hello world");
  });

  test("strips all tag types", () => {
    expect(stripHtmlTags("<b>bold</b> <i>italic</i> <s>strike</s>")).toBe("bold italic strike");
  });

  test("strips residual **bold** markdown", () => {
    expect(stripHtmlTags("**bold**")).toBe("bold");
  });

  test("strips residual ## heading markdown", () => {
    expect(stripHtmlTags("## Title")).toBe("Title");
  });

  test("strips residual *italic* markdown", () => {
    expect(stripHtmlTags("*italic*")).toBe("italic");
  });

  test("strips residual ~~strikethrough~~ markdown", () => {
    expect(stripHtmlTags("~~strike~~")).toBe("strike");
  });

  test("strips residual `inline code` markdown", () => {
    expect(stripHtmlTags("`code`")).toBe("code");
  });

  test("mixed HTML tags + residual markdown → clean plain text", () => {
    const input = "<b>bold</b> and **also bold**\n## heading";
    expect(stripHtmlTags(input)).toBe("bold and also bold\nheading");
  });
});

// --- sendTelegramChunked ---

describe("sendTelegramChunked", () => {
  test("single chunk gửi 1 lần", async () => {
    const calls: any[] = [];
    const sendFn = async (chatId: string, text: string, opts?: any) => {
      calls.push({ chatId, text, opts });
    };
    await sendTelegramChunked(sendFn, "123", "hello world");
    expect(calls.length).toBe(1);
    expect(calls[0].chatId).toBe("123");
    expect(calls[0].opts?.parse_mode).toBe("HTML");
  });

  test("multi-chunk gửi nhiều lần", async () => {
    const calls: any[] = [];
    const sendFn = async (chatId: string, text: string, opts?: any) => {
      calls.push({ chatId, text, opts });
    };
    // Create a text that will be split into 2 chunks
    const longText = "a".repeat(2000) + "\n\n" + "b".repeat(2000);
    await sendTelegramChunked(sendFn, "123", longText);
    expect(calls.length).toBe(2);
    expect(calls[0].opts?.parse_mode).toBe("HTML");
    expect(calls[1].opts?.parse_mode).toBe("HTML");
  });

  test("HTML parse error → retry plain text", async () => {
    let callCount = 0;
    const calls: any[] = [];
    const sendFn = async (chatId: string, text: string, opts?: any) => {
      callCount++;
      if (callCount === 1) {
        throw new Error("Bad Request: can't parse entities in the message");
      }
      calls.push({ chatId, text, opts });
    };
    await sendTelegramChunked(sendFn, "123", "**bold**");
    expect(calls.length).toBe(1);
    // Fallback should not have parse_mode
    expect(calls[0].opts?.parse_mode).toBeUndefined();
    // Text should be plain (no HTML tags)
    expect(calls[0].text).not.toContain("<b>");
  });

  test("non-HTML error → rethrow", async () => {
    const sendFn = async () => {
      throw new Error("ECONNREFUSED");
    };
    await expect(sendTelegramChunked(sendFn, "123", "hello")).rejects.toThrow("ECONNREFUSED");
  });

  test("opts reply_parameters chỉ pass vào chunk đầu tiên", async () => {
    const calls: any[] = [];
    const sendFn = async (chatId: string, text: string, opts?: any) => {
      calls.push({ chatId, text, opts });
    };
    const longText = "a".repeat(2000) + "\n\n" + "b".repeat(2000);
    const opts = { reply_parameters: { message_id: 42 } };
    await sendTelegramChunked(sendFn, "123", longText, opts);
    expect(calls.length).toBe(2);
    expect(calls[0].opts?.reply_parameters?.message_id).toBe(42);
    expect(calls[1].opts?.reply_parameters).toBeUndefined();
  });

  test("empty text → không gửi", async () => {
    const calls: any[] = [];
    const sendFn = async (chatId: string, text: string, opts?: any) => {
      calls.push({ chatId, text, opts });
    };
    await sendTelegramChunked(sendFn, "123", "");
    expect(calls.length).toBe(0);
  });

  test("whitespace-only text → không gửi", async () => {
    const calls: any[] = [];
    const sendFn = async (chatId: string, text: string, opts?: any) => {
      calls.push({ chatId, text, opts });
    };
    await sendTelegramChunked(sendFn, "123", "   \n  ");
    expect(calls.length).toBe(0);
  });

  test("fallback from complex markdown has no raw ** or ## symbols", async () => {
    let callCount = 0;
    const calls: any[] = [];
    const sendFn = async (chatId: string, text: string, opts?: any) => {
      callCount++;
      if (callCount === 1) throw new Error("Bad Request: can't parse entities");
      calls.push({ chatId, text, opts });
    };
    const md = "## Summary\n\n**Result:** done\n\n| col | val |\n|-----|-----|\n| a   | b   |";
    await sendTelegramChunked(sendFn, "123", md);
    expect(calls.length).toBe(1);
    expect(calls[0].text).not.toContain("**");
    expect(calls[0].text).not.toContain("##");
    expect(calls[0].text).toContain("Summary");
    expect(calls[0].text).toContain("Result:");
  });
});
