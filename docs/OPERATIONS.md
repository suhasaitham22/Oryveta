# Reliability, delivery pipeline and operational practices

## CI gates

Required checks before considering a production release: formatting, lint, static types, deterministic tests, integration/e2e acceptance, dependency/security scanning, isolation tests, license audits, migration rehearsal and deploy smoke test. GitHub Actions must use scoped permissions and pinned reviewed actions; prevent unreviewed PRs from exposing secrets.

The initial public preview has a dedicated workflow in .github/workflows/preview-checks.yml. Status and complete code coverage must be verified from actual GitHub Actions runs; do not infer that Vercel deploy success means CI success.

## Durable job state

Target lifecycle: New → Queued → Leased → Running → Verifying → Awaiting Approval → Completed/Failed/Canceled, with heartbeat, lease expiration, idempotency, retry counter and dead-letter records. Workers may crash/restart or lose network. Reconcile outputs and replay safe operations only; never blindly repeat deployments, emails or destructive data writes.

Implemented today, in three separate operating models that must never be described as one. The hosted **durable-analysis** path covers New/Queued/Leased/Running/Completed/Failed/Canceled with real heartbeats, lease fencing, bounded attempts and cancellation, and has no Verifying or Awaiting Approval state because it runs no checks. The hosted **controlled-repair** path adds real `repairing` and `verifying` phases and a terminal result that means *ready for review*, but the verifier is the operator's own host rather than a hosted one, and there is still no approval gate: nothing in the schema can approve, merge or deploy a candidate. The operator-run **local repair CLI** has verification but no queue, no lease and no approval state at all. Keep the three distinct when writing runbooks; a single "verified fix" sentence that spans them is wrong in at least one of them.

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

## Controlled durable repair operations

This covers the controlled design-partner repair path: `python -m oryveta_engine.coding_worker`, run by an operator on a host they own, serving exactly one approved `public.project_repair_policies` row. It is a third operating model, not a mode of either section around it.

| | Durable analysis | Controlled durable repair | Local repair CLI |
| --- | --- | --- | --- |
| Entry point | `factory_runtime`, or `factory_service` unattended | `coding_worker` | `coding_runtime` |
| Started by | `submit_repository_analysis` from the browser | `submit_repository_repair` from the browser | an operator's shell, nothing else |
| Queue, lease, attempts | yes | yes, the same tables | none |
| Executes repository code | no | yes, in local containers | yes, in local containers |
| Needs a model | no | a local Ollama endpoint | a local Ollama endpoint, except `--candidate-zip` |
| Needs Docker | no | a local daemon | a local daemon |
| Container hosting recipe | the image/Railway recipe above | **none** — a native process on an operator Linux host | none |

Flags, the credential format and the evidence layout are in [IMPLEMENTATION.md](IMPLEMENTATION.md#controlled-durable-repair-worker-operator-provisioned); the RPCs, read contracts and payload bounds are in [API.md](API.md#hosted-controlled-repair).

### Reviewed migration order

Apply, in this order: `supabase/schema.sql`, `supabase/migrations/private_chats_and_explicit_sharing.sql`, `projects_and_project_membership.sql`, `durable_factory_runtime.sql`, `retained_attribution_and_lease_clock.sql`, then `controlled_repair_runtime.sql`. A deployment already carrying the first five needs only the sixth. The repair migration is deliberately repeatable — every object is created `if not exists`, replaced in place, or dropped by name and re-added — and it re-owns three generated CHECK constraints so a second task kind can exist. The earlier initial-setup files are **not** repeatable, so never re-run them to "catch up". If a deployment still carries an analysis-era check constraint under some other name, the migration raises and names the constraint instead of silently leaving repair work unadmittable; drop that constraint by name and re-apply.

Until the repair migration is applied, the project panel shows a setup state and says an operator must apply it. That is the correct state to leave a deployment in; do not enroll a policy against a database that cannot admit the work.

### Worker identity, registration and policy enrollment

Three authorities act, in order, and none of them can substitute for another.

1. **An administrator designates a dedicated Auth identity.** Create a separate Supabase Auth user for this worker and set `app_metadata.oryveta_role = 'factory_worker'` through the Auth admin API. Use an identity dedicated to repair; do not reuse a working analysis worker's identity, because code-execution authority is what is being granted and the two grants should be revocable independently.
2. **A project owner or admin registers it for the project** with `register_project_worker(p_project_id, p_worker_user_id, p_label)`. This is the same registration the analysis worker uses and the same refusals apply: not the caller's own account, not an undesignated account, not a project or workspace member.
3. **A project owner or admin enrolls the repair policy** with `register_project_repair_policy(p_project_id, p_worker_user_id, p_label, p_source_commit, p_configuration_sha256)`. The label is 2–60 characters of `A-Z a-z 0-9`, space, `.`, `_` or `-`; the commit is 40 lowercase hex characters; the configuration digest is 64 lowercase hex characters. Neither hash is normalized or re-cased, because silently rewriting a transcription error would hide it. The frozen `source_url`/`source_owner`/`source_repo` are derived from the project's own saved source, never supplied by the caller, so an admin cannot point a policy at an unrelated repository.

Enrollment **installs nothing and grants no inference budget**. It records that an operator reviewed a configuration and designated a worker for one frozen snapshot. A policy binds one project, one worker identity, one public GitHub URL and commit, and one configuration digest, and all of those are immutable: a different commit, a different configuration or a different worker is a **new policy**, never an edit. A trigger enforces that on the table itself, so even a mistaken direct `UPDATE` by the table owner cannot redirect an approved policy. Only revocation, the cleared attribution of a deleted account and the worker's last-contact timestamp may change after enrollment. One enabled enrollment is permitted per project, worker, commit and configuration.

The panel's enrollment form takes only the worker identity, a label, the commit and the digest. There is no field for a command, a model, an image, a host path, a budget or a credential, and there must never be: those stay in the operator's local configuration file. Never paste configuration content or credentials into the browser.

An enrollment never outlives the two facts it was narrowed from. Both enrollment and every later submission re-derive the bound worker's standing, requiring an enabled `project_workers` registration **and** the current `factory_worker` designation, with the registration row held before the policy row so neither can race a revocation. If either has lapsed, submission is refused with an actionable message naming which one — no longer registered, no longer a provisioned worker service identity, or the account no longer exists — instead of queueing work that could never be claimed. Treat such a refusal as a signal to re-provision and enroll a new policy, not as a transient error to retry.

### Source commit and policy enrollment inputs

The approved source is one public GitHub `https://github.com/owner/repo` URL plus one 40-character lowercase commit SHA. Resolve the commit yourself from the public repository and review that exact snapshot before enrolling; the worker fetches only that commit and has no default-branch fallback, so a pin that the runtime could quietly ignore does not exist here. The project's saved source URL must still match the policy's frozen URL for a **new** submission to be admitted, which is what stops an authorized project edit from redirecting an enrolled policy's future work. Work already admitted keeps the source, pin, goal and configuration binding it was admitted under.

### Operator-reviewed configuration and its digest

The configuration is the reviewed JSON repair specification described in [IMPLEMENTATION.md](IMPLEMENTATION.md#operator-contract): commands, expected cases, file allowlists, the pinned local model and digest, the preloaded image ID, the Docker context and the budgets. Keep it operator-owned, outside any source archive, outside the repository and outside the browser.

`configuration_sha256` is **not** `sha256sum` of the file. It is the SHA-256 of the canonical JSON of the *resolved* specification, with defaults applied, which is what both the worker and the control plane compare. Derive it from the parser that will enforce it:

```bash
python -c 'import sys; from oryveta_engine.coding_config import load_spec; print(load_spec(sys.argv[1]).digest)' \
  /etc/oryveta/repair-configuration.json
```

Enroll that value. Reformatting the file, reordering keys or writing a default out explicitly leaves the digest unchanged; changing a command, a check, an allowlist, a limit, the model or the image changes it, and then the existing policy is simply no longer the one being run — enroll a new policy rather than editing the old one. The worker reads the file once at startup, parses those exact bytes, and prints the digest it froze; confirm it matches the enrolled policy before leaving the process running. A mid-flight edit of the file cannot become the authority for an attempt already under way, and a copy of the frozen bytes is placed in every private run directory.

### Host prerequisites

The repair worker runs as a **native Python process on a Linux host the operator controls**, with a local Docker daemon it can reach and a local Ollama endpoint on loopback. Provision the model weights and the trusted execution image explicitly; neither the capacity probe nor a repair ever pulls. `--work-root` must be a directory the local Docker daemon can see, because the disposable per-run tree is what the check containers mount.

Three things are specifically **not** supported, and claiming any of them would be false:

- **Do not route repair work to the Railway analysis container.** The `factory_service` image/Railway recipe above provisions the *analysis* worker: a credential-free reader with no Docker and no model. It is not a nested-Docker or inference deployment recipe, and the repair worker is not a mode of it.
- **Do not mount the Docker socket into that container**, or into any check container, to make it work. A socket mount hands the mounted process control of the host daemon, which is the opposite of the confinement the checks depend on. The repair worker talks to a daemon it owns, on a host it owns.
- **Do not advertise cloud deployment of this worker.** No cloud host is provisioned (see the limits below), so there is no deployment to advertise.

The only host this path has been exercised on is a local workstation whose Docker VM has 2 CPUs and 4 GB of memory on `arm64`, with Ollama serving the model from the host *outside* that VM. That is a functional exercise, not a throughput, memory-fit or model-performance measurement, and it is not evidence about any other machine's capability. Do not publish a performance figure derived from it.

### Starting the worker

Repair is opt-in and every input is explicit; there is no mode flag that turns an analysis worker into this. `--policy`, `--config`, `--source-url`, `--source-commit` and `--evidence-root` are all required, and the worker refuses to start if the policy row disagrees with any of them, is revoked or disabled, or designates another identity.

```bash
export ORYVETA_REPAIR_CREDENTIALS=/etc/oryveta/repair-worker-credentials.json
python -m oryveta_engine.coding_worker \
  --policy 00000000-0000-0000-0000-000000000000 \
  --config /etc/oryveta/repair-configuration.json \
  --source-url https://github.com/owner/repo \
  --source-commit 0000000000000000000000000000000000000000 \
  --evidence-root /var/lib/oryveta/repair-evidence \
  --work-root /var/lib/oryveta/repair-work
```

Startup, in order: load the credential file, take the credential directory's session lock, freeze the configuration, resolve the Docker executable, prepare the private evidence and work roots, build the sanitized Docker configuration copy, confirm the registration and the policy, sweep stale run directories, then observe local capacity. Only then does it poll. Each of those steps can refuse, and a refusal is the intended outcome when its precondition is missing — a worker that cannot confine or verify must not claim work it would have to abandon.

The capacity probe inspects the Docker context, the daemon and the immutable image, and confirms the pinned model is installed locally. It starts no container, pulls nothing and **spends no inference tokens**. It is re-observed at least every 120 seconds before a claim, and the registration and policy are re-read on the same cadence, so an owner's revocation stops a polling worker instead of leaving it asking a control plane that will refuse it forever.

There is no fallback: one local model, one local runner, one frozen configuration. If local capacity is missing the worker refuses to become ready rather than reaching for a paid or remote substitute.

### Private credentials, evidence and retention

- The worker holds **an ordinary Auth session and nothing more**. The service-role key never appears in its credential file and is never used by it. Its authority is that session plus one enabled `project_workers` row plus one enabled policy, re-checked on every call.
- Keep the credential file a non-symlink regular file with no group or world permission bits (`chmod 600`); the worker refuses to start otherwise. `ORYVETA_REPAIR_CREDENTIALS` is a reference to that path, not a place for the token.
- Refresh rotation is persisted through a `0600` temporary file, `fsync` and atomic replace. Give this worker its own independently issued session and its own credential **directory**: the session lock is held for the whole life of the process, so a repair worker and an analysis worker or service must never share one.
- `--evidence-root` is operator-owned and mode `0700`. Each attempt gets a fresh directory under it, namespaced by work item and then by run, attempt and a random suffix, and the worker refuses to reuse one. It retains the resolved configuration, the fetched `source.zip`, the checkpointed receipt, the ordered JSONL trace, baseline and verification results, the candidate archive, the diff, and an operator-only `worker-run.json` index naming the work item, run and attempt. No lease token and nothing client-visible is written into it.
- **Evidence is confidential.** It contains real source, the submitted goal, model prompts and output and the operator's private expected values. Keep it on storage not shared with other tenants' work. Nothing expires, nothing is uploaded, served or indexed, and no hash in it authenticates its producer against a malicious host. Decide retention and deletion deliberately and write that decision down; the control plane keeps only the bounded result and will not tell you when private evidence should go.
- The disposable `--work-root` tree — the snapshot, the config copy, the goal file, the child's result file and its stderr log — is removed when the attempt ends, successfully or not. A hard kill leaves it for the next startup sweep.
- A leaked repair worker credential is bounded but materially worse than a leaked analysis credential, because this identity's claims cause code execution on the operator's host. It still holds no admin or service-role authority, is not a project member, and cannot submit, cancel or enroll anything. Revoke the policy, revoke the registration, remove the `oryveta_role` designation, or all three, then re-provision.

### No secrets in the child, and only the approved Docker context

The supervised repair child is credential-free by construction. It receives a copy of the frozen configuration, the fetched source archive, a goal file, its own private evidence and run directories, a deadline, the worker's PID and the resolved absolute path of the Docker executable. It receives **no** Supabase credentials, no lease token, no project or policy identity, no `DOCKER_HOST`, no proxy variables and no inherited parent environment; its `HOME` is inside the disposable run tree, so the operator's home is never read or written.

The Docker executable must resolve to a runnable regular file owned by root or the operator and not writable by other accounts. For a named context, `--docker-config` (or `$DOCKER_CONFIG`) supplies its canonical, symlink-free `meta.json`, bounded to 1 MiB. The worker writes only that context's name and approved local Unix-socket endpoint into a fresh private directory. Other context metadata, TLS keys, `config.json` and registry credentials are never copied. The default context needs no operator configuration; a missing or non-local named context fails rather than falling back. No Docker socket or host credential is mounted into a check container.

### Continuous polling, bounded retries and fencing

- **Continuous by default.** The worker polls independently of any browser; a submitter can close the tab and the work still runs. `--poll-seconds` (default 5) is the idle delay between claims; `--once` serves at most one item and exits; `--max-runs` stops after a number of completed claims. "Always-on" here means a supervised process that polls on its own — not unlimited work and not an uptime guarantee.
- **Idle polls are authenticated contact.** A claim refreshes the policy's `last_seen_at` even when there is nothing to do, but only after every authorization check has passed.
- **Bounded attempts.** A repair work item is admitted with `max_attempts = 2`, fixed at admission. A failed attempt returns the item to `queued` while an attempt remains; exhaustion is an explicit terminal `failed` carrying the last attempt's actual cause, with each attempt's own cause on its run row. A retry re-fetches **the same approved commit** and recomputes from scratch; it never replays a model trajectory and never reuses a browser grant.
- **Terminal versus retryable.** A refusal of `worker_not_registered`, `policy_revoked`, `creator_unauthorized` or `wrong_kind` means this worker has lost the right to serve the policy, or the attempt was already settled by a fencing path; those are not retried as ordinary failures. Continuous mode exits at once on a credential the identity can no longer refresh and on a revoked or missing policy, and after five consecutive control-loop failures. A supervisor must surface that exit, not restart rejected credentials forever, and must not loop a refused refresh token.
- **Lease, heartbeat, fencing.** A claim takes a lease of 15–900 seconds (default 300) whose fencing token lives only in `private.factory_run_leases` and is readable at no privilege a client can hold. The worker heartbeats at each phase transition and then at least every third of the lease, capped at 30 seconds, for as long as the child waits on local inference and on the controller-owned checks. A heartbeat transport failure is retried up to three further times while the granted lease still has room, so a momentary outage does not spend an attempt. The source download remains a **single unheartbeated window**: with a short lease and a slow repository the lease can expire mid-fetch, so size the lease against the importer's archive limit and HTTP timeout rather than assuming the fetch is checkpointed.
- **Cancellation, revocation and lease loss stop the child.** `cancel_work_item`, `revoke_project_repair_policy`, `revoke_project_worker`, loss of the submitter's editing role, an expired lease and a stolen lease all produce an unambiguous `lease_valid = false` at the next heartbeat. The worker then sends SIGTERM to the child's whole process group, waits five seconds for the leader and sends SIGKILL to any remaining member even if the leader already exited — and it **publishes nothing**, even with a verified candidate already in hand. SIGTERM to the worker itself takes the same teardown path. Stopping remote CPU is bounded by the next heartbeat, not instantaneous.
- **Revocation settles work.** Revoking a policy disables it, fences its outstanding attempts, deletes their leases and settles the work terminally, returning the number of runs it fenced. It does not leave items queued against an identity that is no longer approved. Policies are never re-enabled; a renewed decision is a new policy.
- **Offboarding the worker account is a third, supported way to stop it.** A policy records the designated identity twice: a frozen `worker_identity` that is evidence only and carries no authority or foreign key, and a nullable live `worker_user_id` that every authorization check and read policy actually reads. Deleting the worker's Auth account clears the live reference, withdraws the enrollment and settles its unfinished work in the same statement with `error_code = 'worker_identity_deleted'`, so the deletion succeeds and the enrollment and repair history stay readable instead of being blocked by work items that still name the policy. A cleared live reference is a refusal everywhere, never a wildcard, and it is never restored: re-enroll a new, re-reviewed policy with a new identity rather than expecting the old row to come back. A worker process pointed at such a policy fails closed on its next authority check rather than continuing to poll.

### Restart and reclaim

A crashed repair is **recomputed, not resumed**. There is no in-memory resume, no restored checkpoint and no continued conversation. If the worker or its host disappears, the attempt is settled when its lease expires and the next authorized claim for that policy runs the reclaim path first; the work item, its frozen source and pin, its goal, its policy binding and the run's recorded checkpoint are what survive. Restarting the worker with the same policy, configuration, URL and commit is the whole recovery procedure — and if any of those four no longer matches the policy row, it refuses to start, which is the correct outcome.

Set `--work-root` explicitly so a restart can sweep the marked directories of dead attempts. With no `--work-root` the worker creates a temporary one that disappears with the process, so after a hard kill there is nothing left to sweep. Sweep manually and confirm no stray containers remain after an abnormal exit; SIGKILL cannot guarantee cleanup.

### Honest last contact, and what a result means

`project_repair_policies.last_seen_at` is the **last authenticated, authorized contact from the bound worker**. It is not capacity, not availability and not an uptime promise; no scheduling decision reads it, and the panel is deliberately worded so a recent poll reads as "a credential is polling", not "a worker is up". Do not build an availability indicator, an SLO or an alert threshold on it, and do not generate artificial keep-alive traffic to make it look better.

`succeeded` on a repair work item means exactly one thing: an attempt computed a candidate that passed the operator's own declared checks and is **ready for review**. It is not an approval, a merge, a deployment, a release or a remote attestation, and the UI says "Ready for review" rather than "fixed" for that reason. There is no automatic branch, PR or deploy anywhere in this path.

A downloaded patch therefore **needs independent human review before it goes anywhere**. The stored result carries the untruncated diff, the identities it was computed from and bounded counts; an over-limit patch is refused rather than truncated, and a metadata-only "completion" has no representation. `checks_passed` is the number of the operator's own declared cases that passed — not general correctness, not benchmark qualification and not permission to publish. The registered worker is a trusted producer: the payload validation bounds what it may persist and recomputes the patch hash on both sides, and that is all it does. Read the diff, re-derive the verdict independently if the change matters, and apply it through your normal review and release process. The private receipts, the full candidate archive and the check output stay on the operator's host and are not served by any endpoint.

### Limits that must be stated with this path

- **No cloud worker is provisioned.** There is no hosted repair worker, no always-on proof and no SLA, availability, recovery or support commitment. Every repair runs because an operator started and supervised a process on a host they own.
- **Zero incremental spend is authorized.** Inference is a local Ollama model and execution is a local Docker daemon. There is no paid model, no paid runner, no new plan and no automatic escalation to one; the worker refuses to become ready rather than substituting a paid service.
- **Free hosting capacity is a candidate, not a plan.** No account has been created and no machine provisioned for this worker. The conditional best candidate is Oracle Cloud Always Free, whose current published allowance for Ampere A1 is 1,500 OCPU hours plus 9,000 GB hours per month — up to 2 OCPUs and 12 GB of memory run continuously, not the older 4 OCPU / 24 GB figure — with 200 GB of combined boot and block volume storage in the home region. A1 capacity is explicitly not guaranteed and shortages are common, and idle Always Free compute may be **reclaimed after about seven days of idleness**. Idle reclamation alone makes "always-on" unpromisable on it, and working around reclamation with synthetic load is not an acceptable operating practice here. The hosted control plane's Supabase Free project pauses after a week of inactivity and has no automatic backups. The hosted Studio's Vercel Hobby plan is restricted to non-commercial personal use and a commercial entitlement has not been verified.
- **External accounts are an operator prerequisite.** Signing up for a host, accepting its terms, provisioning the VM, holding its credentials, and separately provisioning the Supabase Auth worker identity are all the operator's responsibility and are outside this repository. No entitlement, allowance, quota or term is claimed on any provider's behalf beyond what their own documentation states.
- **Local defense in depth, not certified isolation.** Check containers run with networking disabled, a non-root UID, dropped capabilities, no-new-privileges, a read-only root and source, and bounded tmpfs/memory/CPU/PIDs/output. Docker still shares a kernel and host administrators remain trusted. Use only operator-approved source and trusted images. This is not a hardened per-tenant sandbox or an isolation certification.
- **No incident path.** There is no alerting, on-call rotation, degraded-mode signalling or availability commitment for this worker, exactly as for the local CLI.

## Local repair and re-verification operations

This covers the operator-run `python -m oryveta_engine.coding_runtime` command, which **remains distinct and fully supported** alongside the durable path above. The durable repair worker supervises this same `coding_runtime` repair loop in a credential-free child, so the two share a verification contract — but this one is not a service: there is no daemon, no queue, no lease, no policy, no inbound port, no scheduled run, no supervisor and nothing to keep alive. It runs once, in a shell, on hardware the operator owns, and exits. It is also the only way to run the **model-free re-verification** mode, which the durable path does not expose. Exact flags, the configuration contract and artifact names are in [IMPLEMENTATION.md](IMPLEMENTATION.md#local-verified-repair-cli).

Operational rules that are easy to get wrong:

- **The configuration and the operator's access are the only authority.** Supply the reviewed current specification from a path outside the source archive, and an archive you are authorized to hold. A receipt from an earlier run grants nothing: it cannot re-authorize a source, re-establish a grant, vouch for the host or stand in for the configuration. Never re-run against a specification that has drifted from the reviewed one, and never treat an old receipt as evidence that today's inputs are approved.
- **Every run needs a new output directory.** The command refuses an existing path. Do not reuse, merge or overwrite an evidence directory, and do not point two runs at one destination.
- **Evidence is confidential.** The output directory holds real source, model prompts and outputs, and the operator's private expected values. Keep the run root and every output directory operator-owned and mode `0700`, on storage that is not shared with other tenants' work. Decide retention and deletion deliberately — nothing expires on its own, and nothing is uploaded, served or indexed.
- **Re-verification is a fresh run, not a resume.** It allocates a new run ID and reproduces the baseline and all declared final checks from scratch in fresh containers. It never restores a checkpoint, never continues an interrupted conversation, never re-issues a recorded tool result and never contacts a model — not even if a model is running locally. Do not describe it as resume, replay, approval, remote attestation or a hosted integration.
- **A supplied result claim is never trusted.** The candidate archive's own assertions, filenames, embedded reports or `passed` fields have no standing. The controller re-derives the verdict from execution it owns.
- **Interrupted work is restarted from inputs, not continued.** A hard-killed controller leaves its last checkpoint unfinalized, still reading `incomplete`. That is not a result and not a liveness signal — only `needs_review`, `rejected`, `failed` and `cancelled` are terminal execution statuses. A pending action may already have executed and its effects may be newer than the saved patch. Never automatically replay it. Treat a result as verified only on a terminal receipt with a matching verified-patch hash; an `unverified.patch` is evidence of a diff, not a verdict.
- **Old patch-only records cannot be re-verified.** A unified diff is not an archive. Runs that recorded only a patch need the original source archive and an equivalent candidate archive before they can be re-checked at all; without both, leave the historical record as it stands rather than implying it was re-confirmed.
- **Cleanup is not guaranteed under a hard kill.** SIGTERM, interrupt and ordinary failures clean the disposable workspace; SIGKILL can leave directories and, in bad cases, containers behind. Sweep the run root manually after an abnormal exit and confirm no stray containers remain.
- **Nothing here is an incident response path.** There is no alerting, no on-call rotation, no degraded-mode signalling and no availability commitment for this command.

## Observability

Structured logs (request ID, tenant ID, task ID, repository, harness/model version); OpenTelemetry spans across API/queue/worker; CPU/memory/token cost; artifact refs; benchmark precision; explicit user-visible degradation; secrets redaction and retention rules.

## Approval and audit

Record the user, permission, precise proposed commit/change, risk classification, evidence, policy version, approval timestamp and release target. Separate approval of a task plan from approval of a production deployment. Provide cancellation, revert instructions and recovery.

Security-advisor output is an observed audit record. Record actual findings and reviewed exceptions, including the authenticated-only RPC write boundary and provider-plan-limited password controls documented at rollout. Do not claim clean results without fresh evidence or weaken controls to clear warnings. See [AUTH-SECURITY.md](AUTH-SECURITY.md#release-gates).

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

The production collaboration and durable-analysis control plane are deployed. A temporary operator-started local worker proved the real analysis execution path. The controlled durable repair runtime — its migration, its policy-scoped worker and its project panel — exists in source and is operated exactly as described above, which means an operator-owned host and no hosted execution; continuous worker hosting, an operated incident system, backup/restore drills and availability/recovery guarantees remain roadmap gates for both task kinds. The local repair/re-verification CLI is an operator tool, not an operated service, and does not change that. No paid deployment, SLA or compliance commitment exists, and no incremental spend is authorized. The single dated current-state record is [STATUS.md](STATUS.md); this page documents how to operate what is there rather than restating its evidence.

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
