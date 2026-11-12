# Product specification and use cases

## Product in plain language

Oryveta is an open-source software delivery workspace for developers, independent builders, consultants and teams. Start New organizes a new application; Evolve organizes a change to an existing application or package. Requirements, source findings and private collaboration stay connected to the work.

The target is an **AI software factory**: agents plan, implement and independently test changes; people review the results and approve publishing. This specification defines that target, not a claim that every capability is live.

Production provides collaboration, planning/demo exports and durable analysis with operator-started workers; no operated cloud coding service is deployed. The working tree additionally provides Reviewed Evolve: project-authorized queued changes, independently reviewed stages, protected verification, exact-candidate human decisions and scoped lessons. It requires the new migration and provisioned model/runner compute. The legacy self-hosted engine and standalone repair CLI remain separate entry points.

**Where statements apply.** *Production* is the deployed Studio; *`main`* is merged source; *this working tree* includes the new Reviewed Evolve implementation. Source, local test evidence, preview deployments and customer outcomes are different evidence levels.

## First cohort and commercial shape

The initial target hypothesis — unvalidated — is a **small engineering team maintaining an existing codebase**, with the first qualification cohort being **Python services that have a runnable test suite**. The entry point is deliberately narrow: one known defect or small maintenance change, repaired on the team's own compute, returned as a reviewable patch with a reproducible verification record rather than a chat transcript. The long-term product remains the full Start New / Evolve factory described below; the narrow cohort is how it is entered, not a reduction of the goal.

Two plans are published: **Community**, where the software is $0 and open source and the hosted workspace is free during preview subject to documented capacity; and a **proposed** Team plan that is not billable because billing, metering and its workspace-level features do not exist. Neither plan includes hosted compute. Nothing already available is paywalled by this, later hosted-terms changes require advance notice, consent and an export path, and commercial use of the hosted site needs a compliant hosting entitlement that is not yet in evidence. See [PRICING.md](PRICING.md) for the buyer/job hypothesis, availability boundaries, preconditions and the evidence gates that must produce data before any charge.

## Locked primary product experiences

### 1. Start New — create a new repository and product

**Goal:** User describes a software product; Oryveta plans, codes, tests, and prepares a complete runnable repository.

Target acceptance journey:
1. Collect purpose, target users, key features, non-functional constraints, budget and preferred stack (or recommend one).
2. Generate a versioned requirements document, architecture plan, acceptance tests, and implementation milestones.
3. Show a design preview with explicit approval for significant changes.
4. Create an isolated working tree with real application source, dependencies, documentation, tests, CI workflow and deployment manifests.
5. Use a model-backed coding harness to implement **specific requirements**; template scaffolding alone is not "complete".
6. Run build, unit/integration/browser/security checks and create a traceable Proof Receipt.
7. Offer repository export, GitHub repository publishing (via authorized GitHub App), deploy preview, review and iteration.
8. Continue approved feature work and maintenance through durable cloud jobs and clear progress reporting.

**Current reality:** Start New exports an in-memory requirements draft. The self-hosted engine creates deterministic starter repositories and source ZIPs; it does not implement the user's full brief. Hosted saved project briefs and collaboration are separate features. Custom model-driven application generation is not implemented.

### 2. Evolve — improve existing repositories

**Goal:** Analyze authorized applications and packages, deliver verified improvements, and perform justified AI-native modernization—including complete replacement when the evidence and approved migration plan support it.

Target acceptance journey:
1. Connect a specific GitHub repository through a least-privilege GitHub App or upload an authorized ZIP.
2. Inventory languages, frameworks, dependency/architecture graph, build/test topology, Git history, performance baselines and ownership.
3. Discover suspected bugs, stale dependencies, security smells, duplication, maintainability debt, missing tests, potential dead code and bottlenecks. Mark unverified findings as **candidates**.
4. Rank opportunities by expected user impact, likelihood, effort, risk and cost. Cite files/lines and reproducible symptoms where possible.
5. Compare retaining the system, adding AI capabilities, exposing safe agent interfaces, staged component replacement and a complete rewrite. Recommend the smallest intervention that achieves the agreed outcome; significant architecture/API/data changes require an approved migration contract.
6. Execute approved changes on isolated branches/worktrees; check behavior parity, regression, security, performance and reversibility.
7. Produce an independently tested patch, pull request, explanation and Proof Receipt.
8. Observe post-merge outcomes with user consent and recommend the next highest-value action.

**Current boundary:** read-only source analysis and the standalone local repair CLI remain available. Reviewed Evolve source now joins protected repair/reverification to project-scoped durable work, stage reviews, process audit, candidate decisions and lessons. Its result is an approved archive, never an automatically published PR or deployment. The earlier synthetic repair recorded 2026-11-04 as `f635c7c92c6b4e5fbea11a0d35d20def` remains historical evidence; current integration results are in [STATUS.md](STATUS.md), not a benchmark success rate or enterprise qualification. Broad modernization, private GitHub App access and operated hosted execution remain planned.

A reviewer can also re-check a saved candidate without any model: the same CLI takes `--candidate-zip` with the original source archive and the reviewed operator configuration, validates that only files inside the editable allowlist changed with nothing added or removed, reproduces the baseline and re-runs every declared final case in fresh local Docker containers. It contacts no inference endpoint, never executes the candidate on the host, trusts no supplied "passed" claim and writes a fresh run into a new private directory with `mode='verification'`, zero model calls and zero observed tokens. A passing re-verification is still `needs_review` — re-verification is not resume, approval, remote attestation or a hosted integration, and the operator must supply a reviewed current configuration and an authorized source, because a receipt cannot grant authorization it never had.

### AI-native modernization contract

“AI-native” means useful agent-driven workflows with typed tools, explicit identity/authorization, permission-aware knowledge retrieval, bounded orchestration, observability and independent evaluation. It does not mean replacing deterministic authorization, validation, money movement or database transactions with model decisions.

The planned Evolve workflow supports four intervention levels: add an AI feature; expose existing domain capabilities safely to agents; replace selected components; or replace the application/package. Prefer staged replacement where it reduces risk, but do not exclude a justified full rewrite. Preserve required behavior, not every accidental legacy defect. Breaking contracts must be explicit, versioned and approved.

Before behavior-changing migration, produce a reviewable **analysis dossier**:

1. Business goals, critical workflows and measurable acceptance criteria.
2. Code/module, public API, dependency/SBOM, data/schema, ownership, test, runtime and deployment maps.
3. Evidence-backed findings, security/license risks and performance/reliability baselines.
4. Coverage accounting: repositories/languages/files/runtime paths examined, skipped or unsupported, inaccessible sources and untested assumptions. Unavailable evidence is not a successful check.
5. Target AI-native architecture: model/tool boundaries, deterministic policy/transaction layer, context/retrieval scope, user experience, evaluation and operating budgets.
6. Alternatives with risk/cost/benefit, including no rewrite, and the rationale for the selected intervention.
7. Package/consumer compatibility and data-migration plan; affected callers, schema transitions, reconciliation, rollout and rollback. Unknown external consumers limit what compatibility can be claimed.
8. A staged change plan and acceptance matrix linking each requirement to tests, source revisions and eventual runtime evidence.

Characterization and contract tests establish required current behavior; approved new requirements add independent acceptance tests. Keep the implementing agent out of the protected verifier's authority. Coverage metrics are useful diagnostics, not sufficient proof and not a reason to discard a strong behavioral regression test that covers an existing line.

Use deterministic, syntax-aware codemods for repeatable mechanical transformations and model-assisted implementation for design/domain changes. Validate both against actual consumers and builds. Audit the exact tool/recipe license before using it in a customer-facing service: OpenRewrite includes Apache, source-available and proprietary components; repository visibility is not permission to vend them. LibCST is one Python codemod option, not a reason to introduce another whole migration platform.

For multi-repository/package changes, inventory and migrate known callers, verify their contracts/CI and use an explicit versioned release policy for breaking external changes. Transitional code or parallel operation, when justified, has a removal/cutover criterion; do not leave permanent aliases, duplicated business logic or unmanaged dual writes. Full replacement must finish with verified cutover and retirement of obsolete paths.

AI features require their own reliability, task-quality, latency and resource tests. If local inference cannot meet the agreed requirement, report the measured limitation or revise the approved scope—never silently invoke a paid provider or label an unimplemented fallback “complete.”

## Planned shared on-call mode

The target product lets both Start New and Evolve projects opt into on-call mode through the same web/mobile/Slack platform. Authorized logs, metrics, traces, release data and bug reports will be correlated into a canonical incident and restricted session. Agents will investigate with read-only tools, then use the same isolated Evolve/fix/verification path. Production actions require a separate explicit policy; reading logs is not deployment permission. This mode is not implemented yet.

New applications should offer reviewed service/release instrumentation. Existing applications connect their current sources first and identify observability gaps. An incident is resolved only after the required post-change evidence, not merely because a PR was created or merged. See [OPERATIONS.md](OPERATIONS.md) for ingestion, correlation, session, automation and proof contracts.

## Additional surfaces (not third entry points)

Overview, projects, agent chat, current execution, approvals, audit evidence, settings, integrations, project on-call sessions and consultancy workspaces. Show user work and verified impact, not artificial "AI agent personalities".

## Consultancy mode

Client → engagement → repository/projects → milestones → approved engineering tasks → artifacts/release → handover/monitoring. Include estimates versus actual, tenant separation, approval and rollback, plus evidence customers can audit. The platform does not promise humans are unnecessary.

## Internal Arena

Research/engineering subsystem only. Benchmark agent harness against existing coding baselines, MLE-Bench/Kaggle (within each competition's rules), performance optimization and build-from-brief scenarios. No official competition medal claims without verified results.

## Essential domain contracts

**Finding:** evidence-linked hypothesis about a problem, with confidence and verification status.
**Outcome Contract:** measurable target, baseline, constraints, allowed resources and acceptance criteria.
**Proof Receipt:** commit/build/test/deployment/results references and limitations.
**Agent Task:** versioned bounded instructions, context, tool policy, owner, idempotency key, cost and time budget.

## Modernization research

[Incremental modernization and the Strangler Fig](https://martinfowler.com/bliki/StranglerFigApplication.html) supports outcome-led decomposition and controlled cutover, not a guarantee that every rewrite should use the same pattern. [Effective agent tools](https://www.anthropic.com/engineering/writing-tools-for-agents) supports small, purpose-built, bounded tools and realistic evaluations. [OpenRewrite licensing](https://docs.openrewrite.org/licensing/openrewrite-licensing) requires component-level review for a commercial/managed service; [LibCST codemods](https://libcst.readthedocs.io/en/latest/codemods_tutorial.html) are a language-specific alternative for Python transformations.
