# Deployment, hosting, cost and free-tier constraints

## Required operating behavior

The browser may close while an approved task continues. A lightweight cloud coordinator must persist status, authorizations, job leases and evidence. **True autonomous execution needs an online independent worker**, with explicit resource limits. No free provider guarantees limitless tasks, persistent GPU usage, or enterprise SLAs.

## Present deployment

- GitHub: https://github.com/suhasaitham22/Oryveta — public source repository (only preview, licensing and the docs have been uploaded so far).
- Vercel: https://oryveta.vercel.app — production alias assigned to an interactive **static frontend skeleton**. Vercel reported deployment READY; direct HTTP fetch was not independently verified from the connected tools.
- The public site intentionally has no real GitHub login, API, customer persistence, agent workers or automatic repository changes.
- Local MVP: Python/FastAPI + SQLite, standalone worker, basic tests, not deployed as a cloud service.

## Target architecture, not a committed vendor lock-in

**Static hosting / integration ingress:** retain the current Vercel GitHub preview integration within its applicable terms. Cloudflare is a candidate for compliant free static hosting and bounded integration endpoints, not a reason to duplicate identity/data in D1 or to run long coding jobs in request handlers.

**Remote worker:** a supervised Python service on authorized, continuously available compute, with disposable isolated execution and local model access. No free VM allowance guarantees capacity or uptime; do not depend on promotional credits or idle-resource reclamation exceptions.

**Data:** Supabase Auth/PostgreSQL is the hosted collaboration authority; a self-hosted deployment is an alternative with operator-owned maintenance/backups. SQLite remains the local engine's store. Keep large datasets, models, source and logs in permission-scoped artifact storage, not a duplicate metadata database.

**Free-service limits:** Supabase Free projects may pause and impose capacity quotas. An authenticated account and a reachable static site are not proof of worker uptime or unlimited execution capacity.

**Vercel:** acceptable for static public preview and approved usage, but Vercel Hobby has restrictions for commercial work; consultancies should verify plan entitlement or choose another permissible hosting option. Vercel functions are not a substitute for unlimited long-running sandbox workers. Project can be moved to Cloudflare, self-hosted or appropriately licensed commercial infrastructure later.

## Expected service-to-service flow

Web/mobile/Slack → shared authenticated operations → PostgreSQL work and grants → scoped Python worker lease → isolated tool execution → independent verifier → artifacts and audit receipts → permission-checked progress/notifications.

## $0 software vs $0 infrastructure

Apache-2.0 source and open-weight model support have **no Oryveta license cost**. Compute, domains, paid model inference, storage, logs, egress and CI minutes can cost money. Protect users with per-project budgets, rate limits, queueing, resource caps and explicit opt-in before paid resources.

## Environment stages

Local demo → public UI preview → private integration preview with real OAuth/database → remote worker sandbox test → production pilot with reviewed security, backups and rollback. A READY deployment is not proof a multi-tenant SaaS is production safe.
