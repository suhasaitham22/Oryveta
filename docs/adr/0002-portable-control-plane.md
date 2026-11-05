# ADR 0002: Portable local MVP and cloud control plane

Status: **Direction accepted; auth/collaboration implemented, factory execution pending**. Updated: 2026-10-22.

## Context

Oryveta should work when browsers close and be self-hostable without mandatory commercial licenses. Hosted $0 infrastructure has meaningful compute/storage limits.

## Decision

Retain the Python/FastAPI + SQLite local engine and independent worker. Hosted collaboration uses Supabase Auth and PostgreSQL RLS; future durable factory metadata extends that same authority. Extend the Python worker with scoped tools, disposable execution and verification instead of requiring Hono, D1 or a Rust rewrite. Web, mobile and Slack share one authorization/work-item contract. Hosting and inference providers remain replaceable; actual availability depends on the chosen deployment.

## Consequences

Users can bring their own compute and inference. Maintain explicit protocol, migration and test boundaries; 24/7 production use depends on real worker availability and provider quotas. Add another service or runtime only for a measured requirement. A local test, hosted frontend and operated factory are distinct deliverables.

## Update 2026-11-04 — status superseded; decision unchanged

The 2026-10-22 status line above ("auth/collaboration implemented, factory execution pending") is superseded and preserved for history. Current status: **direction accepted; auth/collaboration and the durable analysis control plane are deployed; hosted execution still pending.**

What changed since that date, without changing the decision:

- The durable work/run/lease/event authority is applied to the production Supabase project, and a real repository analysis completed through the deployed UI using an operator-started one-off local worker. No always-on worker is hosted, so "factory execution pending" remains true for *hosted continuous* execution specifically.
- Scoped tools, disposable execution and controller-owned verification now exist as an operator-run local CLI, which additionally re-verifies a supplied candidate archive with no model contact. This is the Python-extension path this ADR chose, exercised locally — it is not the hosted runtime, has no queue or lease, and reports to no control plane.
- Hono, D1 and a Rust rewrite remain rejected; nothing has been added that would revisit that. Supabase PostgreSQL is still the single hosted authority, with the local SQLite engine's identity deliberately separate.

The ADR consequence that "a local test, hosted frontend and operated factory are distinct deliverables" is the reason this update changes the status rather than the decision.
