# Bundled security review, error hardening and remaining release risks
2026-11-12 JST. Source: draft PR #112, no merge, deployment or real user data access.

## What was checked

- Source code for public GET shells, app-route authorization, remember-me cookies,
  OAuth subject restrictions, backend/loopback forwarding, private owner scopes,
  visual backup key/etag handling, Nginx rate limits, secret storage, process
  privileges, and failure/exception behavior.
- Local fixture-only authorization regressions include both feature flags on,
  root API-key absence from public HTML, and 401 before internal dispatch for
  representative app/party/Sandbox/missing-analysis/battle/backup APIs.
- The prior exact commit had nine successful GitHub Actions workflows, including
  tests, container builds, secret scans and vulnerability inventory. Those
  results are **not** CI approval of this new commit.

## Fixes in this batch

1. The authenticated JSON-RPC `tools/call` response previously included
   `type(exception): exception text` for every unexpected backend failure,
   potentially revealing internal paths, token-bearing strings and upstream
   response bodies. It now returns a generic failure string for unexpected
   exceptions and logs only the exception type; explicit ValueError input
   guidance is retained.
2. The JSON-RPC parse/error envelope previously echoed `str(exception)`;
   now uses a generic protocol error with the existing -32700 code.
3. The app API previously echoed KeyError/TypeError messages; these are now
   generic input errors, while explicit ValueError messages remain unchanged.
4. The loopback calculation server previously echoed unexpected Python
   exception text in 500 responses. It now sends a fixed message while
   retaining internal exception type logging.
5. Add regression tests for synthetic marker non-disclosure under the root-key
   MCP route, app APIs and loopback server, plus anonymous/public shell tests.
   No actual secrets or private data are used.

## Auth and isolation interpretation

The gateway verifies a server-controlled bearer key or a configured OAuth
subject before privileged operations; app-only bearer and browser cookies
cannot call the MCP endpoint. Anonymous static HTML pages are expected and
allowed but must not contain credentials or personal records. User-supplied
IDs are not trusted to select a storage owner. Owner-scoped database queries
are verified in existing model tests; this is NOT full multi-tenant isolation.
A second unrelated account should not be onboarded without distinct
principal mapping, authorization rules and independent tests.

## Container CVE inventory and remaining blockers

The prior image audit on exact commit `073ec8913976c0bc0c57a086580497653a4231f1`
reported 103 HIGH entries, zero HIGH/CRITICAL with available fixes according
to that scanner. Many are duplicates across packages for one CVE. Not all
reachable code paths are known; in particular SQLite is actively linked.
Do not mark these issues fixed or exposure impossible. No speculative base
image, dependency or Debian OS changes were made.

Remaining verification: full external penetration test on disposable deployment,
actual secret/cookie/URL exposure at the edge, full library CVE reachability,
simultaneous multi-client rate-limit behavior, physical ENOSPC and WAL crash,
operational restore, 4096-IV prolonged load, actual 3v3 tactical fairness,
and independent Astra review. No production or user data touched.

Release status **D / Draft / no merge / no deploy**. Require CI on the new
exact commit before treating these bundled fixes as tested.
