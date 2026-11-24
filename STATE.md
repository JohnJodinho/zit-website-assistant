# STATE (updated 24 November 2026 02:25)
Milestone: Backend-only step 3 (shared database proof)   Status: in progress
Live provider calls used: 2/20
Done: F0-F2 recorded previously; release 2 and 215 search cases recorded as passing. Step 1 full validation: 119 passed, 1 isolated-database integration test skipped; static checks pass. Reduced F3 chat behavior has focused tests (33 passed), with exact-match-only caching. Read-only pre-drill verification against `.env` DATABASE_URL: active published release 2, 274 chunks, no active `zzdrill-` content (`scripts/check_release_live.py`).
Next 3 actions: Run the marked CHAT-DB persistence/cleanup proof; make one live call to each provider within revised 20-call cap; finish reduced F5 and F6.
Open gates: CHAT-DB/LIVE-1/LIVE-2/LOAD-1/DRILL-1/DRILL-2/DRILL-6/OPS-1/DOC-1/DOC-2/DOC-3/CLEAN-1
Blocked: none
Last commit: ba3e5c1 Complete reduced chat backend behavior
