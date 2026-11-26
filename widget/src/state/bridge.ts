import { isHttpUrl, isRecord } from "../api/types";

export type BridgeInit = {
  apiUrl: string;
  mode: LayoutMode;
  privacyNotice: string;
  parentOrigin: string;
};

export type LayoutMode = "mobile" | "desktop";

export function isLayoutMode(value: unknown): value is LayoutMode {
  return value === "mobile" || value === "desktop";
}

export function connectParent(
  window: Window,
  allowedOrigins: string[],
  onInit: (init: BridgeInit) => void,
): () => void {
  const handleMessage = (event: MessageEvent<unknown>): void => {
    if (!isTrustedInitEvent(event, window, allowedOrigins) || !isBridgeInitData(event.data)) return;
    onInit({
      apiUrl: event.data.apiUrl,
      mode: event.data.mode ?? "desktop",
      privacyNotice: typeof event.data.privacyNotice === "string" ? event.data.privacyNotice : "",
      parentOrigin: event.origin,
    });
  };
  window.addEventListener("message", handleMessage);
  return () => window.removeEventListener("message", handleMessage);
}

type BridgeInitData = {
  type: "zit:init";
  apiUrl: string;
  mode?: LayoutMode;
  privacyNotice?: string;
};

function isTrustedInitEvent(
  event: MessageEvent<unknown>,
  window: Window,
  allowedOrigins: string[],
): boolean {
  return event.source === window.parent && allowedOrigins.includes(event.origin);
}

function isBridgeInitData(value: unknown): value is BridgeInitData {
  if (!isRecord(value)) return false;
  return (
    value.type === "zit:init" &&
    typeof value.apiUrl === "string" &&
    isHttpUrl(value.apiUrl) &&
    (value.mode === undefined || isLayoutMode(value.mode)) &&
    (typeof value.privacyNotice === "string" || value.privacyNotice === undefined)
  );
}

export function sendParentMessage(
  window: Window,
  parentOrigin: string,
  message: { type: string; [key: string]: string },
): void {
  if (!parentOrigin || !window.parent || window.parent === window) return;
  window.parent.postMessage(message, parentOrigin);
}

export function parseAllowedOrigins(value: string): string[] {
  return value
    .split(",")
    .map((origin) => origin.trim())
    .filter((origin) => {
      try {
        const url = new URL(origin);
        return (
          (url.protocol === "http:" || url.protocol === "https:") &&
          url.origin === origin &&
          url.username === "" &&
          url.password === ""
        );
      } catch {
        return false;
      }
    });
}
