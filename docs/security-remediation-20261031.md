# Security remediation and release conditions (2026-10-31)

Baseline: `fbf81c9af1f60c4f11c71abbcb8f2dc1ede179ef`.
The user explicitly authorized deployment followed by publication of this
repository on 2026-10-31, using local verification and the Railway build while
GitHub CI is unavailable for the private repository. Publishing the source does
not authorize anonymous app access or a multi-user service. The Auth0 owner
restriction remains required.

## Implemented in source

- **F01:** Nginx is the public listener; the Python gateway listens only on
  `127.0.0.1:8788`. Nginx uses 128 worker connections, 24 active requests,
  10-second header/idle-body timeouts, a 23 MiB body ceiling, 10 requests/second
  and a burst of 40. The application bounds its worker count to 24, active app
  requests to four, backups to one, idle sockets to ten seconds, body reads to
  twenty seconds and connection lifetime to ninety seconds. Owner calculation
  starts and backup operations each have an additional 12/minute budget.
  Overload returns 429 or 503. Request bodies stream into the application's
  absolute timer; transfer-encoded requests are rejected at both layers.
  X-Forwarded-For is never trusted as client identity. Behind Railway the peer
  may represent the edge; this peer budget is not claimed to identify visitors.
  Volumetric DDoS protection and verified edge IP attribution remain external.
- **F02/F04:** Only a root key or owner-validated OAuth bearer can issue a
  long-lived browser cookie. A short app token cannot issue one or a year-long
  backup credential. Invalid/non-ASCII/oversized bearer input is rejected.
  Short links still open the app without remembering the login.
- **F03:** Logout revokes the presented browser cookie and app token. Copies
  fail after logout; other browser sessions remain valid. Fingerprints and
  expiry/revocation state are persisted in SQLite, never raw credentials.
  Backup codes can be listed and individually revoked at `/reader-backup`.
  Legacy signed cookies/codes remain compatible and become known on use;
  unused old codes cannot be enumerated from their previous stateless format.
- **F07:** Direct calculation failure stops the calculation. It never
  automatically launches Chromium. Browser mode requires an explicit
  `PVP_ALLOW_BROWSER=1`; do not enable this in production. Browser subprocesses
  have a minimal environment and no `--no-sandbox` flag. Numerical Node
  subprocesses also receive only their required environment.
- **F06:** All 19 workflows declare `contents: read`; external actions use
  commit SHAs verified from their official repositories, and checkout does not
  persist authentication. A stable `Security and regression` workflow runs on
  every PR and every main push with no path filters. It runs regression tests,
  a verified Gitleaks binary, dependency auditing, production image build,
  unprivileged Nginx checks and browser initialization checks. The Railway image
  build itself also checks Nginx under appuser and runs a real three-condition
  Minior Node calculation. Python/OS inventories are retained inside the image;
  these inventories are not a full OS vulnerability audit or a complete SBOM.
- **F08:** Production Python dependencies and wheel hashes are locked for
  CPython 3.12/Linux x86_64. The Python base image is pinned by its registry
  digest. PvPoke data is pinned to upstream commit
  `6477226670913974993c1f7c936331d55cd7d893`, separately from the engine source.
  Both data files are SHA-256 verified, fetched at build time and reused offline
  at startup. Updates require reviewing a new snapshot and hashes; a refresh
  reloads the approved version. OS package vulnerability auditing and a complete
  reproducible OS-package snapshot remain separate work.
- **F09/F10:** Root `THIRD_PARTY_NOTICES.md` contains the complete upstream
  PokéAPI BSD notice and accurate PvPoke local-modification information. The
  notice is included in the image. Existing MIT text is retained. This does not
  select a license for the user's code or clear every Pokémon asset right.
- **F11:** All HTML routes have hash-based script CSP; common responses have
  nosniff, frame denial and no-referrer. HTTPS deployments advertise a short
  one-day HSTS period. Inline styles remain allowed for the existing UI.

## Persistent state and rollback

The revocation database defaults to
`$RAILWAY_VOLUME_MOUNT_PATH/pvpoke_archives/auth.sqlite3` (or the existing archive
base). `PVP_AUTH_DB` can select another persistent file. Without a volume or
explicit persistent path, revocation will not survive replacement of the
container. Do not delete or restore an older authentication DB during an
ordinary rollback: that can resurrect revoked credentials. Code predating this
change also ignores revocations. If reverting to that code is unavoidable after
a credential incident, rotate the root key and reconnect devices deliberately.
Do not restore compromised keys merely to make old cookies work again.

The startup script supervises the engine, application and proxy and exits if
any required process fails. Nginx stays unprivileged after volume bootstrap.
The existing result archives, party database, presets and backup object format
are unchanged. No existing user data migration is required.

## F05: manual release while private CI is unavailable

At the start of this release the main branch is unprotected and Railway
`source.checkSuites` is false. The available connectors cannot set branch
protection or this source field. The user explicitly authorized finishing the
available checks, deploying, and then publishing the repository so CI can run.
Do not interpret the earlier CI failures with zero steps as passing tests.

The current manual gate requires local regression/security tests, the image's
build-time data/hash and unprivileged Nginx/engine checks, a terminal Railway
SUCCESS and low-load HTTP/browser checks. Keep the previous deployment as a
rollback target and preserve the revocation DB. After publication, execute the
stable Security and regression workflow, resolve real failures, then configure
main protection and Railway Wait for CI once the required check is available.
The hosting provider and repository privacy controls may require an interactive
owner sign-in; do not report these settings changed without observing them.

## Verification and remaining release checks

Local verification uses fake credentials, a fake backend or local fixtures;
no real ChatGPT PvPoke MCP tools are called. Small local socket/proxy tests cover
slow headers, absolute deadlines, overload, spoofed forwarded IPs, oversized
bodies and recovery of normal health requests. Authentication tests cover short
token escalation, cookie replay after logout, restart persistence, separate
sessions and backup-code revocation. The browser test is in CI for execution
under the exact HTTP CSP and production image.

During deployment: use the Railway image build as the build gate, then check
the terminal deployment status, revision-bearing health response, unauthenticated
401 behavior and public-page browser initialization. Android clipboard/intent handoff and an actual production backup
round trip still need device-level verification. No Android sources or APK
signatures are changed by this patch.

Remaining operational checks: finish automated F05 enforcement after public CI
works, OS auditing, incident-related credential rotation, Auth0 MFA/owner
settings, S3 private access and asset distribution rights. These are not claimed
complete merely because the user authorized publishing the source. F12 remains an
explicit single-owner design, not tenant isolation.
