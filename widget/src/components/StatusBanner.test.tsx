import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { StatusBanner } from "./StatusBanner";

describe("StatusBanner", () => {
  it("shows a clear offline message and returns to normal when online", () => {
    const offline = renderToStaticMarkup(<StatusBanner offline message="" />);
    const online = renderToStaticMarkup(<StatusBanner offline={false} message="" />);

    expect(offline).toContain("You’re offline");
    expect(online).toBe("");
  });
});
