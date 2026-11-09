# Functional MVP implementation — code map and verified boundaries

Status: **The React/Supabase collaboration and durable-analysis control plane are deployed.** Production analysis was verified with a one-off local worker; always-on worker hosting remains pending. The separate FastAPI/SQLite engine is not deployed to Vercel and keeps its own local identity. The operator-run local repair CLI additionally performs model-driven edits with controller-owned verification, and model-free re-verification of a supplied candidate — from an operator's shell only, never from an endpoint. A **controlled durable repair** runtime extends the same control plane with a second task kind and a policy-scoped worker, so an authorized project member can queue a bounded goal that an operator's own supervised host serves; that is durable admission, not hosted execution, and no cloud worker is provisioned for it. This page distinguishes deterministic starters and read-only analysis from autonomous software engineering. Dated evidence lives in [STATUS.md](STATUS.md); this page is the code map and the operator contract.

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
| `engine/oryveta_engine/coding_{config,contract,model,tools,sandbox,runtime}.py` | Shared repair engine used by both repair paths: versioned operator specification, pinned local tool model, scoped edits, bounded Docker check execution, review-only evidence, candidate ZIP export and model-free candidate re-verification |
| `engine/oryveta_engine/coding_worker.py` | Policy-scoped durable repair worker: frozen operator configuration, local capacity probe, pinned-commit fetch, supervised credential-free child, fenced heartbeats and one bounded patch result |
| `engine/oryveta_engine/coding_child.py` | Child-process entry point that runs `coding_runtime.repair` over prepared private inputs with its own deadline and parent-loss watcher, and writes a bounded outcome report |
| `apps/web/` | Legacy standalone Soft Modern local UI served at `/`; hosted React Studio builds to `apps/web/studio/dist`, while the self-hosted React Studio uses the separate `apps/web/studio/dist-local` build at `/studio/`. Extensionless `/studio/*` page routes receive the app shell; dotted assets are served only through an explicit per-file allowlist, and reserved API-like paths are not. Missing local builds return `503` without replacing the legacy path |
| `preview/` | Archived standalone static prototype, retained for history; it must never be Vercel's project root and is not published on any environment |
| `apps/web/vercel.json` | Hosted build settings (`cd studio` install/build, output `studio/dist`), the SPA fallback rewrite that excludes assets and dotted paths, and the restrictive security headers including the `connect-src` policy |
| `apps/web/cloud-auth.js` | Supabase Auth PKCE adapter and owner-scoped workspace data client; inactive until configured |
| `apps/web/cloud-config.js` | Public-only Supabase project URL and publishable key placeholders |
| `supabase/schema.sql` | Owner-initiated workspaces, membership trigger and per-row authorization policies |
| `supabase/migrations/durable_factory_runtime.sql` | Work items, fenced runs, typed run events, per-project worker registrations and the unexposed lease table |
| `supabase/migrations/retained_attribution_and_lease_clock.sql` | Forward repair for retained actor deletion and lease deadlines/expiry after lock waits; apply after the durable-runtime migration |
| `supabase/migrations/controlled_repair_runtime.sql` | Repair policies, the `repository_repair` task kind on the same queue, bounded checkpoint/result validation, the per-kind run contract and the repair RPCs; apply last, and it is repeatable |
| `tests/` | API, ownership, CSRF, OAuth state, archive safety, worker and scaffold tests |
| `Dockerfile`, `compose.yaml` | Single-host API and worker containers with local-only port binding |

The hosted collaboration slice uses `apps/web/studio/src/lib/identity.js`, `projects.js`, `pages/Projects.jsx` and the existing private-chat client. `supabase/migrations/projects_and_project_membership.sql` adds project RLS/RPCs without merging local engine identities. The controlled repair panel is `apps/web/studio/src/components/ProjectRepairs.jsx` over `src/lib/repairRuns.js`, kept separate from the read-only repository-analysis panel, which now filters its work list to `kind = 'repository_analysis'` so repair work is never mislabelled. `scripts/auth_ui_smoke.py` exercises actual local Supabase Auth/PostgREST/PostgreSQL/Mailpit and a production-built Studio with headless Chromium; setup and deployment prerequisites are in [IDENTITY-WORKSPACES.md](IDENTITY-WORKSPACES.md).

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

## Controlled durable repair worker (operator-provisioned)

`engine/oryveta_engine/coding_worker.py` is the repair counterpart of the analysis worker. It claims `repository_repair` work items for exactly one approved repair policy and performs one real task per attempt: fetch the policy's pinned public GitHub commit, run the existing `coding_runtime.repair` loop in a supervised credential-free child, and publish one bounded patch result validated against the private evidence the child actually wrote. Operational procedure, trust boundaries and limits are in [OPERATIONS.md](OPERATIONS.md#controlled-durable-repair-operations); the RPCs and payload bounds are in [API.md](API.md#hosted-controlled-repair).

Apply the five analysis prerequisites and then `supabase/migrations/controlled_repair_runtime.sql`. The analysis service is untouched by this module existing: an analysis worker gains no code-execution authority, and nothing about `factory_runtime` or `factory_service` changes.

The credential file is the same JSON object in the same protected regular file as the analysis worker, with the same rules — bare-origin `supabase_url`, `publishable_key` (or `anon_key`), optional `project_id`, `refresh_token`, `chmod 600`, no symlink, no service-role key ever. Only the environment variable differs: `ORYVETA_REPAIR_CREDENTIALS`. Use a dedicated Auth identity and a dedicated credential **directory**, because the process holds that directory's session lock for its whole life.

```bash
export ORYVETA_REPAIR_CREDENTIALS=/etc/oryveta/repair-worker-credentials.json
python -m oryveta_engine.coding_worker \
  --policy <repair policy uuid> \
  --config /etc/oryveta/repair-configuration.json \
  --source-url https://github.com/owner/repo \
  --source-commit <40 lowercase hex> \
  --evidence-root /var/lib/oryveta/repair-evidence \
  --work-root /var/lib/oryveta/repair-work
```

| Flag | Required | Meaning |
| --- | --- | --- |
| `--credentials` | yes | Protected dedicated worker credential file; defaults to `$ORYVETA_REPAIR_CREDENTIALS` and is required if neither is set |
| `--project` | no | Project UUID to serve; defaults to the credential file's `project_id`, and is required when the file has none |
| `--policy` | yes | The approved `project_repair_policies` id this worker serves |
| `--config` | yes | Operator-owned JSON repair specification, read once and frozen at startup |
| `--source-url` | yes | The approved `https://github.com/owner/repo` source URL |
| `--source-commit` | yes | The approved 40-character lowercase commit SHA |
| `--evidence-root` | yes | Private directory that retains full per-run evidence; created or adopted as `0700` and owned by this account |
| `--work-root` | no | Private parent for disposable per-run trees, swept at startup for the trees of dead attempts. It must be visible to the local Docker daemon. Omitted, a temporary root is created and removed with the process, so no later sweep is possible |
| `--docker-cli` | no | Trusted Docker executable; resolved from `PATH` when omitted |
| `--docker-config` | no | Operator Docker configuration directory; only the approved named context's local socket metadata is exposed to the child. Defaults to `$DOCKER_CONFIG` |
| `--lease-seconds` | no | Lease length, 15–900 seconds, default 300 |
| `--poll-seconds` | no | Idle delay between claim attempts in continuous mode, default 5 |
| `--once` | no | Claim and complete at most one work item, then exit |
| `--max-runs` | no | Stop after this many completed claims in continuous mode |

There is deliberately **no** `--max-run-seconds`. The child's bound is the frozen configuration's `limits.wall_seconds` plus a fixed 180-second allowance for fetching, snapshotting, candidate export and result validation, and the child carries its own bound 60 seconds beyond the worker's so a hard-killed worker still leaves a child that stops by itself. There is also no flag that selects a model, an image, a command, a budget or a file grant: those exist only in the frozen configuration.

`configuration_sha256` is the SHA-256 of the **canonical resolved specification**, not of the file's bytes, so derive it with `load_spec(path).digest` rather than `sha256sum` — see [OPERATIONS.md](OPERATIONS.md#operator-reviewed-configuration-and-its-digest). The worker reads the configuration once, parses those exact bytes, prints the digest it froze, and copies those same bytes into every private run directory, so a mid-attempt edit cannot become the authority for a run already under way.

Startup verifies, in order, the enabled project-worker registration and the policy — which must be enabled, must designate this identity, and whose `source_url`, `source_commit` and `configuration_sha256` must equal what the process was started with, with the frozen owner/repo re-parsed by the real importer parser and required to agree — then sweeps stale run directories, then observes local capacity. The capacity probe inspects the Docker context, the daemon and the immutable image and confirms the pinned model is installed; it starts no container, pulls nothing and spends no inference tokens. Capacity and authority are both re-observed at least every 120 seconds before a claim. Nothing falls back: one local model, one local runner, one frozen configuration.

The policy's identity check compares the worker's own Auth id against the policy's **live** `worker_user_id`. That column is nullable and is cleared when the bound account is deleted, so a withdrawn enrollment fails this comparison and the worker stops rather than polling a control plane that would refuse it; the frozen `worker_identity` column is evidence of what was approved and is never used to authorize anything.

Every claim is re-checked before it is served. A claimed item whose `kind`, `project_id`, `repair_policy_id`, `configuration_sha256`, `source_url` or `pinned_source_commit` is not this policy's is a mismatch and is refused, as is an item carrying no bounded goal. The approved commit is then the only thing fetched — there is no default-branch fallback — and the archive's own commit, the fetched slug and any already-pinned reference must all agree.

The child is credential-free. Its argument vector names the configuration copy, source archive, goal file, private evidence/run directories, result path, deadline, worker PID and resolved Docker executable. Its minimal environment adds only that executable directory to `PATH`, a disposable `HOME` and sanitized `DOCKER_CONFIG`: no Supabase credentials, lease token, project/policy identity, `DOCKER_HOST`, proxy variables or inherited parent environment. The worker reads only the selected context's canonical symlink-free `meta.json` (at most 1 MiB), validates its name and local Unix-socket endpoint, and writes those two fields into a fresh private configuration. It copies no arbitrary metadata, other contexts, TLS keys or registry credentials. The parent keeps heartbeating through local inference and independent checks, reporting bounded numeric progress from the private receipt.

Phases reported to the control plane are `claimed`, `fetching_source`, `repairing`, `verifying`, `recording_result` and `done`; the derived checkpoint steps are `fetching_source`, `snapshot_ready`, `repairing`, `verifying` and `recording_result`. Both sets are closed, and the model-loop detail stays in the private receipt. Local failure codes are narrowed to a closed forwarded set before they are persisted, and anything outside it becomes `repair_failed`, so a new upstream code can never widen what a project member is shown.

Private evidence per attempt lives at `<evidence-root>/<work_item_id>/run-<run_id>-attempt-<n>-<random>` and the worker refuses a directory that already exists. It holds the resolved `configuration.json`, the fetched `source.zip`, `receipt.json`, `events.jsonl`, `baseline.json`, `verification.json`, `candidate.zip`, `unverified.patch`/`verified.patch` and an operator-only `worker-run.json` naming the work item, run and attempt. The disposable work tree — snapshot, config copy, goal file, `child-result.json` and `child-stderr.log` — is removed when the attempt ends. Retention of the evidence root is the operator's deliberate decision; nothing in it expires, and no endpoint serves it.

Only a `needs_review` outcome that both the private receipt and the `verified.patch` file support is published, with the patch hash recomputed in the worker and again in the database. The published document carries exactly `kind`, `status`, `verification`, `configuration_sha256`, `source_commit`, `source_tree_sha256`, `candidate_tree_sha256`, `patch_sha256`, `patch`, `checks_passed`, `turns`, `tool_calls`, `tokens_observed`, `model_name` and `model_digest`. An over-limit patch is refused — never truncated, and never replaced by a metadata-only "completion". No stdout, no private acceptance values, no host paths, no prompts and no model trajectory reach the control plane.

Resume semantics match the analysis worker's and are deliberately narrow: **a crashed repair is recomputed, not resumed.** Each retry re-fetches the same pinned commit and recomputes from scratch; a model trajectory is never replayed and a browser grant is never reused. Cancellation, policy or worker or creator revocation, a stolen or expired lease, SIGTERM and the loss of the worker process all stop the child's whole process group and prevent publication, even with a verified candidate in hand. `scripts/coding_worker_smoke.py` is the parent-owned integration harness for this path; its retained private runs stay under the operator evidence root, and a scripted model fixture, when used, is labelled as such and is not a model-quality result.

## Local verified repair CLI

This is a separate operator-run command: not a web endpoint, not a Supabase worker mode and not an unattended service. It is also distinct from the controlled durable repair worker above, which supervises this module's repair loop but adds a queue, a lease, a policy and a bounded published result; this command remains supported on its own, and it is the only way to run re-verification. It has two modes in one module:

- **Repair** (default): accepts a source ZIP, lets a pinned local model edit only explicitly allowed existing files in a disposable copy, independently executes the operator's checks, and returns a patch plus a candidate archive for review.
- **Re-verification** (`--candidate-zip`): accepts the same source ZIP plus a candidate ZIP and re-derives the verdict with **no model contact at all**.

In both modes the original source archive is never modified, nothing is committed, pushed, deployed or applied to a working tree, and no GitHub, Supabase or paid model credential is needed.

### Provision and exercise

Repair mode needs Python 3.11+, a local Ollama service with a tool-capable model, and a local Linux Docker daemon or VM. Start Ollama bound to loopback with cloud use disabled (`OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve`) if it is not already running. Provision weights and a trusted execution image explicitly; the repair command never pulls either. Qwen3 8B needs substantially more memory/disk than the text-only 1.5B gateway model. **Re-verification needs no model and no Ollama at all** — only Python, Docker and the two archives.

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

Replace `default` with the actual local Docker context throughout. On macOS, the VM must share the run-root directory (default `$HOME/.oryveta/repair-runs`). It must be operator-owned and mode `0700`; each output directory must be new. The smoke creates a defective numeric-version sorter and operator-owned regression/preservation cases, invokes the actual CLI, and requires independently verified output — not a scripted model or mocked container result. It also asserts that the exported `candidate.zip` matches the receipt's `candidate_archive_sha256`.

`scripts/smoke_reverify.py` exercises the model-free path against real Docker with **no model required**. It defaults to a deliberately nonexistent model name and an all-zero digest, so a run that reached the model would fail loudly rather than pass silently; it builds a defective source plus a correct candidate, asserts the mode and the zeroed counters, and then asserts that a candidate editing a read-only file is refused with `candidate_scope` before any execution. Both smokes share one fixture and operator contract through the `specification(model, digest, image, context)` helper in `scripts/smoke_coding.py`, so the two modes are exercised against the same declared checks.

```bash
IMAGE_ID=$(docker --context default image inspect python:3.12-slim --format '{{.Id}}')
python scripts/smoke_reverify.py \
  --image "$IMAGE_ID" --docker-context default \
  --output "$HOME/.oryveta/repair-evidence/reverify-run"
```

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

One specification governs both modes within a single run: re-verification uses the allowlists, runner, checks and limits of the config it is given, and there is no per-mode subset or separate "verification config". Every check in the supplied reviewed config runs. Across runs the operator can of course supply a *different* reviewed config, so narrowing happens by supplying a narrower config rather than by choosing a mode — which is exactly why comparing two records is only meaningful when their `configuration_sha256` and `checks_sha256` match. A re-verification against a different config answers a different question; it is not a re-check of the earlier one.

| Flag | Required | Meaning |
| --- | --- | --- |
| `--config` | yes | Operator-owned JSON specification, read from a path outside the source archive |
| `--source-zip` | yes | Original source archive; normalized and checked afresh, never modified |
| `--goal` | yes | The repair requirement, or in verification mode the review requirement. The receipt stores only `goal_sha256`, but the raw text can appear in the private trace, so treat the goal itself as private evidence. In verification mode it never reaches a model, because no model is constructed |
| `--output` | yes | A **new** private evidence directory; an existing path is refused |
| `--run-root` | no | Private directory shared with the local Docker VM; default `~/.oryveta/repair-runs`, operator-owned and mode `0700` |
| `--candidate-zip` | no | Selects model-free re-verification. Absent, the existing repair loop is unchanged |

Repair mode:

```bash
python -m oryveta_engine.coding_runtime \
  --config /path/outside/source/operator.json \
  --source-zip /path/to/source.zip \
  --goal 'Describe the required change and behavior to preserve' \
  --output "$HOME/.oryveta/repair-evidence/repository-run"
```

Model-free re-verification of a candidate:

```bash
python -m oryveta_engine.coding_runtime \
  --config /path/outside/source/operator.json \
  --source-zip /path/to/source.zip \
  --candidate-zip "$HOME/.oryveta/repair-evidence/repository-run/candidate.zip" \
  --goal 'State the requirement this candidate is being reviewed against' \
  --output "$HOME/.oryveta/repair-evidence/repository-run-recheck"
```

Exit codes are the same in both modes: `0` only when the terminal status is `needs_review`, `1` for any other terminal receipt, `2` for a pre-run refusal such as `invalid_goal`, `output_exists` or `invalid_run_root` — reported on stderr rather than as a receipt — and `130` on keyboard interrupt. Those three refusals are raised before the evidence directory is created, but do not treat exit `2` as a guarantee that nothing was written: a later I/O failure can also exit non-zero after partial files exist, so always inspect the output path rather than assuming it is absent. The stdout JSON reports `mode` alongside `status`, `error_code`, `receipt` and `verification`.

The controller reproduces the defect before inference and refuses a failing preservation baseline. Only development inputs/results enter model context; expected values and private acceptance cases stay outside the source and model tools. The model can list/read/search granted files, apply unique SHA-guarded replacements, and request the fixed development suite. Missing-field errors name the required fields without guessing arguments. Two identical failed actions without an intervening edit stop with `no_progress`; the same development check may run again after a real edit.

Each check executes in a fresh container with networking disabled, non-root UID, dropped capabilities, no-new-privileges, read-only root/source, bounded tmpfs/memory/CPU/PIDs/output, no host credentials and no Docker socket. Writable image-declared volumes and image healthchecks are not permitted to bypass this policy. Daemon/context and image metadata are checked; stopped commands/containers are cleaned up, and uncertain cleanup fails the run. This is **local defense in depth**, not a production multi-tenant isolation certification. Use only operator-approved source and trusted images; Docker shares a kernel, host administrators remain trusted, and source code can inspect files included in its own ZIP even when the model's read allowlist is narrower.

The private container scratch mount is `/oryveta-scratch`, supplied as `HOME` and `TMPDIR`; system `/tmp` remains read-only. CPU quotas round **down** to whole milliseconds in a 100 ms period (0.01 CPU steps), preventing kernels from rounding fractional quotas above the operator's ceiling. Programs must honor the configured scratch location.

After the model finishes, the controller executes both suites independently and compares exit status and parsed JSON to its expected values. A successful exit without correct output is insufficient. `needs_review` means only these declared contracts passed, not general correctness, benchmark qualification or permission to publish.

### Candidate export and model-free re-verification

A changed candidate is exported as private `candidate.zip` with `candidate_archive_sha256` beside the saved patch's digest. Successful edit checkpoints retain both artifacts, including for interrupted or failed runs. A completed full-revert checkpoint removes both artifacts and hashes. A crash during a write can leave a partial set, so compare artifact digests with the last receipt before using them; file presence alone does not prove completion. The input source archive is never modified.

The export uses a stable `candidate/` wrapper so a meaningful single top-level project folder survives re-import. `create_archive` callers that omit its optional `wrapper` retain the existing bare-tree format. Use the exported bytes unchanged: renaming the ZIP file does not alter its identity, but repacking changes the archive digest and may change normalization. Do not strip the wrapper.

Round-trip limits are the importer's, not a separate budget: a candidate archive must be at most **12 MiB compressed**, expand to at most **32 MiB** across at most **1,800 files**, with no entry over 3 MiB. A tree that cannot be exported within those bounds fails with `candidate_limit`; a supplied archive that violates them is refused as `invalid_candidate`. Repositories near those limits cannot use this path.

Given `--candidate-zip`, the controller performs a **fresh run** — new run ID, new private output directory, `mode: "verification"` — and proceeds in this order:

1. **Inventory.** Normalize both archives into snapshots and compare them. The candidate must contain *exactly* the files of the source snapshot: any addition or removal is `candidate_inventory` (the detail carries added/removed path samples). Every file that differs must be inside the operator's `write_paths`; anything else is `candidate_scope`. An identical candidate is `no_change`. The sorted differing files are recorded as `changed_paths`.
2. **Baseline.** Reproduce the baseline from the untouched source in fresh containers: the development checks must still reproduce the defect (otherwise `not_reproduced`, with the failing names recorded as `reproduced_failures`) and every `preserve` case must still pass on the unmodified source (otherwise `invalid_baseline`). A re-verification never inherits a baseline from an earlier run.
3. **Final checks.** Execute **all** declared cases — development *and* acceptance — against the candidate in real fresh containers under the same policy as repair, comparing exit status and parsed JSON against the controller's expected values. Any failure is `verification_failed`.

No model is constructed or contacted in verification mode, so Ollama need not be installed or running; source, configuration, Docker and storage requirements still apply. Model/turn/tool/token counters remain zero and no observed-model identity or model summary is claimed. Supplied "passed" reports have no authority. Candidate programs execute only in isolated containers; the controller, archive handling and scope comparison run on the host. No patch is applied with a host shell or `git apply`.

Receipts identify the mode, configuration/check-suite digests, goal and implementation, original source, candidate archive/tree and—on success—the patch. Fields appear as their phases complete. Runner observations and successful check counts are shared by both modes; verification also records changed paths and reproduced failures. A configured model identity is not an observed model in verification mode.

`candidate_archive_sha256` identifies exact ZIP bytes; verification retains the input byte-for-byte. `candidate_tree_sha256` identifies normalized file contents and paths. Matching tree hashes identify the same content, not proof of execution or an authenticated producer. Relate fresh check results using source, candidate, configuration and check-suite identities together.

Both modes retain private receipts, configuration and ordered events, with source/candidate archives and baseline/final results when those phases are reached. Repair exports the changed candidate; verification keeps the supplied bytes. The diff is initially `unverified.patch`; passing checks and successful finalization produce `verified.patch`. Early failures may have no patch and interrupted runs may have only partial artifacts. Original source is not modified; repair changes its disposable copy and verification applies no edits.

Terminal execution statuses are `needs_review`, `rejected`, `failed` and `cancelled`: `needs_review` only when every check passed **and** all evidence and cleanup were committed; `rejected` for the refusals above (`invalid_candidate`, `candidate_inventory`, `candidate_scope`, `no_change`, `invalid_source`, `invalid_baseline`, `not_reproduced`, `verification_failed`); `failed` for controller/infrastructure problems (`candidate_limit`, `wall_budget`, `workspace_cleanup_failed`, `evidence_write_failed`, `trace_limit`, `runner_*`, `internal_error`); `cancelled` on SIGTERM. **`incomplete` is not a terminal result** — it is the status while the run is initializing or in flight, and it is what a last checkpoint still says if the process was killed before it could finalize. Never read `incomplete` as an outcome, and never read it as a liveness signal either. A `verified.patch` never survives a non-`needs_review` receipt. Deadlines and cancellation behave exactly as in repair: the specification's `limits.wall_seconds` bounds the run and overrun is `wall_budget`, SIGTERM yields `cancelled`, SIGKILL leaves the last checkpoint `incomplete`, and the output directory is still never overwritten.

**What this is not.** Re-verification is not resume, not replay, not automatic approval, not remote attestation and not a hosted integration. It restores no checkpoint, continues no conversation and re-issues no recorded tool result. The authority for a re-run is the operator's **reviewed current configuration** and an **authorized source archive**, supplied again at invocation: a receipt is a record and cannot recover an authorization grant, re-authorize a source, vouch for the host or substitute for the configuration. Hashes bind bytes; they do not authenticate the producer, prove that work happened or defend against a malicious host or tampered image. A `needs_review` verdict still means only that the operator's declared contracts held for that candidate.

**Older patch-only records.** Runs that recorded only a `verified.patch` or `unverified.patch`, with no candidate archive, cannot be re-verified from that evidence: a unified diff is not a snapshot, and the controller never applies one. Re-checking such a run requires the original source archive plus an equivalently produced candidate archive. Without both, leave the historical record as it is rather than implying it was re-confirmed.

### Evidence and limitations

Private output includes the resolved `configuration.json`, the original `source.zip`, the checkpointed `receipt.json`, the ordered `events.jsonl`, `baseline.json`, the final `verification.json` when reached, `candidate.zip`, and the reviewable diff as `unverified.patch` until it is verified and `verified.patch` on success. In repair mode a completed edit is saved as `unverified.patch` plus an exported `candidate.zip` before another model/tool action, identified by `candidate_patch_sha256` and `candidate_archive_sha256`; undoing all edits removes both files and both hashes. In verification mode `candidate.zip` holds the submitted bytes unmodified and the diff is recorded once inventory and scope pass, so a rejected re-verification still leaves both as evidence. Keep evidence private: it contains real source, prompts, model output and the operator's private expected results. The JSONL trace is ordered, **not hash-chained**; artifact hashes do not authenticate an operator against a malicious host.

The receipt is atomically replaced and synchronized before model/tool admission and independent verification, and after completed model/tool results. `phase`, `checkpointed_at`, attempt counters, observed tokens, model/image/source identities and `unsettled_token_reservation` survive controller termination at these boundaries. `active_tool` identifies an admitted tool whose completion has not been checkpointed. A nonzero reservation remains potentially consumed; do not refund it merely because the client died. A failed checkpoint stops admission rather than running unrecorded work.

While executing, status remains `incomplete` and verification remains `not_accepted`. **`incomplete` is never a result**: it means initializing or in flight, or — after a SIGKILL, which cannot write a terminal record — that the last checkpoint was never finalized. It is not an outcome and not a liveness indicator. Normal completion/cancellation writes `phase: finished` and preserves `last_phase`. A pending action may already have executed, and its effects may be newer than the saved patch — never automatically replay it. Treat a result as verified only when a terminal `needs_review`/`passed` receipt and the matching `verified.patch` hash are present; a patch filename, an `unverified.patch` or a trace event alone is insufficient. Re-verifying the interrupted run's exported `candidate.zip` is the supported way to settle what that candidate actually does, and it is a new run with its own identity — not a continuation of the interrupted one.

SIGTERM/interrupt and ordinary failures clean disposable work; a hard-killed controller cannot guarantee that cleanup. Evidence is not a crash-resume protocol, and candidate re-verification does not make it one. The CLI has no hosted queue integration, central trajectory store, browser/desktop tools, learned memory, adaptive model switching, GitHub publication or automatic promotion. Disconnecting a timed-out model request does not prove server-side inference has stopped. Resource and quality evaluation on real target repositories — under the consent and reporting rules in [EVALUATION.md](EVALUATION.md#path-to-real-evidence-consented-repositories-not-borrowed-benchmarks) — must precede any claim beyond the single historical synthetic repair recorded in [STATUS.md](STATUS.md).

The public site separately includes a sanitized **synthetic** repair example in `repair-example.json` and `repair-example.patch`. These are reviewed static build assets extracted from one historical local run, not a directory of private runs and not a candidate archive. The self-hosted Studio serves dotted distribution files only through an explicit per-file allowlist — `/studio/demo-stories.json`, `/studio/template-license.txt`, `/studio/geist-license.txt`, `/studio/repair-example.json`, `/studio/repair-example.patch` and `/studio/assets/*` — and every other dotted route still returns 404; a built file without its own route is served as 404. The hosted build serves the same `public/` files at the origin root. No endpoint exposes the operator's evidence directory, serves a `candidate.zip`, or grants a visitor authority to start or re-verify a repair.

## Hardening included in first source PR

- Browser-bound OAuth state in an HttpOnly SameSite cookie plus one-time DB state, preventing a different browser from redeeming a valid OAuth state.
- Owner-scoped project reads and exports, CSRF validation for mutations, localhost-only demo mode, security headers and secure cookie requirements on HTTPS public deployments.
- Bounded GitHub archive streaming, restricted redirect hosts, ZIP traversal/symlink/duplicate-destination rejection, compressed and expanded size limits.
- Atomic benchmark idempotency check-and-insert with conflicting request rejection.
- Exhausted worker leases transition to a terminal failure instead of remaining `running` indefinitely.

## Known production blockers

1. The Vercel UI uses Supabase for collaboration, durable analysis and controlled durable repair. It is not connected to the separate FastAPI/SQLite engine, and no always-on cloud worker is configured for either task kind.
2. SQLite and file workspaces are single-host and not adequate as-is for multi-tenant consultancy deployment.
3. Web/API source imports remain read-only snapshots, and the one-shot repair CLI — including its candidate export and model-free re-verification — is still not integrated into those imports, the hosted Evolve flow, any endpoint or any worker. The controlled durable repair path is the one connection that now exists, and only on its own narrow terms: a project-scoped submission against an operator-enrolled policy, served by an operator-provisioned host. It supplies the durable work contract and the authorization model that were missing; it does **not** supply per-tenant isolation, hosted compute, private-repository access or model-free re-verification, so the general hosted Evolve fix remains unavailable.
4. The worker does not run in a hardened per-tenant container or microVM and has no managed always-on hosting.
5. Production GitHub OAuth, project/private-session schema and controlled multi-user browser authorization are verified. General external email delivery, enterprise identity governance and recovery remain separate requirements.
6. Repository access still requires a separate GitHub App. Production workers also require explicit host/credential provisioning, rate limits, secret handling, audit and backup/restore. The production security advisor still reports the intentional authenticated-only `SECURITY DEFINER` RPC pattern and disabled leaked-password protection (Supabase Pro or above, so unavailable under the no-paid-service requirement); those findings are accepted and documented, and the advisor output is not claimed to be clean.
7. Custom application generation, hosted Evolve fixes, automatic PRs, hosted worker execution, Slack/mobile delivery and the self-improving harness remain planned. The selected path extends Python rather than requiring a Rust/Hono rewrite. Candidate archives over the importer's 12 MiB compressed / 32 MiB expanded / 1,800-file bounds cannot use the re-verification path at all.

## Release discipline

CI passing and code review are necessary, but not sufficient, for production-grade consultancy security. Do not deploy this MVP publicly until threat-model, authorization, operational and integration gates in [AUTH-SECURITY.md](AUTH-SECURITY.md) and [OPERATIONS.md](OPERATIONS.md) are met.
