# Experimental observed-input policy and WAL defensive checks

Date: 2026-11-12. Source of truth: the original Japanese specification,
especially §7 on information fairness, §10 on authorization and §11 on bounded
resource use. This note is not an Astra independent review.

## Observation-only policy proposal

`pvpoke_observed_policy.py` is a **pure internal experiment**, with no HTTP
route, storage migration, Android integration, PvPoke native hook, or
recommendation/role promotion. It accepts only an explicitly allowlisted
visible snapshot, observed opponent event history (up to 64 events), and a
fixed **self-owned** move policy. It rejects hidden opponent IVs, energy,
unrevealed move IDs, and future move knowledge. A move ID can appear only in a
past resolved-charge event, never in an announcement while deciding a shield.
It has deterministic own-energy/cooldown and charge-announcement actions.

All responses deliberately include `observation_provenance_verified=false`,
`native_execution_verified=false`, `practical_role_covered=false`, and
`live_reproducibility=not_verified`. Input allowlists *alone* do not prove
the originating device actually observed the values. The given move costs
need to be bound to the native equipped moves from the pinned GameMaster, and
the resulting actions must be tested against native PvPoke's exact 500ms
turn, cooldown, CMP, shield commitment, KO and charge timing **before**
integration into the user interface or role evidence.

### Native integration gates (not yet implemented)

1. Trusted adapter derives observed events from native trace in their actual
   information-reveal order, with no move identity at shield-prompt time.
2. Exactly equal visible-history prefixes select exactly equal self actions
   across differing opponent hidden IVs, energy and unrevealed moves.
3. Execute/verify selected actions with native Sandbox (not just an
   independently invented fast/charge rule) and compare counterfactual worlds.
4. Bound response branching and computational budget, persist resumable
   progress only with owner-scoped checkpoints.
5. Only then consider a separate practical-policy status. The current fixed
   scripts stay theoretical, and no existing role classification changes.

## Defensive WAL pressure

`BattleStore._writer(critical=False)` now observes an oversized
`database.sqlite3-wal` file. If an external process has caused its size to
exceed the configured main-DB byte cap, expendable cache writes **pause**.
Critical user-authored records retain the original reserved writer path.
The code never truncates another process's WAL, removes or rewrites a record,
or changes the journal mode. The test grows a **real SQLite WAL file** in a
disposable local database, confirms noncritical refusal, critical write
survival, explicit checkpoint, recovery, and SQLite integrity. It does **not**
fill the physical filesystem, test true ENOSPC, prove all external-writer
cases, or guarantee critical writes succeed once the disk is completely full.

## Security and performance boundary

Existing scoped authentication, static FTS5/session reachability triage, and
the Trivy HIGH inventory remain unchanged. This patch does not cure OS CVEs
or establish production multi-tenant authentication. One WAL file-size stat
is added only to cache writes; no method-level before/after HTTP benchmark
is established. Keep Draft and no deployment pending independent Astra review
and the remaining high-risk engineering gates.
