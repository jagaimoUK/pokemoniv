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
