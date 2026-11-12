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


---

## GPT-6 independent review checkpoint (2026-11-12 JST, stage 1)

This section supplements earlier handoffs. It does **not** endorse their conclusions. Source of truth: original missing-analysis/Sandbox requirements and pinned in-repository PvPoke battle engine. Previous review summaries are only hypotheses.

### GitHub verified initial state
- PR #112: **open Draft**, base \`feature/tactic-search-role-advisory-20261112\` (PR #111), head branch \`fix/tactic-review-recovery-20261112\`.
- Start HEAD: \`3d793b9d2a63599ef2d25b4f6a99ec5eeabe7521\` (unchanged from supplied previous checkpoint).
- 14 files changed in PR #112. Its exact start HEAD has 5/5 successful workflow runs: IV contract, recommendation, 24-mode, meta/image, security/regression. The reported 510 Python tests are not yet independently reconstructed locally.
- No local Git checkout exists in this execution environment; uncommitted Work-local edits cannot be inspected or recovered. The connector tracks committed branch changes only.
- Production untouched. The ChatGPT PvPoke MCP was not used.

### Spec-first falsification matrix (expectations before accepting code fixes)

| Independent condition | Counterexample / expected rejection or uncertainty |
|---|---|
| Charge energy 0–100 | At 0 or one point below cost, charge never resolves; exact cost permits firing if otherwise legal; energy never exceeds 100 |
| Fast move duration 1–5 turns | A charge scheduled during unresolved fast-move cooldown cannot count as executed; damage lands at engine-defined turn, not request turn |
| Repeated and mixed charged moves | Each move must be independently paid for and resolved; actor, action ID and equipped move ID must match actual native events |
| CMP and simultaneous actions | Native priority and KO order decide legality; a started but non-resolved action cannot satisfy a role; simultaneous KO must retain both terminal HP=0 |
| Shields 0–2 | No shield usable after depletion; requested and actual shield events, defender, and shield totals must agree |
| Buffs and debuffs | Effects apply only when native engine resolves them; initial stages, timeline transitions and terminal stages must agree |
| Opponent response | Requested original and generated alternate scripts must independently resolve; missing response means counterfactual evidence unsupported |
| Fair information set | Two histories with the same *observations* must lead to the same selected action despite different hidden enemy IV, charge move, energy or shield intent; otherwise label as theoretical |
| Saved proof consistency | Recompute digest after mutating one inner trace/terminal field: load must still reject impossible state transition, not just malformed JSON |
| Required role and IV | Only one exact legal build covering *all* required matchups is eligible; separate IV wins must not be unioned; incomplete IV search is unknown |
| Inventory independence | Calculation, candidate retention, confirmation and unknown ownership are separate states; absence of an ownership record is not proof of unowned |
| Disk capacity | Disposable writes must not starve crucial records; test tiny quotas, WAL/disk exhaustion, failed transaction rollback, restart and recovery, without production data |
| Default calculation | Standard mode golden results must remain identical, including hand-specified move sets and meta presets |

Sources and current limits: the original Japanese request document defines these expected behaviors. The pinned PvPoke \`Battle.js\` uses 500ms turns and cooldown, and \`ActionLogic.js\` reasons from energy and priority, but individual oracle outcomes still require native runner fixtures. The matrix is not a claim that the code passes.

### Progress states

| Stage | State | Completed | Remaining |
|---|---|---|---|
| Latest source / Git / CI | 完了 | PR refs, 14 changed paths, 5 current successful workflows verified | Compare individual workflow job evidence as needed; local Work state unavailable |
| Spec-driven battle review | 作業中 | Independent falsification matrix and vendor code entry points identified | Native test fixtures, red/green tests for new failures |
| Live reproducibility | 未着手 | Observable-history equivalence specified | Run two-hidden-state tests and check UI labels |
| Missing roles / IV | 未着手 | Per-exact-build invariant specified | Audit code and coverage |
| Security / storage | 作業中 | Owner/digest/disk risk conditions specified | Mutation fuzz cases, capacity and WAL audit |
| Repairs | 未着手 | None from this independent pass | Demonstrate failures before targeted fixes |
| Regression / build | 未着手 | Initial pre-review CI 5/5 confirmed | Exact post-fix workflows, tests and image |
| GitHub checkpoint | 完了 | This checkpoint, Draft PR maintained | Save subsequent findings, remediation and final SHA |

### Checkpoint metadata
- Current stage: spec-first battle and stored-proof review.
- Confirmed defects **in this pass**: none yet; hypotheses must not be called confirmed.
- Previous fixes: maintained untouched; no endorsement.
- Unfixed / unverified: full policy fairness, end-to-end native timeline, storage exhaustion and recovery, Trivy HIGH=103 (historical report), 4096-IV coverage.
- Changed paths in this pass: documentation checkpoint only.
- Initial HEAD: \`3d793b9d2a63599ef2d25b4f6a99ec5eeabe7521\`; branch \`fix/tactic-review-recovery-20261112\`. A new documentation commit will advance HEAD.
- Uncommitted changes: unknown outside GitHub; connector edits commit directly.
- Tests: 5/5 existing Actions passed at initial HEAD. No new local tests executed. Do not conflate with the prior 510-test count.
- Next operation: inspect cached-state validation against native trace shape, add a precise red regression test, only then patch the defect and verify CI.


### Independent finding G6-001: forged opening Sandbox state (P1)
- **Reproduction (confirmed red, not an assumption):** on test-only SQLite data, alter the first native trace event's \`before[0].hp\` while preserving the stored \`initial\`; recalculate canonical JSON + SHA256 digest. Prior cache validation accepted the contradiction.
- **Red CI at commit \`f02d55754067e387f0631dc32dd8614e741fc403\`:** Python suite \`511 run / 510 passed / 1 failed\`. New test \`test_rehashed_first_trace_state_must_match_initial\` failed exactly with \`AssertionError: BattleStoreError not raised\`; three workflows running the suite reported the same failure. This is an intentional red test, **not** a previously passing build.
- **Root cause:** \`_validate_cached_sandbox()\` only bounds individual trace states; it did not require the first event's \`before\` snapshot to equal the validated initial state. The SHA256 digest is not an authenticity proof after rehashing.
- **Targeted fix (in this checkpoint's paired source change):** reject any nonempty complete trace whose first \`before\` state differs from \`initial\`; malformed saved facts fail closed, without rerunning native PvPoke or deleting data.
- **Green status:** pending exact-HEAD CI. A later, independent test must still address intermediate trace-state transitions and terminal/effects linkage. No production change.

### Current progress after G6-001 remediation commit
| Stage | State | Evidence | Remaining |
|---|---|---|---|
| Latest source | 完了 | PR #112, Draft, base #111; prior HEAD \`f02d557...\`; original 5/5 initial CI | New head/CI |
| Battle independent review | 作業中 | Native runner semantics reviewed; forged initial timeline contradiction reproduced | Additional energy/CMP/fast action fixtures |
| Live reproducibility | 未着手 | Still counterfactual fixed scripts | Observational-equivalence policies/tests |
| Missing IV / roles | 作業中 | Exact-build intersection and unknown-ownership state inspected, no new failure proven | Full IV coverage and alternative substitution tests |
| Security / storage | 作業中 | P1 cache contradiction proven; capacity reserve code inspected | WAL, tiny quota, crash/repair, owner HTTP, Trivy reachability |
| Repairs | 作業中 | Minimal cache fix and regression test committed together | Verify post-fix CI; further inconsistent trace cases |
| Regression | 作業中 | Red run: 511/510/1 | Green 511+ golden/JS/browser/build checks |
| GitHub saving | 完了 | Source, test, handoff on existing Draft branch | Record exact final commit in visible handoff |

- Previous Work-local unsaved 3 files remain inaccessible; do not overwrite or claim recovered.
- No local working tree available for inspection; uncommitted changes in the previous Work environment remain unknown.
- Changed in this pass: \`tests/test_sandbox.py\`, \`pvpoke_sandbox.py\`, \`docs/ASTRA_REVIEW_CONTINUATION.md\`.
- Initial PR #112 head was \`3d793b9...\`; red test commit \`f02d557...\`. This checkpoint is paired with a new remediation commit on branch \`fix/tactic-review-recovery-20261112\`; its exact GitHub-generated SHA is reported in the review handoff.
- No production merge/deploy/configuration/DB changes. No ChatGPT PvPoke MCP calls.
- Next: confirm new commit's Actions, read any failures, fix only reproducible regressions, then document remaining uncertainty and do not approve publication prematurely.


### Independent finding G6-002: started-but-unresolved native fast action (P1)
- **Red test at \`b78e78ec0e317ac1e2a5a53d26930f9ec4aa1a97\` (confirmed):** \`test_fast_move_tap_without_resolution_is_not_success\` fails with \`AssertionError: True is not false\`. Synthetic fast request is marked "executed" but has no resolved native damage event. Positive fixture \`test_native_fast_start_and_resolution_are_independently_linked\` independently checks that legal native fast moves have a linked \`action_id\`, \`actor\`, \`kind\`, \`move_id\` event.
- **Source of truth:** pinned vendor \`Battle.js\` queues fast attacks to resolve after their cooldown, and \`pvpoke_sandbox_runner.js\` documents that a tap may start even when KO prevents damage. The previous helper only enforced resolution for charged attacks.
- **Root cause:** \`_requested_actions_completed()\` accepted an \`executed\` fast start without requiring resolution.
- **Targeted fix in paired commit:** require matching native resolved event for *both* fast and charged requests; wait still requires only executed-start status. This is conservative: a queued but unlanded tap cannot establish tactical role support.
- **Post-fix state:** pending exact-head CI (expect the prior red test plus positive native fixture to pass). Native GameMaster, vendor Battle.js, standard calculation, ownership and production remain untouched.

### Security triage checkpoint
- Earlier exact-head security workflow recorded Trivy **HIGH 103** with no fixable HIGH/CRITICAL at the then-available package versions. At least \`libsqlite3-0\` appears in HIGH rows (e.g. CVE-2026-119373/119374/119379), so these findings cannot all be dismissed as unused packages: SQLite is exercised by app record storage.
- Also affected packages in the report include Kerberos libraries and utilities such as \`mount\`/ \`login\`; whether they are reachable from untrusted web requests is not established from package names alone.
- This is **triage, not exploit confirmation or a clean security audit**. OS/package advisory verification and individual path review are still required. Do not release solely because no vendor fix is listed.

### Updated work state
- Latest source: 完了; tests and native semantics: 作業中; live information-fairness policy: 未着手; role/IV coverage: 作業中; security/capacity: 作業中; G6-001 source fix: 作業中 (green verification outstanding); G6-002 source fix: 作業中 (green verification outstanding); full regression/build: 作業中; GitHub save: 完了.
- Changed this stage: \`tests/test_tactic_search.py\`, \`pvpoke_tactic_search.py\`, \`docs/ASTRA_REVIEW_CONTINUATION.md\`. Parent red SHA \`b78e78ec0e317ac1e2a5a53d26930f9ec4aa1a97\`, branch \`fix/tactic-review-recovery-20261112\`. Exact new commit SHA appears in PR #112 / final handoff.
- Previous Work uncommitted edits: unknown/unrecoverable; this environment uses direct GitHub commits, no local checkout.
- Remaining: green CI + 324 golden + browser smoke, owner boundary, WAL and true disk exhaustion, information fairness, full IV search, performance comparison; do not mark the feature publishable.
- Next concrete action: read CI conclusions on new HEAD, retrieve failure logs if any, only then finalize the Draft checkpoint and report commit SHA.
