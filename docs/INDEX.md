# Oryveta documentation hub

**Snapshot: 2026-10-09.** This is the main source of architectural intent and product decisions. Always distinguish **current implementation** from **planned capabilities**. The public site at https://oryveta.vercel.app is a responsive static UI preview, not a complete agent service.

## Product and design

| Document | Covers |
| --- | --- |
| [VISION.md](VISION.md) | Mission, competitor differentiation, user pain points, ProofLoop and Verified Outcome Graph |
| [PRODUCT.md](PRODUCT.md) | Start New and Evolve definitions, consultancy scenarios, outcome contracts |
| [USER-JOURNEYS.md](USER-JOURNEYS.md) | Auth/onboarding, builds, Evolve patching, approvals, client handover, error states |
| [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md) | Locked Soft Modern / minimalist look, navigation, accessibility and motion |
| [BRAND.md](BRAND.md) | Oryveta identity, domain and naming history |

## Platform engineering

| Document | Covers |
| --- | --- |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Source layout, local setup, test coverage and current security limitations |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Control/intelligence/execution planes, technology selections, current vs target stack |
| [DATABASE.md](DATABASE.md) | SQLite, D1, optional PostgreSQL/Supabase, schema ownership and artifacts |
| [AUTH-SECURITY.md](AUTH-SECURITY.md) | GitHub OAuth vs GitHub App, roles, sandbox/prompt injection, approvals |
| [API.md](API.md) | Local MVP versus planned API contracts |
| [AGENT-HARNESS.md](AGENT-HARNESS.md) | Context compiler, models, router, tools, worker, verified patch loop and Rust options |
| [EVALUATION.md](EVALUATION.md) | Internal Arena, Kaggle, unbiased benchmarks, self-learning and hypothesis graph |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | GitHub, Vercel, Cloudflare, Supabase, remote 24/7 workers and free-tier constraints |
| [OPERATIONS.md](OPERATIONS.md) | CI/CD, observability, lease/recovery, incidents and backups |
| [QUALITY.md](QUALITY.md) | Enforced CI matrix, security scans, branch coverage, packaging and Docker smoke |

## Delivery and governance

| Document | Covers |
| --- | --- |
| [ROADMAP.md](ROADMAP.md) | Phases and objectively testable milestones |
| [STATUS.md](STATUS.md) | Live GitHub and Vercel status, current limitations and in-progress work |
| [OPEN-SOURCE.md](OPEN-SOURCE.md) | Apache-2.0 licensing, contributor and commercial-use principles |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Tests, PR requirements, benchmark and security contribution standards |
| [DEPLOYMENT-PREVIEW.md](DEPLOYMENT-PREVIEW.md) | Static hosted preview scope and manual run/deploy instructions |

## Architecture decision records

- [ADR 0001](adr/0001-two-product-journeys.md): two product journeys; Arena is internal.
- [ADR 0002](adr/0002-portable-control-plane.md): local-first MVP and portable cloud architecture.
- [ADR 0003](adr/0003-evidence-and-approval.md): evidence before claims, approval for risk.

## What is locked

Oryveta name; Soft Modern/minimalist visual direction; Start New + Evolve as two main journeys; Kaggle only for testing; Apache-2.0 open-source goal; evidence and permission requirements; $0 required software licensing with optional bring-your-own-compute.

## What is not yet locked or built

Final distributed database selection, remote Rust supervisor, hosted Supabase auth/database, production GitHub App integration, autonomous model-backed software changes, tenant-safe CI/worker sandboxes, proven benchmark wins and enterprise deployment.

## Review and updates

Docs explain **decisions and intended use**, not a guarantee all components exist. For every PR, update affected ADR/architecture and [STATUS.md](STATUS.md) alongside tests. The code, deployment checks and independent evidence determine what is actually working. Do not fabricate production capabilities or performance.
