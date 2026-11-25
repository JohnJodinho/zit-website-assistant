import { beforeEach, describe, expect, it, vi } from "vitest";
import { installLoader } from "./loader";

const apiUrl = "https://api.example.invalid";
const widgetUrl = "https://widget.example.invalid";

function configResponse(enabled = true): Response {
  return Response.json({
    enabled,
    rollout_percent: 100,
    maintenance_message: "",
    privacy_notice: "Do not enter personal or confidential information.",
  });
}

describe("installLoader", () => {
  beforeEach(() => {
    document.body.replaceChildren();
    window.sessionStorage.clear();
  });

  it("shows a launcher in an isolated Shadow DOM and waits to create its iframe", async () => {
    const handle = await installLoader({
      document,
      window,
      apiUrl,
      widgetUrl,
      position: "right",
      fetcher: async () => configResponse(),
    });

    expect(handle).not.toBeNull();
    expect(handle?.host.shadowRoot?.querySelector(".launcher")).not.toBeNull();
    expect(handle?.host.shadowRoot?.querySelector("style")).not.toBeNull();
    expect(document.querySelector(".launcher")).toBeNull();
    expect(handle?.iframe).toBeNull();
  });

  it("creates a sandboxed iframe on open and returns focus on a valid close message", async () => {
    const handle = await installLoader({
      document,
      window,
      apiUrl,
      widgetUrl,
      position: "right",
      fetcher: async () => configResponse(),
    });
    const launcher = handle?.launcher;
    expect(launcher).toBeDefined();
    launcher?.click();

    const iframe = handle?.iframe;
    if (!iframe) throw new Error("The loader did not create an iframe.");
    expect(iframe?.getAttribute("sandbox")).toBe("allow-scripts allow-same-origin allow-popups");
    expect(iframe?.hasAttribute("allow")).toBe(false);
    expect(iframe?.getAttribute("referrerpolicy")).toBe("no-referrer");

    window.dispatchEvent(new MessageEvent("message", {
      data: { type: "zit:close" },
      origin: widgetUrl,
      source: iframe.contentWindow,
    }));

    expect(launcher?.hidden).toBe(false);
    expect(handle?.host.shadowRoot?.activeElement).toBe(launcher);
    handle?.destroy();
  });

  it("ignores messages from an unexpected origin", async () => {
    const handle = await installLoader({
      document,
      window,
      apiUrl,
      widgetUrl,
      position: "right",
      fetcher: async () => configResponse(),
    });
    handle?.launcher.click();
    const iframe = handle?.iframe;
    if (!iframe) throw new Error("The loader did not create an iframe.");

    window.dispatchEvent(new MessageEvent("message", {
      data: { type: "zit:close" },
      origin: "https://attacker.example",
      source: iframe.contentWindow,
    }));

    expect(handle?.host.shadowRoot?.querySelector(".frame-shell")?.hasAttribute("hidden")).toBe(false);
    handle?.destroy();
  });

  it("shows the dismissible teaser once after the delay", async () => {
    vi.useFakeTimers();
    const handle = await installLoader({
      document,
      window,
      apiUrl,
      widgetUrl,
      position: "right",
      fetcher: async () => configResponse(),
    });

    await vi.advanceTimersByTimeAsync(8_000);
    const teaser = handle?.host.shadowRoot?.querySelector(".teaser");
    expect(teaser?.hasAttribute("hidden")).toBe(false);
    teaser?.querySelector("button")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(teaser?.hasAttribute("hidden")).toBe(true);
    expect(window.sessionStorage.getItem("zit-widget-teaser-dismissed")).toBe("true");
    handle?.destroy();
    vi.useRealTimers();
  });

  it("does not render a launcher when the assistant is disabled", async () => {
    const handle = await installLoader({
      document,
      window,
      apiUrl,
      widgetUrl,
      position: "right",
      fetcher: async () => configResponse(false),
    });

    expect(handle).toBeNull();
    expect(document.querySelector("[data-zit-assistant-loader]")).toBeNull();
  });

  it("leaves no launcher when the host config endpoint is unreachable", async () => {
    const fetcher: typeof fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });

    await expect(installLoader({
      document,
      window,
      apiUrl,
      widgetUrl,
      position: "right",
      fetcher,
    })).rejects.toThrow("Failed to fetch");
    expect(document.querySelector("[data-zit-assistant-loader]")).toBeNull();
  });
});
