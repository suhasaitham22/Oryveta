# Vision, user pains and differentiation

**Updated: 2026-10-09.** Oryveta is an open-source autonomous software engineering platform. The purpose is to deliver trustworthy engineering outcomes, not merely generate code or simulate an AI development team.

## Problem we are solving

Software teams and consultancies spend disproportionate time on unclear requirements, code review, repetitive maintenance, reliability regressions, deployment and context handoffs. Existing coding agents can generate patches, but their outputs still demand supervision and independent verification. Small firms often cannot afford specialist QA, SRE and security teams.

## Mission and outcomes

"Build thoughtfully. Evolve continuously." The platform has **two** public journeys: **Start New**, which turns an idea into a real software project, and **Evolve**, which improves an existing repository. The platform must produce source code, runnable tests, diffs, approval requests and reproducible evidence. It must keep working when users close their browsers, provided remote workers and quotas permit.

## Research thesis

**ProofLoop:** define a measurable objective and baseline; identify a testable intervention; implement it in isolation; independently verify; observe the outcome; record the reason, costs and evidence; decide what to do next.

**Verified Outcome Graph:** link a user goal, constraints, code context, hypotheses, engineering decision, commit, tests, deployment and measured post-change behavior. Do not confuse hashes with proof of correctness.

**Hypothesis Graph:** systematically record successful and unsuccessful experiments with dataset/codebase characteristics, context and costs; use this evidence when selecting future experiments on genuinely unseen problems.

**Efficiency Governor:** prefer deterministic tools when possible, choose models by measured quality and cost, budget resource use and postpone tasks beyond available free compute.

**Harness Lab:** propose changes to context retrieval, tool use, model routing or policies; compare candidate versions with reproducible experiments; promote only passing variants, retaining rollback.

These are design and research hypotheses. We cannot claim they are legally exclusive inventions, that competitors cannot copy them, or that Oryveta beats Codex/Claude Code without independently reproducible evaluations.

## First users and long-term ambition

Initial users: indie developers and small SaaS engineering teams needing reliable maintenance and creation. Longer term: engineering consultancies managing multiple isolated client engagements, milestones, budgets, approval matrices and evidence-backed handover. Humans remain accountable for client promises, legal/security exceptions and high-risk releases.

## Success metrics

Verified task completion; human intervention including review; end-to-end elapsed time; regression/incident rate; resource spend per accepted change; reproducibility of evidence; deployment reversibility; repeat usage. No fabricated benchmark scores.

## Public product boundaries

There is no separate Kaggle application. Kaggle is one internal **Arena** evaluation source among software repair, code migration, performance optimization and build-from-brief benchmarks. Public primary navigation remains **Start New** and **Evolve**.
