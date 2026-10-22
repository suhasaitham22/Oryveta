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

## Current GitHub API implementation (local/self-hosted; not deployed on the static preview)

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
