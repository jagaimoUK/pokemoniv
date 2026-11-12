# High-priority security gate: actual proxy route and worker secret confinement

Date: 2026-11-12 JST. Branch `fix/tactic-review-recovery-20261112`, draft PR #112.

## Confirmed defect

`pvpoke_web.background_run` previously launched the IV worker with
`env={**os.environ, ...}`. This passes the parent gateway's entire process
environment to a calculation subprocess, including potentially the root
`PVP_API_KEY`, OAuth configuration/credentials and backup storage keys.
The worker does not need these to run the pinned direct simulation. This
is a confirmed excessive-privilege path, **not proof that any secret was
leaked to an external recipient**.

The worker now calls `iv_worker_environment(force=...)`, built from the
existing minimal `child_environment` plus an explicit allowlist of
calculation engine, runtime cache, chunk size, and persistent archive
volume settings. The `PVP_FORCE_RECALCULATE` override remains supported.
It never passes general `PVP_*`, S3, AWS, OAuth, or gateway tokens.

A regression mocks the real `Popen` call and asserts that a synthetic
root key, OAuth secret, cloud backup secret and gateway URL are absent,
while engine, persistent volume and cache values are preserved.

## HTTP authentication defense in depth

A new isolated `test_proxy_security_end_to_end.py` runs the **real Nginx
binary** configured from the production `nginx.conf.template` and the
**real gateway handler**, connected on ephemeral local ports. All
credentials, database files and response bodies are synthetic. It checks:
- Public HTML and health replies contain no root token or credential.
- Anonymous callers cannot reach app, party, missing-analysis, Sandbox,
  battle, visual-backup or MCP endpoints, even with spoofed forwarded IP.
- An authenticated request reaches the intended protected endpoint.
- Cross-origin requests are rejected, browser cookie is HttpOnly /
  SameSite=Strict, cookie-only access cannot reach MCP, and logout
  revokes copied cookies.
- Legacy JSON routes reject duplicate keys, NaN and wrong Content-Type.
- The local calculation server's `/api/status` route is not exposed by
  the public Nginx route.

The suite is skipped on development hosts without Nginx. The existing
security CI runs **the full Python suite inside the production Docker
image**, which includes Nginx and executes this test. It does not
depend on a real user account, the real Railway volume or the
ChatGPT-connected PvPoke MCP.

## Boundaries of this verification

This replica test exercises Nginx and the gateway on localhost only.
It does **not** prove Railway ingress, TLS termination, DNS, firewall,
edge proxy headers, or live production data are configured correctly.
Those require a separately authorized disposable deployment and
network observation without real secrets.

The last verified previous commit `58b42d0b7e2203ef2b4579f6b31266667e723e52`
passed all 11 GitHub Actions. Its image inventory still reported 103
HIGH findings, with zero scanner-reported fixable HIGH/CRITICAL. This
does not prove unreachability. Do not replace the pinned OS packages
speculatively. Continue tracking upstream patches and test each
runtime base-image update with complete smoke and data durability tests.

No database schema changes, persisted record changes, production
deployments, merges, or account provisioning in this patch.
Before merge, require green CI on the exact new SHA plus independent
review and residual-risk acceptance. Keep PR #112 Draft.
