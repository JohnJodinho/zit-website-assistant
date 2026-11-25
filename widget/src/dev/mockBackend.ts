import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";
import { isRecord } from "../api/types";

const mockMarker = "ZIT_WIDGET_MOCK_BACKEND_MARKER_58978D21";
const states = new Set([
  "normal",
  "slow-first-word",
  "long-answer",
  "error-after-text",
  "interrupted",
  "rate-limited",
  "session-expired",
  "disabled",
  "maintenance",
  "busy-fallback",
  "message-too-long",
  "offline",
]);

export function mockBackendPlugin(): Plugin {
  let sessionNumber = 0;
  let expiredResponseSent = false;

  return {
    name: "zit-widget-dev-mock-backend",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const requestUrl = getRequestUrl(request);
        if (!requestUrl?.pathname.startsWith("/__mock-api/")) {
          next();
          return;
        }
        void handleRequest(
          request,
          response,
          requestUrl.pathname,
          () => {
            sessionNumber += 1;
            return `mock_token_${String(sessionNumber).padStart(32, "0")}`;
          },
          () => {
            expiredResponseSent = true;
          },
          () => expiredResponseSent,
        );
      });
    },
  };
}

function getRequestUrl(request: IncomingMessage): URL | null {
  if (!request.url) return null;
  const host = request.headers.host ?? "127.0.0.1";
  return new URL(request.url, `http://${host}`);
}

async function handleRequest(
  request: IncomingMessage,
  response: ServerResponse,
  pathname: string,
  newSessionToken: () => string,
  markExpiredResponse: () => void,
  wasExpiredResponseSent: () => boolean,
): Promise<void> {
  const segments = pathname.split("/").filter(Boolean);
  const state = segments[1] ?? "normal";
  if (!states.has(state)) {
    sendJson(response, 404, { error: { code: "mock_state_not_found" } });
    return;
  }
  const endpoint = `/${segments.slice(2).join("/")}`;
  const handlers: Record<string, () => void | Promise<void>> = {
    "GET /api/v1/config": () => sendConfig(response, state),
    "POST /api/v1/sessions": () =>
      sendJson(response, 200, {
        session_token: newSessionToken(),
        expires_in_minutes: 30,
      }),
    "POST /api/v1/chat/stream": () =>
      sendChat(response, request, state, markExpiredResponse, wasExpiredResponseSent),
    "POST /api/v1/feedback": () =>
      sendJson(response, 200, { status: "recorded", trace_id: "00000000-0000-0000-0000-000000000001" }),
    "POST /api/v1/client-events": () => sendJson(response, 200, { status: "recorded" }),
  };
  const handler = handlers[`${request.method} ${endpoint}`];
  if (!handler) {
    sendJson(response, 404, { error: { code: "mock_endpoint_not_found" } });
    return;
  }
  await handler();
}

function sendConfig(response: ServerResponse, state: string): void {
  sendJson(response, 200, {
    enabled: state !== "disabled",
    rollout_percent: 100,
    maintenance_message:
      state === "maintenance" ? "The assistant is taking a short break. Please contact admissions." : "",
    privacy_notice: "Do not enter personal or confidential information.",
  });
}

async function sendChat(
  response: ServerResponse,
  request: IncomingMessage,
  state: string,
  markExpiredResponse: () => void,
  wasExpiredResponseSent: () => boolean,
): Promise<void> {
  if (respondToChatState(response, state, markExpiredResponse, wasExpiredResponseSent)) return;
  const body = await readRequestBody(request);
  const message = typeof body.message === "string" ? body.message : "How do I apply?";
  const traceId = "00000000-0000-0000-0000-000000000001";
  response.statusCode = 200;
  response.setHeader("Content-Type", "text/event-stream; charset=utf-8");
  response.setHeader("Cache-Control", "no-cache");
  response.setHeader("X-Request-ID", traceId);
  response.flushHeaders();
  response.write(eventFrame("meta", {
    request_id: traceId,
    release: "mock-release",
    path: state === "busy-fallback" ? "capacity" : "content",
    intent: ["mock"],
    links: {
      admissions: { label: "Apply now", url: "https://example.invalid/admissions" },
      courses: { label: "View courses", url: "https://example.invalid/courses" },
    },
    degraded: state === "busy-fallback",
  }));
  const answer = getAnswer(message, state);
  if (state === "slow-first-word") await delay(1_200);
  for (const part of splitAnswer(answer)) {
    response.write(eventFrame("delta", { t: part }));
    await delay(24);
  }
  if (state === "error-after-text") {
    response.write(eventFrame("error", { code: "partial_generation_failed" }));
    response.write(eventFrame("done", { finish: "stop", actions: [], degraded: false }));
    response.end();
    return;
  }
  if (state !== "interrupted") {
    response.write(eventFrame("done", {
      finish: "stop",
      actions: [],
      degraded: state === "busy-fallback",
    }));
  }
  response.end();
}

function respondToChatState(
  response: ServerResponse,
  state: string,
  markExpiredResponse: () => void,
  wasExpiredResponseSent: () => boolean,
): boolean {
  const responses: Record<string, () => void> = {
    "rate-limited": () => sendJson(response, 429, { error: { code: "chat_rate_limited" } }),
    "message-too-long": () => sendJson(response, 413, { error: { code: "message_too_long" } }),
    offline: () => sendJson(response, 200, { error: { code: "mock_offline_state" } }),
  };
  const responseForState = responses[state];
  if (responseForState) {
    responseForState();
    return true;
  }
  if (state !== "session-expired" || wasExpiredResponseSent()) return false;
  markExpiredResponse();
  sendJson(response, 401, { error: { code: "invalid_or_expired_session" } });
  return true;
}

async function readRequestBody(request: IncomingMessage): Promise<Record<string, unknown>> {
  let body = "";
  for await (const part of request) {
    body += typeof part === "string" ? part : part.toString();
  }
  try {
    const parsed: unknown = JSON.parse(body);
    if (isRecord(parsed)) return parsed;
  } catch {
    return {};
  }
  return {};
}

function getAnswer(message: string, state: string): string {
  if (state === "long-answer") {
    return [
      "Here is a longer example answer.",
      "",
      "| Programme | Duration |",
      "| --- | --- |",
      "| Web design | 12 weeks |",
      "| Data skills | 10 weeks |",
      "",
      "Next steps:",
      "- Choose a programme.",
      "- Contact admissions for current fees.",
    ].join("\n");
  }
  if (state === "busy-fallback") {
    return "I can offer a quick answer right now. Please contact admissions for full details.";
  }
  return `Thanks for asking: ${message} ZIT can help you find course and application information.`;
}

function splitAnswer(answer: string): string[] {
  const words = answer.split(/(\s+)/).filter(Boolean);
  return words.length > 0 ? words : [answer];
}

function eventFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function sendJson(response: ServerResponse, status: number, body: unknown): void {
  response.statusCode = status;
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  response.end(JSON.stringify(body));
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

void mockMarker;
