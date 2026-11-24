# Owner actions

These are production and content operations for the backend. They are separate
from the agent completion check: production hosting, real FAQ content, and
rollout are not required for `python scripts/final_check.py` to pass.

## 1. Confirm the local release

1. Run `python scripts/final_check.py` from the repository root.
2. The last line should read `RESULT: DONE`.
3. Keep the output and [STATE.md](./STATE.md) as the record of verified
   database and backend checks.

## 2. Configure the Render backend

1. In Render, create a Web Service for this repository and use the project's
   backend deployment settings.
2. Set the health check path to `/api/v1/health`.
3. In the service's **Environment** settings, add the values listed in
   [deploy/ENV_PRODUCTION.md](./deploy/ENV_PRODUCTION.md). Use `ENV=prod`.
4. Use the existing Supabase project for `DATABASE_URL`, as selected for this
   build. Keep connection URLs, API keys, and passwords in Render's secret
   settings; never put them in Git or chat.
5. Keep `ROLLOUT_PERCENT=0` for initial startup. Keep
   `TURNSTILE_ENABLED=false` unless its server-side secret and client token
   flow are configured.
6. Deploy, then check `/api/v1/health` and `/api/v1/ready`. Readiness should
   report the database, migration, and active release as ready.

## 3. Verify the deployed API

After setting an exact allowed origin in `WIDGET_ORIGINS` and enabling a
nonzero rollout for the smoke check, run:

```powershell
python scripts/smoke_live.py --api https://api.example.invalid --origin https://site.example.invalid
```

Replace both reserved example origins with the real origins privately. The
script checks health, readiness, config/CORS, session creation, and a complete
stream. It sends no Turnstile token, so keep Turnstile disabled during this
check.

## 4. Add and publish approved FAQs

1. Fill `deploy/faqs_template.csv` with approved ZIT questions and answers.
   Keep answer wording accurate and avoid personal information.
2. Use the `POST /admin/v1/faqs/bulk` example in `requests.http` with an admin
   key that has the required scope.
3. Review the resulting draft and search evaluation before publishing it.
4. Confirm the active release and search behavior using the checks in
   [RUNBOOK.md](./RUNBOOK.md).

## 5. Increase chat rollout

1. Start with `ROLLOUT_PERCENT=0`; this keeps public chat disabled.
2. When ready, use the authorized admin settings route to set a small rollout
   percentage. Monitor request traces, errors, and model usage.
3. Increase the percentage gradually only while the service is healthy.
4. To stop chat immediately, set `KILL_SWITCH` to `true`. To resume, turn it
   off and verify the rollout setting.

## If something goes wrong

| What you see | First thing to check |
|---|---|
| Render service does not start | Check the deployment log for the first application error; do not share secrets. |
| `/api/v1/health` fails | Check that the service is running and the health path is exact. |
| `/api/v1/ready` returns 503 | Check the private Supabase connection setting, migration state, and active release. |
| `GET /config` says `enabled: false` | Check `ROLLOUT_PERCENT` and `KILL_SWITCH`. |
| Session creation returns 503 | Check `SESSION_PEPPER` and database readiness. |
| Session creation returns 403 | Check Turnstile settings; the smoke script does not supply a token. |
| Chat returns `session_required` | Create a session and include its token in the chat request body. |
| Chat returns 429 | Respect the configured rate limits; do not retry repeatedly. |
| Answers fall back to the contact reply | Check the active release, BGE service, and free-only model configuration. |
| Admin requests return 401 or 403 | Check that the key is active and has the required scope. Never paste the raw key. |
