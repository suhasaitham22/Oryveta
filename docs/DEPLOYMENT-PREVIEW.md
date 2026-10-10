# Preview deployment

## Scope

The production Vercel project at https://oryveta.vercel.app now serves the **current application frontend from `apps/web/`**. The older `preview/` directory remains an archived, standalone prototype and must not be used as Vercel's project root. The hosted frontend is intentionally separate from the Python API and agent execution. The preview is **not an authenticated or autonomous service**. It shows two product journeys: Start New and Evolve. Kaggle is an internal benchmark, not a top-level UI journey.

### Run locally

```bash
cd preview
python -m http.server 4173
```

Visit http://127.0.0.1:4173. The static app has no npm dependencies. Its generated product brief JSON remains in the browser until exported. The Evolve screen does not read or send entered repository URLs. GitHub authentication, API persistence, agent jobs and actual repository generation will come from the separately tested `apps/api` service after proper deployment and secrets configuration.

### Deployment

Configure Vercel project `oryveta` with **Root Directory: `apps/web`**, Framework Preset: Other. The entrypoint is `apps/web/index.html`. The committed `apps/web/vercel.json` rewrites `/static/app.js` and `/static/styles.css` to the same-directory assets; FastAPI uses the original `/static/` routes when self-hosted. The frontend detects unavailable API routes on Vercel and renders a read-only preview rather than leaving a blank login screen. The `Browser UI smoke` GitHub Actions workflow tests actual desktop and mobile rendering and navigation in Chromium.

**Do not configure Vercel Root Directory as `preview`.** That would silently publish the obsolete prototype while all modern frontend changes remain invisible. Avoid changing or publishing the local demo login intended strictly for localhost.

The hosted static preview must not be labeled production-ready; it offers no GitHub OAuth, multi-tenant persistence or cloud agent worker. The cost of any hosting provider depends on account plan and usage. Do not assume unlimited free commercial usage on Vercel Hobby.

### Licensing

Original work © 2026 Suhas Aitham and Oryveta contributors. Apache License 2.0. See the repository's LICENSE and NOTICE.
