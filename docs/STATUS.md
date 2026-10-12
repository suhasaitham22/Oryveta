# Oryveta implementation status

React/shadcn migration milestone — 2026-10-12.

The `apps/web/studio` Vite React app is the hosted product UI build and the self-hosted local UI at `/studio/` when FastAPI serves its production dist. The legacy vanilla-JS `apps/web/index.html` and root `/` path remain self-hosted compatibility paths. Hosted React and local FastAPI identity/engine sessions are deliberately separate; no hosted engine bridge exists.

**React product:** the selected MIT Vite/shadcn template supplies the Soft Modern responsive shell; scroll-linked artifact chapters explain Start New/Evolve, and Demo Studio is nested in each journey with retained editable context. The local-run panel reports recorded coarse lifecycle tasks, one elapsed timer, event timeline, result summary and cancellation; hosted mode shows an explicitly illustrative sequence. Reduced-motion and keyboard paths are covered by consumer browser smoke. This is a PR milestone, not a production release.

**Identity:** Supabase Auth email magic links are initiated only at a user's request. A successful email login has **not** been tested with a real mailbox or redirect. Project URL and publishable key are public browser configuration. **GitHub OAuth remains disabled**, pending secure GitHub OAuth App registration and provider settings in Supabase; GitHub repo access is a separate GitHub App permission workflow.

**Workspaces:** private Supabase schema and tenant RLS deployed and tested under simulated authenticated roles (PR #17). Real two-user browser tenant checks must pass before enterprise claims. React exposes workspace creation, rename, and switching through RLS-backed Supabase access.

**Demos:** `apps/web/studio/demo` owns vendored MIT snapcn/Remotion compositions for Start New, Evolve, Agent Evaluation, Private chats and local runs. Browser Demo Studio is an editable storyboard preview, not video generation; exports remain `verified:false`. MP4 rendering uses the separate local CLI and does not replace feature tests or human sign-off.

**Agent learning:** local Python evidence-gated evaluation (`oryveta_engine.learning`) does not run an autonomous self-training agent. Candidate promotion remains human-reviewed.

**Not implemented:** hosted FastAPI engine/worker, isolated code execution, production autonomous app generation, real GitHub repository App permissions, a fully functioning online PR/CI agent, secure enterprise invitations/billing, cloud-run Remotion rendering, continuously fine-tuned agents. Local `/studio/` can run deterministic starters and read-only heuristic analysis through the existing single-host worker; this is not hosted autonomous engineering.

See `docs/DEMO-STUDIO.md`, `docs/EVALUATION.md` and `docs/IDENTITY-WORKSPACES.md`. Do not label the hosted engine as live: frontend browser smoke and local worker smoke are distinct evidence.

**Chat sharing milestone (merged base #23):** Dedicated Supabase has owner-private chat/message storage, verified-email or immutable alias invitations, explicit acceptance and viewer/editor/revocation RLS. Synthetic role-level SQL tests pass; real mailbox delivery, two-user browser authorization and hosted AI responses remain unverified. No email notification delivery is claimed.
