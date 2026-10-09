"""Regression tests for authentication, archive boundaries and worker fencing."""

from __future__ import annotations

import io
import stat
import time
import zipfile
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from oryveta_api.config import Settings
from oryveta_api.main import create_app
from oryveta_engine.repositories import (
    InvalidRepository,
    MAX_ARCHIVE,
    create_archive,
    fetch_public_github_repo,
    parse_github_url,
    snapshot_zip,
)
from oryveta_engine.worker import Worker


def zip_bytes(files: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


@pytest.mark.parametrize("filename", [
    "../escape.txt", "repo/../escape.txt", "repo/./escape.txt", "repo//escape.txt",
    "/absolute.txt", "repo/C:/secret.txt", "repo/\\\\server.txt",
])
def test_zip_rejects_noncanonical_paths_before_writing(tmp_path, filename):
    root = tmp_path / "import"
    with pytest.raises(InvalidRepository, match="Unsafe archive path"):
        snapshot_zip(root, zip_bytes({filename: "data"}))
    assert not root.exists()


def test_zip_rejects_file_directory_collision_before_writing(tmp_path):
    root = tmp_path / "import"
    with pytest.raises(InvalidRepository, match="collisions"):
        snapshot_zip(root, zip_bytes({"repo/a": "one", "repo/A/b.py": "two"}))
    assert not root.exists()


def test_zip_rejects_symlink_and_special_files(tmp_path):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        info = zipfile.ZipInfo("repo/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../../outside")
    with pytest.raises(InvalidRepository, match="Special file"):
        snapshot_zip(tmp_path / "import", out.getvalue())


def test_zip_rejects_expanded_size_limit_before_writing(tmp_path):
    root = tmp_path / "import"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("repo/oversize.txt", "a" * (3 * 1024 * 1024 + 1))
    assert len(out.getvalue()) < MAX_ARCHIVE
    with pytest.raises(InvalidRepository, match="Expanded archive"):
        snapshot_zip(root, out.getvalue())
    assert not root.exists()


def test_export_rejects_oversized_files_before_buffering(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    with (root / "large.bin").open("wb") as handle:
        handle.truncate(33 * 1024 * 1024)
    with pytest.raises(InvalidRepository, match="exceeds"):
        create_archive(root)


def test_export_does_not_follow_symlinks(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "good.txt").write_text("safe")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (root / "leak.txt").symlink_to(outside)
    with zipfile.ZipFile(io.BytesIO(create_archive(root))) as archive:
        assert archive.namelist() == ["good.txt"]


@pytest.mark.parametrize("url", [
    "https://github.com:8443/org/repo", "https://user@github.com/org/repo",
    "https://github.com/org/repo/branch", "https://github.com/org/..",
])
def test_github_url_rejects_untrusted_forms(url):
    with pytest.raises(InvalidRepository):
        parse_github_url(url)


def test_public_github_import_follows_only_approved_redirect(monkeypatch):
    def transport(request):
        if request.url.host == "api.github.com" and request.url.path == "/repos/org/repo":
            return httpx.Response(200, json={"private": False, "size": 5, "default_branch": "main"})
        if request.url.host == "api.github.com":
            return httpx.Response(302, headers={"Location": "https://codeload.github.com/org/repo/zip/main"})
        if request.url.host == "codeload.github.com":
            return httpx.Response(200, content=b"sample archive")
        raise AssertionError(f"Unexpected outbound host: {request.url.host}")

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(transport), **kw))
    assert fetch_public_github_repo("https://github.com/org/repo") == ("org/repo", b"sample archive")


def test_public_github_import_rejects_redirect_to_untrusted_host(monkeypatch):
    def transport(request):
        if request.url.path == "/repos/org/repo":
            return httpx.Response(200, json={"private": False, "size": 5, "default_branch": "main"})
        return httpx.Response(302, headers={"Location": "https://evil.example/archive"})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(transport), **kw))
    with pytest.raises(InvalidRepository, match="untrusted archive destination"):
        fetch_public_github_repo("https://github.com/org/repo")


def test_public_github_import_rejects_unbounded_response(monkeypatch):
    def transport(request):
        if request.url.path == "/repos/org/repo":
            return httpx.Response(200, json={"private": False, "size": 5, "default_branch": "main"})
        return httpx.Response(200, content=b"x" * (MAX_ARCHIVE + 1))

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(transport), **kw))
    with pytest.raises(InvalidRepository, match="exceeds"):
        fetch_public_github_repo("https://github.com/org/repo")


def test_github_oauth_callback_sets_session_and_no_store(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    settings = Settings(
        database_path=str(tmp_path / "auth.db"), workspace_root=str(tmp_path / "work"),
        github_client_id="test-id", github_client_secret="test-secret",
    )
    app = create_app(settings)

    class FakeGitHub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, **kwargs):
            assert url == "https://github.com/login/oauth/access_token"
            assert kwargs["data"]["client_secret"] == "test-secret"
            return httpx.Response(200, json={"access_token": "test-token"}, request=httpx.Request("POST", url))

        async def get(self, url, **kwargs):
            assert kwargs["headers"]["Authorization"] == "Bearer test-token"
            return httpx.Response(200, json={"id": 42, "login": "dev", "name": "Developer"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: FakeGitHub())
    with TestClient(app) as client:
        started = client.get("/auth/github", follow_redirects=False)
        assert started.headers["cache-control"] == "no-store"
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        callback = client.get(f"/auth/github/callback?state={state}&code=valid", follow_redirects=False)
        assert callback.status_code == 303
        assert callback.headers["cache-control"] == "no-store"
        assert "httponly" in callback.headers["set-cookie"].lower()
        assert client.get("/api/me").json()["login"] == "dev"
        assert client.get(f"/auth/github/callback?state={state}&code=valid").status_code == 403


def test_public_settings_require_https_and_secure_cookies(tmp_path):
    local = Settings(database_path=str(tmp_path / "db"), workspace_root=str(tmp_path / "work"))
    local.validate()
    with pytest.raises(ValueError, match="HTTPS and secure cookies"):
        replace(local, base_url="http://oryveta.example").validate()
    with pytest.raises(ValueError, match="HTTPS and secure cookies"):
        replace(local, base_url="https://oryveta.example", cookie_secure=False).validate()
    with pytest.raises(ValueError, match="both GitHub OAuth"):
        replace(local, github_client_id="partial").validate()
    replace(local, base_url="https://oryveta.example", cookie_secure=True).validate()


def test_worker_cannot_publish_stale_results(signed_in):
    client, headers = signed_in
    result = client.post(
        "/api/internal/evaluations/runs", json={"challenge": "iris", "seed": 3}, headers=headers,
    )
    assert result.status_code == 202
    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    job = worker.claim()
    assert job and job["id"] == result.json()["id"]
    with worker.db.connect() as conn:
        conn.execute("UPDATE jobs SET lease_token='new-worker', lease_until=? WHERE id=?",
                     (time.time() + 500, job["id"]))
    assert worker._finish(job, {"score": 1}) is False
    assert worker._fail(job, "Failure") is False
    with worker.db.connect() as conn:
        row = conn.execute("SELECT status,result_json FROM jobs WHERE id=?", (job["id"],)).fetchone()
    assert row["status"] == "running"
    assert row["result_json"] is None


def test_worker_does_not_publish_after_lease_expiry(signed_in):
    client, headers = signed_in
    job_id = client.post("/api/internal/evaluations/runs", json={"challenge": "iris"}, headers=headers).json()["id"]
    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    job = worker.claim()
    with worker.db.connect() as conn:
        conn.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time() - 1, job_id))
    assert worker._finish(job, {"score": 1}) is False
    assert worker._fail(job, "Failure") is False


def test_worker_error_is_sanitized_and_recorded(signed_in, monkeypatch):
    client, headers = signed_in
    job_id = client.post("/api/internal/evaluations/runs", json={"challenge": "iris"}, headers=headers).json()["id"]
    def broken(*_):
        raise RuntimeError("private-token-should-not-be-displayed")

    monkeypatch.setattr("oryveta_engine.worker.run_benchmark", broken)
    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    assert worker.run_once()
    with worker.db.connect() as conn:
        row = conn.execute("SELECT status,error FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "failed"
    assert row["error"] == "RuntimeError"
    assert "private-token" not in str(client.get("/api/internal/evaluations/runs").json())


def test_export_api_rejects_large_project(signed_in):
    client, headers = signed_in
    project = client.post("/api/projects", json={
        "name": "Large project", "brief": "A valid project to test archive limits",
        "blueprint": "python-api",
    }, headers=headers).json()
    root = client.app.state.settings.workspace_root
    from pathlib import Path
    path = Path(root) / "local-demo-user" / project["id"] / "large.bin"
    with path.open("wb") as handle:
        handle.truncate(33 * 1024 * 1024)
    response = client.get(f"/api/projects/{project['id']}/export")
    assert response.status_code == 413


def test_database_uses_wal_and_foreign_keys(signed_in):
    client, _ = signed_in
    with client.app.state.db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_concurrent_worker_claims_are_exclusive(signed_in):
    from concurrent.futures import ThreadPoolExecutor

    client, headers = signed_in
    job_id = client.post("/api/internal/evaluations/runs", json={"challenge": "iris"}, headers=headers).json()["id"]
    worker = Worker(client.app.state.db, client.app.state.settings.workspace_root)
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(lambda _: worker.claim(), range(6)))
    taken = [claim for claim in claims if claim]
    assert len(taken) == 1
    assert taken[0]["id"] == job_id


def test_zip_rejects_corrupt_payload_during_extraction(tmp_path):
    archive = bytearray(zip_bytes({"repo/hello.txt": "abcabcabcabc"}))
    # Mutate the stored file data without touching ZIP central directory metadata.
    offset = archive.index(b"abcabcabcabc")
    archive[offset] = ord("x")
    with pytest.raises(InvalidRepository, match="Corrupt or encrypted"):
        snapshot_zip(tmp_path / "import", bytes(archive))
