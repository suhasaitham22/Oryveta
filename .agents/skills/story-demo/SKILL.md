---
name: story-demo
description: Produce accurate feature demos with SnapCN Remotion and verified receipts.
---
# Oryveta demo by default
Every customer-facing feature needs a customer-centered storyboard with explicit evidence and limitations; internal-only changes may use the PR template's documented exception.
1. Add a unique feature ID and at least three scenes to `apps/web/studio/public/demo-stories.json`, or update the affected story. Preserve historical examples rather than relabelling them as fresh execution.
2. Each scene must name a user action, visible result, and proof or limitation. Keep hosted collaboration, self-hosted analysis, local repair/verification and planned hosted agents distinct. Prices and future features must retain their availability labels.
3. Reuse the vendored SnapCN/Remotion components in `apps/web/studio/demo`; validate the manifest, typecheck, and render the matching composition when the local renderer is available. Inspect the resulting frames for clipping and misleading presentation.
4. Associate reviewed artifacts with exact source and CI evidence. Browser Demo Studio edits/exports storyboards only; an offline MP4 does not add browser rendering or prove application execution.
5. Never publish customer code, operator configuration, candidate archives or private run evidence as demo assets without explicit authorization. Public examples must be deliberately sanitized and labelled; no invented customers, live agent activity, benchmark wins or YC affiliation.
Optional upstream: npx skills add snapcndev/snapcn --skill remotion-product-demo
Documentation: https://snapcn.dev/docs/getting-started/agent-skill
