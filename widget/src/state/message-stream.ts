import type { Dispatch, SetStateAction } from "react";
import type { ApiClient } from "../api/client";
import type { ApiConfig, SseEvent } from "../api/types";
import type { ChatMessage } from "./types";

export type StreamProgress = {
  answer: string;
  meta: ChatMessage["meta"];
  degraded: boolean;
};

export function updateMessage(
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>,
  id: string,
  update: (message: ChatMessage) => ChatMessage,
): void {
  setMessages((messages) =>
    messages.map((message) => (message.id === id ? update(message) : message)),
  );
}

export function recordStreamEvent(
  event: SseEvent,
  progress: StreamProgress,
  assistantMessage: ChatMessage,
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>,
): void {
  if (event.event === "meta") progress.meta = event.data;
  if (event.event === "delta") progress.answer += event.data.t;
  if (event.event === "done") {
    progress.degraded = event.data.degraded || progress.meta?.degraded === true;
  }
  if (event.event !== "meta" && event.event !== "delta") return;
  updateMessage(setMessages, assistantMessage.id, (message) => ({
    ...message,
    text: progress.answer,
    traceId: progress.meta?.request_id ?? null,
    meta: progress.meta,
  }));
}

export function canSendQuestion(
  question: string,
  api: ApiClient | null,
  streaming: boolean,
  offline: boolean,
  remainingSeconds: number,
  config: ApiConfig | null,
): api is ApiClient {
  if (!question || !api) return false;
  if (streaming || offline || remainingSeconds > 0) return false;
  return !config?.maintenance_message && !(config && !config.enabled);
}
