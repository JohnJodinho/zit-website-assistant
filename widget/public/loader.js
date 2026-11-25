var ZitAssistantLoader=(function(f){"use strict";const L=`:root,\r
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
`,U=`:host {\r
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
`;function w(e){return typeof e=="object"&&e!==null&&!Array.isArray(e)}function S(e){return w(e)&&typeof e.enabled=="boolean"&&typeof e.rollout_percent=="number"&&typeof e.maintenance_message=="string"&&typeof e.privacy_notice=="string"}function y(e){try{const n=new URL(e);return(n.protocol==="https:"||n.protocol==="http:")&&n.username===""&&n.password===""}catch{return!1}}const p={teaserDismissed:"zit-widget-teaser-dismissed",opened:"zit-widget-opened"};async function x(e){const{document:n,window:r,apiUrl:t,widgetUrl:i,position:l}=e;if(!y(t)||!y(i)||n.querySelector("[data-zit-assistant-loader]"))return null;const u=await T(t,e.fetcher??fetch);if(!u)return null;const d=n.createElement("div");d.dataset.zitAssistantLoader="true",d.dataset.position=l;const c=d.attachShadow({mode:"open"}),A=n.createElement("style");A.textContent=`${L.replace(":root",":host")}
${U}`,c.append(A);const h=n.createElement("div");h.className="layer";const o=R(n,i),m=C(n),a=n.createElement("div");a.className="frame-shell",a.hidden=!0,a.setAttribute("role","region"),a.setAttribute("aria-label","ZIT Assistant"),h.append(o,m,a),c.append(h),n.body.append(d);let s=null,b=0;const g=new URL(i).origin,Z=new URL(t).href.replace(/\/+$/,""),j=k(r,p.teaserDismissed)==="true",$=k(r,p.opened)==="true",D=()=>{delete a.dataset.open,a.hidden=!0,o.hidden=!1,o.setAttribute("aria-expanded","false"),o.focus()},v=q=>{N(q,s,g,D,o,d,a)},O=()=>{m.hidden=!0,E(r,p.opened,"true"),s||(s=n.createElement("iframe"),s.title="ZIT Assistant",s.setAttribute("referrerpolicy","no-referrer"),s.setAttribute("sandbox","allow-scripts allow-same-origin allow-popups"),s.src=i,s.addEventListener("load",()=>{s?.contentWindow?.postMessage({type:"zit:init",apiUrl:Z,privacyNotice:u.privacy_notice},g)}),a.append(s)),a.hidden=!1,o.hidden=!0,o.setAttribute("aria-expanded","true"),r.requestAnimationFrame(()=>{a.hidden||(a.dataset.open="true")}),s.contentWindow?.postMessage({type:"zit:open"},g),s.focus()},_=()=>{m.hidden=!0,E(r,p.teaserDismissed,"true")};o.addEventListener("click",O),m.querySelector("button")?.addEventListener("click",_),r.addEventListener("message",v),!j&&!$&&(b=r.setTimeout(()=>{a.hidden&&(m.hidden=!1)},8e3));const z=()=>{r.clearTimeout(b),r.removeEventListener("message",v)};return r.addEventListener("beforeunload",z,{once:!0}),{host:d,launcher:o,get iframe(){return s},destroy(){r.clearTimeout(b),r.removeEventListener("message",v),r.removeEventListener("beforeunload",z),d.remove()}}}async function T(e,n){const r=await n(`${e.replace(/\/+$/,"")}/api/v1/config`);if(!r.ok)return null;const t=await r.json();return I(t)}function I(e){return!S(e)||!e.enabled?null:e}function N(e,n,r,t,i,l,u){if(!n||e.origin!==r||e.source!==n.contentWindow||!w(e.data)||typeof e.data.type!="string")return;const c={"zit:close":t,"zit:minimize":t,"zit:focus-launcher":()=>i.focus(),"zit:hide":()=>l.remove()}[e.data.type];if(c){c();return}e.data.type==="zit:mode"&&(e.data.mode==="mobile"||e.data.mode==="desktop")&&(u.dataset.mode=e.data.mode)}function R(e,n){const r=e.createElement("button");r.className="launcher",r.type="button",r.setAttribute("aria-label","Ask ZIT"),r.setAttribute("aria-expanded","false");const t=e.createElement("span");t.className="assistant-mark",t.setAttribute("aria-hidden","true");const i=e.createElement("img");i.src=new URL("zit-mark.png",n).href,i.alt="",t.append(i);const l=e.createElement("span");return l.className="launcher-label",l.textContent="Ask ZIT",r.append(t,l),r}function C(e){const n=e.createElement("div");n.className="teaser",n.hidden=!0;const r=e.createElement("p");r.textContent="Questions about courses or applying? Ask me.";const t=e.createElement("button");return t.type="button",t.setAttribute("aria-label","Dismiss suggestion"),t.textContent="×",n.append(r,t),n}function k(e,n){try{return e.sessionStorage.getItem(n)}catch{return null}}function E(e,n,r){try{e.sessionStorage.setItem(n,r)}catch{return}}function M(){const e=document.currentScript;if(!(e instanceof HTMLScriptElement))return;const n=new URL(e.src,document.baseURI),r=e.dataset.apiUrl??"https://zit-website-assistant.onrender.com",t=e.dataset.widgetUrl??""??n.origin,i=e.dataset.position==="left"?"left":"right";r&&x({document,window,apiUrl:r,widgetUrl:t,position:i}).catch(()=>{console.warn("ZIT Assistant could not load its availability settings.")})}return M(),f.installLoader=x,Object.defineProperty(f,Symbol.toStringTag,{value:"Module"}),f})({});
