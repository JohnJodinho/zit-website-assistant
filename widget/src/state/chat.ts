import { ApiError } from "../api/types";
import type { ApiClient } from "../api/client";
import { readSse, type StreamResult } from "../api/sse";
import { SessionManager } from "./session";

type SessionCallbacks = {
  getChallengeToken?(signal: AbortSignal): Promise<string | undefined>;
  onSessionCreated?(): void;
};

export async function streamWithSession(
  api: ApiClient,
  sessions: SessionManager,
  message: string,
  signal: AbortSignal,
  onEvent: Parameters<typeof readSse>[1],
  callbacks: SessionCallbacks = {},
): Promise<StreamResult> {
  const token = await ensureSession(api, sessions, signal, callbacks);
  try {
    return await startStream(api, message, token, signal, onEvent);
  } catch (error) {
    if (!isExpiredSession(error)) throw error;
    sessions.clear();
    const refreshedToken = await ensureSession(api, sessions, signal, callbacks);
    return startStream(api, message, refreshedToken, signal, onEvent);
  }
}

async function ensureSession(
  api: ApiClient,
  sessions: SessionManager,
  signal: AbortSignal,
  callbacks: SessionCallbacks,
): Promise<string> {
  if (signal.aborted) throw new DOMException("The request was stopped.", "AbortError");
  const existing = sessions.currentToken;
  if (existing) return existing;
  const challengeToken = await callbacks.getChallengeToken?.(signal);
  if (signal.aborted) throw new DOMException("The request was stopped.", "AbortError");
  const token = await sessions.getToken(api, challengeToken);
  callbacks.onSessionCreated?.();
  return token;
}

function isExpiredSession(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.status === 401 &&
    error.code === "invalid_or_expired_session"
  );
}

async function startStream(
  api: ApiClient,
  message: string,
  token: string,
  signal: AbortSignal,
  onEvent: Parameters<typeof readSse>[1],
): Promise<StreamResult> {
  const response = await api.streamChat(message, token, signal);
  return readSse(response, onEvent, signal);
}
