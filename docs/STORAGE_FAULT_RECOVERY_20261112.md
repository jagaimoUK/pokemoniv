# Storage durability: OS write denial, WAL and reserved capacity

Date: 2026-11-12 JST. Draft PR #112 only. **Not production validation or release approval.**

## Confirmed code issue and correction

`BattleStore._writer(critical=False)` originally checked free disk only before
starting a transaction. A noncritical cache write could subsequently consume the
8 MiB physical disk reserve without a second check, even if SQLite pages remained
within `PRAGMA max_page_count` (notably with WAL enabled externally).

The narrow correction adds a 2 MiB preflight margin and rechecks the 8 MiB disk
reserve after yielding the write transaction but **before commit**. If free
space has dropped to the threshold, the transaction aborts and SQLite rolls
back the disposable write. Critical owner-authored records keep their separate
priority path. This does not evict, delete or rewrite old user data.

The preflight margin cannot guarantee that an unusually large write or another
process will not exhaust a shared physical volume. The postwrite check also
cannot guarantee free space remains adequate during the subsequent commit,
checkpoint or host crash. External writers, WAL checkpoint behavior and
filesystem quotas must still be considered in deployment planning.

## Added tests

1. `test_disk_reserve_headroom_and_postwrite_rollback` uses controllable disk
   readings around an actual SQLite transaction in **DELETE and WAL** journal
   modes. Verifies preflight refusal, rollback of an inserted cache row after
   simulated reserve consumption, survival of previous data, and independent
   critical write success. **This is simulated capacity**, not real ENOSPC.
2. `test_real_kernel_file_limit_rolls_back_owner_history_and_recovers`
   runs a subprocess with Linux `RLIMIT_FSIZE=64 KiB` and attempts to write
   256 KiB of data in a test trigger at the end of an ownership confirmation.
   It verifies **real OS-level refusal** under DELETE and WAL, atomic rollback
   of owner status, history and revision, cross-owner read isolation, SQLite
   integrity and successful idempotent retry after the fault is removed.
   `RLIMIT_FSIZE` raises an **EFBIG / SQLite I/O error**, not actual disk ENOSPC.
   The limit is child-process-local and all data is disposable.

The existing tests also cover SQLite logical page quotas, a live oversized WAL
file, simulated SQLITE_FULL via triggers, crash-before-commit and backup/restore.
These are complementary tests, not a claim that all physical-volume failures
have been reproduced.

## Release gates still open

- Genuine ENOSPC on a dedicated disposable full filesystem or exhausted quota,
  including journal/WAL checkpoint/restart, has **not** been run.
- Production-volume capacity, free-space behavior during the COMMIT syscall,
  external simultaneous writers, checkpoint failures and power-loss durability
  remain **unverified**. A replica with no production secrets/user data is
  recommended for the destructive volume test.
- Full 4096-IV × multi-matchup calculations, live information-fair tactics,
  exhaustive vulnerability reachability and independent Astra review remain
  separate blockers. PR stays Draft; no merge, deploy or real data modification.

Tests must pass CI on the exact resulting commit before claiming success.
