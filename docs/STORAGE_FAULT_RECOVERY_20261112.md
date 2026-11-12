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

## Test correction after first CI run

On the first CI run, two subtests of the OS file-limit case failed because
the new fixture incorrectly assumed the *ledger* revision was 0 after
`Ownership.register`. Registration correctly increments the owner-wide ledger
to 1 while the individual instance revision remains 0. The initial child
write refusal and unchanged instance were consistent with the test setup.
The assertion now captures `before_revision` immediately after registration,
asserts it is unchanged after the failed confirmation, and verifies a +1
increment only after a successful retry. This is a **test fixture correction**,
not a product data modification. Confirm green CI on the new exact HEAD.

## Follow-up: physical ENOSPC and critical writer contention

The exact prior commit's full CI reported a rare SQLite `database is locked`
while two owners' tactic snapshots raced on `BEGIN IMMEDIATE` in the same
temporary database. The short 250 ms timeout is appropriate for disposable
cache writes, but too aggressive for manual saved data. Critical writes now
wait up to **2 seconds for the SQLite lock**, without delaying uncontended
operations. Noncritical writes retain their 250 ms timeout. A regression
holds a real SQLite write lock for 400 ms and verifies the critical writer
commits after release.

The security CI now includes `tests/test_real_enospc.py`, executed **only**
inside a Docker container with an empty 2 MiB tmpfs mounted at
`/tmp/pvp-enospc`. The test refuses volumes larger than 4 MiB. For both
DELETE and WAL journal modes it creates a synthetic owner instance, injects
a 4 MiB late write through an isolated SQLite trigger, verifies **actual
full-filesystem write refusal**, rollback of owner state/history/revision,
cross-owner isolation, integrity_check, and idempotent retry after space
is freed. The test does not mount or fill a production volume, nor touch
user data.

These are newly added tests, **unverified until the exact new commit's
GitHub Actions Security and regression job passes**. They cannot prove
power-loss durability, externally concurrent writers, all WAL checkpoint
failure conditions, or production filesystem semantics.

## Real tmpfs ENOSPC follow-up: DELETE hot-journal recovery

The first execution of the new disposable-volume test reached a genuine
SQLITE_FULL failure, but a subsequent `mode=ro` open in **DELETE mode**
raised `sqlite3.OperationalError: attempt to write a readonly database`.
The normal SQLite tests passed (574 tests, one opt-in skip); only the new
destructive tmpfs test failed. This is a release-significant recovery gap,
not evidence that owner records were deleted.

The reader now retries **only** if SQLite reports the extended error
`SQLITE_READONLY_ROLLBACK` or `SQLITE_READONLY_RECOVERY`. It closes the
failed read connection, briefly opens the server-owned database writable
to allow SQLite to replay its own hot journal, checks `PRAGMA quick_check`,
and then reopens the original read-only connection. There are no manual
journal deletions, row alterations, schema modifications or unbounded
retries. If the filesystem is still full or corrupt, it fails closed.

The test also increases the removable dummy file from 512 KiB to 1280 KiB,
so removing it after the deliberately failed transaction frees adequate
space for journal recovery on the 2 MiB test filesystem. It still forces
a 4 MiB SQLite write on that smaller filesystem to cause actual ENOSPC,
and tests both DELETE and WAL journal modes.

This attempted correction is **not verified until its exact-commit CI
succeeds**, including both tmpfs subtests and later image security scan.
