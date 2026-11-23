(function () {
  if (document.querySelector("[data-zit-assistant-loader]")) return;

  const script = document.currentScript;
  const widgetUrl = script?.dataset.widgetUrl;
  const apiUrl = script?.dataset.apiUrl;
  const parentOrigin = window.location.origin;
  if (!widgetUrl || !apiUrl) return;

  const marker = document.createElement("div");
  marker.setAttribute("data-zit-assistant-loader", "true");
  marker.style.cssText =
    "position:fixed;right:16px;bottom:16px;z-index:2147483000;width:360px;height:min(620px,calc(100dvh - 32px));max-width:calc(100vw - 32px)";
  const frame = document.createElement("iframe");
  frame.title = "ZIT website assistant";
  frame.src = widgetUrl;
  frame.style.cssText = "width:100%;height:100%;border:0;border-radius:16px";
  frame.setAttribute("allow", "clipboard-write");
  marker.appendChild(frame);
  document.body.appendChild(marker);

  const closeHandler = (event) => {
    if (event.origin !== new URL(widgetUrl).origin) return;
    if (event.data?.type === "zit:remove") marker.remove();
  };
  window.addEventListener("message", closeHandler);

  fetch(`${apiUrl}/api/v1/config`, { mode: "cors" })
    .then((response) => response.ok ? response.json() : null)
    .then((config) => {
      if (!config?.enabled) marker.remove();
    })
    .catch(() => marker.remove());

  window.addEventListener("beforeunload", () => {
    window.removeEventListener("message", closeHandler);
  });
})();
