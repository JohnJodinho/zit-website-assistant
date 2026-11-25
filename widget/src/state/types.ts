import type { ChatMeta } from "../api/types";

export type ChatRole = "user" | "assistant";
export type ChatStatus = "streaming" | "complete" | "incomplete" | "stopped" | "error";
export type Rating = -1 | 0 | 1;

export type ChatMessage = {
  id: string;
  role: ChatRole;
  text: string;
  status: ChatStatus;
  traceId: string | null;
  meta: ChatMeta | null;
  degraded: boolean;
  rating: Rating | null;
};
