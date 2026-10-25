# Databases, artifacts and data isolation

## Decision

**PostgreSQL for hosted collaboration; SQLite for the local engine.** Separate high-value identity/workspace/project/run metadata from high-volume trajectories, code, artifacts and datasets. Do not add a second hosted database or duplicate identity authority without a concrete requirement.

## Current local state

The local FastAPI engine uses SQLite for users, sessions, OAuth state, projects, analyses, jobs and events; its worker uses leases and bounded retries. SQLite WAL is not a multi-host shared-network-filesystem store. Hosted React collaboration instead uses the configured Supabase Auth/PostgreSQL project once its migrations are applied.

## Target hosted control-plane DB

Supabase Auth and PostgreSQL are the selected hosted collaboration boundary. Existing workspace/chat tables are extended by `projects`, `project_memberships`, `project_invitations` and `project_audit_events`. RLS filters reads; narrow RPCs own project writes and grant changes. Durable work, runs, worker leases and run events now live in this same authority rather than in a second queue, broker or D1 database; approvals and evidence metadata belong there too.

`supabase/migrations/durable_factory_runtime.sql` adds `work_items` (accepted work with its frozen source identity, input digest, attempt counters and cancellation record), `factory_runs` (one attempt each, with phase, checkpoint, resolved snapshot identity, bounded result and lease expiry), `factory_run_events` (append-only typed log, capped at 200 rows per run) and `project_workers` (per-project worker registrations). The fencing token is deliberately not among them: it lives in `private.factory_run_leases`, an unexposed schema on which `anon` and `authenticated` hold no privilege, so a user-facing read of a run cannot return a live lease. On the four public tables `authenticated` holds SELECT only, and all mutation is through the migration's SECURITY DEFINER RPCs. Every text column is an identifier, a short enumerated code or a bounded derived detail, and the two JSONB columns are structurally validated, so there is no free-text column into which a credential or host filesystem path could be written.

Apply `retained_attribution_and_lease_clock.sql` after that runtime migration. Accepted project invitations/chat shares and cancelled work retain their state and timestamps when an attribution account is deleted; the actor foreign key may become null, but grants still require a matching live actor. Lease deadlines, expiry checks and reclaim decisions use `clock_timestamp()` after relevant locks. Event/audit timestamps retain transaction-time semantics. Workspace deletion with run history remains a supported cascade, while deleting a referenced worker registration on its own remains forbidden.

## Per-worker state

Disposable workers keep temporary source and execution files locally; authoritative checkpoints, run state and evidence metadata must survive the runner. Keep repositories, datasets, model weights, screenshots and large logs in permission-scoped filesystem/object storage. A Rust rewrite is not part of the selected implementation path.

The durable analysis worker follows that split: each attempt's GitHub snapshot is extracted into a disposable per-run directory on the worker's own disk and deleted when the attempt ends, successfully or not. Nothing of a crashed attempt's working directory is recovered; what survives is the work item, the run row, its checkpoint and its recorded snapshot identity.

## When to choose PostgreSQL / Supabase

The dedicated Oryveta project is configured in the public client defaults. Base workspace/private-chat schemas and the project-membership migration are in `supabase/`; apply them in the documented prerequisite order. Exposed tables require explicit grants plus tested RLS, appropriate indexes and backup/restore procedures. Free-project pausing/quotas cannot support an unconditional uptime promise.

## Auth/storage rules

Do not duplicate conflicting session systems unintentionally (Better Auth vs Supabase Auth). Never send service-role keys to browsers. Separate customer project data and model memory by tenant, with retention, consent and deletion rules.

## Recovery

Encrypt backups; test restorations; keep schema migrations in Git; define recovery-point/recovery-time objectives for real customer use. Cryptographic hashes verify artifact integrity, not software correctness.

Sources: https://sqlite.org/wal.html ; https://developers.cloudflare.com/d1/ ; https://supabase.com/docs/guides/deployment/going-into-prod
