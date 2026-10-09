# API and integration contracts

## Current public website

The deployed preview is a static site. Navigation and project brief drafting run in the browser, with no live server calls for Oryveta project creation or Evolve analysis. Do not document a static form submit as a real backend success.

## Local MVP (not yet deployed or copied to the remote repository)

The earlier local FastAPI source supports health/config, GitHub identity OAuth callback, local-only demo auth, logout, current user/session, owner-scoped projects, scaffold generation, bounded repository ZIP or public GitHub imports, analysis jobs, status/events and artifact export. This API requires live code verification and real credentials before hosted use.

## Target versioned HTTP resources

Auth: GET /api/v1/me; POST /api/v1/logout; GitHub OAuth start/callback; GitHub App installation callback and webhook.

Workspace: GET/POST /api/v1/organizations; GET/POST /api/v1/projects; POST /api/v1/projects/{id}/specifications; GET /api/v1/projects/{id}.

Start New: POST /api/v1/projects/{id}/plans; POST /api/v1/projects/{id}/builds; GET /api/v1/builds/{id}/artifacts.

Evolve: POST /api/v1/repository-imports; POST /api/v1/analyses; GET /api/v1/analyses/{id}/findings; POST /api/v1/change-proposals; POST /api/v1/change-proposals/{id}/execute.

Execution: GET /api/v1/tasks; GET /api/v1/tasks/{id}; POST /api/v1/tasks/{id}/cancel; GET /api/v1/tasks/{id}/events; POST /api/v1/approvals/{id}/decision.

Evidence: GET /api/v1/receipts/{id}; GET /api/v1/experiments; GET /api/v1/experiments/{id}/metrics.

These routes are **proposed**, not implemented endpoints.

## Contracts, auth and idempotency

Use an OpenAPI schema and generated TS/Python clients where practical. Validate requests (Zod/Pydantic) and model explicit states; enforce identity + tenant + resource permissions on each call. Every mutation that may retry accepts idempotency keys. Return clear structured errors: validation, unauthorized, forbidden, not found, conflict, quota exceeded, backend unavailable and verification failed.

Tasks contain contract version, owner, repository baseline, allowed tools/network, timeout/budget, approval rules and cancellation token. Events link evidence and immutable revisions, not raw secrets.

## GitHub integration

GitHub OAuth for login; GitHub App installation-token permissions for selected repositories; HMAC-validated webhooks; PR and CI workflows separate from simple login. Avoid storing broad long-lived personal access tokens.
