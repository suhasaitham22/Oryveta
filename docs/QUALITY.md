# Engineering quality gates and reliability policy

**Status:** Implemented in `hardening/ci-quality-security` PR, pending merge. This document is a policy and a testable baseline, not a claim of enterprise production readiness.

## Every pull request must pass

1. **Static checks:** Ruff Python lint, Python compilation, JavaScript syntax, dependency consistency.
2. **Compatibility matrix:** tests on Python **3.11, 3.12 and 3.13** (all supported by the project).
3. **Coverage:** branch-aware coverage of both the API and engine; **84% minimum** initially. Raise the gate as tests expand. Coverage is a floor, not a proof of correctness.
4. **Security:** `pip-audit --strict --skip-editable` for installed dependency advisories and Bandit for medium-or-higher severity findings. Review results rather than suppressing alerts without evidence.
5. **Packaging:** build an installable wheel and import the installed packages.
6. **Container:** build the Docker image, verify the API imports and process runs without root privileges; validate Compose configuration.
7. **Documentation:** keep `docs/STATUS.md`, architecture decisions and user-facing limitations current when behavior changes.

GitHub Actions workflows use minimal read permissions, SHA-pinned official actions, no credentials persisted by checkout, per-job timeouts, and pull-request concurrency cancellation. Dependabot checks Python, GitHub Actions and Docker dependencies weekly. A scheduled weekly security scan runs even when there are no PRs.

## Verified local hardening tests

- Browser-bound OAuth state, callback success and one-time replay rejection; auth responses must not be cached.
- Cross-account access restrictions and CSRF checks.
- ZIP import limits, canonical paths, traversal, special files, case-insensitive duplicates and file/directory collisions. Validate before writing files.
- Export size preflight and symlink non-following.
- GitHub import fixed-host API calls, trusted redirect allowlist and bounded downloads (mocked HTTP; no network required).
- SQLite WAL, foreign keys and integrity checks; concurrent worker claims.
- Fenced worker completion and failure: a worker that loses/expires its lease cannot publish stale results.
- Atomic repository analysis completion and job status updates.

The local test run is **61 passed** on Python 3.13 with **84.55% branch-aware coverage**. This number is not a benchmark of autonomous agent performance, and remote GitHub CI must be checked separately before merging.

## Required repository protection (manual GitHub admin configuration)

Repository **Settings → Branches / Rulesets** should protect `main` by requiring a PR, approval, conversation resolution, and successful status checks for **Static checks**, each **Tests / Python** matrix job, **Dependency and source security**, and **Docker build and smoke**. Require branches to be up to date, prevent force pushes and deletions, and restrict bypasses. The connected GitHub integration does not currently provide permission to configure branch protection; **these settings are not claimed to be active**.

## Production gates not yet satisfied

- No verified production GitHub OAuth credentials or GitHub App repository grants.
- No multi-tenant RBAC, hardened sandbox isolation or network policy for executing imported code.
- No long-running worker heartbeat, remote lease store, rate limiting, secrets manager or autoscaling.
- No signed/pinned fully reproducible Python dependency lockfile or pinned Docker base-image digest yet.
- No authenticated browser e2e suite, load test, disaster recovery drill, external security review or canary/rollback deployment.
- No evidence of autonomous coding performance or Kaggle leaderboard success.

Do not enable arbitrary repository execution or offer consultancy-grade SLA until these gaps have been addressed and tested. See [AUTH-SECURITY.md](AUTH-SECURITY.md) and [OPERATIONS.md](OPERATIONS.md).
