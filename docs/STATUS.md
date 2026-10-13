# Oryveta implementation status

Navigation and dimensional interaction milestone — 2026-10-13 ([PR #26](https://github.com/suhasaitham22/Oryveta/pull/26), unmerged).

The `apps/web/studio` Vite React app produces the hosted product UI in `dist` and the self-hosted local UI in `dist-local`; FastAPI serves the latter at `/studio/` with extensionless deep-route fallback and strict asset/API path handling. The legacy vanilla-JS `apps/web/index.html` and root `/` path remain self-hosted compatibility paths. Hosted React and local FastAPI identity/engine sessions are deliberately separate; no hosted engine bridge exists.

**React product:** a compact shared header connects distinct Home, About, What We Do and Workspace pages. React Router provides real URLs, linked breadcrumbs, native Back/Forward and contextual `?tab=brief|local|demo` history; Home retains an in-app Back action when history exists. Owner-keyed, root-held drafts survive internal navigation and clear on sign-out/identity change. The Galileo-led Home uses original lazy Three.js geometry with visible entrance, viewpoint and native-scroll changes, not CSS relief loops. Motion 14.1.0 retains readable DOM entrances and real run-layout transitions. Live reduced-motion and unavailable-WebGL alternatives preserve information and navigation. Demo Studio stays contextual. Hosted mode has no coding engine; local runs still report persisted states, events, findings and cancellation. This is a new unmerged PR workstream, not a production release; historical licenses remain preserved.

**Identity:** Supabase Auth email magic links are initiated only at a user's request. A successful email login has **not** been tested with a real mailbox or redirect. Project URL and publishable key are public browser configuration. **GitHub OAuth remains disabled**, pending secure GitHub OAuth App registration and provider settings in Supabase; GitHub repo access is a separate GitHub App permission workflow.

**Workspaces:** private Supabase schema and tenant RLS deployed and tested under simulated authenticated roles (PR #17). Real two-user browser tenant checks must pass before enterprise claims. React exposes workspace creation, rename, and switching through RLS-backed Supabase access.

**Demos:** `apps/web/studio/demo` owns vendored MIT snapcn/Remotion compositions for Start New, Evolve, Agent Evaluation, Private chats, local runs and `guided-workflow`. Browser Demo Studio is an editable contextual storyboard, not video generation; exports remain `verified:false`. MP4 rendering uses the separate local CLI and does not replace feature tests or human sign-off.

**Agent learning:** local Python evidence-gated evaluation (`oryveta_engine.learning`) does not run an autonomous self-training agent. Candidate promotion remains human-reviewed.

**Not implemented:** hosted FastAPI engine/worker, isolated code execution, production autonomous app generation, real GitHub repository App permissions, a fully functioning online PR/CI agent, secure enterprise invitations/billing, cloud-run Remotion rendering, continuously fine-tuned agents. Local `/studio/` can run deterministic starters and read-only heuristic analysis through the existing single-host worker; this is not hosted autonomous engineering.

See `docs/DEMO-STUDIO.md`, `docs/EVALUATION.md` and `docs/IDENTITY-WORKSPACES.md`. Do not label the hosted engine as live: frontend browser smoke and local worker smoke are distinct evidence.

**Local verification for this milestone:** hosted and genuine self-hosted browser smoke passed desktop/mobile navigation, direct reload, Home Back/draft restoration, query history, contextual exports and cancellation. A separate isolated runtime created/exported a starter, ran the real worker to completion, displayed findings, restored selected project/run after Home/Back, canceled another job and cleared drafts on disconnect. Temporary axe checks found no WCAG A/AA violations on seven changed routes at desktop/mobile sizes. Python: 145 tests passed, 88.24% branch-aware coverage, Ruff/compilation/dependency checks passed. Hosted/local Vite builds pass without the old oversized-chunk advisory. These are local results, not remote CI, deployment, mailbox or two-account auth verification.

**Chat sharing milestone (merged base #23):** Dedicated Supabase has owner-private chat/message storage, verified-email or immutable alias invitations, explicit acceptance and viewer/editor/revocation RLS. Synthetic role-level SQL tests pass; real mailbox delivery, two-user browser authorization and hosted AI responses remain unverified. No email notification delivery is claimed.


**Backend Evolve hardening (2026-10-12):** Static analyzer improvements include
complete bounded file fingerprints, manifest-derived framework inventory,
AST-based Python security checks (avoid comment/string false positives),
explicit findings truncation, safer ZIP root retention and rollback cleanup.
This hardening **does not** add hosted repository imports, GitHub App/private
repository permissions, sandbox execution, or autonomous verified fixes.
