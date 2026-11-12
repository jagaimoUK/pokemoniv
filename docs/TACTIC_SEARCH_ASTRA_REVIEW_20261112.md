# Stage I Draft handoff: energy-aware tactical exploration and scoped role advice

Prepared for a **future independent Astra review**, not a self-certified production approval.

## Source and dependencies
- Repository: `jagaimoUK/pokemoniv`; stacked PRs #99–#110 are unmerged.
- Base: PR #110, `1771003397a415d00902a6204a916b129c3037ae`.
- This Draft: PR #111, `feature/tactic-search-role-advisory-20261112`.
- Upstream design: `PokemonIV_MissingAnalysis_Sandbox_Design_20261111.md`.
- All battle semantics come from the pinned in-project PvPoke Sandbox runner. No ChatGPT-connected PvPoke MCP tools were invoked.

## Goals and scope of this incremental pass
1. Avoid search plans dominated by plainly energy-unavailable charged turns.
2. Sample banked energy and two consecutive charged moves of either slot, including both mixed orderings.
3. Preserve the existing maximum 64 candidate scripts and 8 per step; commit checkpoints and use native action execution outcomes.
4. Add an **advisory-only**, scoped comparison of saved scripted evidence with the declared missing-role requirements. The existing immutable standard evaluation, ownership events, stored battle outcomes and real recommendation order remain untouched.
5. Demonstrate that one candidate build cannot be promoted merely because one of two required matchups has tactics.

## Changed source
- `pvpoke_tactic_search.py`: energy-only timing lower bounds (fast-move energy gain and duration), banked turns, repeated/mixed charged schedules, skip occupied self-action turns. The native engine remains the authority about legality, cooldown, CMP, KO, and actual move execution. These are candidates, *not* verified executable schedules.
- `pvpoke_tactic_evidence.py`: read-only `advisory` metadata: checked/matched required conditions, unfavorable-shield matches, role priority, within-saved-builds observed uniqueness, and a **reference order**. All role states and `practical_role_covered=False` remain unchanged.
- `pvpoke_missing_ui.py`: expandable mobile advisory with explicit theory/unknown labels; does not reorder the standard recommendation list.
- `tests/test_tactic_search.py`, `tests/test_tactic_evidence.py`, `tests/browser_missing_analysis.cjs`: synthetic native fixtures, zero re-simulation on compare, distinct required conditions, mobile viewport rendering.

## Invariants that must remain true
- `search_start` creates a plan but does not execute battle simulations.
- Native shield outcomes are checked separately from action execution. A requested shield that could not actually be used does not count toward role support; rechecking occurs when saved traces are compared.
- Alternate opponent charged requests can be paired with self-shield requests, but those remain fixed-script counterfactuals.
- Only the native Sandbox simulator can determine whether a requested action executed; calculated energy-only timing is a proposal, not a legality proof.
- No scenario with unobserved opponent action or exact opponent IV may be called live-reproducible without a policy using *only* observables.
- A complete script at one matchup cannot cover a separate matchup. Coverage is per exact build and exact condition ID.
- `unknown` is not false; no implied ownership and no cross-build merging.
- A successful conditional script is not a practical substitution. `practical_substitution` remains `not_established`.
- A lone positive among the **selected, searched** builds does not mean unique across all builds/IVs.
- No new battle calculations in `compare_tactics`, no writes to old standard results, role snapshots or ownership ledger.
- Feature flags remain opt-in and OFF by default.

## Known tradeoffs and deferred work
- **Not an exhaustive solver**: candidate profiles are a bounded sample, not 4096-IV coverage nor every legal timing/turn.
- Energy-only lower bounds ignore battle interrupts, KO, cooldown interference, charge resets, energy caps at nontrivial timing. They can request impossible moves; execution flags and native trace are authoritative.
- Opponent decisions and shield responses remain fixed script counterfactuals, not proven information-fair contingent policies.
- A same-build set of positive fixed scripts for different matchups does not necessarily amount to one observable real-time strategy.
- No simulated 3v3 role/team substitution proof; no new metadata for species/cup change, no automatic disposal/tag changes.
- Existing search checkpoints are version-coupled to source hash and will be flagged stale after algorithm changes; not silently reused.
- Advice rank is *within selected candidates and completed stored evidence only*; it does not update primary recommendations. `role_priority` is displayed, not used to compare different roles (only one role per request).
- Independent, specification-first review and physical Motorola edge 50 tests are out of scope for this Draft.

## Independent Astra review checklist
Review this document **after** independently reading the design and the code, without relying on GPT-6's characterization:
1. Verify first/second charged energy/turn formulas against the vendor engine and adversarial native traces (cooldown, CMP, charge-lock, opponent shield, bait, move effects).
2. Test near-boundary initial energy 0/34/35/69/70/100 and fast-move durations 1/2/3/4/5 against actual native executions; no hardcoded assumption of guaranteed legality.
3. Verify information sets: same observable history must imply the same recommended action across opponent hidden IV/energy/unknown charged moves. Current fixed-script generator cannot prove this.
4. Challenge the advisory: multiple required matchups, two same-IV distinct instances, untested alternative builds, partial checkpoints, stale/tampered evidence, corrupt cached traces.
5. Check owner scoping, browser-origin/auth, absence of secrets in HTML/JS, JSON output escaping/CSP, concurrent worker budget, SQLite crash recovery and restore.
6. Compare time/memory/engine calls and success quality against baseline #110 using the *same* synthetic fixtures, not production data.
7. Do not approve rollout on CI green alone. Trivy HIGH findings were present on #110 and need manual reachability analysis; hardware and real-play validation remain pending.

## Exit criteria for this stage
Tests and CI must pass on the **exact PR #111 head**. If they fail, do not declare implementation complete. Handoff should record the exact commit SHA, test results and unresolved issues.

## Operations policy
PR #111 stays Draft and unmerged. No Railway or Cloud Run change, no feature flag activation, no production database access. Both independent reviewer and user decision are required before release.
