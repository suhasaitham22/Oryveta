# Authentication, authorization and trust boundaries

## GitHub login is not GitHub repository access

**GitHub OAuth** (Supabase Auth PKCE for the hosted frontend when configured, FastAPI OAuth in local prototype) authenticates an identity with minimal scopes. A **separate GitHub App** with per-repository permissions grants source access, webhook events and approved PR operations. Starting a new app without GitHub repo access should still be possible.

## Target roles

Organization Owner, Admin, Engineer, Reviewer and Viewer; per-client/per-engagement/per-repository roles; machine identities with narrower grants than users. Audit all sensitive actions. Check access for every read, write, download, approval and artifact fetch, not merely route visibility.

## Authentication controls

OAuth state and redirect validation; PKCE where applicable; session expiry/revocation; secure HttpOnly/SameSite cookies over HTTPS; CSRF protection; brute-force/rate protections; MFA/SSO options for consultancy deployments; safe error handling. Never enable local/demo login on the production host.

## Agent privileges

A model may recommend a tool call but cannot authorize it. The host enforces tenant scope, path/network policies, compute budget, secrets scope, repository installation permissions and approved side effects.

**Explicit human approval** for high-blast-radius production deployment, destructive migrations, force pushes, secret rotation/security exemptions and actions with legal/financial impact. Capture approved commit/policy versions.

## Sandbox threats

Repository instructions, Markdown docs and package outputs are untrusted and can contain prompt injection. Assume generated code may be malicious. Use restricted isolated executions, CPU/memory/time limits, network deny-by-default, no ambient credentials, path normalization, ZIP size limits, SSRF protection, symlink/archive validation and dependency review.

## Multi-tenant threat model

Cross-tenant IDOR; leaking code into prompts/training; compromised GitHub App; forged webhooks; dependency hijack; unsafe shell/network execution; secret leakage in logs; worker crash with duplicate external actions; tampered artifact storage; OAuth failure. Verify fixes with automated negative tests and adversarial reviews.

## Release gates

Independent tenant access tests, threat modeling, secret scanners, dependency audits, critical-path e2e, rollback drills, monitored auth, incident response and backup restoration. **Hosted GitHub OAuth is not yet enabled.** The hosted sign-in gate and workspace UI are implemented in a review branch; production sign-in requires a dedicated Supabase project, configured GitHub OAuth provider and live isolation tests. See [IDENTITY-WORKSPACES.md](IDENTITY-WORKSPACES.md).
