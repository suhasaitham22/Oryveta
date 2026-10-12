# Oryveta implementation status

React/shadcn migration milestone — 2026-10-12.

The `apps/web/studio` Vite React app is the proposed **hosted product UI**, served via the `apps/web/vercel.json` Vercel build output. The legacy vanilla-JS `apps/web/index.html` and FastAPI local backend are retained as self-hosted compatibility paths; React replaces the hosted interface first.

**React product:** mobile/desktop responsive premium glass design, semantic navigation, meaningful scroll narrative, shadcn/Radix UI primitives, reduced-motion support, interactive Start New and Evolve planning flows, Demo Studio with edit/preview/export, and a truthful agent evidence lab. Build and React browser smoke in GitHub Actions are release gates.

**Identity:** Supabase Auth email magic links are initiated only at a user's request. A successful email login has **not** been tested with a real mailbox or redirect. Project URL and publishable key are public browser configuration. **GitHub OAuth remains disabled**, pending secure GitHub OAuth App registration and provider settings in Supabase; GitHub repo access is a separate GitHub App permission workflow.

**Workspaces:** private Supabase schema and tenant RLS deployed and tested under simulated authenticated roles (PR #17). Real two-user browser tenant checks must pass before enterprise claims. React exposes workspace creation, rename, and switching through RLS-backed Supabase access.

**Demos:** `apps/web/studio/demo` owns the vendored MIT-licensed snapcn TextReveal and Remotion compositions for Start New, Evolve and Agent Evaluation. Website Demo Studio provides storyboards, *not browser-rendered videos*. Rendering MP4 requires the separate local CLI. Every new customer-facing feature must have a story in `apps/web/studio/public/demo-stories.json`.

**Agent learning:** local Python evidence-gated evaluation (`oryveta_engine.learning`) does not run an autonomous self-training agent. Candidate promotion remains human-reviewed.

**Not implemented:** hosted FastAPI engine/worker, isolated code execution, production autonomous app generation, real GitHub repository App permissions, a fully functioning online PR/CI agent, secure enterprise invitations/billing, cloud-run Remotion rendering, continuously fine-tuned agents.

See `docs/DEMO-STUDIO.md`, `docs/EVALUATION.md` and `docs/IDENTITY-WORKSPACES.md`. Do not label this milestone deployed until Vercel confirms READY on the new React app SHA and frontend smoke passes.
