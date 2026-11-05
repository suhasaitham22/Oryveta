# Hosted deployment

## Scope

The production Vercel project at https://oryveta.vercel.app serves the **React Studio** built from `apps/web/studio`. The hosted site is a browser client only; it is intentionally separate from the Python API, the durable worker and any agent execution. The archived `preview/` directory is a historical static prototype and must never be Vercel's project root — see [the historical preview notes](../preview/README.md). For local engine and Studio commands see the repository README.

Hosted today: Supabase GitHub/email sign-in, saved projects and briefs, project roles/invitations, private conversations, and the Supabase durable-analysis control plane. Public routes are `/`, `/about`, `/what-we-do`, `/pricing` and `/sign-in`; `/workspace/*` is behind sign-in. The build also publishes two static synthetic evidence files, `/repair-example.json` and `/repair-example.patch`, which the Pricing and Home evidence sections read and offer for download. They are reviewed build assets extracted from one historical local run — not a live agent feed, a benchmark or a customer result — and no endpoint lets a visitor start a repair.

Production verification is recorded in [STATUS.md](STATUS.md). Analysis completed through the deployed UI using a **one-off local worker**; no always-on cloud worker is configured, so there is no continuous or unattended execution and no availability commitment. Starter generation, the local model gateway and the operator-run repair/reverification CLI all require the separate self-hosted engine or an operator shell; none is reachable from this deployment. A saved brief is not a generated application, and Kaggle remains an internal benchmark rather than a product journey.

### Naming the environments precisely

Four states exist and conflating any two of them produces a false claim:

- **Production** — what https://oryveta.vercel.app currently serves.
- **Preview** — a Vercel deployment built from a branch. A review candidate **can** be deployed to a preview, so never describe an unmerged branch as simply "not deployed": say it is **not merged and not deployed to production**. A preview URL is also not production evidence.
- **`main`** — the merged source. Merged is not released: `main` can be ahead of production until a rollout succeeds, so do not equate the two or infer production behavior from merged code.
- **Local / self-hosted** — an operator's own machine. Nothing here is served by Vercel.

A source change, a local test, a preview deployment and a successful production rollout are four different evidence levels. Vercel reporting a build READY is a build result, not proof that the production alias serves it or that the behavior works.

### Vercel configuration

Configure Vercel project `oryveta` with **Root Directory: `apps/web`** and Framework Preset: Other. The committed `apps/web/vercel.json` supplies the rest:

| Setting | Value |
| --- | --- |
| `installCommand` | `cd studio && npm ci --no-audit --no-fund` |
| `buildCommand` | `cd studio && npm run build` |
| `outputDirectory` | `studio/dist` |

Its single rewrite is the SPA fallback to `/index.html`, deliberately excluding `assets/`, `favicon.ico` and any path containing a dot, so a missing asset stays a real 404 instead of returning HTML. The same file sets the restrictive security headers, including the `Content-Security-Policy` whose `connect-src` must list the Supabase origin the build uses. A hosted build is rejected when that origin is absent from the policy, and when a privileged browser key is supplied. See [identity configuration and RLS verification](IDENTITY-WORKSPACES.md).

The `/static/*` asset routes belong to the self-hosted FastAPI surface, which mounts `apps/web/` at `/static` for the legacy `/` interface and serves the separate `build:local` distribution at `/studio/`. Vercel serves neither of those.

**Do not configure Vercel Root Directory as `preview`.** That would silently publish the obsolete prototype while every current frontend change stayed invisible. Avoid changing or publishing the local demo sign-in intended strictly for localhost; it is loopback-only and not permitted on the public deployment.

### Browser checks

The `Browser UI smoke` workflow renders the real frontend in desktop and mobile Chromium. `React Studio build and browser QA` validates the story and evidence contracts, builds both deployment targets and exercises the real Supabase auth, RLS and browser collaboration suites. See [CI and quality gates](QUALITY.md).

A successful build and browser rendering are not evidence of general email deliverability, an always-on worker or an availability commitment. The cost of any hosting provider depends on account plan and usage; do not assume unlimited free commercial usage on Vercel Hobby.

### Licensing

Original work © 2026 Suhas Aitham and Oryveta contributors. Apache License 2.0. See the repository's LICENSE and NOTICE.
