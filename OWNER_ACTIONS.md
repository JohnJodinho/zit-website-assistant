# What you do after the final stage

**Draft note for the agent:** Keep this structure and plain English. Replace every `<...>` with the real value from this build. Remove or add steps so everything is true. Do not add real secrets or real URLs.

This guide is for you, John. You do not need to write or read code. Each step says what to do and what you should see when it worked.

Order matters. Do the parts in order.

---

## Part 1. Check the build is finished (5 minutes)

1. Open the project and run: `python scripts/final_check.py`
2. You should see `RESULT: DONE` on the last line.
3. Anything marked `SKIPPED` or `BLOCKED` is listed in `FINAL_STATUS.md` with the reason. Read that list once.
4. Items marked `OWNER` are the steps below. They are not problems.

## Part 2. Make fresh secrets for production (10 minutes)

Never reuse your development secrets in production.

1. **Google and Groq keys:** In Google AI Studio, create a new key for a project with billing off. Do the same in Groq. Save both in your password manager. Delete the old development keys.
2. **Session secret (`SESSION_PEPPER`):** Run `<command from deploy/ENV_PRODUCTION.md>`. Save the result in your password manager.
3. **Admin key:** Your admin key is already in your password manager. If you want a fresh one for production, run `<command>` and follow `RUNBOOK.md` section `<name>`.
4. **Admin docs login (optional):** Only if you want the admin web page (`/admin/docs`). Pick a username and a long password. Otherwise leave it off.

You will paste these into Render in Part 5. Do not send them in chat.

## Part 3. Cloudflare Turnstile (10 minutes)

Turnstile is the check that stops bots from opening chats.

1. Log in to Cloudflare and open Turnstile.
2. Add a site. For the hostname, use your Vercel widget address from Part 6. If you do not have it yet, come back to this step after Part 6.
3. Copy the **site key** (public) and the **secret key** (private).
4. You will use the site key in Vercel and the secret in Render.

## Part 4. Telegram alerts (optional, 10 minutes)

Skip this if you want. The assistant works without it. You will just not get phone alerts.

1. In Telegram, message `@BotFather` and create a bot. Copy the token.
2. Send any message to your new bot. Then find your chat id using `<steps from RUNBOOK.md>`.
3. You will add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in Render.

## Part 5. Create the backend on Render

1. In Render, click **New**, then **Web Service**, and connect your GitHub repository.
2. Choose the **Docker** option. The project has a `Dockerfile`. (If the first build fails, copy the last 30 lines of the build log and give them to the agent. This is the Docker setup you planned to do at this point.)
3. Pick a plan that is **always on** (not a free plan that sleeps). This has a monthly cost, so decide before you click.
4. Pick a region close to your Supabase project.
5. Set the number of instances to **1**. The app keeps its memory in one process on purpose.
6. Health check path: `/api/v1/health`
7. Open `deploy/ENV_PRODUCTION.md`. It lists every variable, where to get it and what to type. Add them in Render under **Environment**. Important ones:
   - `ENV=prod`
   - `DATABASE_URL` (Supabase **session pooler** address, port 5432) and `DATABASE_URL_DIRECT` if you have one
   - `ZIT_API_KEY` and `EMBEDDING_API_BASE_URL` for your Hugging Face Space
   - `GOOGLE_AI_API_KEY` and `GROQ_API_KEY` (the new ones)
   - `SESSION_PEPPER`, `ADMIN_BOOTSTRAP_KEY_HASH` if needed
   - `TURNSTILE_SECRET`
   - `LLM_MODELS` (use the value given in the file, with your real free limits)
   - `ROLLOUT_PERCENT=0` (nobody sees the chat yet, which is correct)
   - `WIDGET_ORIGINS` and `FRAME_ANCESTORS`: leave a placeholder for now. You fill them in Part 7.
8. Click **Create Web Service** and wait for the deploy.
9. Open `https://<your-render-address>/api/v1/ready`. You should see that the database is reachable and a release is loaded.

## Part 6. Put the chat window on Vercel

1. In Vercel, click **Add New Project** and import the same GitHub repository.
2. Set **Root Directory** to `widget`.
3. Add environment variables from `deploy/ENV_PRODUCTION.md` (the ones starting with `VITE_`). The Render address goes in `VITE_ASSISTANT_API_URL`. The Turnstile **site** key goes in `VITE_TURNSTILE_SITE_KEY`. These are public values, never put secrets here.
4. Deploy. Copy the address Vercel gives you (for example `https://something.vercel.app`).
5. Go back to Cloudflare Turnstile (Part 3) and add this address as the hostname if you have not.

## Part 7. Tell the backend where the widget lives

1. In Render, set `WIDGET_ORIGINS` to the Vercel address (no slash at the end).
2. In Vercel, set `FRAME_ANCESTORS` to the website addresses (`https://www.zibeh.ng https://zibeh.ng`) and `VITE_PARENT_ORIGINS` to the same websites.
3. Redeploy both so the new values apply.

## Part 8. Test it with the built-in checker

1. Run: `python scripts/smoke_live.py --api <render-address> --widget <vercel-address>`
2. Every line should say PASS. If a line says FAIL, it prints a one-line fix hint. Fix it and run again.
3. Then open the Vercel address in a browser on your phone and your laptop, ask three questions, and make sure answers appear word by word.

## Part 9. Add your 20 FAQs

1. Open `deploy/faqs_template.csv`. Fill one row per question. Write answers exactly as you want visitors to see them. Add 3 to 5 other ways people ask the same thing in the variants column.
2. Upload them with the bulk call shown in `requests.http` (`POST /admin/v1/faqs/bulk`). If any row is wrong, nothing is saved and you get a list of the bad rows.
3. Check the draft with the diff call. Then publish. `RUNBOOK.md` section `<name>` shows each call.
4. Ask each FAQ in the chat. It should answer instantly.

## Part 10. Ask the web team to add one line

Send them the script tag from `deploy/ENV_PRODUCTION.md` (it has your real addresses filled in). If their site uses a Content-Security-Policy, also tell them to allow your Vercel address in `script-src` and `frame-src`. After that you never need them again.

Before they do it, you can test on the real site yourself by adding `?assistant=on` to a page address once the script is live.

## Part 11. Open it slowly

1. Start at `ROLLOUT_PERCENT=0`. Only staff with `?assistant=on` see it.
2. After a few days with no problems: 10 percent for 2 days, then 50, then 100.
3. To change the percent, use the settings call in `requests.http` (`PATCH /admin/v1/settings`). No redeploy needed.
4. **Emergency switch:** set `KILL_SWITCH` to true the same way. The chat disappears from the website at once.

## Part 12. Keep things safe and healthy

- **Embedding Space:** Hugging Face free Spaces sleep. If yours sleeps, search stops working. Use a paid always-on option, or set up an uptime monitor that opens the Space address every few minutes. `<exact advice from build>`
- **Uptime monitor:** Create a free monitor (for example UptimeRobot or Better Stack) that checks `https://<render-address>/api/v1/health` every 5 minutes and emails you.
- **Sentry (optional):** Create a project, copy its DSN and set `SENTRY_DSN` in Render. Leave it as `placeholder` to keep it off.
- **Backups:** Check what your Supabase plan includes. Free plans may not have daily backups. If not, run the backup steps in `RUNBOOK.md` weekly, and do one test restore before launch.
- **Privacy notice:** Get the notice approved (the Nigeria Data Protection Act applies). Then set the privacy page address in `VITE_PRIVACY_URL` and redeploy the widget.
- **Phone testing:** Test once on Android Chrome and once on iPhone Safari.
- **Google key and billing:** Look at the Google AI Studio usage page weekly in the first month. Keep billing off.

## Part 13. First week routine

1. Every morning for the first week: open the metrics call (`GET /admin/v1/metrics/summary?since=24h`). Look at the "not sure" rate and errors.
2. If you see a bad answer, follow the fix loop in `RUNBOOK.md`: find the trace, fix the chunk or add a FAQ, check it, publish.
3. If free Gemini limits run out, the chat shows a polite "please contact admissions" reply. That is by design. Do not turn on billing.

## If something goes wrong

| What you see | First thing to check |
| --- | --- |
| Render build fails | Copy the last 30 lines of the log and give them to the agent |
| `/api/v1/ready` says database not reachable | `DATABASE_URL` in Render (port 5432 session pooler, password encoded) |
| `/ready` says no release loaded | Release not published; see `RUNBOOK.md` publish steps |
| Chat window does not appear | `ROLLOUT_PERCENT` is 0 (use `?assistant=on`), or the script tag is missing, or `WIDGET_ORIGINS` is wrong |
| Chat window appears but never answers | `WIDGET_ORIGINS` and CORS; Turnstile hostname; the browser console message |
| Everyone gets "high demand" replies | Gemini free limit used up, or `LLM_MODELS` has the model disabled |
| Answers say "I do not have that" too often | Search is failing: check the embedding Space is awake |
| Chat window blank on the website | `FRAME_ANCESTORS` is missing the website address, or the website blocks iframes |
| Admin calls return 401 | Wrong or revoked admin key |
| Crawl upload fails with 409 | Another run is still going; wait or discard it |
