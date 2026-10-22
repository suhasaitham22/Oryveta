# Oryveta implementation status

## Auth and collaboration changes

The current auth/collaboration change adds persisted hosted project briefs, project roles and invitations, private-conversation project association, runtime sign-in provider discovery, and real Supabase/browser regression coverage. It does not add a hosted coding factory. Production migration and provider rollout are separate from these local verification results.

The React Studio builds a hosted `dist` and a self-hosted `dist-local`. FastAPI serves the latter at `/studio/`; the legacy `/` remains a separate self-hosted surface. Hosted Supabase identity and local FastAPI engine sessions are deliberately separate. No hosted engine bridge exists.

**Identity:** Supabase email links use PKCE with browser storage shared across tabs; identity is verified with `getUser()`. Initialization failures are surfaced. GitHub availability comes from the actual project settings, not a hard-coded feature flag. During the 2026-10-22 check the resumed hosted project advertised email enabled and GitHub disabled. Its administrative credentials were unavailable, so no hosted provider/schema changes are claimed.

**Projects:** PostgreSQL RLS and narrow RPCs enforce owner/admin/engineer/reviewer/viewer roles. Pending email or immutable-user-bound alias invitations confer no project access. Acceptance is atomic; replay cannot recreate a revoked grant. Reassigned aliases cannot silently upgrade an invitation for the former owner. Workspace membership and project membership are distinct.

**Private sessions:** Existing `chats`/`chat_shares` remain owner-private until explicitly shared and accepted. A project association grants no conversation access; a conversation guest does not gain project access. The browser cannot rewrite the association. Automatic external invitation emails are not implemented.

## Exercised verification

- Actual Supabase CLI 2.121.0 native PostgreSQL 17, Auth/GoTrue, PostgREST and Mailpit; no mocked auth responses.
- Transactional workspace and project RLS suites, including anonymous/unauthorized access, roles, owner protection, project/session boundaries, revoke/replay and the failing-before/passing-after alias-reassignment regression.
- Production-built React Studio in headless Chromium: actual email link opened in a new tab, original-tab session restoration, three users, project create/invite/accept, read-only mutation denial, session-only sharing, project/admin-self revocation, sign-out and desktop/mobile-width rendering. The new-tab PKCE regression failed before the storage fix and passed afterward.
- Python suite: 151 tests passed. Ruff and the seven storyboard/security-scan contracts passed.
- Vercel-target build succeeds for the canonical configuration; a privileged browser key and a Supabase origin absent from the deployed CSP are rejected before building.

Local mail is captured in Mailpit. These results do not prove external mailbox delivery, live GitHub OAuth consent, production redirects, physical mobile-device behavior, hosted schema deployment, a 24-hour worker soak or enterprise uptime. The existing lazy Three.js chunk still emits Vite's size advisory; it was not hidden or treated as a correctness failure.

## Existing engine and product boundaries

The local FastAPI/SQLite worker supports deterministic starter repositories, bounded ZIP/public GitHub snapshots, read-only heuristic analysis, cancellation/result fencing and exports. Analysis includes bounded full-file fingerprints, manifest hints, AST-based Python security checks and explicit truncation. Imported code is not executed or modified autonomously.

Demo Studio edits contextual storyboards; exports remain unverified drafts. Local Remotion rendering and model/benchmark demonstrations do not establish application-generation correctness.

`oryveta_engine.learning` compares submitted evidence and requires human review. It does not authenticate execution evidence, train a model, retrieve cross-session memory or promote its own production harness.

**Not implemented:** hosted factory execution, isolated arbitrary customer-code execution, full knowledge graph/analysis, autonomous verified Evolve fixes, AI-native application/package rewriting, custom Start New application generation, project on-call telemetry/correlation/repair, GitHub App repository publication, Slack integration, native mobile distribution, continuously running recursive improvement, enterprise SSO/billing or an availability SLA.

See [identity and testing](IDENTITY-WORKSPACES.md), [architecture](ARCHITECTURE.md) and the [staged roadmap](ROADMAP.md). A source change, local test, preview deployment and production release are different evidence levels.
