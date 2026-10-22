# Databases, artifacts and data isolation

## Decision

**PostgreSQL for hosted collaboration; SQLite for the local engine.** Separate high-value identity/workspace/project/run metadata from high-volume trajectories, code, artifacts and datasets. Do not add a second hosted database or duplicate identity authority without a concrete requirement.

## Current local state

The local FastAPI engine uses SQLite for users, sessions, OAuth state, projects, analyses, jobs and events; its worker uses leases and bounded retries. SQLite WAL is not a multi-host shared-network-filesystem store. Hosted React collaboration instead uses the configured Supabase Auth/PostgreSQL project once its migrations are applied.

## Target hosted control-plane DB

Supabase Auth and PostgreSQL are the selected hosted collaboration boundary. Existing workspace/chat tables are extended by `projects`, `project_memberships`, `project_invitations` and `project_audit_events`. RLS filters reads; narrow RPCs own project writes and grant changes. Future durable work, approvals, worker leases and evidence metadata belong in this same authority rather than being split into D1 by default.

## Per-worker state

Disposable workers keep temporary source and execution files locally; authoritative checkpoints, run state and evidence metadata must survive the runner. Keep repositories, datasets, model weights, screenshots and large logs in permission-scoped filesystem/object storage. A Rust rewrite is not part of the selected implementation path.

## When to choose PostgreSQL / Supabase

The dedicated Oryveta project is configured in the public client defaults. Base workspace/private-chat schemas and the project-membership migration are in `supabase/`; apply them in the documented prerequisite order. Exposed tables require explicit grants plus tested RLS, appropriate indexes and backup/restore procedures. Free-project pausing/quotas cannot support an unconditional uptime promise.

## Auth/storage rules

Do not duplicate conflicting session systems unintentionally (Better Auth vs Supabase Auth). Never send service-role keys to browsers. Separate customer project data and model memory by tenant, with retention, consent and deletion rules.

## Recovery

Encrypt backups; test restorations; keep schema migrations in Git; define recovery-point/recovery-time objectives for real customer use. Cryptographic hashes verify artifact integrity, not software correctness.

Sources: https://sqlite.org/wal.html ; https://developers.cloudflare.com/d1/ ; https://supabase.com/docs/guides/deployment/going-into-prod
