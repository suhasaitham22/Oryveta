# Evolve: read-only patch proposal preview

**Scope:** First verification primitive for the future Evolve patch engine. This is not yet autonomous repair, a code execution sandbox, a GitHub pull request generator or proof of runtime correctness.

## API

`POST /api/projects/{project_id}/patch-preview` requires a signed-in account, ownership of the project and the standard CSRF header. Request JSON:

```json
{
  "path": "src/service.py",
  "expected_sha256": "<64 lowercase hex digits of current file bytes>",
  "replacement": "<entire proposed UTF-8 file contents>"
}
```

The response includes the old/new content hashes, bounded unified diff, explicit syntax/hash checks and status `review_required`. It **never writes to the repository** and sets `applied=false`, `behavior_verified=false`. The source hash guards against stale proposals; mismatch returns HTTP 409. Unsafe paths, symlinks, binaries, oversized source/replacement, invalid Python syntax and unsupported file types return HTTP 422. Access to another user's project returns 404.

## Independent evidence and limits

The service checks a single text file up to 128 KiB and caps the diff at 24,000 characters. Python replacements are AST-parsed but **not executed**; for other languages only the source hash and diff are checked. The next milestones are isolated test execution, persisted proposal records, explicit human approval, safe application in a separate worktree, GitHub App installation permissions and reviewable PR creation. Never advertise a syntax-checked preview as a verified production fix.

## Security

Never follow source symlinks or accept path traversal. Read from the authenticated user's bounded workspace only. No imported source is executed or loaded as a Python module. The service is currently a single-host MVP; hard multi-tenant OS/container isolation and runtime sandboxing remain future work.
