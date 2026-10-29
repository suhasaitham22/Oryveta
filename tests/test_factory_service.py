"""Session preservation and fail-closed startup for an unattended worker."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from oryveta_engine import factory_service
from oryveta_engine.factory_runtime import CredentialError, WorkerCredentials


@pytest.fixture
def seed():
    return json.dumps({
        "supabase_url": "https://stack.example.test",
        "publishable_key": "sb_publishable_test_only",
        "project_id": "3f0a1b2c-4d5e-4f60-8a71-9b0c1d2e3f40",
        "refresh_token": "initial-refresh-must-stay-private",
    })


def service_process(path, payload, *arguments):
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(factory_service.__file__).parent.parent),
        factory_service.BOOTSTRAP_ENV: payload,
    }
    return subprocess.run(
        [sys.executable, "-m", "oryveta_engine.factory_service",
         "--credentials", str(path), *arguments],
        env=environment, capture_output=True, text=True, timeout=5)


def test_restart_keeps_the_rotated_session_even_with_invalid_bootstrap(tmp_path, seed):
    path = tmp_path / "credentials.json"
    factory_service.bootstrap_credentials(path, seed)
    session = WorkerCredentials.load(path)
    session.record_session("new-access", "new-refresh", 1_900_000_000)
    before = path.read_bytes()
    factory_service.bootstrap_credentials(path, "expired or invalid bootstrap")
    factory_service.bootstrap_credentials(path, None)
    assert path.read_bytes() == before
    assert WorkerCredentials.load(path).refresh_token == "new-refresh"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("fault", ["corrupt", "permissions", "symlink", "directory", "fifo"])
def test_existing_invalid_state_is_not_replaced_by_bootstrap(tmp_path, seed, fault):
    path = tmp_path / "credentials.json"
    if fault == "symlink":
        path.symlink_to(tmp_path / "absent-target")
    elif fault == "directory":
        path.mkdir(mode=0o700)
    elif fault == "fifo":
        os.mkfifo(path, 0o600)
    else:
        path.write_text("broken JSON" if fault == "corrupt" else seed)
        path.chmod(0o644 if fault == "permissions" else 0o600)
    before = path.lstat()
    result = service_process(path, seed, "--once")
    assert result.returncode == 2
    assert path.lstat().st_ino == before.st_ino
    assert stat.S_IMODE(path.lstat().st_mode) == stat.S_IMODE(before.st_mode)
    assert "initial-refresh-must-stay-private" not in result.stdout + result.stderr


@pytest.mark.parametrize("payload", [None, "private-non-json-token", "[]", "{}",
                                     '{"refresh_token":"private-broken-token"}'])
def test_invalid_bootstrap_leaves_no_credential_or_partial_file(tmp_path, payload):
    with pytest.raises(CredentialError) as failure:
        factory_service.bootstrap_credentials(tmp_path / "credentials.json", payload)
    assert list(tmp_path.iterdir()) == []
    assert "private-" not in str(failure.value)


def test_concurrent_service_cannot_bootstrap_the_same_session(tmp_path, seed):
    path = tmp_path / "credentials.json"
    with factory_service.session_lock(tmp_path):
        result = service_process(path, seed, "--once")
    assert result.returncode == 2
    assert "another worker service" in result.stderr
    assert not path.exists()
    assert "initial-refresh-must-stay-private" not in result.stdout + result.stderr
    # After the owning process releases its lock, a new process can take over.
    result = subprocess.run(
        [sys.executable, "-c",
         "from pathlib import Path; import sys; "
         "from oryveta_engine.factory_service import session_lock; "
         "\nwith session_lock(Path(sys.argv[1])): print('acquired after release')",
         str(tmp_path)],
        env={**os.environ, "PYTHONPATH": str(Path(factory_service.__file__).parent.parent)},
        capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
    assert "acquired after release" in result.stdout


def test_symlinked_state_directory_does_not_change_target_permissions(tmp_path, seed):
    target = tmp_path / "other-directory"
    target.mkdir(mode=0o755)
    link = tmp_path / "state"
    link.symlink_to(target, target_is_directory=True)
    result = service_process(link / "credentials.json", seed, "--once")
    assert result.returncode == 2
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert list(target.iterdir()) == []


def test_root_cannot_change_an_arbitrary_credential_directory(tmp_path, monkeypatch):
    tmp_path.chmod(0o755)
    monkeypatch.setattr(factory_service.os, "geteuid", lambda: 0)
    with pytest.raises(CredentialError, match="root startup"):
        factory_service.prepare_directory(tmp_path / "credentials.json")
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755


def test_railway_without_its_persistent_volume_is_refused(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "synthetic-environment")
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH", raising=False)
    with pytest.raises(CredentialError, match="persistent volume"):
        factory_service.prepare_directory(factory_service.DEFAULT_CREDENTIALS)


def test_invalid_bootstrap_cli_fails_without_exposing_the_secret(tmp_path):
    result = service_process(tmp_path / "credentials.json", "private-bootstrap-secret", "--once")
    assert result.returncode == 2
    assert "readable JSON" in result.stderr
    assert "private-bootstrap-secret" not in result.stdout + result.stderr
    assert not (tmp_path / "credentials.json").exists()
