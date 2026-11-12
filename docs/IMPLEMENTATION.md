# Implementation — code map and verified boundaries

Production collaboration and durable analysis are deployed; an operated cloud coding service is not. This working tree adds a supervised, project-authorized Reviewed Evolve workflow using Pydantic AI, protected repair/reverification, stage reviews, process audit, human approval and scoped lessons. It requires the new SQL migration, private Storage and operator-provisioned inference/runner compute. The standalone FastAPI/SQLite engine retains its separate identity. Dated verification evidence belongs in [STATUS.md](STATUS.md).

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
| `engine/oryveta_engine/coding_{config,contract,model,tools,sandbox,runtime}.py` | Separate operator-run repair CLI: versioned operator specification, pinned local tool model, scoped edits, bounded Docker check execution, review-only evidence, candidate ZIP export and model-free candidate re-verification |
| `engine/oryveta_engine/evolve_{contract,agents,child,runtime,storage,lessons}.py` | Typed read-only roles, supervised durable Evolve execution, protected checks, reviews, exact-candidate approval handoff, private artifacts and scoped learning |
| `apps/web/` | Legacy standalone Soft Modern local UI served at `/`; hosted React Studio builds to `apps/web/studio/dist`, while the self-hosted React Studio uses the separate `apps/web/studio/dist-local` build at `/studio/`. Extensionless `/studio/*` page routes receive the app shell; dotted assets are served only through an explicit per-file allowlist, and reserved API-like paths are not. Missing local builds return `503` without replacing the legacy path |
| `preview/` | Archived standalone static prototype, retained for history; it must never be Vercel's project root and is not published on any environment |
| `apps/web/vercel.json` | Hosted build settings (`cd studio` install/build, output `studio/dist`), the SPA fallback rewrite that excludes assets and dotted paths, and the restrictive security headers including the `connect-src` policy |
| `apps/web/cloud-auth.js` | Supabase Auth PKCE adapter and owner-scoped workspace data client; inactive until configured |
| `apps/web/cloud-config.js` | Public-only Supabase project URL and publishable key placeholders |
| `supabase/schema.sql` | Owner-initiated workspaces, membership trigger and per-row authorization policies |
| `supabase/migrations/durable_factory_runtime.sql` | Work items, fenced runs, typed run events, per-project worker registrations and the unexposed lease table |
| `supabase/migrations/retained_attribution_and_lease_clock.sql` | Forward repair for retained actor deletion and lease deadlines/expiry after lock waits; apply after the durable-runtime migration |
| `supabase/migrations/reviewed_evolve_runtime.sql` | Evolve stages, reviews, diagnostic records, private artifact policy, human decisions and lessons on the existing work/run authority |
| `deploy/oryveta-evolve.service` | Systemd user-service definition for a separately provisioned worker identity, model and rootless Docker runtime |
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

`python -m oryveta_engine.factory_service` supplies one-time secret bootstrap, the persistent rotating-session file, an exclusive session lock and SIGTERM handling. Without `--evolve-config` it runs analysis. With that flag it runs Reviewed Evolve and requires a persistent private `--work-root`. It provisions neither identity nor compute; see [OPERATIONS.md](OPERATIONS.md).

## Reviewed Evolve worker

The React project detail submits a public-source change goal to the canonical work queue. The worker resolves and pins the snapshot, obtains requirements and a plan with independent reviews, executes a bounded repair, reviews the complete diff, independently re-verifies the exported candidate, audits the process and extracts/reviews lessons. PostgreSQL admits each stage and requires an owner/admin decision on the exact candidate archive digest.

The operator supplies the existing JSON specification described below: exact read/write paths, immutable local model and Docker image identities, fixed development/acceptance checks and resource limits. The submitted goal is not a way to choose commands, loosen scope or replace expected values. Approved requirements, plans and applicable lessons reach the executor as bounded task context, not additional authority.

```sh
python -m oryveta_engine.factory_service \
  --evolve-config /path/to/reviewed-operator.json \
  --credentials /path/to/private-worker.json \
  --work-root /path/to/private-persistent-runs
```

Credential provisioning and registration are unchanged from the analysis worker. `--project` can select its registered project. `--once` processes at most one claim; otherwise the service continues until stopped or bounded control failures require operator intervention. `--review-config` optionally pins a separate local reviewer model. All roles share the attempt's token/time budget; role-call and rework ceilings are explicit CLI settings. No model is downloaded or substituted automatically.

Read-only roles use Pydantic AI `NativeOutput` with Ollama's JSON-schema response format; both the schema and framework validation feedback reach the model. The existing native tool interface remains the code editor's only capability. Model digest checks, response bounds and controller-owned expected values are retained. A diff too large to review completely is refused, not clipped into an apparent pass.

The worker's Auth session stays in the supervisor; stage children receive only a minimal interpreter/Docker environment. Repository checks run in fresh network-disabled containers, not on the host. Private resolved configurations and raw model/check traces stay on the worker. Registered candidate/patch bytes and sanitized receipt/trace manifests go to private Storage under current project authorization.

Execution ends at `awaiting_approval`, releasing the lease while the human is absent. Approval changes the work to `succeeded` and activates only reviewed lessons for that exact source/configuration scope; it does not commit, merge or deploy. Retries restart pinned inputs as new attempts rather than replaying uncertain tool effects. Failure diagnostics retain check outcomes and bounded reviewed lessons where possible; missing authority, model or budget is explicit unavailability.

Reproducible real-service verification is `scripts/evolve_runtime_smoke.py --help`. It requires isolated local Supabase, a provisioned local tool-capable model and image, and a new private output directory. `--ui-origin` drives an already-built local Studio; `--crash-restart` additionally exercises worker interruption and live cancellation/revocation. It changes only disposable copies of a public repository, never the upstream repository.

## Local verified repair CLI

The standalone CLI remains an operator-run command with no HTTP endpoint. The reviewed worker above reuses these library functions under its own durable authorization contract. The CLI has two modes:

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

1. The Vercel UI uses Supabase for collaboration and durable analysis. It is not connected to the separate FastAPI/SQLite engine, and no always-on cloud worker is configured.
2. SQLite and file workspaces are single-host and not adequate as-is for multi-tenant consultancy deployment.
3. Legacy ZIP imports remain read-only. Reviewed Evolve is a separate public-GitHub-snapshot workflow in source, requiring migration and provisioned worker/model/runner resources before rollout. Private GitHub App access is not implemented.
4. The worker does not run in a hardened per-tenant container or microVM and has no managed always-on hosting.
5. Production GitHub OAuth, project/private-session schema and controlled multi-user browser authorization are verified. General external email delivery, enterprise identity governance and recovery remain separate requirements.
6. Repository access still requires a separate GitHub App. Production workers also require explicit host/credential provisioning, rate limits, secret handling, audit and backup/restore. The production security advisor still reports the intentional authenticated-only `SECURITY DEFINER` RPC pattern and disabled leaked-password protection (Supabase Pro or above, so unavailable under the no-paid-service requirement); those findings are accepted and documented, and the advisor output is not claimed to be clean.
7. Custom application generation, automatic PRs, an operated hosted coding service, Slack/mobile delivery and self-modifying harness promotion remain planned. Reviewed Evolve and its scoped diagnostic memory are not those capabilities. The existing 12 MiB compressed / 32 MiB expanded / 1,800-entry archive limits remain enforced.

## Release discipline

CI passing and code review are necessary, but not sufficient, for production-grade consultancy security. Do not deploy this execution pathway publicly until the threat-model, authorization, operational and integration gates in [AUTH-SECURITY.md](AUTH-SECURITY.md) and [OPERATIONS.md](OPERATIONS.md) are met.
