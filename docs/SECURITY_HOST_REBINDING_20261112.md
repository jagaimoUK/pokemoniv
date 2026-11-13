# Loopback Host validation and JSON media-type security

Date: 2026-11-12 JST. Draft PR #112. No production deployment.

## Source analysis and mitigation

`pvpoke_web.py` binds the internal calculation server to
`127.0.0.1:8765`. The direct `GET /` HTML contains a random local bearer
token used to make internal POST requests. This is an intentional local UI
feature, but the handler previously accepted any HTTP `Host` value.
A browser DNS-rebinding setup could attempt to fetch this local page through
an attacker-controlled hostname. Same-origin and token checks on POST add
further protection but do not justify exposing the local token through a
foreign Host value.

The local handler now requires an exact `Host` of `127.0.0.1:<bound-port>`
or `localhost:<bound-port>` for both GET and POST, and rejects missing or
duplicate Host headers. This protects the local token-bearing page,
status/catalog routes and finished result ZIP against hostile browser Host
values without moving the service to a different port or changing user
configuration. It is defense in depth, not protection against another
already-compromised process on the same host or an attacker who can forge
HTTP headers outside a browser.

The internal JSON POST handler also now checks the actual media type
before the first semicolon, not whether the header merely contains the
substring `application/json`. Normal `application/json; charset=utf-8`
and the existing bridge continue to be supported.

The new regression uses a disposable localhost server and synthetic
headers. It verifies 403 for hostile Host on `/`, `/api/catalog`,
`/api/status`, `/download` and a privileged POST; 200 for both
legitimate loopback hostnames; and 415 for disguised JSON media types.
It verifies that a rejected request does not start the battle client.

## Security context and outstanding gates

Previous commit `8c3bcbf9ae10d6b3f2f4b354e50f899e7b7b1fd2`
had 11/11 successful CI workflows, including Python/JS tests, image
builds, secret scan and image vulnerability inventory. That success
does not validate this new commit.

Official Debian security tracking at the time of review still marks
several SQLite trixie and Kerberos trixie CVEs as vulnerable. The most
recent image scan counted 103 HIGH entries and zero with scanner-reported
fixes. Do not replace the pinned runtime or silently remove native
dependencies without functional builds, package audit and data durability
testing. Counts may change when the image is rebuilt.

This application is presently a single-owner deployment. This change
does not add multi-tenant authentication, restrict public static pages,
verify remote hosting firewall ACLs or perform live penetration tests.
Other outstanding gates: genuine ENOSPC/WAL checkpoint on a disposable
volume, client-origin/CSRF validation under a real edge proxy, full
native 4096-IV load and tactical information fairness, independent
Astra audit and safe release authorization.

PR remains **Draft / no merge / no deployment**.
