import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ChatMeta } from "../api/types";
import { LinkButtons } from "./LinkButtons";
import { MarkdownContent } from "./MarkdownContent";

const bareUrlCases = [
  {
    text: "https://www.example.com/programmes",
    href: "https://www.example.com/programmes",
    label: "example.com/programmes",
  },
  {
    text: "https://example.com/programmes",
    href: "https://example.com/programmes",
    label: "example.com/programmes",
  },
  {
    text: "http://www.example.com/programmes",
    href: "http://www.example.com/programmes",
    label: "example.com/programmes",
  },
  {
    text: "www.example.com/programmes",
    href: "http://www.example.com/programmes",
    label: "example.com/programmes",
  },
];

describe("URL rendering without backend calls", () => {
  it.each(bareUrlCases)("auto-links and shortens $text", ({ text, href, label }) => {
    const html = renderToStaticMarkup(<MarkdownContent content={`Visit ${text}.`} />);

    expect(html).toContain(`href="${href}"`);
    expect(html).toContain(`>${label}<svg`);
    expect(html).not.toContain(`>${text}<svg`);
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain("</a>.</p>");
  });

  it("keeps an explicit Markdown label instead of replacing it with the URL", () => {
    const html = renderToStaticMarkup(
      <MarkdownContent content="[Course list](https://www.example.com/programmes)" />,
    );

    expect(html).toContain(">Course list<svg");
    expect(html).not.toContain(">example.com/programmes<svg");
  });

  it("keeps API-provided link labels and rejects unsafe Markdown destinations", () => {
    const meta: ChatMeta = {
      request_id: "00000000-0000-0000-0000-000000000001",
      release: null,
      path: "content",
      intent: [],
      links: {
        admissions: { label: "Contact admissions", url: "https://www.example.com/admissions" },
      },
      degraded: false,
    };
    const buttons = renderToStaticMarkup(<LinkButtons meta={meta} />);
    const unsafe = renderToStaticMarkup(
      <MarkdownContent content="[unsafe](javascript:alert(1)) and <mailto:admissions@example.com>" />,
    );

    expect(buttons).toContain(">Contact admissions<svg");
    expect(buttons).toContain('href="https://www.example.com/admissions"');
    expect(unsafe).not.toContain("javascript:");
    expect(unsafe).not.toContain('href="');
    expect(unsafe).not.toContain('class="markdown-link"');
  });
});
