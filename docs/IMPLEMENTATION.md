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
| `engine/oryveta_engine/factory_runtime.py` | Project-scoped durable analysis worker: Auth session refresh, PostgREST RPC transitions, fenced leases and a supervised analysis child |
| `engine/oryveta_engine/analysis_child.py` | Child-process entry point that runs `analyze_repository` over a prepared snapshot and writes the JSON result atomically |
| `apps/web/` | Legacy standalone Soft Modern local UI served at `/`; hosted React Studio builds to `apps/web/studio/dist`, while the self-hosted React Studio uses the separate `apps/web/studio/dist-local` build at `/studio/`. Extensionless `/studio/*` page routes receive the app shell; dotted assets and reserved API-like paths do not. Missing local builds return `503` without replacing the legacy path |
| `preview/` | Archived standalone static prototype; **not deployed** to Vercel |
| `apps/web/vercel.json` | Vercel asset rewrites and restrictive security headers for the real app UI |
| `apps/web/cloud-auth.js` | Supabase Auth PKCE adapter and owner-scoped workspace data client; inactive until configured |
| `apps/web/cloud-config.js` | Public-only Supabase project URL and publishable key placeholders |
| `supabase/schema.sql` | Owner-initiated workspaces, membership trigger and per-row authorization policies |
| `supabase/migrations/durable_factory_runtime.sql` | Work items, fenced runs, typed run events, per-project worker registrations and the unexposed lease table |
| `tests/` | API, ownership, CSRF, OAuth state, archive safety, worker and scaffold tests |
| `Dockerfile`, `compose.yaml` | Single-host API and worker containers with local-only port binding |

The hosted collaboration slice uses `apps/web/studio/src/lib/identity.js`, `projects.js`, `pages/Projects.jsx` and the existing private-chat client. `supabase/migrations/projects_and_project_membership.sql` adds project RLS/RPCs without merging local engine identities. `scripts/auth_ui_smoke.py` exercises actual local Supabase Auth/PostgREST/PostgreSQL/Mailpit and a production-built Studio with headless Chromium; setup and deployment prerequisites are in [IDENTITY-WORKSPACES.md](IDENTITY-WORKSPACES.md).

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

Build the React Studio separately with Node 20.19+ or 22.12+:

```bash
npm --prefix apps/web/studio ci
npm --prefix apps/web/studio run check
npm --prefix apps/web/studio run build
npm --prefix apps/web/studio run build:local
```

The hosted build writes `apps/web/studio/dist`; `build:local` writes `apps/web/studio/dist-local` for the FastAPI `/studio/` surface. Open `http://127.0.0.1:8000/studio/`, sign in to local demo, and use Start New/Evolve. `pytest -q`, coverage and `ruff check apps/api engine tests` provide Python gates.

Python 3.11+ is supported by metadata; backend CI tests Python 3.11–3.13. No paid model keys are required.

## Durable analysis worker (self-hosted)

`engine/oryveta_engine/factory_runtime.py` is a client of `supabase/migrations/durable_factory_runtime.sql`. It authenticates as its own Supabase Auth service identity, serves exactly one project, and performs exactly one task kind: a bounded public-GitHub snapshot plus the existing static analyzer. Apply the migration after `supabase/schema.sql`, the private-chat migration and the project-membership migration, then register the worker identity with `register_project_worker` as described in [OPERATIONS.md](OPERATIONS.md).

The credential file is a JSON object in a protected regular file:

```json
{
  "supabase_url": "https://<project-ref>.supabase.co",
  "publishable_key": "<publishable (anon) key>",
  "project_id": "<project uuid>",
  "refresh_token": "<worker Auth session refresh token>"
}
```

`supabase_url` must be a bare origin; plain `http` is accepted only for a loopback test stack. `anon_key` is accepted as an alias for `publishable_key`. `project_id` is optional and only supplies the default for `--project`. The worker also stores `access_token` and `expires_at` in this file after each refresh. A symlink, or any file with group or world permission bits, is refused: use `chmod 600`. **The service-role key never appears here and is never used by the worker**; its authority is an ordinary Auth session plus one enabled `project_workers` row.

```bash
export ORYVETA_WORKER_CREDENTIALS=/etc/oryveta/worker-credentials.json
python -m oryveta_engine.factory_runtime --once
```

| Flag | Meaning |
| --- | --- |
| `--credentials` | Protected worker credential file; defaults to `$ORYVETA_WORKER_CREDENTIALS` and is required if neither is set |
| `--project` | Project UUID to serve; defaults to the credential file's `project_id` |
| `--once` | Claim and complete at most one work item, then exit |
| `--max-runs` | Stop after this many completed claims in continuous mode |
| `--lease-seconds` | Lease length, 15–900 seconds, default 300 |
| `--max-run-seconds` | Bounded runtime for one analysis child process, default 900 |
| `--poll-seconds` | Idle delay between claim attempts in continuous mode, default 5 |
| `--work-root` | Persistent parent for disposable snapshots; startup reclaims marked directories whose worker is gone. Set this for crash cleanup. |

Startup verifies an enabled project-worker registration. Each claim freezes the project source, revalidates its owner/repo with the importer, fetches a bounded archive, and runs the trusted static analyzer in a credential-free child process. Heartbeats fence every phase and run at most 30 seconds apart while analyzing. The source download remains one unheartbeated window: size the lease for the bounded fetch. Transport failures are distinct from source errors; heartbeats retry within the remaining lease margin. Fencing signals the whole analysis process group with SIGTERM, then SIGKILL after a five-second grace. Source identity conflicts, unresolved commits and creator authorization loss cannot publish results.

Resume semantics are deliberately narrow. **A crashed analysis is recomputed, not resumed in memory.** The work item's frozen URL, owner/repo and input digest survive project edits. The first accepted source resolution pins `pinned_source_ref` and `pinned_source_commit` on that work item. Claims return that pin plus `previous_source_digest` and `previous_checkpoint`; retries request the exact pinned commit without falling back to HEAD. Checkpoints report `resumed_attempt`, `source_commit`, `source_pinned` and whether the archive digest matches the previous attempt.

The first attempt resolves the default branch. GitHub's ZIP comment supplies the full commit; the short root-directory suffix is checked for agreement, not mistaken for a full hash. Missing or conflicting identity fails closed. Later attempts fetch the exact pin. Imported source is read, never executed. There is still no hosted always-on worker: an operator must start and supervise this process on an authorized host.

Persisted output is bounded on both sides: the schema allows 256 KB and 400 findings; the worker retains at most 200 and exposes truncation explicitly. Normal completion removes the snapshot. A hard-killed worker leaves its directory for the next `--work-root` startup sweep, which removes only marked directories belonging to dead processes. The child receives the original worker PID, refuses an already-orphaned start, monitors parent loss and carries its own deadline. These guards do not simulate recovery from losing the host.

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
5. Local real Supabase email/PKCE, project/session authorization and multi-user browser checks pass. Hosted migration deployment, external mailbox delivery, GitHub OAuth consent and production redirect verification remain separate prerequisites.
6. OAuth requires real client credentials, production ingress, rate limits, secrets management, audit and backup/restore before internet-facing operation.
7. Custom application generation, automated verified fixes/PRs, hosted worker execution, Slack/mobile delivery and the self-improving harness remain planned. The selected path extends Python rather than requiring a Rust/Hono rewrite.

## Release discipline

CI passing and code review are necessary, but not sufficient, for production-grade consultancy security. Do not deploy this MVP publicly until threat-model, authorization, operational and integration gates in [AUTH-SECURITY.md](AUTH-SECURITY.md) and [OPERATIONS.md](OPERATIONS.md) are met.
