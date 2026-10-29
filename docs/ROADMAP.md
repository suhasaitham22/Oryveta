# Oryveta product and pull-request roadmap

This is a delivery plan, not a claim that the factory already exists. Sequence numbers below identify planned PRs, not GitHub PR IDs. Current implementation and exercised evidence are recorded separately in [STATUS.md](STATUS.md).

## Shared goal

One platform for personal users and teams: a polished web/mobile experience and Slack client operating the same accounts, projects, private/shared sessions, durable work items, runs, approvals and scoped knowledge.

- **Start New:** requirements become an implemented, independently tested application and reviewable source—not merely a template.
- **Evolve:** analyze applications/packages, implement verified changes, and execute justified AI-native modernization or replacement with contract/data migration and rollback.
- **Always-on:** accepted work and explicit schedules survive client closure and recover from interruption; machine/integration grants are independent of browser sessions.
- **Recursive learning:** verified outcomes produce candidate memories/skills/harness improvements, which are compared against a baseline, reviewed, versioned and rolled back when necessary.
- **On-call:** both Start New and Evolve projects can ingest authorized operational signals, correlate bug reports, open a scoped investigation session and produce a verified fix through the same factory.

## Architectural commitments

Retain React/shadcn, Python/FastAPI and Supabase/PostgreSQL. Keep one hosted identity and explicit workspace/project/session authorization. Local SQLite is a development mode, not a distributed tenant database. Use one run/event contract across web, mobile and Slack. Deterministic code owns permissions, state transitions, resource limits and publication; models propose actions inside that boundary.

Use open-source Deep Agents/LangGraph primitives where they fit, rather than adopting Open SWE's required managed deployment wholesale. The Matt Pocock factory skill is a planning reference, not executable infrastructure. No framework rewrite, duplicate tracker/database or generic agent meta-framework is required.

## Planned PRs and proof gates

| PR | Purpose and deliverable | Evidence required | Depends on |
| --- | --- | --- | --- |
| 1 — Auth and collaboration | Real provider discovery/login, projects, explicit roles/invitations, private-session association, revocation | Real Supabase/new-tab email login; three actors; denied writes; project/session isolation; alias reassignment and invite replay; sign-out | Hosted setup for production rollout |
| 2 — Durable work and events | Canonical work items/runs, typed events, checkpoints, leases, cancellation, supervised worker; adapt real analysis rather than ship an empty queue | Browser/API/worker interruption preserves accepted work; stale worker cannot publish; no duplicate completion | 1 |
| 3 — Model, tools and verifier | One bounded coding loop with a resolved versioned execution spec, scoped tools, isolated runner, tool/artifact lineage, explicit continue/switch/stop checkpoints and independent checks | Real edit/run/repair; denied credential/network/evaluator access; pinned source/configuration; inspectable failure and safe restart; no paid fallback | 2, authorized inference/runner compute |
| 4 — GitHub App | Selected-repository grants, short-lived tokens, source SHAs, branch/PR publication, separately approved repository creation | Allowed private repo works; unselected/revoked access denied; token renewal; deduplicated side effects; stale approval rejected | 1–3 |
| 5 — Knowledge graph and analysis | Versioned repository/package/service/API/test/release relationships, source provenance, scoped retrieval and explicit coverage gaps | Trace an affected component to its tests, deployed release and findings; deny cross-project retrieval; invalidate stale/deleted sources | 4 |
| 6 — Agent chat/workspace | Canonical agent conversation, task/tool spans, evidence/artifact inspector, basic debugger, read-only playback and authorized sandbox forks | Real progress survives reconnect; inspect the exact tool/configuration/source behind a failure; forks do not replay external side effects or copy credentials; keyboard/mobile checks | 2–5 |
| 7 — Evolve verified changes | Reproduce, plan, implement, verify, draft PR and bounded feedback/rework | Baseline fails and candidate passes independent tests; required behavior preserved; exact tested SHA in PR | 2–6 |
| 8 — AI-native modernization | Full analysis dossier, target architecture, app/package migration, typed agent/tool boundaries and staged replacement | Required API/data/security behavior preserved or explicitly migrated; consumer tests, rollout/rollback and AI-quality gates pass | 5, 7 |
| 9 — Start New | Brief/criteria, decomposition, implementation, build/test/preview, reviewed publication and follow-up changes | Working app and persistence, browser/API smoke, restart and changed-requirement check; observable service/release identity | Shared loop from 7 |
| 10 — Review and release | Proof-linked review inbox, isolated previews, exact-artifact approvals, configured target and rollback | Unauthorized preview/deploy denied; previews cannot access app cookies; stale approval rejected; release rollback tested | 7–9 |
| 11 — Slack | Explicit installation/linking/bindings, commands/mentions, durable intake/outbox and review links | Linked/unlinked/unauthorized actors; retry dedupe; fast ack; long-job callback; no channel leakage | 1–10 |
| 12 — Telemetry and bug connectors | Read-only log/metric/trace and issue connectors, release/source mapping, redaction, durable event receipts | Source/tenant isolation, bounded retrieval, replay handling, secret/PII controls and explicit retention/query limits | 2, 4, 5 |
| 13 — On-call investigation | Deterministic incident correlation, automatic scoped sessions, evidence timeline, hypotheses and escalation | Duplicate/storm inputs create bounded canonical work; near-miss incidents stay distinct; diagnosis cites actual source evidence | 6, 12 |
| 14 — On-call fix and closure | Reproduce incident against deployed revision, isolated patch, independent tests, controlled release and post-change observation | Real operational fault reaches a verified fix; no production write via telemetry credentials; resolution requires observation, not merely a merged PR | 7, 10, 13 |
| 15 — Scoped learning registry | Versioned experience entries and localized updates with evidence/provenance, applicability, permissions, retention/deletion and reviewed activation | Reuse a supported lesson; distinguish model ratings from verified outcomes; reject forged/poisoned evidence; deny private-session leakage; invalidate stale/deleted sources | Reliable run/incident evidence |
| 16 — Recursive improvement lab | Bounded skill edits and task-local harness/approach experiments, pre-registered comparisons, protected reporting split and reviewed promotion; optional calibrated ranking only if useful | Whole-campaign quality/cost evidence, no required/security regressions, no evaluator/authority changes; reject inconclusive candidates and demonstrate rollback | 15 |
| 17 — Mobile delivery | Installable PWA using the same backend; explicit native follow-ons where required | Same run/incident across phone/web; closure does not stop work; safe caches/logout and honest device coverage | Complete web flows |
| 18 — Enterprise identity/governance | Required federation/MFA/lifecycle integrations, service identities, separation of duties, audit export and retention/deletion controls | Deprovisioning/revocation drills, least privilege and administrative audit; provider entitlements verified, not assumed free | Existing resource security from 1 |
| 19 — Operated launch and scale | Supervision, fair queues, quotas, recovery, operational ownership and measured capacity | Soak and injected crash/network/expiry/revocation/reboot/restore; agreed SLO/RPO/RTO demonstrated; no false SLA/compliance claims | Relevant completed flows |

Each PR must add an exercised capability and may be split further for reviewability. Security and verification start with the first execution; the release and enterprise milestones do not defer baseline isolation or approval. Basic supervision starts in PR 2. Collect learning evidence early, but activate learning only after outcomes are trustworthy. Detailed modernization and on-call contracts are in [PRODUCT.md](PRODUCT.md) and [OPERATIONS.md](OPERATIONS.md).

### Research-informed implementation order

The [factory checklist and research decisions](AGENT-HARNESS.md#factory-as-code-and-inspectable-execution) and [experiment protocol](EVALUATION.md#research-led-experiments) refine these stages; they do not declare them implemented.

1. **First prove the fixed loop.** Stage 3 must complete an actual independently checked repair, not only parse a manifest or render a chat. Capture the resolved configuration, tool spans and artifact lineage from its first run. Keep the trusted permission/verifier boundary outside candidate code.
2. **Make it inspectable before making it adaptive.** Basic trace inspection accompanies Stage 3; Stage 6 supplies the richer chat/debugger surface. Recorded playback is not re-execution. Browser/desktop work uses isolated approved preview accounts, not a human's general browsing session.
3. **Measure our work.** Curate consented repository tasks from pre-action snapshots and establish baseline outcomes, variance, cost and failure categories. Public benchmarks supplement, not replace, this distribution. Do not train or select against exposed final answers.
4. **Add reviewed memory, then bounded adaptation.** Test structured experience, one-skill changes and controlled continue-versus-alternative forks before wider harness search. Keep unsupported lessons as candidates. A learned ranker, if later justified, orders experiments rather than approving results.
5. **Keep weight training separate.** LM2LM-style RL/model-training campaigns need their own data, compute and cost authorization. No published efficiency percentage makes those campaigns fit a no-paid-fallback pilot automatically.

An unavailable continuous host does not prevent source/design work or an authorized local experiment. It does prevent a 24/7 availability claim. Model experiments still require an authorized provider and suitable isolated execution capacity; none of these paper reviews supplies that access.


## Premium, minimal chat UI

Desktop: a compact project/session sidebar, readable conversation and optional inspector for tasks/files/diffs/preview/evidence. Mobile: one primary pane, sidebar/inspector sheets and a keyboard-safe composer. Keep the current project/session audience visible.

Use owned shadcn/Radix composites for messages, composer, run activity, task list, tool results, evidence and approvals. Decision/reasoning blocks contain useful progress and decision summaries, not raw private model reasoning. Todos and tool states come from persisted worker events, not simulated completion. Collapse routine completed activity; keep failures and approvals visible.

On-call sessions add an incident summary, affected service/environment/release, evidence timeline, linked bug reports, hypotheses, actual investigation tasks, fix/verification state and escalation/approval controls. Never mix model hypotheses with confirmed operational facts.

Quality means readable typography, restrained color, consistent spacing, responsive controls, accessible focus/contrast, reduced motion, safe Markdown, stable scroll and honest terminal states. More animation, agents or panels does not make the product better.

## Recursive learning contract

Verified outcome -> candidate -> baseline comparison -> protected holdout/security/budget gates -> authorized promotion or rejection -> observe later outcomes -> next bounded candidate.

Keep source scope and lineage. Private sessions do not become project/global memory automatically. No cross-customer training by default. Learned text cannot modify permissions, tool/network access, evaluator criteria or approval policy. Every active version has evidence and a rollback parent. Human-reviewed activation is compatible with automatic learning and evaluation; unrestricted self-promotion makes the safety argument circular.

Weight training is a separate data-consent/compute program, not another name for memory or skill reuse.

## Free architecture and scaling

Target no mandatory paid service dependency, not unlimited free SaaS capacity. A continuously powered authorized host, electricity, storage, network and maintenance are still required. Local inference has no per-token service bill but must meet measured coding-quality and throughput gates. Never switch to a paid provider automatically.

AI-native generated applications also need inference resources. Log providers can charge for ingestion, retention, queries and egress. A connector does not make those services free: default to existing authorized allowances or self-hosted sources, enforce budgets and never enable a paid telemetry/model plan automatically.

Free static hosting and Supabase allowances can support a bounded pilot; quotas/pausing are not an availability SLA. Vercel Hobby is non-commercial personal use only. Choose a compliant launch deployment, such as an appropriate Cloudflare static-hosting plan, or explicitly approve a paid plan. Self-hosted Supabase transfers backups, updates and availability to the operator. Native store/signing accounts may require fees; a PWA is not falsely described as App Store delivery.

Scale isolated runners and inference separately, using measured queue wait, accepted-task success, review effort and compute per accepted change. Customer-owned pools are an optional deployment mode with explicit enrollment and evidence trust boundaries. Add services only when a measured bottleneck justifies them.

## Decisions before broader implementation

1. Required mobile distribution: PWA-first, or named native iOS/Android/desktop targets.
2. Authorized always-on compute, stable integration ingress and backup storage.
3. Capacity-limited multi-user pilot versus a contractual service-level promise.
4. One real Evolve task and one Start New brief as launch acceptance cases.
5. The first modernization target, required application/package contracts and the initial on-call telemetry/bug sources, with explicit environments and automation policy.

The auth code, a local test, a preview deploy and a production release are separate milestones. No source claim replaces actual provider setup or a live test.

## References

[Matt Pocock factory skill](https://github.com/mattpocock/skills/pull/1316), [Open SWE](https://github.com/langchain-ai/open-swe), [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview), [shadcn](https://ui.shadcn.com/docs/components), [Slack transport constraints](https://docs.slack.dev/apis/events-api/comparing-http-socket-mode), [Supabase self-hosting](https://supabase.com/docs/guides/self-hosting), [Vercel fair use](https://vercel.com/docs/limits/fair-use-guidelines), [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/), [PWA installation](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable).
