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

Keep **Start New** and **Evolve** as primary journeys and **Arena** internal. Follow the current [design system](DESIGN-SYSTEM.md): bright product-centered composition, restrained motion and a calm workspace, not the superseded Soft Modern styling. Keep labels truthful, native scroll, keyboard navigation, visible focus and no mobile overflow. UI changes need desktop/mobile captures plus actual scroll/hover/press behavior, all keyboard chapter selections and live reduced-motion preference changes. Confirm active receipts stay readable; preserve contextual exports and real local lifecycle/stale/canceled behavior. Reference public previews without copying paid source, assets, branding or fabricated customer claims.

For React Studio changes, run `npm --prefix apps/web/studio run check`, `npm --prefix apps/web/studio run build`, and `npm --prefix apps/web/studio run build:local`. Verify hosted root and self-hosted `/studio/` direct reloads, browser Back/Forward, breadcrumb targets, and missing-asset behavior with the compiled bundles; extensionless route fallback must never mask dotted assets or API-like paths.

## Licensing

See ../LICENSE and ../NOTICE. Contributions should include license attribution where appropriate; third-party model weights and datasets have their own independent terms.
