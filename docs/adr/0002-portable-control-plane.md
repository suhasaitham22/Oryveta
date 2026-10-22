# ADR 0002: Portable local MVP and cloud control plane

Status: **Direction accepted; auth/collaboration implemented, factory execution pending**. Updated: 2026-10-22.

## Context

Oryveta should work when browsers close and be self-hostable without mandatory commercial licenses. Hosted $0 infrastructure has meaningful compute/storage limits.

## Decision

Retain the Python/FastAPI + SQLite local engine and independent worker. Hosted collaboration uses Supabase Auth and PostgreSQL RLS; future durable factory metadata extends that same authority. Extend the Python worker with scoped tools, disposable execution and verification instead of requiring Hono, D1 or a Rust rewrite. Web, mobile and Slack share one authorization/work-item contract. Hosting and inference providers remain replaceable; actual availability depends on the chosen deployment.

## Consequences

Users can bring their own compute and inference. Maintain explicit protocol, migration and test boundaries; 24/7 production use depends on real worker availability and provider quotas. Add another service or runtime only for a measured requirement. A local test, hosted frontend and operated factory are distinct deliverables.
