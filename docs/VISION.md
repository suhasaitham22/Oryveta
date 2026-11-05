# Vision, user pains and position

**Updated: 2026-11-04.** Oryveta is an open-source software delivery workspace that is being built into an AI software factory. It brings software requirements, repository analysis and team collaboration into one place. The purpose is trustworthy engineering outcomes, not fast code generation or a simulated AI development team.

**One goal, approached in order:** make a maintenance change to an existing codebase that a reviewer can verify, then widen into the full factory. The narrow first step — one known defect, the team's own compute, a reviewable patch with a reproducible verification record — is sequencing, not a smaller ambition. Everything after it (custom application generation, hosted execution, publication, on-call, learning) is gated on recorded evidence from the step before; the staging is in [ROADMAP.md](ROADMAP.md), and the separate commercial hypotheses are in [PRICING.md](PRICING.md).

**Who it is for:** the current target hypothesis is a **small team maintaining an existing codebase**, with the first qualification cohort being **Python services that have a runnable test suite**. The long-term audience stays wider — individual builders, developers, consultants and teams working on applications, services and packages — but that breadth is the destination, not a claim about who is served well today.

**Two entry points, kept stable:** **Start New** for a new application, and **Evolve** for understanding and improving an existing application or package.

## What exists today and what is planned

- **Hosted today:** GitHub sign-in, saved projects and project briefs, project roles and invitations, and private conversations between people that stay private until their owner shares them. Start New and Evolve journey drafts live in the browser and are exported by hand; they are not saved projects. Demo Studio edits a **demo script** — a scene-by-scene storyboard exported as JSON to explain a journey, not a generated app, rendered video or agent run.
- **Self-hosted today:** deterministic starter repositories, authorized ZIP and public GitHub snapshot intake, bounded read-only source analysis and downloads. Analysis reports *candidate* findings; it never runs imported code and is not a security audit or a passing test suite.
- **Local model tooling today, operator-run:** two separate opt-in local paths use a model. The Ollama adapter behind the self-hosted API is text-only assistance, not a coding tool loop. The separate repair CLI *is* a real tool loop: granted-file reads, SHA-guarded edits applied by the controller to a disposable host copy, controller-owned checks in fresh network-disabled containers, and a `needs_review` patch. Neither is hosted, neither is reachable from the public site, and neither is a claim of hosted inference.
- **Production control plane; worker hosting pending:** durable public-repository analysis is deployed to Supabase and verified through the production UI using a one-off local worker. The always-on cloud worker is still absent, so continuous background availability is not yet a product promise.
- **Planned — the factory goal:** a person describes a new application or a change; agents plan, implement and test it; people review the result and approve publishing or deployment. What remains planned is *hosted* model-directed implementation/verification, private repository access and publication, the full knowledge graph, AI-native rewrites, on-call response, learned skills and enterprise operation — not model tooling as such, which already exists locally. The evidence behind each line above is recorded in [STATUS.md](STATUS.md).

## Problem we are solving

Software teams and consultancies spend disproportionate time on unclear requirements, code review, repetitive maintenance, reliability regressions, deployment and context handoffs. Existing coding agents can generate patches, but their outputs still demand supervision and independent verification. Small firms often cannot afford specialist QA, SRE and security teams.

## Mission and outcomes

"Build thoughtfully. Evolve continuously." The workspace keeps **two** public journeys under their existing names: **Start New** and **Evolve**. The factory target for both is to produce source code, runnable tests, diffs, approval requests and reproducible evidence, and to keep working after the user closes the browser where remote workers and quotas permit. These are requirements for the work ahead, not descriptions of the current hosted product.

## Research directions

Each name below is shorthand for a plain idea; prefer the plain idea in product copy.

**ProofLoop** — change one thing at a time and prove it: define a measurable objective and baseline; identify a testable intervention; implement it in isolation; verify it independently; observe the outcome; record the reason, costs and evidence; decide what to do next.

**Verified Outcome Graph** — keep the trail from goal to measured result: link a user goal, constraints, code context, hypotheses, engineering decision, commit, tests, deployment and measured post-change behavior. Do not confuse hashes with proof of correctness.

**Hypothesis Graph** — remember what worked and what did not: record successful and unsuccessful experiments with dataset/codebase characteristics, context and costs; use this evidence when selecting future experiments on genuinely unseen problems.

**Efficiency Governor** — spend the cheapest resource that answers the question: prefer deterministic tools when possible, choose models by measured quality and cost, budget resource use and postpone tasks beyond available free compute.

**Harness Lab** — improve the harness the same way: propose changes to context retrieval, tool use, model routing or policies; compare candidate versions with reproducible experiments; promote only passing variants, retaining rollback.

These are design and research hypotheses, not differentiators that have been demonstrated. We cannot claim they are legally exclusive inventions, that competitors cannot copy them, or that Oryveta beats Codex/Claude Code; any such comparison would need independently reproducible evaluations that do not exist here. The one position stated plainly is a design choice, not a measured advantage: the checks, the expected values and the final verifying run belong to the controller rather than the model.

## First users and long-term ambition

First users (hypothesis, unvalidated): small engineering teams maintaining an existing codebase, entering through one known defect in a Python service with a runnable test suite. Next: individual builders and developers needing dependable creation and maintenance. Longer term: consultants and engineering consultancies managing multiple isolated client engagements, milestones, budgets, approval matrices and evidence-backed handover. No team has been recorded as a customer or design partner in this repository. Humans remain accountable for client promises, legal/security exceptions and high-risk releases.

## Success metrics

Verified task completion; human intervention including review; end-to-end elapsed time; regression/incident rate; resource spend per accepted change; reproducibility of evidence; deployment reversibility; repeat usage. No fabricated benchmark scores.

## Public product boundaries

There is no separate Kaggle application. Kaggle is one internal **Arena** evaluation source among software repair, migration, performance and build-from-brief scenarios. **Start New** and **Evolve** remain the two workspace journeys; public site navigation is **Home / About / What We Do / Pricing / Workspace**.
