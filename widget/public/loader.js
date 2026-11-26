var ZitAssistantLoader=(function(b){"use strict";const I=`:root,\r
:host {\r
  color-scheme: dark;\r
  --blue: #039fe0;\r
  --blue-hover: #0286bd;\r
  --blue-light: #4cc3f2;\r
  --navy: #0a2d4a;\r
  --page: #0b1622;\r
  --surface: #0e1c2b;\r
  --surface-soft: #102131;\r
  --ink: #e9f1f8;\r
  --muted: #a9b7c4;\r
  --line: #1f3347;\r
  --danger: #ff8a80;\r
  --success: #8bd6b4;\r
  --font-display: "Nunito Sans", "Segoe UI", sans-serif;\r
  --font-body: "Roboto", "Segoe UI", sans-serif;\r
  --text-small: 0.75rem;\r
  --text-base: 1rem;\r
  --text-large: 1.125rem;\r
  --space-1: 0.5rem;\r
  --space-2: 0.625rem;\r
  --space-3: 0.75rem;\r
  --space-4: 0.875rem;\r
  --space-5: 1rem;\r
  --space-6: 1.25rem;\r
  --space-7: 1.5rem;\r
  --space-8: 1.75rem;\r
  --space-9: 1.875rem;\r
  --radius-small: 1rem;\r
  --radius-card: 1.625rem;\r
  --radius-pill: 999px;\r
  --shadow-panel: 0 1.125rem 2.5rem rgb(0 0 0 / 35%);\r
  --shadow-accent: 0 1.125rem 2.5rem rgb(3 159 224 / 16%);\r
  --z-content: 1;\r
  --z-panel: 10;\r
  --z-loader: 95;\r
  --motion-fast: 150ms;\r
  --motion-base: 200ms;\r
  --motion-slow: 250ms;\r
  --ease-standard: cubic-bezier(0.2, 0.8, 0.2, 1);\r
  --breakpoint-phone: 37.5rem;\r
  --panel-width: 25rem;\r
  --panel-height: 40rem;\r
  --safe-top: env(safe-area-inset-top, 0px);\r
  --safe-right: env(safe-area-inset-right, 0px);\r
  --safe-bottom: env(safe-area-inset-bottom, 0px);\r
  --safe-left: env(safe-area-inset-left, 0px);\r
}\r
`,M=`:host {\r
  position: fixed;\r
  inset: 0;\r
  z-index: var(--z-loader);\r
  display: block;\r
  pointer-events: none;\r
  font-family: var(--font-body);\r
}\r
\r
.layer {\r
  position: fixed;\r
  inset: 0;\r
  pointer-events: none;\r
}\r
\r
.launcher,\r
.teaser,\r
.frame-shell {\r
  position: fixed;\r
  right: max(1.25rem, var(--safe-right));\r
  bottom: max(1.25rem, var(--safe-bottom));\r
  pointer-events: auto;\r
}\r
\r
:host([data-position="left"]) .launcher,\r
:host([data-position="left"]) .teaser,\r
:host([data-position="left"]) .frame-shell {\r
  right: auto;\r
  left: max(1.25rem, var(--safe-left));\r
}\r
\r
.launcher {\r
  display: inline-flex;\r
  min-width: 7.75rem;\r
  min-height: 3.25rem;\r
  align-items: center;\r
  justify-content: center;\r
  gap: var(--space-3);\r
  padding: 0 var(--space-6);\r
  border: 0;\r
  border-radius: var(--radius-pill);\r
  background: linear-gradient(135deg, var(--blue), var(--blue-hover));\r
  box-shadow: var(--shadow-accent);\r
  color: #fff;\r
  cursor: pointer;\r
  animation: launcher-pulse 900ms ease-out 1;\r
  font: 700 1rem var(--font-display);\r
  transition:\r
    transform var(--motion-base) var(--ease-standard),\r
    box-shadow var(--motion-base) var(--ease-standard);\r
}\r
\r
.launcher:hover {\r
  box-shadow: var(--shadow-panel);\r
  transform: translateY(-2px);\r
}\r
\r
.launcher:focus-visible,\r
.teaser button:focus-visible {\r
  outline: 3px solid var(--blue-light);\r
  outline-offset: 3px;\r
}\r
\r
.assistant-mark {\r
  display: grid;\r
  width: 1.75rem;\r
  height: 1.75rem;\r
  place-items: center;\r
  overflow: hidden;\r
  border-radius: 50%;\r
  background: rgb(255 255 255 / 16%);\r
}\r
\r
.assistant-mark img {\r
  width: 100%;\r
  height: 100%;\r
  object-fit: contain;\r
}\r
\r
.teaser {\r
  right: max(1.25rem, var(--safe-right));\r
  bottom: calc(max(1.25rem, var(--safe-bottom)) + 4.25rem);\r
  display: flex;\r
  max-width: min(21rem, calc(100vw - 2.5rem));\r
  align-items: flex-start;\r
  gap: var(--space-3);\r
  padding: var(--space-4) var(--space-5);\r
  border: 1px solid var(--line);\r
  border-radius: var(--radius-small);\r
  background: var(--surface);\r
  box-shadow: var(--shadow-panel);\r
  color: var(--ink);\r
  font-size: 0.9375rem;\r
  line-height: 1.45;\r
}\r
\r
:host([data-position="left"]) .teaser {\r
  right: auto;\r
  left: max(1.25rem, var(--safe-left));\r
}\r
\r
.teaser p {\r
  margin: 0;\r
}\r
\r
.teaser button {\r
  display: grid;\r
  width: 2.75rem;\r
  height: 2.75rem;\r
  flex: 0 0 auto;\r
  place-items: center;\r
  border: 0;\r
  border-radius: 50%;\r
  background: transparent;\r
  color: var(--muted);\r
  cursor: pointer;\r
}\r
\r
.frame-shell {\r
  --host-layout-mode: desktop;\r
  width: min(var(--panel-width), calc(100vw - 2.5rem));\r
  height: min(var(--panel-height), calc(100dvh - 2.5rem));\r
  overflow: hidden;\r
  border: 1px solid var(--line);\r
  border-radius: var(--radius-card);\r
  background: var(--page);\r
  box-shadow: var(--shadow-panel);\r
  opacity: 0;\r
  transform: translateY(0.5rem) scale(0.98);\r
  transition:\r
    opacity var(--motion-base) var(--ease-standard),\r
    transform var(--motion-base) var(--ease-standard);\r
}\r
\r
.frame-shell[data-open="true"] {\r
  opacity: 1;\r
  transform: translateY(0) scale(1);\r
}\r
\r
.frame-shell[hidden],\r
.teaser[hidden],\r
.launcher[hidden] {\r
  display: none;\r
}\r
\r
.frame-shell iframe {\r
  display: block;\r
  width: 100%;\r
  height: 100%;\r
  border: 0;\r
  background: var(--page);\r
}\r
\r
.frame-shell[data-mode="mobile"] {\r
  inset: 0;\r
  width: 100%;\r
  height: 100dvh;\r
  max-height: 100dvh;\r
  border: 0;\r
  border-radius: 0;\r
}\r
\r
.frame-shell[data-mode="mobile"] iframe {\r
  height: 100%;\r
}\r
\r
@media (max-width: 37.5rem), (max-height: 30rem) {\r
  .frame-shell {\r
    --host-layout-mode: mobile;\r
  }\r
\r
  .launcher {\r
    width: 3.5rem;\r
    min-width: 3.5rem;\r
    height: 3.5rem;\r
    padding: 0;\r
    border-radius: 50%;\r
  }\r
\r
  .launcher-label {\r
    position: absolute;\r
    width: 1px;\r
    height: 1px;\r
    overflow: hidden;\r
    clip-path: inset(50%);\r
    white-space: nowrap;\r
  }\r
}\r
\r
@media (prefers-reduced-motion: reduce) {\r
  *,\r
  *::before,\r
  *::after {\r
    animation-duration: 0.01ms !important;\r
    animation-iteration-count: 1 !important;\r
    transition-duration: 0.01ms !important;\r
  }\r
}\r
\r
@keyframes launcher-pulse {\r
  0% {\r
    box-shadow: var(--shadow-accent);\r
    transform: scale(1);\r
  }\r
  45% {\r
    box-shadow: 0 0 0 0.75rem rgb(3 159 224 / 12%);\r
    transform: scale(1.04);\r
  }\r
  100% {\r
    box-shadow: var(--shadow-accent);\r
    transform: scale(1);\r
  }\r
}\r
`;function x(e){return typeof e=="object"&&e!==null&&!Array.isArray(e)}function C(e){return x(e)&&typeof e.enabled=="boolean"&&typeof e.rollout_percent=="number"&&typeof e.maintenance_message=="string"&&typeof e.privacy_notice=="string"}function k(e){try{const n=new URL(e);return(n.protocol==="https:"||n.protocol==="http:")&&n.username===""&&n.password===""}catch{return!1}}const h={teaserDismissed:"zit-widget-teaser-dismissed",opened:"zit-widget-opened"};async function E(e){const{document:n,window:r,apiUrl:t,widgetUrl:o,position:l}=e;if(!k(t)||!k(o)||n.querySelector("[data-zit-assistant-loader]"))return null;const g=await N(t,e.fetcher??fetch);if(!g)return null;const i=n.createElement("div");i.dataset.zitAssistantLoader="true",i.dataset.position=l;const U=i.attachShadow({mode:"open"}),S=n.createElement("style");S.textContent=`${I.replace(":root",":host")}
${M}`,U.append(S);const v=n.createElement("div");v.className="layer";const d=j(n,o),p=$(n),a=n.createElement("div");a.className="frame-shell",a.hidden=!0,a.setAttribute("role","region"),a.setAttribute("aria-label","ZIT Assistant"),v.append(d,p,a),U.append(v),n.body.append(i);let s=null,w=0,c=z(r,a);a.dataset.mode=c;const f=new URL(o).origin,O=new URL(t).href.replace(/\/+$/,""),W=L(r,h.teaserDismissed)==="true",_=L(r,h.opened)==="true",u=()=>{const m=z(r,a);return m===c||(c=m,a.dataset.mode=c,s?.contentWindow?.postMessage({type:"zit:host-mode",mode:c},f)),c},q=()=>{delete a.dataset.open,a.hidden=!0,d.hidden=!1,d.setAttribute("aria-expanded","false"),d.focus()},y=m=>{Z(m,s,f,q,d,i)},H=()=>{u(),p.hidden=!0,A(r,h.opened,"true"),s||(s=n.createElement("iframe"),s.title="ZIT Assistant",s.setAttribute("referrerpolicy","no-referrer"),s.setAttribute("sandbox","allow-scripts allow-same-origin allow-popups"),s.src=o,s.addEventListener("load",()=>{const m=u();s?.contentWindow?.postMessage({type:"zit:init",apiUrl:O,mode:m,privacyNotice:g.privacy_notice},f)}),a.append(s)),a.hidden=!1,d.hidden=!0,d.setAttribute("aria-expanded","true"),r.requestAnimationFrame(()=>{a.hidden||(a.dataset.open="true")}),s.contentWindow?.postMessage({type:"zit:open"},f),s.focus()},P=()=>{p.hidden=!0,A(r,h.teaserDismissed,"true")};d.addEventListener("click",H),p.querySelector("button")?.addEventListener("click",P),r.addEventListener("message",y),r.addEventListener("resize",u),!W&&!_&&(w=r.setTimeout(()=>{a.hidden&&(p.hidden=!1)},8e3));const T=()=>{r.clearTimeout(w),r.removeEventListener("message",y),r.removeEventListener("resize",u)};return r.addEventListener("beforeunload",T,{once:!0}),{host:i,launcher:d,get iframe(){return s},destroy(){r.clearTimeout(w),r.removeEventListener("message",y),r.removeEventListener("resize",u),r.removeEventListener("beforeunload",T),i.remove()}}}function z(e,n){return e.getComputedStyle(n).getPropertyValue("--host-layout-mode").trim()==="mobile"?"mobile":"desktop"}async function N(e,n){const r=await n(`${e.replace(/\/+$/,"")}/api/v1/config`);if(!r.ok)return null;const t=await r.json();return R(t)}function R(e){return!C(e)||!e.enabled?null:e}function Z(e,n,r,t,o,l){if(!n||e.origin!==r||e.source!==n.contentWindow||!x(e.data)||typeof e.data.type!="string")return;const i={"zit:close":t,"zit:minimize":t,"zit:focus-launcher":()=>o.focus(),"zit:hide":()=>l.remove()}[e.data.type];i&&i()}function j(e,n){const r=e.createElement("button");r.className="launcher",r.type="button",r.setAttribute("aria-label","Ask ZIT"),r.setAttribute("aria-expanded","false");const t=e.createElement("span");t.className="assistant-mark",t.setAttribute("aria-hidden","true");const o=e.createElement("img");o.src=new URL("zit-mark.png",n).href,o.alt="",t.append(o);const l=e.createElement("span");return l.className="launcher-label",l.textContent="Ask ZIT",r.append(t,l),r}function $(e){const n=e.createElement("div");n.className="teaser",n.hidden=!0;const r=e.createElement("p");r.textContent="Questions about courses or applying? Ask me.";const t=e.createElement("button");return t.type="button",t.setAttribute("aria-label","Dismiss suggestion"),t.textContent="×",n.append(r,t),n}function L(e,n){try{return e.sessionStorage.getItem(n)}catch{return null}}function A(e,n,r){try{e.sessionStorage.setItem(n,r)}catch{return}}function D(){const e=document.currentScript;if(!(e instanceof HTMLScriptElement))return;const n=new URL(e.src,document.baseURI),r=e.dataset.apiUrl??"https://zit-website-assistant.onrender.com",t=e.dataset.widgetUrl??""??n.origin,o=e.dataset.position==="left"?"left":"right";r&&E({document,window,apiUrl:r,widgetUrl:t,position:o}).catch(()=>{console.warn("ZIT Assistant could not load its availability settings.")})}return D(),b.installLoader=E,Object.defineProperty(b,Symbol.toStringTag,{value:"Module"}),b})({});
