# Autonomous coding harness — research and implementation design

## Goal

Oryveta must perform verifiable software work in Start New and Evolve, while remaining fully inspectable, model-agnostic and free of mandatory commercial model APIs. This document describes the **target architecture**, not an already operational remote agent.

## Start minimal: the single-agent loop

1. Parse a versioned Outcome Contract: user goal, acceptance criteria, source state, allowed changes, limits, safety policies.
2. Collect precise context: repository symbols, tests, dependency graph, failure traces and relevant history.
3. Plan a bounded change, with explicit rollback and verification steps.
4. Select deterministic tools first; use a model only where reasoning or generation helps.
5. Make changes in an isolated Git worktree/sandbox, recording tool calls and a structured trajectory.
6. Run independent acceptance tests, static checks, security rules and resource measurement.
7. Stop if constraints fail; surface evidence, errors, ambiguity and any needed human approval.
8. Persist the receipt and outcomes. Never report "fixed" merely because an LLM claims success.

## Harness components

**Context Compiler:** Tree-sitter, language server data, symbol/call graphs, Git history, relevant tests, semantic retrieval and compact evidence-linked context windows.

**Model Adapter:** standardized messages, tools and resource usage for Ollama, llama.cpp, vLLM and optional customer providers. A free open-weight baseline should work without API keys. Large model inference requires user-provided compute.

**Adaptive Router:** versions of model-to-task policies; choose by observed quality, speed, cost and hardware constraints, not model brand. Permit splitting/defer rather than exceeding budget or silently using a paid service.

**Task Orchestrator:** durable task DAG, dependencies, priority, replay/resume points, bounded parallelism, per-tenant quotas and merge-conflict management. Add multi-agent roles only when tests show benefit.

**Typed Tool Runtime:** Git operations, code search, filesystem, shell, test runner, package manager, browser preview, observability and deployment. Validate every action outside the model.

**Independent Verifier:** compile, lint, unit/integration/e2e, expected-behavior tests, performance benchmarks, security gates and source/build hashes. Tests invented by the agent must not be the only proof.

**Experience Memory:** working memory, project decisions, reusable experience and evaluation history with tenant isolation, retention and human override.

**Harness Lab:** propose policy/tool/context changes, test blinded evaluations, reject regressions, stage rollout and enable rollback.

## Rewrite to Rust

Rust modernization is not a default instruction. First compare defects, latency, throughput, runtime costs, maintainability and migration risk against targeted improvements in the current stack. Use characterization tests and behavior parity before incremental migration; require approval for changes to production behavior.

## Safety / non-goals

No privileged autonomous production deployment; no self-modifying security policy; no untested auto-merge; no silent cost escalation; no cross-tenant training on customer data; no unlimited background agent promises. Single-agent verified patching should work before scaling to agent swarms.
