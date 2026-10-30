# Security policy

This repository contains a personal, single-owner Pokémon GO helper. Publishing
the source does not make the hosted application a public or multi-user service.
Authentication and the configured Auth0 owner restriction must stay enabled.

Do not include API keys, cookies, backup connection codes, private screenshots,
or personal data in public issues, pull requests, or logs. Use GitHub's private
vulnerability reporting if it is available, or contact the repository owner
privately. Do not post a working exploit against the live service publicly.

Only run load/security tests on your own local instance or an explicitly
authorized test environment. Do not test other users' deployments.

The security workflow checks reachable Git history, pinned Python dependencies,
regression tests, the production image, and browser script initialization.
Passing it does not certify all infrastructure, credentials, operating-system
packages, or separately protected assets. Deployment and public-release review
conditions are recorded in `docs/security-remediation-20261031.md`.

Never commit a real `.env`, signing key, cookie database, or backup connection
code. Supply secrets through the hosting provider's secret configuration.
