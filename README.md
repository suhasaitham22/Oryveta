# Oryveta

**Plan software. Review source. Work together.**

Oryveta is an open-source software delivery workspace for developers, independent builders and teams. It brings requirements, repository analysis and private collaboration together around two journeys: **Start New** for a new application, and **Evolve** for an existing application or package.

**The goal:** an AI software factory in which agents plan, implement and test changes, while people review results and approve publishing. That complete agent workflow is still in development; the capabilities below describe what can be used now.

### [Open Oryveta — https://oryveta.vercel.app](https://oryveta.vercel.app)

**Deployment:** [Vercel production](https://oryveta.vercel.app) serves the React Studio. GitHub sign-in, saved projects and private-conversation sharing have production verification. Starter generation and source analysis require a separately operated engine. The durable analysis worker is implemented and locally/CI verified, but its cloud host is not configured. FastAPI serves the self-hosted React workspace at `/studio/` and retains a separate legacy `/` interface.

> **Documentation:** [Complete product and technical decisions](docs/INDEX.md) · [Architecture](docs/ARCHITECTURE.md) · [UI design](docs/DESIGN-SYSTEM.md) · [Roadmap](docs/ROADMAP.md) · [Verified status](docs/STATUS.md) · [Quality gates](docs/QUALITY.md)

## What you can do today

- **Start New:** describe an app's users, features and acceptance criteria, then export the requirements as a brief. With the self-hosted engine, choose a template and download a starter repository. It does not implement a custom application from the brief.
- **Evolve:** describe a change, import an authorized ZIP or public GitHub snapshot into the self-hosted engine, and review file-linked candidate issues. Analysis is read-only; it does not run imported code or apply verified fixes.
- **Collaborate:** save project briefs, invite members with explicit roles and discuss work in separately shared private conversations.
- **Explain the work:** use Demo Studio to write scenes and export a JSON storyboard. It is a demo script, not a rendered video or proof of working software. Journey drafts are kept in memory and must be exported before reloading.

Kaggle and related benchmarks are **internal evaluation scenarios**, not a third product or navigation destination.

## Status

**Not available yet:** model-driven implementation and independent verification, private GitHub App repository access/publication, AI-native application/package modernization, operational on-call automation, scoped agent learning and an operated 24/7 service. These are [roadmap goals](docs/ROADMAP.md), not benefits of merely signing in.

Project roles, invitations and separately shared private conversations are enforced by Supabase RLS/RPCs. Real local email/PKCE tests, production GitHub OAuth and deployed multi-user authorization checks pass. No unrestricted repository execution or full software factory is claimed. See [identity, permissions and reproducible verification](docs/IDENTITY-WORKSPACES.md).

See [current status](docs/STATUS.md) and [open-source policy](docs/OPEN-SOURCE.md).

## Engineering principles

1. Make agent-generated changes testable and independently verifiable.
2. Require approval for production deployments and other high-risk actions.
3. Keep the harness inspectable, modular, self-hostable, and model-agnostic.
4. Use Kaggle and software benchmarks to evaluate genuine results with reproducible artifacts.
5. Never claim benchmark wins, production reliability, or completed work without evidence.
6. Keep free and open-source operation possible with bring-your-own-compute.

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

For service boundaries, limitations, and deployment considerations see [implementation guide](docs/IMPLEMENTATION.md).

## Copyright and license

Copyright © 2026 Suhas Aitham and Oryveta contributors.

Oryveta's original source code is licensed under the **Apache License, Version 2.0**.
See [LICENSE](LICENSE) and [NOTICE](NOTICE). Apache-2.0 permits use,
modification, redistribution, and commercial use subject to its terms; it
also includes an express patent license. Copyright holders retain their
ownership, and third-party components retain their respective licenses.

Brand and trademark rights are not automatically granted by a source-code license.
