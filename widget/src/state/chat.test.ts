import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "../api/client";
import type { SseEvent } from "../api/types";
import { streamWithSession } from "./chat";
import { SessionManager } from "./session";

const sessionToken = "mock_session_token_123456789012345678901234";

function streamResponse(): Response {
  const frame = [
    'event: meta\ndata: {"request_id":"00000000-0000-0000-0000-000000000001","release":null,"path":"content","intent":[],"links":{},"degraded":false}\n\n',
    'event: delta\ndata: {"t":"Hello"}\n\n',
    'event: done\ndata: {"finish":"stop","actions":[],"degraded":false}\n\n',
  ].join("");
  return new Response(frame, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("streamWithSession", () => {
  it("refreshes an expired session once and retries the same message", async () => {
    let sessionCalls = 0;
    let chatCalls = 0;
    const fetcher: typeof fetch = async (input) => {
      const url = input.toString();
      if (url.endsWith("/api/v1/sessions")) {
        sessionCalls += 1;
        const token = `${sessionToken.slice(0, -1)}${sessionCalls}`;
        return Response.json({ session_token: token, expires_in_minutes: 30 });
      }
      chatCalls += 1;
      if (chatCalls === 1) {
        return Response.json(
          { error: { code: "invalid_or_expired_session" } },
          { status: 401 },
        );
      }
      return streamResponse();
    };
    const api = createApiClient("https://api.example.invalid", fetcher);
    const events: SseEvent[] = [];
    const result = await streamWithSession(
      api,
      new SessionManager(),
      "How do I apply?",
      new AbortController().signal,
      (event) => events.push(event),
    );

    expect(result.completed).toBe(true);
    expect(sessionCalls).toBe(2);
    expect(chatCalls).toBe(2);
    expect(events.map((event) => event.event)).toEqual(["meta", "delta", "done"]);
  });

  it("keeps a failed network request explicit", async () => {
    const fetcher: typeof fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const api = createApiClient("https://api.example.invalid", fetcher);

    await expect(api.getConfig()).rejects.toThrow("Failed to fetch");
  });
});
