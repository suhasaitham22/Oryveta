"""Real TCP HTTP path against a deterministic Ollama-compatible test server.

This exercises FastAPI authentication, CSRF, Ollama /api/tags and /api/generate,
response limits and SQLite budget settlement. It does not download model weights.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from oryveta_api.config import Settings
from oryveta_api.main import create_app
from oryveta_engine.model_runtime import (
    MAX_PROVIDER_RESPONSE_BYTES, OllamaProvider,
)


class StubOllama(BaseHTTPRequestHandler):
    model = "qwen2.5-coder:1.5b"
    catalog = True
    oversized = False
    requests = []

    def log_message(self, *_):
        pass

    def send_json(self, data):
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != "/api/tags":
            self.send_error(404)
            return
        self.send_json({"models": [{"name": self.model}] if self.catalog else []})

    def do_POST(self):
        if self.path != "/api/generate":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(body)
        self.requests.append(payload)
        if self.oversized:
            self.send_json({"padding": "x" * MAX_PROVIDER_RESPONSE_BYTES})
            return
        self.send_json({"done": True, "response": "The model responded.",
                        "prompt_eval_count": 8, "eval_count": 4,
                        "model": self.model})


@pytest.fixture
def ollama_stub():
    class Handler(StubOllama):
        catalog = True
        oversized = False
        requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Handler, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def client_with_ollama(tmp_path, ollama_stub):
    handler, url = ollama_stub
    app = create_app(Settings(database_path=str(tmp_path / "db"),
                              workspace_root=str(tmp_path / "work"),
                              local_demo=True, ollama_model=handler.model))
    # Test-only dynamic loopback port. Production URLs are always validated
    # and fixed to port 11434 by OllamaProvider.__init__.
    assert isinstance(app.state.model_provider, OllamaProvider)
    app.state.model_provider.base_url = url
    client = TestClient(app)
    assert client.post("/auth/local-demo").status_code == 204
    csrf = client.get("/api/me").json()["csrf_token"]
    return client, {"X-Oryveta-CSRF": csrf}


def test_tcp_end_to_end_status_generation_and_budget(tmp_path, ollama_stub):
    handler, _ = ollama_stub
    client, headers = client_with_ollama(tmp_path, ollama_stub)
    assert client.get("/api/ai/status").json() == {
        "status": "ready", "model": handler.model}
    assert client.get("/api/ai/budget").json()["allocated_tokens"] == 0
    r = client.post("/api/ai/generate",
                    json={"prompt": "Write a test", "max_output_tokens": 32},
                    headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "The model responded."
    assert r.json()["usage"] == {"prompt_tokens": 8, "output_tokens": 4}
    assert client.get("/api/ai/budget").json()["allocated_tokens"] == 12
    assert handler.requests[0]["model"] == handler.model
    assert handler.requests[0]["options"]["num_predict"] == 32
    assert handler.requests[0]["stream"] is False
    assert client.post("/api/ai/generate", json={"prompt": "hello"}).status_code == 403


def test_tcp_model_missing_is_reported_without_generation(tmp_path, ollama_stub):
    handler, _ = ollama_stub
    handler.catalog = False
    client, _ = client_with_ollama(tmp_path, ollama_stub)
    assert client.get("/api/ai/status").json()["status"] == "model_missing"
    assert client.get("/api/ai/budget").json()["allocated_tokens"] == 0


def test_tcp_oversized_provider_response_rejected_before_json_parse(tmp_path, ollama_stub):
    handler, _ = ollama_stub
    handler.oversized = True
    client, headers = client_with_ollama(tmp_path, ollama_stub)
    r = client.post("/api/ai/generate", json={"prompt": "hello"}, headers=headers)
    assert r.status_code == 502
    assert "Provider" not in r.text and "padding" not in r.text
    assert client.get("/api/ai/budget").json()["allocated_tokens"] > 0


def test_disabled_model_status_and_no_auth(signed_in):
    client, _ = signed_in
    assert client.get("/api/ai/status").json() == {"status": "disabled", "model": None}
    other = TestClient(client.app)
    assert other.get("/api/ai/status").status_code == 401
