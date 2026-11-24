# STATE (updated 24 November 2026 02:41 UTC)
Milestone: F6 closeout   Status: in progress
Live provider calls used: 5/20 (2 earlier; 1 Groq, 2 Gemini including the corrected usage check; no rate limits)
Done: F0-F2 recorded previously; release 2 and 215 search cases pass. Reduced F3 chat behavior, CHAT-DB, and live Groq/Gemini checks pass. F5 operations and retained drills committed as 3513487.
Step 1 full validation baseline: 119 passed, 1 isolated-database test skipped; static checks passed. Current focused checks: 12 operations/FAQ/load tests passed, 1 updated shared-DB tracing integration test passed, mypy and Ruff passed.
Fresh database baseline before DRILL-6: active published release 2, 274 chunks, zero active `zzdrill-` chunks, and no open draft. DRILL-6 passed; release 3 is archived with no content associations, its key is revoked, and 3 marked traces plus 3 immutable audit rows remain.
DRILL-1 cleanup rerun passed: no temporary keys or marked traces remain from that test; its immutable audit records remain. Post-test read-only check confirmed release 2/274 and no draft. DRILL-2 synthetic FAQ and 10 concurrent fake streams pass.
Open gates: final-check implementation and run; documentation validation; CLEAN-1.
Blocked: none
Last commit: 3513487 Complete backend operations and retained drills
