#!/usr/bin/env bash
# Untrusted third-party skills: opt-in, only on a reviewed local development host.
set -euo pipefail
echo "Review GitHub upstream: tester-army/e2e, mattpocock/skills, snapcndev/snapcn"
if [[ "$(printenv ORYVETA_ALLOW_EXTERNAL_SKILL_INSTALL || true)" != "reviewed" ]]; then
  echo "Set ORYVETA_ALLOW_EXTERNAL_SKILL_INSTALL=reviewed after inspecting sources"
  exit 1
fi
npx skills add tester-army/e2e --skill create-verification-skill
npx skills@latest add mattpocock/skills
npx skills add snapcndev/snapcn --skill remotion-product-demo
echo "Inspect all installed content and pin the reviewed revisions before granting any tool permissions"
