# Production environment variables

Never put real secrets in this file or in Git. Copy names into the host's secret settings.

| Name | Required | Value format | Source |
|---|---|---|---|
| `ENV` | Yes | `prod` | Fixed |
| `DATABASE_URL` | Yes | Supabase session pooler URL | Supabase connection settings |
| `DATABASE_URL_DIRECT` | Recommended | Supabase direct PostgreSQL URL | Supabase connection settings |
| `DATABASE_SSL_ROOT_CERT` | Optional | CA certificate path | Supabase dashboard |
| `DB_POOL_SIZE` | Yes | Positive integer, default `8` | Host setting |
| `SESSION_PEPPER` | Yes | 32 or more random bytes | Generate locally |
| `ADMIN_BOOTSTRAP_KEY_HASH` | Yes | SHA-256 hash | Run `python -m app.security.keys generate` |
| `ADMIN_DOCS_USERNAME` | Optional | Username | Owner decision |
| `ADMIN_DOCS_PASSWORD` | Optional | Long password | Owner decision |
| `PUBLIC_DOCS_ENABLED` | Yes | `false` unless docs are needed | Fixed |
| `ZIT_API_KEY` | Yes | BGE service bearer key | Existing owner secret |
| `EMBEDDING_API_BASE_URL` | Yes | `https://...` | Existing BGE service |
| `EMBEDDING_MODEL` | Yes | `bge-base-768-v1` | Fixed |
| `EMBEDDING_DIMENSIONS` | Yes | `768` | Fixed |
| `GOOGLE_AI_API_KEY` | Optional | Google AI Studio key | Owner account |
| `GROQ_API_KEY` | Optional | Groq key | Owner account |
| `LLM_MODELS` | Yes | JSON model configuration | Copy approved file content |
| `ROLLOUT_PERCENT` | Yes | `0` for staff-only start | Fixed |
| `KILL_SWITCH` | Yes | `false` | Fixed |
| `MAINTENANCE_MESSAGE` | Yes | Short safe text | Fixed |
| `WIDGET_ORIGINS` | Yes | Exact Vercel origin | Vercel deployment |
| `FRAME_ANCESTORS` | Yes | Exact ZIT website origins | Web team |
| `VITE_ASSISTANT_API_URL` | Yes | Backend origin | Render deployment |
| `VITE_ASSISTANT_WIDGET_URL` | Yes | Widget origin | Vercel deployment |
| `VITE_TURNSTILE_SITE_KEY` | Optional | Public Turnstile site key | Cloudflare |
| `VITE_PARENT_ORIGINS` | Yes | Exact ZIT website origins | Web team |
| `VITE_PRIVACY_URL` | Optional | Public privacy URL | Owner |
| `TURNSTILE_SECRET` | Optional | Private Turnstile secret | Cloudflare |
| `SENTRY_DSN` | Optional | DSN or `placeholder` | Sentry project |

Generate `SESSION_PEPPER` with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
