"""Regression tests for enterprise job admission, cancellation and lease heartbeats."""

from __future__ import annotations

import io
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from oryveta_api.auth import new_session
from oryveta_api.main import MAX_ACTIVE_JOBS_PER_USER
from oryveta_engine.worker import Worker


def enqueue(client, headers, seed=42, key=None):
    h = {**headers}
    if key:
        h["Idempotency-Key"] = key
    return client.post("/api/internal/evaluations/runs",
                       json={"challenge": "iris", "seed": seed}, headers=h)


def archive_bytes():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("project/main.py", 'print("safe")\n')
    return stream.getvalue()


def test_status_is_owner_scoped_and_hides_lease_token(signed_in):
    client, headers = signed_in
    job_id = enqueue(client, headers).json()["id"]
    response = client.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert "lease_token" not in response.json()
    assert "result_json" not in response.json()
    assert client.get("/api/jobs/not-found").status_code == 404
    assert response.headers["cache-control"] == "no-store"


def test_cancel_queued_is_idempotent_and_releases_capacity(signed_in):
    client, headers = signed_in
    ids = [enqueue(client, headers, seed=i).json()["id"]
           for i in range(MAX_ACTIVE_JOBS_PER_USER)]
    rejected = enqueue(client, headers, seed=99)
    assert rejected.status_code == 429
    assert rejected.headers["retry-after"] == "30"
    assert client.post(f"/api/jobs/{ids[0]}/cancel").status_code == 403
    canceled = client.post(f"/api/jobs/{ids[0]}/cancel", headers=headers)
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    assert canceled.json()["replayed"] is False
    replay = client.post(f"/api/jobs/{ids[0]}/cancel", headers=headers)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert enqueue(client, headers, seed=100).status_code == 202
    assert client.get(f"/api/jobs/{ids[0]}").json()["status"] == "canceled"
    assert any(e["kind"] == "job_canceled" for e in client.get("/api/activity").json())


def test_concurrent_admission_is_atomic(signed_in):
    client, headers = signed_in
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(
            lambda seed: enqueue(client, headers, seed=seed).status_code, range(15)))
    assert results.count(202) == MAX_ACTIVE_JOBS_PER_USER
    assert results.count(429) == 15 - MAX_ACTIVE_JOBS_PER_USER
    assert client.get("/api/overview").json()["active_jobs"] == MAX_ACTIVE_JOBS_PER_USER


def test_idempotency_replay_works_at_capacity(signed_in):
    client, headers = signed_in
    original = enqueue(client, headers, seed=1, key="unique")
    assert original.status_code == 202
    for seed in range(2, MAX_ACTIVE_JOBS_PER_USER + 1):
        assert enqueue(client, headers, seed=seed).status_code == 202
    replay = enqueue(client, headers, seed=1, key="unique")
    assert replay.status_code == 202
    assert replay.json()["id"] == original.json()["id"]
    assert replay.json()["replayed"] is True
    assert enqueue(client, headers, seed=100, key="unique").status_code == 409


def test_rejected_import_has_no_orphan_project_or_workspace(signed_in):
    client, headers = signed_in
    for seed in range(MAX_ACTIVE_JOBS_PER_USER):
        assert enqueue(client, headers, seed=seed).status_code == 202
    response = client.post("/api/projects/import/zip",
                           headers={**headers, "Content-Type": "application/zip"},
                           content=archive_bytes())
    assert response.status_code == 429
    assert client.get("/api/projects").json() == []
    from pathlib import Path
    workspace = Path(client.app.state.settings.workspace_root) / "local-demo-user"
    assert not list(workspace.glob("*"))


def test_analysis_admission_limit(signed_in):
    client, headers = signed_in
    project = client.post("/api/projects", json={
        "name": "My app", "brief": "An application for verifying admission limits",
        "blueprint": "python-api",
    }, headers=headers).json()
    for seed in range(MAX_ACTIVE_JOBS_PER_USER):
        assert enqueue(client, headers, seed=seed).status_code == 202
    response = client.post(f"/api/projects/{project['id']}/analyze", headers=headers)
    assert response.status_code == 429
    with client.app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind='analyze'").fetchone()[0] == 0


def test_cancel_running_fences_results_and_retry(signed_in):
    client, headers = signed_in
    job_id = enqueue(client, headers).json()["id"]
    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    job = worker.claim()
    assert job["id"] == job_id
    assert worker.renew_lease(job)
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=headers).status_code == 200
    assert worker.renew_lease(job) is False
    assert worker._finish(job, {"untrusted": "result"}) is False
    assert worker._fail(job, "Failure") is False
    assert worker.claim() is None
    with worker.db.connect() as conn:
        row = conn.execute(
            "SELECT status,result_json,lease_token FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    assert row["status"] == "canceled"
    assert row["result_json"] is None
    assert row["lease_token"] is None


def test_terminal_job_cannot_be_canceled(signed_in):
    client, headers = signed_in
    job_id = enqueue(client, headers).json()["id"]
    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    assert worker.run_once()
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=headers).status_code == 409
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "succeeded"


def test_other_account_cannot_read_or_cancel(signed_in):
    client, headers = signed_in
    job_id = enqueue(client, headers).json()["id"]
    with client.app.state.db.connect() as conn:
        conn.execute("""INSERT INTO users(id,github_id,login,display_name,avatar_url,created_at)
            VALUES('another','another-gh','another','Another','',0)""")
    token = new_session(client.app.state.db, "another")
    other = TestClient(client.app)
    other.cookies.set("oryveta_session", token)
    csrf = other.get("/api/me").json()["csrf_token"]
    assert other.get(f"/api/jobs/{job_id}").status_code == 404
    assert other.post(f"/api/jobs/{job_id}/cancel",
                      headers={"X-Oryveta-CSRF": csrf}).status_code == 404
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "queued"


def test_cancel_imported_analysis_updates_project(signed_in):
    client, headers = signed_in
    response = client.post("/api/projects/import/zip",
                           headers={**headers, "Content-Type": "application/zip"},
                           content=archive_bytes())
    assert response.status_code == 201
    data = response.json()
    assert client.post(f"/api/jobs/{data['analysis_job_id']}/cancel",
                       headers=headers).status_code == 200
    assert client.get(f"/api/projects/{data['id']}").json()["status"] == "analysis_canceled"


def test_lease_renewal_rejects_expired_and_stolen_tokens(signed_in):
    client, headers = signed_in
    job_id = enqueue(client, headers).json()["id"]
    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    job = worker.claim()
    with worker.db.connect() as conn:
        conn.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time() - 1, job_id))
    assert not worker.renew_lease(job)
    with worker.db.connect() as conn:
        conn.execute("UPDATE jobs SET lease_until=?,lease_token=? WHERE id=?",
                     (time.time() + 60, "stolen", job_id))
    assert not worker.renew_lease(job)


def test_heartbeat_keeps_long_running_job_alive(signed_in, monkeypatch):
    client, headers = signed_in
    job_id = enqueue(client, headers).json()["id"]
    import oryveta_engine.worker as worker_module
    # Sub-second real-time leases are flaky under parallel CI runners. Use a
    # synchronization event to prove an actual renewal occurred instead of
    # assuming a sleeping thread will be scheduled within 180 milliseconds.
    monkeypatch.setattr(worker_module, "LEASE_SECONDS", 4.0)
    renewed = threading.Event()
    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    original_renew = worker.renew_lease

    def observe_renewal(job):
        ok = original_renew(job)
        if ok:
            renewed.set()
        return ok

    monkeypatch.setattr(worker, "renew_lease", observe_renewal)

    def slow_benchmark(*_):
        assert renewed.wait(timeout=10), "Heartbeat did not renew the running job"
        return {"result": "complete"}

    monkeypatch.setattr(worker_module, "run_benchmark", slow_benchmark)
    assert worker.run_once()
    assert renewed.is_set()
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "succeeded"


def test_cancel_in_flight_disallows_late_result(signed_in, monkeypatch):
    client, headers = signed_in
    job_id = enqueue(client, headers).json()["id"]
    entered = threading.Event()
    release = threading.Event()
    import oryveta_engine.worker as worker_module

    def waiting_benchmark(*_):
        entered.set()
        assert release.wait(5)
        return {"result": "must-not-persist"}

    monkeypatch.setattr(worker_module, "run_benchmark", waiting_benchmark)
    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(worker.run_once)
        try:
            assert entered.wait(5)
            response = client.post(f"/api/jobs/{job_id}/cancel", headers=headers)
            assert response.status_code == 200
        finally:
            release.set()
        assert task.result(timeout=5)
    with worker.db.connect() as conn:
        row = conn.execute("SELECT status,result_json FROM jobs WHERE id=?",
                           (job_id,)).fetchone()
    assert row["status"] == "canceled" and row["result_json"] is None
