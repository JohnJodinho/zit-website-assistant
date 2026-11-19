# Phase 1 runbook

## Current status

- Phase 1 foundation is implemented and verified locally and against the development database.
- Do not deploy to Render yet; deployment is deferred to its later phase.
- Use the already-created Supabase project and its configured region.
- The GitHub repository exists. GitHub Actions checks lint, types, and tests; its first run is pending.
- Docker image validation is deferred at the owner's request.
- AI provider calls are not used by the Phase 1 app or tests.
- `SENTRY_DSN=placeholder` disables Sentry. Configure a real DSN only after creating the Sentry project and following the separate setup guide.
- The separate Sentry setup guide is maintained in the local planning materials.

## Database migration reference

Migration `0001_foundation` has been applied to the development Supabase project. For a new environment, confirm these read-only facts before migrating:

1. Database server version and current database identity.
2. Whether `vector` and `pgcrypto` are installed, and which schema contains them.
3. Whether the `assistant` schema or any `assistant` tables already exist.
4. Whether an Alembic version table or history already exists.
5. Whether the `assistant` schema is private and not exposed through the Supabase Data API; verify schema exposure and grants.

If `assistant` contains data or an unknown migration history, stop. Do not drop or overwrite it.

The app URL and migration URL may be configured separately. The app uses `DATABASE_URL`; Alembic uses `DATABASE_URL_DIRECT` when set and otherwise falls back to `DATABASE_URL`. Supabase endpoints use asyncpg's `ssl=require` mode by default: traffic is encrypted without requiring a separate certificate file. For certificate and hostname verification, set `sslmode=verify-full` and, if needed, point `DATABASE_SSL_ROOT_CERT` to the root CA downloaded from the Supabase Dashboard. Do not use unencrypted database connections. Percent-encode reserved characters in the database password when placing it in a URL; keep the URL private and never paste it into chat or logs.

## Admin key bootstrap

Run the local generation command in a private terminal, record the raw key in the owner's password manager, and put only its hash in `ADMIN_BOOTSTRAP_KEY_HASH`. Apply migrations first, then run `python -m app.security.keys bootstrap`. The bootstrap operation refuses to add a key if any API key already exists.

Do not include raw API keys, database URLs, DSNs or passwords in tickets, chat, logs, screenshots or the repository.

## Readiness and diagnostics

- `/api/v1/health` is liveness only and does not check the database.
- `/api/v1/ready` returns 503 until the database is reachable and the current migration is applied. It also reports telemetry queue/drop counts and that no content release is loaded.
- Every HTTP response includes `X-Request-ID`. The request trace and HTTP span are written asynchronously to PostgreSQL when the database is ready.
- Sentry remains off while the DSN is blank or `placeholder`.

## Later Render deployment

Deployment is deferred until the deployment stage starts. At that time, configure production secrets in Render, use the exact widget origins, apply Alembic migrations with the direct connection before switching traffic, and verify health, readiness, request tracing, logs and rollback instructions. Never store secrets in GitHub workflow files.
