# Oryveta documentation hub

**Snapshot: 2026-11-08.** This is the main source of architectural intent and product decisions, and the complete hub: every active document is linked below. Oryveta is an open-source software delivery workspace being built into an AI software factory, entered through **Start New** or **Evolve**; see [VISION.md](VISION.md) for the audience and the available-versus-planned boundary. Always distinguish **current implementation** from **planned capabilities**.

**One goal, approached in order.** Verifiable maintenance changes to an existing codebase come first — a bounded repair that a reviewer can check — and the broader factory (custom application generation, hosted execution, repository publication, on-call, learning) follows, each stage gated on recorded evidence. Narrowing the entry point is sequencing, not a reduction of the goal.

**Three states, named separately everywhere.** *Production* is what https://oryveta.vercel.app serves: the hosted React Studio with real sign-in and saved project collaboration as a free preview, which is not an agent service and does not run Start New or Evolve work. *`main`* is the merged source behind it, and it now carries the evidence-led Home, the dedicated `/pricing` route, the downloadable synthetic repair example, the local CLI's durable interruption receipts and its model-free candidate re-verification. *The current review candidate* is the unmerged **controlled durable repair integration**: the repair migration, the policy-scoped `coding_worker`, and the project repair panel — source under review, not merged, not deployed and not customer results. Dated deployment and evidence state live only in [STATUS.md](STATUS.md).

**Model tooling exists, locally.** Three separate local, opt-in paths use a model today: the operator-run repair CLI in [IMPLEMENTATION.md](IMPLEMENTATION.md#local-verified-repair-cli), the policy-scoped durable repair worker in [IMPLEMENTATION.md](IMPLEMENTATION.md#controlled-durable-repair-worker-operator-provisioned), and the local Ollama adapter in [MODEL-GATEWAY.md](MODEL-GATEWAY.md). The CLI also runs **model-free re-verification** of a saved candidate archive (`--candidate-zip`), which contacts no model or inference endpoint at all, re-runs the operator's own declared checks in fresh local Docker containers and records `mode='verification'` with zero model calls and zero observed tokens. The durable worker adds a queue, a lease, bounded retries, fencing and a reviewable patch result to the same repair loop — but it runs on a Linux host an operator provisions and supervises, with a local Docker daemon and a local Ollama endpoint, so none of this is hosted inference and none of it is a cloud worker. What is absent is hosted model-driven coding and an always-on cloud worker — not model tooling itself.

## Product and design

| Document | Covers |
| --- | --- |
| [VISION.md](VISION.md) | Mission, audience, the problem being solved, research directions stated as hypotheses, success metrics |
| [PRODUCT.md](PRODUCT.md) | Start New and Evolve definitions, first maintenance cohort, consultancy scenarios, outcome contracts |
| [USER-JOURNEYS.md](USER-JOURNEYS.md) | Auth/onboarding, builds, Evolve patching, approvals, client handover, error states |
| [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md) | Off-white/cobalt Geist system with a dark workspace rail, the real public routes including `/pricing`, original graphics, the opt-in spatial viewer, accessibility and motion |
| [BRAND.md](BRAND.md) | Oryveta identity, voice, domain and naming history |
| [PRICING.md](PRICING.md) | The two published plans, the buyer hypothesis and the commercial proposal (also listed under governance) |
| [DEMO-STUDIO.md](DEMO-STUDIO.md) | Storyboard contract, the browser editor's export-only boundary and local captioned-storyboard rendering |

## Platform engineering

| Document | Covers |
| --- | --- |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Source layout, local setup, the two repair entry points and their operator contracts, test coverage and current security limitations |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Control/intelligence/execution planes, technology selections, current vs target stack, and which parts of the repair path report to the control plane |
| [STATE-MACHINES.md](STATE-MACHINES.md) | Complete lifecycle-family inventory, existing state authorities, implicit coordination, UX/DX/AX decision and regression boundaries |
| [ENTERPRISE-FOUNDATIONS.md](ENTERPRISE-FOUNDATIONS.md) | Enterprise AI invariants, task safety, quotas, evaluation gates and scale triggers |
| [DATABASE.md](DATABASE.md) | Local SQLite engine state, the deployed Supabase PostgreSQL control plane that owns durable work/runs/leases and repair policies, schema ownership, private evidence boundaries and recovery |
| [AUTH-SECURITY.md](AUTH-SECURITY.md) | GitHub OAuth vs GitHub App, roles, sandbox/prompt injection, approvals |
| [IDENTITY-WORKSPACES.md](IDENTITY-WORKSPACES.md) | Hosted sign-in, workspace onboarding, RLS boundaries, setup and launch gates |
| [API.md](API.md) | Local MVP versus planned API contracts, plus the hosted durable analysis and controlled repair RPC/read contracts and payload bounds |
| [AGENT-HARNESS.md](AGENT-HARNESS.md) | Context compiler, models, router, tools, worker, verified patch loop and Rust options |
| [MODEL-GATEWAY.md](MODEL-GATEWAY.md) | Opt-in local Ollama model adapter, strict request contract, owner-scoped daily token budget |
| [EVOLVE-PATCH-PREVIEW.md](EVOLVE-PATCH-PREVIEW.md) | Read-only patch proposal, bounded diffs, stale-source checks and review gates |
| [EVALUATION.md](EVALUATION.md) | Internal Arena, Kaggle, unbiased benchmarks, self-learning and hypothesis graph |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | GitHub, Vercel, Cloudflare, Supabase, remote 24/7 workers and free-tier constraints |
| [OPERATIONS.md](OPERATIONS.md) | CI/CD, observability, the three operating models and their runbooks, lease/recovery, incidents and backups |
| [QUALITY.md](QUALITY.md) | Enforced CI matrix, security scans, branch coverage, packaging and Docker smoke |

## Delivery and governance

| Document | Covers |
| --- | --- |
| [ROADMAP.md](ROADMAP.md) | Phases and objectively testable milestones |
| [STATUS.md](STATUS.md) | Live GitHub and Vercel status, current limitations and in-progress work |
| [PRICING.md](PRICING.md) | Pricing and launch plan: preview-versus-paid availability, preconditions before charging, effort allocation and evidence gates |
| [OPEN-SOURCE.md](OPEN-SOURCE.md) | Apache-2.0 licensing, contributor and commercial-use principles |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Tests, PR requirements, benchmark and security contribution standards |
| [DEPLOYMENT-PREVIEW.md](DEPLOYMENT-PREVIEW.md) | Hosted Vercel deployment of the React Studio, its build settings and what is not hosted |
| [AGENT-SKILLS.md](AGENT-SKILLS.md) | Repository-native agent skills, the review requirement before installing upstream packs |

Also active outside `docs/`: the [repository README](../README.md) is the entry overview, and [`preview/README.md`](../preview/README.md) documents the **historical static prototype** that is retained as an archive and must not be deployed.

## Architecture decision records

- [ADR 0001](adr/0001-two-product-journeys.md): two product journeys; Arena is internal.
- [ADR 0002](adr/0002-portable-control-plane.md): local-first MVP and portable cloud architecture.
- [ADR 0003](adr/0003-evidence-and-approval.md): evidence before claims, approval for risk.

## What is locked

Oryveta name; the current off-white/cobalt Geist visual direction with a dark workspace rail (the earlier olive/yellow treatment is retired); Home / About / What We Do / Pricing / Workspace as the public navigation; Start New + Evolve as the two journeys; Kaggle only for testing; Apache-2.0 open-source goal; evidence and permission requirements; $0 required software licensing with optional bring-your-own-compute. Two published plans only — Community, with $0 open-source software and a hosted workspace that is free during preview subject to documented capacity, and a proposed Team plan — with no hosted compute included in either. Apache-2.0 rights already granted are never retracted, which is not a promise of perpetual free hosted capacity. Hosted-terms changes require advance notice, consent and an export path; see [PRICING.md](PRICING.md).

## What is not yet locked or built

Hosted factory execution, GitHub App repository publication, tenant-safe runner isolation, autonomous verified changes, Slack/mobile delivery, controlled recursive learning and enterprise operational guarantees. Supabase identity/project/session collaboration and the durable-analysis control plane are deployed and production-verified with a one-off local worker. The controlled durable repair runtime is unmerged source: it closes the queue/lease/authorization gap for one bounded repair policy, but it does not provide hosted compute, and an **always-on cloud worker is still absent for both task kinds**, so continuous hosting remains pending and no availability, capacity or SLA claim may be made. No incremental spend is authorized for it, and the free-tier hosting options under consideration carry inactivity-pause, capacity and idle-reclamation limits that are documented rather than worked around. The missing piece is hosted execution, not local model tooling, which exists. Evidence and deployment state are tracked in [STATUS.md](STATUS.md). Billing, usage metering, quota enforcement and the Team plan's shared run history / review workflow / budget administration are not built, so the Team price in [PRICING.md](PRICING.md) is a proposal that cannot be charged. Long-term hosted-preview terms, capacity limits and a compliant commercial hosting entitlement are also unresolved, and the self-hosted FastAPI/SQLite engine identity stays deliberately separate from the hosted Supabase identity.

## Review and updates

Docs explain **decisions and intended use**, not a guarantee all components exist. For every PR, update affected ADR/architecture and [STATUS.md](STATUS.md) alongside tests. The code, deployment checks and independent evidence determine what is actually working. Do not fabricate production capabilities or performance.
