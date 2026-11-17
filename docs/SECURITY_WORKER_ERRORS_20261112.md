# Worker exception disclosure follow-up
2026-11-12 JST. Draft PR #112. No deployment or real data access.

## Source-confirmed propagation

The local Party Builder's `_worker` previously stored every exception's
`str(exc)[:400]` in its persistent `runs.details` status row. That row can
be read back through `/api/party/status` and then the authenticated app
proxy. Unexpected OSError/SQLite/subprocess exceptions can contain
internal filesystem paths or diagnostic details.

The legacy IV worker `background_run` similarly placed raw exception
text in `STATUS['logs']` and `STATUS['message']`, which are exposed via
local status and may reach job polling. `load_catalog` exposed unexpected
initialization text via the catalog's `error` field.

The changed branches now display generic, actionable retry messages and
log only the Python exception type, preserving the worker's cancellation
state. Explicit Party Builder ValueError input validation remains
human-readable. These changes do **not** remove historical status rows
already written by past versions, nor do they sanitize every deliberate
subprocess progress line or other user validation error.

A new dedicated fixture test injects fake private markers into unexpected
Party Builder errors, catalog initialization and subprocess start failures
and verifies that no marker reaches the recorded status. Separate
validation-feedback and cancellation assertions protect existing behavior.

## Verified baseline and open limits

Commit `dc75139293779085c5017f5a605f9b5c94e5f0a9` passed 11/11 CI
including real ENOSPC recovery in DELETE/WAL modes, browser CSP checks
and image/package scans. The previous JSON consistency change
`17491609ac68060d7bc06643b8c696984183286b` requires an exact-sha
CI conclusion before it is called verified.

No root API key or real credential is embedded in tests. The runtime
still reports 103 HIGH image findings with zero scanner-reported fixable
HIGH/CRITICAL; Debian updates, independent peer review and disposable
network penetration testing remain mandatory release gates. The app
remains single-owner, not proven multi-tenant safe.

PR status: Draft, unmerged, not deployed.
