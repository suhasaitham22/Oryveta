"""Security and reliability regression tests for the functional MVP."""

import io
import time
import zipfile

from fastapi.testclient import TestClient

from oryveta_api.config import Settings
from oryveta_api.main import create_app
from oryveta_engine.repositories import InvalidRepository, snapshot_zip
from oryveta_engine.worker import MAX_ATTEMPTS, Worker


def test_oauth_callback_requires_browser_bound_state(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "auth.db"),
        workspace_root=str(tmp_path / "workspaces"),
        github_client_id="example-client", github_client_secret="test-only-secret",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        started = client.get("/auth/github", follow_redirects=False)
        assert started.status_code == 302
        assert "oryveta_oauth_state" in started.cookies
        # Even a valid state in SQLite must be bound to the initiating browser.
        from urllib.parse import parse_qs, urlsplit
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        stranger = TestClient(app)
        denied = stranger.get(f"/auth/github/callback?state={state}&code=forged")
        assert denied.status_code == 403
        # An unrelated state with the initiating browser cookie is also rejected.
        assert client.get("/auth/github/callback?state=wrong&code=forged").status_code == 403


def test_idempotent_benchmark_replays_only_same_request(signed_in):
    client, csrf = signed_in
    headers = {**csrf, "Idempotency-Key": "same-task"}
    first = client.post("/api/internal/evaluations/runs", json={"challenge": "iris", "seed": 10}, headers=headers)
    assert first.status_code == 202
    again = client.post("/api/internal/evaluations/runs", json={"challenge": "iris", "seed": 10}, headers=headers)
    assert again.status_code == 202
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["replayed"] is True
    conflict = client.post("/api/internal/evaluations/runs", json={"challenge": "iris", "seed": 11}, headers=headers)
    assert conflict.status_code == 409


def test_worker_exhausted_lease_becomes_terminal(signed_in):
    client, csrf = signed_in
    job = client.post("/api/internal/evaluations/runs", json={"challenge": "iris"}, headers=csrf).json()
    db = client.app.state.db
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET status='running',attempts=?,lease_until=?,lease_token='expired' WHERE id=?",
                     (MAX_ATTEMPTS, time.time()-10, job["id"]))
    worker = Worker(db, client.app.state.settings.workspace_root)
    assert worker.claim() is None
    with db.connect() as conn:
        result = conn.execute("SELECT status,error FROM jobs WHERE id=?", (job["id"],)).fetchone()
    assert (result["status"], result["error"]) == ("failed", "WorkerLeaseExpired")


def test_duplicate_zip_destinations_rejected(tmp_path):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("repo/src/main.py", "first")
        out.writestr("repo/src/MAIN.py", "second")
    import pytest
    with pytest.raises(InvalidRepository, match="duplicate"):
        snapshot_zip(tmp_path / "project", archive.getvalue())
