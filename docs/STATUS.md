# Oryveta implementation status

Checked 2026-10-09. Distinguish merged behavior, proposed changes and production gaps.

| Capability | State |
| --- | --- |
| GitHub + CI | [Source](https://github.com/suhasaitham22/Oryveta); CI stabilization merged in PR #7, Evolve read-only patch preview merged in PR #8 |
| Start New | Runnable starter scaffolds and ZIP export; not autonomous implementation of custom business requirements |
| Evolve | Public GitHub/ZIP import, static findings, manual read-only patch previews and opt-in local-model-assisted read-only proposals; not autonomous fixes or PRs |
| Identity | GitHub OAuth code + local demo; live hosted OAuth is not configured |
| Hosted site | `oryveta.vercel.app` serves the actual `apps/web` frontend in read-only preview mode, with Start New/Evolve navigation and no hosted worker/API. Browser smoke tests cover desktop/mobile UI |
| Jobs | SQLite single-host queue with fenced retries; heartbeat, owner-scoped status/cancel and admission quotas proposed in this enterprise-foundations milestone |
| Security | CSRF, owner isolation, bounded archives, patch preview tests; no untrusted code execution or multi-tenant sandbox |
| AI | Opt-in local Ollama text generation and 20k tokens/day/account ledger; local assistant UI, readiness probe, optional Compose Ollama stack and read-only Evolve proposals. Tested with mocks and real TCP to a deterministic stub, not downloaded weights. No hosted model, production agent or independent verifier |

**Not implemented:** autonomous coding, private GitHub App access, isolated code execution, distributed job orchestration, enterprise multi-tenancy, or 24/7 hosted worker. The local model endpoint is not deployed on Vercel and has not been exercised against a downloaded real model in CI. A real-model smoke script is provided for self-hosted operators.

See [ENTERPRISE-FOUNDATIONS.md](ENTERPRISE-FOUNDATIONS.md) for design invariants and measurable release gates. Proposed changes must pass remote CI and merge before being labeled implemented.
