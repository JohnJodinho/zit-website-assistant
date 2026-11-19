# ZIT Website Assistant API

This repository contains the FastAPI foundation for the ZIT website assistant. It uses Supabase PostgreSQL for durable application data and Alembic for schema changes. The backend does not call Gemini or Groq during Phase 1.

## Local setup

1. Use Python 3.12.
2. Create and activate a virtual environment.
3. Install dependencies with `python -m pip install -r requirements-dev.txt`.
4. Copy `.env.example` to `.env` and set `DATABASE_URL` to the already-created development Supabase project. Never commit `.env`.
5. Before changing the database, run the documented read-only checks in `RUNBOOK.md`.
6. Apply the migration with `python -m alembic upgrade head`.
7. Start the API with `python -m uvicorn app.main:app --reload`.

The health endpoint is `GET /api/v1/health`. Readiness is `GET /api/v1/ready` and reports the database, migration, telemetry queue and unpublished-release state.

## Admin key setup

After migrations are complete, run `python -m app.security.keys generate` in a private local terminal. Save the displayed raw key in the owner's password manager, and put only its displayed SHA-256 hash in `ADMIN_BOOTSTRAP_KEY_HASH`. Then run `python -m app.security.keys bootstrap`. The raw key is never stored in PostgreSQL. Do not send it in chat, commit it, or copy it to logs.

Admin API keys can later be created and revoked under `/admin/v1/api-keys`. A newly created key is returned only in that one creation response. Admin docs are off unless `PUBLIC_DOCS_ENABLED=true` and both `ADMIN_DOCS_USERNAME` and `ADMIN_DOCS_PASSWORD` are configured.

## Checks

```powershell
python -m ruff check app tests
python -m ruff format --check app tests
python -m mypy app
python -m pytest
```

Tests do not call AI providers. PostgreSQL integration tests are skipped unless
`PHASE1_TEST_DATABASE_URL` is set. Set it privately to a non-production database with
the Phase 1 migration applied. The audit integration test creates uniquely named temporary
API keys, audit rows, and request traces, then removes them when it finishes. Never point it
at production or share the connection URL.

The `assistant` database schema is private: `anon` and `authenticated` have no schema access.
The website should call this backend, not query Supabase tables directly. No owner action is
needed for RLS while the schema remains private. If a future design exposes these tables
through Supabase's Data API, first add and test table grants and row-level security policies
that match that access model.

Render deployment and Docker image validation are deferred. GitHub Actions runs lint, type
checks, and tests; it does not build a Docker image.
