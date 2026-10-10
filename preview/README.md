# Preview deployment

## Scope

The `preview/` directory is a **legacy standalone static prototype**. The current Vercel deployment serves `apps/web/`, not this directory. This prototype remains for historical reference and is intentionally separate from the Python API and agent execution. The preview is **not an authenticated or autonomous service**. It shows two product journeys: Start New and Evolve. Kaggle is an internal benchmark, not a top-level UI journey.

### Run locally

```bash
cd preview
python -m http.server 4173
```

Visit http://127.0.0.1:4173. The static app has no npm dependencies. Its generated product brief JSON remains in the browser until exported. The Evolve screen does not read or send entered repository URLs. GitHub authentication, API persistence, agent jobs and actual repository generation will come from the separately tested `apps/api` service after proper deployment and secrets configuration.

### Deployment

**Do not deploy this directory for the current application.** Vercel Root Directory must be `apps/web`, which serves the actual application UI. See [current deployment guide](../docs/DEPLOYMENT-PREVIEW.md). Avoid changing or publishing the local demo login intended strictly for localhost.

The hosted static preview must not be labeled production-ready; it offers no GitHub OAuth, multi-tenant persistence or cloud agent worker. The cost of any hosting provider depends on account plan and usage. Do not assume unlimited free commercial usage on Vercel Hobby.

### Licensing

Original work © 2026 Suhas Aitham and Oryveta contributors. Apache License 2.0. See the repository's LICENSE and NOTICE.
