# Contributing and engineering standards

Oryveta aims to be fully open source under Apache License 2.0. Contributors retain copyright unless otherwise agreed and must submit only work they have rights to share; preserve third-party license notices.

## Workflow

1. Review docs/INDEX.md, docs/ROADMAP.md and relevant architecture decision records.
2. Open or link an issue describing a user-facing problem and expected acceptance criteria.
3. Prefer small bounded changes, versioned configuration and stable interfaces.
4. Include independent tests, failure cases and security impact.
5. Run lint/static checks and unit/integration checks; document anything skipped and why.
6. Open a PR with scope, before/after behavior, reproducible verification commands, screenshots where UI changed, failure/rollback considerations.
7. Update docs/STATUS.md and affected design/contract docs when implementation changes.

## Security

Do not upload secrets, tokens, client source or private datasets. Never execute imported code with host credentials. Treat AI-produced patches as untrusted until reviewed and tested. Coordinate security disclosures privately with maintainers rather than publishing exploitable details before a fix.

## Benchmark integrity

Record pinned seeds/data versions, model versions, hardware, cost and time. No fabricated wins, cherry-picked comparisons or results on leaked hidden answers. Competition entries must obey their terms and avoid excess public leaderboard use.

## Product/visual acceptance

Keep **Start New** and **Evolve** as primary journeys and **Arena** internal. Retain the minimalist Soft Modern style, keyboard navigation, responsive layouts and clear preview/verified status labels.

## Licensing

See ../LICENSE and ../NOTICE. Contributions should include license attribution where appropriate; third-party model weights and datasets have their own independent terms.
