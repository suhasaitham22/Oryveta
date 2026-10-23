# Oryveta

**Build thoughtfully. Evolve continuously.**

### [Open Oryveta — https://oryveta.vercel.app](https://oryveta.vercel.app)

**Deployment:** [Vercel production](https://oryveta.vercel.app) serves the hosted React Studio from `apps/web/studio/dist`. GitHub sign-in, persisted project membership and private-session sharing have production verification. Start New/Evolve execution still requires the separate self-hosted API; a saved brief is not a generated application. FastAPI retains legacy `/` and serves the local React workspace at `/studio/` from `apps/web/studio/dist-local`; that API/worker is not deployed to Vercel.

> **Documentation:** [Complete product and technical decisions](docs/INDEX.md) · [Architecture](docs/ARCHITECTURE.md) · [UI design](docs/DESIGN-SYSTEM.md) · [Roadmap](docs/ROADMAP.md) · [Verified status](docs/STATUS.md) · [Quality gates](docs/QUALITY.md)

> **Launch status:** Production GitHub identity and project/private-session collaboration are live. General email deliverability, enterprise operations and hosted coding agents remain separate gates. Local deterministic starters and read-only analysis are not autonomous custom application generation.

Oryveta is an open-source software engineering workspace with two target product journeys (the local MVP implements only bounded starter/scanning capabilities):

- **Start New (target):** turn a project brief into a real software repository, then iteratively develop, test, review, and deploy it. Today the local path creates a deterministic starter and can analyze it; custom feature generation is not implemented.
- **Evolve (target):** import an existing repository, analyze bugs, risky patterns, unused-code *candidates*, security concerns, and modernization opportunities, then implement verified improvements. Today the local path imports authorized snapshots and performs read-only heuristic analysis; patches remain review-only.

Kaggle and related benchmarks are **internal evaluation scenarios**, not a third product or navigation destination.

## Status

**Early development.** The functional Python/FastAPI + SQLite MVP, tests, background worker, Docker Compose and CI are merged into `main`. The React Studio is the hosted UI and also an optional self-hosted `/studio/` surface; local jobs expose coarse worker states/events only. Autonomous code execution, test-backed AI fixes, GitHub publishing, hosted inference and 24/7 execution are not implemented.

Project roles, invitations and separately shared private conversations are enforced by Supabase RLS/RPCs. Real local email/PKCE tests, production GitHub OAuth and deployed multi-user authorization checks pass. No unrestricted repository execution or full software factory is claimed. See [identity, permissions and reproducible verification](docs/IDENTITY-WORKSPACES.md).

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
