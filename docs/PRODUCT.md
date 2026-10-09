# Product specification and use cases

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

**Current reality:** an earlier local Python/FastAPI MVP supports starter-template generation, ZIP export and tests. The publicly deployed static preview only drafts a brief; it does not run the API or generate repositories. Real autonomous custom product generation is not implemented.

### 2. Evolve — improve existing repositories

**Goal:** Import an authorized repository and make it genuinely better.

Target acceptance journey:
1. Connect a specific GitHub repository through a least-privilege GitHub App or upload an authorized ZIP.
2. Inventory languages, frameworks, dependency/architecture graph, build/test topology, Git history, performance baselines and ownership.
3. Discover suspected bugs, stale dependencies, security smells, duplication, maintainability debt, missing tests, potential dead code and bottlenecks. Mark unverified findings as **candidates**.
4. Rank opportunities by expected user impact, likelihood, effort, risk and cost. Cite files/lines and reproducible symptoms where possible.
5. Present a proposed fix/refactor or modernization plan; never force a rewrite to Rust. Compare alternatives and quantify expected benefits when possible.
6. Execute approved changes on isolated branches/worktrees; check behavior parity, regression, security, performance and reversibility.
7. Produce an independently tested patch, pull request, explanation and Proof Receipt.
8. Observe post-merge outcomes with user consent and recommend the next highest-value action.

**Current reality:** a local MVP supports public-repository or ZIP snapshot intake with static heuristic findings. Public preview does not analyze repositories. Autonomous fixing, production migration to Rust, private GitHub App installs and PR generation remain planned.

## Additional surfaces (not third entry points)

Overview, projects, agent chat, current execution, approvals, audit evidence, settings, integrations and consultancy workspaces. Show user work and verified impact, not artificial "AI agent personalities".

## Consultancy mode

Client → engagement → repository/projects → milestones → approved engineering tasks → artifacts/release → handover/monitoring. Include estimates versus actual, tenant separation, approval and rollback, plus evidence customers can audit. The platform does not promise humans are unnecessary.

## Internal Arena

Research/engineering subsystem only. Benchmark agent harness against existing coding baselines, MLE-Bench/Kaggle (within each competition's rules), performance optimization and build-from-brief scenarios. No official competition medal claims without verified results.

## Essential domain contracts

**Finding:** evidence-linked hypothesis about a problem, with confidence and verification status.
**Outcome Contract:** measurable target, baseline, constraints, allowed resources and acceptance criteria.
**Proof Receipt:** commit/build/test/deployment/results references and limitations.
**Agent Task:** versioned bounded instructions, context, tool policy, owner, idempotency key, cost and time budget.
