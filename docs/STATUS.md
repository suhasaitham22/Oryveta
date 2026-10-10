# Oryveta implementation status

Checked 2026-10-09. Distinguish merged behavior, proposed changes and production gaps.

| Capability | State |
| --- | --- |
| GitHub + CI | [Source](https://github.com/suhasaitham22/Oryveta); CI stabilization merged in PR #7, Evolve read-only patch preview merged in PR #8 |
| Start New | Runnable starter scaffolds and ZIP export; not autonomous implementation of custom business requirements |
| Evolve | Public GitHub/ZIP import, static findings, read-only patch previews; not autonomous bug fixes or PRs |
| Identity | GitHub OAuth code + local demo; live hosted OAuth is not configured |
| Hosted site | `oryveta.vercel.app` is a static preview, not a deployed worker/API |
| Jobs | SQLite single-host queue with fenced retries; heartbeat, owner-scoped status/cancel and admission quotas proposed in this enterprise-foundations milestone |
| Security | CSRF, owner isolation, bounded archives, patch preview tests; no untrusted code execution or multi-tenant sandbox |
| AI | Opt-in local Ollama text generation and 20k tokens/day/account ledger introduced in this change; disabled by default, tested with mocks only; no production agent, independent verifier or proof receipts |

**Not implemented:** autonomous coding, private GitHub App access, isolated code execution, distributed job orchestration, enterprise multi-tenancy, or 24/7 hosted worker. The local model endpoint is not deployed on Vercel and has not been exercised against a real model.

See [ENTERPRISE-FOUNDATIONS.md](ENTERPRISE-FOUNDATIONS.md) for design invariants and measurable release gates. Proposed changes must pass remote CI and merge before being labeled implemented.
