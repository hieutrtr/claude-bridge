/**
 * W3.5b: Markdown → Telegram HTML converter.
 */
import { describe, test, expect } from "bun:test";
import { mdToTelegramHtml } from "../../src/channel/telegram/markdown-to-html.js";
import { TelegramFormatter, chunkHtml } from "../../src/channel/telegram/format.js";

describe("mdToTelegramHtml", () => {
  test("bold (** and __)", () => {
    expect(mdToTelegramHtml("**Business / Khởi nghiệp**")).toBe("<b>Business / Khởi nghiệp</b>");
    expect(mdToTelegramHtml("__bold__")).toBe("<b>bold</b>");
  });

  test("italic (single * and _) does not eat snake_case", () => {
    expect(mdToTelegramHtml("*emphasis*")).toBe("<i>emphasis</i>");
    expect(mdToTelegramHtml("_emphasis_")).toBe("<i>emphasis</i>");
    expect(mdToTelegramHtml("snake_case_var stays")).toBe("snake_case_var stays");
  });

  test("nested bold + italic", () => {
    expect(mdToTelegramHtml("**_both_**")).toBe("<b><i>both</i></b>");
  });

  test("strikethrough", () => {
    expect(mdToTelegramHtml("~~old~~")).toBe("<s>old</s>");
  });

  test("inline code escapes HTML", () => {
    expect(mdToTelegramHtml("`a < b & c`")).toBe("<code>a &lt; b &amp; c</code>");
  });

  test("fenced code block with language", () => {
    const md = "```ts\nconst x = 1;\n```";
    expect(mdToTelegramHtml(md)).toBe('<pre><code class="language-ts">const x = 1;</code></pre>');
  });

  test("fenced code preserves markdown markers literally", () => {
    const md = "```\n**not bold**\n```";
    expect(mdToTelegramHtml(md)).toContain("**not bold**");
    expect(mdToTelegramHtml(md)).not.toContain("<b>");
  });

  test("headings → bold (all levels)", () => {
    expect(mdToTelegramHtml("# H1")).toBe("<b>H1</b>");
    expect(mdToTelegramHtml("## H2")).toBe("<b>H2</b>");
    expect(mdToTelegramHtml("###### H6")).toBe("<b>H6</b>");
  });

  test("unordered list → bullets", () => {
    const out = mdToTelegramHtml("- one\n- two");
    expect(out).toBe("• one\n• two");
  });

  test("ordered list keeps numbering", () => {
    const out = mdToTelegramHtml("1. first\n2. second");
    expect(out).toBe("1. first\n2. second");
  });

  test("blockquote", () => {
    expect(mdToTelegramHtml("> quoted")).toBe("<blockquote>quoted</blockquote>");
    expect(mdToTelegramHtml("> a\n> b")).toBe("<blockquote>a\nb</blockquote>");
  });

  test("link → anchor with escaped attr", () => {
    expect(mdToTelegramHtml("[text](https://x.com)")).toBe(
      '<a href="https://x.com">text</a>',
    );
    expect(mdToTelegramHtml('[t](https://x.com?a=1&b=2)')).toContain("&amp;");
  });

  test("image alt is preserved as text", () => {
    expect(mdToTelegramHtml("![alt](http://x/y.png)")).toBe("[image: alt]");
  });

  test("escapes raw HTML in user text", () => {
    expect(mdToTelegramHtml("a < b > c & d")).toBe("a &lt; b &gt; c &amp; d");
  });

  test("hr renders as separator", () => {
    expect(mdToTelegramHtml("---")).toBe("———");
  });

  test("collapses excessive newlines", () => {
    expect(mdToTelegramHtml("a\n\n\n\nb")).toBe("a\n\nb");
  });

  test("real-world example: header + bullets + code + bold", () => {
    const md = [
      "## Tổng quan",
      "",
      "**Business / Khởi nghiệp**",
      "- Item 1",
      "- Item 2 với `bridge dispatch`",
      "",
      "```ts",
      "const x = 1;",
      "```",
    ].join("\n");
    const out = mdToTelegramHtml(md);
    expect(out).toContain("<b>Tổng quan</b>");
    expect(out).toContain("<b>Business / Khởi nghiệp</b>");
    expect(out).toContain("• Item 1");
    expect(out).toContain("<code>bridge dispatch</code>");
    expect(out).toContain('<pre><code class="language-ts">const x = 1;</code></pre>');
  });

  test("does not mangle italic inside word boundaries", () => {
    expect(mdToTelegramHtml("a*b*c stays untouched")).toContain("a*b*c");
  });

  test("empty input returns empty string", () => {
    expect(mdToTelegramHtml("")).toBe("");
  });
});

describe("TelegramFormatter primitives", () => {
  const f = new TelegramFormatter();

  test("formatInlineCode escapes content", () => {
    expect(f.formatInlineCode("a < b")).toBe("<code>a &lt; b</code>");
  });

  test("formatBlockquote: expandable variant", () => {
    expect(f.formatBlockquote("hi", true)).toBe("<blockquote expandable>hi</blockquote>");
    expect(f.formatBlockquote("hi")).toBe("<blockquote>hi</blockquote>");
  });

  test("escapeAttr also escapes quotes", () => {
    expect(f.escapeAttr('a"b')).toBe("a&quot;b");
  });

  test("fromMarkdown delegates to converter", () => {
    expect(f.fromMarkdown("**x**")).toBe("<b>x</b>");
  });
});

describe("chunkHtml", () => {
  test("returns single chunk when below limit", () => {
    expect(chunkHtml("hello", 100)).toEqual(["hello"]);
  });

  test("splits at newline boundaries when possible", () => {
    const text = "aaaa\n\nbbbb\n\ncccc";
    const chunks = chunkHtml(text, 6);
    // Each chunk should be ≤ limit and content preserved.
    for (const c of chunks) expect(c.length).toBeLessThanOrEqual(6);
    expect(chunks.join("")).toContain("aaaa");
    expect(chunks.join("")).toContain("bbbb");
  });

  test("keeps small <pre> block intact alongside text", () => {
    const text = "Intro text.\n<pre><code>a()</code></pre>\nOutro.";
    const chunks = chunkHtml(text, 1000);
    expect(chunks).toEqual([text]);
  });

  test("oversized <blockquote> splits with reopened tag", () => {
    const inner = "line1\nline2\nline3\nline4\nline5";
    const text = `<blockquote>${inner}</blockquote>`;
    const chunks = chunkHtml(text, 40);
    // Every chunk must be a complete blockquote element.
    for (const c of chunks) {
      expect(c.startsWith("<blockquote>")).toBe(true);
      expect(c.endsWith("</blockquote>")).toBe(true);
    }
  });

  test("oversized <pre><code class=...> retains language wrapper across splits", () => {
    const inner = "line1\nline2\nline3\nline4\nline5\nline6";
    const text = `<pre><code class="language-ts">${inner}</code></pre>`;
    const chunks = chunkHtml(text, 50);
    for (const c of chunks) {
      expect(c.startsWith('<pre><code class="language-ts">')).toBe(true);
      expect(c.endsWith("</code></pre>")).toBe(true);
    }
  });
});
