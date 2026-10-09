# Roadmap and measurable engineering milestones

This roadmap records intent, **not promises of delivery dates**. Avoid labeling future components as completed merely because a mockup or scaffold exists.

| Phase | Primary deliverable | Objective exit criteria |
| --- | --- | --- |
| 0 — Brand and public skeleton | Oryveta, Soft Modern, Apache-2.0, static site, docs | Two navigation paths work on mobile, public URL assigned, license and docs available |
| 1 — Publish functional MVP | Existing FastAPI/SQLite local code, tests, scaffold/export, source analysis | Remote GitHub source complete, CI runs, automated tests succeed |
| 2 — Real identity and persistence | GitHub OAuth sessions, projects and repository-scoped GitHub App | Live OAuth, denied/expired/revoked tests, private repo permission isolation |
| 3 — Autonomous patch engine | Model/tools + sandbox, independent tests, traceable PR | One real Evolve bug fix proposed, independently tested and reviewable as PR |
| 4 — Autonomous app generation | Start New requirements → source → tests → preview | Custom brief becomes runnable feature-complete repo validated by external acceptance checks |
| 5 — Cloud continuity | Durable tasks, remote worker, recovery, budget | Job survives browser/device closure and worker restart; no duplicate side effects |
| 6 — Learning + internal Arena | Verified outcomes, hypothesis graph and harness A/B | Evidence-backed improvement on held-out tasks at equal compute and safety standards |
| 7 — Consultancy readiness | Multi-client workspace, roles, audit, handover, security reviews | Cross-tenant isolation, approvals, backup/restore, rollback, measured pilot outcomes |

## Task decomposition

1. Keep GitHub README and docs/STATUS.md accurate.
2. Finish source upload with full test suite and dependency audit.
3. Connect real GitHub identity without broad repository permissions.
4. Add GitHub App and permit selected repo imports.
5. Create issue/finding → proposed patch → sandbox → independent tests → PR.
6. Build a comparable Start New agent loop.
7. Persist remote job state and evidence.
8. Evaluate cost/quality against open-source baselines.
9. Only then add parallel agent roles, Rust runtime and multi-tenant consultancy features if results justify them.

## Definition of done

Each feature requires code review, successful relevant CI, documented security boundary, accessible UX, evidence/limitations, an explicit test and safe rollback where appropriate. Release notes must reflect actual deployed behavior, not plans.
