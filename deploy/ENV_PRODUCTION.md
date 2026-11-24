# Backend production environment

Set these in the backend host's private environment/secret settings. Never put
real values in this file, Git, screenshots, logs, or chat. The canonical
variable list is also in `.env.example`.

The selected deployment uses the existing Supabase project. `DATABASE_URL` is
the application connection; keep it private. Do not use a separate test
database. The application requires `ENV=prod`, `DATABASE_URL`, and
`SESSION_PEPPER` in production.

## Database, embedding, and runtime

| Variable | Production value or default | Notes |
|---|---|---|
| `ENV` | `prod` | Required. |
| `DATABASE_URL` | Existing Supabase PostgreSQL connection URL | Required by the application. Use the approved connection mode and keep the URL private. |
| `DATABASE_URL_SESSION` | Optional connection URL | Accepted configuration field; runtime database connections use `DATABASE_URL`. |
| `DATABASE_URL_DIRECT` | Optional direct PostgreSQL URL | Use for Alembic when the migration environment is configured to use it. |
| `DATABASE_SSL_ROOT_CERT` | Optional certificate file path | Leave unset when the Supabase SSL configuration is sufficient. |
| `DB_POOL_SIZE` | `8` | Positive integer; match the host's connection budget. |
| `ZIT_API_KEY` | BGE service bearer key | Required for embedding operations; configure as a secret. |
| `EMBEDDING_API_BASE_URL` | Approved HTTPS service origin | Must be an origin without credentials, path, or query. |
| `EMBEDDING_MODEL` | `bge-base-768-v1` | Fixed model. |
| `EMBEDDING_DIMENSIONS` | `768` | Must match the database vector dimension. |
| `EMBEDDING_TIMEOUT_SECONDS` | `100` | Positive timeout. |
| `WRITER_QUEUE_MAX` | `5000` | Telemetry queue capacity. |
| `WRITER_BATCH_ROWS` | `100` | Telemetry write batch size. |
| `WRITER_FLUSH_SECONDS` | `1` | Positive telemetry flush interval. |
| `ETL_MAX_JSON_MB` | `5` | Upload limit. |
| `ETL_MAX_ZIP_MB` | `20` | Upload limit. |
| `ETL_MAX_ZIP_FILES` | `500` | Upload limit. |
| `ETL_MAX_REMOVAL_PERCENT` | `15` | Content change guard, 0–100. |
| `ETL_MAX_COUNT_SWING_PERCENT` | `50` | Content change guard, 0–100. |
| `ETL_MISSING_SECTION_FAIL_PERCENT` | `10` | Content validation guard, 0–100. |
| `CHUNK_HARD_MAX_TOKENS` | `350` | Maximum chunk size. |
| `GATE_VECTOR_MIN` | `0.62` | Vector retrieval threshold. |
| `GATE_BM25_MIN` | `0.30` | BM25 retrieval threshold. |
| `GATE_BM25_MIN_DEGRADED` | `0.45` | BM25 threshold when vector retrieval is degraded. |
| `GATE_RETRIEVAL_MIN_HIT` | `0.95` | Search evaluation target. |
| `GATE_MAX_DROP_POINTS` | `0.02` | Maximum allowed evaluation drop. |
| `FAQ_DIRECT_SIM` | `0.90` | FAQ direct-answer similarity threshold. |

## Sessions, chat, and providers

| Variable | Production value or default | Notes |
|---|---|---|
| `SESSION_PEPPER` | At least 32 random bytes | Required secret. Generate privately with the command below. |
| `SESSION_TTL_MINUTES` | `30` | Session token lifetime. |
| `SESSION_MAX_HOURS` | `4` | Maximum session age guard. |
| `SESSION_CACHE_SECONDS` | `300` | Exact-match answer cache lifetime. |
| `SESSION_RATE_LIMIT_PER_MINUTE` | `10` | Session creation limit. |
| `CHAT_RATE_LIMIT_PER_MINUTE` | `30` | Chat request limit. |
| `MESSAGE_MAX_CHARS` | `500` | Maximum visitor message length. |
| `SSE_PING_SECONDS` | `15` | Keep-alive interval for chat streams. |
| `GOOGLE_AI_API_KEY` | Optional provider key | Secret. Use only a free-confirmed model configuration. |
| `GROQ_API_KEY` | Optional provider key | Secret. Use only a free-confirmed model configuration. |
| `LLM_MODELS` | Approved free-only JSON model list | Copy the approved configuration from `.env.example`; do not enable paid or unverified models. |
| `QUOTA_SAFETY_PER_MINUTE` | `0.90` | Fraction of configured per-minute quota used as the safety cap. |
| `QUOTA_SAFETY_DAILY` | `0.95` | Fraction of configured daily quota used as the safety cap. |
| `LLM_PRETOKEN_DEADLINE_S` | `12` | Generation deadline before first text. |
| `LLM_FIRST_TOKEN_TIMEOUT_S` | `8` | First-token timeout. |
| `LLM_MAX_ATTEMPTS` | `3` | Maximum provider attempts. |
| `BREAKER_FAILURES` | `3` | Failures before opening a model circuit breaker. |
| `BREAKER_MIN_OPEN_S` | `30` | Minimum breaker open time. |
| `FAST_GREETING` | `true` | Existing response fast path. |
| `FAST_THANKS_BYE` | `true` | Existing response fast path. |
| `FAST_CONTACT` | `true` | Existing response fast path. |
| `FAST_APPLY` | `true` | Existing response fast path. |
| `FAST_FIELD` | `true` | Existing response fast path. |
| `FAST_CATEGORY` | `true` | Existing response fast path. |
| `FAST_FAQ` | `true` | Existing response fast path. |

## Access, rollout, and diagnostics

| Variable | Production value or default | Notes |
|---|---|---|
| `WIDGET_ORIGINS` | Comma-separated exact browser origins | No wildcard, path, query, or trailing slash. Required when a browser client calls the API. |
| `TRUSTED_PROXY_HOPS` | `0` unless a trusted proxy is configured | Set to the actual trusted proxy hop count only. |
| `ADMIN_IP_ALLOWLIST` | Empty unless network restrictions are used | Comma-separated IP addresses or CIDR networks. |
| `ADMIN_BOOTSTRAP_KEY_HASH` | Optional one-time bootstrap hash | Only needed when bootstrapping the first admin key; never put the raw key here. |
| `ADMIN_DOCS_USERNAME` | Optional | Set with the password only when enabling admin docs. |
| `ADMIN_DOCS_PASSWORD` | Optional secret | Set with the username only when enabling admin docs. |
| `PUBLIC_DOCS_ENABLED` | `false` | Keep disabled unless admin docs are intentionally enabled. |
| `TURNSTILE_ENABLED` | `false` | The default. If enabled, also configure `TURNSTILE_SECRET` and send a verification token on session creation. |
| `TURNSTILE_SECRET` | Optional secret | Required when `TURNSTILE_ENABLED=true`. |
| `TURNSTILE_FAIL_OPEN_PER_MINUTE` | `1` | Rate limit for temporary Turnstile verification failures. |
| `ROLLOUT_PERCENT` | `0` | Start disabled; change only through the authorized rollout process. |
| `KILL_SWITCH` | `false` | Set true to stop public chat immediately. |
| `MAINTENANCE_MESSAGE` | `ZIT assistant is temporarily unavailable.` | Safe message shown while the assistant is unavailable. |
| `LOG_LEVEL` | `INFO` | Use a supported level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `GIT_SHA` | `local` | Set to the deployed revision when available. |
| `SENTRY_DSN` | `placeholder` | Optional; blank or `placeholder` disables Sentry. |
| `OTLP_ENDPOINT` | Empty | Optional OpenTelemetry collector endpoint. |

Generate `SESSION_PEPPER` in a private terminal:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

For the API routes, error shapes, CORS behavior, and SSE protocol, see
[`API_CONTRACT.md`](../API_CONTRACT.md). Local setup and operational checks are
in [`RUNBOOK.md`](../RUNBOOK.md).
