# Uniform strict JSON parsing for all private API entry points

Date: 2026-11-12 JST. Draft PR #112, no production change.

## Root issue and correction

The gateway previously rejected duplicate JSON keys and JavaScript-style
non-finite numeric literals (NaN, Infinity) only for Sandbox and direct
battle calculation. Ordinary app routes, backup routes, and authenticated
JSON-RPC requests used `json.loads` defaults, which allow duplicate fields
(last wins) and non-finite numbers. The internal calculation server applied
the same strict-vs-legacy split. This causes inconsistent interpretation of
client requests and can undermine validation, auditing and future policy
enforcement. It is a consistency/security-hardening issue, **not a proven
unauthenticated compromise**.

All incoming JSON at the public app gateway, visual-backup endpoint,
JSON-RPC endpoint and local calculation API now uses the existing
`_unique_object` and `_reject_constant` helpers. Valid RFC-style JSON
has unchanged behavior; ambiguous or non-finite payloads return HTTP 400.
No database schema changes, migrations, stored data changes or new
authentication identities.

The regression tests send synthetic duplicate top-level/nested keys,
NaN and Infinity through app, backup, JSON-RPC and legacy local routes,
and verify input rejection before backend operations. Existing tests
still cover successful legitimate requests.

## Current verified security baseline

The previous exact commit `dc75139293779085c5017f5a605f9b5c94e5f0a9`
passed **11/11 GitHub Actions**, including real OS ENOSPC tests of both
DELETE and WAL on a disposable Docker 2 MiB tmpfs, runtime secret scan,
browser/CSP checks, package scan, and image build.

The image still reported 103 HIGH package findings and zero with
scanner-reported HIGH/CRITICAL fixes. This is neither equivalent to a
proven exploitable route nor a clean security audit. Source and test
verification cannot establish external network controls, production
database durability, arbitrary multi-tenant isolation or resilience to
a compromised host.

## Remaining gates

1. Confirm CI success on this **new** commit.
2. Test production-like network/routing and authentication on a
   disposable replica without real secrets or data, including all
   public HTML and initial API calls.
3. Continue tracking Debian CVE fixes, redeploy only an image with
   tested dependencies. No unsupported package replacement.
4. Independent adversarial/peer review, operational restore and
   performance limits remain required before merge or production release.

PR remains Draft and unmerged.
