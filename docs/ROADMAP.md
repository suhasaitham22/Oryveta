# Oryveta product and pull-request roadmap

This is a delivery plan, not a claim that the factory already exists. Sequence numbers below identify planned PRs, not GitHub PR IDs. Current implementation and exercised evidence are recorded separately in [STATUS.md](STATUS.md).

## Shared goal

One platform for personal users and teams: a polished web/mobile experience and Slack client operating the same accounts, projects, private/shared sessions, durable work items, runs, approvals and scoped knowledge.

- **Start New:** requirements become an implemented, independently tested application and reviewable source—not merely a template.
- **Evolve:** an authorized repository/change request becomes a reproduced problem, isolated implementation, independent verification and reviewable PR.
- **Always-on:** accepted work and explicit schedules survive client closure and recover from interruption; machine/integration grants are independent of browser sessions.
- **Recursive learning:** verified outcomes produce candidate memories/skills/harness improvements, which are compared against a baseline, reviewed, versioned and rolled back when necessary.

## Architectural commitments

Retain React/shadcn, Python/FastAPI and Supabase/PostgreSQL. Keep one hosted identity and explicit workspace/project/session authorization. Local SQLite is a development mode, not a distributed tenant database. Use one run/event contract across web, mobile and Slack. Deterministic code owns permissions, state transitions, resource limits and publication; models propose actions inside that boundary.

Use open-source Deep Agents/LangGraph primitives where they fit, rather than adopting Open SWE's required managed deployment wholesale. The Matt Pocock factory skill is a planning reference, not executable infrastructure. No framework rewrite, duplicate tracker/database or generic agent meta-framework is required.

## Planned PRs and proof gates

| PR | Purpose and deliverable | Evidence required | Depends on |
| --- | --- | --- | --- |
| 1 — Auth and collaboration | Real provider discovery/login, projects, explicit roles/invitations, private-session association, revocation | Real Supabase/new-tab email login; three actors; denied writes; project/session isolation; alias reassignment and invite replay; sign-out | Hosted setup for production rollout |
| 2 — Durable work and events | Canonical work items/runs, typed events, checkpoints, leases, cancellation, supervised worker; adapt real analysis rather than ship an empty queue | Browser/API/worker interruption preserves accepted work; stale worker cannot publish; no duplicate completion | 1 |
| 3 — Model, tools and verifier | Explicit local model, scoped tools, disposable isolated execution, budgets, independent checks | Real edit/run/repair; denied credential/network access; protected evaluator; no paid fallback | 2, authorized compute |
| 4 — GitHub App | Selected-repository grants, short-lived tokens, source SHAs, branch/PR publication, separately approved repository creation | Allowed private repo works; unselected/revoked access denied; token renewal; deduplicated side effects; stale approval rejected | 1–3 |
| 5 — Agent chat/workspace | Minimal shadcn conversation, composer, decision summaries, real todos/tool cards, evidence/approval inspector, reconnect/cancel | Actual streamed events survive reconnect without duplicates; readable history/scroll; keyboard/reduced-motion/mobile checks | 1–3; GitHub surfaces use 4 |
| 6 — Evolve | Reproduce, plan, implement, verify, draft PR and bounded feedback/rework | Baseline fails and candidate passes independent tests; required behavior preserved; exact tested SHA in PR | 1–5 |
| 7 — Start New | Brief/criteria, decomposition, implementation, build/test/preview, reviewed publication and follow-up changes | Working CRUD/validation/persistence app, browser/API smoke, restart and changed-requirement check; more than one brief | Shared loop from 6 |
| 8 — Review and release | Proof-linked review inbox, isolated previews, exact-artifact approvals, configured deployment target and rollback | Unauthorized preview/deploy denied; preview cannot access app cookies; stale approval rejected; test release rollback | 6–7 |
| 9 — Slack | Installation/linking, explicit bindings, commands/mentions, durable intake/outbox, status/review links | Authorized/unlinked/unauthorized actors; retry dedupe; fast ack; long-job callback; rotation/uninstall; no channel leakage | 1–8 |
| 10 — Scoped learning registry | Evidence/provenance, candidate memories/skills, retrieval permissions, retention/deletion, versioned activation/rollback | Reuse a reviewed lesson; deny cross-tenant/private-session retrieval; reject forged results; invalidate deleted sources | Reliable run/verifier evidence |
| 11 — Recursive improvement lab | Outcome-driven candidates, isolated baseline/candidate trials, protected holdouts, bounded repeated cycles, reviewed promotion | Held-out improvement within budget, no required/security regressions, rejection and rollback paths demonstrated | 10 |
| 12 — Mobile delivery | Installable PWA using the same backend; explicit native-platform follow-on PRs if required | Same run across phone/web, client closure does not stop work, safe caches/logout, honest browser/device coverage | Complete web flows |
| 13 — Operated launch and scale | Supervision, fair queues, quota/secret/retention controls, backup/restore, incident procedures, measured capacity | 24-hour soak plus crashes/network loss/expiry/revocation/reboot/restore; no lost accepted work or duplicate publication in tested scenarios | Relevant completed flows |

Each PR must add an exercised capability. Verification and human boundaries begin with the first execution; PR 8 is not permission to postpone safety. Basic supervision starts in PR 2; PR 13 is the operated-launch gate. Collect learning evidence early, but activate learning only after the evidence is trustworthy.

## Premium, minimal chat UI

Desktop: a compact project/session sidebar, readable conversation and optional inspector for tasks/files/diffs/preview/evidence. Mobile: one primary pane, sidebar/inspector sheets and a keyboard-safe composer. Keep the current project/session audience visible.

Use owned shadcn/Radix composites for messages, composer, run activity, task list, tool results, evidence and approvals. Decision/reasoning blocks contain useful progress and decision summaries, not raw private model reasoning. Todos and tool states come from persisted worker events, not simulated completion. Collapse routine completed activity; keep failures and approvals visible.

Quality means readable typography, restrained color, consistent spacing, responsive controls, accessible focus/contrast, reduced motion, safe Markdown, stable scroll and honest terminal states. More animation, agents or panels does not make the product better.

## Recursive learning contract

Verified outcome -> candidate -> baseline comparison -> protected holdout/security/budget gates -> authorized promotion or rejection -> observe later outcomes -> next bounded candidate.

Keep source scope and lineage. Private sessions do not become project/global memory automatically. No cross-customer training by default. Learned text cannot modify permissions, tool/network access, evaluator criteria or approval policy. Every active version has evidence and a rollback parent. Human-reviewed activation is compatible with automatic learning and evaluation; unrestricted self-promotion makes the safety argument circular.

Weight training is a separate data-consent/compute program, not another name for memory or skill reuse.

## Free architecture and scaling

Target no mandatory paid service dependency, not unlimited free SaaS capacity. A continuously powered authorized host, electricity, storage, network and maintenance are still required. Local inference has no per-token service bill but must meet measured coding-quality and throughput gates. Never switch to a paid provider automatically.

Free static hosting and Supabase allowances can support a bounded pilot; quotas/pausing are not an availability SLA. Vercel Hobby is non-commercial personal use only. Choose a compliant launch deployment, such as an appropriate Cloudflare static-hosting plan, or explicitly approve a paid plan. Self-hosted Supabase transfers backups, updates and availability to the operator. Native store/signing accounts may require fees; a PWA is not falsely described as App Store delivery.

Scale isolated runners and inference separately, using measured queue wait, accepted-task success, review effort and compute per accepted change. Customer-owned pools are an optional deployment mode with explicit enrollment and evidence trust boundaries. Add services only when a measured bottleneck justifies them.

## Decisions before broader implementation

1. Required mobile distribution: PWA-first, or named native iOS/Android/desktop targets.
2. Authorized always-on compute, stable integration ingress and backup storage.
3. Capacity-limited multi-user pilot versus a contractual service-level promise.
4. One real Evolve task and one Start New brief as launch acceptance cases.

The auth code, a local test, a preview deploy and a production release are separate milestones. No source claim replaces actual provider setup or a live test.

## References

[Matt Pocock factory skill](https://github.com/mattpocock/skills/pull/1316), [Open SWE](https://github.com/langchain-ai/open-swe), [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview), [shadcn](https://ui.shadcn.com/docs/components), [Slack transport constraints](https://docs.slack.dev/apis/events-api/comparing-http-socket-mode), [Supabase self-hosting](https://supabase.com/docs/guides/self-hosting), [Vercel fair use](https://vercel.com/docs/limits/fair-use-guidelines), [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/), [PWA installation](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable).
