# Reliability, delivery pipeline and operational practices

## CI gates

Required checks before considering a production release: formatting, lint, static types, deterministic tests, integration/e2e acceptance, dependency/security scanning, isolation tests, license audits, migration rehearsal and deploy smoke test. GitHub Actions must use scoped permissions and pinned reviewed actions; prevent unreviewed PRs from exposing secrets.

The initial public preview has a dedicated workflow in .github/workflows/preview-checks.yml. Status and complete code coverage must be verified from actual GitHub Actions runs; do not infer that Vercel deploy success means CI success.

## Durable job state

Persist New → Queued → Leased → Running → Verifying → Awaiting Approval → Completed/Failed/Canceled. Include heartbeat, lease expiration, idempotency, retry counter and dead-letter records. Workers may crash/restart or lose network. Reconcile outputs and replay safe operations only; never blindly repeat deployments, emails or destructive data writes.

## Observability

Structured logs (request ID, tenant ID, task ID, repository, harness/model version); OpenTelemetry spans across API/queue/worker; CPU/memory/token cost; artifact refs; benchmark precision; explicit user-visible degradation; secrets redaction and retention rules.

## Approval and audit

Record the user, permission, precise proposed commit/change, risk classification, evidence, policy version, approval timestamp and release target. Separate approval of a task plan from approval of a production deployment. Provide cancellation, revert instructions and recovery.

## Incidents / playbooks

Worker offline: mark degraded, avoid double execution, preserve jobs and resume with lease checks.
Control DB unavailable: reject writes clearly; do not "succeed" without persistence.
OAuth/GitHub unavailable: show actionable error; do not bypass authorization.
Compromised credentials: revoke/rotate tokens, invalidate sessions, inspect logs and notify affected users.
Deployment failure: stop promotion, restore previous release/backup and preserve evidence.
Quota exhausted: queue/pause gracefully; never charge users or switch to paid models silently.
Cross-tenant isolation failure: disable affected pathway and investigate before re-enabling.

## Backup/recovery

Encrypted backups for SQL and artifacts, regular restore drills, schema migration rollback and retention/deletion controls. Define RPO/RTO and escalation before enterprise clients.

## Current limitation

Public Vercel site has no authenticated backend, no actual incident tracking and no managed autonomous worker. These are roadmap requirements.
