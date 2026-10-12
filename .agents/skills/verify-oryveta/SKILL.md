---
name: verify-oryveta
description: Check security, real browser flows, evidence and demo honesty before merging.
---
# Oryveta project verification
Inspired by tester-army/e2e create-verification-skill; see https://github.com/tester-army/e2e.
1. State exactly what is claimed, including whether a test uses mock accounts or real user credentials.
2. Run the Python CI, Vite production build and scripts/react_ui_smoke.py using real Chromium on desktop/mobile. Confirm keyboard and reduced-motion.
3. For private data, run transactional two-user RLS tests on the dedicated database; verify that pending shares expose nothing, viewers cannot write, editors can contribute, owners can revoke and outsiders cannot read.
4. Confirm Supabase advisors are clean. Run live two-account flows before serving customers; synthetic PostgreSQL accounts are not real sign-ins.
5. Require a three-beat accurate demo-stories.json entry for every customer-facing feature and matching snapcn Remotion rendering setup. Do not confuse storyboards with videos or functional proof.
6. Inspect all PR CI and errors and report exact commit and limitations. No unverified OAuth, backend, email delivery or AI success claims.
Optional upstream: npx skills add tester-army/e2e --skill create-verification-skill
