# Deployment, hosting, cost and free-tier constraints

## Required operating behavior

The browser may close while an approved task continues. A lightweight cloud coordinator must persist status, authorizations, job leases and evidence — that coordinator is deployed (Supabase durable analysis control plane). **Continuous autonomous execution still needs an online independent worker**, with explicit resource limits, and no such worker is hosted. No free provider guarantees limitless tasks, persistent GPU usage, or enterprise SLAs.

## Present deployment

- GitHub: https://github.com/suhasaitham22/Oryveta — public Apache-2.0 source repository.
- Vercel: https://oryveta.vercel.app — production alias serving the React Studio browser client built from `apps/web/studio`. It is a browser client with real Supabase identity and persistence, not a static marketing skeleton and not an execution host.
- Hosted and working: Supabase GitHub/email sign-in, workspaces, saved project briefs, project roles/invitations, private conversations, and the durable analysis control plane (work items, leases, bounded attempts, checkpoints, cancellation, pinned sources). Current public routes are `/`, `/about`, `/what-we-do`, `/pricing` and `/sign-in`, with `/workspace/*` behind sign-in. The build also serves the two static synthetic evidence files `repair-example.json` and `repair-example.patch`.
- **Not hosted:** any always-on cloud worker, model inference, code execution, repository writes or automatic repository changes. Production analysis has only ever been completed by a separately authenticated **one-off local worker**; see [STATUS.md](STATUS.md).
- Local/self-hosted only: the Python/FastAPI + SQLite engine with its own identity and worker, the optional local Ollama gateway, and the operator-run local repair/reverification CLI. None of these is deployed as a cloud service, and the hosted site does not call them.

## Target architecture, not a committed vendor lock-in

**Static hosting / integration ingress:** retain the current Vercel GitHub integration within its applicable terms. Cloudflare is a candidate for compliant free static hosting and bounded integration endpoints. It is **not** a reason to duplicate identity or application data in D1, or to run long coding jobs in request handlers: Supabase PostgreSQL is the single hosted authority for identity, grants, durable work and evidence metadata, and D1 is not part of the selected path. See [DATABASE.md](DATABASE.md).

**Remote worker:** a supervised Python service on authorized, continuously available compute, with disposable isolated execution and local model access. No free VM allowance guarantees capacity or uptime; do not depend on promotional credits or idle-resource reclamation exceptions.

**Data:** Supabase Auth/PostgreSQL is the hosted collaboration and durable-work authority; a self-hosted deployment is an alternative with operator-owned maintenance/backups. SQLite remains the **local** FastAPI engine's store for a separate local identity — it is not a second hosted authority and the two identities are deliberately not bridged. The local repair/reverification CLI persists neither: its receipts, traces, patches and candidate archives are private operator-owned files outside both databases. Keep large datasets, models, source and logs in permission-scoped artifact storage, not a duplicate metadata database.

**Free-service limits:** Supabase Free projects may pause and impose capacity quotas. An authenticated account, a deployed control plane and a reachable site are not proof of worker uptime or unlimited execution capacity. The capacity-limited free hosted preview in [PRICING.md](PRICING.md) is not forever-free hosting.

**Vercel:** acceptable for the public preview within approved usage, but Vercel Hobby has restrictions for commercial work. **Commercial hosting eligibility must be settled before any commercial use** — running a free pilot for another organization is not automatically non-commercial. Verify plan entitlement or choose another permissible hosting option; no payment method or paid plan is authorized today. Vercel functions are not a substitute for long-running sandbox workers. The project can move to Cloudflare, self-hosted or appropriately licensed commercial infrastructure later.

## Expected service-to-service flow

Target: web/mobile/Slack → shared authenticated operations → PostgreSQL work and grants → scoped Python worker lease → isolated tool execution → independent verifier → artifacts and audit receipts → permission-checked progress/notifications.

Today the first three hops are deployed; the worker lease is exercised only by an operator-started local process, and isolated tool execution plus independent verification exist only in the separate operator-run local CLI documented in [IMPLEMENTATION.md](IMPLEMENTATION.md#local-verified-repair-cli). Those two halves are not connected.

## $0 software vs $0 infrastructure

Apache-2.0 source and open-weight model support have **no Oryveta license cost**. Compute, domains, paid model inference, storage, logs, egress and CI minutes can cost money. The local repair and reverification CLI needs the operator's own CPU/RAM/disk, model weights and Docker host; Oryveta provides none of that and bills nothing for it. Protect users with per-project budgets, rate limits, queueing, resource caps and explicit opt-in before paid resources. No paid resource, card or inference key is authorized in the current state, and no availability or compliance guarantee is offered.

## Environment stages

Local demo → public UI preview → private integration preview with real OAuth/database → remote worker sandbox test → production pilot with reviewed security, backups and rollback. The hosted control plane is at the third stage; the remote worker sandbox stage is not started. A READY deployment is not proof a multi-tenant SaaS is production safe.
