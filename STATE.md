# STATE (updated 24 November 2026 02:49 UTC)
Milestone: F6 closeout   Status: in progress
Live provider calls used: 5/20 (2 earlier; 1 Groq, 2 Gemini including the corrected usage check; no rate limits)
Done: F0-F2 recorded previously; release 2 and 215 search cases pass. Reduced F3 chat behavior, CHAT-DB, live provider checks, F5 operations, and retained drills pass. F5 implementation commit: 3513487.
Database baseline remains active published release 2 with 274 chunks, no active `zzdrill-` content, and no open draft. DRILL-1 and DRILL-6 pass; DRILL-2 synthetic FAQs and 10 concurrent fake streams pass. Temporary keys are removed or revoked; immutable audit rows are retained.
F6 docs and backend-only `final_check.py` gates are implemented. Ruff, formatting, mypy, DOC-1 variable coverage, and DOC-3 route/SSE coverage pass. Out-of-scope worktree changes remain preserved.
Open gates: final full `python scripts/final_check.py` run and its any reported AGENT failures.
Blocked: none
Last commit: fb76cde Checkpoint backend operations completion
