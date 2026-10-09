# ADR 0002: Portable local MVP and cloud control plane

Status: **Direction accepted, implementation pending**. Date: 2026-10-09.

## Context

Oryveta should work when browsers close and be self-hostable without mandatory commercial licenses. Hosted $0 infrastructure has meaningful compute/storage limits.

## Decision

Begin with a portable, inspectable Python/FastAPI + SQLite MVP and independent worker. Publish a static UI preview; do not conflate it with a hosted API. Proposed production control plane uses Cloudflare Workers/Hono, D1/Drizzle and durable coordination with replaceable adapters. Proposed supervisor uses Rust/Tokio and sandboxed Python processes. Allow local SQLite and PostgreSQL/Supabase adapters instead of tying users to one provider.

## Consequences

Users can bring their own compute, databases and inference. We must maintain explicit protocol, migration and test boundaries; 24/7 production use depends on real worker availability and provider quotas. Rust and Cloudflare choices remain subject to prototype evidence.
