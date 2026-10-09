# End-to-end user journeys and acceptance criteria

## Public visitor and GitHub login

Landing introduces two choices: Start New and Evolve. Sign-in presents a single **Continue with GitHub** action, a privacy explanation and minimal identity scope. Verify OAuth state/callback, create HttpOnly Secure sessions, handle logout and expiry. **Installing the GitHub App for source access is separate from GitHub sign-in** and optional until needed. This is a target flow, not active on the public static preview.

Test denial, expired state, revoked app, private repository restrictions, unavailable GitHub, invalid session and account deletion. Never use a publicly reachable "demo login" to bypass authentication.

## Start New flow

Brief → scope proposal and acceptance criteria → tech stack recommendation → design and architecture → approved implementation plan → repository creation → model-backed feature implementation → automated independent checks → user preview and revision loop → reviewed GitHub publishing → authorized deployment → measured result and handover.

Required states: Draft, Planning, Awaiting Approval, Queued, Running, Verifying, Needs Review, Completed, Failed, Canceled. Refreshing or closing the browser must not destroy persisted work.

## Evolve flow

GitHub App/ZIP → repository map → categorized findings → rank impact/risk → select work → optional human approval → isolated patch → regression/security/performance verification → reviewable diff and PR → post-change verification. Dead-code analysis is conservative because dynamic references can defeat static inspection.

For a potential Rust rewrite, include a baseline, interoperability/migration strategy, data format compatibility tests, behavior parity, rollback and measurable cost/latency tradeoffs. Require explicit approval; never silently replace working language stacks.

## 24/7 task lifecycle

Authenticated request persists to central SQL state → queue/event wakes remote worker → worker claims expiring lease with idempotency → periodically checkpoints and reports state → stores artifacts and evidence → requests approval for sensitive operations → resumes independently of the browser. Recover transparently from worker outages without duplicate side effects.

## Consultancy case

Client manager uploads requirements, assigns milestones and owners, reviews proposed work, approves permitted operations, inspects cost and evidence, and signs off release. Workspaces, client artifacts, repository permissions, model prompts and memory are strongly tenant-isolated.

## UX quality bar

Mobile + desktop, accessible keyboard focus, high contrast, reduced motion, loading/success/error/empty states, streaming explanations without fabricated certainty, simple approvals, safe cancel/retry, clear "preview" labeling. Never turn a sample metric into a verified result.
