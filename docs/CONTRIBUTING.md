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

Do not upload secrets, tokens, client source or private datasets. Never execute imported code with host credentials. Treat AI-produced patches as untrusted until reviewed and tested: when the patch came from the local repair CLI, a reviewer can re-check the candidate archive with no model involved using `--candidate-zip` against the reviewed operator configuration, which re-runs the declared checks in fresh local containers and trusts no supplied "passed" claim. Candidate archives contain source code; keep them as private local files rather than committed or published artifacts. Coordinate security disclosures privately with maintainers rather than publishing exploitable details before a fix.

## Benchmark integrity

Record pinned seeds/data versions, model versions, hardware, cost and time. No fabricated wins, cherry-picked comparisons or results on leaked hidden answers. Competition entries must obey their terms and avoid excess public leaderboard use.

## Product/visual acceptance

Keep **Start New** and **Evolve** as primary journeys and **Arena** internal. Follow the current [design system](DESIGN-SYSTEM.md): an off-white canvas with Geist typography, cobalt actions, a dark workspace rail, restrained original artwork and an opt-in spatial viewer. The earlier olive/yellow treatment is retired and must not return. Public navigation is Home / About / What We Do / Pricing / Workspace in the header, and What We Do / About / Pricing / Workspace / Sign in in the footer; `/pricing` is its own route, not a tab inside another page. Keep labels truthful, native scroll, keyboard navigation, visible focus and no mobile overflow. UI changes need desktop/mobile captures plus actual scroll/hover/press behavior, all keyboard chapter selections and live reduced-motion preference changes. Confirm active receipts stay readable; preserve contextual exports and real local lifecycle/stale/canceled behavior. Every capability sentence names its edition — hosted, self-hosted, operator-run local or planned — and distinguishes production from merged `main` and from an open review candidate. Reference public previews without copying paid source, assets, branding or fabricated customer claims.

Name evidence precisely, because three kinds are easy to conflate: a **captioned storyboard** (JSON scenes, and any video rendered from them), an **application capture** (screenshot or recording of the real UI), and **CLI evidence** (a receipt, patch and digests from an actual run). A storyboard proves renderability only. Historical counts, digests and screenshots keep their original dates and are never restated as covering newer surfaces.

For React Studio changes, run `npm --prefix apps/web/studio run check`, `npm --prefix apps/web/studio run build`, and `npm --prefix apps/web/studio run build:local`. Verify hosted root and self-hosted `/studio/` direct reloads, browser Back/Forward, breadcrumb targets, and missing-asset behavior with the compiled bundles; extensionless route fallback must never mask dotted assets or API-like paths.

## Licensing

See ../LICENSE and ../NOTICE. Contributions should include license attribution where appropriate; third-party model weights and datasets have their own independent terms.
