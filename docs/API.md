# API and integration contracts

## Current public website

The hosted frontend uses Supabase for identity, persisted project briefs, membership and private conversations once the required schema is applied. Start New/Evolve execution remains unavailable online: a saved brief is not a generated application or a completed analysis.

## Hosted project collaboration

These calls target the configured Supabase project's `/rest/v1` API with the user's authenticated token, not the separate local FastAPI API. PostgreSQL RLS authorizes reads; project mutations use the following RPCs. Apply the schema prerequisites in [IDENTITY-WORKSPACES.md](IDENTITY-WORKSPACES.md) before deploying the client.

| RPC | Parameters | Authorization / result |
| --- | --- | --- |
| `create_project` | `p_workspace_id`, `p_name`, `p_brief`, `p_kind`, optional `p_source_url` | Workspace owner/admin/engineer; atomically returns project and provisions creator ownership |
| `update_project` | `p_project_id`, `p_name`, `p_brief`, optional `p_source_url` | Project owner/admin/engineer; cannot reassign workspace/owner/kind |
| `invite_project_member` | `p_project_id`, `p_recipient`, `p_role` | Owner/admin; verified-email target or immutable alias identity, non-owner role; returns invitation ID/status |
| `list_project_invitations` | None | Only the intended recipient's pending invitations; minimal project-name disclosure |
| `accept_project_invitation` | `p_invitation_id` | Intended verified recipient; atomic acceptance/membership; accepted replay never recreates a revoked grant |
| `revoke_project_member` | `p_project_id`, `p_user_id` | Owner/admin; owner is protected |
| `cancel_project_invitation` | `p_invitation_id` | Owner/admin; cancels pending access without granting membership |

Authenticated SELECT on `projects`, `project_memberships`, `project_invitations` and `project_audit_events` is RLS-filtered; direct browser mutation grants are absent. Project name is 2–80 characters, brief at most 2,000, source URL at most 500 with HTTP(S) scheme, and kind is `new` or `evolve`. Invalid/forbidden RPC calls fail rather than returning fabricated success.

Existing private-chat endpoints keep their separate viewer/editor sharing contract. `chats.project_id` is an optional creation-time association, not a permission grant. Null workspace is permitted for a project-only guest; a non-null workspace must be readable and match the project. Chat owner/workspace/project columns cannot be reassigned by the client.

## Hosted durable work and events

Durable repository analysis uses the same configured Supabase project's `/rest/v1` API with the caller's authenticated token. Apply `supabase/schema.sql`, `supabase/migrations/private_chats_and_explicit_sharing.sql`, `supabase/migrations/projects_and_project_membership.sql`, `supabase/migrations/durable_factory_runtime.sql` and `supabase/migrations/retained_attribution_and_lease_clock.sql`, in that order. An installation already at the fourth file needs only the fifth repair. Reads are RLS-filtered SELECT; every state change goes through a narrow RPC. The only task kind is `repository_analysis`, operating on the project's frozen public GitHub source; arbitrary commands, host paths and private-repository grants are not expressible.

| RPC | Parameters | Authorization | Returned columns |
| --- | --- | --- | --- |
| `submit_repository_analysis` | `p_project_id`, optional `p_idempotency_key` | Current project role engineer or above | `work_item_id`, `status`, `replayed`, `kind`, `source_url`, `input_digest`, `attempts`, `max_attempts` |
| `cancel_work_item` | `p_work_item_id` | Current project role engineer or above | `work_item_id`, `status`, `already_terminal`, `fenced_runs` |
| `register_project_worker` | `p_project_id`, `p_worker_user_id`, `p_label` | Project owner/admin | `id`, `project_id`, `worker_user_id`, `label`, `enabled` |
| `revoke_project_worker` | `p_project_id`, `p_worker_user_id` | Project owner/admin | `id`, `enabled`, `fenced_runs` |
| `claim_analysis_work` | `p_project_id`, `p_lease_seconds` (default 300) | Designated, registered worker and currently authorized creator | Zero or one row: `work_item_id`, `run_id`, `attempt`, `max_attempts`, `lease_token`, `lease_expires_at`, `kind`, `source_url`, `source_owner`, `source_repo`, `input_digest`, `pinned_source_ref`, `pinned_source_commit`, `previous_source_digest`, `previous_checkpoint` |
| `heartbeat_analysis_run` | `p_run_id`, `p_lease_token`, `p_phase`, `p_checkpoint`, `p_source_ref`, `p_source_commit`, `p_source_digest`, `p_lease_seconds` | Registered worker identity that owns the run | `lease_valid`, `reason`, `run_status`, `work_item_status`, `cancel_requested`, `lease_expires_at`, `phase` |
| `finish_analysis_run` | `p_run_id`, `p_lease_token`, `p_result` | Registered worker identity that owns the run | `accepted`, `reason`, `work_item_status` |
| `fail_analysis_run` | `p_run_id`, `p_lease_token`, `p_error_code` | Registered worker identity that owns the run | `accepted`, `reason`, `work_item_status`, `retry_scheduled` |

A worker identity is a separate Supabase Auth user carrying `raw_app_meta_data->>'oryveta_role' = 'factory_worker'` **and** an enabled `project_workers` row for the project it acts on; both conditions are re-checked on every worker call. `register_project_worker` refuses the caller's own account, any account without that designation, and any project or workspace member. Run-scoped calls additionally require `factory_runs.worker_user_id = auth.uid()`, and a run owned by another identity is reported as missing rather than forbidden, so run IDs are not probeable. `cancel_work_item` reports an unauthorized or unknown work item with the same "not found" message for the same reason.

Fencing outcomes normally return `lease_valid = false` or `accepted = false`: `worker_not_registered`, `cancelled`, `not_running`, `lease_lost` or `creator_unauthorized`. Creator revocation terminally fences the attempt and fails the work item without retry. Completion additionally requires repository reference, commit and archive digest and refuses missing/conflicting source identity. Conflicting heartbeat identity arguments raise rather than being silently ignored. Invalid callers/arguments raise. Concurrent identical idempotent submissions return the same work item; a key reused for a different frozen input is rejected.

Read surface, all RLS-filtered to current project readers and to the project's own enabled worker identity:

- `GET /rest/v1/work_items` — `id`, `project_id`, `created_by`, `kind`, `status`, `source_url`, `source_owner`, `source_repo`, `input_digest`, `idempotency_key`, `attempts`, `max_attempts`, `error_code`, `pinned_source_ref`, `pinned_source_commit`, `cancel_requested_at`, `cancelled_by`, `created_at`, `updated_at`.
- `GET /rest/v1/factory_runs` — `id`, `work_item_id`, `project_id`, `attempt`, `worker_user_id`, `worker_registration_id`, `status`, `phase`, `checkpoint`, `source_ref`, `source_commit`, `source_digest`, `result`, `error_code`, `lease_expires_at`, `heartbeat_at`, `started_at`, `finished_at`.
- `GET /rest/v1/factory_run_events` — `id`, `run_id`, `work_item_id`, `project_id`, `kind`, `phase`, `detail`, `created_at`. `id` is a monotonic identity column, so a client can page the log forward; `detail` is derived server side from validated arguments and is at most 200 characters.
- `GET /rest/v1/project_workers` — `id`, `project_id`, `worker_user_id`, `label`, `enabled`, `registered_by`, `created_at`, `revoked_at`, `revoked_by`. Visible only to project admins and to the worker identity itself, so a worker can confirm its own scope.

Enumerations are complete and checked in the schema. Work item `status`: `queued`, `running`, `succeeded`, `failed`, `cancelled`. Run `status`: `running`, `succeeded`, `failed`, `cancelled`. Run `phase`: `claimed`, `fetching_source`, `analyzing`, `recording_result`, `done`. Event `kind`: `claimed`, `source_resolved`, `phase_changed`, `checkpoint`, `succeeded`, `failed`, `cancelled`, `lease_expired`, `retry_scheduled`, `attempts_exhausted`.

Bounds a client can rely on: `p_lease_seconds` is 15–900 seconds and defaults to 300; `max_attempts` defaults to 2 and is constrained to 1–5, with `attempts <= max_attempts`; a checkpoint is a flat JSON object of at most 16 snake_case keys with scalar values, at most 4,096 bytes; a result is a JSON object of only `summary` and `findings`, at most 262,144 bytes (256 KB) with at most 400 findings whose fields are limited to `path`, `line`, `category`, `severity`, `title`, `recommendation`, `confidence`; each run's event log stops at 200 rows, so a looping worker cannot grow it without bound. `error_code` on both work items and runs matches `^[a-z][a-z0-9_]{2,47}$`. Attempt exhaustion is an explicit terminal state, not a silently idle row: the work item reaches `status = 'failed'` with `attempts = max_attempts`, keeps the *last attempt's actual cause* in `error_code` (for example `invalid_repository` or `lease_expired`), and the final run carries an `attempts_exhausted` event; each attempt's own cause stays on its `factory_runs.error_code`. An idempotency key is 8–120 characters of `A-Z a-z 0-9 . _ : -` and is scoped to one project, one submitting account and that key, so two accounts cannot collide and a key cannot cross a project boundary. `input_digest` is the SHA-256 of the task kind plus the frozen source URL.

Progress events stop at 180 per run, reserving capacity for terminal/retry outcomes. Registration, work-item, run and lease locks use a consistent order. The first resolved repository/commit is pinned for subsequent attempts. Lease deadlines and expiry decisions use the wall clock after relevant locks, not the transaction-start timestamp. Ten real multi-session PostgreSQL cases exercise cancellation/completion, revocation/claim, concurrent pinning, idempotency and a lock wait longer than the requested lease.

Browsers cannot mutate run state. Only `submit_repository_analysis`, `cancel_work_item`, `register_project_worker` and `revoke_project_worker` are reachable from a human session; the four worker RPCs refuse an undesignated identity. The fencing token is not readable through this API at any privilege a client can hold: it lives in `private.factory_run_leases`, which is not an exposed PostgREST schema and on which `authenticated` holds no privilege, so no run read and no forgotten policy can return a live lease token. `factory_runs.lease_expires_at` is liveness information only. On the four public tables the `authenticated` role holds SELECT only and `anon` holds nothing, so a missing write policy fails closed instead of exposing a write.

## Current GitHub API implementation (local/self-hosted; not deployed on the hosted site)

The published FastAPI source supports health/config, GitHub identity OAuth callback, local-only demo auth, logout, current user/session, owner-scoped projects, scaffold generation, bounded repository ZIP or public GitHub imports, analysis jobs, status/events and artifact export. This API requires live code verification and real credentials before hosted use.

## Current job control API (single-host)

- `GET /api/jobs?project_id=<id>` — authenticated owner-only safe job summaries, optionally filtered to one owned project. The response omits lease tokens, result blobs and event history.
- `GET /api/jobs/{job_id}` — authenticated owner-only job status with sanitized fields and ascending persisted `events` (`id`, `kind`, `detail`, `created_at`). It also returns `started_at` from the first `job_started` event and terminal-only `finished_at` from `updated_at`; neither field invents granular task progress.
- `POST /api/jobs/{job_id}/cancel` — authenticated owner-only, CSRF-protected cancellation; `200` for queued/running and already-canceled tasks, `409` for succeeded/failed tasks, `404` for non-owned IDs.
- New job admission is capped at eight queued/running tasks per authenticated user, atomically enforced in SQLite; over-limit requests return `429` with `Retry-After: 30`. Matching idempotency-key benchmark retries are replayed without consuming extra capacity.
- Worker lease heartbeats keep long-running tasks eligible to commit, while canceled or stolen leases cannot publish results. Running CPU work is **not** forcibly terminated by this endpoint; killable sandboxes are still required before executing imported code.

## Self-hosted React Studio

- `/studio` redirects to canonical `/studio/`, which serves the self-hosted Vite build from `apps/web/studio/dist-local`.
- Extensionless page paths such as `/studio/about` and `/studio/workspace/evolve` serve the same app shell for client-side routing. Paths containing a dot, reserved API/auth prefixes, and missing `/studio/assets/*` files return `404` rather than HTML.
- `/studio/assets/*`, `/studio/demo-stories.json` and `/studio/template-license.txt` are same-origin built distribution files.
- If the self-hosted build is absent, Studio page and distribution routes return HTTP `503` while legacy `/` remains available. Escaped asset paths return `404`.

## Optional local model gateway (self-hosted only)

- `GET /api/ai/budget`: authenticated, owner-scoped UTC daily token allowance and current reservations.
- `POST /api/ai/generate`: CSRF-protected text-only local Ollama request, bounded to 4096 UTF-8 prompt bytes and 512 output tokens. Requires operator-configured model; disabled by default.
- The API reserves worst-case tokens before inference, settles verified provider usage, rejects over-limit output, and fails closed on timeout/unknown usage. Default allowance is 20,000 tokens/day/account and two concurrent calls. No prompts or generated text are stored in the usage ledger.
- No tool calls, repository writes, independent verification or real model quality guarantees are provided by this endpoint. See [MODEL-GATEWAY.md](MODEL-GATEWAY.md).

## AI-assisted Evolve patch proposal (read-only)

- `POST /api/projects/{project_id}/ai-patch-preview`: authenticated, CSRF-protected and owner-scoped. Requires `path`, `expected_sha256`, `source` (the exact file contents, at most 1,500 characters) and `instruction` (8–350 characters).
- First checks that the supplied source hashes to the expected digest, then validates the actual workspace file and safe path. Only then does it spend a local-model budget reservation.
- The model proposes a **complete replacement file**; Oryveta checks the unchanged baseline again and returns a unified diff, SHA-256 digests, Python syntax check where applicable, usage and `review_required` status. The original file is never written.
- Rejects unsafe paths, symlinks, stale content, invalid Python output and unavailable local models. No commands, tests, GitHub writes or deployments run. See [EVOLVE-PATCH-PREVIEW.md](EVOLVE-PATCH-PREVIEW.md).

## Target versioned HTTP resources

Auth: GET /api/v1/me; POST /api/v1/logout; GitHub OAuth start/callback; GitHub App installation callback and webhook.

Workspace: GET/POST /api/v1/organizations; GET/POST /api/v1/projects; POST /api/v1/projects/{id}/specifications; GET /api/v1/projects/{id}.

Start New: POST /api/v1/projects/{id}/plans; POST /api/v1/projects/{id}/builds; GET /api/v1/builds/{id}/artifacts.

Evolve: POST /api/v1/repository-imports; POST /api/v1/analyses; GET /api/v1/analyses/{id}/findings; POST /api/v1/change-proposals; POST /api/v1/change-proposals/{id}/execute.

Execution: GET /api/v1/tasks; GET /api/v1/tasks/{id}; POST /api/v1/tasks/{id}/cancel; GET /api/v1/tasks/{id}/events; POST /api/v1/approvals/{id}/decision.

Evidence: GET /api/v1/receipts/{id}; GET /api/v1/experiments; GET /api/v1/experiments/{id}/metrics.

These routes are **proposed**, not implemented endpoints.

## Contracts, auth and idempotency

Use an OpenAPI schema and generated TS/Python clients where practical. Validate requests (Zod/Pydantic) and model explicit states; enforce identity + tenant + resource permissions on each call. Every mutation that may retry accepts idempotency keys. Return clear structured errors: validation, unauthorized, forbidden, not found, conflict, quota exceeded, backend unavailable and verification failed.

Tasks contain contract version, owner, repository baseline, allowed tools/network, timeout/budget, approval rules and cancellation token. Events link evidence and immutable revisions, not raw secrets.

## GitHub integration

GitHub OAuth for login; GitHub App installation-token permissions for selected repositories; HMAC-validated webhooks; PR and CI workflows separate from simple login. Avoid storing broad long-lived personal access tokens.


## Repository analysis v2 (static, local only)

- Bounded ZIP import validates unsafe paths, duplicates, file/directory collisions,
  symlinks and expanded sizes before extraction. If extraction fails, temporary
  files are cleaned up; a single `src/` archive is not incorrectly flattened.
- Imported repositories are **not executed**. Analysis categorizes bounded
  source files and recognizes limited dependency/build manifests
  (`package.json`, `pyproject.toml`, `requirements.txt`,
  `Cargo.toml`, `go.mod`, `pom.xml` and Gradle files).
- `analysis.summary.technology` contains deterministic ecosystem/framework
  hints, manifest names, test-folder and CI flags. These are *manifest hints*,
  not proof of runtime behavior or compatibility.
- `input_fingerprint_sha256` hashes the **entire bounded content** of analyzed
  files and recognized readable manifests with length/path framing, not
  just their first 1000 characters; changes can be compared for stale analyses.
  A truncated/skipped repository must not be mistaken for full coverage.
- Python `eval`/`exec` and `shell=True` security detections are AST-based,
  avoiding code-comment and string false positives. Findings still need
  human triage and are not a comprehensive vulnerability scan.
- When over 400 findings are found, `findings_truncated` and
  `findings_returned` expose the cap. Nothing is auto-patched, pushed,
  executed or approved based only on these heuristics.
