# End-to-end user journeys and acceptance criteria

Oryveta has two entry points: Start New for a new application, and Evolve for an existing application or package. The complete journeys below remain acceptance targets. Production offers collaboration, planning exports and durable analysis. The working tree adds the bounded Reviewed Evolve workflow described in [IMPLEMENTATION.md](IMPLEMENTATION.md#reviewed-evolve-worker), including queued execution, independent reviews, protected checks, human candidate decisions and scoped lessons. It is not full application generation, private-repository publication or an operated cloud service. Keep production, merged source and working-tree verification distinct; dated evidence belongs in [STATUS.md](STATUS.md).

## Public visitor and GitHub login

The landing page explains Start New and Evolve before sign-in. Hosted GitHub sign-in and project/private-conversation authorization have production verification; email sign-in depends on configured delivery. The local engine uses its own session and does not inherit cloud access. **Installing the planned GitHub App for source access is separate from GitHub sign-in**: logging in does not authorize private repository imports or publication.

Test denial, expired state, revoked app, private repository restrictions, unavailable GitHub, invalid session and account deletion. Never use a publicly reachable "demo login" to bypass authentication.

## Target Start New flow

Brief → scope proposal and acceptance criteria → tech stack recommendation → design and architecture → approved implementation plan → repository creation → model-backed feature implementation → automated independent checks → user preview and revision loop → reviewed GitHub publishing → authorized deployment → measured result and handover.

Required states: Draft, Planning, Awaiting Approval, Queued, Running, Verifying, Needs Review, Completed, Failed, Canceled. Refreshing or closing the browser must not destroy persisted work.

## Target Evolve flow

GitHub App/ZIP → repository map → categorized findings → rank impact/risk → select work → optional human approval → isolated patch → regression/security/performance verification → reviewable diff and PR → post-change verification. Dead-code analysis is conservative because dynamic references can defeat static inspection.

Independent re-check, available locally today: a reviewer holding a candidate archive, the original source archive and the reviewed operator configuration can re-run the declared checks with no model at all (`--candidate-zip`). The run validates that only allowlisted files changed, reproduces the baseline, executes every declared case in fresh local containers and records a new private receipt in `mode='verification'`. The acceptance criterion for this journey is that a reviewer never has to trust the producing agent's own claim — not that re-verification approves, resumes or publishes anything.

For a potential Rust rewrite, include a baseline, interoperability/migration strategy, data format compatibility tests, behavior parity, rollback and measurable cost/latency tradeoffs. Require explicit approval; never silently replace working language stacks.

## Target 24/7 task lifecycle

Durable repository analysis is deployed to Supabase and verified through the production UI with a one-off local worker. The always-on cloud worker host is still absent. The full agent lifecycle below therefore still requires that infrastructure, plus hosted equivalents of the implementation/verifier tools — the local CLI already provides a controller-owned verifier on an operator's own machine, so what is missing here is hosted execution rather than the tooling itself.

Authenticated request persists to central SQL state → queue/event wakes remote worker → worker claims expiring lease with idempotency → periodically checkpoints and reports state → stores artifacts and evidence → requests approval for sensitive operations → resumes independently of the browser. Recover transparently from worker outages without duplicate side effects.

## Target consultancy case

Client manager uploads requirements, assigns milestones and owners, reviews proposed work, approves permitted operations, inspects cost and evidence, and signs off release. Workspaces, client artifacts, repository permissions, model prompts and memory are strongly tenant-isolated.

## UX quality bar

Mobile + desktop, accessible keyboard focus, high contrast, reduced motion, loading/success/error/empty states, streaming explanations without fabricated certainty, simple approvals, safe cancel/retry, clear "preview" labeling. Never turn a sample metric into a verified result.
