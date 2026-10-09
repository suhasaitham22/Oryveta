# Oryveta

**Build thoughtfully. Evolve continuously.**

### [Live website preview → https://oryveta.vercel.app](https://oryveta.vercel.app)

> **Preview only:** This deployment demonstrates the responsive Start New and Evolve UI. It does **not** yet offer live GitHub OAuth, repository generation, source analysis or autonomous coding. The local MVP API has not been deployed or wired to the site.

Oryveta is an open-source autonomous software engineering workspace with two product journeys:

- **Start New:** turn a project brief into a real software repository, then iteratively develop, test, review, and deploy it.
- **Evolve:** import an existing repository, analyze bugs, risky patterns, unused-code *candidates*, security concerns, and modernization opportunities, then implement verified improvements.

Kaggle and related benchmarks are **internal evaluation scenarios**, not a third product or navigation destination.

## Status

**Early development.** A local MVP has been built with a responsive Soft Modern interface, Python/FastAPI + SQLite API, starter repository scaffolding, snapshot-based source analysis, tests, and local background worker. The complete local implementation is being transferred into this public repository. The public repository now contains Apache-2.0 licensing, documentation, an interactive **static frontend preview**, and basic preview CI. Vercel serves that frontend at **https://oryveta.vercel.app**; it is **not** an operational authenticated or autonomous engineering service. Autonomous bug-fixing PRs, Rust migrations, fully agent-built applications, hardened tenant isolation, and 24/7 hosted execution are planned—not completed.

See [current status](docs/STATUS.md) and [open-source policy](docs/OPEN-SOURCE.md).

## Engineering principles

1. Make agent-generated changes testable and independently verifiable.
2. Require approval for production deployments and other high-risk actions.
3. Keep the harness inspectable, modular, self-hostable, and model-agnostic.
4. Use Kaggle and software benchmarks to evaluate genuine results with reproducible artifacts.
5. Never claim benchmark wins, production reliability, or completed work without evidence.
6. Keep free and open-source operation possible with bring-your-own-compute.

## Copyright and license

Copyright © 2026 Suhas Aitham and Oryveta contributors.

Oryveta's original source code is licensed under the **Apache License, Version 2.0**.
See [LICENSE](LICENSE) and [NOTICE](NOTICE). Apache-2.0 permits use,
modification, redistribution, and commercial use subject to its terms; it
also includes an express patent license. Copyright holders retain their
ownership, and third-party components retain their respective licenses.

Brand and trademark rights are not automatically granted by a source-code license.
