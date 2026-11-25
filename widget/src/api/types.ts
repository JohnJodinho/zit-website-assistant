export type ApiConfig = {
  enabled: boolean;
  rollout_percent: number;
  maintenance_message: string;
  privacy_notice: string;
};

export type ApiLink = {
  label: string;
  url: string;
};

export type ChatMeta = {
  request_id: string;
  release: string | null;
  path: string;
  intent: string[];
  links: Record<string, ApiLink>;
  degraded: boolean;
};

export type ChatDone = {
  finish: string;
  actions: unknown[];
  degraded: boolean;
};

export type SseEvent =
  | { event: "ping"; data: Record<string, never> }
  | { event: "meta"; data: ChatMeta }
  | { event: "delta"; data: { t: string } }
  | { event: "error"; data: { code: string } }
  | { event: "done"; data: ChatDone };

export type ClientEventName = "response_error" | "feedback_submitted";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly traceId: string | null;

  constructor(status: number, code: string, traceId: string | null) {
    super(code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.traceId = traceId;
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isApiConfig(value: unknown): value is ApiConfig {
  return (
    isRecord(value) &&
    typeof value.enabled === "boolean" &&
    typeof value.rollout_percent === "number" &&
    typeof value.maintenance_message === "string" &&
    typeof value.privacy_notice === "string"
  );
}

export function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      (url.protocol === "https:" || url.protocol === "http:") &&
      url.username === "" &&
      url.password === ""
    );
  } catch {
    return false;
  }
}

export function isApiLink(value: unknown): value is ApiLink {
  return (
    isRecord(value) &&
    typeof value.label === "string" &&
    value.label.length > 0 &&
    typeof value.url === "string" &&
    isHttpUrl(value.url)
  );
}

export function isChatMeta(value: unknown): value is ChatMeta {
  return (
    isRecord(value) &&
    typeof value.request_id === "string" &&
    typeof value.path === "string" &&
    (typeof value.release === "string" || value.release === null) &&
    Array.isArray(value.intent) &&
    value.intent.every((item: unknown) => typeof item === "string") &&
    isRecord(value.links) &&
    Object.values(value.links).every(isApiLink) &&
    typeof value.degraded === "boolean"
  );
}

export function isChatDone(value: unknown): value is ChatDone {
  return (
    isRecord(value) &&
    typeof value.finish === "string" &&
    Array.isArray(value.actions) &&
    typeof value.degraded === "boolean"
  );
}
