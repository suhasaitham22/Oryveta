# Databases, artifacts and data isolation

## Decision

**SQLite-first** as an open, portable baseline. Separate high-value identity/workspace/task metadata from high-volume agent trajectories, code, benchmark artifacts and training datasets. Avoid introducing unnecessary databases before evidence demands them.

## Current local state

The local FastAPI MVP uses SQLite for users, sessions, OAuth state, projects, project analyses, jobs and events; background jobs use leases and bounded retries. SQLite WAL supports multiple readers but a single writer and is not suited to multi-host shared-network-filesystem state. Current public static preview has no database and stores no user projects.

## Target hosted control-plane DB

Cloudflare D1 + Drizzle was the initial free-tier control-plane proposal. **For the first hosted authentication/workspace milestone, Supabase Auth + PostgreSQL is the selected implementation** because a single managed identity and RLS boundary is simpler and auditable. Avoid splitting identity and workspace data across D1 and Supabase before evidence justifies it. Model tables: organizations, memberships, clients, engagements, projects, repository connections, specs, approvals, agent_jobs, job_attempts, leases, workers, audit_events, evidence_receipts and release outcomes. Each query must enforce authorization at its actual data boundary. D1 per-database and daily-operation quotas need validation at deployment time.

## Per-worker state

A separate SQLite file (via Rust SQLx if the Rust worker is built) for checkpoints, experiment trials, metrics, temporary context caches and retry history. Keep source repositories in isolated Git worktrees; datasets, model weights, screenshots, log streams and large outputs in tenant-scoped filesystem/object storage.

## When to choose PostgreSQL / Supabase

For multi-writer consultancies, complex queries or more substantial tenant operation, provide a PostgreSQL adapter. Supabase is selected for the hosted identity/workspace foundation; a dedicated Oryveta project is **not yet provisioned**. The reviewed schema lives at `supabase/schema.sql`. On Supabase, apply tested per-tenant Row Level Security to exposed tables, secure storage policies, appropriate indexes and a deliberate backup plan. Free Supabase projects may pause after inactivity, making them unsuitable for guaranteed always-on critical services without mitigation.

## Auth/storage rules

Do not duplicate conflicting session systems unintentionally (Better Auth vs Supabase Auth). Never send service-role keys to browsers. Separate customer project data and model memory by tenant, with retention, consent and deletion rules.

## Recovery

Encrypt backups; test restorations; keep schema migrations in Git; define recovery-point/recovery-time objectives for real customer use. Cryptographic hashes verify artifact integrity, not software correctness.

Sources: https://sqlite.org/wal.html ; https://developers.cloudflare.com/d1/ ; https://supabase.com/docs/guides/deployment/going-into-prod
