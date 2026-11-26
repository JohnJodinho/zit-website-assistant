# Vercel handover

The widget is a static Vite site. No backend deployment or paid provider call is part of this setup.

1. **Confirm the GitHub repository is pushed.** The Vercel project must use the pushed `JohnJodinho/zit-website-assistant` repository.

2. **Create the Vercel project.**
   - Root Directory: `widget`
   - Framework Preset: Vite
   - Install Command: `npm ci`
   - Build Command: `npm run build`
   - Output Directory: `dist`
   - Node.js: 22 (the package requires Node `>=22 <23`)
   
   The same settings are recorded in `widget/vercel.json`. A successful build produces the app, `/loader.js`, and `/playground.html`.

3. **Add the build-time environment variables.**

   | Name | Value / example | Required? | Public or private? |
   | --- | --- | --- | --- |
   | `VITE_ASSISTANT_API_URL` | `https://zit-website-assistant.onrender.com` | Yes | Public |
   | `VITE_ASSISTANT_WIDGET_URL` | Leave blank for the first build; then use the exact Vercel origin, such as `https://your-project.vercel.app` | After first deploy | Public |
   | `VITE_PARENT_ORIGINS` | Comma-separated exact origins: the Vercel origin and each school-site origin, with no paths or trailing slashes | Yes | Public |
   | `VITE_TURNSTILE_SITE_KEY` | Blank while Turnstile is off; later, the Cloudflare public site key | Optional | Public |
   | `VITE_PRIVACY_URL` | The school's privacy page URL, or blank | Optional | Public |
   | `VITE_CONTACT_URL` | The admissions/contact page URL, or blank | Optional | Public |

   These `VITE_` values are included in browser code. Do not put secrets in them. The build rejects a missing API URL or missing/invalid parent origins. The widget URL may be blank on the first deploy because the loader can use its own origin.

4. **Deploy once, then set the real Vercel origin.** Copy the deployed origin (origin only, not a path). Set `VITE_ASSISTANT_WIDGET_URL` to it and include it in `VITE_PARENT_ORIGINS`, along with the exact school-site origins. Redeploy. Including the Vercel origin lets the same-origin playground work.

5. **Allow the widget at the backend.** In Render, add the exact Vercel origin and each exact school-site origin to the existing comma-separated `WIDGET_ORIGINS` setting (no trailing slash or path), preserve other origins, and redeploy the backend. The loader fetches config from the school page; the iframe requests chat from Vercel, so both origins are needed. Then check `https://zit-website-assistant.onrender.com/api/v1/ready`. Do not add a wildcard origin.

6. **Allow only the real school pages to frame the widget.** In `widget/vercel.json`, replace the placeholder domains in this exact value with the school's real origins:

   ```text
   "value": "frame-ancestors 'self' https://your-school.example https://www.your-school.example;"
   ```

   Keep `'self'` so `/playground.html` can frame the widget on the Vercel origin. Add every real school origin explicitly; do not use `*`. Commit and redeploy. The actual school domains were not available during this build.

7. **Try the deployed playground.** Open `https://your-project.vercel.app/playground.html`, check desktop and phone layouts, and try the launcher, a new chat, links, and feedback. Mock responses are development-only and are not shipped in the production build. Sending real questions may invoke a model provider; only do so if the provider is approved and the call is known to be no-cost.

8. **Roll out safely.** The current production config reports `enabled: false` and `rollout_percent: 0`, so the loader correctly shows no launcher. In Render, set `KILL_SWITCH=false` and choose a nonzero `ROLLOUT_PERCENT` when ready; use `100` to include all visitors or a lower value for a staged rollout. Keep `MAINTENANCE_MESSAGE` empty for normal chat: a non-empty message is treated by the widget as maintenance and disables sending. The API contract has no staff-only `?assistant=on` bypass; staged rollout is percentage-based.

9. **Give the web team this script tag after replacing the placeholders:**

   ```html
   <script async
     src="https://your-project.vercel.app/loader.js"
     data-api-url="https://zit-website-assistant.onrender.com"
     data-widget-url="https://your-project.vercel.app"
     data-position="right"></script>
   ```

   If the school page has its own Content Security Policy, allow the Vercel origin in `script-src`, `frame-src`, and `img-src`, and the Render API origin in `connect-src`. The existing site may also need to permit the Vercel iframe under its own `frame-src` policy.

10. **Enable Turnstile later, only if wanted.** In Cloudflare, create a Turnstile widget for the school's actual hostname and copy its public site key to Vercel as `VITE_TURNSTILE_SITE_KEY`. In Render, set `TURNSTILE_ENABLED=true` and the private `TURNSTILE_SECRET`, then redeploy the backend and Vercel site. Never put the secret in Vercel's `VITE_` variables. Confirm by opening a new chat and checking that the challenge is completed before a session is created.

## If something goes wrong

| Symptom | First thing to check |
| --- | --- |
| No launcher | `GET /api/v1/config`; the loader intentionally stays hidden if the assistant is disabled |
| Launcher shows but panel is blank | `VITE_ASSISTANT_WIDGET_URL` and the Vercel deployment origin |
| CORS error | Render `WIDGET_ORIGINS` must contain the exact Vercel origin |
| Stuck on typing | Network tab for `/api/v1/chat/stream`; confirm SSE events reach the iframe |
| 429 message | Wait for the countdown and check backend rate-limit settings |
| Widget has wrong colors | Confirm the page loads the Vercel `loader.js`, not a cached old copy |
| Frame blocked | Check the school's `frame-src` and Vercel's `frame-ancestors` origins |
| Render is asleep or the first reply is slow | Wait for the backend to wake, then retry once |
| Build fails for missing configuration | Check Vercel's `VITE_ASSISTANT_API_URL` and exact `VITE_PARENT_ORIGINS` values |
| Playground cannot open the widget | Include the Vercel origin in `VITE_PARENT_ORIGINS`; keep `'self'` in `frame-ancestors` |
| Privacy or contact link is absent | Set `VITE_PRIVACY_URL` or `VITE_CONTACT_URL` and redeploy |
| Turnstile blocks session creation | Confirm the site key hostname and Render's private secret match |
