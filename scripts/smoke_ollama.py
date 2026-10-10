"""Explicit real-Ollama smoke test for a self-hosted Oryveta API.

Run with a local API started with ORYVETA_LOCAL_DEMO=true and an installed model.
This script deliberately refuses public/non-loopback endpoints and never prints
prompts, tokens, cookies or credentials.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit

import httpx


def main() -> int:
    base = os.environ.get("ORYVETA_SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    url = urlsplit(base)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        print("Smoke test refuses non-loopback HTTP targets", file=sys.stderr)
        return 2
    try:
        with httpx.Client(base_url=base, timeout=100, trust_env=False) as client:
            health = client.get("/api/health")
            health.raise_for_status()
            login = client.post("/auth/local-demo")
            if login.status_code != 204:
                print("Enable ORYVETA_LOCAL_DEMO=true for the local-only smoke test")
                return 2
            me = client.get("/api/me")
            me.raise_for_status()
            csrf = me.json()["csrf_token"]
            status = client.get("/api/ai/status")
            status.raise_for_status()
            data = status.json()
            if data["status"] != "ready":
                print("Ollama not ready:", data["status"])
                return 2
            result = client.post(
                "/api/ai/generate",
                headers={"X-Oryveta-CSRF": csrf},
                json={"prompt": "Respond with one short greeting.",
                      "max_output_tokens": 32, "temperature": 0},
            )
            result.raise_for_status()
            body = result.json()
            if not body["text"].strip() or body["usage"]["output_tokens"] < 1:
                print("Model returned an empty completion")
                return 1
            print("PASS: local Ollama model is ready; authenticated generation and usage accounting work.")
            return 0
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        print("Smoke test failed:", type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
