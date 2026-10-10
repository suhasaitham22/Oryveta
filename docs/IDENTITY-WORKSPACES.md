# Identity and workspace foundations (Phase 1)

**State:** Code and SQL review only until a dedicated Supabase project and GitHub OAuth provider are configured. This is not a claim of live authentication.

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

1. Select which Supabase organization should own a **new dedicated Oryveta project**. Never reuse another app's database. Supabase project pricing must be checked and confirmed before creation; prefer free tier.
2. Create the project; run the reviewed `supabase/schema.sql` using SQL editor or a migration. Run Supabase database/security advisors and verify RLS using two independent test accounts.
3. In [GitHub Developer Settings](https://github.com/settings/developers), create an **OAuth App** for Oryveta. Homepage: `https://oryveta.vercel.app`. Callback: `https://<project-ref>.supabase.co/auth/v1/callback`. Store its **client secret only in Supabase Auth provider settings**, never in GitHub or frontend files.
4. In Supabase Auth, enable GitHub provider, set Site URL `https://oryveta.vercel.app` and allow the exact production redirect. For previews, allowlist explicit preview URLs only.
5. Put only the Supabase project URL and **publishable** key in `apps/web/cloud-config.js`. Review key scope. A publishable key is public by design.
6. Verify sign-in, callback, refresh, logout, denied consent, unauthorized data access, workspace create/rename and a cross-account isolation attempt. Do not mark auth production-ready without this integration test.
7. Configure incident logging, abuse/rate controls, MFA/SSO requirements, session lifecycle and recovery before serving enterprise clients.

## Current limitations

The UI can be reviewed without provider credentials, but a real GitHub sign-in cannot complete until steps 1–5 are configured. Vercel still hosts only a frontend: creating/importing actual code repositories, agent execution and Ollama remain self-hosted. Team invitation, organization transfer, billing, audit history and hosted job execution are **future milestones**.
