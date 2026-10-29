# Reliability, delivery pipeline and operational practices

## CI gates

Required checks before considering a production release: formatting, lint, static types, deterministic tests, integration/e2e acceptance, dependency/security scanning, isolation tests, license audits, migration rehearsal and deploy smoke test. GitHub Actions must use scoped permissions and pinned reviewed actions; prevent unreviewed PRs from exposing secrets.

The initial public preview has a dedicated workflow in .github/workflows/preview-checks.yml. Status and complete code coverage must be verified from actual GitHub Actions runs; do not infer that Vercel deploy success means CI success.

## Durable job state

Persist New → Queued → Leased → Running → Verifying → Awaiting Approval → Completed/Failed/Canceled. Include heartbeat, lease expiration, idempotency, retry counter and dead-letter records. Workers may crash/restart or lose network. Reconcile outputs and replay safe operations only; never blindly repeat deployments, emails or destructive data writes.

## Durable analysis worker operations

This covers project-authorized repository analysis, served by `python -m oryveta_engine.factory_runtime`. Apply `durable_factory_runtime.sql` after its workspace/chat/project prerequisites, then `retained_attribution_and_lease_clock.sql` before starting the worker. Flags and credential format are in [IMPLEMENTATION.md](IMPLEMENTATION.md); RPCs and read contracts are in [API.md](API.md).

### Worker identity provisioning

A worker is a separate Supabase Auth user, never a human's browser session. Provisioning is two steps with two different authorities:

1. An administrator creates the Auth user and designates it with the Auth admin API, setting `app_metadata.oryveta_role = 'factory_worker'`. Only the admin API can write that field: an account cannot self-assign it, and `register_project_worker` deliberately cannot create or designate users.
2. A project owner or admin calls `register_project_worker(p_project_id, p_worker_user_id, p_label)` with a 2–60 character label of `A-Z a-z 0-9`, space, `.`, `_` or `-`. The RPC refuses the caller's own account, any account without the designation, and any project or workspace member, so a project admin cannot promote a colleague's ordinary account into a worker.

Authority is the conjunction of both facts and is re-checked on every worker call, so there are two independent ways to stop an identity. `revoke_project_worker` disables the registration and immediately fences every run that identity still holds in that project with `error_code = 'worker_revoked'`; removing the `oryveta_role` designation in Auth fences the identity everywhere at once. Re-registering a revoked identity re-enables the same row. Registration is per project: an identity that serves two projects needs a registration in each, and one worker process serves one project (`--project`).

### Credential handling

The worker process holds only an ordinary Auth session. Do not provision a continuous worker host with an admin/service-role credential; identity designation belongs to the administrator. The opt-in production verification harness temporarily performs administrative setup on the same machine as its one-off worker, but does not pass the admin key to that worker's environment or credential file. That check proves process-level credential handling, not hardened host isolation.

- Keep the credential file as a non-symlink regular file with no group or world permission bits (`chmod 600`); the worker refuses to start otherwise. `ORYVETA_WORKER_CREDENTIALS` is a secure reference to that path, not a place to put the token itself.
- Supabase rotates refresh tokens. The worker persists them through a `0600` temporary file, `fsync` and atomic replace. This protects file integrity, not a crash between remote token issuance and local persistence; re-provision a rejected session. Give each worker process its own independently issued session and credential file; never copy one rotating token across processes.
- Tokens are excluded from credential `repr` and from control-plane error diagnostics. HTTP errors retain method/path/status and only the two fixed source-conflict messages; raw response bodies and upstream protocol-error text are not logged because they can reflect credentials or private leases. The analysis child receives a minimal environment without the parent's tokens, lease or network identity.
- A leaked worker credential is bounded but not harmless. On the durable-work surface it grants claim/heartbeat/finish/fail for the projects where that identity is registered plus the RLS-filtered reads those projects allow — it is not a project member, holds no admin or service-role authority, and cannot submit, cancel or register anything. It is still a valid Auth session on the rest of the project's schema, so treat it like any other user credential: revoke the registration, remove the `oryveta_role` designation, or both, then re-provision.

### Unattended service startup

`python -m oryveta_engine.factory_service` wraps the same analysis worker; it does not create an identity or grant project access. Provision and register a dedicated worker session first. Set `ORYVETA_WORKER_BOOTSTRAP` as a **secret environment variable** containing the credential JSON documented in [IMPLEMENTATION.md](IMPLEMENTATION.md#durable-analysis-worker-self-hosted). Do not place it in source, command arguments, build arguments or logs.

- The default credential path is `/data/worker/credentials.json`. First startup validates the bootstrap and publishes a `0600` file in a `0700` directory. Later starts use that file, even if the bootstrap is missing or obsolete. Corrupt, unsafe or rejected persisted credentials fail closed; they are never silently replaced with the initial token.
- One service holds an OS lock on its credential directory for its entire lifetime. Do not run the direct `factory_runtime` CLI against that same session or directory: it does not participate in the service lock. Independent workers require independent Auth sessions and private directories.
- Only the credential directory needs persistent storage. The default analysis work directory is temporary and removed on normal completion or SIGTERM. Hard-killed containers can leave transient files until their writable layer is discarded. `--work-root` remains available for the direct worker's explicit startup-sweep behavior.
- The bootstrap variable is removed from the service's process environment before starting work. After the first successful authenticated run, remove the bootstrap secret from the hosting configuration too. The hosting platform may retain historical deployment variables; treat the original session as sensitive.

With the secret already set in the invoking environment:

```bash
docker build --tag oryveta-worker:local .
docker volume create oryveta-worker-state
docker run --detach --name oryveta-worker --user 0:0 \
  --restart on-failure:3 \
  --volume oryveta-worker-state:/data \
  --env ORYVETA_WORKER_BOOTSTRAP \
  --entrypoint python oryveta-worker:local \
  -m oryveta_engine.factory_service
```

Root is used **only to prepare the mounted private directory**; the service clears supplementary groups and switches to UID/GID `65532` before loading credentials, contacting Supabase or analyzing a repository. Root startup refuses an unmounted `/data` or another credential path. The existing API image still defaults to a non-root API process.

For Railway, attach a persistent volume at `/data`, use the existing Dockerfile, set the start command to `python -m oryveta_engine.factory_service`, and set `RAILWAY_RUN_UID=0` for that initialization step. Railway supplies `RAILWAY_VOLUME_MOUNT_PATH`; the service checks the mount and refuses ephemeral state. Keep one replica, no public domain/inbound port, sleeping disabled and a bounded restart policy (at most three retries). Check the account's actual free-plan entitlements and measured resource usage before enabling continuous operation; this recipe does not establish allowance fit or availability.

The service accepts the existing worker flags. On a non-root development host, `--credentials` can select another private directory. SIGTERM invokes the worker's existing child-process teardown; interrupted work remains governed by the database lease/reclaim rules. Configuration errors exit `2`, runtime authorization/control-plane failures retain the worker's nonzero status, and bounded supervisor retries must stop and surface the failure. Never loop rejected refresh tokens indefinitely.

For a code rollback, retain the **latest** credential volume. Restoring an old token file is not a session rollback: it can contain an already-spent refresh token. Re-provision a rejected session through the administrator/project-owner process instead of enabling automatic bootstrap fallback.


### Runtime behaviour operators depend on

- **Lease, heartbeat, reclaim.** A claim takes a lease of 15–900 seconds (default 300) whose fencing token lives only in `private.factory_run_leases`. The worker heartbeats at each phase transition and then at least every 30 seconds — and at least every third of the lease — while the analysis child runs. The source download is a single unheartbeated window, so with a short lease and a slow repository the lease can expire mid-fetch and the attempt be reclaimed; size that lease against the importer's 12 MB archive limit and 25-second HTTP timeout rather than assuming the fetch is checkpointed. A worker that dies lets the lease expire; the next `claim_analysis_work` for that project runs the reclaim path first, marking the abandoned run `failed` with `error_code = 'lease_expired'`, deleting its lease, recording a `lease_expired` event and re-queueing or terminally failing the work item. Because reclaim happens inside the claim RPC, no scheduler, cron job or privileged process is needed — and equally, an abandoned run is only reclaimed once some worker next asks that project for work.
- **Concurrency.** Claiming uses `FOR UPDATE SKIP LOCKED`, so two workers receive different work items or nothing. They never share an attempt or a lease token.
- **Bounded retries.** `work_items.max_attempts` defaults to 2 (limit 5). A failed or reclaimed attempt returns the item to `queued` while attempts remain; exhaustion is an explicit terminal `failed` with `attempts = max_attempts`, the last attempt's actual cause in `work_items.error_code` and an `attempts_exhausted` event on the final run. Per-attempt causes stay on each `factory_runs.error_code`, so "why did it fail" and "it ran out of attempts" are both answerable. No row is left silently `running`. If the worker cannot even report its failure, the lease expiry path above still settles the item.
- **Cancellation and revocation stop analysis.** Cancellation and worker revocation delete the lease transactionally. Creator permission loss is rechecked at claim, heartbeat and completion/failure and terminally fences that work item. At the next checkpoint, publication is refused and the worker sends SIGTERM to the analysis process group. It waits up to five seconds for the leader, then sends SIGKILL to any remaining group members—even if the leader already exited. Remote CPU shutdown is bounded by the next checkpoint, not instantaneous.
- **Bounded runtime and crash cleanup.** Child waits are capped by the remaining `--max-run-seconds` budget; a result observed after the deadline is rejected as `analysis_timeout`, even if the child exits before the next heartbeat. Blocking control-plane calls can still delay supervisor checkpoints; the child retains its independent deadline and original-worker-PID check. Normal teardown removes snapshots and remaining process-group helpers. After a hard worker kill, the next `--work-root` startup sweep removes marked directories whose owning process is gone; without a configured work root there is no startup sweep.
- **Supervision.** Heartbeat transport failures retry at most three extra times within the lease margin. Continuous mode exits immediately on authority loss and after five consecutive control-loop failures. A supervisor must surface this exit, not silently restart rejected credentials forever. Abandoned attempts settle when another authorized worker claims after lease expiry.

### Local versus production limits

The production Supabase schema and Vercel UI have been verified with a one-off local analysis worker, in addition to the isolated local/CI checks. No always-on cloud worker is configured and there is no availability promise. The worker requires outbound access to Supabase and GitHub, with no inbound port. Its credential-free analyzer process reads imported source but does not execute it; this is not a hardened per-tenant sandbox.

## Observability

Structured logs (request ID, tenant ID, task ID, repository, harness/model version); OpenTelemetry spans across API/queue/worker; CPU/memory/token cost; artifact refs; benchmark precision; explicit user-visible degradation; secrets redaction and retention rules.

## Approval and audit

Record the user, permission, precise proposed commit/change, risk classification, evidence, policy version, approval timestamp and release target. Separate approval of a task plan from approval of a production deployment. Provide cancellation, revert instructions and recovery.

## Incidents / playbooks

Worker offline: mark degraded, avoid double execution, preserve jobs and resume with lease checks.
Control DB unavailable: reject writes clearly; do not "succeed" without persistence.
OAuth/GitHub unavailable: show actionable error; do not bypass authorization.
Compromised credentials: revoke/rotate tokens, invalidate sessions, inspect logs and notify affected users.
Deployment failure: stop promotion, restore previous release/backup and preserve evidence.
Quota exhausted: queue/pause gracefully; never charge users or switch to paid models silently.
Cross-tenant isolation failure: disable affected pathway and investigate before re-enabling.

## Backup/recovery

Encrypted backups for SQL and artifacts, regular restore drills, schema migration rollback and retention/deletion controls. Define RPO/RTO and escalation before enterprise clients.

## Current limitation

The production collaboration and durable-analysis control plane are deployed. A temporary local worker proved the real execution path, but continuous worker hosting, an operated incident system and availability/recovery guarantees remain roadmap gates.

## Project on-call mode — planned product capability

On-call is a mode on a project, whether it originated in Start New or Evolve. Web, mobile and Slack operate the same incident and investigation session. It is not a separate bot with separate permissions.

For Start New, offer reviewed instrumentation, structured logs, service/release identity and health checks as part of the generated application. For Evolve, connect existing sources and identify instrumentation gaps; add instrumentation through a reviewed change rather than silently modifying production.

### Signal to verified fix

1. An authorized connector receives a bug report/alert or queries a bounded log, metric or trace window. Resolve tenant/project/source scope from the registered integration, never from an untrusted payload alone.
2. Verify authenticity and size limits, normalize metadata and durably record a receipt. Acknowledge webhook delivery promptly; expensive investigation runs asynchronously.
3. Deduplicate exact delivery IDs separately from incident correlation. Preserve individual occurrences while linking them to a canonical incident.
4. Correlate using service/resource, environment, release, trace/span and error fingerprint. Similar wording or nearby timestamps alone are hypotheses, not proof that two incidents are identical. Missing telemetry is reported as missing.
5. Atomically create or attach a restricted investigation session and work item. Replayed delivery, parallel workers and alert storms must not create one agent/session per notification.
6. Query only policy-approved read-only sources; build a cited timeline, hypotheses, affected scope and confidence/unknowns. Link existing bug reports rather than filing duplicates.
7. When evidence supports a code fix, use the existing Evolve engine in an isolated workspace. Pin the deployed source revision and account for differences from the target branch. Reproduce the fault and run protected regression checks.
8. Publish a reviewed fix/PR or a separately authorized runbook proposal. Telemetry credentials never grant production mutation or repository publication.
9. Release through the configured approval policy, then observe the relevant signals for a defined window. A passing test or merged PR is not by itself an operational resolution.
10. Record the outcome, update the incident/bug links and produce a scoped learning candidate. Reopen or escalate if signals remain unhealthy; do not start an unbounded repair loop.

### Connector and data contract

Use a small typed connector interface: receive/verify an event, query scoped evidence, return a bounded structured result, and report permission/rate-limit/unavailability explicitly. Start with the project's actual sources, not an unimplemented catalogue of every observability vendor.

Preserve event time and observed time, service/resource identity, environment, release/build reference, trace/span IDs where available, severity and source-specific event/fingerprint identifiers. OpenTelemetry's stable log data model provides a useful normalization baseline. Keep build/release-to-commit mapping so an investigation does not debug unrelated source.

Raw logs stay in their original system by default. Store bounded, redacted excerpts, source links/query windows and provenance in Oryveta. A separately approved forensic retention policy may retain encrypted raw material with a narrower audience. Do not persist credentials or unrestricted request bodies simply because an alert arrived.

Deduplication keys include the integration/tenant boundary. Correlation links have evidence and confidence; uncertain relations remain “possibly related.” Apply per-source/project concurrency, occurrence coalescing, cardinality, query-byte and time budgets. Retain a durable cursor/receipt and bounded retry/dead-letter path. One logical incident can have many occurrences and runs.

### Investigation session contents

The session shows severity, affected service/environment/release, linked reports, timeline, collected evidence, hypotheses versus confirmed findings, actual agent tasks, patch/test status and the next approval or escalation. Sources and actions remain inspectable. Private production data is not copied into a broader Slack channel; notifications link back to permission-checked content.

State distinguishes investigation, diagnosis, fix available, awaiting release, observing, resolved, false positive and blocked/escalated. Do not conflate “PR created,” “deployed,” and “service recovered.”

### Automation policy

- **Observe/investigate:** approved read-only sources may automatically open a session and investigate within a project policy and budget.
- **Prepare repair:** the agent may reproduce, edit, test and create a draft fix through a scoped repository grant. No production secrets enter the code sandbox.
- **Execute a runbook/release:** only a separately authorized action, resource set, environment, precondition and rollback policy may permit automated execution. Default production posture requires approval. High-risk/destructive migrations, permission changes, secret operations and new spending remain explicit human decisions.

Reading production logs never implies shell access, `kubectl exec`, SQL writes, restarts, deployment or arbitrary network access. A read-only prompt or command denylist is not the security boundary; use purpose-built read operations backed by genuinely least-privilege credentials.

Logs, stack traces, tickets, runbooks and repository instructions are untrusted input. They cannot override tool permissions, select another tenant, expand network access or alter the protected verifier. Production investigation and isolated code verification use different credentials and environments.

If the on-call service is itself failing, an external health signal and human escalation must remain available. A failed attempt to fix the factory must not recursively spawn unlimited attempts to fix its fixer.

### Required evidence before enabling unattended operation

- Real signal -> linked incident -> scoped session -> reproduced fault -> verified fix -> approved release -> observed outcome.
- Duplicate, delayed, out-of-order and replayed events produce one logical work item with preserved occurrences.
- Storm and quota tests demonstrate bounded sessions, queues, queries and model use.
- Correlation tests include true matches, near misses, multiple concurrent releases and missing identifiers; false merges are measured.
- Cross-tenant/source access, revoked grants, log/ticket prompt injection, secret/PII leakage and production-write attempts are denied.
- Worker crash, stale lease, expired credentials, provider rate limits and notification failures preserve truthful state and recover safely.
- Service recovery is checked after release; recurrent symptoms reopen/escalate rather than being hidden behind a successful PR.

### Research and reuse

[HolmesGPT](https://github.com/HolmesGPT/holmesgpt) provides useful investigation/connector patterns and Apache-2.0 code. Its configurable toolsets and optional mutation/PR paths are not an Oryveta tenant or read-only guarantee. Reuse reviewed connector shapes where helpful; do not inherit broad shell authority or adopt the whole product as a free backend.

[OpenTelemetry log records](https://opentelemetry.io/docs/specs/otel/logs/data-model/) support consistent timestamps, resource and trace context. [Sentry Seer RCA](https://docs.sentry.io/product/ai-in-sentry/seer/root-cause-analysis/) is a reference for combining issue, source and telemetry context, not a required/free runtime dependency. Provider query/retention/egress and model costs must be accounted for separately.

The on-call audience is explicit. A project viewer or session invitee does not automatically receive production-log access. Distinguish permission to read evidence, start investigations, prepare fixes, execute approved runbooks and approve releases. Automatically creating a session never grants the original reporter or the surrounding Slack channel access to confidential telemetry.
