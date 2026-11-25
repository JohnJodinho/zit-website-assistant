import "./parent.css";

const query = new URLSearchParams(window.location.search);
const requestedBackend = query.get("backend");
const backend = import.meta.env.DEV && requestedBackend === "mock" ? "mock" : "local";
const mockStates = new Set([
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
const requestedState = query.get("state") ?? "normal";
const mockState = mockStates.has(requestedState) ? requestedState : "normal";
const apiUrl = backend === "mock"
  ? `${window.location.origin}/__mock-api/${mockState}`
  : import.meta.env.VITE_ASSISTANT_API_URL;
const widgetUrl = import.meta.env.VITE_ASSISTANT_WIDGET_URL || window.location.origin;
const loader = document.createElement("script");
loader.src = new URL("loader.js", window.location.origin).href;
loader.async = true;
loader.dataset.apiUrl = apiUrl;
loader.dataset.widgetUrl = widgetUrl;
loader.dataset.position = "right";
document.body.append(loader);
