## Current authoritative checkpoint (2026-11-12, supersedes historical pending statements below)

**Scope:** Draft PR #112 stacked on Draft PR #111, head
`af1516cc73f3ba901ccc8ac92e0c73f2e3fa573c` **before this documentation-only update**.
GitHub Actions on that exact source SHA: **11 / 11 success**, including:
Python **583 tests (1 skipped)**, JS regression, image build, Chromium
CSP/mobile initialization, dependency/secret checks, and Docker-based
**real filesystem ENOSPC test on an isolated 2 MiB tmpfs in DELETE and WAL modes**.
The real-Nginx-to-gateway HTTP authentication regression also ran in the
production Docker image. Synthetic data only; no production DB or credentials.

That confirms the stated **specific tests**, not live railway ingress,
production load, a power-loss crash, external-writer capacity, exhaustive
vulnerability reachability, complete 4096-IV × matchup native results, or
observation-conditioned real-match strategy. Fixed scripts remain
counterfactual, not practical role coverage.

The last image scan reported **103 HIGH entries, 25 unique CVEs, 0 scanner-
reported fixable HIGH/CRITICAL**. Not security clearance and not 103
separately proven exploitable bugs. Independent Astra code review has **not
been performed or signed off**. Release assessment D; PRs stay Draft
and unmerged; no production deployment.

**Historical note:** The chronological material below records earlier
RED/green investigations and at-the-time pending statements, for audit
traceability. Where those statements say 'CI pending', 'real ENOSPC
not run', 'Docker proxy not verified' or list earlier head SHAs, use
this checkpoint and `docs/ASTRA_INDEPENDENT_REVIEW_BRIEF_20261112.md`
instead. Do not erase evidence of previous failures.

---

# Remaining independent verification: storage, IV throughput and vulnerability reachability
Updated: 2026-11-12 JST. Draft PR #112 only. This is a review checkpoint, **not approval to release**.

## Source and safety constraints
- Stack: PR #112 on PR #111, neither merged, no Railway/production access, no user inventory read or changed.
- Original Japanese source specification §4.2–4.6, §7, §10–11: no inferred ownership, never equate untested IVs to losing, only observable in-game information supports practical policy, new API retains authorization.
- Native vendor PvPoke source is local within the Web app. No ChatGPT-connected PvPoke MCP tools are invoked, including indirectly.

## Storage fault injection / recovery (test fixture only)
- New unit regression `test_disk_full_abort_is_atomic_for_owned_instance_history_and_revision`: verify rollback of individual status, ledger revision and event history when SQLite aborts at the **last event append**, and verify same-event retry after removal of the fault. Run under both native DELETE and external WAL journal modes, with a second owner unable to read the records.
- This is a deterministic injected SQLite `RAISE(ABORT, 'database or disk is full')`, **not genuine filesystem ENOSPC**. It does not demonstrate persistence if a shared real volume goes entirely full. Existing tests already exercise reserve policies, process exit before commit, backup and fresh-process restore.
- Baseline application creates new SQLite files with DELETE journal mode; external WAL can expand beyond `PRAGMA max_page_count`, so actual disk and external-writer scenarios remain unknown. No cleanup or eviction of user data.

## Bounded exploration and performance
- New native test: 4096 eligible IVs, execute a budget of 32 full standard battles only, preserve the remaining 4064+ as unverified, reopen and inspect saved evidence without spawning new native battles. Print per-battle service wrapper p50/p95 in the CI log.
- New tactic-planning method test: 21 reused plan starts and 21 budget=0 progress reads, report p50/p95; assert no Sandbox subprocess and no `live_reproducibility` promotion.
- A prior successful 4096-candidate **static profiler** test ran in 0.255 seconds. It does not simulate 4096 battles, or establish battle-equivalent IV ranges.
- All metrics refer to shared CI hardware on this SHA. No before/after same-machine baseline for this endpoint, no production mobile device/HTTP load p95, no full multi-matchup 4096 × N run.

## Exact-image security triage, not security sign-off
Source: GitHub Actions Security and regression run 43170281001, generated **runtime-package-inventory** artifact, `image-vulnerabilities.json`; Debian 13.7 image. Trivy at that run reported 103 HIGH, 0 fixable HIGH/CRITICAL, 25 unique CVE IDs across 22 package names. Package row counts can duplicate one CVE across binary package names:
| Component / advertised vulnerable code path | HIGH rows | CVEs | Source-based reachability assessment |
|---|---:|---:|---|
| MIT Kerberos KDC, kadmind, GSS-RPC | 56 | 14 | Docker start scripts launch the Web engine, internal API and nginx, not KDC/kadmind; direct attacker path to listed daemon procedures not identified. Library dependency remains, untested indirect usage |
| util-linux mount/nsenter and privileged helpers | 36 | 4 | Runtime drops root using gosu after volume directory ownership setup; no application request route starts mount/nsenter; local post-compromise and host privilege/capability exposure untested |
| SQLite FTS5/session extensions | 3 | 3 | SQL storage uses normal parameterized tables and no identified FTS5 or session-changeset endpoint; SQLite library is actively exercised, so this cannot be dismissed as an unused dependency |
| ncurses infocmp utility | 4 | 1 | No service-launch invocation found; possible ancillary/debug invocations outside checked scripts not tested |
| systemd-homed | 2 | 1 | No systemd-homed daemon starts in application scripts; host/environment out of scope |
| libacl path symlink functions | 1 | 1 | No direct use found; indirect native dependency paths not exhaustively audited |
| Perl Archive::Tar parser | 1 | 1 | Application start scripts do not invoke Perl Archive::Tar; untrusted archive inputs elsewhere not exhaustively examined |
| **Total** | **103** | **25 distinct** | **No confirmed reachable exploit; no proof of absolute absence** |

No patch is available according to this Trivy image audit for HIGH/CRITICAL, and deleting OS libraries or changing pinned image without a compatibility test is not a safe remediation. Re-audit as OS fixes become available; maintain gateway auth, process non-root runtime, trusted fixed Node engine paths, secret isolation and limited input sizes. Confirm exact runtime privileges/capabilities and outbound exposure when a disposable deployed replica is available.

## Information fairness and role limits
- Existing policy is `fixed_script_counterfactual` / `live_reproducibility=not_verified`. Already tested hidden opponent energy/IV/move order and strict action execution. That checks **no false promotion**, not a reactive observation-based strategy. Need a policy model mapping same visible history to same self action, plus tests for delayed move reveal and optional shield decisions, before any claim of live reproducibility.
- A legal single exact build must cover all role conditions; never union disjoint wins across builds/species; untested conditions and unknown ownership remain pending. Existing positive regression covers cross-species partial cases. No 3v3 live proof.
- Device verification on Motorola edge 50 still requires the device. No user data or production setting was accessed for this report.

## State / next action
- Prior GitHub source HEAD before this test/doc addition was `28d23911660ff56c8e4c2b52c6cfbc29c0e86764`; exact new SHA must be verified separately.
- The new Python tests are **unverified until CI on the exact new HEAD succeeds**. A red/failing test is not a confirmed product defect until its trace is read and attributed.
- Release decision: **D, keep Draft**. Do not merge/deploy without a new user instruction and independent live-policy/security/capacity validation.


## Stage VII: information-fairness disclosure and public-shell security audit (2026-11-12)
- Requirements: original request §7 explicitly distinguishes knowing an opponent's unrevealed charged move in advance from decisions based only on observations; §10 forbids private data in unauthenticated HTML or initial API responses. These are independent release requirements.
- **Test-first RED confirmed on SHA `4af65bbabc6db6547bcd2f0d0a7208d3f6db8102`:** GitHub meta Python 532 tests, 530 pass, 2 expected errors. `test_counterfactual_paths_disclose_unobservable_assumptions` lacked `observation_conditioned` and `test_shield_choices_in_fixed_scripts_get_conservative_info_warnings` lacked the pure `_information_assumptions` helper. The new public-page/no-secret test passed.
- **Implementation SHA `c669e315ccd72093330f8fa96c52c3e89e7022c8`:** each saved tactic evidence path now explicitly reports `observation_conditioned=False`, plus conservative `information_assumptions`: fixed timed self actions, prespecified future opponent actions, assumed unrevealed alternate charged move, assumed opponent shield choice, own shield commitment before the current charged move's reveal. Labels are displayed in the existing missing-analysis UI. They are a warning about the **assumptions of a script**, not a claim that hidden information is always necessary to win. No new battles, outcomes, standard role changes, schema migration, secret sharing or production deployment.
- **Public shell/initial-request security regression:** under enabled missing-analysis/Sandbox flags, check unauthenticated `/app`, `/app/missing`, `/app/sandbox`, `/app/party`, `/app/migration` do not contain the root API key or loopback Web token. Unauthenticated `/app-api/missing-analysis` and `/app-api/sandbox` must return 401 before any bridge call. This exercises a disposable local gateway test fixture, not production.
- **Static reachability check (scope-limited):** nine principal persistence modules (`pvpoke_battle_store.py`, `pvpoke_ownership.py`, `pvpoke_sandbox.py`, `pvpoke_role_evaluation.py`, `pvpoke_missing_analysis.py`, `pvpoke_iv_search.py`, `pvpoke_tactic_search.py`, `pvpoke_auth_store.py`, `visual_backup.py`) use normal SQLite tables and have no found call to `CREATE VIRTUAL TABLE`, `FTS5`, `sqlite3session`, `changeset`, or `load_extension`. This is limited to those files; uninspected dependencies, host tools, database corruption and other code paths remain unproven. The Trivy image inventory still reports FTS5/session-related HIGH findings; do not claim fixes or full nonreachability.
- **Architecture boundary:** external gateway's `pvpoke_mcp_remote.py` serves public static shells and requires auth before app API dispatch. The local `pvpoke_web.py` binds only 127.0.0.1:8765; the main app gateway uses a shared authenticated single-owner scope, **not proven multi-tenant isolation for arbitrary account onboarding**. Database owner_scope regression is separate from production multi-user/pen-test assurance.
- **Remaining P0:** a deterministic *reactive* policy that maps equal observed history to equal own action, native evaluation of competing hidden opponent worlds, visibility of current energy/charge/reveal timing, measured support across distinct opponent choices. Fixed scripts cannot be promoted to live reproducibility by adding the above annotations. Continue to return `information_fairness=not_established`, `live_reproducibility=not_verified` and `practical_role_covered=false`.
- **CI on new implementation:** not yet verified in this note. Do not infer green from the RED test run or the previous 529-test green run. Draft PR remains unmerged and deployment disabled.
