import { describe, expect, it, vi } from "vitest";
import { ApiError, isApiLink, isHttpUrl } from "./types";
import { createApiClient } from "./client";

const sessionToken = "mock_session_token_123456789012345678901234";

describe("createApiClient", () => {
  it("uses an empty object to create a session when Turnstile is off", async () => {
    const fetcher: typeof fetch = async (_input, init) => {
      expect(init?.body).toBe("{}");
      return Response.json({ session_token: sessionToken, expires_in_minutes: 30 });
    };
    const api = createApiClient("https://api.example.invalid", fetcher);

    await expect(api.createSession()).resolves.toBe(sessionToken);
  });

  it("validates config responses instead of trusting network data", async () => {
    const api = createApiClient("https://api.example.invalid", async () =>
      Response.json({ enabled: "yes" }),
    );

    await expect(api.getConfig()).rejects.toThrow("invalid config response");
  });

  it.each([
    [409, "session_request_in_progress"],
    [413, "message_too_long"],
    [422, "validation_error"],
    [429, "chat_rate_limited"],
    [503, "database_unavailable"],
  ])("exposes the contract error for HTTP %s", async (status, code) => {
    const api = createApiClient("https://api.example.invalid", async () =>
      Response.json({ error: { code } }, {
        status,
        headers: { "X-Request-ID": "trace-reference" },
      }),
    );

    await expect(api.streamChat("question", sessionToken, new AbortController().signal))
      .rejects.toMatchObject({ status, code, traceId: "trace-reference" });
  });

  it("does not copy session tokens into error messages or logs", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const api = createApiClient("https://api.example.invalid", async () =>
      Response.json({ error: { code: "database_unavailable" } }, { status: 503 }),
    );

    let caught: unknown;
    try {
      await api.streamChat("question", sessionToken, new AbortController().signal);
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect(String(caught)).not.toContain(sessionToken);
    expect(log).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });
});

describe("URL validation", () => {
  it("allows only credential-free HTTP and HTTPS links", () => {
    expect(isHttpUrl("https://example.invalid/path")).toBe(true);
    expect(isHttpUrl("javascript:alert(1)")).toBe(false);
    expect(isHttpUrl("https://user:pass@example.invalid")).toBe(false);
  });

  it("rejects links with unsafe schemes before they reach link buttons", () => {
    expect(isApiLink({ label: "Unsafe", url: "javascript:alert(1)" })).toBe(false);
    expect(isApiLink({ label: "Apply", url: "https://example.invalid/apply" })).toBe(true);
  });
});
