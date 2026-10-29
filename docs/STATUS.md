# Oryveta implementation status

## Unattended worker service — source verification, 2026-10-29

The analysis worker now has a container-oriented `factory_service` entry point. It initializes a private credential from a secret only when no persisted file exists, preserves rotated sessions across restart, excludes another service using that private directory, drops root after mounted-volume initialization, and handles SIGTERM through the existing worker teardown. Invalid persisted state is refused rather than replaced by a stale bootstrap.

Local verification: **320 Python tests passed**, with **85.27% branch-inclusive coverage** against the 84% gate; Ruff and Python compilation passed. An actual CLI smoke exercised private first-start storage, restart with a rotated credential and corrupt-state refusal without network or real credentials. A reproduced `0600` FIFO startup hang is now rejected as a non-regular credential file. The CI gates additionally exercise real Supabase/GitHub analysis through first-start/restart, continuous-service SIGTERM, and credential preservation/privilege drop across replacement Docker containers.

This is a deployable source change, **not a hosted rollout**. Railway authorization, actual free-plan entitlement/capacity checks, persistent worker operation and model/isolation compute remain outstanding. No payment method, paid plan or paid inference fallback has been enabled.

## Production runtime rollout — 2026-10-25 UTC

The Vercel production deployment for merged commit `1c3e731c2d4b3ffd434dcfd5719fb57b679b658c` succeeded. The reviewed `durable_factory_runtime.sql` and `retained_attribution_and_lease_clock.sql` migrations are now applied to Oryveta project `nydtmiseclkwauiepqxn`; existing prerequisite migrations were not replayed.

- All four public runtime tables and the private lease table have RLS enabled. Anonymous reads and direct authenticated writes are denied; authenticated callers cannot read private leases. All 15 exposed security-definer RPCs have fixed empty search paths and deny anonymous execution.
- `production_auth_smoke.py --runtime` passed against the deployed site and API: browser-submitted public-repository analysis survived browser closure, a separately authenticated **one-off local worker** completed it, and the downloaded JSON matched the stored result. The worker rotated its ordinary session and received no administrative key.
- Production cancellation rejected a late heartbeat/completion; worker revocation removed access. Deleting the cancelling/invited account preserved terminal metadata, and a new account at the same email address inherited no project or chat access.
- Five controlled test identities and their application rows were removed. An independent catalog/data query found no release-test accounts, workspaces, projects, chats, registrations, work items, runs, events or leases remaining. Provider audit logs may remain.
- Security advisors still report the intentional authenticated-only `SECURITY DEFINER` RPC pattern and disabled leaked-password protection. The RPCs require their reviewed actor/role/lease checks; switching them to invoker mode would break the no-direct-write contract. Supabase leaked-password protection requires Pro or above, so no paid plan was enabled. The advisor output is not claimed to be clean.

**Still pending:** an authorized always-on worker host and measured free-tier capacity. This rollout proves the production control plane and one-off execution path, not 24/7 availability, model-driven coding, host recovery or enterprise readiness.

## Auth and collaboration changes

PR #31 is deployed to Vercel production. Its atomic project/collaboration migration is applied to Supabase, with RLS enabled and direct client mutation grants denied on all four new tables. Production GitHub sign-in and deployed multi-user project/private-session authorization have been exercised. This release does not add a hosted coding factory.

The React Studio builds a hosted `dist` and a self-hosted `dist-local`. FastAPI serves the latter at `/studio/`; the legacy `/` remains a separate self-hosted surface. Hosted Supabase identity and local FastAPI engine sessions are deliberately separate. No hosted engine bridge exists.

**Identity:** Supabase email links use PKCE with shared browser storage; identity is verified with `getUser()`. GitHub provider discovery is dynamic. The production site URL and exact redirects are configured, and GitHub OAuth is enabled using an identity-only OAuth App. A real GitHub consent/callback reached the production origin and `/auth/v1/user` returned 200. Existing email identities are not silently merged with a new GitHub identity.

**Projects:** PostgreSQL RLS and narrow RPCs enforce owner/admin/engineer/reviewer/viewer roles. Pending email or immutable-user-bound alias invitations confer no project access. Acceptance is atomic; replay cannot recreate a revoked grant. Reassigned aliases cannot silently upgrade an invitation for the former owner. Workspace membership and project membership are distinct.

**Private sessions:** Existing `chats`/`chat_shares` remain owner-private until explicitly shared and accepted. A project association grants no conversation access; a conversation guest does not gain project access. The browser cannot rewrite the association. Automatic external invitation emails are not implemented.

## Exercised verification

- Actual Supabase CLI 2.121.0 native PostgreSQL 17, Auth/GoTrue, PostgREST and Mailpit; no mocked auth responses.
- Transactional workspace and project RLS suites, including anonymous/unauthorized access, roles, owner protection, project/session boundaries, revoke/replay and the failing-before/passing-after alias-reassignment regression.
- Production-built React Studio in headless Chromium: actual email link opened in a new tab, original-tab session restoration, three users, project create/invite/accept, read-only mutation denial, session-only sharing, project/admin-self revocation, sign-out and desktop/mobile-width rendering. The new-tab PKCE regression failed before the storage fix and passed afterward.
- Python suite: 151 tests passed. Ruff and the seven storyboard/security-scan contracts passed.
- Vercel-target build succeeds for the canonical configuration; a privileged browser key and a Supabase origin absent from the deployed CSP are rejected before building.
- Exact-head GitHub preflight and PR checks passed, including Python 3.11–3.13, security/Docker, React browser QA and the real local Supabase integration.
- Production browser OAuth: identity-only GitHub consent, production callback, verified user and a Projects page without schema errors.
- `scripts/production_auth_smoke.py`: three controlled production identities authenticated through the real Auth password grant; ordinary user sessions exercised the deployed create/invite/accept/read-only/session-sharing/revocation paths and mobile rendering. The admin key only provisioned/removed test identities, never entered a browser. All three test identities and their cascading application rows were removed; cleanup was independently checked.

Local Mailpit coverage is not external email delivery. Production GitHub OAuth and authorization checks are separate evidence from the API-issued test-session setup; the latter does not claim email or OAuth-consent coverage. The default hosted SMTP remains limited and unverified for general delivery. Physical mobile devices, a 24-hour worker soak, enterprise recovery and uptime remain unproven. The existing lazy Three.js size advisory is not hidden.

## Runtime and collaboration hardening — local verification, 2026-10-24

- Worker results observed after the execution deadline are rejected. Process-group cleanup also stops helpers when their leader has already exited. Raw control-plane responses and protocol-error text cannot expose reflected credentials through the normal error/traceback paths.
- Conversation details and sharing controls remain tied to their chat. Old refreshes cannot hide a newly created conversation. Delayed message, conversation, invitation and project-save acknowledgements preserve newer drafts, including after navigation.
- The conversation view shows the newest 200 messages, including newly accepted messages beyond the old cutoff, and announces omitted older history.
- The forward migration `retained_attribution_and_lease_clock.sql` permits deletion of attribution accounts while preserving terminal timestamps/state and refusing inherited grants. Lease timing uses wall-clock observations after locks: a 17-second lock wait still returned a fresh 15-second lease in the real concurrency test.
- A suspected workspace-cascade conflict did not reproduce. Its existing foreign key was kept; successful workspace deletion and forbidden standalone registration deletion now have regression coverage.

Verification before rollout: **302 Python tests passed**, all four SQL suites passed, all **10 concurrent-session cases** passed, and all **8 real-browser collaboration ordering cases** passed. Existing real Supabase email/PKCE, project/session authorization and compiled desktop/tablet/mobile navigation checks passed. The real GitHub worker smoke also passed completion, rotating credentials, crash recovery, cancellation and revocation. Production rollout evidence is recorded above.

## Product explanation and navigation — local verification, 2026-10-24

The product explanation now starts with project planning, repository analysis and private collaboration. Public pages, workspace introductions, demo scripts, metadata, the legacy interface, historical prototype and product docs distinguish hosted features, self-hosted tools and the planned AI software factory.

Normal pages no longer show generic Back controls. Demo Studio provides **Back to brief**, including direct links, while preserving the draft and returning keyboard focus to the Brief tab. Shared gutters, readable supporting text, explicit mobile workspace navigation, larger touch targets and restrained hover feedback keep the existing visual style consistent.

Exercised verification:

- Python suite: **295 passed**; Ruff, JavaScript syntax and seven storyboard/security contracts passed.
- Hosted and self-hosted production builds passed. Chromium exercised navigation, demo return, draft retention and contextual exports at desktop, tablet and mobile widths. The self-hosted path also exercised real local login, ZIP analysis and cancellation.
- Real local Supabase/Chromium collaboration passed: new-tab email/PKCE login, project invitations and viewer denial, private-session sharing and isolation, revocation and sign-out.
- Additional 320px/768px browser scenarios preserved drafts and focus after demo return. Eight signed-out routes at 1440px and 390px produced no horizontal overflow or axe-core 4.10.3 violations for the selected WCAG A/AA rules. This is automated coverage, not a full accessibility certification or a physical-device test.
- Legacy browser flows passed, with the existing auth-adapter mock clearly distinguished from the real Supabase checks. Historical prototype checks now exercise escaped draft export, local-only repository preview and navigation instead of asserting marketing phrases. They cover the repaired inline-script parse error and the missing mobile Activity link.

These source/local checks preceded the production UI rollout. Free worker hosting still requires provider authorization and measured allowance fit; no card, paid plan or paid inference fallback has been added.

## Durable runtime candidate — local verification, 2026-10-23

Stage 2 implements real project-authorized public-repository analysis, not an empty queue or a coding agent. Work items, attempts, events, leases, checkpoints, cancellation, creator/worker revocation and source pins are persisted in Supabase. The browser can submit, inspect, cancel and download a completed report independently of the worker.

Exercised against isolated native Supabase and real GitHub downloads:

- SQL authorization/transition suite and all nine concurrent PostgreSQL-session cases pass: cancellation/completion, reclaim, registration revocation, concurrent source pinning and idempotent admission.
- A separately authenticated worker completed `pallets/click` analysis (91 source files) after the submitting session signed out; its rotating credential stayed private.
- SIGKILL recovery stopped the orphaned child, reclaimed its expired lease, swept its snapshot directory and completed attempt 2 at the pinned commit. Cancellation and revoked registrations could not publish late results.
- Production-built Chromium UI submitted work, closed the page, reopened the completed report and downloaded the persisted JSON. A new queued run did not show the previous run's result and could be cancelled.
- Python suite: **295 passed**. Ruff and all seven frontend storyboard/security-scan contracts pass. A startup-race regression and a separate actual-child-entrypoint smoke prove that a worker dying before child initialization produces exit 3 and no result.

These initial checks proved local runtime behavior. The production database and one-off execution path were subsequently verified as recorded above; no always-on worker host is configured. A host-reboot/restore drill, 24-hour soak, model-driven code changes and an availability commitment remain unproven. Worker operation, credential limitations and source-pin semantics are in [OPERATIONS.md](OPERATIONS.md), [IMPLEMENTATION.md](IMPLEMENTATION.md) and [API.md](API.md).

## Existing engine and product boundaries

The local FastAPI/SQLite worker supports deterministic starter repositories, bounded ZIP/public GitHub snapshots, read-only heuristic analysis, cancellation/result fencing and exports. Analysis includes bounded full-file fingerprints, manifest hints, AST-based Python security checks and explicit truncation. Imported code is not executed or modified autonomously.

Demo Studio edits contextual storyboards; exports remain unverified drafts. Local Remotion rendering and model/benchmark demonstrations do not establish application-generation correctness.

`oryveta_engine.learning` compares submitted evidence and requires human review. It does not authenticate execution evidence, train a model, retrieve cross-session memory or promote its own production harness.

**Not implemented:** hosted factory execution, isolated arbitrary customer-code execution, full knowledge graph/analysis, autonomous verified Evolve fixes, AI-native application/package rewriting, custom Start New application generation, project on-call telemetry/correlation/repair, GitHub App repository publication, Slack integration, native mobile distribution, continuously running recursive improvement, enterprise SSO/billing or an availability SLA.

See [identity and testing](IDENTITY-WORKSPACES.md), [architecture](ARCHITECTURE.md) and the [staged roadmap](ROADMAP.md). A source change, local test, preview deployment and production release are different evidence levels.
