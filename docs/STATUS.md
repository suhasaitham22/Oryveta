# Oryveta implementation status

Product-focused frontend refinement on `feat/product-surface-refinement`, building on merged navigation PR [#26](https://github.com/suhasaitham22/Oryveta/pull/26). This refinement is a locally verified review candidate, not a production deployment; the local backend remains separate.

The `apps/web/studio` Vite React app produces the hosted product UI in `dist` and the self-hosted local UI in `dist-local`; FastAPI serves the latter at `/studio/` with extensionless deep-route fallback and strict asset/API path handling. The legacy vanilla-JS `apps/web/index.html` and root `/` path remain self-hosted compatibility paths. Hosted React and local FastAPI identity/engine sessions are deliberately separate; no hosted engine bridge exists.

**React product:** a compact shared header connects distinct Home, About, What We Do and Workspace pages. React Router provides real URLs, linked breadcrumbs, native Back/Forward and contextual `?tab=brief|local|demo` history; Home retains an in-app Back action when history exists. Owner-keyed, root-held drafts survive internal navigation and clear on sign-out/identity change. The Galileo-led Home now pairs concrete product copy with original readable canvas-textured Three.js document panels. Artifact selection brings the relevant document forward; live reduced-motion and unavailable-WebGL modes expose the same content semantically without clipping. Overview resumes actual open work, and Local run prioritizes the selected source, recorded state and latest results while creation/import remains available in a secondary disclosure. Demo Studio stays contextual. Hosted mode has no coding engine; real local runs retain persisted events, findings, technology profiles and cancellation. Historical licenses remain preserved.

**Identity:** Supabase Auth email magic links are initiated only at a user's request. A successful email login has **not** been tested with a real mailbox or redirect. Project URL and publishable key are public browser configuration. **GitHub OAuth remains disabled**, pending secure GitHub OAuth App registration and provider settings in Supabase; GitHub repo access is a separate GitHub App permission workflow.

**Workspaces:** private Supabase schema and tenant RLS deployed and tested under simulated authenticated roles (PR #17). Real two-user browser tenant checks must pass before enterprise claims. React exposes workspace creation, rename, and switching through RLS-backed Supabase access.

**Demos:** `apps/web/studio/demo` owns vendored MIT snapcn/Remotion compositions for Start New, Evolve, Agent Evaluation, Private chats, local runs and `guided-workflow`. Browser Demo Studio is an editable contextual storyboard, not video generation; exports remain `verified:false`. MP4 rendering uses the separate local CLI and does not replace feature tests or human sign-off.

**Agent learning:** local Python evidence-gated evaluation (`oryveta_engine.learning`) does not run an autonomous self-training agent. Candidate promotion remains human-reviewed.

**Not implemented:** hosted FastAPI engine/worker, isolated code execution, production autonomous app generation, real GitHub repository App permissions, a fully functioning online PR/CI agent, secure enterprise invitations/billing, cloud-run Remotion rendering, continuously fine-tuned agents. Local `/studio/` can run deterministic starters and read-only heuristic analysis through the existing single-host worker; this is not hosted autonomous engineering.

See `docs/DEMO-STUDIO.md`, `docs/EVALUATION.md` and `docs/IDENTITY-WORKSPACES.md`. Do not label the hosted engine as live: frontend browser smoke and local worker smoke are distinct evidence.

**Local verification for this frontend refinement:** hosted and genuine self-hosted compiled browser smoke passes on desktop/mobile, including direct routes, native history, breadcrumb/draft restoration, query tabs, contextual exports, real import/cancel and reduced motion. New consumer regressions require a fresh file after successful import and prevent static document clipping. An isolated real worker completed a synthetic source review; the UI retained the exact project/run through Overview Continue, distinguished older runs from latest project analysis, exported a real starter ZIP and cleared drafts on disconnect. Manifest-derived FastAPI/Express hints and an actual 400-of-412 truncated result were exercised without executing imported code. Temporary axe checks pass on the affected desktop/mobile surfaces and semantic alternatives. Renderer checks observed settled/offscreen draws stopping, explicit owned-texture/shadow disposal, context release and zero Three resources on direct workspace entry. Both builds and seven storyboard checks pass. The lazy Three chunk is 508.38 kB minified (130.62 kB gzip), producing the unchanged default Vite advisory. Remotion rendering/TypeScript gates were not rerun after removing confirmed disposable demo dependencies to recover browser scratch capacity. Prior backend test results are not claimed as new verification; remote CI and preview are separate release-time checks, not replaced by these local results.

**Chat sharing milestone (merged base #23):** Dedicated Supabase has owner-private chat/message storage, verified-email or immutable alias invitations, explicit acceptance and viewer/editor/revocation RLS. Synthetic role-level SQL tests pass; real mailbox delivery, two-user browser authorization and hosted AI responses remain unverified. No email notification delivery is claimed.


**Backend Evolve hardening (2026-10-12):** Static analyzer improvements include
complete bounded file fingerprints, manifest-derived framework inventory,
AST-based Python security checks (avoid comment/string false positives),
explicit findings truncation, safer ZIP root retention and rollback cleanup.
This hardening **does not** add hosted repository imports, GitHub App/private
repository permissions, sandbox execution, or autonomous verified fixes.
