# Functional MVP implementation — code map and verified boundaries

Status: **Merged local API and React Studio frontend; hosted React/Supabase integration remains separately configured.** The Python API is not deployed to Vercel. This page documents actual code and distinguishes deterministic starters/read-only analysis from autonomous software engineering.

## Local architecture

| Path | Responsibility |
| --- | --- |
| `apps/api/oryveta_api/main.py` | FastAPI routes, owner-scoped project CRUD, GitHub identity OAuth, imports, exports, job requests |
| `apps/api/oryveta_api/auth.py` | Hashed session tokens, CSRF checks, session-bound user lookup |
| `apps/api/oryveta_api/database.py` | SQLite schema, indexed lookups, per-operation connections, job/event records |
| `apps/api/oryveta_api/config.py` | Validated base URL, demo restrictions, OAuth settings, workspace path |
| `engine/oryveta_engine/repositories.py` | Bounded public GitHub downloads, ZIP path validation, export |
| `engine/oryveta_engine/analysis.py` | Heuristic, non-executing source inspection and evidence |
| `engine/oryveta_engine/scaffold.py` | Portable runnable project templates, tests and CI skeleton |
| `engine/oryveta_engine/benchmarks.py` | Deterministic local classification baselines; not Kaggle |
| `engine/oryveta_engine/worker.py` | SQLite lease-based background worker, retry limits and status |
| `apps/web/` | Legacy standalone Soft Modern local UI served at `/`; hosted React Studio builds to `apps/web/studio/dist`, while the self-hosted React Studio uses the separate `apps/web/studio/dist-local` build at `/studio/`. Extensionless `/studio/*` page routes receive the app shell; dotted assets and reserved API-like paths do not. Missing local builds return `503` without replacing the legacy path |
| `preview/` | Archived standalone static prototype; **not deployed** to Vercel |
| `apps/web/vercel.json` | Vercel asset rewrites and restrictive security headers for the real app UI |
| `apps/web/cloud-auth.js` | Supabase Auth PKCE adapter and owner-scoped workspace data client; inactive until configured |
| `apps/web/cloud-config.js` | Public-only Supabase project URL and publishable key placeholders |
| `supabase/schema.sql` | Owner-initiated workspaces, membership trigger and per-row authorization policies |
| `tests/` | API, ownership, CSRF, OAuth state, archive safety, worker and scaffold tests |
| `Dockerfile`, `compose.yaml` | Single-host API and worker containers with local-only port binding |

## Run and test

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export ORYVETA_LOCAL_DEMO=true
export ORYVETA_BASE_URL=http://127.0.0.1:8000
uvicorn oryveta_api.main:app --host 127.0.0.1 --port 8000
# second terminal:
python -m oryveta_engine.worker
```

Build the React Studio separately with Node 20+:

```bash
npm --prefix apps/web/studio ci
npm --prefix apps/web/studio run check
npm --prefix apps/web/studio run build
npm --prefix apps/web/studio run build:local
```

The hosted build writes `apps/web/studio/dist`; `build:local` writes `apps/web/studio/dist-local` for the FastAPI `/studio/` surface. Open `http://127.0.0.1:8000/studio/`, sign in to local demo, and use Start New/Evolve. `pytest -q`, coverage and `ruff check apps/api engine tests` provide Python gates.

Python 3.11+ is supported by metadata; GitHub CI tests Python 3.12. No paid model keys required.

## Hardening included in first source PR

- Browser-bound OAuth state in an HttpOnly SameSite cookie plus one-time DB state, preventing a different browser from redeeming a valid OAuth state.
- Owner-scoped project reads and exports, CSRF validation for mutations, localhost-only demo mode, security headers and secure cookie requirements on HTTPS public deployments.
- Bounded GitHub archive streaming, restricted redirect hosts, ZIP traversal/symlink/duplicate-destination rejection, compressed and expanded size limits.
- Atomic benchmark idempotency check-and-insert with conflicting request rejection.
- Exhausted worker leases transition to a terminal failure instead of remaining `running` indefinitely.

## Known production blockers

1. The public Vercel React Studio is not connected to the self-hosted FastAPI engine; hosted flows remain planning/storyboard experiences.
2. SQLite and file workspaces are single-host and not adequate as-is for multi-tenant consultancy deployment.
3. Source imports are snapshots only; imported code is not executed or changed by an AI agent.
4. The worker does not run in a hardened per-tenant container or microVM and has no managed always-on hosting.
5. Supabase Auth/workspace integration is implemented in the React client/schema, but real mailbox login, two-user RLS/browser authorization and provider configuration remain unverified.
6. OAuth requires real client credentials, production ingress, rate limits, secrets management, audit and backup/restore before internet-facing operation.
7. Full custom application generation, automated bug fixes/PRs, Rust supervisor, managed Cloudflare/Supabase production infrastructure and self-improving harness remain planned.

## Release discipline

CI passing and code review are necessary, but not sufficient, for production-grade consultancy security. Do not deploy this MVP publicly until threat-model, authorization, operational and integration gates in [AUTH-SECURITY.md](AUTH-SECURITY.md) and [OPERATIONS.md](OPERATIONS.md) are met.
