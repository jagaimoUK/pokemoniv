# Astra review continuation: recover, repair, and verify

Updated: 2026-11-12 JST. This is a **checkpoint, not a final review sign-off**.

## Trusted starting point and recovery constraints
- Repository: `jagaimoUK/pokemoniv`.
- PR #111 (Draft, unmerged) head at start: `bbc0619f830704da3c626b5682c3c4b58cf211b8`.
- Separate child branch: `fix/tactic-review-recovery-20261112`, stacked on #111. Do not merge or deploy.
- Previous Work/Astra stated it edited 3 files and updated "Astra review" / "Astra storage security", but no saved patch or file from that Work environment was accessible to this chat. GitHub PR #111 had not advanced. Previous changes **were not recovered**, and have not been claimed as recovered.
- This continuation independently reimplemented the **reported** fixes against PR #111, without any ChatGPT-connected PvPoke MCP tools.
- The quoted old "503 tests, 0 failures, 4 skipped" is a **previous Work report, not a test result of the new changes**.

## Checkpoint table
| Stage | State | Evidence and changes | What remains |
|---|---|---|---|
| 0. Recover Work changes | Blocked | GitHub and Project/Library checked; Work-local edits unavailable | Recover original Work patch only if separately accessible. Do not overwrite these changes blindly |
| 1. Opponent action execution | Implemented, CI pending | Track all native opponent action IDs (including seeded actions and alternate+self-shield case); require actual resolved charged-move events as well as action-start statuses; new failing-case tests | Verify tests/CI, examine non-observable opponent behavior |
| 2. Saved Sandbox integrity | Implemented, CI pending | Revalidate cached results on read: action status/trace, terminal vs outcome, initial values, shield and damage totals, event consistency, JSON canonical encoding; rehashed invalid-record tests | Verify native trace compatibility, test more adversarial synthetic cases |
| 3. Capacity separation | Implemented, CI pending | Reserve 1/8 SQLite page quota and 8 MiB disk free for user-authored records; prioritize ownership events, role evaluations, analysis definitions, saved tactics. No eviction, no schema migration | Verify small-database saturation, free-space simulation, real storage capacity and external disk consumers |
| 4. Remaining independent review | Not started in this chat | Previous Work reported some boundary tests, no portable artifacts | Complete legal timings, hidden-information fairness, other algorithms independently |
| 5. Post-fix regression + CI | Not started | Prior PR #111 passed 503 tests and 5 workflows *before* changes | Verify exact new HEAD: Python, JS, browser, 324 golden, security, build |
| 6. Saved changes | In progress | Source changes committed on a child branch; no production changes | Create Draft PR; report final head and CI |

## Changed modules
- `pvpoke_tactic_search.py` and `pvpoke_tactic_evidence.py`: all requested opponent actions must be executed and charged moves must have matching native resolution events (action ID, actor, move). Previously just the new alternate was checked, and some variants were missed.
- `pvpoke_sandbox.py`: cached data must be semantically valid even when the checksum has been recalculated. No automatic re-simulation on invalid saved data.
- `pvpoke_battle_store.py`: two-tier writer with quota headroom and physical-disk guard; critical writes use reserve.
- `pvpoke_ownership.py`, `pvpoke_missing_analysis.py`, `pvpoke_role_evaluation.py`, `pvpoke_sandbox_workspace.py`: important writes use the critical quota.
- `tests/test_tactic_search.py`, `tests/test_tactic_evidence.py`, `tests/test_sandbox.py`, `tests/test_battle_store.py`, `tests/test_ownership.py`: regression tests.

## Explicit limitations
- Fixed scripts remain theoretical counterfactuals. Live reproducibility **not verified**. No promotion into normal coverage or ownership.
- Reserve protects the app's own quota and defers expendable writes at low physical free space; it **cannot guarantee** important writes succeed if external processes fill the volume, if WAL grows unexpectedly, or if the reserved area also runs out.
- No actual production SQLite data, credentials, keys or user holdings were read, altered or copied.
- No real device test, exhaustive 4096-IV or 3v3 policy fairness validation in this continuation.
- Changing the search source hash makes existing saved search checkpoints stale; they are retained rather than rewritten. Cached Sandbox results remain separate and verified by key/version.

## Next steps, in order
1. Check PR creation and the exact branch SHA.
2. Run CI tests on the exact branch head; fix reproducible regressions first without touching main.
3. Record test totals, any failures and whether native Sandbox and mobile browser tests passed.
4. Perform additional independent review of rules, resource fairness, owner boundaries and capacity under real volume constraints.
5. Leave branch/PR Draft, and write a user-visible handoff with concrete commit SHA and residual risk.

GitHub edits in this session were made through the connector; no local git checkout was available. Git status of the old Work container therefore remains **unknown**, not clean.
