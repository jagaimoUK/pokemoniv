# Independent Astra review brief (preparation only)

> This is a review handoff, **not** the independent review itself, an
> implementation sign-off, or permission to merge/deploy. Prepared on
> 2026-11-12 JST from GitHub's source, GitHub Actions, and the original
> Japanese requirement attachment.

## Authoritative materials in review order

1. **Original user specification**: attachment named
   `開発依頼：Pokémon-GO個体値厳選アプリの不足個体分析・ビジュアルSandbox・共通計算基盤.txt`,
   especially §§3–8, 10–13 and 16. Pass the *original text* to the
   reviewer. It is **not** committed to this repository, so do not
   silently substitute this brief or assume the reviewer can see it.
   The user also supplied `セキュリティ.txt` as security context.
2. **Current GitHub source**, pinned for this handoff to commit
   `af1516cc73f3ba901ccc8ac92e0c73f2e3fa573c`. Review PR #111
   https://github.com/jagaimoUK/pokemoniv/pull/111 and **stacked**
   PR #112 https://github.com/jagaimoUK/pokemoniv/pull/112.
   Inspect combined functionality and base-code behavior, not #112's
   changes alone. Re-resolve both branch heads at review start.
3. **Native in-repository PvPoke engine**:
   `vendor/pvpoke/src/js/battle/Battle.js`,
   `vendor/pvpoke/src/js/battle/actions/ActionLogic.js`,
   `pvpoke_node_matrix.js`, `pvpoke_sandbox_runner.js`,
   `pvpoke_battle_policy.js`, `pvpoke_direct_backend.py`.
   Actual resolved events, timing, shield results, CMP and KO behavior
   take precedence over proposed scripts and implementation commentary.
4. **Auditable evidence**, not authoritative claims:
   `docs/ASTRA_REVIEW_CONTINUATION.md`,
   `docs/REMAINING_RISK_VALIDATION_20261112.md`,
   `docs/STORAGE_FAULT_RECOVERY_20261112.md`,
   `docs/HIGH_PRIORITY_SECURITY_GATE_20261112.md`,
   `docs/TACTIC_SEARCH_ASTRA_REVIEW_20261112.md`,
   corresponding `tests/`, and GitHub Actions run
   https://github.com/jagaimoUK/pokemoniv/actions/runs/43237933023.
   Some earlier docs are chronological snapshots with stale 'pending'
   conclusions; this handoff supersedes those statuses.

**Unavailable document:** Earlier handoffs cite a
`PokemonIV_MissingAnalysis_Sandbox_Design_20261111.md`. Checks of the
repository root and `docs/` under the above branch did not find it;
do not claim to have reviewed that file. The original attachment is
the formal review baseline. If an additional design document is
available elsewhere, compare it explicitly, do not guess its contents.

## Latest source-verified build/test checkpoint

- Pre-handoff source SHA: `af1516cc73f3ba901ccc8ac92e0c73f2e3fa573c`.
- Exact-head GitHub Actions: **11/11 success**.
- Security workflow: **583 Python tests, 1 skipped**, JS tests,
  Docker image/proxy tests, real disposable ENOSPC recovery (DELETE/WAL),
  browser CSP check, secret scan, package audit. The ENOSPC simulation
  is a real filesystem-capacity exhaustion in a disposable CI tmpfs,
  **not** evidence of production durability under power loss or
  competing external writers. Proxy tests are localhost replicas,
  **not** live Railway edge/TLS verification.
- Image audit: 103 HIGH rows, 25 distinct CVE IDs, 0 with
  scanner-reported HIGH/CRITICAL fixes; do not infer exploitable reachability
  or absence of risk from the counts.
- This documentation-only handoff commit changes the head again.
  **Its CI must be checked separately**; historical green results
  are pinned only to the SHA above.

## Review questions ranked by risk

**P0: Battle correctness and information fairness.**
Reproduce the native PvPoke Sandbox turn resolution independently:
energy cost and fast-move timing (1–5 turns), charging/banking,
repeated charged moves, interrupts, simultaneous KO/CMP, initial
HP/energy/stages, bluff and both participants' independent shield
choices. Demand proof that each requested charged action *resolved*
in native event traces. Compare normal and edited results under
identical metadata. Challenge theoretically winning fixed scripts
that depend on unrevealed opponent moves, energy, IVs, shields or
future decisions. Check whether the **same observable history**
forces the same own action across hidden worlds.
**Do not promote** `information_fairness=not_established`,
`live_reproducibility=not_verified`, or
`practical_role_covered=false` without such proof.

**P0: Missing-IV integrity and ownership.**
Inspect `pvpoke_missing_analysis.py`, `pvpoke_iv_search.py`,
`pvpoke_ownership.py`, `pvpoke_role_evaluation.py`,
`pvpoke_tactic_evidence.py`, `pvpoke_missing_comparison.py`
and relevant tests. Distinguish evaluated, candidate, confirmed
owned, and unknown, including missing records, revisions, conflicting
identity and stale game-data/version settings. An untested IV must
not become 'lost', 'unowned', 'useless' or 'no win'. A single exact
build/condition must satisfy all required roles; do not union
separate wins from different builds or species. Examine the
static-only 4096-IV scan against the bounded 1/8/32 battle budget
and safe resume, including invalid or interrupted checkpoints.

**P0: Persistence, security and regression.**
Challenge role/event history transactions across SQLite DELETE/WAL
and native write failure, read-only journal recovery, full-volume
conditions, owner scopes, backup/restore and restart. Verify anonymous
HTML and initial network fetches contain no secrets or owner data;
authorization for every API and guessed resource ID; CSRF/origin,
cookie revocation, localhost Host/DNS rebinding, JSON duplicate
keys, runtime subprocess environment and output-error redaction.
The deployment is single-owner; multi-user isolation is **not**
established by two-owner unit tests. Distinguish reachable OS CVEs
from installed-but-unused libraries. Regress normal IV selection,
team builder, move/meta presets, history, saved Sandbox, mobile UI,
backup/import and direct engine parity.

**P1: Performance and UX.**
Inspect whether a 4096 candidate *static profile* is mistaken for
4096 native simulations; test cache invalidation, budget/deadline,
request-rate behavior, restart and resumability, 320px/390px mobile
flows, and saved results during fetch/retry failures. Quantify
native engine calls and p50/p95 where reproducible; clearly label
unmeasured full-load or real-device latency.

## Independence protocol and restrictions

- Start from the **original requirements, checked-out code, and
  native engine**, not prior GPT implementation descriptions.
  Assume prior conclusions may be false; seek counterexamples
  before acknowledging claimed fixes.
- First review **read-only**. For every finding specify severity
  P0/P1/P2/P3, violated requirement section, file/function/line,
  minimal reproduction and actual-vs-expected behavior,
  test evidence, data/security impact and remediation.
- Distinguish **confirmed by source**, **confirmed by test**,
  **hypothesis** and **unverified**. Where possible add a failing
  test before proposing a minimal fix; no random refactoring.
- Do not use or even connect the **ChatGPT-connected PvPoke MCP**,
  including any `get_catalog` or indirect call. The app's local
  pinned PvPoke engine and ordinary tests are allowed.
- No live production credentials, volumes, user collections or
  network attack testing. Avoid changing third-party/vendor files
  without evidence. Do not clear old uncommitted work.
- Keep PRs #111/#112 Draft and unmerged; do not enable feature
  flags, deploy Railway/Cloud Run, or change production data.
  Authorized code fixes, if separately undertaken, need isolated
  tests, a named branch/commit and exact-head CI.
- The original attachment describes an **initial design-only
  phase**; subsequent user decisions authorized incremental
  implementation on Draft PRs. Review implemented code as it
  exists, but do not infer permission to deploy.

## Expected reviewer output

1. Requirement-to-implementation matrix; each row says
   implemented / partial / missing / unverifiable, with evidence.
2. Independent native-engine correctness tests and failed
   counterexamples for timing, charged-action resolution and
   information-fair opponent policies.
3. Owner and missing-IV correctness, persistence, security and
   backward-compatibility findings sorted by severity.
4. Measured resource/call counts, data durability boundary and
   explicit uncertainty for the 4096-IV scope.
5. Specific minimal patches / tests if authorized, exact SHA
   and CI state; a complete list of still-unverified risks.
6. **Separate verdicts**: (a) review quality/completion,
   (b) readiness for implementation fixes, (c) release. A green
   CI is *not* permission to call the release safe.

## Operations / current decision

Before this docs-only commit the source head was `af1516cc73f3ba901ccc8ac92e0c73f2e3fa573c`.
PR #112 is Draft stacked on Draft #111, both unmerged.
No production deployments, external penetration tests, live
device measurements or independent Astra sign-off were
performed in preparing this brief. **Release verdict: D (hold).**
