import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, isHttpUrl, type ApiConfig } from "./api/types";
import { createApiClient, type ApiClient } from "./api/client";
import { ChatPanel } from "./components/ChatPanel";
import { connectParent, parseAllowedOrigins, sendParentMessage } from "./state/bridge";
import { streamWithSession } from "./state/chat";
import { shouldSubmitRating } from "./state/feedback";
import { canSendQuestion, recordStreamEvent, updateMessage, type StreamProgress } from "./state/message-stream";
import { SessionManager } from "./state/session";
import type { ChatMessage } from "./state/types";

const privacyFallback = "Do not enter personal or confidential information.";
const allowedOrigins = parseAllowedOrigins(import.meta.env.VITE_PARENT_ORIGINS ?? "");
const turnstileSiteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY?.trim() ?? "";
const privacyUrl = isHttpUrl(import.meta.env.VITE_PRIVACY_URL ?? "")
  ? import.meta.env.VITE_PRIVACY_URL ?? ""
  : "";
const contactUrl = isHttpUrl(import.meta.env.VITE_CONTACT_URL ?? "")
  ? import.meta.env.VITE_CONTACT_URL ?? ""
  : "";
let messageSequence = 0;

export default function App() {
  const apiRef = useRef<ApiClient | null>(null);
  const [parentOrigin, setParentOrigin] = useState("");
  const parentOriginRef = useRef("");
  const [config, setConfig] = useState<ApiConfig | null>(null);
  const [configLoading, setConfigLoading] = useState(true);
  const [configFailed, setConfigFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"mobile" | "desktop">("desktop");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [offline, setOffline] = useState(!navigator.onLine);
  const [statusMessage, setStatusMessage] = useState("");
  const [messageHint, setMessageHint] = useState("");
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const [announcement, setAnnouncement] = useState("");
  const [busy, setBusy] = useState(false);
  const [followLatest, setFollowLatest] = useState(true);
  const [showJump, setShowJump] = useState(false);
  const [privacyDismissed, setPrivacyDismissed] = useState(readPrivacyDismissed);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [turnstileToken, setTurnstileToken] = useState("");
  const [turnstileResetKey, setTurnstileResetKey] = useState(0);
  const sessionManager = useMemo(() => new SessionManager(), []);
  const turnstileTokenRef = useRef("");
  const turnstileWaiter = useRef<((token: string) => void) | null>(null);
  const abortController = useRef<AbortController | null>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const reportedTraceIds = useRef(new Set<string>());

  const receiveTurnstileToken = useCallback((token: string): void => {
    turnstileTokenRef.current = token;
    setTurnstileToken(token);
    if (token && turnstileWaiter.current) {
      turnstileWaiter.current(token);
      turnstileWaiter.current = null;
    }
  }, []);

  const getChallengeToken = useCallback(async (signal: AbortSignal): Promise<string | undefined> => {
    if (!turnstileSiteKey) return undefined;
    if (turnstileTokenRef.current) return turnstileTokenRef.current;
    return new Promise((resolve) => {
      const finish = (token: string): void => {
        signal.removeEventListener("abort", abort);
        if (turnstileWaiter.current === finish) turnstileWaiter.current = null;
        resolve(token || undefined);
      };
      const abort = (): void => finish("");
      turnstileWaiter.current = finish;
      signal.addEventListener("abort", abort, { once: true });
    });
  }, []);

  const handleSessionCreated = useCallback((): void => {
    turnstileTokenRef.current = "";
    setTurnstileToken("");
    setTurnstileResetKey((current) => current + 1);
  }, []);

  useEffect(() => {
    const disconnect = connectParent(window, allowedOrigins, (init) => {
      try {
        const client = createApiClient(init.apiUrl);
        apiRef.current = client;
        parentOriginRef.current = init.parentOrigin;
        setParentOrigin(init.parentOrigin);
        setOpen(true);
        setConfigLoading(true);
        setConfigFailed(false);
        if (import.meta.env.DEV && new URL(init.apiUrl).pathname.includes("/__mock-api/offline")) {
          setOffline(true);
        }
        void client
          .getConfig()
          .then((result) => {
            setConfig(result);
            setConfigLoading(false);
            if (!result.enabled && !result.maintenance_message) {
              sendParentMessage(window, init.parentOrigin, { type: "zit:hide" });
            }
          })
          .catch(() => {
            setConfigLoading(false);
            setConfigFailed(true);
          });
      } catch {
        setConfigLoading(false);
        setConfigFailed(true);
      }
    });

    return disconnect;
  }, []);

  useEffect(() => {
    const onOnline = (): void => setOffline(false);
    const onOffline = (): void => setOffline(true);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  useEffect(() => {
    if (remainingSeconds <= 0) return;
    const timer = window.setInterval(() => {
      setRemainingSeconds((seconds) => Math.max(0, seconds - 1));
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [remainingSeconds]);

  useEffect(() => {
    const handleParentMessage = (event: MessageEvent<unknown>): void => {
      if (event.source !== window.parent || event.origin !== parentOriginRef.current) return;
      if (typeof event.data !== "object" || event.data === null || !("type" in event.data)) return;
      if (event.data.type === "zit:open") setOpen(true);
    };
    window.addEventListener("message", handleParentMessage);
    return () => window.removeEventListener("message", handleParentMessage);
  }, []);

  useEffect(() => {
    if (open) composerRef.current?.focus();
  }, [open, configLoading]);

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && open) closePanel();
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [open]);

  useEffect(() => {
    const reportMode = (): void => {
      const mode = window.innerWidth <= 600 || window.innerHeight <= 480 ? "mobile" : "desktop";
      setMode(mode);
      sendParentMessage(window, parentOrigin, { type: "zit:mode", mode });
    };
    reportMode();
    window.addEventListener("resize", reportMode);
    return () => window.removeEventListener("resize", reportMode);
  }, [parentOrigin]);

  useEffect(() => {
    const list = messageListRef.current;
    if (!list || !followLatest) return;
    list.scrollTop = list.scrollHeight;
  }, [messages, streaming, followLatest]);

  function closePanel(): void {
    setOpen(false);
    sendParentMessage(window, parentOriginRef.current, { type: "zit:close" });
    sendParentMessage(window, parentOriginRef.current, { type: "zit:focus-launcher" });
  }

  function handleListScroll(): void {
    const list = messageListRef.current;
    if (!list) return;
    const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 48;
    setFollowLatest(atBottom);
    setShowJump(!atBottom);
  }

  async function sendQuestion(question: string): Promise<void> {
    const cleaned = question.trim();
    const currentApi = apiRef.current;
    if (!canSendQuestion(cleaned, currentApi, streaming, offline, remainingSeconds, config)) return;

    const userMessage = makeMessage("user", cleaned, "complete");
    const assistantMessage = makeMessage("assistant", "", "streaming");
    setMessages((items) => [...items, userMessage, assistantMessage]);
    setDraft("");
    setMessageHint("");
    setStatusMessage("");
    setAnnouncement("");
    setStreaming(true);
    setFollowLatest(true);
    const controller = new AbortController();
    abortController.current = controller;
    const streamData: StreamProgress = {
      answer: "",
      meta: null,
      degraded: false,
    };

    try {
      const result = await streamWithSession(
        currentApi,
        sessionManager,
        cleaned,
        controller.signal,
        (event) => recordStreamEvent(event, streamData, assistantMessage, setMessages),
        {
          getChallengeToken,
          onSessionCreated: handleSessionCreated,
        },
      );
      await applyStreamResult(result, controller.signal, assistantMessage, streamData, currentApi);
    } catch (error) {
      if (controller.signal.aborted) {
        updateMessage(setMessages, assistantMessage.id, (message) => ({ ...message, status: "stopped" }));
      } else {
        handleRequestFailure(error, assistantMessage, currentApi, cleaned);
      }
    } finally {
      setStreaming(false);
      abortController.current = null;
      setShowJump(false);
    }
  }

  function handleRequestFailure(
    error: unknown,
    assistantMessage: ChatMessage,
    currentApi: ApiClient,
    question: string,
  ): void {
    setMessages((items) => items.filter((message) => message.id !== assistantMessage.id));
    if (error instanceof ApiError && handleKnownApiError(error, question)) return;
    const traceId = error instanceof ApiError ? error.traceId : null;
    setMessages((items) => [
      ...items,
      { ...assistantMessage, status: "error", traceId },
    ]);
    setBusy(false);
    void reportResponseError(currentApi, traceId);
  }

  function handleKnownApiError(error: ApiError, question: string): boolean {
    if (error.status === 429) {
      setDraft(question);
      setStatusMessage("Please wait a moment before sending another message.");
      setRemainingSeconds(30);
      return true;
    }
    if (error.status === 409) {
      setDraft(question);
      setStatusMessage("Another reply is still in progress. Please wait a moment.");
      setRemainingSeconds(3);
      return true;
    }
    if (error.status === 413 || error.code === "message_too_long") {
      setDraft(question);
      setMessageHint("Your message is too long. Please shorten it and try again.");
      return true;
    }
    if (error.status === 422) {
      setDraft(question);
      setMessageHint("Please check your message and try again.");
      return true;
    }
    if (error.code === "assistant_not_available" || error.code === "assistant_not_in_rollout") {
      sendParentMessage(window, parentOriginRef.current, { type: "zit:hide" });
      setStatusMessage(config?.maintenance_message || "The assistant is unavailable right now.");
      return true;
    }
    return false;
  }

  async function reportResponseError(currentApi: ApiClient, traceId: string | null): Promise<void> {
    const token = sessionManager.currentToken;
    if (!traceId || !token || reportedTraceIds.current.has(traceId)) return;
    reportedTraceIds.current.add(traceId);
    try {
      await currentApi.sendClientEvent(traceId, token, "response_error");
    } catch {
      setStatusMessage("We couldn’t record the problem. You can still try your question again.");
    }
  }

  async function applyStreamResult(
    result: Awaited<ReturnType<typeof streamWithSession>>,
    signal: AbortSignal,
    assistantMessage: ChatMessage,
    progress: StreamProgress,
    currentApi: ApiClient,
  ): Promise<void> {
    if (signal.aborted || result.stopped) {
      updateMessage(setMessages, assistantMessage.id, (message) => ({ ...message, status: "stopped" }));
      return;
    }
    if (result.errorCode || !result.completed) {
      updateMessage(setMessages, assistantMessage.id, (message) => ({
        ...message,
        status: "incomplete",
        traceId: progress.meta?.request_id ?? null,
      }));
      await reportResponseError(currentApi, progress.meta?.request_id ?? null);
      return;
    }
    updateMessage(setMessages, assistantMessage.id, (message) => ({
      ...message,
      status: "complete",
      traceId: progress.meta?.request_id ?? null,
      meta: progress.meta,
      degraded: progress.degraded,
    }));
    setBusy(progress.degraded);
    setAnnouncement(`Assistant response: ${progress.answer}`);
  }

  async function submitFeedback(messageId: string, rating: -1 | 1): Promise<void> {
    const message = messages.find((item) => item.id === messageId);
    const currentApi = apiRef.current;
    const token = sessionManager.currentToken;
    if (!message?.traceId || !currentApi || !token || !shouldSubmitRating(message.rating, rating)) return;
    try {
      await currentApi.sendFeedback(message.traceId, token, rating);
      setMessages((items) =>
        items.map((item) => (item.id === messageId ? { ...item, rating } : item)),
      );
      await currentApi.sendClientEvent(message.traceId, token, "feedback_submitted");
      setStatusMessage("");
    } catch {
      setStatusMessage("Feedback could not be recorded. Please try again later.");
    }
  }

  async function copyAnswer(messageId: string): Promise<void> {
    const message = messages.find((item) => item.id === messageId);
    if (!message) return;
    try {
      await navigator.clipboard.writeText(message.text);
      setCopiedMessageId(messageId);
      window.setTimeout(() => setCopiedMessageId(null), 1_500);
    } catch {
      setStatusMessage("Copy is unavailable in this browser. You can select the answer text.");
    }
  }

  function retryMessage(messageId: string): void {
    const index = messages.findIndex((message) => message.id === messageId);
    const previousUser = messages.slice(0, index).reverse().find((message) => message.role === "user");
    if (previousUser) void sendQuestion(previousUser.text);
  }

  function startNewChat(): void {
    if (messages.length > 0 && !window.confirm("Start a new chat? Your current conversation will be cleared.")) {
      return;
    }
    setMessages([]);
    setDraft("");
    setStatusMessage("");
    setMessageHint("");
    setBusy(false);
    sessionManager.clear();
  }

  function stopResponse(): void {
    abortController.current?.abort();
  }

  function retryConfig(): void {
    const currentApi = apiRef.current;
    if (!currentApi) return;
    setConfigLoading(true);
    setConfigFailed(false);
    void currentApi
      .getConfig()
      .then((result) => {
        setConfig(result);
        if (!result.enabled && !result.maintenance_message) {
          sendParentMessage(window, parentOriginRef.current, { type: "zit:hide" });
        }
      })
      .catch(() => setConfigFailed(true))
      .finally(() => setConfigLoading(false));
  }

  const disabled = offline ||
    remainingSeconds > 0 ||
    Boolean(config?.maintenance_message) ||
    (turnstileSiteKey.length > 0 && !turnstileToken && !sessionManager.currentToken);
  return (
    <main className={`widget-shell ${open ? "widget-open" : ""}`} data-mode={mode}>
      {open && (
        <ChatPanel
          announcement={announcement}
          busy={busy}
          config={config}
          configFailed={configFailed}
          configLoading={configLoading}
          contactUrl={contactUrl}
          copiedMessageId={copiedMessageId}
          disabled={disabled}
          draft={draft}
          inputRef={composerRef}
          messageHint={messageHint}
          messageListRef={messageListRef}
          messages={messages}
          offline={offline}
          onClose={closePanel}
          onCopy={(id) => void copyAnswer(id)}
          onDraftChange={setDraft}
          onFeedback={(id, rating) => void submitFeedback(id, rating)}
          onJump={() => {
            setFollowLatest(true);
            setShowJump(false);
          }}
          onListScroll={handleListScroll}
          onMinimize={() => {
            setOpen(false);
            sendParentMessage(window, parentOriginRef.current, { type: "zit:minimize" });
          }}
          onNewChat={startNewChat}
          onPrivacyDismiss={() => {
            setPrivacyDismissed(true);
            writePrivacyDismissed();
          }}
          onRetry={(id) => retryMessage(id)}
          onRetryConfig={retryConfig}
          onStop={stopResponse}
          onSubmit={() => void sendQuestion(draft)}
          onSuggest={(question) => void sendQuestion(question)}
          onTurnstileToken={receiveTurnstileToken}
          privacyDismissed={privacyDismissed}
          privacyNotice={privacyFallback}
          privacyUrl={privacyUrl}
          remainingSeconds={remainingSeconds}
          showJump={showJump}
          statusMessage={statusMessage}
          streaming={streaming}
          turnstileResetKey={turnstileResetKey}
          turnstileSiteKey={turnstileSiteKey}
        />
      )}
    </main>
  );
}

function makeMessage(
  role: ChatMessage["role"],
  text: string,
  status: ChatMessage["status"],
): ChatMessage {
  messageSequence += 1;
  return {
    id: `message-${messageSequence}`,
    role,
    text,
    status,
    traceId: null,
    meta: null,
    degraded: false,
    rating: null,
  };
}

function readPrivacyDismissed(): boolean {
  try {
    return window.sessionStorage.getItem("zit-widget-privacy-dismissed") === "true";
  } catch {
    return false;
  }
}

function writePrivacyDismissed(): void {
  try {
    window.sessionStorage.setItem("zit-widget-privacy-dismissed", "true");
  } catch {
    return;
  }
}
