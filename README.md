# ZIT Website Assistant API

The project is a FastAPI backend for ZIT's website assistant. It uses the
shared Supabase PostgreSQL database for sessions, content, and telemetry. The
active content is release 2 with 274 chunks. Search embeddings use the
configured BGE 768-dimensional embedding service; text generation uses the
configured free-only Gemini/Groq model chain.

## Local setup

1. Use Python 3.12 and create a virtual environment.
2. Install dependencies with `python -m pip install -r requirements-dev.txt`.
3. Copy `.env.example` to `.env`. Set the existing `DATABASE_URL` privately;
   never create or use a separate test database. Set `SESSION_PEPPER` for
   public sessions and configure the embedding and model credentials needed
   for the checks you intend to run.
4. Apply migrations with `python -m alembic upgrade head` only when the schema
   needs an upgrade.
5. Start the API with `python -m uvicorn app.main:app --reload`.

The health endpoint is `GET /api/v1/health`. Readiness is
`GET /api/v1/ready`. Public request and streaming formats are documented in
[API_CONTRACT.md](./API_CONTRACT.md).

## Content and chat

`python -m app.content.cli dry-run` previews the local approved content input.
It does not write to the database or call the embedding service. Staging and
publishing are protected admin operations; review the current release and
search evaluation before changing live content. The importer validates
manifests, archive paths and limits, required source data, and 768-dimensional
BGE embeddings.

The public API creates expiring sessions, streams answers over SSE, accepts
feedback, and records supported client events. The backend applies rate limits,
best-effort PII masking, free-model quota controls, provider failover, an
exact-match answer cache, rollout controls, and a kill switch. PII masking is
best effort; clients should not send personal or confidential information.

## Admin key setup

Run `python -m app.security.keys generate` in a private terminal. Keep the raw
key in a password manager and put only its displayed hash in
`ADMIN_BOOTSTRAP_KEY_HASH` before running
`python -m app.security.keys bootstrap`. The raw key is returned only once.
Never put it in chat, logs, or tracked files. Admin docs are disabled unless
`PUBLIC_DOCS_ENABLED=true` and both admin docs credentials are configured.

## Validation

```powershell
python -m ruff check app tests scripts
python -m ruff format --check app tests scripts
python -m mypy app
python -m pytest
python scripts/final_check.py
```

The PostgreSQL integration test uses the configured `DATABASE_URL` and is
marked with `zzdrill-` data. It cleans its temporary keys and traces while
retaining immutable audit records. Run it only with `ENV=dev` and the
authorized shared Supabase project configured; it refuses `ENV=prod`. The
suite does not make live AI-provider calls.

## Database and operations

Application data lives in the private `assistant` schema. The website client
must use this API rather than query Supabase tables directly. Keep the schema
private; any future Data API exposure requires explicit grants and tested
row-level security policies.

For production environment values and backend operations, see
[deploy/ENV_PRODUCTION.md](./deploy/ENV_PRODUCTION.md) and
[RUNBOOK.md](./RUNBOOK.md). Owner-operated deployment, FAQ, and rollout steps
are in [OWNER_ACTIONS.md](./OWNER_ACTIONS.md).
