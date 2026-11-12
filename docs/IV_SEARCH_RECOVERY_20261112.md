# 4,096-IV exploration: bounded resume and fail-closed checkpoints

Date: 2026-11-12. Research branch in Draft PR #112, **not deployed**.

## Root cause and minimal correction

Existing `IVSearch.step` issued at most 32 native battles but attempted the
whole planned batch even after the native engine returned `failed`,
`invalid`, `partial` or `unsupported`. It then moved the saved search
cursor beyond a failed position. The result was still marked unverified, but
the failed candidate could be delayed until the next circular scan.

Now stop immediately on any result other than `complete`, retain the
actual incomplete IV's position as the next durable cursor, and leave all
previously committed battle cache rows intact. The next call can retry
precisely the failed candidate. Cache write failure still raises
`AnalysisUnavailable` and does NOT advance the checkpoint.

A 10-second budget governs the *batch* after the already-bounded native
input profiler/planning phase. A single native call can overrun this
boundary up to its own process timeout, and the mandatory 4,096 × 1–6 slot
full-cache scans are part of step accounting. Once at least one battle
completed, stop starting new native calls past the deadline. Preserve the
next unattempted position, including during adaptive boundary scheduling.
This is **not** a hard end-to-end HTTP timeout guarantee.

The SQLite checkpoint uses a compare-and-swap `UPDATE ... WHERE next_offset=?`.
The previous implementation did not verify whether the cursor actually
matched. A 0-row update now fails closed as `AnalysisUnavailable` instead
of claiming successful checkpoint advancement. Another worker may still
duplicate work *before* the compare-and-swap; strong cross-worker locking
or leases are NOT implemented. Cached identical battle results remain
idempotent under current store semantics; non-identical results fail.

## Verification gates

- Six distinct shield-condition slots, two eligible IVs, 12 native battles:
  strict budgets 5+7, restart with zero new battles, no false completion or
  promotion of unverified IVs.
- Three IVs: one complete battle followed by synthetic `failed`, no more
  attempts; cursor points to the failed candidate, which is retried first
  on restart.
- Synthetic interruption after one *committed* result but before a
  checkpoint: reopen using saved evidence and calculate only missing IV.
- Injected batch clock exhaustion after one battle: check persisted cursor,
  subsequent restart and completion.
- Simulated external checkpoint update during a battle: compare-and-swap
  rejects the stale cursor and preserves validated results.
- Existing 4,096-IV/32-battle native benchmark remains intact; no entire
  4,096×6 brute-force attempt or production database modification.

## Non-goals and remaining risk

No changes to the PvPoke native engine, role classification, UI, schema,
stored ownership data, game rules or deployment. Old search IDs may be stale
after implementation source version changes by design; source-bound plans
are never silently retagged as current results. Concurrent worker
reservation remains unresolved. Tests need final GitHub CI verification.
Full 4,096×6 stress, real ENOSPC, external-worker interleavings,
Astra independent review, current CVE reachability and Android device
testing remain separate approval gates.
