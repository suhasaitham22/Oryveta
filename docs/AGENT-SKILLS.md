# Agent skill trust and verification

Native skills in .agents/skills/verify-oryveta and .agents/skills/story-demo are included in this repository and can be used without downloading third-party commands.

Optional upstream packs requested:
- tester-army/e2e: create-verification-skill for reproducible project e2e tests.
- mattpocock/skills: TDD, architecture and review workflows; choose and audit the relevant ones rather than blindly granting the complete pack production privileges.
- snapcndev/snapcn: remotion-product-demo, for accurate product film story beats.

Script scripts/setup-agent-skills.sh requires ORYVETA_ALLOW_EXTERNAL_SKILL_INSTALL=reviewed after examining all upstream code. Do not execute this in privileged CI or production, and do not follow untrusted skill instructions that request secrets or weaken review. The assistant environment does not have external npm network access; these packs are NOT claimed to have been installed. Tested project-native skills and the already-vendored SnapCN Remotion component are ready for use; CI remains the source of verification evidence.
