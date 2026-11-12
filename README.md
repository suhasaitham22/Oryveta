# Oryveta

**Scope the change. Check the code. Review the patch.**

Oryveta is an open-source workspace for small teams maintaining existing code. Define a change, review its source and preserve the behavior that matters. **Evolve** is the first qualification focus; **Start New** remains the journey for a new application, with the broader factory built in stages.

**Working today, locally:** a bounded repair loop for an existing codebase. You grant specific files, a local model proposes SHA-guarded edits that the controller applies to a disposable copy on your host, and controller-owned checks reproduce the defect first and test required behavior afterward. The model cannot rewrite their expected results. Checks execute in fresh network-disabled containers. Passing candidates are ready for human review, not automatic merge.

**One goal, in order:** an AI software factory in which agents plan, implement and test changes, while people review results and approve publishing. The route to it is deliberately sequential — **verifiable maintenance changes on an existing codebase first**, the broader factory (custom application generation, hosted execution, publication, on-call, learning) afterwards, each stage gated on evidence rather than intent. The complete agent workflow is still in development and the hosted site does not run it; the capabilities below describe what can be used now.

### [Open Oryveta — https://oryveta.vercel.app](https://oryveta.vercel.app)

**Deployment:** [Vercel production](https://oryveta.vercel.app) serves the React Studio built from merged `main`. GitHub sign-in, saved projects and private-conversation sharing have production verification. The durable analysis schema is deployed to Supabase; browser submission, result download, cancellation and revocation were verified with a temporary local worker. No always-on cloud worker is configured. Starter generation still uses the separate self-hosted FastAPI engine, which serves `/studio/` and retains a legacy `/` interface. The local repair CLI is operator-run and is **not** reachable from the hosted site.

**Three states, kept distinct.** *Production* is the deployment at https://oryveta.vercel.app. *`main`* is merged source and can be ahead of deployment. *This working tree* adds Reviewed Evolve: durable project work, Pydantic AI roles, stage reviews, protected verification, process audit, human approval and scoped lessons. It is not a production rollout. Current exercised evidence is in [STATUS.md](docs/STATUS.md).

> **Documentation:** [Complete product and technical decisions](docs/INDEX.md) · [Architecture](docs/ARCHITECTURE.md) · [UI design](docs/DESIGN-SYSTEM.md) · [Pricing and launch plan](docs/PRICING.md) · [Roadmap](docs/ROADMAP.md) · [Demo standard](docs/DEMO-STUDIO.md) · [Verified status](docs/STATUS.md) · [Quality gates](docs/QUALITY.md)

## What you can do today

- **Start New:** describe an app's users, features and acceptance criteria, then export the requirements as a brief. With the self-hosted engine, choose a template and download a starter repository. It does not implement a custom application from the brief.
- **Evolve:** describe a change, import an authorized ZIP or public GitHub snapshot into the self-hosted engine, and review file-linked candidate issues. Analysis is read-only; it does not run imported code or apply verified fixes.
- **Collaborate:** save project briefs, invite members with explicit roles and discuss work in separately shared private conversations.
- **Explain the work:** use Demo Studio to write scenes and export a JSON storyboard. The browser editor does not render video: its exports stay `storyboard_only_not_rendered` with `verified: false`. A reviewer can separately render a **captioned storyboard** video from `apps/web/studio/demo`; it is not footage of a live agent run, an application recording or proof of working software. Journey drafts are kept in memory and must be exported before reloading.
- **Local verified repair CLI:** operate directly on an authorized source ZIP with explicit file grants, SHA-guarded edits, a reproduced baseline and controller-owned checks in fresh network-disabled containers. Private checkpoints and candidate export support review, not automatic merge or replay. The earlier synthetic run `f635c7c92c6b4e5fbea11a0d35d20def` (2026-11-04) remains historical evidence, not a benchmark. The standalone CLI is not a hosted endpoint; Reviewed Evolve reuses its protected library under a separate durable work contract. See [setup and restrictions](docs/IMPLEMENTATION.md#local-verified-repair-cli).
- **Model-free re-verification of a saved candidate:** the same CLI accepts `--candidate-zip` and then contacts no model or inference endpoint at all. It re-reads the operator's reviewed configuration, validates that the candidate changes only files inside the editable allowlist with nothing added or removed, reproduces the baseline, and re-runs every declared final case in fresh local Docker containers. A supplied "passed" claim is never trusted, the candidate is never executed on the host, and this is re-verification rather than resume, approval, remote attestation or anything hosted. The receipt records `mode='verification'` with `model_calls` and `tokens_observed` at `0`.
- **Reviewed Evolve (configured self-hosting):** submit a change against a project's public GitHub source, inspect durable stages and independent reviews, download the exact candidate, and approve or reject it as a project administrator. The worker reuses protected repair/reverification and keeps raw private evidence off the web. Approved lessons apply only to the same project/source/configuration; failed-run lessons are diagnostic, not active memory. Install the new migration and provision a registered worker, model and runner first; [setup](docs/IMPLEMENTATION.md#reviewed-evolve-worker).

Kaggle and related benchmarks are **internal evaluation scenarios**, not a third product or navigation destination.

## Status

**Not deployed or operated yet:** the new Reviewed Evolve workflow, private GitHub App access/publication, AI-native modernization, on-call automation and an operated 24/7 service. The source includes bounded project-scoped learning, not autonomous policy changes or shared cross-customer training. Signing in alone provisions no execution capacity.

Project roles, invitations and separately shared private conversations are enforced by Supabase RLS/RPCs. Real local email/PKCE tests, production GitHub OAuth and deployed multi-user authorization checks pass. No unrestricted repository execution or full software factory is claimed. See [identity, permissions and reproducible verification](docs/IDENTITY-WORKSPACES.md).

See [current status](docs/STATUS.md) and [open-source policy](docs/OPEN-SOURCE.md).

## Pricing

Two plans, published so the commercial position is reviewable. **Pricing is a business hypothesis, not an implemented fact:** the prices, the buyer definition and the Y Combinator application framing in [docs/PRICING.md](docs/PRICING.md) are proposals to be tested, while the implemented facts are the hosted collaboration workspace, the self-hosted analysis engine and the local repair CLI. Y Combinator is a goal the project is being prepared for; it is not an affiliation, an application outcome or an admission, and no YC name, logo or batch reference appears in the product.

- **Community — $0 software.** The source is Apache-2.0 and self-hosting never needs a subscription; those rights cannot be revoked later. The **hosted workspace is free during preview, subject to documented capacity** — shared free-tier allowances with quotas and pausing, not an availability commitment or a perpetual free-hosting promise. You supply the machine, the model weights and the container runtime.
- **Team — $49 USD per workspace per month, up to 5 builders. Proposed, not billable.** Workspace-wide reporting, review assignment and budget administration remain proposals. Project-scoped Reviewed Evolve history, candidate decisions and lessons are included in the open-source code, not paywalled. Billing, metering and checkout are absent, so this price cannot be charged today.

**No plan includes hosted compute or hosted inference.** This change paywalls nothing that already exists, and any later change to hosted terms requires advance notice, consent before it binds an existing workspace, and a working export path. Commercial use of the hosted site — paid or free — requires a compliant hosting entitlement first; that entitlement is unverified here and no account or plan has been changed. The buyer/job hypothesis, availability boundaries, explicitly hypothetical unit economics, effort allocation and the evidence gates are in [docs/PRICING.md](docs/PRICING.md).

## Engineering principles

1. Make agent-generated changes testable and independently verifiable.
2. Require approval for production deployments and other high-risk actions.
3. Keep the harness inspectable, modular, self-hostable, and model-agnostic.
4. Use Kaggle and software benchmarks to evaluate genuine results with reproducible artifacts.
5. Never claim benchmark wins, production reliability, or completed work without evidence.
6. Keep free and open-source operation possible with bring-your-own-compute.
7. Publish prices and limits before charging, meter usage visibly first, and change hosted terms only with advance notice, consent and a working export path.

## Run the self-hosted engine

The Python/FastAPI + SQLite engine runs on a single host with a separate worker. It creates template starters, imports source snapshots, performs bounded static analysis and exports repositories. It is distinct from the Supabase-backed durable analysis runtime described in [IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export ORYVETA_LOCAL_DEMO=true
export ORYVETA_BASE_URL=http://127.0.0.1:8000
uvicorn oryveta_api.main:app --host 127.0.0.1 --port 8000
# In another terminal, with the same environment:
python -m oryveta_engine.worker
```

For the React Studio, Vite 7 requires Node **20.19+ or 22.12+** (CI uses Node 22):

```bash
npm --prefix apps/web/studio install
npm --prefix apps/web/studio run check
npm --prefix apps/web/studio run build       # hosted dist/
npm --prefix apps/web/studio run build:local # self-hosted dist-local/
```

Open `http://127.0.0.1:8000/studio/`, choose **Start New** or **Evolve**, open **Local run**, then choose **Sign in to local demo**. The browser and API must share the same origin/base URL; local demo sign-in is loopback-only and not permitted on public Vercel. `npm --prefix apps/web/studio run check` validates story/evidence contracts. Use `docker compose up --build` only with configured GitHub OAuth for non-demo sign-in. See [CI and quality gates](docs/QUALITY.md).

### Run local Ollama inference

On a computer with [Ollama](https://ollama.com/) installed and enough RAM/disk for the model:

```bash
# Ensure the Ollama desktop service is running (or run ollama serve separately).
ollama pull qwen2.5-coder:1.5b
```

In another terminal, from this repository, start the Python API (as above) with:

```bash
export ORYVETA_LOCAL_DEMO=true
export ORYVETA_OLLAMA_MODEL=qwen2.5-coder:1.5b
export ORYVETA_OLLAMA_URL=http://127.0.0.1:11434
uvicorn oryveta_api.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000, select **Explore local demo**, then use **Local AI assistant** on Overview. Verify actual model generation (not just mocks) with `python scripts/smoke_ollama.py`.

Alternatively, the opt-in Docker Compose overlay runs Ollama privately, downloads the model into a persistent volume and starts the API after the download:

```bash
docker compose -f compose.yaml -f compose.ollama.yaml up --build
```

**Docker mode requires configured GitHub OAuth credentials to sign in**; the loopback-only demo sign-in is deliberately disabled inside Docker. Ollama is not published to the host or internet. See [complete Ollama setup, resource requirements and troubleshooting](docs/MODEL-GATEWAY.md).

### Re-verify a saved candidate without a model

A reviewer who has the candidate archive, the original source archive and the reviewed operator configuration can re-run the checks with no inference of any kind — Ollama does not need to be installed or running:

```bash
python -m oryveta_engine.coding_runtime \
  --config operator.json \
  --source-zip source.zip \
  --candidate-zip candidate.zip \
  --goal 'review requirement' \
  --output reverified-run
```

`--output` must be a new directory so earlier evidence is never overwritten. Add `--run-root PRIVATE_DIR` if the default private directory is not shared with your Docker VM. Omit `--candidate-zip` to use model-driven repair instead. The verification path uses the reviewed operator spec's allowlists, runner and behavior checks. Terminal execution results are `needs_review`, `rejected`, `failed` or `cancelled`; `incomplete` is an in-flight or interrupted checkpoint, never acceptance. Exit `0` means `needs_review`, not approval or publication.

Named refusals include added/removed files (`candidate_inventory`), edits outside the write allowlist (`candidate_scope`), no changes (`no_change`), unusable candidate ZIPs (`invalid_candidate`), a non-reproducing or already-regressed baseline (`not_reproduced` / `invalid_baseline`), and failed final checks (`verification_failed`). The private `candidate.zip` uses a stable `candidate/` wrapper and is identified by `candidate_archive_sha256`. It contains source code and must not be published by default. Re-verification is neither resume, remote attestation nor a hosted service.

For service boundaries, limitations, and deployment considerations see [implementation guide](docs/IMPLEMENTATION.md).

## Copyright and license

Copyright © 2026 Suhas Aitham and Oryveta contributors.

Oryveta's original source code is licensed under the **Apache License, Version 2.0**.
See [LICENSE](LICENSE) and [NOTICE](NOTICE). Apache-2.0 permits use,
modification, redistribution, and commercial use subject to its terms; it
also includes an express patent license. Copyright holders retain their
ownership, and third-party components retain their respective licenses.

Brand and trademark rights are not automatically granted by a source-code license.
