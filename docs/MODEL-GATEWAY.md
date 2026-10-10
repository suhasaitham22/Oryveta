# Local model gateway and token budget

**Scope:** Optional, text-only local Ollama integration in the self-hosted FastAPI service. The public Vercel preview remains static. No model is installed or launched by this change.

## Why this boundary exists

- Oryveta must work with open-weight models and no mandatory paid API keys.
- The user can submit only text, output length and temperature; **not** arbitrary URLs, model names, tools, shell commands or GitHub write permissions.
- The configured model is fixed by the operator through ORYVETA_OLLAMA_MODEL. By default this is empty, and generation responds with 503.
- Only http://127.0.0.1:11434, http://localhost:11434, http://[::1]:11434 or http://ollama:11434 are accepted as trusted operator endpoints. No redirects or proxy environment variables are followed.
- The ModelProvider protocol separates callers from provider implementations. OllamaProvider is the only real implementation; tests use a deterministic fake.

## Configuration

Install Ollama separately, pull a model that fits your own machine, then set the variables below on the API host:

```sh
ORYVETA_OLLAMA_URL=http://127.0.0.1:11434
ORYVETA_OLLAMA_MODEL=llama3.2:latest
```

Do not configure Ollama on an internet-exposed address. Docker Compose users can use http://ollama:11434 **only** on a private internal Docker network. No remote hosted inference, GPU rental or paid provider is provisioned.

## API

- GET /api/ai/budget — owner-only current UTC day token allocation, remaining budget and active calls.
- POST /api/ai/generate — authenticated and CSRF-protected text generation. JSON: prompt (1–4096 UTF-8 bytes), max_output_tokens (1–512, default 256), temperature (0–1).
- Returns generated text, provider model, provider-reported token usage, current budget and an explicit **unverified** disclaimer.
- 422 for invalid input; 429 with Retry-After for budget/concurrency exhaustion; 502 for invalid provider output or provider failure; 503 when disabled or reservation expired.

## Budget contract

- **20,000 allocated tokens per account per UTC day** and **two concurrent reservations per account**, serialized by SQLite BEGIN IMMEDIATE.
- Before contacting Ollama, reserve prompt UTF-8 bytes + 128 framing tokens + requested max output tokens. This is a deliberately conservative estimate for common tokenizers, not a universal tokenizer proof.
- On success, charge actual provider-reported prompt+output tokens. Reject responses exceeding the declared token/byte limits; over-reported usage is charged so the account cannot silently exceed its allowance.
- On timeout, crash, unknown usage or a 90-second reservation expiry, charge the **full reservation** (fail-closed). A late response cannot refund an expired reservation.
- Reservation records contain IDs, account, UTC day, status, token counts and timestamps, **not** prompts, responses or provider credentials.
- The 30-second asyncio deadline limits request lifetime. It does not terminate computation already in progress on the Ollama server.

## What is not yet implemented

Agent tool calling, repository modification, prompt injection defense for retrieved code, independent verification, GPU isolation, provider-agnostic streaming, durable idempotency for model calls, model cancellation, production usage billing and per-organization policy are still future milestones.

## Validation

Regression tests mock HTTP and model responses to cover auth, CSRF, tenant isolation, concurrent admission, UTC day accounting, conservative failure charging, malformed usage, provider allowlist, disabled-by-default behavior and response sanitization. CI passing does **not** establish real model quality, inference throughput or cloud readiness.
