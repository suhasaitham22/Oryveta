# Authentication, authorization and trust boundaries

## GitHub login is not GitHub repository access

**GitHub OAuth** (Supabase Auth PKCE for the hosted frontend when configured, FastAPI OAuth in local prototype) authenticates an identity with minimal scopes. A **separate GitHub App** with per-repository permissions grants source access, webhook events and approved PR operations. Starting a new app without GitHub repo access should still be possible.

## Target roles

Organization Owner, Admin, Engineer, Reviewer and Viewer; per-client/per-engagement/per-repository roles; machine identities with narrower grants than users. Audit all sensitive actions. Check access for every read, write, download, approval and artifact fetch, not merely route visibility.

## Authentication controls

OAuth state and redirect validation; PKCE where applicable; session expiry/revocation; secure HttpOnly/SameSite cookies over HTTPS; CSRF protection; brute-force/rate protections; MFA/SSO options for consultancy deployments; safe error handling. Never enable local/demo login on the production host.

The current hosted client uses Supabase-managed browser sessions with shared browser storage so PKCE email links work in a new tab. It verifies identity with `getUser()` and handles callback failure; it is not a first-party HttpOnly BFF. Same-origin JavaScript can read these tokens, so restrictive CSP, safe rendering and no untrusted scripts remain mandatory. Production browser/session policy and MFA/SSO are separate launch requirements.

Project grants are enforced by PostgreSQL RLS and narrow RPCs. Alias invitations bind to immutable user IDs; a reassigned alias cannot amend the former recipient's offer. Accepted-invitation replay cannot restore revoked membership. Project membership does not expose a private chat, and a chat invitation does not expose its project.

## Agent privileges

A model may recommend a tool call but cannot authorize it. The host enforces tenant scope, path/network policies, compute budget, secrets scope, repository installation permissions and approved side effects.

**Explicit human approval** for high-blast-radius production deployment, destructive migrations, force pushes, secret rotation/security exemptions and actions with legal/financial impact. Capture approved commit/policy versions.

### Local repair CLI: where authority actually comes from

The operator-run repair/reverification CLI has no account, session, role or grant of its own. Its entire authority is the conjunction of two things the operator supplies at invocation: the **reviewed configuration file** (model and runner identities, exact read/write path allowlists, the check suites and their expected values, and the budgets) and the **operator's own OS access** to the source archive, the Docker context and the private run/evidence directories. Nothing else can widen it.

- The configuration is read from a path **outside** the source archive, and the imported source cannot register a tool, add a path, change a check, raise a budget, choose a model or select an image. Source files and tool output are untrusted data.
- A receipt is a record, not a credential. It cannot re-establish a grant, re-authorize a source, vouch for a host or let a later run skip the operator's configuration. Re-verifying a candidate therefore requires the reviewed **current** configuration and an authorized source archive supplied again by the operator — authority is never recovered from evidence.
- Hashes bind bytes. They do not authenticate the producer, prove that work happened, or protect the operator against a malicious host or a tampered image. There is no signing, no remote attestation and no third-party verification service.
- The container policy (no network, non-root, dropped capabilities, no-new-privileges, read-only root/source, bounded tmpfs/memory/CPU/PIDs/output, no host credentials, no Docker socket) is local defense in depth for *operator-approved* source and *trusted* images. Docker shares a kernel and the host administrator remains trusted; this is not a multi-tenant boundary and must not be used to run code you do not already trust enough to read.
- A `needs_review` status means only that the operator's declared contracts held. It is not approval, not permission to publish and not a correctness claim.

## Sandbox threats

Repository instructions, Markdown docs and package outputs are untrusted and can contain prompt injection. Assume generated code may be malicious. Use restricted isolated executions, CPU/memory/time limits, network deny-by-default, no ambient credentials, path normalization, ZIP size limits, SSRF protection, symlink/archive validation and dependency review. Note that imported source can read whatever files its own archive contains, even when the model's read allowlist is narrower — the allowlist bounds the *model*, not the code the checks execute.

## Multi-tenant threat model

Cross-tenant IDOR; leaking code into prompts/training; compromised GitHub App; forged webhooks; dependency hijack; unsafe shell/network execution; secret leakage in logs; worker crash with duplicate external actions; tampered artifact storage; OAuth failure. Verify fixes with automated negative tests and adversarial reviews.

## Release gates

Independent tenant access tests, threat modeling, secret scanners, dependency audits, critical-path e2e, rollback drills, monitored auth, incident response and backup restoration remain release gates. Production project RLS/grants, GitHub OAuth and controlled multi-user UI/authorization checks pass. Local email/PKCE uses Mailpit; general production email delivery, enterprise identity governance and operated recovery remain separate requirements. The operator-run local Docker check policy is explicitly **not** the production multi-tenant execution boundary and does not satisfy any of these gates; arbitrary customer code must not be executed until a hardened per-tenant runtime exists. No compliance certification or availability guarantee is offered. See [IDENTITY-WORKSPACES.md](IDENTITY-WORKSPACES.md) for exact boundaries and test methods.

**Report observed advisor findings, not an assumed clean bill of health.** Recorded rollout evidence includes the intentional authenticated `SECURITY DEFINER` RPC write boundary and disabled leaked-password protection, whose provider requirements are documented [here](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection). Preserve anonymous denial, fixed search paths and actor/role/lease checks; never grant direct writes or change RPC modes merely to silence a warning. Record findings and reviewed exceptions from a fresh check. A clean result may be reported only when actually observed; historical findings and unverified paid-plan controls must not be silently erased.
