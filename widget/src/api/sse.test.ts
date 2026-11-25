import { describe, expect, it, vi } from "vitest";
import { readSse } from "./sse";
import type { SseEvent } from "./types";

function responseFromChunks(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, { status: 200 });
}

const meta = {
  request_id: "00000000-0000-0000-0000-000000000001",
  release: null,
  path: "content",
  intent: ["courses"],
  links: {},
  degraded: false,
};

describe("readSse", () => {
  it("parses events split at arbitrary UTF-8 and CRLF boundaries", async () => {
    const text = [
      `event: meta\r\ndata: ${JSON.stringify(meta)}\r\n\r\n`,
      'event: delta\r\ndata: {"t":"Hello"}\r\n\r\n',
      'event: done\r\ndata: {"finish":"stop","actions":[],"degraded":false}\r\n\r\n',
    ].join("");
    const chunks = Array.from(text, (_, index) => text.slice(index, index + 1));
    const onEvent = vi.fn<(event: SseEvent) => void>();
    const result = await readSse(responseFromChunks(chunks), onEvent);

    expect(onEvent.mock.calls.map(([event]) => event.event)).toEqual(["meta", "delta", "done"]);
    expect(result).toEqual({ completed: true, stopped: false, errorCode: null });
  });

  it("marks an error after text as incomplete even if done follows", async () => {
    const onEvent = vi.fn<(event: SseEvent) => void>();
    const response = responseFromChunks([
      'event: delta\ndata: {"t":"Partial"}\n\n',
      'event: error\ndata: {"code":"partial_generation_failed"}\n\n',
      'event: done\ndata: {"finish":"stop","actions":[],"degraded":false}\n\n',
    ]);

    const result = await readSse(response, onEvent);
    expect(result).toEqual({
      completed: true,
      stopped: false,
      errorCode: "partial_generation_failed",
    });
  });

  it("treats a stream without done as interrupted", async () => {
    const result = await readSse(
      responseFromChunks(['event: delta\ndata: {"t":"Partial"}\n\n']),
      () => undefined,
    );
    expect(result.completed).toBe(false);
    expect(result.stopped).toBe(false);
  });

  it("cancels the reader when the request is aborted", async () => {
    const controller = new AbortController();
    const stream = new ReadableStream<Uint8Array>({
      start(streamController) {
        streamController.enqueue(new TextEncoder().encode('event: delta\ndata: {"t":"Stop"}\n\n'));
      },
    });
    const result = await readSse(new Response(stream, { status: 200 }), () => {
      controller.abort();
    }, controller.signal);
    expect(result.stopped).toBe(true);
    expect(result.completed).toBe(false);
  });
});
