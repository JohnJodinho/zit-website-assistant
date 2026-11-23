# OWNER INPUTS (already filled in, do not ask the owner again)

The agent reads this file at the start of every session. Secrets live only in `.env`, never here.

## Provider limits and billing
- Gemini: billing is OFF in AI Studio. Only free limits are used. Key is in `.env` as `GOOGLE_AI_API_KEY`.
- Groq: billing is OFF. Only free limits are used. Key is expected in `.env` as `GROQ_API_KEY` (check the name only).
- Model IDs and free limits for both are in `misc/groq_llms_rate_limits.md` and `misc/gemini_api_rate_limits_free_tier.md`. Use those files as the only source. The owner has no other provider info.
- Live testing allowed: yes (up to 60 calls in total across both providers).

## Database
- One Supabase project only (the one in `.env`). It is used for development and production. It holds no sensitive data.
- No separate test database. Do not ask for one. Follow section 9.1 of `FINAL_STAGE.md`.

## Embedding service
- The Hugging Face BGE Space is awake and running. The owner owns it and accepts its cost and limits.
- Most requests per minute the agent may send to it during testing: 30.

## Computer
- Node.js: v22.16.0. Use it as it is.
- Python venv works and tests run.

## GitHub
- The agent may `git commit` and `git push`: yes.

## Optional items
- Telegram alerts: skip for now (build the code, leave it dormant).
- Privacy page address: not ready (widget shows the warning text without a link).

## Not needed from the agent
Docker, Render, Vercel, Sentry setup, real Turnstile keys, key rotation and the 20 FAQs. The owner does these after the final stage.
