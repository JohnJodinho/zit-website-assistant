# WIDGET STATE (updated 26 November 2026)

Phase: B — Approved widget build
Status: Complete

Done:
- Built the TypeScript/Tailwind widget, secure loader, playground, dev-only mock API, tests, Vercel config, and handover guides.
- Fixed the desktop/tablet flicker by making the embedding page's CSS viewport mode authoritative; removed iframe-to-loader mode feedback and passed the host mode to the composer.
- Added bridge/loader tests for validated host mode and parent-controlled panel mode.
- `npm run verify` passed: 28 tests, typecheck, lint, style/layout, secret scan, production build, bundle budgets, and mock exclusion.
- Production config and health endpoints returned HTTP 200. No paid provider request or browser screenshot was made.

Next:
- For local chat, set `ROLLOUT_PERCENT=100`, `KILL_SWITCH=false`, and an empty `MAINTENANCE_MESSAGE`; add the four Vite origins to `WIDGET_ORIGINS` and restart the backend.
- For production chat, choose a nonzero Render `ROLLOUT_PERCENT`, set `KILL_SWITCH=false`, and keep `MAINTENANCE_MESSAGE` empty for normal chat. Add the exact Vercel and school origins to `WIDGET_ORIGINS`.
- Visually review the playground at phone, landscape, tablet, laptop, and full-window sizes after the updated widget is published.

Open: Local CORS currently blocks all four Vite origins; real school domains and the Vercel origin must be supplied by the owner. The admin settings route does not update the app settings used by public config/chat; backend fix is out of widget scope.
Checks: `npm run verify` passed; the owner performs the visual check.
Last commit: host-mode stability and availability report.
