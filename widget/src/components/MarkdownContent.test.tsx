import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MarkdownContent } from "./MarkdownContent";

describe("MarkdownContent", () => {
  it("does not render raw HTML or unsafe link destinations", () => {
    const html = renderToStaticMarkup(
      <MarkdownContent content={'<script>window.secret = "bad"</script>\n\n[unsafe](javascript:alert(1))\n\n[safe](https://example.invalid/path)'} />,
    );

    expect(html).not.toContain("<script>");
    expect(html).not.toContain("javascript:");
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain("https://example.invalid/path");
  });
});
