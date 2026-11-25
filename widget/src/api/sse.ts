import {
  isChatDone,
  isChatMeta,
  isRecord,
  type SseEvent,
} from "./types";

export type StreamResult = {
  completed: boolean;
  stopped: boolean;
  errorCode: string | null;
};

type ParserState = {
  eventName: string;
  dataLines: string[];
};

type EventDispatch = () => void;

export async function readSse(
  response: Response,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<StreamResult> {
  if (!response.ok || !response.body) {
    throw new Error("The assistant did not start a response stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const parser: ParserState = { eventName: "message", dataLines: [] };
  let completed = false;
  let errorCode: string | null = null;
  const cancelReader = (): void => {
    void reader.cancel();
  };
  signal?.addEventListener("abort", cancelReader, { once: true });

  const dispatch = (): void => {
    if (parser.dataLines.length === 0) {
      parser.eventName = "message";
      return;
    }
    const event = decodeEvent(parser.eventName, parser.dataLines.join("\n"));
    parser.dataLines = [];
    parser.eventName = "message";
    if (event === null) return;
    onEvent(event);
    if (event.event === "done") completed = true;
    if (event.event === "error") errorCode = event.data.code;
  };

  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });
      let lineEnd = findLineEnd(buffer);
      while (lineEnd !== null) {
        const line = buffer.slice(0, lineEnd.position);
        buffer = buffer.slice(lineEnd.position + lineEnd.length);
        processLine(line, parser, dispatch);
        lineEnd = findLineEnd(buffer);
      }
    }
    buffer += decoder.decode();
    return { completed, stopped: signal?.aborted === true, errorCode };
  } finally {
    signal?.removeEventListener("abort", cancelReader);
    reader.releaseLock();
  }
}

function processLine(line: string, parser: ParserState, dispatch: EventDispatch): void {
  if (line === "") {
    dispatch();
    return;
  }
  if (line.startsWith(":")) return;
  if (line.startsWith("event:")) {
    parser.eventName = line.slice(6).trim();
    return;
  }
  if (line.startsWith("data:")) parser.dataLines.push(line.slice(5).replace(/^ /, ""));
}

function findLineEnd(buffer: string): { position: number; length: number } | null {
  const position = buffer.search(/\r\n|\n|\r/);
  if (position < 0) return null;
  if (buffer[position] === "\r" && position === buffer.length - 1) return null;
  const length = buffer.startsWith("\r\n", position) ? 2 : 1;
  return { position, length };
}

function decodeEvent(eventName: string, json: string): SseEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(json);
  } catch {
    throw new Error("The assistant sent an invalid stream event.");
  }
  if (!isRecord(value)) throw new Error("The assistant sent an invalid stream event.");
  return eventDecoders[eventName]?.(value) ?? null;
}

const eventDecoders: Record<string, (value: Record<string, unknown>) => SseEvent | null> = {
  ping: () => ({ event: "ping", data: {} }),
  meta: (value) => isChatMeta(value) ? { event: "meta", data: value } : null,
  delta: (value) => typeof value.t === "string" ? { event: "delta", data: { t: value.t } } : null,
  error: (value) =>
    typeof value.code === "string" ? { event: "error", data: { code: value.code } } : null,
  done: (value) => isChatDone(value) ? { event: "done", data: value } : null,
};
