# Engineering quality gates and reliability policy

**Status:** CI hardening and security audit repair merged via PR #7; Evolve patch previews merged via PR #8. This document is a policy and a testable baseline, not a claim of enterprise production readiness.

## Every pull request must pass

1. **Static checks:** Ruff Python lint, Python compilation, JavaScript syntax, dependency consistency.
2. **Compatibility matrix:** tests on Python **3.11, 3.12 and 3.13** (all supported by the project).
3. **Coverage:** branch-aware coverage of both the API and engine; **84% minimum** initially. Raise the gate as tests expand. Coverage is a floor, not a proof of correctness.
4. **Security:** `pip-audit --strict --no-deps` over pinned installed third-party dependencies, excluding only the local unpublished Oryveta wheel and Bandit for medium-or-higher severity findings. Review results rather than suppressing alerts without evidence.
5. **Packaging:** build an installable wheel and import the installed packages.
6. **Container:** build the Docker image, verify the API imports and process runs without root privileges; validate Compose configuration.
7. **Documentation:** keep `docs/STATUS.md`, architecture decisions and user-facing limitations current when behavior changes.

## React Studio route/build gate

The React Studio gate must build both deployment targets: `npm --prefix apps/web/studio run build` (`dist`, hosted root) and `npm --prefix apps/web/studio run build:local` (`dist-local`, self-hosted `/studio/`). Compiled browser checks must cover direct route reloads, Back/Forward, breadcrumb navigation, draft retention, keyboard/mobile headers, and reduced-motion behavior. HTTP checks must confirm extensionless routes receive the app shell while missing dotted assets and reserved API-like paths remain `404`; an absent self-hosted build remains an honest `503`.

GitHub Actions workflows use minimal read permissions, SHA-pinned official actions, no credentials persisted by checkout, per-job timeouts, and pull-request concurrency cancellation. Dependabot checks Python, GitHub Actions and Docker dependencies weekly. A scheduled weekly security scan runs even when there are no PRs.

## Real hosted-auth boundary tests

The auth integration job starts isolated Supabase CLI 2.121.0 native PostgreSQL, Auth, PostgREST and Mailpit, applies the schema and transactional RLS cases, then runs `scripts/auth_ui_smoke.py` against a production-built Studio. The browser requests real email links and opens them in a new tab; three users exercise project/session grants, denial, revocation and replay. No auth responses are mocked. Setup is maintained in [IDENTITY-WORKSPACES.md](IDENTITY-WORKSPACES.md).

Local captured email is not external mailbox delivery, GitHub consent or a production deployment. Vercel builds also reject privileged browser keys and Supabase origins absent from the deployed CSP. The source credential scanner covers both React source and legacy browser configuration.

## Verified local hardening tests

- Browser-bound OAuth state, callback success and one-time replay rejection; auth responses must not be cached.
- Cross-account access restrictions and CSRF checks.
- ZIP import limits, canonical paths, traversal, special files, case-insensitive duplicates and file/directory collisions. Validate before writing files.
- Export size preflight and symlink non-following.
- GitHub import fixed-host API calls, trusted redirect allowlist and bounded downloads (mocked HTTP; no network required).
- SQLite WAL, foreign keys and integrity checks; concurrent worker claims.
- Fenced worker completion and failure: a worker that loses/expires its lease cannot publish stale results.
- Atomic repository analysis completion and job status updates.

Earlier hardening preflight passed 61 tests locally. Enterprise job controls require independent remote Python 3.11–3.13 CI validation before merge. Coverage is not a measure of autonomous agent performance.

## Required repository protection (manual GitHub admin configuration)

Repository **Settings → Branches / Rulesets** should protect `main` by requiring a PR, approval, conversation resolution, and successful status checks for **Static checks**, each **Tests / Python** matrix job, **Dependency and source security**, and **Docker build and smoke**. Require branches to be up to date, prevent force pushes and deletions, and restrict bypasses. The connected GitHub integration does not currently provide permission to configure branch protection; **these settings are not claimed to be active**.

## Production gates not yet satisfied

- Production GitHub identity and project/session authorization are verified; repository-access GitHub App grants and broader enterprise administration remain unimplemented.
- Hardened isolation/network policy for executing customer code is not implemented.
- The single-host worker has heartbeats and admission limits. Remote execution, secrets management, infrastructure rate limits and autoscaling remain unimplemented.
- No signed/pinned fully reproducible Python dependency lockfile or pinned Docker base-image digest yet.
- Production OAuth and controlled multi-user browser authorization pass. General email delivery, load tests, disaster recovery and canary/rollback deployment remain separate gates.
- No evidence of autonomous coding performance or Kaggle leaderboard success.

Do not enable arbitrary repository execution or offer consultancy-grade SLA until these gaps have been addressed and tested. See [AUTH-SECURITY.md](AUTH-SECURITY.md) and [OPERATIONS.md](OPERATIONS.md).

## Preflight before opening PRs

For CI/workflow changes, push to a `ci/preflight-*` branch and verify the **same complete workflow** (static, Python 3.11–3.13, security and Docker) is green before opening a PR. Then review the PR's checks again; green preflight is evidence, not a guarantee against infrastructure outages or future dependency advisories. Keep PRs draft until required checks pass. Security scanning must fail on real vulnerabilities and may not be disabled merely to make CI green.

Dependency auditing runs against a fully pinned snapshot of the actual installed distributions, excluding the local unpublished `oryveta` wheel. This avoids a scanner failure on a distribution that has no public vulnerability index record while preserving audits for runtime and scanner dependencies. GitHub Actions are pinned to reviewed commit SHAs.
