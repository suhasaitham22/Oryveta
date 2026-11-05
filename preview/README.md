# Historical static preview

## Scope

The `preview/` directory is a **historical standalone static prototype**, kept for reference. It is **not** the deployed application: the Vercel project builds the React Studio from `apps/web/studio` (Root Directory `apps/web`, build `cd studio && npm run build`, output `studio/dist`). The prototype has no backend, no authentication and no code execution, and it is intentionally separate from the Python API and agent work. It shows the two product entry points: Start New for a new application and Evolve for an application you already have. Kaggle is an internal benchmark, not a top-level UI journey.

**Archive status is deliberate and retained.** This prototype is frozen as a record of an earlier stage. It does **not** follow the current design system, it does not carry the current public navigation (Home / About / What We Do / Pricing / Workspace) and it has no pricing page. Do not restyle it to match the current product, do not add current features to it, and do not read its screens as a description of today's application — see [the documentation hub](../docs/INDEX.md) and [the design system](../docs/DESIGN-SYSTEM.md) for what is current. Keep changes here limited to accuracy fixes, licence/attribution notices and keeping the page working.

### Run locally

```bash
cd preview
python -m http.server 4173
```

Visit http://127.0.0.1:4173. The static app has no npm dependencies. The scope draft it produces stays in the browser until you download it as JSON. The Evolve screen does not read or send the repository URL you type.

What lives elsewhere, not in this directory:

- **Deployed React Studio (`apps/web/studio`)** — GitHub sign-in, persisted projects and project briefs, roles and invitations, and private conversations that are only shared when you share them.
- **Self-hosted `apps/api` with the legacy UI at `apps/web/index.html`** — deterministic starter repositories, authorized ZIP or public GitHub snapshot intake, bounded static source analysis and downloads. Analysis reads source without executing it and reports candidate issues; it is not a security audit or a passing test suite.
- **Operator-run local tools, outside this directory** — a local CLI repairs an operator-selected source ZIP under controller-owned checks in fresh containers, and re-verifies a saved candidate archive with no model at all. Those tools exist today on an operator's own machine; they are not part of this prototype and are not reachable from any website.
- **Planned, not implemented** — *hosted* model-directed implement/test/repair, private GitHub App access and publication, and any always-on cloud worker. What is missing is hosted execution, not model tooling.

### Deployment

**Do not deploy this directory.** Vercel Root Directory must stay `apps/web`, which builds `studio/` into `studio/dist`; pointing it at `preview` would publish this obsolete prototype while every current frontend change stayed invisible. See the [current deployment guide](../docs/DEPLOYMENT-PREVIEW.md). Avoid changing or publishing the local demo login intended strictly for localhost.

This prototype must not be labeled production-ready: it offers no GitHub OAuth, no multi-tenant persistence and no cloud agent worker. The cost of any hosting provider depends on account plan and usage. Do not assume unlimited free commercial usage on Vercel Hobby.

### Licensing

Original work © 2026 Suhas Aitham and Oryveta contributors. Apache License 2.0. See the repository's LICENSE and NOTICE.
