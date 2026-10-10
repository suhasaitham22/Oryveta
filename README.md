# Oryveta

**Build thoughtfully. Evolve continuously.**

### [Open Oryveta — https://oryveta.vercel.app](https://oryveta.vercel.app)

**Deployment:** [Vercel production](https://oryveta.vercel.app) automatically deploys from the GitHub `main` branch. Vercel now serves the **actual `apps/web` interface** (Overview, Start New, Evolve, Projects, Activity), rather than the old `preview/index.html` placeholder. Without a deployed API, Start New/Evolve remain **read-only**. The new startup sign-in gate and workspace UI are ready for a dedicated Supabase Auth project, but **real hosted login and persistent workspaces are not enabled until provider setup and RLS verification**. This is not an Ollama server or a hosted FastAPI service. The Ollama feature below works in the self-hosted API.

> **Documentation:** [Complete product and technical decisions](docs/INDEX.md) · [Architecture](docs/ARCHITECTURE.md) · [UI design](docs/DESIGN-SYSTEM.md) · [Roadmap](docs/ROADMAP.md) · [Verified status](docs/STATUS.md) · [Quality gates](docs/QUALITY.md)

> **Launch status:** The Vercel deployment offers a polished GitHub sign-in gate and explicit **Explore product preview**. Live GitHub OAuth is **not yet configured**. Project generation, repository analysis and model inference require the separate API. See [identity and workspace setup](docs/IDENTITY-WORKSPACES.md). The local FastAPI app includes a functional AI assistant when Ollama is configured; it is not deployed to Vercel.

Oryveta is an open-source autonomous software engineering workspace with two product journeys:

- **Start New:** turn a project brief into a real software repository, then iteratively develop, test, review, and deploy it.
- **Evolve:** import an existing repository, analyze bugs, risky patterns, unused-code *candidates*, security concerns, and modernization opportunities, then implement verified improvements.

Kaggle and related benchmarks are **internal evaluation scenarios**, not a third product or navigation destination.

## Status

**Early development.** The functional Python/FastAPI + SQLite MVP, tests, background worker, Docker Compose and CI are merged into `main`. The local app supports opt-in open-weight Ollama text generation, readiness checks, a budgeted AI assistant in the workspace and read-only AI-assisted Evolve patch proposals. CI tests exercise the Ollama HTTP protocol with a local deterministic test server; **a real downloaded model is not executed in CI**. The public Vercel site remains a static UI preview. Autonomous code execution, test-backed AI fixes, GitHub publishing, hosted inference and 24/7 execution are not implemented.

See [current status](docs/STATUS.md) and [open-source policy](docs/OPEN-SOURCE.md).

## Engineering principles

1. Make agent-generated changes testable and independently verifiable.
2. Require approval for production deployments and other high-risk actions.
3. Keep the harness inspectable, modular, self-hostable, and model-agnostic.
4. Use Kaggle and software benchmarks to evaluate genuine results with reproducible artifacts.
5. Never claim benchmark wins, production reliability, or completed work without evidence.
6. Keep free and open-source operation possible with bring-your-own-compute.

## Functional MVP — run locally

The production-style foundation is intentionally a **single-host MVP**, not a multi-tenant cloud service. It runs locally with Python 3.11+, FastAPI, SQLite, and a separate durable worker. It can create runnable starter repositories, import authorized ZIP/public GitHub snapshots, perform heuristic static analysis, export projects and run reproducible *starter* ML evaluations.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export ORYVETA_LOCAL_DEMO=true
uvicorn oryveta_api.main:app --host 127.0.0.1 --port 8000
# In another terminal, with the same environment:
python -m oryveta_engine.worker
```

Open http://127.0.0.1:8000. Local demo sign-in is restricted to localhost; it is **not permitted** on the public Vercel site. Alternatively, use `docker compose up --build` with real GitHub OAuth credentials configured. To validate changes run `pytest -q --cov=oryveta_api --cov=oryveta_engine --cov-branch --cov-fail-under=84`, `ruff check apps/api engine tests`, and `node --check apps/web/app.js`. See [CI and quality gates](docs/QUALITY.md).

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
