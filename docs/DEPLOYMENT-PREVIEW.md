# Hosted deployment

## Scope

The production Vercel project at https://oryveta.vercel.app serves the **React Studio** built from `apps/web/studio`. The hosted site is a browser client only; it is intentionally separate from the Python API, the durable worker and any agent execution. The archived `preview/` directory is a historical static prototype and must never be Vercel's project root — see [the historical preview notes](../preview/README.md). For local engine and Studio commands see the repository README.

Hosted today: GitHub sign-in, saved projects and briefs, project roles/invitations, private conversations and the Supabase durable-analysis control plane. Production verification is recorded in [STATUS.md](STATUS.md). Analysis completed through the deployed UI using a one-off local worker; no always-on cloud worker is configured. Starter generation still requires the separate self-hosted FastAPI engine. A saved brief is not a generated application, and Kaggle remains an internal benchmark rather than a product journey.

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
