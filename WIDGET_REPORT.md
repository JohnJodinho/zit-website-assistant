# Widget Phase B report

## What was built

The TypeScript/Tailwind chat app, API client and SSE reader, session retry, Shadow DOM loader, playground and development mock backend, responsive chat states, tests, Vercel configuration, and owner handover guides are in place. Backend files and environment values were not changed.

## Verification

`npm run verify` passed:

- strict typecheck
- ESLint and accessibility rules
- style and layout rules
- 26 Vitest/jsdom tests
- secret scan
- production app and loader build
- gzip budgets
- mock-code exclusion from `dist/`

Gzip sizes from the passing check: app JavaScript 93.2 KB / 150 KB; CSS 19.2 KB / 25 KB; loader 3.5 KB / 6 KB.
The development playground and mock API returned HTTP 200; the rate-limit mock returned HTTP 429. The production preview served `/`, `/playground.html`, `/parent.html`, and `/loader.js` with HTTP 200.

Production dependency audit: 0 vulnerabilities. The full development dependency tree reports 7 moderate advisories; no high or critical advisories remain. No package published within the last 14 days was used to address them.

ESLint passes; `jsx-ast-utils` prints a non-fatal notice about resolving a `MetaProperty` expression.

## Backend notes

- Production `GET /api/v1/config` and `GET /api/v1/health` both returned HTTP 200.
- Local config requests returned HTTP 200, but CORS preflights for `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:4173`, and `http://127.0.0.1:4173` returned HTTP 400, and the normal responses did not include `Access-Control-Allow-Origin`. Append those four origins to the existing backend `WIDGET_ORIGINS` value, then restart the backend. This is also in `LOCAL_TESTING.md`.
- No live model/provider request was made to avoid any paid AI call. Real backend chat remains unverified; mocked chat, SSE, session retry, validation errors, URL checks, feedback replacement, and interrupted/error streams are covered by tests.
- No browser screenshots or browser automation were used. The owner should make the visual check through the playground.

Implementation commit: `e9f979e65c0fecf28d44ee0b5b8eaef7f4c96262`.
