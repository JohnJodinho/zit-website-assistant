# ZIT Website Assistant API

This repository contains the FastAPI foundation for the ZIT website assistant. It uses Supabase PostgreSQL for durable application data and Alembic for schema changes. The backend supports direct Gemini and Groq generation adapters behind the free-only model configuration.

## Local setup

1. Use Python 3.12.
2. Create and activate a virtual environment.
3. Install dependencies with `python -m pip install -r requirements-dev.txt`.
4. Copy `.env.example` to `.env` and set `DATABASE_URL` to the already-created development Supabase project. Never commit `.env`.
5. Before changing the database, run the documented read-only checks in `RUNBOOK.md`.
6. Apply the migration with `python -m alembic upgrade head`.
7. Start the API with `python -m uvicorn app.main:app --reload`.

The health endpoint is `GET /api/v1/health`. Readiness is `GET /api/v1/ready` and reports the database, migration, telemetry queue and unpublished-release state.

## Phase 2 local content dry-run

With the approved crawl and frontend source available at their default paths under `misc/`, run:

```powershell
python -m app.content.cli dry-run
```

This reads the local crawl and supporting JSON, reports course chunks and source counts, and makes
no database writes or embedding requests. It is a preview only; review the output before approving
any future content staging.

The importer verifies the approved crawl ID, manifest counts, direct Markdown, and both supporting
course JSON sources. It ignores query-page artifacts, reports source conflicts, fills only missing
crawl fields when the JSON sources agree, and preserves unknown course sections as chunks.

## Phase 2 content operations

Admin ETL and content APIs are protected by the existing bearer API keys. For upload examples, see
[requests.http](./requests.http). The bounded ZIP must contain the approved crawl export and both
approved website JSON files. `dry_run` is read-only. `stage` writes a draft and calls the configured
BGE embedding service. The owner approved the initial stage: one validated draft containing 65
documents, 274 unique chunks, 114 links, and 274 BGE embeddings is in the shared Supabase project.
No release has been published.

Release data checks and snapshot loading are implemented. Publish and rollback require a passing search evaluation. Public chat is implemented behind rollout and kill-switch settings.

Migration `0002_phase2_content` is applied to the shared Supabase project. For future long-running
ETL staging, use a Supabase session-pooler connection (port 5432) or a reachable direct connection
for `DATABASE_URL`; transaction-pooler mode (port 6543) dropped connections during staging.
Keep the connection URL private.

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

The normal test suite needs neither AI credentials nor a database. The optional Phase 1
PostgreSQL audit integration test runs only when `PHASE1_TEST_DATABASE_URL` is set. You do not
need to create a test database; leave this unset when no isolated disposable database is
available. Do not point that test at the shared development database that will later serve
production.

The `assistant` database schema is private: `anon` and `authenticated` have no schema access.
The website should call this backend, not query Supabase tables directly. No owner action is
needed for RLS while the schema remains private. If a future design exposes these tables
through Supabase's Data API, first add and test table grants and row-level security policies
that match that access model.

Render deployment and Docker image validation are deferred. GitHub Actions runs lint, type
checks, and tests; it does not build a Docker image.
