# Technical architecture and component choices

## Architectural principle

Keep three replaceable planes: **control**, **intelligence**, and **execution**. Every external provider should sit behind a versioned adapter. Start with a small single-host implementation, then distribute only where measured demand justifies complexity.

## Current known implementation

**Hosted site:** Vercel builds `apps/web/studio` as the React/shadcn product UI. Hosted Supabase identity/workspaces and the self-hosted FastAPI engine are separate; the hosted UI does not call local jobs.

**Collaboration source:** Supabase-backed project briefs, explicit project membership and separate private-session grants are implemented in the React client and SQL migration. Sign-in is identity, not project/repository authority. Local real-service authorization/browser checks pass; deployment state is recorded in [STATUS.md](STATUS.md).

**Self-hosted compatibility:** FastAPI retains legacy `/` plus `/studio/` for the built React distribution. SQLite users/projects/jobs/events support deterministic starter creation, ZIP snapshot import, read-only heuristic analysis and coarse queued/running/succeeded/failed/canceled worker lifecycle. No hosted bridge, sandboxed arbitrary execution or autonomous coding agent exists.

## Planned production control plane

- Retain the existing React/shadcn UI and Python/FastAPI engineering code; do not rewrite runtimes to add the factory.
- Supabase Auth supplies the hosted principal. PostgreSQL owns explicit workspace/project/session grants, durable work and evidence metadata. A self-hosted deployment is an alternative, not a second identity authority.
- GitHub App permissions are separate from human sign-in. Slack/mobile clients use the same authorization and work-item contract.
- A small Python orchestrator owns durable admission, leases, bounded attempts, cancellation, checkpoints and side-effect reconciliation.
- Browser clients never receive worker, GitHub App or database service credentials. Large evidence artifacts live outside SQL with scoped metadata.

## Planned execution plane

Extend the existing Python worker with disposable isolated execution, scoped tool capabilities and an independent verifier. Persist run/checkpoint state outside the runner and release compute while awaiting a person. No Rust supervisor, Hono API or additional queue platform is required for this delivery path; introduce another service only for a measured constraint. Worktrees alone are not isolation for untrusted customer code.

## Planned intelligence plane

Python research/coding harness, scikit-learn/AutoGluon/CatBoost/LightGBM/XGBoost/Optuna for ML benchmarks; Tree-sitter/language tools for code structure; prompt/model adapters to Ollama/llama.cpp/vLLM and optional customer-configured providers; policy engine, verifier, versioned context retrieval and memory.

## Data flows

Start New: authenticated brief → persisted specification/plan → approved task DAG → sandbox workspace → code/test/build → evidence artifacts → reviewable source/PR → user-approved deployment.

Evolve: authorized repo snapshot → architecture map + static/runtime diagnostics → ranked opportunities → bounded change in isolated branch → independent tests → review/PR → measured result.

## Architecture diagram

```mermaid
flowchart TD
    U[Browser: Start New / Evolve] --> C[Control API / Auth / Workspace]
    C --> D[(Control SQL: users jobs approvals)]
    C --> Q[Durable task queue]
    Q --> R[Python worker supervisor - factory extensions planned]
    R --> P[Python engineering / experiment harness]
    P --> S[Isolated Git workspace / sandbox]
    S --> V[Independent verification]
    V --> A[Artifacts and proof receipts]
    V --> D
```

## Key boundaries

Models cannot grant permissions. Repository content is untrusted input. Local SQLite is not a shared cross-host WAL database. Database rows are not storage for model weights and large logs. One $0 VM cannot guarantee unlimited agents, GPU time, or enterprise uptime.
