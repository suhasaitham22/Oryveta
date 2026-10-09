# Deployment, hosting, cost and free-tier constraints

## Required operating behavior

The browser may close while an approved task continues. A lightweight cloud coordinator must persist status, authorizations, job leases and evidence. **True autonomous execution needs an online independent worker**, with explicit resource limits. No free provider guarantees limitless tasks, persistent GPU usage, or enterprise SLAs.

## Present deployment

- GitHub: https://github.com/suhasaitham22/Oryveta — public source repository (only preview, licensing and the docs have been uploaded so far).
- Vercel: https://oryveta.vercel.app — production alias assigned to an interactive **static frontend skeleton**. Vercel reported deployment READY; direct HTTP fetch was not independently verified from the connected tools.
- The public site intentionally has no real GitHub login, API, customer persistence, agent workers or automatic repository changes.
- Local MVP: Python/FastAPI + SQLite, standalone worker, basic tests, not deployed as a cloud service.

## Target architecture, not a committed vendor lock-in

**Cloudflare** Workers/Hono + D1 + Queues/Cron as free-tier control-plane candidate; suitable for metadata and brief API calls, not continuous GPU/CPU-heavy coding agents.

**Remote worker** initially a bring-your-own server/VM with Rust/Tokio supervisor (planned), sandboxed code execution and Python research/ML processes. Oracle Always Free may help experimental workloads but has eligibility/capacity/reclamation constraints and no guaranteed availability.

**Self-hosted alternative:** single-host SQLite and worker; PostgreSQL adapter for large consultancies. Object storage/isolated disk for datasets, model weights, source snapshots and large logs. Users should own their infrastructure when scale exceeds free-tier quotas.

**Supabase:** an optional PostgreSQL, storage and possibly auth provider if deliberately chosen. Not used for Oryveta yet. Supabase Free projects may pause after inactivity; no implied 24/7 guarantee.

**Vercel:** acceptable for static public preview and approved usage, but Vercel Hobby has restrictions for commercial work; consultancies should verify plan entitlement or choose another permissible hosting option. Vercel functions are not a substitute for unlimited long-running sandbox workers. Project can be moved to Cloudflare, self-hosted or appropriately licensed commercial infrastructure later.

## Expected service-to-service flow

UI → authenticated API → central SQL metadata → durable jobs/queues → remote worker lease → isolated sandbox → Python/Rust tool execution → verifier → artifact store + audit receipt → progress API/notifications.

## $0 software vs $0 infrastructure

Apache-2.0 source and open-weight model support have **no Oryveta license cost**. Compute, domains, paid model inference, storage, logs, egress and CI minutes can cost money. Protect users with per-project budgets, rate limits, queueing, resource caps and explicit opt-in before paid resources.

## Environment stages

Local demo → public UI preview → private integration preview with real OAuth/database → remote worker sandbox test → production pilot with reviewed security, backups and rollback. A READY deployment is not proof a multi-tenant SaaS is production safe.
