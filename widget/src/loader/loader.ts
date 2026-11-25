import tokens from "../styles/tokens.css?raw";
import loaderStyles from "./loader.css?raw";
import { isApiConfig, isHttpUrl, isRecord } from "../api/types";

type LoaderOptions = {
  document: Document;
  window: Window;
  apiUrl: string;
  widgetUrl: string;
  position: "left" | "right";
  fetcher?: typeof fetch;
};

type LoaderHandle = {
  host: HTMLElement;
  launcher: HTMLButtonElement;
  iframe: HTMLIFrameElement | null;
  destroy(): void;
};

const storageKeys = {
  teaserDismissed: "zit-widget-teaser-dismissed",
  opened: "zit-widget-opened",
};

export async function installLoader(options: LoaderOptions): Promise<LoaderHandle | null> {
  const { document, window, apiUrl, widgetUrl, position } = options;
  if (!isHttpUrl(apiUrl) || !isHttpUrl(widgetUrl)) return null;
  if (document.querySelector("[data-zit-assistant-loader]")) return null;

  const config = await getEnabledConfig(apiUrl, options.fetcher ?? fetch);
  if (!config) return null;

  const host = document.createElement("div");
  host.dataset.zitAssistantLoader = "true";
  host.dataset.position = position;
  const shadow = host.attachShadow({ mode: "open" });
  const styleElement = document.createElement("style");
  styleElement.textContent = `${tokens.replace(":root", ":host")}\n${loaderStyles}`;
  shadow.append(styleElement);

  const layer = document.createElement("div");
  layer.className = "layer";
  const launcher = createLauncher(document, widgetUrl);
  const teaser = createTeaser(document);
  const panel = document.createElement("div");
  panel.className = "frame-shell";
  panel.hidden = true;
  panel.setAttribute("role", "region");
  panel.setAttribute("aria-label", "ZIT Assistant");
  layer.append(launcher, teaser, panel);
  shadow.append(layer);
  document.body.append(host);

  let iframe: HTMLIFrameElement | null = null;
  let teaserTimer = 0;
  const widgetOrigin = new URL(widgetUrl).origin;
  const apiOrigin = new URL(apiUrl).href.replace(/\/+$/, "");
  const dismissed = safeStorageGet(window, storageKeys.teaserDismissed) === "true";
  const wasOpened = safeStorageGet(window, storageKeys.opened) === "true";

  const closePanel = (): void => {
    delete panel.dataset.open;
    panel.hidden = true;
    launcher.hidden = false;
    launcher.setAttribute("aria-expanded", "false");
    launcher.focus();
  };

  const handleMessage = (event: MessageEvent<unknown>): void => {
    handleLoaderMessage(event, iframe, widgetOrigin, closePanel, launcher, host, panel);
  };

  const openPanel = (): void => {
    teaser.hidden = true;
    safeStorageSet(window, storageKeys.opened, "true");
    if (!iframe) {
      iframe = document.createElement("iframe");
      iframe.title = "ZIT Assistant";
      iframe.setAttribute("referrerpolicy", "no-referrer");
      iframe.setAttribute("sandbox", "allow-scripts allow-same-origin allow-popups");
      iframe.src = widgetUrl;
      iframe.addEventListener("load", () => {
        iframe?.contentWindow?.postMessage(
          { type: "zit:init", apiUrl: apiOrigin, privacyNotice: config.privacy_notice },
          widgetOrigin,
        );
      });
      panel.append(iframe);
    }
    panel.hidden = false;
    launcher.hidden = true;
    launcher.setAttribute("aria-expanded", "true");
    window.requestAnimationFrame(() => {
      if (!panel.hidden) panel.dataset.open = "true";
    });
    iframe.contentWindow?.postMessage({ type: "zit:open" }, widgetOrigin);
    iframe.focus();
  };

  const dismissTeaser = (): void => {
    teaser.hidden = true;
    safeStorageSet(window, storageKeys.teaserDismissed, "true");
  };

  launcher.addEventListener("click", openPanel);
  teaser.querySelector("button")?.addEventListener("click", dismissTeaser);
  window.addEventListener("message", handleMessage);

  if (!dismissed && !wasOpened) {
    teaserTimer = window.setTimeout(() => {
      if (!panel.hidden) return;
      teaser.hidden = false;
    }, 8_000);
  }

  const handleBeforeUnload = (): void => {
    window.clearTimeout(teaserTimer);
    window.removeEventListener("message", handleMessage);
  };
  window.addEventListener("beforeunload", handleBeforeUnload, { once: true });

  return {
    host,
    launcher,
    get iframe() {
      return iframe;
    },
    destroy() {
      window.clearTimeout(teaserTimer);
      window.removeEventListener("message", handleMessage);
      window.removeEventListener("beforeunload", handleBeforeUnload);
      host.remove();
    },
  };
}

async function getEnabledConfig(
  apiUrl: string,
  fetcher: typeof fetch,
): Promise<ReturnType<typeof getValidatedConfig>> {
  const response = await fetcher(`${apiUrl.replace(/\/+$/, "")}/api/v1/config`);
  if (!response.ok) return null;
  const config: unknown = await response.json();
  return getValidatedConfig(config);
}

function getValidatedConfig(config: unknown) {
  if (!isApiConfig(config) || !config.enabled) return null;
  return config;
}

function handleLoaderMessage(
  event: MessageEvent<unknown>,
  iframe: HTMLIFrameElement | null,
  widgetOrigin: string,
  closePanel: () => void,
  launcher: HTMLButtonElement,
  host: HTMLElement,
  panel: HTMLDivElement,
): void {
  if (!iframe || event.origin !== widgetOrigin || event.source !== iframe.contentWindow) return;
  if (!isRecord(event.data) || typeof event.data.type !== "string") return;
  const handlers: Record<string, () => void> = {
    "zit:close": closePanel,
    "zit:minimize": closePanel,
    "zit:focus-launcher": () => launcher.focus(),
    "zit:hide": () => host.remove(),
  };
  const handler = handlers[event.data.type];
  if (handler) {
    handler();
    return;
  }
  if (event.data.type !== "zit:mode") return;
  if (event.data.mode === "mobile" || event.data.mode === "desktop") {
    panel.dataset.mode = event.data.mode;
  }
}

function createLauncher(document: Document, widgetUrl: string): HTMLButtonElement {
  const launcher = document.createElement("button");
  launcher.className = "launcher";
  launcher.type = "button";
  launcher.setAttribute("aria-label", "Ask ZIT");
  launcher.setAttribute("aria-expanded", "false");
  const mark = document.createElement("span");
  mark.className = "assistant-mark";
  mark.setAttribute("aria-hidden", "true");
  const image = document.createElement("img");
  image.src = new URL("zit-mark.png", widgetUrl).href;
  image.alt = "";
  mark.append(image);
  const label = document.createElement("span");
  label.className = "launcher-label";
  label.textContent = "Ask ZIT";
  launcher.append(mark, label);
  return launcher;
}

function createTeaser(document: Document): HTMLDivElement {
  const teaser = document.createElement("div");
  teaser.className = "teaser";
  teaser.hidden = true;
  const message = document.createElement("p");
  message.textContent = "Questions about courses or applying? Ask me.";
  const dismiss = document.createElement("button");
  dismiss.type = "button";
  dismiss.setAttribute("aria-label", "Dismiss suggestion");
  dismiss.textContent = "×";
  teaser.append(message, dismiss);
  return teaser;
}

function safeStorageGet(window: Window, key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeStorageSet(window: Window, key: string, value: string): void {
  try {
    window.sessionStorage.setItem(key, value);
  } catch {
    return;
  }
}

function bootLoader(): void {
  const script = document.currentScript;
  if (!(script instanceof HTMLScriptElement)) return;
  const scriptUrl = new URL(script.src, document.baseURI);
  const apiUrl =
    script.dataset.apiUrl ?? import.meta.env.VITE_ASSISTANT_API_URL;
  const widgetUrl =
    script.dataset.widgetUrl ??
    import.meta.env.VITE_ASSISTANT_WIDGET_URL ??
    scriptUrl.origin;
  const position = script.dataset.position === "left" ? "left" : "right";
  if (!apiUrl) return;
  void installLoader({ document, window, apiUrl, widgetUrl, position }).catch(() => {
    console.warn("ZIT Assistant could not load its availability settings.");
  });
}

bootLoader();
