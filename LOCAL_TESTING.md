# Local widget testing

The widget uses Node 22 and the backend API. The mock backend runs locally and makes no provider calls.

## Start the playground

1. Open a terminal in `widget/` and run `npm ci`.
2. Start the backend with the usual command, if it is not already running:
   `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
   Do not start Docker for this project.
3. In another terminal, run `npm run dev`.
4. Open `http://127.0.0.1:5173/playground.html`.
5. Use the device menu to check Phone (390 × 844), Small phone (320 × 568), Tablet (768 × 1024), Laptop (1366 × 768), Desktop (1920 × 1080), Landscape phone (844 × 390), and Full window. The frame scales to fit the available space.
6. Use the Backend menu to choose Local backend or Mock backend. The page shows the API and widget URLs it will use.

## Mock scenarios

Choose **Mock backend**, then select a response state. These states require no real AI provider:

| State | Expected result |
| --- | --- |
| Normal answer with links | Complete answer, link buttons, and feedback controls |
| Slow first word | Typing indicator remains visible before text arrives |
| Long answer with table and list | Long Markdown response renders and scrolls inside the conversation |
| Error after partial text | Partial answer is retained, marked incomplete, and can be retried |
| Stream ends without done | Answer is marked incomplete and can be retried |
| Rate limited (429) | A friendly wait message and countdown appear |
| Session expires, then recovers | The session refreshes once and the same message is retried |
| Assistant disabled | No launcher is shown |
| Maintenance message | Maintenance text and the normal contact option are shown |
| Busy capacity fallback | Answer is marked as a quick/degraded response |
| Message too long (413) | An inline message-length hint appears |
| Offline | The offline banner appears and sending is disabled |

Also check that opening the launcher creates the frame only on first open, closing returns focus to the launcher, the teaser can be dismissed, and a new chat clears the conversation. The playground page intentionally has forceful page styles, a sticky header, a floating button, and a cookie notice to exercise Shadow DOM isolation.

## Use the local backend

The local backend responds to the config request, but the current local CORS allow-list does not include the four Vite origins: preflight requests returned HTTP 400 and normal config responses did not include `Access-Control-Allow-Origin`. To use the local backend from the playground, append these exact origins to the existing comma-separated `WIDGET_ORIGINS` value in the backend `.env`:

```text
http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173
```

Keep any existing origins in that setting; do not replace them. Restart the backend after changing its environment. This project did not change backend code or environment files.

Sending a question to the real backend may invoke a configured model provider. Use that mode only when the provider is approved and the call is known to be no-cost. The automated checks use mocks and do not send provider requests.

## Test the production build locally

1. From `widget/`, run `npm run verify`.
2. Run `npm run preview`.
3. Open `http://localhost:4173/playground.html`. This uses the production build; development-only mock scenarios are not included.

For production-build testing against a local backend, provide `VITE_ASSISTANT_API_URL`, `VITE_ASSISTANT_WIDGET_URL`, and `VITE_PARENT_ORIGINS` in the same terminal before `npm run build`. Use the 4173 origins from the list above. The Vercel headers in `vercel.json` are not applied by Vite's local preview server.

## If something looks wrong

- Check the API and widget URLs shown below the playground.
- Confirm `npm run dev` or `npm run preview` is still running.
- Use Mock backend first to separate widget issues from backend or CORS issues.
- If the widget is blank on Local backend, check the browser's network panel for a CORS error and confirm `WIDGET_ORIGINS` includes the playground origin.
- If the frame is blocked, check the `frame-ancestors` policy and any Content Security Policy on the page hosting the widget.
- If a mock response does not match the table, reload the playground and select the state again.
- The automated checks do not take screenshots. Please make the final visual check at the listed sizes in your browser.
