# ADR 0003: Independent evidence and approval gates

Status: **Accepted design policy, implementation pending**. Date: 2026-10-09.

## Context

AI-generated patches may be wrong; claims from the creating agent are insufficient for trust. A multi-client consultancy environment increases risk and responsibility.

## Decision

Every material change uses an Outcome Contract (objective, baseline, guardrails), a bounded task policy, isolated execution, independent verification, and a Proof Receipt linking exact commits, build/tests, cost, deployment and verified results. High-risk external effects require explicit human approval. The harness is allowed to self-improve only through controlled evaluation of candidate versions.

## Consequences

Slower execution for risky work, but better auditability and rollback. Store full failures and negative outcomes. Evidence hashing cannot prove correctness. Do not advertise "fully autonomous safe production" without measured pilot results.
