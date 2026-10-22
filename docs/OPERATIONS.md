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

Hosted collaboration uses Supabase identity and project/session policies after the target migrations are applied; local real-service/browser checks do not prove production rollout. There is still no hosted autonomous worker, operated incident system or guaranteed availability. Those remain roadmap gates.

## Project on-call mode — planned product capability

On-call is a mode on a project, whether it originated in Start New or Evolve. Web, mobile and Slack operate the same incident and investigation session. It is not a separate bot with separate permissions.

For Start New, offer reviewed instrumentation, structured logs, service/release identity and health checks as part of the generated application. For Evolve, connect existing sources and identify instrumentation gaps; add instrumentation through a reviewed change rather than silently modifying production.

### Signal to verified fix

1. An authorized connector receives a bug report/alert or queries a bounded log, metric or trace window. Resolve tenant/project/source scope from the registered integration, never from an untrusted payload alone.
2. Verify authenticity and size limits, normalize metadata and durably record a receipt. Acknowledge webhook delivery promptly; expensive investigation runs asynchronously.
3. Deduplicate exact delivery IDs separately from incident correlation. Preserve individual occurrences while linking them to a canonical incident.
4. Correlate using service/resource, environment, release, trace/span and error fingerprint. Similar wording or nearby timestamps alone are hypotheses, not proof that two incidents are identical. Missing telemetry is reported as missing.
5. Atomically create or attach a restricted investigation session and work item. Replayed delivery, parallel workers and alert storms must not create one agent/session per notification.
6. Query only policy-approved read-only sources; build a cited timeline, hypotheses, affected scope and confidence/unknowns. Link existing bug reports rather than filing duplicates.
7. When evidence supports a code fix, use the existing Evolve engine in an isolated workspace. Pin the deployed source revision and account for differences from the target branch. Reproduce the fault and run protected regression checks.
8. Publish a reviewed fix/PR or a separately authorized runbook proposal. Telemetry credentials never grant production mutation or repository publication.
9. Release through the configured approval policy, then observe the relevant signals for a defined window. A passing test or merged PR is not by itself an operational resolution.
10. Record the outcome, update the incident/bug links and produce a scoped learning candidate. Reopen or escalate if signals remain unhealthy; do not start an unbounded repair loop.

### Connector and data contract

Use a small typed connector interface: receive/verify an event, query scoped evidence, return a bounded structured result, and report permission/rate-limit/unavailability explicitly. Start with the project's actual sources, not an unimplemented catalogue of every observability vendor.

Preserve event time and observed time, service/resource identity, environment, release/build reference, trace/span IDs where available, severity and source-specific event/fingerprint identifiers. OpenTelemetry's stable log data model provides a useful normalization baseline. Keep build/release-to-commit mapping so an investigation does not debug unrelated source.

Raw logs stay in their original system by default. Store bounded, redacted excerpts, source links/query windows and provenance in Oryveta. A separately approved forensic retention policy may retain encrypted raw material with a narrower audience. Do not persist credentials or unrestricted request bodies simply because an alert arrived.

Deduplication keys include the integration/tenant boundary. Correlation links have evidence and confidence; uncertain relations remain “possibly related.” Apply per-source/project concurrency, occurrence coalescing, cardinality, query-byte and time budgets. Retain a durable cursor/receipt and bounded retry/dead-letter path. One logical incident can have many occurrences and runs.

### Investigation session contents

The session shows severity, affected service/environment/release, linked reports, timeline, collected evidence, hypotheses versus confirmed findings, actual agent tasks, patch/test status and the next approval or escalation. Sources and actions remain inspectable. Private production data is not copied into a broader Slack channel; notifications link back to permission-checked content.

State distinguishes investigation, diagnosis, fix available, awaiting release, observing, resolved, false positive and blocked/escalated. Do not conflate “PR created,” “deployed,” and “service recovered.”

### Automation policy

- **Observe/investigate:** approved read-only sources may automatically open a session and investigate within a project policy and budget.
- **Prepare repair:** the agent may reproduce, edit, test and create a draft fix through a scoped repository grant. No production secrets enter the code sandbox.
- **Execute a runbook/release:** only a separately authorized action, resource set, environment, precondition and rollback policy may permit automated execution. Default production posture requires approval. High-risk/destructive migrations, permission changes, secret operations and new spending remain explicit human decisions.

Reading production logs never implies shell access, `kubectl exec`, SQL writes, restarts, deployment or arbitrary network access. A read-only prompt or command denylist is not the security boundary; use purpose-built read operations backed by genuinely least-privilege credentials.

Logs, stack traces, tickets, runbooks and repository instructions are untrusted input. They cannot override tool permissions, select another tenant, expand network access or alter the protected verifier. Production investigation and isolated code verification use different credentials and environments.

If the on-call service is itself failing, an external health signal and human escalation must remain available. A failed attempt to fix the factory must not recursively spawn unlimited attempts to fix its fixer.

### Required evidence before enabling unattended operation

- Real signal -> linked incident -> scoped session -> reproduced fault -> verified fix -> approved release -> observed outcome.
- Duplicate, delayed, out-of-order and replayed events produce one logical work item with preserved occurrences.
- Storm and quota tests demonstrate bounded sessions, queues, queries and model use.
- Correlation tests include true matches, near misses, multiple concurrent releases and missing identifiers; false merges are measured.
- Cross-tenant/source access, revoked grants, log/ticket prompt injection, secret/PII leakage and production-write attempts are denied.
- Worker crash, stale lease, expired credentials, provider rate limits and notification failures preserve truthful state and recover safely.
- Service recovery is checked after release; recurrent symptoms reopen/escalate rather than being hidden behind a successful PR.

### Research and reuse

[HolmesGPT](https://github.com/HolmesGPT/holmesgpt) provides useful investigation/connector patterns and Apache-2.0 code. Its configurable toolsets and optional mutation/PR paths are not an Oryveta tenant or read-only guarantee. Reuse reviewed connector shapes where helpful; do not inherit broad shell authority or adopt the whole product as a free backend.

[OpenTelemetry log records](https://opentelemetry.io/docs/specs/otel/logs/data-model/) support consistent timestamps, resource and trace context. [Sentry Seer RCA](https://docs.sentry.io/product/ai-in-sentry/seer/root-cause-analysis/) is a reference for combining issue, source and telemetry context, not a required/free runtime dependency. Provider query/retention/egress and model costs must be accounted for separately.

The on-call audience is explicit. A project viewer or session invitee does not automatically receive production-log access. Distinguish permission to read evidence, start investigations, prepare fixes, execute approved runbooks and approve releases. Automatically creating a session never grants the original reporter or the surrounding Slack channel access to confidential telemetry.
