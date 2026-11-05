# Technical architecture and component choices

Oryveta is an open-source software delivery workspace being built toward an AI software factory. Its near-term audience is small teams maintaining existing codebases, with the initial qualification cohort being Python services. This page separates the parts that run today from the planes the factory still needs. For the single current-state summary read [STATUS.md](STATUS.md); this page describes structure and boundaries rather than restating dated evidence.

## Architectural principle

Keep three replaceable planes: **control**, **intelligence**, and **execution**. Every external provider should sit behind a versioned adapter. Start with a small single-host implementation, then distribute only where measured demand justifies complexity.

## Implemented today

**Hosted site:** Vercel builds `apps/web/studio` as the React/shadcn product UI. Hosted Supabase identity/workspaces and the self-hosted FastAPI engine are separate; the hosted UI does not call local jobs.

**Collaboration:** Supabase-backed project briefs, explicit project membership and separate private-session grants are deployed. Sign-in is identity, not project/repository authority. Production GitHub sign-in and multi-user project/private-session authorization are verified in [STATUS.md](STATUS.md); they do not grant code-execution privileges.

**Self-hosted compatibility:** FastAPI retains legacy `/` plus `/studio/` for the built React distribution. SQLite users/projects/jobs/events support deterministic starter creation, ZIP snapshot import, read-only heuristic analysis and a coarse queued/running/succeeded/failed/canceled worker lifecycle. This engine has its own local identity; hosted Supabase sessions are never forwarded into it and no hosted bridge exists.

**Durable analysis control plane (deployed; worker hosting pending):** production Supabase stores project-authorized work items, leases, bounded attempts, checkpoints, cancellation and pinned sources. Browser submission, a real public-repository analysis and result download were verified with a separately authenticated one-off local worker. The database is deployed, but no always-on cloud worker is configured; continuous execution still requires an authorized host and worker registration.

**Local model-driven repair and model-free reverification (operator-run CLI only):** `python -m oryveta_engine.coding_runtime` performs model-driven edits of an operator-selected ZIP inside a disposable copy, under a versioned operator specification, exact file allowlists, a pinned local Ollama model and bounded Docker check execution, and emits a review candidate plus private evidence. The same command re-verifies a supplied candidate archive without any model contact. Two distinct boundaries matter here and are frequently conflated: **model-driven file edits** happen only in the local disposable workspace, while **check execution** happens in fresh, networkless, non-root containers that the model cannot configure. This is local defense in depth, not multi-tenant production isolation, and it is not hosted, queued or autonomous. See [IMPLEMENTATION.md](IMPLEMENTATION.md#local-verified-repair-cli).

There is no hosted coding service, no hosted autonomous Evolve fix, no sandboxed execution of arbitrary customer code and no unattended coding agent.

## Planned production control plane

- Retain the existing React/shadcn UI and Python/FastAPI engineering code; do not rewrite runtimes to add the factory.
- Supabase Auth supplies the hosted principal. PostgreSQL owns explicit workspace/project/session grants, durable work and evidence metadata. A self-hosted deployment is an alternative, not a second identity authority.
- GitHub App permissions are separate from human sign-in. Slack/mobile clients use the same authorization and work-item contract.
- A small Python orchestrator owns durable admission, leases, bounded attempts, cancellation, checkpoints and side-effect reconciliation.
- Browser clients never receive worker, GitHub App or database service credentials. Large evidence artifacts live outside SQL with scoped metadata.

## Planned execution plane

The operator-run local CLI already supplies a disposable workspace, scoped tool capabilities, bounded isolated check execution and controller-owned verification for one fixed single-agent repair policy. What remains planned is making that path *hosted and durable*: run/checkpoint state persisted outside the runner by the control plane, compute released while awaiting a person, per-tenant isolation strong enough for untrusted customer code, and admission from the durable work contract rather than an operator's shell. No Rust supervisor, Hono API or additional queue platform is required for this delivery path; introduce another service only for a measured constraint. Worktrees alone are not isolation for untrusted customer code, and a shared-kernel Docker container is not a per-tenant boundary.

## Planned intelligence plane

Planned, with one exception: the pinned local Ollama tool-model adapter used by the operator-run repair CLI and the text-only local gateway both exist. Still planned are the Python research harness beyond small scikit-learn baselines; scikit-learn/AutoGluon/CatBoost/LightGBM/XGBoost/Optuna for ML benchmarks; Tree-sitter/language tools for code structure; llama.cpp/vLLM and customer-configured provider adapters; a policy engine, versioned context retrieval and memory. Model inference always runs on compute the user supplies; no paid provider or hosted inference key is enabled.

## Target data flows

Both flows are the factory target, not current behavior. Today Start New stops at a brief plus a deterministic starter. Evolve stops at authorized snapshot intake plus read-only analysis in the product; its only change-producing path is the separate operator-run local CLI, which is not reachable from a brief, a project or any endpoint.

Start New (target): authenticated brief → persisted specification/plan → approved task DAG → sandbox workspace → code/test/build → evidence artifacts → reviewable source/PR → user-approved deployment.

Evolve (target): authorized repo snapshot → architecture map + static/runtime diagnostics → ranked opportunities → bounded change in isolated branch → independent tests → review/PR → measured result.

## Architecture diagram

The diagram is the **target** topology. Deployed today: the browser, the control API/auth/workspace and the control SQL, with durable work items and leases in that same PostgreSQL authority rather than a separate queue platform. The worker supervisor runs only when an operator starts it locally. The isolated workspace, independent verification and receipts exist only inside the separate local CLI and do not report to the control plane.

```mermaid
flowchart TD
    U[Browser: Start New / Evolve] --> C[Control API / Auth / Workspace - deployed]
    C --> D[(Control SQL: grants, work items, leases, events - deployed)]
    D --> R[Python worker supervisor - operator-started, not hosted]
    R --> P[Read-only analysis child - implemented]
    R -.-> H[Python engineering / experiment harness - planned]
    H -.-> S[Isolated workspace + bounded check containers - local CLI only]
    S -.-> V[Controller-owned verification - local CLI only]
    V -.-> A[Private local evidence receipts - local CLI only]
    A -.-> D
```

## Key boundaries

Models cannot grant permissions. Repository content is untrusted input. Local SQLite is the local engine's single-host store, not a shared cross-host WAL database and not a second hosted identity authority; Supabase PostgreSQL is the one hosted authority, and D1 or another queue/broker is not part of this path. Database rows are not storage for model weights and large logs; the local CLI's receipts, traces, patches and candidate archives stay in private operator-owned files outside both databases. One $0 VM cannot guarantee unlimited agents, GPU time, or enterprise uptime.
