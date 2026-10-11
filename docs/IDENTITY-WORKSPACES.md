# Identity and workspace foundations (Phase 1)

**State (2026-10-10):** Dedicated Oryveta Supabase project is provisioned, workspace schema and RLS applied, security advisors clear. GitHub OAuth provider is **not configured**, so the production login remains gated off. This is not a claim of live authentication.

## Product decision

ORYVETA is a company-grade engineering workspace, not a demo playground. The hosted site must open at a polished sign-in gate. GitHub is the first identity provider. GitHub repository permissions are a separate GitHub App consent flow and **must not** be inferred from identity login. A visitor can explicitly choose **Explore preview** without a fake account or saved workspace.

After sign-in, the first meaningful action is to create/select a workspace. An account may own multiple workspaces, and the data model reserves owner/admin/engineer/reviewer/viewer roles for later verified invitations. **V1 only provisions the owner membership**. Do not render pretend collaborators, connected repositories, job runs, invoices or usage data.

## Stack and rationale

- **Identity:** Supabase Auth with GitHub OAuth and PKCE via pinned supabase-js SDK. Public static Vercel frontend; no hosted FastAPI or worker in this phase.
- **Storage:** dedicated Supabase PostgreSQL project. `supabase/schema.sql` contains RLS-enforced `workspaces` and `workspace_memberships`. All exposed tables have RLS.
- **Sessions:** sessionStorage-backed PKCE session for the browser MVP, with SDK refresh/revocation; not long-lived HttpOnly server cookies. This is a conscious security/UX tradeoff until a first-party BFF is deployed. Never store provider secrets or service-role keys in the browser.
- **Authorization:** PostgreSQL RLS controls workspace read/write, not hidden UI. Direct client mutations of membership are disallowed. Security-definer helpers live in non-exposed `private` schema with explicit grants and search paths.
- **Separation:** local FastAPI GitHub OAuth remains unchanged for self-hosted mode. The hosted frontend uses Supabase Auth only when explicitly configured; it must never silently fall back to demo login.

## Setup checklist (requires owner actions)

1. **Completed:** Dedicated project `nydtmiseclkwauiepqxn` created in the `oryveta` Free-plan organization (US West, $0/month base). [Project dashboard](https://supabase.com/dashboard/project/nydtmiseclkwauiepqxn).
2. **Partially complete:** `supabase/schema.sql` applied as migration `initial_workspace_identity_rls`. Both workspace tables have RLS (4 workspace policies, 1 membership policy); Supabase security advisors report zero findings. Cross-account tenant isolation with two actual signed-in users is **still pending**. Performance advisor reports one expected unused index on the empty membership table.
3. In [GitHub Developer Settings](https://github.com/settings/developers), create an **OAuth App** for Oryveta. Homepage: `https://oryveta.vercel.app`. Callback: `https://<project-ref>.supabase.co/auth/v1/callback`. Store its **client secret only in Supabase Auth provider settings**, never in GitHub or frontend files.
4. In Supabase Auth, enable GitHub provider, set Site URL `https://oryveta.vercel.app` and allow the exact production redirect. For previews, allowlist explicit preview URLs only.
5. **Staged safely:** `apps/web/cloud-config.js` contains only the project URL and **publishable** key, which is public by design. `githubEnabled: false` deliberately hides the sign-in action until the GitHub provider and redirect settings are configured and checked. Flip to `true` through a reviewed PR after steps 3–4.
6. Verify sign-in, callback, refresh, logout, denied consent, unauthorized data access, workspace create/rename and a cross-account isolation attempt. Do not mark auth production-ready without this integration test.
7. Configure incident logging, abuse/rate controls, MFA/SSO requirements, session lifecycle and recovery before serving enterprise clients.

## Current limitations

The UI can be reviewed without provider credentials, but real GitHub sign-in cannot complete until GitHub OAuth provider setup and a controlled enablement PR. Vercel still hosts only a frontend: creating/importing actual code repositories, agent execution and Ollama remain self-hosted. Team invitation, organization transfer, billing, audit history and hosted job execution are **future milestones**.
