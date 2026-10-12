---
name: story-demo
description: Produce accurate feature demos with SnapCN Remotion and verified receipts.
---
# Oryveta demo by default
Every feature and story needs a customer-centered storyboard and verifiable constraints.
1. Add a feature ID and at least three scenes to apps/web/studio/public/demo-stories.json.
2. Include a user action, visible state/result, and a proof or limitation in every scene. Never invent customer usage or hosted agent outcomes.
3. Use vendored SnapCN components and Remotion in apps/web/studio/demo; run npm run check and npx tsc --noEmit and render the matching composition when runtime tools are available.
4. Associate approved evidence with exact commits and CI runs. Browser Demo Studio remains storyboard-only until a video render is independently verified.
5. Never auto-publish a demo or expose customer data without explicit review.
Optional upstream: npx skills add snapcndev/snapcn --skill remotion-product-demo
Documentation: https://snapcn.dev/docs/getting-started/agent-skill
