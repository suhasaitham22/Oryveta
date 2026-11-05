# Evolve: read-only patch proposal preview

**Scope:** The hosted/self-hosted HTTP patch-preview endpoints. These remain **read-only**: one text file, a hash-guarded baseline, a diff and a syntax check. They are not autonomous repair, not a code execution sandbox, not a GitHub pull request generator and not proof of runtime correctness.

**Do not confuse this with the local repair CLI.** A separate operator-run command, `python -m oryveta_engine.coding_runtime`, already performs model-driven edits across an operator-allowlisted file set and executes controller-owned behavioral checks in isolated containers, and it can re-verify a supplied candidate archive with no model contact at all. That capability is deliberately *not* wired into these endpoints, any project, the hosted site or any worker: it has no HTTP surface and runs only from an operator's shell on the operator's own hardware. See [IMPLEMENTATION.md](IMPLEMENTATION.md#local-verified-repair-cli). The endpoints below gained no execution, no multi-file scope and no verification authority from it.

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

The service checks a single text file up to 128 KiB and caps the diff at 24,000 characters. Python replacements are AST-parsed but **not executed**; for other languages only the source hash and diff are checked. A syntax-checked preview is never a verified production fix — and passing the separate local CLI's behavioral checks is not one either, since that only means the operator's declared contracts held for that candidate. The next milestones for *this* path are isolated test execution, persisted proposal records, explicit human approval, safe application in a separate worktree, GitHub App installation permissions and reviewable PR creation.

## Security

Never follow source symlinks or accept path traversal. Read from the authenticated user's bounded workspace only. No imported source is executed or loaded as a Python module. The service is currently a single-host MVP; hard multi-tenant OS/container isolation and runtime sandboxing remain future work.

## Optional AI-assisted proposal

An authenticated user can provide the **exact source text** they intend to change, its SHA-256, the relative path and a short instruction. The API verifies that the client-supplied text matches the hash and that the workspace file still matches before invoking the configured local Ollama model. The model returns a full replacement file, which is passed through the same bounded `preview_patch` validation and baseline check. The API returns only a reviewable diff and hashes, never applies changes, runs repository commands or publishes a PR. No source is transmitted to an unconfigured external model.

The proposal uses the same per-user daily token reservation as `/api/ai/generate`. Model output is untrusted, and passing syntax checks is not proof of correctness. Files larger than the 1,500-character client-source limit cannot use this first AI path. The hosted Vercel deployment never calls this endpoint: it is a browser client with no FastAPI backend, so these routes exist only on a self-hosted engine.
