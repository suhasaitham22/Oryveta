# Identity, projects and private sessions

## Current boundary

The hosted React Studio uses Supabase Auth and PostgreSQL RLS. Its public configuration lives in `apps/web/studio/src/lib/publicConfig.js`; `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` can override it. Only publishable/anon keys belong in browser configuration. Vite rejects secret/user keys, and Vercel builds reject a configured origin absent from `apps/web/vercel.json`'s explicit `connect-src` policy.

GitHub provider availability is read from the project's real `/auth/v1/settings` response. An unavailable or unconfirmed provider stays disabled; the frontend cannot enable an unconfigured OAuth provider. Sign-in identifies a person, not repository authority. Repository access still requires a separate GitHub App, which is not implemented by this collaboration change.

The self-hosted FastAPI/SQLite engine retains a separate local identity. Hosted tokens are not forwarded into that engine and a cloud project is not an executed local project.

## Browser sessions and email links

The Supabase browser SDK uses PKCE, shared browser `localStorage`, automatic token refresh and server-verified `getUser()` identity. Shared storage is necessary for an email link opened in a new tab of the same browser. The original `sessionStorage` configuration failed that common flow; the regression now follows the actual Mailpit email in a separate tab and verifies restoration in the original tab.

PKCE remains bound to the requesting browser/device. A different browser/device has no verifier: request a new link there. Initialization/callback failures produce an actionable sign-in error rather than silently appearing successful. This release does not claim cross-device magic-link completion or a first-party HttpOnly BFF session.

Browser-managed tokens remain readable by same-origin JavaScript. Restrictive CSP, safe rendering, no untrusted scripts and explicit sign-out are important controls; localStorage is not a substitute for XSS prevention. Workspace state is keyed by the verified user and remounts on identity changes. Sign-out clears protected application state; use it on shared devices.

## Workspace, project and session access

`supabase/schema.sql` creates workspaces and provisions their creator's owner membership. Direct membership mutation remains unavailable to browser clients. Workspace-wide invitation administration is not added here.

`supabase/migrations/projects_and_project_membership.sql` adds persisted project briefs and explicit project membership:

| Project role | Read project | Edit brief | Invite/revoke members |
| --- | --- | --- | --- |
| Owner | Yes | Yes | Yes; owner cannot be removed/demoted |
| Admin | Yes | Yes | Yes; cannot remove the owner |
| Engineer | Yes | Yes | No |
| Reviewer | Yes | No | No |
| Viewer | Yes | No | No |

Project creation requires owner/admin/engineer membership in the target workspace. Joining a project does not join its workspace. Pending invitations disclose the project name to the intended recipient but grant no project access until accepted. Email acceptance requires the currently verified address; alias invitations bind to an immutable user ID. If an alias changes owners, an old invitation cannot be upgraded or retargeted: cancel it explicitly before inviting the new owner. Replaying an accepted invitation never recreates revoked membership.

`/workspace/projects` lists all projects the user may read, including projects from workspaces they cannot read. Privileged mutations use narrow security-definer RPCs with fixed search paths and explicit actor checks. Project tables expose SELECT only to authenticated roles, with RLS; browser clients have no direct mutation grants. Project audit events record IDs, actions, roles and timestamps, not briefs, prompts, addresses or secrets.

Conversations continue to use `chats`, `chat_shares` and `chat_messages`. A nullable `chats.project_id` associates a private conversation with a readable project. It does not change the conversation's audience. A project-only invitee may create a linked private conversation with `workspace_id = null`; an explicit workspace must match and be readable. Clients cannot reassign the project, workspace or owner through UPDATE.

Private chat invitations remain explicit viewer/editor grants with acceptance. Project/workspace membership grants no chat visibility. A session-only recipient can read the shared conversation without reading the linked project. In-app invitations do not send external notification emails.

Conversation details and sharing actions are tied to the chat that produced them, not just the current header. Old collection responses and post-navigation saves cannot replace a newer selection or draft. A successful send, conversation creation or invitation clears only the submitted value, preserving text entered while its acknowledgement was pending.

The chat view fetches the newest 200 messages in deterministic timestamp/id order and displays them chronologically. One extra row detects omitted older history, which is announced in the UI; earlier messages remain stored but are not shown in this bounded view. Sharing revocation identifies both the share and its intended conversation.

## Applying the schema

Use a dedicated project and inspect its existing schema before applying changes:

1. Apply `supabase/schema.sql` if the workspace foundation is absent.
2. Apply `supabase/migrations/private_chats_and_explicit_sharing.sql` if the private-chat foundation is absent. Its initial policy creation is not a repeatable migration runner.
3. Apply `supabase/migrations/projects_and_project_membership.sql` after those prerequisites. It is additive, preserves existing conversations and wraps table creation/RLS/grants in one transaction; execute the complete file rather than selected statements.
4. Apply `supabase/migrations/durable_factory_runtime.sql`, followed by `supabase/migrations/retained_attribution_and_lease_clock.sql`. The latter repairs retained attribution during account deletion and runtime lease timing. Applying schema does not start a worker.
5. Run all transactional RLS/lifecycle regressions on a controlled development/test database before rollout.
6. Deploy the frontend only after the target schema exists. A missing migration is shown as an actionable error, never replaced with pretend data.

These SQL files follow the repository's manual migration convention; do not assume `supabase db push` automatically applies unnumbered files. `supabase/config.toml` is for isolated local verification, not a production auth configuration to push remotely.

For an installation that already has the first four SQL files, apply only `retained_attribution_and_lease_clock.sql`. It preserves accepted/cancelled records after deleting their attribution account without allowing a successor account at the same email address to inherit an old grant. Rehearse this forward repair before production deployment; do not replay the private-chat initial policy setup.

## Real local auth and browser verification

Supabase CLI 2.121.0 provides an experimental native runtime for macOS arm64 and supported Linux hosts; no Docker or cloud credentials are required. The script runs actual PostgreSQL/RLS, GoTrue, PostgREST and Mailpit. Test emails stay in Mailpit and are never delivered externally.

```sh
npm --prefix apps/web/studio ci
python -m pip install 'httpx==0.28.1' 'playwright==1.64.1'
python -m playwright install chromium
export SUPABASE_HOME="$(mktemp -d)"
export SUPABASE_EXPERIMENTAL_STACK=1
umask 077
npx --yes supabase@2.121.0 start --runtime native --eager --output-format json > "$SUPABASE_HOME/connections.json"
python scripts/auth_ui_smoke.py --connections "$SUPABASE_HOME/connections.json"
npx --yes supabase@2.121.0 stack destroy --yes
```

The connection file contains local test secrets; never commit or upload it. The script refuses non-loopback endpoints and compiles a separate temporary Studio build using the local public configuration. SQL fixtures roll back; browser fixtures are removed with the isolated stack. `--skip-sql` is only for iterating against an already bootstrapped test stack. CI runs this same real-service path.

Exercised checks: new-tab email/PKCE login, reload, three independent accounts, project creation/invite/accept through the UI, read-only denial through real user tokens, private-session isolation, session-only sharing, revocation/replay, self-removing admin, sign-out, desktop and mobile-width Chromium rendering. SQL additionally covers anonymous callers, role escalation, owner protection, workspace mismatch and alias reassignment.

## Hosted rollout and remaining boundaries

Production project `nydtmiseclkwauiepqxn` has the project-membership, durable-runtime and retained-attribution/lease-clock migrations applied. Project and public runtime tables have RLS enabled, with no anonymous SELECT or direct authenticated INSERT/UPDATE/DELETE grants. Private leases are unreadable by authenticated clients. Site URL is `https://oryveta.vercel.app`; exact callbacks are allowlisted and GitHub/email providers are enabled.

The Oryveta GitHub OAuth App uses the exact callback `https://nydtmiseclkwauiepqxn.supabase.co/auth/v1/callback`, with identity-only profile/email scopes; it is not a repository-access GitHub App. Its secret is stored only in Supabase. The real production GitHub consent/callback, `getUser()` verification and Projects rendering passed. A new GitHub identity does not automatically inherit a differently addressed email account's workspaces.

`scripts/production_auth_smoke.py` is an explicit, opt-in deployed authorization check. It requires matching `--confirm-project nydtmiseclkwauiepqxn` and connection JSON on stdin. A protected server-side admin key creates three temporary, confirmed test users; normal Auth password grants supply their browser/user tokens. The administrative key is never injected into the browser, and no authentication response is mocked. This setup verifies production UI/RLS, not the email-delivery or GitHub-consent flow. Test identities and application rows are removed by recorded ID; provider audit logs may remain. Never run it automatically from untrusted PRs or upload the connection JSON/browser traces.

`--runtime` adds a designated worker and a successor identity at a deleted test account's address. It verifies production UI submission and download around a one-off local worker, idempotent admission, cancellation/late-publication fencing, worker revocation, retained account-deletion metadata and denial of inherited grants. Five temporary identities are removed by recorded ID. The worker receives only its own ordinary session in a private temporary credential file; the administrator key stays out of workers and browsers. This option is manual and opt-in, not a CI production job or evidence of always-on hosting.

The production security advisor reports authenticated-callable `SECURITY DEFINER` RPCs by design. These entrypoints are the controlled write boundary: anonymous execution is denied, search paths are fixed and each call checks its actor, resource role and, where applicable, worker identity and lease. Keep the warnings visible rather than granting direct table writes or changing to invoker mode to silence them. Leaked-password protection is also flagged; [Supabase requires Pro or above](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection), so it remains disabled under the no-paid-service requirement.

The default hosted Supabase email service has restrictions and is not a general-purpose production mail provider. Before launch, verify delivery configuration, rate limits, recovery, MFA/SSO requirements, backup/restore and incident controls. Factory execution, Slack integration and recursive learning remain separate roadmap milestones.
