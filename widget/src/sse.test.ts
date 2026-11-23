import { describe, expect, it, vi } from "vitest";
import { readSse } from "./sse";

describe("readSse", () => {
  it("reads SSE event frames", async () => {
    const frames = [
      'event: meta\ndata: {"request_id":"a"}\n\n',
      'event: delta\ndata: {"t":"Hello"}\n\n',
      'event: done\ndata: {"finish":"stop"}\n\n',
    ].join("");
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(frames));
        controller.close();
      },
    });
    const onEvent = vi.fn();
    await readSse(new Response(stream, { status: 200 }), onEvent);
    expect(onEvent).toHaveBeenCalledTimes(3);
  });
});
