# WIDGET STATE (updated 26 November 2026)

Phase: B — Approved widget build
Status: Complete

Done:
- Built the TypeScript/Tailwind widget, secure loader, playground, dev-only mock API, tests, Vercel config, and handover guides.
- Fixed the desktop/tablet flicker by making the embedding page's CSS viewport mode authoritative; removed iframe-to-loader mode feedback and passed the host mode to the composer.
- Added bridge/loader tests for validated host mode and parent-controlled panel mode.
- Fixed the `postMessage` origin warning by waiting until the iframe loads before sending messages, including viewport updates; first-open initialization already opens the chat, and later opens use `zit:open`.
- Removed asynchronous composer autofocus that caused the browser focus-policy warning; the launcher click focuses the iframe, and keyboard navigation proceeds inside the widget.
- Replaced native composer form submission with explicit button and Enter-key handling. The iframe sandbox still blocks form navigation, and chat messages no longer attempt it.
- Added GFM URL autolinking for bare `https://`, `http://`, and `www.` URLs. Visible URL labels omit the scheme and leading `www.`, while explicit Markdown and API-provided labels remain intact; unsafe destinations are not rendered as links.
- Added `npm run test:urls` for six backend-independent URL-rendering tests.
- `npm run verify` passed: 37 tests, typecheck, lint, style/layout, secret scan, production build, bundle budgets, and mock exclusion. Gzip sizes: JavaScript 107.1 KB / 150 KB, CSS 19.2 KB / 25 KB, loader 3.6 KB / 6 KB.
- Production config and health endpoints returned HTTP 200. No paid provider request or browser screenshot was made.

Next:
- For local chat, set `ROLLOUT_PERCENT=100`, `KILL_SWITCH=false`, and an empty `MAINTENANCE_MESSAGE`; add the four Vite origins to `WIDGET_ORIGINS` and restart the backend.
- For production chat, choose a nonzero Render `ROLLOUT_PERCENT`, set `KILL_SWITCH=false`, and keep `MAINTENANCE_MESSAGE` empty for normal chat. Add the exact Vercel and school origins to `WIDGET_ORIGINS`.
- Visually review the playground at phone, landscape, tablet, laptop, and full-window sizes after the updated widget is published.

Open: Local CORS currently blocks all four Vite origins; real school domains and the Vercel origin must be supplied by the owner. The admin settings route does not update the app settings used by public config/chat; backend fix is out of widget scope.
Checks: `npm run verify` passed; the owner performs the visual check.
Last implementation commit: `0db8a9f` — bare URL autolinking and display labels.
