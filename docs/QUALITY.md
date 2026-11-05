# Engineering quality gates and reliability policy

**Status:** This document is a policy and a testable baseline, not a claim of enterprise production readiness and not a record of results. Dated evidence — test counts, coverage, builds, browser runs — belongs in [STATUS.md](STATUS.md); do not restate or revise it here, and never describe a check as executed unless an actual run recorded it.

## Every pull request must pass

1. **Static checks:** Ruff Python lint, Python compilation, JavaScript syntax, dependency consistency.
2. **Compatibility matrix:** tests on Python **3.11, 3.12 and 3.13** (all supported by the project).
3. **Coverage:** branch-aware coverage of both the API and engine; **84% minimum** initially. Raise the gate as tests expand. Coverage is a floor, not a proof of correctness.
4. **Security:** `pip-audit --strict --no-deps` over pinned installed third-party dependencies, excluding only the local unpublished Oryveta wheel and Bandit for medium-or-higher severity findings. Review results rather than suppressing alerts without evidence.
5. **Packaging:** build an installable wheel and import the installed packages.
6. **Container:** build the Docker image, verify the API imports and process runs without root privileges; validate Compose configuration.
7. **Documentation:** keep `docs/STATUS.md`, architecture decisions and user-facing limitations current when behavior changes.

## React Studio route/build gate

The React Studio gate must build both deployment targets: `npm --prefix apps/web/studio run build` (`dist`, hosted root) and `npm --prefix apps/web/studio run build:local` (`dist-local`, self-hosted `/studio/`). Compiled browser checks must cover direct route reloads, Back/Forward, breadcrumb navigation, draft retention, keyboard/mobile headers, and reduced-motion behavior across the current public routes (`/`, `/about`, `/what-we-do`, `/pricing`, `/sign-in`) and the signed-in workspace. HTTP checks must confirm extensionless routes receive the app shell while reserved API-like paths remain `404`. Each allowlisted dotted distribution file must have a **positive** check that it is actually served — `demo-stories.json`, `template-license.txt`, `geist-license.txt`, `repair-example.json`, `repair-example.patch` — because a built file with no route is silently a `404`, and a negative-only "dotted paths 404" assertion cannot catch that. Any other dotted path must stay `404`, and an absent self-hosted build must remain an honest `503`.

GitHub Actions workflows use minimal read permissions, SHA-pinned official actions, no credentials persisted by checkout, per-job timeouts, and pull-request concurrency cancellation. Dependabot checks Python, GitHub Actions and Docker dependencies weekly. A scheduled weekly security scan runs even when there are no PRs.

Browser jobs pin Playwright `1.64.1` and install Chromium with `--with-deps`, matching the real-auth integration job. The older `1.55.0` pin fails browser provisioning on GitHub's Ubuntu 26 runners; unsupported-host failures must not be bypassed or mistaken for application test failures.

## Real hosted-auth boundary tests

The auth integration job starts isolated Supabase CLI 2.121.0 native PostgreSQL, Auth, PostgREST and Mailpit, applies the schema and transactional RLS cases, then runs `scripts/auth_ui_smoke.py` against a production-built Studio. The browser requests real email links and opens them in a new tab; three users exercise project/session grants, denial, revocation and replay. No auth responses are mocked. Setup is maintained in [IDENTITY-WORKSPACES.md](IDENTITY-WORKSPACES.md).

Local captured email is not external mailbox delivery, GitHub consent or a production deployment. Vercel builds also reject privileged browser keys and Supabase origins absent from the deployed CSP. The source credential scanner covers both React source and legacy browser configuration.

`scripts/collaboration_race_smoke.py` adds real-service browser regressions for slow and out-of-order responses. It defers delivery of actual HTTP responses rather than mocking successes, covering identity-scoped chat details, collection refresh order, pending mutation acknowledgements, navigation lifetimes and the newest bounded message window. Its fixture cleanup fails loudly instead of claiming success when temporary data remains. The auth-integration workflow runs it after schema setup.

## Local coding-loop verification

CI explicitly provisions a local Python execution image and runs the coding-runtime/sandbox cases on every Python matrix version. These tests use real containers for behavioral acceptance, denied network/host writes, resource limits and teardown; scripted models make proposal/denial cases deterministic. They do not establish model coding quality.

For local execution, set `ORYVETA_TEST_DOCKER_CONTEXT` and `ORYVETA_TEST_DOCKER_IMAGE` to an authorized local context and preloaded immutable image ID. On a Docker VM, set `ORYVETA_TEST_RUN_ROOT` to a shared private host directory. Without explicit context/image selection, real-container cases are skipped; do not describe that run as isolation verification.

Controller interruption regressions launch the actual CLI in child processes, run baseline checks in real containers, and use deterministic paused model/runner boundaries for SIGKILL and SIGTERM. They verify retained reservations, attempted-tool counts, unverified patch hashes and graceful cleanup. Separate storage-failure cases require checkpoint admission to fail closed and terminal-write failure to leave no verified artifact. These tests are not live-model performance measurements or host-power-loss simulations.

The separate `scripts/smoke_coding.py` command exercises the real local model, tools, CLI and independent verifier; setup is in [IMPLEMENTATION.md](IMPLEMENTATION.md#local-verified-repair-cli). Keep actual model outcomes and failed attempts distinct from scripted-model regressions. A passed synthetic repair is not a benchmark or a security certification — see the single-case framing in [EVALUATION.md](EVALUATION.md#current-status).

The model-free candidate re-verification mode (`--candidate-zip`) needs its own gate, and it is a *different* gate from the repair loop because it must hold with no model present at all. Required coverage, stated as policy rather than as a completed result: a candidate whose only changes are inside `write_paths` reaches `needs_review`; a candidate that adds or removes any file is refused as `candidate_inventory`; a candidate touching a file outside `write_paths` is refused as `candidate_scope` **before any execution**; an unchanged candidate is `no_change`; a malformed, oversized or unsafe archive is `invalid_candidate`; a tampered candidate that fails a declared case yields `verification_failed` and leaves `unverified.patch` plus `candidate.zip` as evidence with no `verified.patch`; a run with **no Ollama endpoint reachable** still completes normally with `model_calls`, `turns`, `tool_calls` and `tokens_observed` all `0` and no `model_observed`/`model_summary`; a supplied `passed` claim inside the candidate changes nothing; a repair-mode candidate export round-trips through the importer, including a project whose only top-level entry is itself a folder; and `candidate_tree_sha256` matches between a repair run and the re-verification of its exported archive. Omitting the no-model case would let an accidental model dependency pass unnoticed, which is why `scripts/smoke_reverify.py` defaults to a nonexistent model name and an all-zero digest rather than to a working one.

## Verified local hardening tests

- Browser-bound OAuth state, callback success and one-time replay rejection; auth responses must not be cached.
- Cross-account access restrictions and CSRF checks.
- ZIP import limits, canonical paths, traversal, special files, case-insensitive duplicates and file/directory collisions. Validate before writing files.
- Export size preflight and symlink non-following.
- GitHub import fixed-host API calls, trusted redirect allowlist and bounded downloads (mocked HTTP; no network required).
- SQLite WAL, foreign keys and integrity checks; concurrent worker claims.
- Fenced worker completion and failure: a worker that loses/expires its lease cannot publish stale results.
- Atomic repository analysis completion and job status updates.

That early hardening preflight passed 61 tests locally at the time; it is a historical figure, not the current suite — current counts and coverage are in [STATUS.md](STATUS.md). Enterprise job controls require independent remote Python 3.11–3.13 CI validation before merge. Coverage is a floor, not a measure of autonomous agent performance.

## Required repository protection (manual GitHub admin configuration)

Repository **Settings → Branches / Rulesets** should protect `main` by requiring a PR, approval, conversation resolution, and successful status checks for **Static checks**, each **Tests / Python** matrix job, **Dependency and source security**, and **Docker build and smoke**. Require branches to be up to date, prevent force pushes and deletions, and restrict bypasses. The connected GitHub integration does not currently provide permission to configure branch protection; **these settings are not claimed to be active**.

## Production gates not yet satisfied

- Production GitHub identity and project/session authorization are verified; repository-access GitHub App grants and broader enterprise administration remain unimplemented.
- Production multi-tenant isolation/network policy for arbitrary customer code is not implemented; the operator-run local Docker CLI is not that boundary, and neither is its re-verification mode.
- The single-host worker has heartbeats and admission limits. Remote execution, secrets management, infrastructure rate limits and autoscaling remain unimplemented, and no always-on worker is hosted.
- No signed/pinned fully reproducible Python dependency lockfile or pinned Docker base-image digest yet.
- Production OAuth and controlled multi-user browser authorization pass. General email delivery, load tests, disaster recovery and canary/rollback deployment remain separate gates.
- No evidence of autonomous coding performance or Kaggle leaderboard success. One historical synthetic repair exists; it is not a rate, a benchmark or real-repository qualification, and candidate re-verification produces verdicts about declared contracts rather than evaluation evidence.
- Recorded security-advisor findings include reviewed exceptions. Report current results only from an actual check; see [AUTH-SECURITY.md](AUTH-SECURITY.md#release-gates).
- Operated restoration, recovery objectives, availability and compliance claims remain unestablished in the recorded evidence; no paid deployment is authorized.

Do not enable arbitrary repository execution or offer consultancy-grade SLA until these gaps have been addressed and tested. See [AUTH-SECURITY.md](AUTH-SECURITY.md) and [OPERATIONS.md](OPERATIONS.md).

## Preflight before opening PRs

For CI/workflow changes, push to a `ci/preflight-*` branch and verify the **same complete workflow** (static, Python 3.11–3.13, security and Docker) is green before opening a PR. Then review the PR's checks again; green preflight is evidence, not a guarantee against infrastructure outages or future dependency advisories. Keep PRs draft until required checks pass. Security scanning must fail on real vulnerabilities and may not be disabled merely to make CI green.

Dependency auditing runs against a fully pinned snapshot of the actual installed distributions, excluding the local unpublished `oryveta` wheel. This avoids a scanner failure on a distribution that has no public vulnerability index record while preserving audits for runtime and scanner dependencies. GitHub Actions are pinned to reviewed commit SHAs.
