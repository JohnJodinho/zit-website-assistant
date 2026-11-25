import { isHttpUrl, isRecord } from "../api/types";

export type BridgeInit = {
  apiUrl: string;
  privacyNotice: string;
  parentOrigin: string;
};

export function connectParent(
  window: Window,
  allowedOrigins: string[],
  onInit: (init: BridgeInit) => void,
): () => void {
  const handleMessage = (event: MessageEvent<unknown>): void => {
    if (event.source !== window.parent || !allowedOrigins.includes(event.origin)) return;
    if (!isRecord(event.data) || event.data.type !== "zit:init") return;
    if (
      typeof event.data.apiUrl !== "string" ||
      !isHttpUrl(event.data.apiUrl) ||
      (typeof event.data.privacyNotice !== "string" && event.data.privacyNotice !== undefined)
    ) {
      return;
    }
    onInit({
      apiUrl: event.data.apiUrl,
      privacyNotice: typeof event.data.privacyNotice === "string" ? event.data.privacyNotice : "",
      parentOrigin: event.origin,
    });
  };
  window.addEventListener("message", handleMessage);
  return () => window.removeEventListener("message", handleMessage);
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
