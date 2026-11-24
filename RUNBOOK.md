# Backend runbook

## Database safety

Use the existing Supabase project configured in `.env` as the shared
development/production database. Never create a test database, point tests at a
different database, downgrade the shared database, or delete real content,
release history, audit records, or the owner's admin key.

Before a migration or database drill:

1. Confirm privately that `ENV=dev` and `DATABASE_URL` is the authorized
   Supabase connection. Never print or paste the URL.
2. Read the migration and its offline SQL before applying it.
3. Record the active release and chunk count in `STATE.md`.
4. Prefix temporary drill data with `zzdrill-`. Afterward, verify the baseline
   release and count, revoke temporary keys, archive drill releases, and retain
   audit rows.

The application uses the private `assistant` schema. The Alembic version is
stored in `public.alembic_version`. Keep the schema private and do not expose
its tables through Supabase's Data API.

## Install, migrate, and run

Use Python 3.12. Install with:

```powershell
python -m pip install -r requirements-dev.txt
```

Copy `.env.example` to `.env` and set the existing `DATABASE_URL` privately.
Configure `SESSION_PEPPER` for sessions, and the BGE/model credentials for
features that need them. Never commit `.env` or paste any of its values into
logs or chat.

Review current migration state:

```powershell
python -m alembic current
python -m alembic check
```

Generate and review SQL before applying a migration:

```powershell
python -m alembic upgrade head --sql
python -m alembic upgrade head
```

Do not run a downgrade on the shared database. Start the API locally with:

```powershell
python -m uvicorn app.main:app --reload
```

## Content releases

Preview local approved content without database writes or embedding requests:

```powershell
python -m app.content.cli dry-run
```

Review the preview and current release before staging through the admin API.
Staging uses the configured BGE 768-dimensional embedding service and creates
a draft; publishing requires the release validation and search evaluation to
pass. Check live release data read-only with:

```powershell
python -m scripts.check_release_live
```

The currently verified baseline is published release 2 with 274 chunks. Do
not assume a future release is correct from its ID alone; verify its content,
search results, and rollback path before publishing.

## Public chat

See [API_CONTRACT.md](./API_CONTRACT.md) for all public routes, JSON bodies,
error codes, and SSE event handling. Chat is disabled when rollout is zero or
the kill switch is active. Sessions expire after 30 minutes by default.
`TURNSTILE_ENABLED` defaults to `false`; when enabled, the server requires a
valid verification token and configured secret.

Text is masked for common PII patterns before provider calls, but masking is
best effort. Do not send personal or confidential data. Only free-confirmed
models should be enabled in `LLM_MODELS`; unknown quotas are not unlimited.
When every provider is unavailable, the service returns its fixed contact
reply.

## Health, traces, and routine checks

- `GET /api/v1/health` is liveness only.
- `GET /api/v1/ready` checks database connectivity, migration state, and
  snapshot readiness.
- Responses include `X-Request-ID`. Use it to find a trace through the
  authorized admin trace API.
- The application flushes telemetry asynchronously. Do not delete audit rows.
- Expired sessions are removed by the in-process nightly retention worker at
  02:00 UTC. The worker is stopped cleanly during application shutdown.

With the local API running and chat enabled, check the API and exact CORS
origin:

```powershell
python scripts/smoke_live.py --api http://127.0.0.1:8000 --origin http://localhost:5173
```

This script checks health, readiness, config/CORS, session creation, and a
complete chat stream. It sends a session request without a Turnstile token, so
keep Turnstile disabled for this local smoke check.

## Tests and checks

```powershell
python -m ruff check app tests scripts
python -m ruff format --check app tests scripts
python -m mypy app
python -m pytest
python scripts/final_check.py
```

The PostgreSQL integration test uses the configured shared `DATABASE_URL`,
refuses `ENV=prod`, and creates marked temporary rows. It removes its temporary
keys and traces but keeps immutable audit records. Do not run that test against
an unauthorized database. Unit and fake-provider tests do not call AI
providers.

The marked publish/rollback drill has already run and been verified. Its
read-only verification command is:

```powershell
python -m scripts.check_publish_rollback --verify
```

Do not rerun the publishing drill unless deliberately repeating an approved
database drill with a fresh baseline recorded in `STATE.md`.

## Common failures

| Symptom | First check |
|---|---|
| `/ready` returns 503 | Check `DATABASE_URL`, migration state, and active release; do not print the connection URL. |
| Session creation returns 503 | Check `SESSION_PEPPER` and database readiness. |
| Chat returns `assistant_not_available` | Check `ROLLOUT_PERCENT` and `KILL_SWITCH`. |
| Chat returns `assistant_not_in_rollout` | The request is outside the configured rollout percentage. |
| Chat returns `session_required` | Create a session and send its token in the chat JSON body. |
| Chat returns 429 | Respect the session/chat rate limit; do not retry in a tight loop. |
| Stream ends with an `error` event | Treat earlier deltas as partial; use the event code and request ID for diagnosis. |
| Search has no usable results | Check the active release and BGE embedding service readiness. |
| Admin request returns 401/403 | Check the key's validity and required scope; never expose the raw key. |
| CORS check fails | Set the exact browser origin in `WIDGET_ORIGINS`; wildcard origins are rejected. |
