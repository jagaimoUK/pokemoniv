# Security remediation and release conditions (2026-10-31)

Baseline: `fbf81c9af1f60c4f11c71abbcb8f2dc1ede179ef`.
Keep this repository private. This change does not authorize public access or a
multi-user service. The Auth0 owner restriction remains required.

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
  unprivileged Nginx checks and browser initialization checks. It exports Python
  and OS package inventories; these inventories are not a full OS vulnerability
  audit or a complete SBOM.
- **F08 (partial):** Production Python dependencies and their wheel hashes are
  locked in `requirements.lock` for CPython 3.12/Linux x86_64. Termux/development
  can still use `requirements.txt`. Image digest, OS packages and game data
  approval/pinning remain separate work; runtime game data is still fetched as
  before, to avoid silently changing the user's active ruleset.
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

## F05: release gate still requires platform configuration

The observed main branch is unprotected and Railway `source.checkSuites` is
false. The available connectors cannot set branch protection or this source
field. Keep the security change on its PR until CI, including the image build,
actually passes. Do not merge a failed or unstarted build merely because local
unit tests passed.

Once Actions can execute successfully, configure main protection with the
stable `security-regression` job and appropriate review restrictions. Enable
Railway Wait for CI (`source.checkSuites=true`) after confirming the main-push
workflow exists. Do not publish the repository to bypass private-plan limits.
If automation is unavailable, use a documented manual deployment gate instead.

## Verification and remaining release checks

Local verification uses fake credentials, a fake backend or local fixtures;
no real ChatGPT PvPoke MCP tools are called. Small local socket/proxy tests cover
slow headers, absolute deadlines, overload, spoofed forwarded IPs, oversized
bodies and recovery of normal health requests. Authentication tests cover short
token escalation, cookie replay after logout, restart persistence, separate
sessions and backup-code revocation. The browser test is in CI for execution
under the exact HTTP CSP and production image.

Before deployment: obtain a passing image build and mobile-browser CSP check,
then check the terminal Railway deployment status, health and unauthenticated
401 behavior. Android clipboard/intent handoff and an actual production backup
round trip still need device-level verification. No Android sources or APK
signatures are changed by this patch.

Before public release: finish F05, image/game-data reproducibility and OS
auditing, confirm incident-related credential rotation, Auth0 MFA/owner
settings, S3 private access and asset distribution rights. F12 remains an
explicit single-owner design, not tenant isolation.
