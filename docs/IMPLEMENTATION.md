# Functional MVP implementation — code map and verified boundaries

Status: **Merged local API and hosted read-only frontend**. The Python API is not deployed to Vercel. This page documents what the code actually does, and deliberately distinguishes starter generation and static analysis from autonomous software engineering.

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
| `apps/web/` | Standalone Soft Modern local UI served by FastAPI |
| `preview/` | Archived standalone static prototype; **not deployed** to Vercel |
| `apps/web/vercel.json` | Vercel static asset rewrites for the real app UI, read-only without hosted API |
| `tests/` | API, ownership, CSRF, OAuth state, archive safety, worker and scaffold tests |
| `Dockerfile`, `compose.yaml` | Single-host API and worker containers with local-only port binding |

## Run and test

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export ORYVETA_LOCAL_DEMO=true
uvicorn oryveta_api.main:app --host 127.0.0.1 --port 8000
# second terminal:
python -m oryveta_engine.worker
# verification:
pytest -q
ruff check apps/api engine tests
node --check apps/web/app.js
```

Python 3.11+ is supported by metadata; GitHub CI tests Python 3.12. No paid model keys required.

## Hardening included in first source PR

- Browser-bound OAuth state in an HttpOnly SameSite cookie plus one-time DB state, preventing a different browser from redeeming a valid OAuth state.
- Owner-scoped project reads and exports, CSRF validation for mutations, localhost-only demo mode, security headers and secure cookie requirements on HTTPS public deployments.
- Bounded GitHub archive streaming, restricted redirect hosts, ZIP traversal/symlink/duplicate-destination rejection, compressed and expanded size limits.
- Atomic benchmark idempotency check-and-insert with conflicting request rejection.
- Exhausted worker leases transition to a terminal failure instead of remaining `running` indefinitely.

## Known production blockers

1. The public `https://oryveta.vercel.app` preview is not connected to this API. It has no actual GitHub login, persistence or agent work.
2. SQLite and file workspaces are single-host and not adequate as-is for multi-tenant consultancy deployment.
3. Source imports are snapshots only; imported code is not executed or changed by an AI agent.
4. The worker does not run in a hardened per-tenant container or microVM and has no managed always-on hosting.
5. OAuth requires real client credentials, production ingress, rate limits, secrets management, audit and backup/restore before internet-facing operation.
6. Full custom application generation, automated bug fixes/PRs, Rust supervisor, Cloudflare/Supabase production DB and self-improving harness remain planned.

## Release discipline

CI passing and code review are necessary, but not sufficient, for production-grade consultancy security. Do not deploy this MVP publicly until threat-model, authorization, operational and integration gates in [AUTH-SECURITY.md](AUTH-SECURITY.md) and [OPERATIONS.md](OPERATIONS.md) are met.
