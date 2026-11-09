# API and integration contracts

## Current public website

The hosted frontend uses Supabase for identity, persisted project briefs, membership and private conversations, plus the durable analysis and controlled repair control planes below. Start New/Evolve **execution** remains unavailable online: a saved brief is not a generated application, and a submitted analysis or repair only runs when an authorized worker process is started by an operator on hardware they own. No hosted endpoint performs model-driven code changes, and no endpoint approves, publishes or deploys a repair candidate.

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

Durable repository analysis uses the same configured Supabase project's `/rest/v1` API with the caller's authenticated token. Apply `supabase/schema.sql`, `supabase/migrations/private_chats_and_explicit_sharing.sql`, `supabase/migrations/projects_and_project_membership.sql`, `supabase/migrations/durable_factory_runtime.sql`, `supabase/migrations/retained_attribution_and_lease_clock.sql` and `supabase/migrations/controlled_repair_runtime.sql`, in that order. An installation already at the fourth file needs the fifth and sixth; one already at the fifth needs only the sixth, which is repeatable. Reads are RLS-filtered SELECT; every state change goes through a narrow RPC. This section covers the `repository_analysis` kind, which operates on the project's frozen public GitHub source; the second kind, `repository_repair`, is documented in [Hosted controlled repair](#hosted-controlled-repair) below and shares these tables, leases, events and reclaim paths. For neither kind are arbitrary commands, host paths or private-repository grants expressible.

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

Enumerations are complete and checked in the schema, and are shared with the repair kind. Work item `kind`: `repository_analysis`, `repository_repair`. Work item `status`: `queued`, `running`, `succeeded`, `failed`, `cancelled`. Run `status`: `running`, `succeeded`, `failed`, `cancelled`. Run `phase`: `claimed`, `fetching_source`, `analyzing`, `repairing`, `verifying`, `recording_result`, `done` — `analyzing` occurs only on an analysis attempt and `repairing`/`verifying` only on a repair attempt, which a per-run trigger enforces structurally rather than leaving to the calling RPC. Event `kind`: `claimed`, `source_resolved`, `phase_changed`, `checkpoint`, `succeeded`, `failed`, `cancelled`, `lease_expired`, `retry_scheduled`, `attempts_exhausted`.

Bounds a client can rely on: `p_lease_seconds` is 15–900 seconds and defaults to 300; `max_attempts` defaults to 2 and is constrained to 1–5, with `attempts <= max_attempts`; a checkpoint is a flat JSON object of at most 16 snake_case keys with scalar values, at most 4,096 bytes; a result is a JSON object of only `summary` and `findings`, at most 262,144 bytes (256 KB) with at most 400 findings whose fields are limited to `path`, `line`, `category`, `severity`, `title`, `recommendation`, `confidence`; each run's event log stops at 200 rows, so a looping worker cannot grow it without bound. `error_code` on both work items and runs matches `^[a-z][a-z0-9_]{2,47}$`. Attempt exhaustion is an explicit terminal state, not a silently idle row: the work item reaches `status = 'failed'` with `attempts = max_attempts`, keeps the *last attempt's actual cause* in `error_code` (for example `invalid_repository` or `lease_expired`), and the final run carries an `attempts_exhausted` event; each attempt's own cause stays on its `factory_runs.error_code`. An idempotency key is 8–120 characters of `A-Z a-z 0-9 . _ : -` and is scoped to one project, one submitting account and that key, so two accounts cannot collide and a key cannot cross a project boundary. `input_digest` is the SHA-256 of the task kind plus the frozen source URL.

Progress events stop at 180 per run, reserving capacity for terminal/retry outcomes. Registration, work-item, run and lease locks use a consistent order. The first resolved repository/commit is pinned for subsequent attempts. Lease deadlines and expiry decisions use the wall clock after relevant locks, not the transaction-start timestamp. Ten real multi-session PostgreSQL cases exercise cancellation/completion, revocation/claim, concurrent pinning, idempotency and a lock wait longer than the requested lease.

Browsers cannot mutate run state. Only `submit_repository_analysis`, `cancel_work_item`, `register_project_worker` and `revoke_project_worker` are reachable from a human session; the four worker RPCs refuse an undesignated identity. The fencing token is not readable through this API at any privilege a client can hold: it lives in `private.factory_run_leases`, which is not an exposed PostgREST schema and on which `authenticated` holds no privilege, so no run read and no forgotten policy can return a live lease token. `factory_runs.lease_expires_at` is liveness information only. On every exposed table of this runtime — the four above plus `project_repair_policies` — the `authenticated` role holds SELECT only and `anon` holds nothing, so a missing write policy fails closed instead of exposing a write.

## Hosted controlled repair

`supabase/migrations/controlled_repair_runtime.sql` adds a second task kind to the tables above. There is **no second queue**: repair work is `public.work_items` of kind `repository_repair`, with attempts on `public.factory_runs`, events on `public.factory_run_events` and fencing tokens in `private.factory_run_leases`, exactly as analysis work is — one metadata authority, one reclaim path, one cancellation path, one revocation path. The migration changes no existing RPC argument list or return shape, relaxes no authorization, pinning or fencing check, and adds no write privilege for any client role. Operating this path is documented in [OPERATIONS.md](OPERATIONS.md#controlled-durable-repair-operations).

Code execution is not a capability any existing analysis worker gains. It is bound by a `public.project_repair_policies` row that a project owner or admin enrolls, naming one project, one already-designated and registered worker Auth identity, one public GitHub URL and 40-hex commit, and one operator configuration SHA-256. The policy's identity, source and configuration are immutable — a table trigger permits only revocation, cleared attribution of a deleted account, the clearing of the live worker reference and the worker's last-contact timestamp to change — so any other change is a **new policy**. The row installs nothing and grants no inference budget; it records that an operator reviewed a configuration and designated a worker for one frozen snapshot. The commands, expected cases, file/model/runner grants and budgets stay in the operator's local configuration file: nothing in this schema can name a command, a host path, a model endpoint or a container image.

The worker identity is recorded twice, following the retained-attribution rule the lease-clock migration established. `worker_identity` is the frozen enrollment: the Auth id an operator designated for this snapshot, with no foreign key, immutable, outliving the account so what was approved stays readable after an offboarding — and carrying **no authority**. `worker_user_id` is the live reference every authorization check and the RLS predicate read; it is *cleared*, never redirected and never restored, when the account is deleted, and a null live identity is a refusal everywhere rather than a wildcard. Clearing it withdraws the enrollment and settles its unfinished work in the same statement, so deleting a worker account succeeds and leaves the enrollment and the repair history intact instead of deadlocking against human-created work items that still name the policy. Deleting a policy on its own while work items still name it stays refused. An offboarded identity is re-enrolled only as a new, re-reviewed policy.

| RPC | Parameters | Authorization | Returned columns |
| --- | --- | --- | --- |
| `register_project_repair_policy` | `p_project_id`, `p_worker_user_id`, `p_label`, `p_source_commit`, `p_configuration_sha256` | Project owner/admin; the worker must already hold the `factory_worker` designation and an enabled `project_workers` registration, must not be the caller's own account and must not be a project or workspace member | The full policy row: `id`, `project_id`, `worker_user_id`, `label`, `enabled`, `source_url`, `source_owner`, `source_repo`, `source_commit`, `configuration_sha256`, `last_seen_at`, `created_at`, `created_by`, `revoked_at`, `revoked_by` |
| `revoke_project_repair_policy` | `p_policy_id` | Project owner/admin | `id`, `enabled`, `fenced_runs` |
| `submit_repository_repair` | `p_project_id`, `p_policy_id`, `p_goal`, optional `p_idempotency_key` | Current project role engineer or above, same `creator_may_run` rule as analysis | `work_item_id`, `status`, `replayed`, `kind`, `source_url`, `input_digest`, `attempts`, `max_attempts`, `repair_policy_id`, `goal` |
| `claim_repair_work` | `p_policy_id`, `p_configuration_sha256`, `p_lease_seconds` (default 300) | Only the policy's bound worker, with the designation, an enabled registration and a currently authorized submitter; the supplied digest must equal the policy's | Zero or one row: `work_item_id`, `run_id`, `attempt`, `max_attempts`, `lease_token`, `lease_expires_at`, `kind`, `project_id`, `source_url`, `source_owner`, `source_repo`, `pinned_source_ref`, `pinned_source_commit`, `previous_source_digest`, `previous_checkpoint`, `repair_policy_id`, `goal`, `configuration_sha256` |
| `heartbeat_repair_run` | `p_run_id`, `p_lease_token`, `p_phase`, `p_checkpoint`, `p_source_ref`, `p_source_commit`, `p_source_digest`, `p_lease_seconds` | The registered worker identity that owns the run, re-checked against the policy, the submitter's role, the lease and the pinned source on every call | `lease_valid`, `reason`, `run_status`, `work_item_status`, `cancel_requested`, `lease_expires_at`, `phase` |
| `finish_repair_run` | `p_run_id`, `p_lease_token`, `p_result` | Same identity and fencing as the heartbeat, plus an exact policy-configuration and source-pin match | `accepted`, `reason`, `work_item_status` |
| `fail_repair_run` | `p_run_id`, `p_lease_token`, `p_error_code` | Same identity and fencing as the heartbeat | `accepted`, `reason`, `work_item_status`, `retry_scheduled` |

The existing generic `cancel_work_item` and `revoke_project_worker` fence repair work too, and keep their existing signatures and return shapes. Revoking a policy disables it — the row is never deleted, so the record of what was approved survives — fences every attempt running under it, deletes those leases and settles the work terminally instead of leaving it queued; it reports how many runs it fenced. Policies are never re-enabled.

Admission freezes what the attempt may ever do, and re-derives authority rather than trusting the enrollment row. `submit_repository_repair` requires the policy to be enabled and to belong to the named project, **and** an enabled `project_workers` registration for the bound identity, **and** that identity's current `factory_worker` designation — the same conjunction `claim_repair_work` requires — with the registration taken before the policy, in the one lock order, and both held `FOR SHARE` until the work item is inserted, so an admission cannot race a concurrent revocation. `register_project_repair_policy` takes the registration `FOR SHARE` the same way before inserting an enrollment. It also requires the project's **currently saved source** to still match the policy for a *new* admission; it then freezes the source URL, owner, repo, `pinned_source_ref` and `pinned_source_commit` from the policy, together with the goal and the policy binding, and sets `max_attempts = 2`. Idempotency keeps the existing scope — one project, one submitting account, one key — and a key reused with a different goal, policy or kind is refused rather than replayed. A goal is 1–4,096 bytes of trimmed UTF-8 text with no control characters other than newline and tab, and submitting it shares it with everyone who can read the project; it is never copied from a private conversation.

Submission raises, rather than quietly queueing, when the bound worker's standing has lapsed, and a client can surface these verbatim: *"the worker identity bound to this repair policy is no longer registered for this project"*, *"the worker identity bound to this repair policy is no longer a provisioned factory worker service identity"* and *"the worker identity bound to this repair policy no longer exists"*. Enrollment itself refuses an unregistered identity with *"worker identity is not registered for this project"*.

Kind-dependent constraints keep the two kinds from contaminating each other. An analysis row must carry no `repair_policy_id` and no `goal`; a repair row must carry both, plus its pin, from the moment it is admitted. A per-run trigger enforces the phase enum and the result shape per kind, so an analysis completion path cannot write an analysis-shaped result or an `analyzing` phase onto a repair attempt, and a repair result cannot appear on an analysis attempt, whatever path is taken. An RPC called with the wrong kind returns `wrong_kind` without taking a lock or spending an attempt.

Fencing outcomes are reported, not raised, so a worker has an unambiguous signal to stop: `worker_not_registered`, `policy_revoked`, `creator_unauthorized`, `cancelled`, `not_running`, `lease_lost` or `wrong_kind`. The first three mean authority was lost and are terminal rather than retryable.

Terminal `work_items.error_code` values this runtime can settle a repair item with include `policy_revoked`, `worker_revoked`, `worker_identity_deleted`, `creator_unauthorized`, `lease_expired`, `source_identity_conflict` and `attempts_exhausted`, in addition to the attempt-level codes a worker reports. `worker_identity_deleted` is written by the deleted-identity settlement path described above, not by a worker.

Repair read surface, in addition to the four tables above:

- `GET /rest/v1/project_repair_policies` — `id`, `project_id`, `worker_identity`, `worker_user_id`, `label`, `enabled`, `source_url`, `source_owner`, `source_repo`, `source_commit`, `configuration_sha256`, `last_seen_at`, `created_at`, `created_by`, `revoked_at`, `revoked_by`. RLS admits current project readers and the live worker identity itself, so a worker can confirm the scope it was started with; `anon` holds nothing and no client role holds a write privilege, so enrollment and revocation exist only through the two RPCs. Revoked policies and policies whose live worker reference has been cleared both remain readable, because work history still names them — treat a null `worker_user_id` as "this enrollment can no longer admit or claim anything", not as an unrestricted one.
- `GET /rest/v1/work_items` additionally exposes `repair_policy_id` and `goal` on repair rows, under the same RLS as the rest of the row.

`last_seen_at` is the last authenticated, authorized contact from the bound worker — refreshed even on an idle claim, but only after every authorization check has passed, and it only ever moves forward, so a stale or out-of-order write cannot make an idle worker look like it just polled. It is **not** capacity, availability or an uptime signal, and no scheduling decision reads it. Clients must present it as last contact, never as uptime.

Bounds a repair client can rely on. `p_lease_seconds` is 15–900 and defaults to 300. `max_attempts` is 2, fixed at admission. A label is 2–60 characters of `A-Z a-z 0-9`, space, `.`, `_` or `-`; `source_commit` is 40 lowercase hex characters; `configuration_sha256` is 64 lowercase hex characters, and neither hash is normalized or re-cased. A repair checkpoint is at most 4,096 bytes and admits only `step` (one of `fetching_source`, `snapshot_ready`, `repairing`, `verifying`, `recording_result`), the bounded non-negative numbers `turns` (≤50), `tool_calls` (≤100), `tokens_observed` (≤500,000), `unsettled_token_reservation` (≤500,000), `elapsed_seconds` (≤86,400), `archive_bytes` (≤1 GiB) and `archive_entries` (≤1,000,000), the hashes `source_commit` and `configuration_sha256`, and the boolean `source_pinned`. Any other key is refused rather than ignored, so a prompt, tool argument, host path, credential or upstream error message has nowhere to go. `error_code` matches `^[a-z][a-z0-9_]{2,47}$` on both work items and runs.

A persisted repair result is a JSON object of at most 196,608 bytes (192 KiB) containing exactly these fifteen required fields and nothing else: `kind` (`repository_repair`), `status` (`needs_review`), `verification` (`passed`), `configuration_sha256`, `source_commit`, `source_tree_sha256`, `candidate_tree_sha256`, `patch_sha256`, `patch`, `checks_passed` (1–48), `turns` (1–50), `tool_calls` (0–100), `tokens_observed` (0–500,000), `model_name` and `model_digest`. Hashes are 64 lowercase hex characters except the 40-character `source_commit`; `model_name` matches the same safe local-model pattern the operator configuration accepts; a candidate tree equal to the source tree is refused because it changed nothing. The patch is non-empty UTF-8 of at most 65,536 bytes and its SHA-256 is **recomputed** in the database and compared to `patch_sha256`. An over-limit patch is refused rather than stored truncated, and metadata without a patch is not a result. Absent by design: command lines, check stdout/stderr, the operator's expected acceptance values, the model trajectory, container names, host paths and run receipts — those stay in the operator's private evidence root.

`succeeded` on a repair work item means one thing: an attempt computed a candidate that passed the operator's own checks and is **ready for review**. It is not an approval, a merge, a deployment or a remote attestation. The registered worker is a trusted producer and this validation bounds what it may persist; it is not remote attestation of the producer. A client may show and download the patch and the safe receipt metadata from an accepted result, and must present it as a change needing independent review.

Browsers still cannot mutate run state for this kind. Only `submit_repository_repair`, `cancel_work_item`, `register_project_repair_policy` and `revoke_project_repair_policy` are reachable from a human session; the four repair worker RPCs refuse an undesignated identity, and the lease token remains unreadable at any privilege a client can hold. Every exposed function is `SECURITY DEFINER` with an empty `search_path` and explicit auth/role checks, with execution revoked from `public` and `anon`. No service-role credential belongs in a worker or a browser. A policy or run in another project is reported as missing rather than forbidden, so ids are not probeable.

Lock order for the whole repair runtime is one rule: `project_workers` → `project_repair_policies` → `work_items` → `factory_runs`. The policy row sits between the registration and the work item, so the existing work-item-then-run order is unchanged and analysis paths, which never touch a policy, keep exactly the ordering they had. Deadlines and every comparison against a deadline read `clock_timestamp()` after the locks are held.

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
- Extensionless page paths such as `/studio/about`, `/studio/pricing` and `/studio/workspace/evolve` serve the same app shell for client-side routing. Paths containing a dot, reserved API/auth prefixes, and missing `/studio/assets/*` files return `404` rather than HTML.
- Dotted distribution files are served **only** through an explicit per-file allowlist, never a general dotted-path fallback. The allowlisted files are `/studio/assets/*`, `/studio/demo-stories.json`, `/studio/template-license.txt`, `/studio/geist-license.txt`, `/studio/repair-example.json` and `/studio/repair-example.patch`. Any other dotted path stays `404`. Adding a new built file to `apps/web/studio/public/` therefore requires adding its route too; a file that exists in the build but has no route is served as `404`.
- `/studio/repair-example.json` and `/studio/repair-example.patch` are the sanitized **synthetic** repair example — reviewed static build assets extracted from one historical local run, not a live feed, a benchmark, a customer result or a view into any operator's private evidence directory. No endpoint exposes a run directory or lets a caller start a repair.
- If the self-hosted build is absent, Studio page and distribution routes return HTTP `503` while legacy `/` remains available. Escaped asset paths return `404`.
- The hosted Vercel build serves the same `public/` files at the origin root (for example `/repair-example.json`), because its SPA rewrite excludes any path containing a dot. `/studio/*` belongs to the self-hosted FastAPI surface only.

## Optional local model gateway (self-hosted only)

- `GET /api/ai/budget`: authenticated, owner-scoped UTC daily token allowance and current reservations.
- `POST /api/ai/generate`: CSRF-protected text-only local Ollama request, bounded to 4096 UTF-8 prompt bytes and 512 output tokens. Requires operator-configured model; disabled by default.
- The API reserves worst-case tokens before inference, settles verified provider usage, rejects over-limit output, and fails closed on timeout/unknown usage. Default allowance is 20,000 tokens/day/account and two concurrent calls. No prompts or generated text are stored in the usage ledger.
- No tool calls, repository writes, independent verification or real model quality guarantees are provided by this endpoint. See [MODEL-GATEWAY.md](MODEL-GATEWAY.md).

## AI-assisted Evolve patch proposal (read-only, single file, no execution)

- `POST /api/projects/{project_id}/ai-patch-preview`: authenticated, CSRF-protected and owner-scoped. Requires `path`, `expected_sha256`, `source` (the exact file contents, at most 1,500 characters) and `instruction` (8–350 characters).
- First checks that the supplied source hashes to the expected digest, then validates the actual workspace file and safe path. Only then does it spend a local-model budget reservation.
- The model proposes a **complete replacement file**; Oryveta checks the unchanged baseline again and returns a unified diff, SHA-256 digests, Python syntax check where applicable, usage and `review_required` status. The original file is never written.
- Rejects unsafe paths, symlinks, stale content, invalid Python output and unavailable local models. No commands, tests, GitHub writes or deployments run. See [EVOLVE-PATCH-PREVIEW.md](EVOLVE-PATCH-PREVIEW.md).

**This endpoint is not the coding CLI.** It is a read-only, one-file, syntax-only suggestion with no execution and no behavioral verification. The separate operator-run `python -m oryveta_engine.coding_runtime` performs multi-turn model-driven edits across an allowlisted file set with controller-owned check execution in isolated containers, and it has **no HTTP surface at all**: it cannot be invoked by an authenticated user, a project, a hosted worker or any route on either deployment. Nothing in this API reads or writes its evidence directories. See [IMPLEMENTATION.md](IMPLEMENTATION.md#local-verified-repair-cli).

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
