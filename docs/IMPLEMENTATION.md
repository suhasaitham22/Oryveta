# Functional MVP implementation — code map and verified boundaries

Status: **The React/Supabase collaboration and durable-analysis control plane are deployed.** Production analysis was verified with a one-off local worker; always-on worker hosting remains pending. The separate FastAPI/SQLite engine is not deployed to Vercel. This page distinguishes deterministic starters/read-only analysis from autonomous software engineering.

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
| `engine/oryveta_engine/factory_service.py` | Unattended service entry point: one-time secret bootstrap, exclusive session lock, persistent rotated credentials, mounted-volume privilege drop and SIGTERM handling |
| `engine/oryveta_engine/analysis_child.py` | Child-process entry point that runs `analyze_repository` over a prepared snapshot and writes the JSON result atomically |
| `engine/oryveta_engine/coding_{config,contract,model,tools,sandbox,runtime}.py` | Separate local repair CLI: versioned operator specification, pinned local tool model, scoped edits, bounded Docker checks and review-only evidence |
| `apps/web/` | Legacy standalone Soft Modern local UI served at `/`; hosted React Studio builds to `apps/web/studio/dist`, while the self-hosted React Studio uses the separate `apps/web/studio/dist-local` build at `/studio/`. Extensionless `/studio/*` page routes receive the app shell; dotted assets and reserved API-like paths do not. Missing local builds return `503` without replacing the legacy path |
| `preview/` | Archived standalone static prototype; **not deployed** to Vercel |
| `apps/web/vercel.json` | Hosted build settings (`cd studio` install/build, output `studio/dist`), the SPA fallback rewrite that excludes assets and dotted paths, and the restrictive security headers including the `connect-src` policy |
| `apps/web/cloud-auth.js` | Supabase Auth PKCE adapter and owner-scoped workspace data client; inactive until configured |
| `apps/web/cloud-config.js` | Public-only Supabase project URL and publishable key placeholders |
| `supabase/schema.sql` | Owner-initiated workspaces, membership trigger and per-row authorization policies |
| `supabase/migrations/durable_factory_runtime.sql` | Work items, fenced runs, typed run events, per-project worker registrations and the unexposed lease table |
| `supabase/migrations/retained_attribution_and_lease_clock.sql` | Forward repair for retained actor deletion and lease deadlines/expiry after lock waits; apply after the durable-runtime migration |
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

`engine/oryveta_engine/factory_runtime.py` authenticates as its own Supabase Auth service identity, serves one project and performs bounded public-repository analysis. Apply the workspace schema, private-chat migration, project-membership migration, `durable_factory_runtime.sql` and `retained_attribution_and_lease_clock.sql`, in that order. Existing installations with the first four applied need only the final repair. Then register the worker identity with `register_project_worker` as described in [OPERATIONS.md](OPERATIONS.md).

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

Startup verifies an enabled project-worker registration. Each claim freezes the project source, revalidates its owner/repo with the importer, fetches a bounded archive, and runs the trusted analyzer in a credential-free child process. Heartbeats fence each phase and run at most 30 seconds apart while analyzing. Source download remains one unheartbeated window. Child waits cannot extend to the next heartbeat past the execution deadline, and late-observed results are rejected. Control-plane errors report safe status/category diagnostics rather than raw responses. Teardown sends SIGTERM to the process group, waits up to five seconds for the leader, then kills remaining helpers even if the leader exited first. Source conflicts and authorization loss cannot publish results.

Resume semantics are deliberately narrow. **A crashed analysis is recomputed, not resumed in memory.** The work item's frozen URL, owner/repo and input digest survive project edits. The first accepted source resolution pins `pinned_source_ref` and `pinned_source_commit` on that work item. Claims return that pin plus `previous_source_digest` and `previous_checkpoint`; retries request the exact pinned commit without falling back to HEAD. Checkpoints report `resumed_attempt`, `source_commit`, `source_pinned` and whether the archive digest matches the previous attempt.

The first attempt resolves the default branch. GitHub's ZIP comment supplies the full commit; the short root-directory suffix is checked for agreement, not mistaken for a full hash. Missing or conflicting identity fails closed. Later attempts fetch the exact pin. Imported source is read, never executed. There is still no hosted always-on worker: an operator must start and supervise this process on an authorized host.

Persisted output is bounded on both sides: the schema allows 256 KB and 400 findings; the worker retains at most 200 and exposes truncation explicitly. Normal completion removes the snapshot. A hard-killed worker leaves its directory for the next `--work-root` startup sweep, which removes only marked directories belonging to dead processes. The child receives the original worker PID, refuses an already-orphaned start, monitors parent loss and carries its own deadline. These guards do not simulate recovery from losing the host.

For container/hosted startup without manually staging the first token file, use `python -m oryveta_engine.factory_service`. It uses the same flags and worker, with `/data/worker/credentials.json` as the default credential path and a temporary analysis directory by default. Its first-start secret, persistent volume, single-session lock and bounded supervisor setup are documented in [OPERATIONS.md](OPERATIONS.md#unattended-service-startup). It adds no model inference, repository grants or paid services.

## Local verified repair CLI

This is a separate operator-run command, not a web endpoint, Supabase worker mode or unattended service. It accepts an existing source ZIP, edits only explicitly allowed existing files in a disposable copy, and returns a patch for review. The original archive is never modified. No GitHub, Supabase or paid model credentials are needed.

### Provision and exercise

Use Python 3.11+, a local Ollama service with a tool-capable model, and a local Linux Docker daemon or VM. Start Ollama bound to loopback with cloud use disabled (`OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve`) if it is not already running. Provision weights and a trusted execution image explicitly; the repair command never pulls either. Qwen3 8B needs substantially more memory/disk than the text-only 1.5B gateway model.

```bash
ollama pull qwen3:8b
docker --context default pull python:3.12-slim
MODEL_DIGEST=$(curl --fail --silent http://127.0.0.1:11434/api/tags |
  python -c 'import json,sys; print(next(m["digest"] for m in json.load(sys.stdin)["models"] if m["name"] == "qwen3:8b"))')
IMAGE_ID=$(docker --context default image inspect python:3.12-slim --format '{{.Id}}')
python scripts/smoke_coding.py \
  --model qwen3:8b --model-digest "$MODEL_DIGEST" \
  --image "$IMAGE_ID" --docker-context default \
  --output "$HOME/.oryveta/repair-evidence/first-run"
```

Replace `default` with the actual local Docker context throughout. On macOS, the VM must share the run-root directory (default `$HOME/.oryveta/repair-runs`). It must be operator-owned and mode `0700`; each output directory must be new. The smoke creates a defective numeric-version sorter and operator-owned regression/preservation cases, invokes the actual CLI, and requires independently verified output—not a scripted model or mocked container result.

### Operator contract

For a selected repository, prepare the JSON specification outside its ZIP, using the complete specification in `scripts/smoke_coding.py` as an example:

| Field | Contract |
| --- | --- |
| `schema_version` | Integer `1`; unknown fields and duplicate JSON keys are rejected |
| `model` | Required `name` and SHA-256 `digest`; approved local `endpoint`, `context_tokens` and `output_tokens` are optional. Defaults: loopback Ollama, 16,384 context tokens, 1,024 output tokens |
| `runner` | Required preloaded `sha256:` image ID; optional `docker_context`, per-command `timeout_seconds`, `memory_mb`, `cpus`, `pids`, `tmpfs_mb`, `output_bytes` |
| `read_paths`, `write_paths` | Nonempty exact relative file allowlists; writes must also be readable. No path globs, traversal, symlinks, file creation/deletion/rename or arbitrary shell tool |
| `development_checks`, `acceptance_checks` | Each check has unique `name`, literal `argv`, string `stdin`, `expected_json`, `kind` (`regression` or `preserve`), and optional `expected_exit_code` (default zero). Both suites are required; development must reproduce a defect and at least one preservation case must exist |
| `limits` | Optional `turns`, `tool_calls`, `total_tokens`, `wall_seconds`; defaults: 20, 60, 64,000 and 600. No automatic escalation or paid fallback |

```bash
python -m oryveta_engine.coding_runtime \
  --config /path/outside/source/operator.json \
  --source-zip /path/to/source.zip \
  --goal 'Describe the required change and behavior to preserve' \
  --output "$HOME/.oryveta/repair-evidence/repository-run"
```

The controller reproduces the defect before inference and refuses a failing preservation baseline. Only development inputs/results enter model context; expected values and private acceptance cases stay outside the source and model tools. The model can list/read/search granted files, apply unique SHA-guarded replacements, and request the fixed development suite. Missing-field errors name the required fields without guessing arguments. Two identical failed actions without an intervening edit stop with `no_progress`; the same development check may run again after a real edit.

Each check executes in a fresh container with networking disabled, non-root UID, dropped capabilities, no-new-privileges, read-only root/source, bounded tmpfs/memory/CPU/PIDs/output, no host credentials and no Docker socket. Writable image-declared volumes and image healthchecks are not permitted to bypass this policy. Daemon/context and image metadata are checked; stopped commands/containers are cleaned up, and uncertain cleanup fails the run. This is **local defense in depth**, not a production multi-tenant isolation certification. Use only operator-approved source and trusted images; Docker shares a kernel, host administrators remain trusted, and source code can inspect files included in its own ZIP even when the model's read allowlist is narrower.

The private container scratch mount is `/oryveta-scratch`, supplied as `HOME` and `TMPDIR`; system `/tmp` remains read-only. CPU quotas round **down** to whole milliseconds in a 100 ms period (0.01 CPU steps), preventing kernels from rounding fractional quotas above the operator's ceiling. Programs must honor the configured scratch location.

After the model finishes, the controller executes both suites independently and compares exit status and parsed JSON to its expected values. A successful exit without correct output is insufficient. `needs_review` means only these declared contracts passed, not general correctness, benchmark qualification or permission to publish.

### Evidence and limitations

Private output includes the resolved `configuration.json`, original `source.zip`, checkpointed `receipt.json`, ordered `events.jsonl`, `baseline.json`, final `verification.json` when reached, and `verified.patch` on success. Completed edits are saved as `unverified.patch` before another model/tool action; `candidate_patch_sha256` identifies that checkpoint. Undoing all edits removes it. Keep evidence private: it contains source, prompts, outputs and private expected results. The JSONL trace is ordered, **not hash-chained**; artifact hashes do not authenticate an operator against a malicious host.

The receipt is atomically replaced and synchronized before model/tool admission and independent verification, and after completed model/tool results. `phase`, `checkpointed_at`, attempt counters, observed tokens, model/image/source identities and `unsettled_token_reservation` survive controller termination at these boundaries. `active_tool` identifies an admitted tool whose completion has not been checkpointed. A nonzero reservation remains potentially consumed; do not refund it merely because the client died. A failed checkpoint stops admission rather than running unrecorded work.

While executing, status remains `incomplete` and verification remains `not_accepted`. Normal completion/cancellation writes `phase: finished` and preserves `last_phase`. SIGKILL cannot write a terminal record: the last checkpoint remains incomplete. It is not a liveness indicator. A pending action may already have executed, and its effects may be newer than the saved patch—never automatically replay it. Treat a result as verified only when a terminal `needs_review`/`passed` receipt and the matching `verified.patch` hash are present; a patch filename or trace event alone is insufficient.

SIGTERM/interrupt and ordinary failures clean disposable work; a hard-killed controller cannot guarantee that cleanup. Evidence is not a crash-resume protocol. The CLI has no hosted queue integration, central trajectory store, browser/desktop tools, learned memory, adaptive model switching, GitHub publication or automatic promotion. Disconnecting a timed-out model request does not prove server-side inference has stopped. Run resource/quality evaluations on real target repositories before widening this local capability.

The public site separately includes a sanitized **synthetic** repair example in `repair-example.json` and `repair-example.patch`. These are reviewed build assets, not a directory of private runs. The self-hosted Studio serves exactly `/studio/repair-example.json` and `/studio/repair-example.patch`; other dotted routes still return 404. No endpoint exposes the operator's evidence directory or grants a visitor authority to execute a repair.

## Hardening included in first source PR

- Browser-bound OAuth state in an HttpOnly SameSite cookie plus one-time DB state, preventing a different browser from redeeming a valid OAuth state.
- Owner-scoped project reads and exports, CSRF validation for mutations, localhost-only demo mode, security headers and secure cookie requirements on HTTPS public deployments.
- Bounded GitHub archive streaming, restricted redirect hosts, ZIP traversal/symlink/duplicate-destination rejection, compressed and expanded size limits.
- Atomic benchmark idempotency check-and-insert with conflicting request rejection.
- Exhausted worker leases transition to a terminal failure instead of remaining `running` indefinitely.

## Known production blockers

1. The Vercel UI uses Supabase for collaboration and durable analysis. It is not connected to the separate FastAPI/SQLite engine, and no always-on cloud worker is configured.
2. SQLite and file workspaces are single-host and not adequate as-is for multi-tenant consultancy deployment.
3. Web/API source imports remain read-only snapshots. The separate local repair CLI is not integrated into those imports or the hosted Evolve flow.
4. The worker does not run in a hardened per-tenant container or microVM and has no managed always-on hosting.
5. Production GitHub OAuth, project/private-session schema and controlled multi-user browser authorization are verified. General external email delivery, enterprise identity governance and recovery remain separate requirements.
6. Repository access still requires a separate GitHub App. Production workers also require explicit host/credential provisioning, rate limits, secret handling, audit and backup/restore.
7. Custom application generation, hosted Evolve fixes, automatic PRs, hosted worker execution, Slack/mobile delivery and the self-improving harness remain planned. The selected path extends Python rather than requiring a Rust/Hono rewrite.

## Release discipline

CI passing and code review are necessary, but not sufficient, for production-grade consultancy security. Do not deploy this MVP publicly until threat-model, authorization, operational and integration gates in [AUTH-SECURITY.md](AUTH-SECURITY.md) and [OPERATIONS.md](OPERATIONS.md) are met.
