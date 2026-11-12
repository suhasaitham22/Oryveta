# Databases, artifacts and data isolation

## Decision

**PostgreSQL (Supabase) for hosted collaboration and durable work; SQLite for the local engine; private operator-owned files for local repair evidence.** Separate high-value identity/workspace/project/run metadata from high-volume trajectories, code, artifacts and datasets. Do not add a second hosted database or duplicate identity authority without a concrete requirement. **D1 is explicitly not part of this path** — it is listed below only as a reference for why the choice was rejected, not as a component.

The existing stores remain distinct; Reviewed Evolve additionally uses private object storage:

| Store | Authority over | Not used for |
| --- | --- | --- |
| Supabase Auth + PostgreSQL (hosted, deployed) | Hosted identity, workspaces, projects, grants, private conversations, durable work items/runs/leases/events | The local engine's identity; any repair-CLI evidence; large blobs |
| SQLite (local self-hosted engine) | A **separate** local identity, local projects, analyses, jobs and events on one host | Hosted identity, multi-host writes, shared network filesystems |
| Private filesystem (local repair/reverification CLI) | Operator-owned configuration, source/candidate archives, receipts, traces, patches and results | No automatic publication, queue submission or web serving; sanitized public samples are separate reviewed build assets |
| Private Supabase Storage (`evolve-artifacts`, source extension) | Registered candidate/patch bytes and sanitized manifests, authorized through project/run metadata | Worker credentials, resolved private checks, public artifact URLs |

The hosted Supabase identity and the local FastAPI/SQLite identity are deliberately distinct and are not bridged: a hosted session is never forwarded into the local engine, and a cloud project is not an executed local project.

## Current local state

The local FastAPI engine uses SQLite for users, sessions, OAuth state, projects, analyses, jobs and events; its worker uses leases and bounded retries. SQLite WAL is not a multi-host shared-network-filesystem store. Hosted React collaboration instead uses the configured Supabase Auth/PostgreSQL project once its migrations are applied.

## Hosted control-plane DB (deployed)

Supabase Auth and PostgreSQL are the selected hosted collaboration boundary, and this is no longer only a target: the migrations are applied to the production project. Existing workspace/chat tables are extended by `projects`, `project_memberships`, `project_invitations` and `project_audit_events`. RLS filters reads; narrow RPCs own project writes and grant changes. Durable work, runs, worker leases and run events live in this same authority rather than in a second queue, broker or D1 database; approvals and evidence metadata belong there too. What is deployed is the **control plane**, not a runtime: rows describing work exist, but no hosted process executes it.

`supabase/migrations/durable_factory_runtime.sql` adds `work_items` (accepted work with its frozen source identity, input digest, attempt counters and cancellation record), `factory_runs` (one attempt each, with phase, checkpoint, resolved snapshot identity, bounded result and lease expiry), `factory_run_events` (append-only typed log, capped at 200 rows per run) and `project_workers` (per-project worker registrations). The fencing token is deliberately not among them: it lives in `private.factory_run_leases`, an unexposed schema on which `anon` and `authenticated` hold no privilege, so a user-facing read of a run cannot return a live lease. On the four public tables `authenticated` holds SELECT only, and all mutation is through the migration's SECURITY DEFINER RPCs. Every text column is an identifier, a short enumerated code or a bounded derived detail, and the two JSONB columns are structurally validated, so there is no free-text column into which a credential or host filesystem path could be written.

Apply `retained_attribution_and_lease_clock.sql` after that runtime migration. Accepted project invitations/chat shares and cancelled work retain their state and timestamps when an attribution account is deleted; the actor foreign key may become null, but grants still require a matching live actor. Lease deadlines, expiry checks and reclaim decisions use `clock_timestamp()` after relevant locks. Event/audit timestamps retain transaction-time semantics. Workspace deletion with run history remains a supported cascade, while deleting a referenced worker registration on its own remains forbidden.

`reviewed_evolve_runtime.sql` extends the same authority with kind `evolve`, operator-config pinning, human decisions, `evolve_stages`, `evolve_artifacts` and `evolve_lessons`. It does not create a second queue or identity. Apply it only after the preceding migrations and with Storage enabled; this extension is source, not a production migration claim.

Stage records are immutable and source/configuration-bound. Artifacts are registered only after an authorized worker uploads their bytes into the insert-only private bucket. Objects without a registration are unreadable. Human decisions name the exact latest run and candidate digest and re-check project, creator and worker authority.

Lessons carry project, source/configuration digests, origin and revocation state. Only human-activated successful-run lessons are eligible for exact-scope retrieval. Failure-report lessons are constrained to rejected/revoked states. Raw stage/failure evidence is available to authorized project readers but is not approved memory. A terminal diagnostic report cannot be converted back into normal stage progression.

## Per-worker state

Disposable workers keep temporary source and execution files locally; authoritative checkpoints, run state and evidence metadata must survive the runner. Keep repositories, datasets, model weights, screenshots and large logs in permission-scoped filesystem/object storage. A Rust rewrite is not part of the selected implementation path.

The durable analysis worker follows that split: each attempt's GitHub snapshot is extracted into a disposable per-run directory on the worker's own disk and deleted when the attempt ends, successfully or not. Nothing of a crashed attempt's working directory is recovered; what survives is the work item, the run row, its checkpoint and its recorded snapshot identity.

The local repair/reverification CLI deliberately does **not** follow that split, because it has no control plane to report to. Its disposable workspace lives under an operator-owned `0700` run root and is removed on normal completion, cancellation or ordinary failure; a hard kill can leave it behind. Its durable output is a new private `0700` evidence directory per run, never an existing one. That directory retains the resolved configuration, the original source archive, any candidate archive, the checkpointed receipt, the ordered JSONL trace, baseline and verification results, and the patch. **It contains real source, prompts, model output and the operator's private expected values, so it must be treated as confidential and retained or deleted under the operator's own policy.** No raw evidence file is automatically published, indexed, served or referenced by either database, and no hash in it authenticates its producer. Publishing anything derived from a run is a separate, deliberate act: the public `repair-example.json`/`repair-example.patch` assets were extracted and sanitized by hand from one historical run, and that is the only path by which run-derived material has ever become public.

## When to choose PostgreSQL / Supabase

The dedicated Oryveta project is configured in the public client defaults. Base workspace/private-chat schemas and the project-membership migration are in `supabase/`; apply them in the documented prerequisite order. Exposed tables require explicit grants plus tested RLS, appropriate indexes and backup/restore procedures. Free-project pausing/quotas cannot support an unconditional uptime promise.

## Auth/storage rules

Do not duplicate conflicting session systems unintentionally (Better Auth vs Supabase Auth). Never send service-role keys to browsers. Separate customer project data and model memory by tenant, with retention, consent and deletion rules. Local repair evidence has no tenant model at all: its only boundary is operator file ownership and `0700` permissions on the host, so one operator's evidence must never be placed on shared storage with other tenants' work.

## Recovery

Encrypt backups; test restorations; keep schema migrations in Git; define recovery-point/recovery-time objectives for real customer use. Cryptographic hashes verify artifact integrity, not software correctness. This repository establishes **no** backup, restore-drill, recovery-objective or availability evidence — whatever a given deployment's provider or operator may do independently, none of it is documented, exercised or committed to here, so no such claim may be made on Oryveta's behalf.

Sources: https://sqlite.org/wal.html ; https://supabase.com/docs/guides/deployment/going-into-prod ; https://developers.cloudflare.com/d1/ (reference for the rejected D1 option, not a component of this system)
