---
name: verify-oryveta
description: Check security, real browser flows, evidence and demo honesty before merging.
---
# Oryveta project verification
Inspired by tester-army/e2e create-verification-skill; see https://github.com/tester-army/e2e.
1. Read `docs/INDEX.md`, `docs/STATUS.md` and the affected contracts before changing code. State the exact source/review/production boundary and whether evidence uses real services, scripted proposals or historical examples.
2. Run the affected Python behavior tests and required CI gates. For UI changes, build both hosted and self-hosted Studio and exercise `scripts/react_ui_smoke.py` in real Chromium, including Pricing/evidence links, keyboard and reduced motion. A passing build alone is not behavior proof.
3. For authorization changes, exercise the real dedicated Supabase RLS/browser suite with distinct ordinary-user sessions: pending shares expose nothing, readers cannot write, owners can revoke, and outsiders cannot read. Do not use administrative credentials for ordinary-user assertions.
4. Review and record Supabase advisor findings when database/deployment scope requires it. Do not suppress findings or claim a clean report when documented exceptions or paid-only controls remain. Production verification needs explicit authorized fixtures and cleanup; a local suite is not a production login or recovery drill.
5. Local repair/verification changes need real-container checks and a CLI smoke. Model-free re-verification must not contact inference or inherit approval from an old receipt. Keep candidate archives, operator checks and private run evidence private; only reviewed synthetic assets belong on the public site.
6. Require accurate three-scene demo coverage for customer-facing changes. A captioned Remotion storyboard, a browser recording, a synthetic repair and a real customer outcome are different evidence levels.
7. Check all current-head PR results, report failures without hiding them, and keep `docs/STATUS.md` current. Preserve the Community/free-preview versus proposed Team distinction; never invent billing availability, customer traction, YC affiliation, admission or an uptime promise.
Optional upstream: npx skills add tester-army/e2e --skill create-verification-skill
