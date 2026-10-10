"""No network, no real models: contract and budget security regressions."""

from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from oryveta_api.ai_budget import AiBudget, BudgetExceeded, DAILY_TOKEN_LIMIT, MAX_IN_FLIGHT
from oryveta_api.config import Settings
from oryveta_api.main import create_app
from oryveta_engine.model_runtime import (
    ModelCompletion, OllamaProvider, ProviderContractError,
    prompt_token_ceiling, validate_local_ollama_url,
)


class FakeModel:
    async def complete(self, prompt, *, max_output_tokens, temperature):
        return ModelCompletion("Safe suggestion", 12, min(6, max_output_tokens), "mock")


def test_disabled_by_default_and_csrf(signed_in):
    client, headers = signed_in
    assert client.get("/api/config").json().get("local_model_enabled") is False
    assert client.post("/api/ai/generate", json={"prompt": "Hello"}, headers=headers).status_code == 503
    assert client.get("/api/ai/budget").json()["allocated_tokens"] == 0
    assert client.post("/api/ai/generate", json={"prompt": "Hello"}).status_code == 403
    assert client.get("/api/ai/budget").status_code == 200


def enabled_client(tmp_path):
    settings = Settings(database_path=str(tmp_path / "ai.db"),
                        workspace_root=str(tmp_path / "work"), local_demo=True,
                        ollama_model="llama3.2:latest")
    app = create_app(settings)
    app.state.model_provider = FakeModel()
    client = TestClient(app)
    assert client.post("/auth/local-demo").status_code == 204
    headers = {"X-Oryveta-CSRF": client.get("/api/me").json()["csrf_token"]}
    return client, headers


def test_local_generation_and_private_audit(tmp_path):
    client, headers = enabled_client(tmp_path)
    r = client.post("/api/ai/generate", json={"prompt": "My secret prompt"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Safe suggestion"
    assert r.json()["usage"] == {"prompt_tokens": 12, "output_tokens": 6}
    assert r.json()["budget"]["allocated_tokens"] == 18
    assert r.json()["note"].startswith("Generated text is unverified")
    with client.app.state.db.connect() as conn:
        row = conn.execute("SELECT * FROM ai_calls").fetchone()
    assert row["status"] == "completed" and row["charged_tokens"] == 18
    assert "secret" not in json.dumps(dict(row)).lower()


def test_prompt_bytes_and_validation(tmp_path):
    client, headers = enabled_client(tmp_path)
    assert client.post("/api/ai/generate", json={"prompt": "🎯" * 1100},
                       headers=headers).status_code == 422
    assert client.post("/api/ai/generate", json={"prompt": "hi", "max_output_tokens": 513},
                       headers=headers).status_code == 422
    assert client.post("/api/ai/generate", json={"prompt": "hi", "temperature": 1.5},
                       headers=headers).status_code == 422
    assert prompt_token_ceiling("🧪") == len("🧪".encode()) + 128
    assert client.get("/api/ai/budget").json()["allocated_tokens"] == 0


def test_bad_provider_fails_closed_and_charges_reservation(tmp_path):
    client, headers = enabled_client(tmp_path)
    class Broken:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("secret-token-leaked-in-exception")
    client.app.state.model_provider = Broken()
    r = client.post("/api/ai/generate", json={"prompt": "Confidential"}, headers=headers)
    assert r.status_code == 502
    assert "secret-token" not in r.text
    assert client.get("/api/ai/budget").json()["allocated_tokens"] == (
        prompt_token_ceiling("Confidential") + 256)
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT status FROM ai_calls").fetchone()[0] == "failed"


def test_overusage_rejected_and_charged(tmp_path):
    client, headers = enabled_client(tmp_path)
    class Overuse:
        async def complete(self, *args, **kwargs):
            return ModelCompletion("over", 99999, 1, "mock")
    client.app.state.model_provider = Overuse()
    r = client.post("/api/ai/generate", json={"prompt": "x"}, headers=headers)
    assert r.status_code == 502
    assert client.get("/api/ai/budget").json()["allocated_tokens"] == 100000
    assert client.post("/api/ai/generate", json={"prompt": "x"}, headers=headers).status_code == 429


def test_budget_concurrent_reservations_are_atomic(signed_in):
    client, _ = signed_in
    budget = AiBudget(client.app.state.db)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: reserve_or_reject(budget, "local-demo-user"), range(8)))
    assert len([r for r in results if r]) == MAX_IN_FLIGHT
    assert budget.summary("local-demo-user")["active_calls"] == MAX_IN_FLIGHT
    assert budget.summary("other-user")["allocated_tokens"] == 0


def reserve_or_reject(budget, user_id):
    try:
        return budget.reserve(user_id, 100)
    except BudgetExceeded:
        return None


def test_budget_daily_limit_and_settlement(signed_in):
    client, _ = signed_in
    budget = AiBudget(client.app.state.db)
    a = budget.reserve("local-demo-user", DAILY_TOKEN_LIMIT - 100)
    assert budget.summary("local-demo-user")["remaining_tokens"] == 100
    with pytest.raises(BudgetExceeded):
        budget.reserve("local-demo-user", 101)
    assert budget.settle("local-demo-user", a, 10)
    assert not budget.settle("local-demo-user", a, 10)
    assert budget.summary("local-demo-user")["allocated_tokens"] == 10
    b = budget.reserve("local-demo-user", 100)
    assert budget.settle("local-demo-user", b, None)
    assert budget.summary("local-demo-user")["allocated_tokens"] == 110


def test_budget_expiry_charges_full_and_late_settlement_fails(signed_in):
    client, _ = signed_in
    budget = AiBudget(client.app.state.db)
    call_id = budget.reserve("local-demo-user", 200)
    with budget.db.connect() as conn:
        conn.execute("UPDATE ai_calls SET expires_at=? WHERE id=?", (time.time()-1, call_id))
    assert budget.summary("local-demo-user")["allocated_tokens"] == 200
    assert budget.summary("local-demo-user")["active_calls"] == 0
    assert not budget.settle("local-demo-user", call_id, 1)
    with budget.db.connect() as conn:
        row = conn.execute("SELECT status,charged_tokens FROM ai_calls WHERE id=?", (call_id,)).fetchone()
    assert (row["status"], row["charged_tokens"]) == ("expired", 200)


def test_budget_day_is_utc_and_owner_isolation(signed_in):
    client, _ = signed_in
    budget = AiBudget(client.app.state.db)
    assert budget.utc_day(0) == "1970-01-01"
    a = budget.reserve("local-demo-user", 30)
    assert not budget.settle("other-user", a, 0)
    assert budget.summary("other-user")["allocated_tokens"] == 0
    assert budget.settle("local-demo-user", a, 5)


def test_endpoint_auth_and_cross_account_isolation(tmp_path):
    client, headers = enabled_client(tmp_path)
    assert client.post("/api/ai/generate", json={"prompt": "hi"}).status_code == 403
    assert client.post("/api/ai/generate", json={"prompt": "hi"}, headers=headers).status_code == 200
    from oryveta_api.auth import new_session
    with client.app.state.db.connect() as conn:
        conn.execute("""INSERT INTO users(id,github_id,login,display_name,avatar_url,created_at)
            VALUES('another','another','another','Another','',0)""")
    other = TestClient(client.app)
    other.cookies.set("oryveta_session", new_session(client.app.state.db, "another"))
    assert other.get("/api/ai/budget").json()["allocated_tokens"] == 0
    assert client.get("/api/ai/budget").json()["allocated_tokens"] == 18


@pytest.mark.parametrize("url", [
    "http://169.254.169.254:11434", "http://localhost:1234",
    "https://localhost:11434", "http://user:pass@localhost:11434",
    "http://localhost:11434/evil", "http://localhost:11434/?foo=1",
    "http://evil.example:11434", "http://localhost:11434#x",
])
def test_ollama_url_is_restricted(url):
    with pytest.raises(ValueError):
        validate_local_ollama_url(url)


def test_valid_ollama_urls():
    assert validate_local_ollama_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"
    assert validate_local_ollama_url("http://ollama:11434") == "http://ollama:11434"
    with pytest.raises(ValueError):
        OllamaProvider("http://localhost:11434", "../malicious")


def test_ollama_provider_uses_fixed_model_and_output_limit(monkeypatch):
    calls = []
    def transport(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["model"] == "llama3.2:latest"
        assert body["options"]["num_predict"] == 25
        assert body["stream"] is False
        return httpx.Response(200, json={"done": True, "response": "Done",
                                          "prompt_eval_count": 12, "eval_count": 2,
                                          "model": "llama3.2:latest"})
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(
        transport=httpx.MockTransport(transport), **{k: v for k, v in kw.items()
                                                  if k != "follow_redirects"}))
    provider = OllamaProvider("http://localhost:11434", "llama3.2:latest")
    result = asyncio.run(provider.complete("Hello", max_output_tokens=25, temperature=0.3))
    assert result == ModelCompletion("Done", 12, 2, "llama3.2:latest")
    assert len(calls) == 1 and calls[0].url.path == "/api/generate"


@pytest.mark.parametrize("payload", [
    {"done": True, "response": "hi", "prompt_eval_count": 1, "eval_count": 999,
     "model": "llama3.2:latest"},
    {"done": True, "response": "hi", "prompt_eval_count": 1,
     "model": "llama3.2:latest"},
    {"done": True, "response": "hi", "prompt_eval_count": True, "eval_count": 1,
     "model": "llama3.2:latest"},
    {"done": True, "response": "hi", "prompt_eval_count": 1, "eval_count": 1,
     "model": "other-model"},
    {"done": False, "response": "hi", "prompt_eval_count": 1, "eval_count": 1,
     "model": "llama3.2:latest"},
])
def test_ollama_provider_rejects_untrusted_usage(monkeypatch, payload):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)), **kw))
    provider = OllamaProvider("http://localhost:11434", "llama3.2:latest")
    with pytest.raises(ProviderContractError):
        asyncio.run(provider.complete("hello", max_output_tokens=25, temperature=0.2))


def test_settings_rejects_unsafe_ollama_config(tmp_path):
    settings = Settings(database_path=str(tmp_path / "db"),
                        workspace_root=str(tmp_path / "work"),
                        ollama_model="llama3.2", ollama_url="http://evil.example:11434")
    with pytest.raises(ValueError):
        settings.validate()
