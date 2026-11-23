# Engineering Decisions

- Groq tier 1 model IDs: `openai/gpt-oss-120b` (RPM 30, RPD 1000, TPM 8000, TPD 200000) and `openai/gpt-oss-20b` (same limits). `qwen/qwen3.8-27b` is preview and remains disabled.
- Groq prompt guard IDs are not generation models and remain disabled.
- Gemini text models with usable listed limits will be enabled: `gemini-3.8-flash` (RPM 5, TPM 250000, RPD 20), `gemini-3.1-flash-lite` (RPM 15, TPM 250000, RPD 500), `gemini-3.5-flash-lite` (RPM 15, TPM 250000, RPD 500), and `gemini-3.6-flash` (RPM 5, TPM 250000, RPD 20). `gemini-4-hydrogen` also shows RPM 5, TPM 250000, RPD 20 but needs explicit model-ID verification before enabling.
- Gemini preview, deprecated, unlisted, or zero-quota models remain disabled unless a live model-ID check proves they are available.
- Final tier choice will follow the Main Plan while keeping Groq tier 1 and Gemini tiers 2/3.
- The shared Supabase URL in the local environment is on port 5432, so no transaction-pooler rewrite is required. `DATABASE_URL_SESSION` support will be added for explicit staging use.
- Normalize BM25's strongest match by the query's maximum weighted term coverage before applying the 0.30 relevance gate; raw BM25 values are unbounded and made unrelated queries look relevant. The 215-case BGE evaluation then passed all retrieval, link, and refusal gates.
- Pace BGE embedding requests at one every 2.1 seconds to honor the owner's 30-requests-per-minute testing cap, including retry attempts.
