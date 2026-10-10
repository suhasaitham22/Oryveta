# Local model gateway and token budget

**Scope:** Optional, text-only local Ollama integration in the self-hosted FastAPI service. The public Vercel preview remains static. The optional Docker Compose overlay provisions an Ollama container and pulls an open-weight model on the user's own hardware; Vercel does not run the model.

## Why this boundary exists

- Oryveta must work with open-weight models and no mandatory paid API keys.
- The user can submit only text, output length and temperature; **not** arbitrary URLs, model names, tools, shell commands or GitHub write permissions.
- The configured model is fixed by the operator through ORYVETA_OLLAMA_MODEL. By default this is empty, and generation responds with 503.
- Only http://127.0.0.1:11434, http://localhost:11434, http://[::1]:11434 or http://ollama:11434 are accepted as trusted operator endpoints. No redirects or proxy environment variables are followed.
- The ModelProvider protocol separates callers from provider implementations. OllamaProvider is the only real implementation; tests use a deterministic fake.

## Ready-to-use local setup

**Prerequisites:** Python 3.11+, Ollama installed and sufficient local RAM/disk (a small 1.5B model is the default to reduce the footprint). Downloading weights requires internet; inference then runs locally. This does not create a hosted Ollama service.

```bash
ollama pull qwen2.5-coder:1.5b
# ollama serve  # only if the background service is not running
export ORYVETA_LOCAL_DEMO=true
export ORYVETA_OLLAMA_MODEL=qwen2.5-coder:1.5b
export ORYVETA_OLLAMA_URL=http://127.0.0.1:11434
uvicorn oryveta_api.main:app --host 127.0.0.1 --port 8000
# In another terminal:
python scripts/smoke_ollama.py
```

After local demo login, Overview contains the **Local AI assistant**. The status badge distinguishes `ready`, `model_missing`, `offline` and `disabled`. It uses the existing CSRF-protected, owner-scoped token budget.

**Optional Docker Compose deployment** (with real GitHub OAuth credentials configured):

```bash
docker compose -f compose.yaml -f compose.ollama.yaml config --quiet
docker compose -f compose.yaml -f compose.ollama.yaml up --build
```

The overlay adds `ollama`, a one-shot `ollama-pull` container and a persistent `ollama_models` volume. The API waits for the model download to finish before starting. Ollama is only reachable on the private Compose network, not from the internet. The default model is `qwen2.5-coder:1.5b` and can be overridden by the operator with `ORYVETA_OLLAMA_MODEL`. Docker local-demo login is disabled by design; configure a GitHub OAuth App or run the native loopback-only mode.

**Troubleshooting:** `model_missing` means the configured tag is not installed; run `ollama pull <tag>`. `offline` means the configured Ollama service is unreachable or returned an invalid response. Large models may exceed the 75-second request deadline on slow CPUs; use a smaller model or faster local hardware. The 120-second budget reservation TTL is longer than the model deadline, so failed requests cannot silently escape accounting.

## Configuration

Install Ollama separately, pull a model that fits your own machine, then set the variables below on the API host:

```sh
ORYVETA_OLLAMA_URL=http://127.0.0.1:11434
ORYVETA_OLLAMA_MODEL=llama3.2:latest
```

Do not configure Ollama on an internet-exposed address. Docker Compose users can use http://ollama:11434 **only** on a private internal Docker network. No remote hosted inference, GPU rental or paid provider is provisioned.

## API

- GET /api/ai/status — owner-only readiness probe of the configured Ollama model; reports disabled, offline, model_missing or ready without consuming inference tokens.
- GET /api/ai/budget — owner-only current UTC day token allocation, remaining budget and active calls.
- POST /api/ai/generate — authenticated and CSRF-protected text generation. JSON: prompt (1–4096 UTF-8 bytes), max_output_tokens (1–512, default 256), temperature (0–1).
- Returns generated text, provider model, provider-reported token usage, current budget and an explicit **unverified** disclaimer.
- 422 for invalid input; 429 with Retry-After for budget/concurrency exhaustion; 502 for invalid provider output or provider failure; 503 when disabled or reservation expired.

## Budget contract

- **20,000 allocated tokens per account per UTC day** and **two concurrent reservations per account**, serialized by SQLite BEGIN IMMEDIATE.
- Before contacting Ollama, reserve prompt UTF-8 bytes + 128 framing tokens + requested max output tokens. This is a deliberately conservative estimate for common tokenizers, not a universal tokenizer proof.
- On success, charge actual provider-reported prompt+output tokens. Reject responses exceeding the declared token/byte limits; over-reported usage is charged so the account cannot silently exceed its allowance.
- On timeout, crash, unknown usage or a 120-second reservation expiry, charge the **full reservation** (fail-closed). A late response cannot refund an expired reservation.
- Reservation records contain IDs, account, UTC day, status, token counts and timestamps, **not** prompts, responses or provider credentials.
- The 75-second asyncio deadline limits request lifetime. It does not terminate computation already in progress on the Ollama server.

## Optional Evolve patch proposals

The authenticated `POST /api/projects/{id}/ai-patch-preview` endpoint takes a client-supplied file, digest and instruction. It generates a **read-only** replacement suggestion, rechecks the baseline and returns a diff marked `review_required`. It uses the same token budget as ordinary text generation. The API never executes the model's code or writes files.

## What is not yet implemented

Agent tool calling, repository modification, prompt injection defense for retrieved code, independent verification, GPU isolation, provider-agnostic streaming, durable idempotency for model calls, model cancellation, production usage billing and per-organization policy are still future milestones.

## Validation

Regression tests include a real TCP loopback Ollama-compatible stub server and mock HTTP/model responses to cover auth, CSRF, tenant isolation, concurrent admission, UTC day accounting, conservative failure charging, malformed usage, provider allowlist, disabled-by-default behavior and response sanitization. CI passing does **not** establish real model quality, inference throughput or cloud readiness.
