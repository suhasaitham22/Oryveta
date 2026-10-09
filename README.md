# Oryveta

**Build thoughtfully. Evolve continuously.**

### [Live website preview → https://oryveta.vercel.app](https://oryveta.vercel.app)

> **Documentation:** [Complete product and technical decisions](docs/INDEX.md) · [Architecture](docs/ARCHITECTURE.md) · [UI design](docs/DESIGN-SYSTEM.md) · [Roadmap](docs/ROADMAP.md) · [Verified status](docs/STATUS.md) · [Quality gates](docs/QUALITY.md)

> **Preview only:** This deployment demonstrates the responsive Start New and Evolve UI. It does **not** yet offer live GitHub OAuth, repository generation, source analysis or autonomous coding. The local MVP API has not been deployed or wired to the site.

Oryveta is an open-source autonomous software engineering workspace with two product journeys:

- **Start New:** turn a project brief into a real software repository, then iteratively develop, test, review, and deploy it.
- **Evolve:** import an existing repository, analyze bugs, risky patterns, unused-code *candidates*, security concerns, and modernization opportunities, then implement verified improvements.

Kaggle and related benchmarks are **internal evaluation scenarios**, not a third product or navigation destination.

## Status

**Early development.** The functional Python/FastAPI + SQLite MVP, tests, background worker, Docker Compose and initial CI are now merged into `main`. The latest completed `main` CI run passed on 2026-10-09. A follow-up hardening PR adds Python 3.11/3.12/3.13 test coverage gates, dependency/security checks, container smoke tests and worker/ZIP security regressions. The public Vercel site remains a **static UI preview**, not a hosted API. Autonomous bug-fixing PRs, Rust migrations, agent-built applications, hardened tenant isolation and 24/7 hosted execution are **not yet implemented**.

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

For service boundaries, limitations, and deployment considerations see [implementation guide](docs/IMPLEMENTATION.md).

## Copyright and license

Copyright © 2026 Suhas Aitham and Oryveta contributors.

Oryveta's original source code is licensed under the **Apache License, Version 2.0**.
See [LICENSE](LICENSE) and [NOTICE](NOTICE). Apache-2.0 permits use,
modification, redistribution, and commercial use subject to its terms; it
also includes an express patent license. Copyright holders retain their
ownership, and third-party components retain their respective licenses.

Brand and trademark rights are not automatically granted by a source-code license.
