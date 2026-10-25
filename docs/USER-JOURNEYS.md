# End-to-end user journeys and acceptance criteria

Oryveta has two entry points: Start New for a new application, and Evolve for an existing application or package. The complete agent-driven journeys below are acceptance targets, not current feature claims. Today, hosted users can manage projects and private conversations and export planning/demo drafts; the self-hosted engine provides starter code and read-only source analysis. See [STATUS.md](STATUS.md) for exercised deployment evidence.

## Public visitor and GitHub login

The landing page explains Start New and Evolve before sign-in. Hosted GitHub sign-in and project/private-conversation authorization have production verification; email sign-in depends on configured delivery. The local engine uses its own session and does not inherit cloud access. **Installing the planned GitHub App for source access is separate from GitHub sign-in**: logging in does not authorize private repository imports or publication.

Test denial, expired state, revoked app, private repository restrictions, unavailable GitHub, invalid session and account deletion. Never use a publicly reachable "demo login" to bypass authentication.

## Target Start New flow

Brief → scope proposal and acceptance criteria → tech stack recommendation → design and architecture → approved implementation plan → repository creation → model-backed feature implementation → automated independent checks → user preview and revision loop → reviewed GitHub publishing → authorized deployment → measured result and handover.

Required states: Draft, Planning, Awaiting Approval, Queued, Running, Verifying, Needs Review, Completed, Failed, Canceled. Refreshing or closing the browser must not destroy persisted work.

## Target Evolve flow

GitHub App/ZIP → repository map → categorized findings → rank impact/risk → select work → optional human approval → isolated patch → regression/security/performance verification → reviewable diff and PR → post-change verification. Dead-code analysis is conservative because dynamic references can defeat static inspection.

For a potential Rust rewrite, include a baseline, interoperability/migration strategy, data format compatibility tests, behavior parity, rollback and measurable cost/latency tradeoffs. Require explicit approval; never silently replace working language stacks.

## Target 24/7 task lifecycle

Durable repository analysis is deployed to Supabase and verified through the production UI with a one-off local worker. No always-on cloud worker host is configured. The full agent lifecycle below still requires that infrastructure and the planned implementation/verifier tools.

Authenticated request persists to central SQL state → queue/event wakes remote worker → worker claims expiring lease with idempotency → periodically checkpoints and reports state → stores artifacts and evidence → requests approval for sensitive operations → resumes independently of the browser. Recover transparently from worker outages without duplicate side effects.

## Target consultancy case

Client manager uploads requirements, assigns milestones and owners, reviews proposed work, approves permitted operations, inspects cost and evidence, and signs off release. Workspaces, client artifacts, repository permissions, model prompts and memory are strongly tenant-isolated.

## UX quality bar

Mobile + desktop, accessible keyboard focus, high contrast, reduced motion, loading/success/error/empty states, streaming explanations without fabricated certainty, simple approvals, safe cancel/retry, clear "preview" labeling. Never turn a sample metric into a verified result.
