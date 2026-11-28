# Security continuation: authenticated error disclosure and runtime CVEs

Date: 2026-11-12 JST. Draft PR #112 research only. No production probing,
credential handling, data migration, merge, or deployment.

## Verified starting point

- HEAD before this change: `d79fccbc0410c07af8b63a3bd39d9a3cca99174f`.
- All five CI workflows on that SHA succeeded.
- Security job `43218313026`, artifact `runtime-package-inventory`, reported
  103 HIGH findings and zero **reportedly fixable** HIGH/CRITICAL. The
  high-severity package report still includes SQLite, MIT Kerberos libraries,
  util-linux, ncurses, systemd libraries, libacl and Perl. This report is
  version-specific and does not prove exploitability or safety. Re-scan a
  patched image whenever Debian fixes become available.
- The public gateway is a single-owner application with one authorized
  Auth0 subject or root key, short-lived app tokens, and signed app cookies.
  Owner-scoped database rows do not constitute independent multi-account
  onboarding or proven tenant isolation.
- Local engine binds to loopback; nginx proxies to the authenticated gateway.
  No production port exposure or actual network ACL verification was performed.

## Source-confirmed disclosure path

`pvpoke_bridge_core._request` wraps an internal HTTP error body or connection
error in `BridgeError`, including its local backend URL in connection errors.
Most `pvpoke_mcp_remote.Handler.app_request` routes previously returned
`str(exc)` as the authenticated browser's error JSON. A client with access to
an app endpoint could learn internal URLs, backend failure details or returned
private strings through a failed request. This is an **authenticated error
disclosure** (defense-in-depth issue), not proof of anonymous access or
cross-owner data theft.

The gateway now catches `backend.BridgeError` separately, mapping recognized
upstream HTTP 400/404/409/413/422 to generic client-facing errors without
the body, and all other upstream errors to a generic 503. Valid direct
`ValueError` validation messages stay unchanged to avoid breaking established
input feedback. Already-specialized Sandbox/battle handlers remain untouched.

The new HTTP regression injects an unmistakable **fake** internal URL and
marker in a backend connection failure. It confirms an anonymous request is
rejected before reaching the backend, and that a root-key-authenticated
request returns 503 without leaking details. A second case uses a valid signed
cookie and an upstream HTTP 400 containing private-looking JSON, and confirms
the status remains 400 while the error body is sanitized. No real secrets
are embedded in tests.

## Scope and remaining gates

- This correction narrows one actual browser response disclosure path. Other
  authenticated MCP tool response paths and safe diagnostic messages should
  be reviewed independently; root API key holders already have full owner
  access by design.
- SQLite FTS5/session, Kerberos, util-linux, and other reported vulnerabilities
  still need version-specific end-to-end reachability validation. The absence
  of matching string references is not a proof that an exploit is impossible.
- No real production authentication tests, external penetration tests,
  malicious-host tests, multi-tenant exposure tests, or live 3v3 policy tests.
- Independent Astra review and explicit publication approval remain mandatory.
  Release status: **D / Draft / not deployed**.

Do not mark this change as passing before CI completes on its exact commit.
