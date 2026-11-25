import {
  ApiError,
  isApiConfig,
  isRecord,
  type ApiConfig,
  type ClientEventName,
} from "./types";

export type ApiClient = {
  getConfig(): Promise<ApiConfig>;
  createSession(turnstileToken?: string): Promise<string>;
  streamChat(message: string, sessionToken: string, signal: AbortSignal): Promise<Response>;
  sendFeedback(traceId: string, sessionToken: string, rating: -1 | 0 | 1): Promise<void>;
  sendClientEvent(
    traceId: string,
    sessionToken: string,
    event: ClientEventName,
  ): Promise<void>;
};

export function createApiClient(apiOrigin: string, fetcher: typeof fetch = fetch): ApiClient {
  const baseUrl = new URL(apiOrigin);
  if (!["http:", "https:"].includes(baseUrl.protocol) || baseUrl.username || baseUrl.password) {
    throw new Error("The assistant API URL must be an HTTP(S) origin.");
  }

  const endpoint = (path: string): string => {
    const base = `${baseUrl.href.replace(/\/+$/, "")}/`;
    return new URL(path.replace(/^\/+/, ""), base).href;
  };

  const request = async (path: string, init?: RequestInit): Promise<Response> => {
    const response = await fetcher(endpoint(path), init);
    if (!response.ok) await throwResponseError(response);
    return response;
  };

  return {
    async getConfig() {
      const response = await request("api/v1/config");
      const value: unknown = await response.json();
      if (!isApiConfig(value)) throw new Error("The assistant returned an invalid config response.");
      return value;
    },
    async createSession(turnstileToken) {
      const body = turnstileToken ? { turnstile_token: turnstileToken } : {};
      const response = await request("api/v1/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const value: unknown = await response.json();
      if (
        !isRecord(value) ||
        typeof value.session_token !== "string" ||
        value.session_token.length < 40 ||
        typeof value.expires_in_minutes !== "number"
      ) {
        throw new Error("The assistant returned an invalid session response.");
      }
      return value.session_token;
    },
    streamChat(message, sessionToken, signal) {
      return request("api/v1/chat/stream", {
        method: "POST",
        headers: {
          Accept: "text/event-stream",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ message, session_token: sessionToken }),
        signal,
      });
    },
    async sendFeedback(traceId, sessionToken, rating) {
      await request("api/v1/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          trace_id: traceId,
          session_token: sessionToken,
          rating,
        }),
      });
    },
    async sendClientEvent(traceId, sessionToken, event) {
      await request("api/v1/client-events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          trace_id: traceId,
          session_token: sessionToken,
          event,
        }),
      });
    },
  };
}

async function throwResponseError(response: Response): Promise<never> {
  const traceId = response.headers.get("X-Request-ID");
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError(response.status, "invalid_error_response", traceId);
  }
  if (!isRecord(payload) || !isRecord(payload.error) || typeof payload.error.code !== "string") {
    throw new ApiError(response.status, "invalid_error_response", traceId);
  }
  const code = payload.error.code;
  throw new ApiError(response.status, code, traceId);
}
