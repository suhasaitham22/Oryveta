"""Regression tests for enterprise job admission, cancellation and lease heartbeats."""

from __future__ import annotations

import io
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from oryveta_api.auth import new_session
from oryveta_api.main import MAX_ACTIVE_JOBS_PER_USER, create_app
from oryveta_engine.worker import MAX_ATTEMPTS, Worker


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

def test_job_list_and_event_timestamps_are_owner_scoped(signed_in):
    client, headers = signed_in
    job_id = enqueue(client, headers).json()["id"]
    queued = client.get("/api/jobs").json()
    assert queued[0]["id"] == job_id
    assert "events" not in queued[0]
    assert "started_at" not in queued[0]
    assert "finished_at" not in queued[0]

    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    assert worker.run_once()
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert [event["kind"] for event in detail["events"]] == [
        "benchmark_queued", "job_started", "job_completed"
    ]
    assert detail["started_at"] == detail["events"][1]["created_at"]
    assert detail["finished_at"] == detail["updated_at"]
    assert detail["finished_at"] >= detail["started_at"]
    assert all({"id", "kind", "detail", "created_at"} <= set(event)
               for event in detail["events"])
    assert all("lease_token" not in event and "result_json" not in event
               for event in detail["events"])


def test_job_list_project_filter_and_other_owner_isolation(signed_in):
    client, headers = signed_in
    project = client.post("/api/projects", json={
        "name": "Filtered app", "brief": "An application for filtering jobs safely",
        "blueprint": "python-api",
    }, headers=headers).json()
    matching = client.post(f"/api/projects/{project['id']}/analyze", headers=headers)
    assert matching.status_code == 202
    other_project = client.post("/api/projects", json={
        "name": "Other app", "brief": "An application for another job filter",
        "blueprint": "python-api",
    }, headers=headers).json()
    other_job = client.post(f"/api/projects/{other_project['id']}/analyze", headers=headers)
    assert other_job.status_code == 202
    matching_id = matching.json()["id"]
    other_id = other_job.json()["id"]
    assert [job["id"] for job in client.get("/api/jobs", params={"project_id": project["id"]}).json()] == [matching_id]
    assert [job["id"] for job in client.get("/api/jobs", params={"project_id": other_project["id"]}).json()] == [other_id]
    assert client.get("/api/jobs", params={"project_id": "missing"}).json() == []

    with client.app.state.db.connect() as conn:
        conn.execute("""INSERT INTO users(id,github_id,login,display_name,avatar_url,created_at)
            VALUES('job-owner-2','job-owner-2-gh','job-owner-2','Other','',0)""")
        conn.execute("""INSERT INTO jobs
            (id,user_id,project_id,kind,status,created_at,updated_at)
            VALUES('hidden-job','job-owner-2',NULL,'benchmark','queued',0,0)""")
    assert all(job["id"] not in {"hidden-job"} for job in client.get("/api/jobs").json())
    hidden_detail = client.get("/api/jobs/hidden-job")
    assert hidden_detail.status_code == 404


def test_studio_redirect_and_missing_build(monkeypatch, tmp_path):
    import oryveta_api.main as main_module
    monkeypatch.setattr(main_module, "WEB_DIR", tmp_path / "web")
    (tmp_path / "web").mkdir()
    settings = main_module.Settings(database_path=str(tmp_path / "db.sqlite"),
                                    workspace_root=str(tmp_path / "workspaces"),
                                    local_demo=True)
    client = TestClient(create_app(settings))
    assert client.post("/auth/local-demo").status_code == 204
    redirect = client.get("/studio", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/studio/"
    assert client.get("/studio/").status_code == 503
    assert client.get("/studio/demo-stories.json").status_code == 503
    assert client.get("/studio/template-license.txt").status_code == 503
    assert client.get("/studio/about").status_code == 503
    assert client.get("/studio/assets/%2E%2E/index.html").status_code == 404


def test_studio_partial_build_does_not_break_api_startup(monkeypatch, tmp_path):
    import oryveta_api.main as main_module

    monkeypatch.setattr(main_module, "WEB_DIR", tmp_path / "web")
    (tmp_path / "web" / "studio" / "dist-local").mkdir(parents=True)
    settings = main_module.Settings(database_path=str(tmp_path / "db.sqlite"),
                                    workspace_root=str(tmp_path / "workspaces"),
                                    local_demo=True)
    client = TestClient(create_app(settings))
    assert client.get("/api/health").status_code == 200
    assert client.get("/studio/").status_code == 503
    assert client.get("/studio/assets/missing.js").status_code == 404


def test_studio_deep_routes_fallback_without_masking_assets(monkeypatch, tmp_path):
    import oryveta_api.main as main_module

    monkeypatch.setattr(main_module, "WEB_DIR", tmp_path / "web")
    dist = tmp_path / "web" / "studio" / "dist-local"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id='root'></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    settings = main_module.Settings(database_path=str(tmp_path / "db.sqlite"),
                                    workspace_root=str(tmp_path / "workspaces"),
                                    local_demo=True)
    client = TestClient(create_app(settings))

    deep = client.get("/studio/about")
    assert deep.status_code == 200
    assert deep.text.startswith("<!doctype html>")
    assert client.get("/studio/workspace/evolve").status_code == 200
    assert client.get("/studio/assets/app.js").text == "console.log('ok')"
    assert client.get("/studio/assets/missing.js").status_code == 404
    assert client.get("/studio/missing.js").status_code == 404
    assert client.get("/studio/api/projects").status_code == 404


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


def test_failed_initial_analysis_marks_import_failed(signed_in):
    client, headers = signed_in
    response = client.post("/api/projects/import/zip",
                           headers={**headers, "Content-Type": "application/zip"},
                           content=archive_bytes())
    assert response.status_code == 201
    payload = response.json()
    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    job = worker.claim()
    assert job["id"] == payload["analysis_job_id"]
    assert worker._fail(job, "StaticScanError")
    project = client.get(f"/api/projects/{payload['id']}").json()
    assert project["status"] == "analysis_failed"
    assert project["analysis"] is None
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"


def test_expired_final_analysis_lease_is_failed_with_event(signed_in):
    client, headers = signed_in
    response = client.post("/api/projects/import/zip",
                           headers={**headers, "Content-Type": "application/zip"},
                           content=archive_bytes())
    assert response.status_code == 201
    payload = response.json()
    with client.app.state.db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET status='running', attempts=?,lease_until=?,lease_token='stale' WHERE id=?",
            (MAX_ATTEMPTS, time.time()-10, payload["analysis_job_id"]),
        )
    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    assert worker.claim() is None
    project = client.get(f"/api/projects/{payload['id']}").json()
    assert project["status"] == "analysis_failed"
    job = client.get(f"/api/jobs/{payload['analysis_job_id']}").json()
    assert job["status"] == "failed"
    assert job["error"] == "WorkerLeaseExpired"
    assert any(event["kind"] == "job_failed" for event in job["events"])
