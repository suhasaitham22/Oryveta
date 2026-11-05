# ADR 0003: Independent evidence and approval gates

Status: **Accepted design policy, implementation pending**. Date: 2026-10-09.

## Context

AI-generated patches may be wrong; claims from the creating agent are insufficient for trust. A multi-client consultancy environment increases risk and responsibility.

## Decision

Every material change uses an Outcome Contract (objective, baseline, guardrails), a bounded task policy, isolated execution, independent verification, and a Proof Receipt linking exact commits, build/tests, cost, deployment and verified results. High-risk external effects require explicit human approval. The harness is allowed to self-improve only through controlled evaluation of candidate versions.

## Consequences

Slower execution for risky work, but better auditability and rollback. Store full failures and negative outcomes. Evidence hashing cannot prove correctness. Do not advertise "fully autonomous safe production" without measured pilot results.

## Update 2026-11-04 — status superseded; decision unchanged

The 2026-10-09 status line above ("implementation pending") is superseded and preserved for history. Current status: **accepted design policy; partially implemented locally; hosted approval and publication gates still pending.**

Implemented, in the operator-run local CLI only: a versioned specification acting as the Outcome Contract (objective, baseline, guardrails, budgets and allowlists), a bounded task policy, isolated execution of checks in fresh networkless containers, independent controller-owned verification whose expected values the model never sees, and a checkpointed receipt binding the configuration, check-suite, goal, implementation, source and candidate digests. A candidate archive can additionally be re-verified with no model contact at all, so a verdict can be re-derived without trusting the producer.

Still pending, and the reason the decision is unchanged:

- A receipt is not a credential. It cannot re-establish a grant, re-authorize a source or attest to a host. Hashes bind bytes; they do not prove the work happened. There is no signing and no remote attestation.
- `needs_review` is the ceiling the tooling can reach. There is no approval record, no release target, no publication path and no deployment linkage — so the "Proof Receipt linking exact commits, build/tests, cost, deployment and verified results" is only partly realised.
- Harness self-improvement through controlled evaluation of candidate versions remains entirely unimplemented, and the single historical synthetic repair in [STATUS.md](../STATUS.md) is not the measured pilot result this ADR requires before any "fully autonomous safe production" language.
