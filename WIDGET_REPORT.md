# Widget Phase B report

## What was built

The TypeScript/Tailwind chat app, API client and SSE reader, session retry, Shadow DOM loader, playground and development mock backend, responsive chat states, tests, Vercel configuration, and owner handover guides are in place. Backend files and environment values were not changed.

## Fixes in this update

- The parent page now decides whether the widget is in phone or desktop layout. The loader reads that mode from its own responsive CSS and sends it to the iframe. The iframe no longer reports its own resized width back to the loader, which removes the resize feedback loop that caused the large-viewport flicker.
- The composer uses the parent-provided layout mode for Enter-key behavior, rather than guessing from the compact iframe width.
- The loader now waits for the iframe's `load` event before sending any messages to it, including viewport updates. On first open, `zit:init` opens the panel; `zit:open` is sent only on later opens. This prevents messages from targeting the configured widget origin while the iframe is still on its inherited-origin blank page.
- Removed the app's asynchronous automatic focus on the composer. The launcher click focuses the iframe itself, so keyboard focus enters the widget without triggering the browser's `focus-without-user-activation` warning. Visitors can tab to the composer normally.
- The existing availability behavior is preserved: disabled config means no launcher; a maintenance message with enabled config is shown and sending stays disabled. The backend config must be corrected for normal chat; changing this display rule would conflict with the widget contract.
- Added focused tests for valid host-mode initialization, keeping panel mode controlled by the parent viewport, and waiting for iframe readiness before messaging it.

## Verification

`npm run verify` passed after these changes:

- strict TypeScript check
- ESLint and accessibility rules
- style/layout rules
- 29 Vitest/jsdom tests
- secret scan
- production app and loader build
- gzip budgets
- mock-code exclusion from `dist/`

Gzip sizes: app JavaScript 93.2 KB / 150 KB; CSS 19.2 KB / 25 KB; loader 3.6 KB / 6 KB. ESLint also printed its existing non-fatal `jsx-ast-utils` MetaProperty notice.

Implementation commit: `fe78421`.

## Backend notes

- Production `GET /api/v1/config` and `GET /api/v1/health` both returned HTTP 200.
- The last observed local config was enabled at 100%, but its non-empty `MAINTENANCE_MESSAGE` made the widget display maintenance and disable sending. Set the local backend environment to `ROLLOUT_PERCENT=100`, `KILL_SWITCH=false`, and `MAINTENANCE_MESSAGE=` for normal chat, then restart it.
- The last observed production config was disabled at 0%, so the loader correctly shows no launcher. In Render, choose a nonzero `ROLLOUT_PERCENT` (100 for all visitors), set `KILL_SWITCH=false`, and keep `MAINTENANCE_MESSAGE` empty for normal chat. Restart/redeploy the backend after changing its effective environment.
- The admin settings route persists rollout and maintenance values in the database, but the public config and chat availability checks read the app's startup settings. Admin-setting changes therefore do not update runtime availability. This is a backend issue and was not changed; use the effective Render/local environment settings until the backend is updated.
- Local CORS preflights for `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:4173`, and `http://127.0.0.1:4173` returned HTTP 400, and the normal responses did not include `Access-Control-Allow-Origin`. Append those four origins to the existing backend `WIDGET_ORIGINS` value, then restart the backend. This is also in `LOCAL_TESTING.md`.
- No live model/provider request was made to avoid any paid AI call. Real backend chat remains unverified; mocked chat, SSE, session retry, validation errors, URL checks, feedback replacement, and interrupted/error streams are covered by tests.
- No browser screenshots or browser automation were used. The owner should make the visual check through the playground.
- No live browser session was available for checking the two reported console messages directly. The first is covered by the new iframe-ready messaging test; the focus warning is prevented by removing the asynchronous textarea focus call. The owner can confirm both in the playground using either `localhost` or `127.0.0.1`.

## Owner actions

These settings control different things:

| Setting | Meaning |
| --- | --- |
| `ROLLOUT_PERCENT=0` | No users are included; config is disabled and the loader shows no launcher. |
| `ROLLOUT_PERCENT=1` to `99` | A staged rollout; some users may still be rejected. |
| `ROLLOUT_PERCENT=100` | Include all users, unless the kill switch is on. |
| `KILL_SWITCH=true` | Turn public chat off immediately, regardless of rollout. |
| `KILL_SWITCH=false` | Allow the rollout percentage to decide access. |
| `MAINTENANCE_MESSAGE` with text | The widget displays maintenance and disables sending. |
| Empty `MAINTENANCE_MESSAGE` | Normal chat is possible when rollout is enabled and the kill switch is off. |

1. For local chat, update the backend `.env` values noted above and append the four exact Vite origins to its existing `WIDGET_ORIGINS`; restart the local backend.
2. In Render, set the intended nonzero rollout, `KILL_SWITCH=false`, and an empty maintenance message when ready to serve chats. Keep the existing origin list and add the Vercel and school-site origins as documented in `VERCEL_HANDOVER.md`.
3. Use the playground to verify phone, landscape, tablet, laptop, and full-window layouts after the updated widget is published. Do not send a real question unless its provider call is approved and known to be no-cost.
