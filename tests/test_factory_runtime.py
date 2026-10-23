"""Behavioral regressions for the durable factory worker's uncertain boundaries.

The worker in `oryveta_engine.factory_runtime` is only trustworthy if three
things hold under failure: a rejected or rotated credential never leaks and
never becomes a silent success, a fenced or timed-out run actually stops the
child process it owns, and every reported failure is one of the short codes the
metadata authority accepts. These tests drive those paths with real OS child
processes and an `httpx.MockTransport` control plane. No network, no GitHub
access and no real Supabase stack participate; the SQL-side authorization and
fencing rules are proved by the SQL tests instead.

A case added for a review finding names that finding (DR-00x / Fx) in a comment
next to the behaviour it pins, so a red run maps straight back to the finding it
came from.
"""

from __future__ import annotations

import datetime
import io
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from oryveta_engine import factory_runtime
from oryveta_engine.analysis_child import main as analysis_child_main
from oryveta_engine.factory_runtime import (
    MAX_PERSISTED_FINDINGS,
    MAX_RESULT_BYTES,
    REFRESH_SKEW_SECONDS,
    AnalysisProcessError,
    AnalysisRuntimeWorker,
    AnalysisTimeout,
    ControlPlaneUnavailable,
    CredentialError,
    FactoryRuntimeClient,
    FactoryRuntimeError,
    SourceCommitUnresolved,
    SourceIdentityConflict,
    WorkerCredentials,
    archive_commit,
    bound_result,
    error_code,
    minimal_child_environment,
    sweep_stale_work_roots,
)
from oryveta_engine.repositories import InvalidRepository

PROJECT_ID = "3f0a1b2c-4d5e-4f60-8a71-9b0c1d2e3f40"
RUN_ID = "22222222-2222-4222-8222-222222222222"
WORK_ITEM_ID = "11111111-1111-4111-8111-111111111111"
LEASE_TOKEN = "lease-fencing-value-for-tests"
PUBLISHABLE_KEY = "sb_publishable_test_only_value"
FIRST_REFRESH_TOKEN = "refresh-token-generation-0"
ARCHIVE_SHA = "0123456789abcdef0123456789abcdef01234567"

# The metadata authority's accepted shape for `work_items.error_code` and
# `fail_analysis_run(p_error_code)`.
ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,47}$")

CHILD_ENVIRONMENT_KEYS = {
    "PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING",
    "TMPDIR", "LC_ALL", "LANG",
}

# Children are launched through the `child_command` seam, so a test can choose
# exactly which process transition it needs without a real analysis.
SLEEPING_CHILD = "import time\ntime.sleep(120)\n"
REFUSING_CHILD = (
    "import sys\n"
    "sys.stderr.write('child refused the snapshot\\n')\n"
    "raise SystemExit(3)\n"
)
SILENT_CHILD = "pass\n"
RESULT_CHILD = (
    "import json, sys\n"
    "findings = [{'path': 'module_%d.py' % i, 'line': i, 'category': 'maintenance',\n"
    "             'title': 'Maintenance marker'} for i in range(250)]\n"
    "summary = {'language': 'Python', 'findings_count': 250, 'findings_truncated': False}\n"
    "with open(sys.argv[2], 'w', encoding='utf-8') as handle:\n"
    "    json.dump({'summary': summary, 'findings': findings}, handle)\n"
)

# The per-run marker the startup sweep identifies an attempt by: the owning
# worker PID, the run id and an ISO start time, and nothing else.
RUN_MARKER_NAME = ".oryveta-run.json"

SIGTERM_IGNORING_CHILD = (
    "import signal, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "time.sleep(120)\n"
)
GRANDCHILD_SPAWNING_CHILD = (
    "import os, subprocess, sys, time\n"
    "grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "with open(os.path.join(os.path.dirname(sys.argv[2]), 'grandchild.pid'),\n"
    "          'w', encoding='utf-8') as handle:\n"
    "    handle.write(str(grandchild.pid))\n"
    "    handle.flush()\n"
    "    os.fsync(handle.fileno())\n"
    "time.sleep(120)\n"
)
MARKER_REPORTING_CHILD = (
    "import json, os, sys\n"
    "directory = os.path.dirname(sys.argv[2])\n"
    f"with open(os.path.join(directory, '{RUN_MARKER_NAME}'), encoding='utf-8') as handle:\n"
    "    marker = json.load(handle)\n"
    "with open(sys.argv[2], 'w', encoding='utf-8') as handle:\n"
    "    json.dump({'summary': {'marker': marker, 'pid': os.getpid(),\n"
    "                           'pgid': os.getpgid(0)}, 'findings': []}, handle)\n"
)
SLOW_RESULT_CHILD = (
    "import json, sys, time\n"
    "time.sleep(2.5)\n"
    "with open(sys.argv[2], 'w', encoding='utf-8') as handle:\n"
    "    json.dump({'summary': {'language': 'Python'}, 'findings': []}, handle)\n"
)

# A real `analysis_child` process whose analysis never finishes on its own, so
# the child's own deadline and its parent-death detection are the only things
# that can end it.
SLOW_ANALYSIS_HARNESS = (
    "import sys, time\n"
    "from oryveta_engine import analysis_child\n"
    "analysis_child.analyze_repository = lambda root: time.sleep(30)\n"
    "raise SystemExit(analysis_child.main(sys.argv[1:]))\n"
)

# A stand-in for the worker process: it starts the analysis child in its own
# session exactly as the worker does, records the child's PID and then has its
# own PID killed, leaving the child with no parent left to fence it.
WORKER_STANDIN = (
    "import os, signal, subprocess, sys\n"
    "child = subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2], sys.argv[3],\n"
    "                          sys.argv[4], str(os.getpid())], start_new_session=True)\n"
    "with open(sys.argv[5], 'w', encoding='utf-8') as handle:\n"
    "    handle.write(str(child.pid))\n"
    "    handle.flush()\n"
    "    os.fsync(handle.fileno())\n"
    "os.kill(os.getpid(), signal.SIGKILL)\n"
)

DEFAULT_RPC_ROWS: dict[str, object] = {
    "claim_analysis_work": None,
    "heartbeat_analysis_run": {
        "lease_valid": True, "reason": None, "run_status": "running",
        "work_item_status": "running", "cancel_requested": False,
        "lease_expires_at": "2026-10-22T00:05:00+00:00", "phase": "analyzing",
    },
    "finish_analysis_run": {
        "accepted": True, "reason": None, "work_item_status": "succeeded",
    },
    "fail_analysis_run": {
        "accepted": True, "reason": None, "work_item_status": "failed",
        "retry_scheduled": False,
    },
}


# -- helpers --------------------------------------------------------------

def write_credentials(directory: Path, *, raw: str | None = None, mode: int = 0o600,
                      omit: tuple[str, ...] = (), **overrides) -> Path:
    """Create a worker credential file the way an operator provisions one."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "worker-credentials.json"
    payload: dict[str, object] = {
        "supabase_url": "https://stack.example.test",
        "publishable_key": PUBLISHABLE_KEY,
        "project_id": PROJECT_ID,
        "refresh_token": FIRST_REFRESH_TOKEN,
        "access_token": "",
        "expires_at": 0,
    }
    payload.update(overrides)
    for key in omit:
        payload.pop(key, None)
    path.write_text(raw if raw is not None else json.dumps(payload), encoding="utf-8")
    path.chmod(mode)
    return path


def claim_row(**overrides) -> dict:
    """A `claim_analysis_work` row as the SQL function returns it."""
    row = {
        "work_item_id": WORK_ITEM_ID,
        "run_id": RUN_ID,
        "attempt": 1,
        "max_attempts": 2,
        "lease_token": LEASE_TOKEN,
        "lease_expires_at": "2026-10-22T00:05:00+00:00",
        "kind": "repository_analysis",
        "source_url": "https://github.com/owner/repo",
        "source_owner": "owner",
        "source_repo": "repo",
        "input_digest": "sha256:" + "0" * 64,
        # DR-004: the source identity is pinned on the work item, so every
        # attempt fetches the same commit instead of re-resolving HEAD. The
        # previous attempt's ref and commit are no longer handed out.
        "pinned_source_ref": None,
        "pinned_source_commit": None,
        "previous_source_digest": None,
        "previous_checkpoint": None,
    }
    row.update(overrides)
    return row


def github_archive(files: dict[str, str], *, root: str | None = None,
                   comment: bytes | None = None) -> bytes:
    """An in-memory GitHub-shaped zipball; nothing is fetched.

    A real zipball abbreviates the commit in its single root folder and carries
    the whole commit in the ZIP archive comment, so that is the default shape
    here. `root` and `comment` override it for the degenerate archives.
    """
    prefix = f"owner-repo-{ARCHIVE_SHA[:7]}" if root is None else root
    declared = ARCHIVE_SHA.encode() if (root is None and comment is None) else comment
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, body in files.items():
            archive.writestr(f"{prefix}/{name}" if prefix else name, body)
        if declared:
            archive.comment = declared
    return stream.getvalue()


def wait_until_exited(child: subprocess.Popen, limit: float = 10.0) -> int | None:
    """Poll for a real process transition instead of trusting a fixed sleep."""
    deadline = time.monotonic() + limit
    while child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    return child.poll()


def wait_until_gone(pid: int, limit: float = 3.0) -> bool:
    """Poll until a process this test does not own has really gone away."""
    deadline = time.monotonic() + limit
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def kill_if_alive(pid: int) -> None:
    """Never leave a stray sleeper behind, even when an assertion fails."""
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def recorded_pid(path: Path, limit: float = 5.0) -> int:
    """Read a PID a real child wrote, waiting for the write to land."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            time.sleep(0.02)
    raise AssertionError(f"no process recorded a PID in {path.name}")


def reaped_pid() -> int:
    """A PID that is positively gone: a child this test started and reaped."""
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    return finished.pid


def lease_expiry_in(seconds: float) -> str:
    """A `lease_expires_at` as the control plane renders it, N seconds out."""
    moment = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
    return moment.isoformat()


def live_lease_state(**overrides) -> dict:
    """A valid heartbeat state whose lease is nowhere near expiry."""
    state = {
        "lease_valid": True, "reason": None, "run_status": "running",
        "work_item_status": "running", "cancel_requested": False,
        "lease_expires_at": lease_expiry_in(300), "phase": "analyzing",
    }
    state.update(overrides)
    return state


def run_marker(directory: Path, *, pid: int, body: str | None = None) -> Path:
    """Write the per-run marker the startup sweep identifies an attempt by."""
    (directory / "source").mkdir(parents=True, exist_ok=True)
    (directory / "source" / "main.py").write_text("value = 1\n", encoding="utf-8")
    marker = directory / RUN_MARKER_NAME
    marker.write_text(body if body is not None else json.dumps({
        "worker_pid": pid,
        "run_id": RUN_ID,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }), encoding="utf-8")
    return marker


class LoopedTooLong(BaseException):
    """Stops a continuous-mode regression instead of hanging the suite.

    `forever()` absorbs transient failures, so a loop that should have stopped
    is broken out of with a `BaseException` it cannot swallow.
    """


class FakeSupabase:
    """Auth plus PostgREST stand-in for `httpx.MockTransport`.

    Refresh tokens rotate and a spent one is refused, exactly as Supabase
    behaves, so a worker that fails to persist the rotated credential cannot
    pass these tests by accident.
    """

    def __init__(self, *, reject_rpc: bool = False, refuse_refresh: bool = False) -> None:
        self.refresh_token = FIRST_REFRESH_TOKEN
        self.generation = 0
        self.valid_access: set[str] = set()
        self.refresh_calls = 0
        self.rpc_calls = 0
        self.reject_rpc = reject_rpc
        self.refuse_refresh = refuse_refresh

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/token":
            return self._token(request)
        if request.url.path.startswith("/rest/v1/rpc/"):
            return self._rpc(request)
        return httpx.Response(404, json={"message": "unexpected path"})

    def _token(self, request: httpx.Request) -> httpx.Response:
        self.refresh_calls += 1
        if self.refuse_refresh:
            # A real Auth refusal body echoes the submitted token. Nothing from
            # this body may reach the worker's raised message or its output.
            return httpx.Response(400, json={
                "error": "invalid_grant",
                "error_description": f"Refresh Token {self.refresh_token} Not Found",
            })
        body = json.loads(request.content or b"{}")
        if body.get("refresh_token") != self.refresh_token:
            return httpx.Response(400, json={"error": "invalid_grant"})
        self.generation += 1
        self.refresh_token = f"refresh-token-generation-{self.generation}"
        access = f"access-token-generation-{self.generation}"
        self.valid_access = {access}
        return httpx.Response(200, json={
            "access_token": access,
            "refresh_token": self.refresh_token,
            "expires_in": 3600,
        })

    def _rpc(self, request: httpx.Request) -> httpx.Response:
        self.rpc_calls += 1
        presented = request.headers.get("authorization", "")
        accepted = {f"Bearer {token}" for token in self.valid_access}
        if self.reject_rpc or presented not in accepted:
            return httpx.Response(401, json={"message": "JWT expired"})
        return httpx.Response(200, json=[{"work_item_id": WORK_ITEM_ID, "status": "queued"}])


class RecordingClient:
    """Records the worker's RPC calls and answers them from a script.

    A list answer is consumed positionally per RPC name and its last element
    repeats; that is how "the lease goes invalid part-way through the run" is
    expressed without a database.
    """

    def __init__(self, *, answers: dict[str, object] | None = None,
                 registrations: list[dict] | None = None,
                 worker_user: str = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d") -> None:
        self.calls: list[tuple[str, dict]] = []
        self.selects: list[tuple[str, dict]] = []
        self._answers = dict(answers or {})
        self._registrations = list(registrations or [])
        self._worker_user = worker_user

    def rpc_row(self, name: str, payload: dict) -> dict | None:
        index = self.count(name)
        self.calls.append((name, payload))
        answer = self._answers.get(name, DEFAULT_RPC_ROWS.get(name))
        if callable(answer):
            return answer(payload, index)
        if isinstance(answer, list):
            return answer[min(index, len(answer) - 1)]
        return answer

    def select(self, table: str, params: dict[str, str]) -> list[dict]:
        self.selects.append((table, dict(params)))
        return list(self._registrations)

    def worker_user_id(self) -> str:
        return self._worker_user

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def payloads(self, name: str) -> list[dict]:
        return [payload for called, payload in self.calls if called == name]

    def count(self, name: str) -> int:
        return len(self.payloads(name))


class ClientContext:
    """`main()`'s `with FactoryRuntimeClient(...)` seam, answered by a recorder."""

    def __init__(self, client: RecordingClient) -> None:
        self._client = client

    def __enter__(self) -> RecordingClient:
        return self._client

    def __exit__(self, *_: object) -> None:
        return None


class ScriptedChildWorker(AnalysisRuntimeWorker):
    """Supervises a real child process chosen by the test.

    `child_command` exists as an overridable seam precisely so supervision,
    cancellation and timeout can be exercised against a genuine OS process
    without running the analyzer.
    """

    script = SLEEPING_CHILD

    def child_command(self, snapshot: Path, result_path: Path) -> list[str]:
        return [sys.executable, "-c", self.script, str(snapshot), str(result_path)]


def build_worker(client: RecordingClient, *, script: str | None = None,
                 max_run_seconds: int = 60, work_root: Path | None = None
                 ) -> AnalysisRuntimeWorker:
    worker_type = AnalysisRuntimeWorker if script is None else ScriptedChildWorker
    worker = worker_type(
        client=client, project_id=PROJECT_ID, lease_seconds=15,
        max_run_seconds=max_run_seconds, poll_seconds=0.01, work_root=work_root,
    )
    if script is not None:
        worker.script = script
    return worker


def prepared_run(tmp_path: Path) -> tuple[Path, Path]:
    """A per-run directory with an already-extracted snapshot inside it."""
    directory = tmp_path / "run"
    directory.mkdir()
    snapshot = directory / "source"
    snapshot.mkdir()
    (snapshot / "main.py").write_text("value = 1\n", encoding="utf-8")
    return directory, snapshot


@pytest.fixture
def fast_supervision(monkeypatch):
    """Shorten the heartbeat poll so supervised-process tests stay quick."""
    monkeypatch.setattr(factory_runtime, "MAX_HEARTBEAT_INTERVAL", 0.05)


@pytest.fixture
def spawned_children(monkeypatch):
    """Capture the real children the worker starts, to prove termination."""
    processes: list[subprocess.Popen] = []

    class Recorded(subprocess.Popen):
        def __init__(self, *arguments, **keywords):
            super().__init__(*arguments, **keywords)
            processes.append(self)

    monkeypatch.setattr(factory_runtime.subprocess, "Popen", Recorded)
    return processes


@pytest.fixture
def fast_termination(monkeypatch):
    """Shorten the SIGTERM grace so the escalation path is quick to observe."""
    monkeypatch.setattr(factory_runtime, "TERMINATE_GRACE_SECONDS", 0.2)


@pytest.fixture
def fast_control_plane_retry(monkeypatch):
    """Keep the bounded heartbeat retry's backoff out of the wall clock."""
    monkeypatch.setattr(factory_runtime, "HEARTBEAT_RETRY_BACKOFF_SECONDS", 0.01)


# -- credential loading ---------------------------------------------------

def test_missing_credential_file_is_refused(tmp_path):
    with pytest.raises(CredentialError, match="does not exist"):
        WorkerCredentials.load(tmp_path / "absent.json")


def test_symlinked_credential_file_is_refused(tmp_path):
    # A symlink lets another account swap the file the worker trusts.
    real = write_credentials(tmp_path / "secrets")
    link = tmp_path / "linked-credentials.json"
    link.symlink_to(real)
    with pytest.raises(CredentialError, match="symlink"):
        WorkerCredentials.load(link)


def test_group_or_world_readable_credential_file_is_refused(tmp_path):
    path = write_credentials(tmp_path / "secrets", mode=0o644)
    with pytest.raises(CredentialError, match="chmod 600"):
        WorkerCredentials.load(path)


def test_non_json_credential_file_is_refused(tmp_path):
    path = write_credentials(tmp_path / "secrets", raw="refresh_token=plain-text\n")
    with pytest.raises(CredentialError, match="readable JSON"):
        WorkerCredentials.load(path)


def test_json_array_credential_file_is_refused(tmp_path):
    path = write_credentials(tmp_path / "secrets", raw='["refresh-token"]')
    with pytest.raises(CredentialError, match="JSON object"):
        WorkerCredentials.load(path)


@pytest.mark.parametrize("missing", ["refresh_token", "publishable_key"])
def test_incomplete_credential_file_is_refused(tmp_path, missing):
    path = write_credentials(tmp_path / "secrets", omit=(missing,))
    with pytest.raises(CredentialError, match="publishable_key and refresh_token"):
        WorkerCredentials.load(path)


@pytest.mark.parametrize("endpoint", [
    "http://metadata.example.test",
    "http://10.0.0.7:8000",
    "https://stack.example.test:443/rest/v1",
    "https://user:pass@stack.example.test",
    "ftp://stack.example.test",
    "",
])
def test_unsafe_supabase_endpoint_is_refused(tmp_path, endpoint):
    path = write_credentials(tmp_path / "secrets", supabase_url=endpoint)
    with pytest.raises(CredentialError):
        WorkerCredentials.load(path)


def test_loopback_http_endpoint_is_accepted_for_a_local_stack(tmp_path):
    path = write_credentials(tmp_path / "secrets", supabase_url="http://127.0.0.1:54321")
    assert WorkerCredentials.load(path).supabase_url == "http://127.0.0.1:54321"


def test_well_formed_credential_file_loads_without_exposing_tokens(tmp_path):
    path = write_credentials(
        tmp_path / "secrets", refresh_token="refresh-value-must-not-print",
        access_token="access-value-must-not-print", expires_at=1_900_000_000)
    credentials = WorkerCredentials.load(path)
    assert credentials.supabase_url == "https://stack.example.test"
    assert credentials.project_id == PROJECT_ID
    assert credentials.refresh_token == "refresh-value-must-not-print"
    assert credentials.expires_at == 1_900_000_000.0
    # An accidental log line, traceback frame or debugger repr must stay safe.
    text = repr(credentials)
    assert str(path) in text
    for secret in ("refresh-value-must-not-print", "access-value-must-not-print",
                   PUBLISHABLE_KEY):
        assert secret not in text


# -- session refresh ------------------------------------------------------

def test_expired_session_refreshes_and_persists_the_rotated_credential(tmp_path, capsys):
    directory = tmp_path / "secrets"
    path = write_credentials(directory, access_token="spent-access-token",
                             expires_at=time.time() - 30)
    stack = FakeSupabase()
    with FactoryRuntimeClient(WorkerCredentials.load(path),
                              transport=stack.transport()) as client:
        token = client.access_token()

    assert token == "access-token-generation-1"
    assert stack.refresh_calls == 1
    stored = json.loads(path.read_text(encoding="utf-8"))
    # The rotated refresh token must be durable before it is relied upon.
    assert stored["refresh_token"] == "refresh-token-generation-1"
    assert FIRST_REFRESH_TOKEN not in path.read_text(encoding="utf-8")
    assert stored["access_token"] == "access-token-generation-1"
    assert stored["expires_at"] > time.time()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # The replacement is atomic: no partially written sibling survives it.
    assert sorted(entry.name for entry in directory.iterdir()) == [path.name]
    captured = capsys.readouterr()
    for stream in (captured.out, captured.err):
        assert "refresh-token-generation" not in stream
        assert "access-token-generation" not in stream


def test_session_near_expiry_refreshes_then_the_fresh_token_is_reused(tmp_path):
    path = write_credentials(tmp_path / "secrets", access_token="nearly-expired-access",
                             expires_at=time.time() + REFRESH_SKEW_SECONDS - 5)
    stack = FakeSupabase()
    with FactoryRuntimeClient(WorkerCredentials.load(path),
                              transport=stack.transport()) as client:
        first = client.access_token()
        assert stack.refresh_calls == 1
        # Still comfortably inside its lifetime: no second refresh request.
        assert client.access_token() == first
        assert client.access_token() == first
        assert stack.refresh_calls == 1


def test_valid_stored_session_is_used_without_contacting_auth(tmp_path):
    path = write_credentials(tmp_path / "secrets", access_token="still-valid-access",
                             expires_at=time.time() + 3600)
    stack = FakeSupabase()
    with FactoryRuntimeClient(WorkerCredentials.load(path),
                              transport=stack.transport()) as client:
        assert client.access_token() == "still-valid-access"
    assert stack.refresh_calls == 0


def test_refused_refresh_raises_without_disclosing_the_token(tmp_path, capsys):
    path = write_credentials(tmp_path / "secrets")
    stack = FakeSupabase(refuse_refresh=True)
    with FactoryRuntimeClient(WorkerCredentials.load(path),
                              transport=stack.transport()) as client:
        with pytest.raises(CredentialError) as excinfo:
            client.access_token()

    message = str(excinfo.value)
    assert "HTTP 400" in message
    assert "re-provision" in message
    assert FIRST_REFRESH_TOKEN not in message
    assert "invalid_grant" not in message
    # A refused refresh must not overwrite the credential the operator provisioned.
    assert json.loads(path.read_text(encoding="utf-8"))["refresh_token"] == FIRST_REFRESH_TOKEN
    captured = capsys.readouterr()
    assert FIRST_REFRESH_TOKEN not in captured.out + captured.err


def test_refresh_returning_no_access_token_is_refused(tmp_path):
    path = write_credentials(tmp_path / "secrets")

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"refresh_token": "rotated", "expires_in": 3600})

    with FactoryRuntimeClient(WorkerCredentials.load(path),
                              transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(CredentialError, match="no access token"):
            client.access_token()


# -- one-shot retry -------------------------------------------------------

def test_unauthorized_request_is_retried_once_after_a_refresh(tmp_path, capsys):
    path = write_credentials(tmp_path / "secrets", access_token="stale-access-token",
                             expires_at=time.time() + 3600)
    stack = FakeSupabase()
    with FactoryRuntimeClient(WorkerCredentials.load(path),
                              transport=stack.transport()) as client:
        row = client.rpc_row("claim_analysis_work", {"p_project_id": PROJECT_ID})

    assert row == {"work_item_id": WORK_ITEM_ID, "status": "queued"}
    assert stack.rpc_calls == 2
    assert stack.refresh_calls == 1
    captured = capsys.readouterr()
    assert "stale-access-token" not in captured.out + captured.err
    assert "access-token-generation-1" not in captured.out + captured.err


def test_persistent_unauthorized_request_fails_loudly(tmp_path, capsys):
    path = write_credentials(tmp_path / "secrets", access_token="stale-access-token",
                             expires_at=time.time() + 3600)
    stack = FakeSupabase(reject_rpc=True)
    with FactoryRuntimeClient(WorkerCredentials.load(path),
                              transport=stack.transport()) as client:
        with pytest.raises(FactoryRuntimeError) as excinfo:
            client.rpc_row("claim_analysis_work", {"p_project_id": PROJECT_ID})

    # Exactly one retry, then an honest failure rather than a silent empty row.
    assert stack.rpc_calls == 2
    assert "401" in str(excinfo.value)
    captured = capsys.readouterr()
    for secret in ("stale-access-token", FIRST_REFRESH_TOKEN, "access-token-generation-1"):
        assert secret not in captured.out + captured.err
        assert secret not in str(excinfo.value)


# -- error codes ----------------------------------------------------------

@pytest.mark.parametrize("exception, expected", [
    (InvalidRepository("Only public https URLs are supported"), "invalid_repository"),
    (AnalysisTimeout("too long"), "analysis_timeout"),
    (AnalysisProcessError("child died"), "analysis_process_failed"),
    (CredentialError("refresh refused"), "worker_credentials_rejected"),
    (httpx.ConnectError("name resolution failed"), "source_fetch_failed"),
    (httpx.ReadTimeout("archive stalled"), "source_fetch_failed"),
    (httpx.StreamConsumed(), "source_fetch_failed"),
    (json.JSONDecodeError("Expecting value", "", 0), "analysis_output_invalid"),
    (ValueError("analysis child produced no summary object"), "analysis_output_invalid"),
    (OSError("no space left on device"), "worker_storage_error"),
    (PermissionError("/home/worker/credentials.json"), "worker_storage_error"),
    (RuntimeError("unexpected"), "worker_error"),
    (KeyError("run_id"), "worker_error"),
    (Exception("bare"), "worker_error"),
])
def test_error_code_is_an_enumerated_short_code(exception, expected):
    code = error_code(exception)
    assert code == expected
    # The persisted code must never be able to carry a message, path or secret.
    assert ERROR_CODE_PATTERN.fullmatch(code)


def test_error_code_never_echoes_the_exception_text():
    exception = OSError("/Users/operator/.oryveta/worker-credentials.json is unreadable")
    code = error_code(exception)
    assert code == "worker_storage_error"
    assert "operator" not in code and "/" not in code


# -- bounded results -----------------------------------------------------

def test_bound_result_trims_findings_and_reports_the_cap_honestly():
    findings = [{"path": f"module_{index}.py", "line": index, "title": "Maintenance marker"}
                for index in range(MAX_PERSISTED_FINDINGS + 50)]
    bounded = bound_result({
        "summary": {"language": "Python", "findings_count": len(findings),
                    "findings_returned": len(findings), "findings_truncated": False},
        "findings": findings,
    })
    assert len(bounded["findings"]) == MAX_PERSISTED_FINDINGS
    assert bounded["findings"] == findings[:MAX_PERSISTED_FINDINGS]
    assert bounded["summary"]["findings_persisted"] == MAX_PERSISTED_FINDINGS
    assert bounded["summary"]["findings_persisted_truncated"] is True
    # The analyzer's own accounting is preserved next to the worker's cap, so a
    # reader can see both how much evidence exists and how much was stored.
    assert bounded["summary"]["findings_count"] == MAX_PERSISTED_FINDINGS + 50
    assert bounded["summary"]["findings_truncated"] is False
    assert bounded["summary"]["language"] == "Python"
    assert set(bounded) == {"summary", "findings"}


def test_bound_result_keeps_a_small_result_whole_and_flags_nothing():
    findings = [{"path": "a.py", "line": 1, "title": "Maintenance marker"}]
    bounded = bound_result({"summary": {"language": "Python"}, "findings": findings})
    assert bounded["findings"] == findings
    assert bounded["summary"]["findings_persisted"] == 1
    assert bounded["summary"]["findings_persisted_truncated"] is False


def test_bound_result_tolerates_a_missing_findings_list():
    bounded = bound_result({"summary": {"language": "Unknown"}})
    assert bounded["findings"] == []
    assert bounded["summary"]["findings_persisted"] == 0
    assert bounded["summary"]["findings_persisted_truncated"] is False


@pytest.mark.parametrize("payload", [
    {}, {"findings": []}, {"summary": None}, {"summary": "ok"}, {"summary": []},
    [], "result", None,
])
def test_bound_result_refuses_a_result_without_a_summary_object(payload):
    with pytest.raises(ValueError, match="no summary object"):
        bound_result(payload)


def test_oversized_result_drops_findings_and_says_so():
    # A large summary still has to fit, so evidence rows are dropped rather
    # than failing the attempt - and the summary admits it.
    summary = {"language": "Python", "technology": {"notes": "x" * 200_000}}
    findings = [{"path": "a.py", "line": 1, "title": "y" * 1000} for _ in range(300)]
    bounded = bound_result({"summary": summary, "findings": findings})
    assert bounded["findings"] == []
    assert bounded["summary"]["findings_persisted"] == 0
    assert bounded["summary"]["findings_persisted_truncated"] is True
    assert len(json.dumps(bounded).encode("utf-8")) <= MAX_RESULT_BYTES


def test_summary_that_cannot_fit_at_all_is_refused():
    summary = {"language": "Python", "technology": {"notes": "x" * (MAX_RESULT_BYTES + 1000)}}
    with pytest.raises(ValueError, match="exceeds the persisted result limit"):
        bound_result({"summary": summary, "findings": []})


# -- archive identity ----------------------------------------------------

def test_archive_commit_resolves_the_commit_from_a_real_zipball():
    payload = github_archive({"README.md": "# demo\n", "src/main.py": "value = 1\n"})
    assert archive_commit(payload) == ARCHIVE_SHA


def test_a_real_zipball_abbreviates_the_commit_and_declares_it_in_the_comment():
    # The shape the live endpoint really returns: pallets/click arrives as
    # pallets-click-2247b35/ with the whole commit in the archive comment, so
    # the root folder alone never carries an identity an attempt could pin.
    commit = "2247b35ea1c47c727d7a06e51fa280e12a863ff6"
    payload = github_archive({"README.md": "# click\n"},
                             root=f"pallets-click-{commit[:7]}", comment=commit.encode())
    assert archive_commit(payload) == commit


def test_a_dashed_repository_name_does_not_confuse_the_root_cross_check():
    commit = "2247b35ea1c47c727d7a06e51fa280e12a863ff6"
    payload = github_archive({"README.md": "# demo\n"},
                             root=f"pallets-click-7-{commit[:7]}", comment=commit.encode())
    assert archive_commit(payload) == commit


def test_an_archive_whose_root_and_comment_disagree_is_refused():
    # Resolving either value would pin an identity the archive itself
    # contradicts, so the attempt fails rather than picking a side.
    commit = "2247b35ea1c47c727d7a06e51fa280e12a863ff6"
    payload = github_archive({"README.md": "# demo\n"}, root="pallets-click-deadbee",
                             comment=commit.encode())
    with pytest.raises(SourceIdentityConflict):
        archive_commit(payload)


@pytest.mark.parametrize("comment", [b"", b"Created by GitHub", b"\xff\xfe binary",
                                     b"0123456789ABCDEF0123456789ABCDEF01234567"])
def test_a_comment_that_is_not_a_commit_falls_back_to_the_root(comment):
    payload = github_archive({"README.md": "# demo\n"},
                             root="owner-repo-" + "b" * 40, comment=comment)
    assert archive_commit(payload) == "b" * 40


@pytest.mark.parametrize("root", ["repo", "owner-repo-main", "owner-repo-" + "g" * 40,
                                  "owner-repo-" + "a" * 39, f"owner-repo-{ARCHIVE_SHA[:7]}"])
def test_archive_without_a_commit_root_resolves_nothing(root):
    payload = github_archive({"README.md": "# demo\n"}, root=root)
    assert archive_commit(payload) is None


def test_empty_archive_resolves_nothing():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w"):
        pass
    assert archive_commit(stream.getvalue()) is None


@pytest.mark.parametrize("payload", [b"", b"not a zip archive", b"PK\x03\x04truncated"])
def test_non_zip_payload_resolves_nothing(payload):
    assert archive_commit(payload) is None


# -- child environment ---------------------------------------------------

def test_child_environment_excludes_the_parent_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("ORYVETA_WORKER_CREDENTIALS", "/parentonlyvalue/credentials.json")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "parentonlyvalue-service-role")
    monkeypatch.setenv("GITHUB_TOKEN", "parentonlyvalue-github-token")
    monkeypatch.setenv("PATH", "/parentonlyvalue/bin")
    monkeypatch.setenv("LANG", "parentonlyvalue-locale")
    work = tmp_path / "run"
    work.mkdir()

    environment = minimal_child_environment(work)

    assert set(environment) == CHILD_ENVIRONMENT_KEYS
    for inherited in ("ORYVETA_WORKER_CREDENTIALS", "SUPABASE_SERVICE_ROLE_KEY",
                      "GITHUB_TOKEN", "HOME"):
        assert inherited not in environment
    assert "parentonlyvalue" not in " ".join(environment.values())
    assert environment["PATH"] == "/usr/bin:/bin"
    assert environment["LANG"] == "C.UTF-8"
    assert environment["TMPDIR"] == str(work)
    for name in environment:
        assert not re.search(r"token|secret|password|credential|api_?key", name, re.IGNORECASE)


def test_child_environment_points_python_at_the_engine_package(tmp_path):
    environment = minimal_child_environment(tmp_path)
    root = Path(environment["PYTHONPATH"])
    assert (root / "oryveta_engine" / "__init__.py").is_file()
    assert (root / "oryveta_engine" / "analysis_child.py").is_file()


# -- supervised child ----------------------------------------------------

def test_lost_lease_terminates_the_child_and_publishes_nothing(
        tmp_path, fast_supervision, spawned_children, capsys):
    client = RecordingClient(answers={"heartbeat_analysis_run": [{
        "lease_valid": False, "reason": "cancelled", "run_status": "cancelled",
        "work_item_status": "cancelled", "cancel_requested": True, "phase": "analyzing",
    }]})
    worker = build_worker(client, script=SLEEPING_CHILD)
    directory, snapshot = prepared_run(tmp_path)

    assert worker._analyse_in_child(claim_row(), snapshot, directory) is None

    assert len(spawned_children) == 1
    # Cancellation must actually stop the CPU work, not merely discard output.
    assert wait_until_exited(spawned_children[0]) is not None
    assert "finish_analysis_run" not in client.names()
    assert "fail_analysis_run" not in client.names()
    assert f"run {RUN_ID} terminated child: cancelled" in capsys.readouterr().out


@pytest.mark.parametrize("reason", ["worker_not_registered", "lease_lost", "not_running"])
def test_every_fencing_reason_stops_the_child(
        tmp_path, fast_supervision, spawned_children, reason, capsys):
    client = RecordingClient(answers={"heartbeat_analysis_run": [
        {"lease_valid": False, "reason": reason},
    ]})
    worker = build_worker(client, script=SLEEPING_CHILD)
    directory, snapshot = prepared_run(tmp_path)

    assert worker._analyse_in_child(claim_row(), snapshot, directory) is None
    assert wait_until_exited(spawned_children[0]) is not None
    assert reason in capsys.readouterr().out


def test_bounded_runtime_terminates_the_child_and_maps_to_analysis_timeout(
        tmp_path, fast_supervision, spawned_children):
    client = RecordingClient()
    worker = build_worker(client, script=SLEEPING_CHILD, max_run_seconds=1)
    directory, snapshot = prepared_run(tmp_path)

    with pytest.raises(AnalysisTimeout) as excinfo:
        worker._analyse_in_child(claim_row(), snapshot, directory)

    assert error_code(excinfo.value) == "analysis_timeout"
    assert wait_until_exited(spawned_children[0]) is not None
    assert "finish_analysis_run" not in client.names()


def test_child_exiting_non_zero_maps_to_analysis_process_failed(
        tmp_path, fast_supervision, capsys):
    client = RecordingClient()
    worker = build_worker(client, script=REFUSING_CHILD)
    directory, snapshot = prepared_run(tmp_path)

    with pytest.raises(AnalysisProcessError) as excinfo:
        worker._analyse_in_child(claim_row(), snapshot, directory)

    assert error_code(excinfo.value) == "analysis_process_failed"
    # Child diagnostics go to the operator's output, never to a persisted row.
    assert "child refused the snapshot" in capsys.readouterr().out
    assert "finish_analysis_run" not in client.names()


def test_child_exiting_without_a_result_maps_to_analysis_process_failed(
        tmp_path, fast_supervision):
    client = RecordingClient()
    worker = build_worker(client, script=SILENT_CHILD)
    directory, snapshot = prepared_run(tmp_path)

    with pytest.raises(AnalysisProcessError) as excinfo:
        worker._analyse_in_child(claim_row(), snapshot, directory)

    assert error_code(excinfo.value) == "analysis_process_failed"


def test_child_result_is_bounded_before_it_leaves_the_worker(tmp_path, fast_supervision):
    client = RecordingClient()
    worker = build_worker(client, script=RESULT_CHILD)
    directory, snapshot = prepared_run(tmp_path)

    result = worker._analyse_in_child(claim_row(), snapshot, directory)

    assert set(result) == {"summary", "findings"}
    assert len(result["findings"]) == MAX_PERSISTED_FINDINGS
    assert result["summary"]["findings_persisted"] == MAX_PERSISTED_FINDINGS
    assert result["summary"]["findings_persisted_truncated"] is True
    assert result["summary"]["findings_count"] == 250
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESULT_BYTES


def test_supervised_child_receives_no_credentials(tmp_path, fast_supervision, monkeypatch):
    # The child's own view of its environment proves the boundary, rather than
    # trusting the parent's dictionary.
    monkeypatch.setenv("ORYVETA_WORKER_CREDENTIALS", "/parentonlyvalue/credentials.json")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "parentonlyvalue-service-role")
    monkeypatch.setenv("ORYVETA_LEASE_TOKEN", "parentonlyvalue-lease")
    script = (
        "import json, os, sys\n"
        "with open(sys.argv[2], 'w', encoding='utf-8') as handle:\n"
        "    json.dump({'summary': {'environment': dict(os.environ)},\n"
        "               'findings': []}, handle)\n"
    )
    client = RecordingClient()
    worker = build_worker(client, script=script)
    directory, snapshot = prepared_run(tmp_path)

    result = worker._analyse_in_child(claim_row(), snapshot, directory)

    seen = result["summary"]["environment"]
    assert CHILD_ENVIRONMENT_KEYS <= set(seen)
    for inherited in ("ORYVETA_WORKER_CREDENTIALS", "SUPABASE_SERVICE_ROLE_KEY",
                      "ORYVETA_LEASE_TOKEN", "HOME"):
        assert inherited not in seen
    assert "parentonlyvalue" not in " ".join(seen.values())
    assert LEASE_TOKEN not in " ".join(seen.values())
    for name in seen:
        assert not re.search(r"token|secret|password|credential|api_?key", name, re.IGNORECASE)


def test_valid_result_is_published_exactly_once(tmp_path, fast_supervision, monkeypatch, capsys):
    archive = github_archive({"README.md": "# demo\n", "src/main.py": "value = 1\n"})
    # DR-004: the fetch seam takes an optional pinned commit.
    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo",
                        lambda url, ref=None: ("owner/repo", archive))
    client = RecordingClient()
    worker = build_worker(client, script=RESULT_CHILD, work_root=tmp_path / "work")

    worker._execute(claim_row())

    assert client.count("finish_analysis_run") == 1
    assert client.count("fail_analysis_run") == 0
    published = client.payloads("finish_analysis_run")[0]
    assert published["p_run_id"] == RUN_ID
    assert published["p_lease_token"] == LEASE_TOKEN
    assert len(published["p_result"]["findings"]) == MAX_PERSISTED_FINDINGS
    assert published["p_result"]["summary"]["findings_persisted"] == MAX_PERSISTED_FINDINGS
    assert published["p_result"]["summary"]["findings_persisted_truncated"] is True
    assert published["p_result"]["summary"]["language"] == "Python"

    # The run's phase trail and its resolved source identity are recorded before
    # the result is offered, so `finish_analysis_run` cannot hit
    # `source_identity_missing`.
    heartbeats = client.payloads("heartbeat_analysis_run")
    assert [beat["p_phase"] for beat in heartbeats if beat["p_phase"]] == [
        "fetching_source", "analyzing", "recording_result"]
    identity = [beat for beat in heartbeats if beat["p_source_digest"]]
    assert len(identity) == 1
    assert identity[0]["p_source_digest"].startswith("sha256:")
    assert identity[0]["p_source_commit"] == ARCHIVE_SHA
    assert identity[0]["p_source_ref"] == "github.com/owner/repo"
    assert identity[0]["p_checkpoint"]["resumed_attempt"] is False
    assert f"{MAX_PERSISTED_FINDINGS} findings persisted" in capsys.readouterr().out


def test_refused_result_is_reported_and_not_claimed_as_success(
        tmp_path, fast_supervision, monkeypatch, capsys):
    archive = github_archive({"README.md": "# demo\n"})
    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo",
                        lambda url, ref=None: ("owner/repo", archive))
    client = RecordingClient(answers={"finish_analysis_run": {
        "accepted": False, "reason": "source_identity_missing",
        "work_item_status": "running",
    }})
    worker = build_worker(client, script=RESULT_CHILD, work_root=tmp_path / "work")

    worker._execute(claim_row())

    output = capsys.readouterr().out
    assert "result refused: source_identity_missing" in output
    assert "findings persisted" not in output
    assert client.count("finish_analysis_run") == 1
    assert client.count("fail_analysis_run") == 0


def test_frozen_identity_divergence_is_refused_before_any_network_access(
        tmp_path, monkeypatch):
    # The SQL mirror of parse_github_url froze owner/repo at admission. If the
    # frozen URL no longer parses to the same pair, this attempt must not fetch
    # anything at all.
    fetched: list[str] = []

    def record_fetch(url: str, ref: str | None = None) -> tuple[str, bytes]:
        fetched.append(url)
        return "owner/repo", github_archive({"README.md": "# demo\n"})

    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo", record_fetch)
    client = RecordingClient()
    worker = build_worker(client, work_root=tmp_path / "work")

    worker._execute(claim_row(source_repo="another-repository"))

    assert fetched == []
    assert client.count("heartbeat_analysis_run") == 0
    assert client.count("finish_analysis_run") == 0
    assert client.payloads("fail_analysis_run")[0]["p_error_code"] == "invalid_repository"


def test_fetched_identity_mismatch_is_refused_before_analysis(tmp_path, monkeypatch):
    # A redirect, cache or edited project that answers with another repository
    # must not be analysed under the frozen work item's identity.
    archive = github_archive({"README.md": "# demo\n"})
    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo",
                        lambda url, ref=None: ("someone/else", archive))
    client = RecordingClient()
    worker = build_worker(client, work_root=tmp_path / "work")

    worker._execute(claim_row())

    assert client.count("finish_analysis_run") == 0
    assert client.payloads("fail_analysis_run")[0]["p_error_code"] == "invalid_repository"


def test_run_directory_is_removed_even_when_the_attempt_fails(tmp_path, monkeypatch):
    def refused(url: str, ref: str | None = None):
        raise InvalidRepository("Only public https://github.com/owner/repo URLs are supported")

    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo", refused)
    work_root = tmp_path / "work"
    client = RecordingClient()
    worker = build_worker(client, work_root=work_root)

    worker._execute(claim_row())

    # The disposable snapshot directory is gone even though the attempt failed.
    assert work_root.is_dir()
    assert list(work_root.iterdir()) == []


# -- claim and failure reporting -----------------------------------------

def test_run_once_reports_no_work_without_touching_anything_else():
    client = RecordingClient()
    worker = build_worker(client)
    assert worker.run_once() is False
    assert client.names() == ["claim_analysis_work"]


def test_claim_requests_the_configured_project_and_lease():
    client = RecordingClient(answers={"claim_analysis_work": None})
    worker = build_worker(client)
    worker.claim()
    assert client.payloads("claim_analysis_work")[0] == {
        "p_project_id": PROJECT_ID, "p_lease_seconds": 15,
    }


def test_failed_analysis_reports_the_mapped_code_exactly_once(tmp_path, capsys):
    # An unparseable frozen URL fails before any network access, so the failure
    # reporting path is exercised without a fetch.
    client = RecordingClient(answers={
        "claim_analysis_work": claim_row(source_url="https://gitlab.com/owner/repo"),
    })
    worker = build_worker(client, work_root=tmp_path / "work")

    assert worker.run_once() is True

    assert client.count("fail_analysis_run") == 1
    reported = client.payloads("fail_analysis_run")[0]
    assert reported["p_run_id"] == RUN_ID
    assert reported["p_lease_token"] == LEASE_TOKEN
    assert reported["p_error_code"] == "invalid_repository"
    assert ERROR_CODE_PATTERN.fullmatch(reported["p_error_code"])
    assert client.count("finish_analysis_run") == 0
    assert client.count("heartbeat_analysis_run") == 0
    assert f"run {RUN_ID} failed: invalid_repository" in capsys.readouterr().out


def test_retry_and_terminal_failure_are_reported_distinctly(tmp_path, capsys):
    client = RecordingClient(answers={
        "claim_analysis_work": claim_row(source_url="https://gitlab.com/owner/repo"),
        "fail_analysis_run": {"accepted": True, "reason": None,
                              "work_item_status": "queued", "retry_scheduled": True},
    })
    worker = build_worker(client, work_root=tmp_path / "work")
    assert worker.run_once() is True
    assert f"run {RUN_ID} will be retried" in capsys.readouterr().out

    exhausted = RecordingClient(answers={
        "claim_analysis_work": claim_row(source_url="https://gitlab.com/owner/repo",
                                         attempt=2),
        "fail_analysis_run": {"accepted": True, "reason": None,
                              "work_item_status": "failed", "retry_scheduled": False},
    })
    worker = build_worker(exhausted, work_root=tmp_path / "work")
    assert worker.run_once() is True
    assert f"work item {WORK_ITEM_ID} failed terminally" in capsys.readouterr().out


def test_refused_failure_report_is_surfaced(tmp_path, capsys):
    client = RecordingClient(answers={
        "claim_analysis_work": claim_row(source_url="https://gitlab.com/owner/repo"),
        "fail_analysis_run": {"accepted": False, "reason": "lease_lost"},
    })
    worker = build_worker(client, work_root=tmp_path / "work")
    assert worker.run_once() is True
    assert "failure report refused: lease_lost" in capsys.readouterr().out


def test_unreportable_failure_falls_back_to_lease_expiry(tmp_path, capsys):
    def unavailable(payload, index):
        raise FactoryRuntimeError("POST /rest/v1/rpc/fail_analysis_run failed with HTTP 503")

    client = RecordingClient(answers={
        "claim_analysis_work": claim_row(source_url="https://gitlab.com/owner/repo"),
        "fail_analysis_run": unavailable,
    })
    worker = build_worker(client, work_root=tmp_path / "work")

    # The worker must not crash: the work item is recovered by lease expiry.
    assert worker.run_once() is True
    assert client.count("fail_analysis_run") == 1
    assert "the lease will expire and be reclaimed" in capsys.readouterr().out


def test_heartbeat_without_a_run_state_is_an_error():
    client = RecordingClient(answers={"heartbeat_analysis_run": None})
    worker = build_worker(client)
    with pytest.raises(FactoryRuntimeError, match="no run state"):
        worker.heartbeat(claim_row(), phase="analyzing")


@pytest.mark.parametrize("lease_seconds", [0, 14, 901, -1])
def test_out_of_range_lease_is_refused_at_construction(lease_seconds):
    with pytest.raises(ValueError, match="lease seconds"):
        AnalysisRuntimeWorker(client=RecordingClient(), project_id=PROJECT_ID,
                              lease_seconds=lease_seconds)


def test_non_positive_run_bound_is_refused_at_construction():
    with pytest.raises(ValueError, match="maximum run seconds"):
        AnalysisRuntimeWorker(client=RecordingClient(), project_id=PROJECT_ID,
                              max_run_seconds=0)


# -- registration --------------------------------------------------------

def test_unregistered_worker_fails_fast_with_an_actionable_message():
    client = RecordingClient(registrations=[])
    worker = build_worker(client)
    with pytest.raises(FactoryRuntimeError, match="register_project_worker"):
        worker.verify_registration()


def test_revoked_registration_is_not_treated_as_a_grant():
    client = RecordingClient(registrations=[{"id": "r-1", "label": "ci", "enabled": False}])
    worker = build_worker(client)
    with pytest.raises(FactoryRuntimeError, match="no enabled registration"):
        worker.verify_registration()


def test_enabled_registration_is_returned_and_scoped_to_this_worker():
    client = RecordingClient(registrations=[
        {"id": "r-1", "label": "revoked", "enabled": False},
        {"id": "r-2", "label": "ci-runner", "enabled": True},
    ])
    worker = build_worker(client)

    assert worker.verify_registration() == {"id": "r-2", "label": "ci-runner", "enabled": True}

    table, params = client.selects[-1]
    assert table == "project_workers"
    assert params["project_id"] == f"eq.{PROJECT_ID}"
    assert params["worker_user_id"] == f"eq.{client.worker_user_id()}"


# -- analysis child entry point ------------------------------------------

@pytest.mark.parametrize("argv", [[], ["only-one"], ["a", "b", "c", "d", "e"]])
def test_analysis_child_refuses_wrong_argument_counts(argv, capsys):
    assert analysis_child_main(argv) == 2
    assert "usage" in capsys.readouterr().err


def test_analysis_child_refuses_a_missing_snapshot_root(tmp_path, capsys):
    assert analysis_child_main([str(tmp_path / "absent"), str(tmp_path / "result.json")]) == 2
    assert "snapshot root" in capsys.readouterr().err
    assert not (tmp_path / "result.json").exists()


def test_analysis_child_refuses_a_file_or_symlink_as_snapshot_root(tmp_path):
    plain = tmp_path / "plain.txt"
    plain.write_text("not a directory\n", encoding="utf-8")
    assert analysis_child_main([str(plain), str(tmp_path / "result.json")]) == 2

    real = tmp_path / "snapshot"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    assert analysis_child_main([str(link), str(tmp_path / "result.json")]) == 2


def test_analysis_child_refuses_a_missing_result_directory(tmp_path, capsys):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    missing = tmp_path / "absent" / "result.json"
    assert analysis_child_main([str(snapshot), str(missing)]) == 2
    assert "result directory" in capsys.readouterr().err


def test_analysis_child_writes_a_complete_result_atomically(tmp_path):
    snapshot = tmp_path / "snapshot"
    (snapshot / "src").mkdir(parents=True)
    (snapshot / "README.md").write_text("# demo\n", encoding="utf-8")
    (snapshot / "src" / "main.py").write_text(
        "import os\n\n\ndef run():\n    # TODO: tighten this\n    return os.getcwd()\n",
        encoding="utf-8")
    output = tmp_path / "out"
    output.mkdir()
    result_path = output / "result.json"

    assert analysis_child_main([str(snapshot), str(result_path)]) == 0

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert set(result) == {"summary", "findings"}
    assert result["summary"]["source_files_analyzed"] == 1
    assert result["summary"]["language"] == "Python"
    assert result["summary"]["input_fingerprint_sha256"]
    assert any(finding["title"] == "Maintenance marker" for finding in result["findings"])
    # Atomic replacement leaves no partial or temporary sibling behind.
    assert [entry.name for entry in output.iterdir()] == ["result.json"]
    # The result the worker would publish stays inside the persisted bound.
    bounded = bound_result(result)
    assert len(json.dumps(bounded).encode("utf-8")) <= MAX_RESULT_BYTES


def test_analysis_child_result_is_json_the_worker_can_bound(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "app.ts").write_text("console.log('hi')\n", encoding="utf-8")
    result_path = tmp_path / "result.json"

    assert analysis_child_main([str(snapshot), str(result_path)]) == 0

    bounded = bound_result(json.loads(result_path.read_text(encoding="utf-8")))
    assert bounded["summary"]["findings_persisted"] == len(bounded["findings"])
    assert bounded["summary"]["findings_persisted_truncated"] is False
    assert os.path.isfile(result_path)


# -- continuous mode -----------------------------------------------------

def test_forever_stops_when_this_worker_lost_its_authority(tmp_path):
    # F2: today every `run_once` exception is swallowed and the loop polls
    # again, so a revoked or undesignated worker spins against a control plane
    # that will never hand it work. Post-fix a failure re-checks the
    # registration and the refusal propagates.
    def failing_claim(payload, index):
        if index >= 4:
            raise LoopedTooLong("forever() kept claiming after the registration was gone")
        raise FactoryRuntimeError("POST /rest/v1/rpc/claim_analysis_work failed with HTTP 403")

    client = RecordingClient(answers={"claim_analysis_work": failing_claim}, registrations=[])
    worker = build_worker(client, work_root=tmp_path / "work")

    with pytest.raises(FactoryRuntimeError, match="register_project_worker"):
        worker.forever()

    assert client.count("claim_analysis_work") == 1
    assert [table for table, _ in client.selects] == ["project_workers"]

    # A refused credential is still terminal on its own, with no round trip to
    # the control plane to confirm what the worker already knows.
    def refused_credential(payload, index):
        raise CredentialError("worker session refresh was refused (HTTP 400)")

    stale = RecordingClient(answers={"claim_analysis_work": refused_credential},
                            registrations=[{"id": "r-1", "label": "ci", "enabled": True}])
    stale_worker = build_worker(stale, work_root=tmp_path / "work")

    with pytest.raises(CredentialError):
        stale_worker.forever()

    assert stale.count("claim_analysis_work") == 1
    assert stale.selects == []


def test_forever_absorbs_one_failure_while_the_registration_still_holds(tmp_path):
    # F2: stopping on authority loss must not make supervision brittle. A
    # single transient refusal is absorbed, but only after the worker has
    # confirmed it is still a designated worker for this project.
    def claim(payload, index):
        if index == 0:
            raise FactoryRuntimeError(
                "POST /rest/v1/rpc/claim_analysis_work failed with HTTP 503")
        return claim_row(source_url="https://gitlab.com/owner/repo")

    client = RecordingClient(answers={"claim_analysis_work": claim},
                             registrations=[{"id": "r-1", "label": "ci", "enabled": True}])
    worker = build_worker(client, work_root=tmp_path / "work")

    assert worker.forever(max_runs=1) == 1

    assert client.count("claim_analysis_work") == 2
    # The absorbed failure was weighed against the registration exactly once.
    assert len(client.selects) == 1


def test_forever_gives_up_after_five_consecutive_failures(tmp_path):
    # F2: an intact registration in front of a control plane that keeps
    # refusing is not retried indefinitely either.
    def failing_claim(payload, index):
        if index >= 6:
            raise LoopedTooLong("forever() never stopped after repeated failures")
        raise FactoryRuntimeError("POST /rest/v1/rpc/claim_analysis_work failed with HTTP 503")

    client = RecordingClient(answers={"claim_analysis_work": failing_claim},
                             registrations=[{"id": "r-1", "label": "ci", "enabled": True}])
    worker = build_worker(client, work_root=tmp_path / "work")

    try:
        worker.forever()
    except FactoryRuntimeError:
        # Giving up may surface the last refusal; stopping is what matters.
        pass

    assert client.count("claim_analysis_work") == 5
    assert len(client.selects) == 5


def test_continuous_mode_stops_after_a_single_requested_run(tmp_path, monkeypatch):
    # F7 (coverage): `forever` had no test at all, so the mode the operator
    # actually runs was unproven. The idle delay is recorded instead of slept.
    slept: list[float] = []
    monkeypatch.setattr(factory_runtime.time, "sleep", lambda seconds: slept.append(seconds))
    client = RecordingClient(answers={
        "claim_analysis_work": claim_row(source_url="https://gitlab.com/owner/repo"),
    }, registrations=[{"id": "r-1", "label": "ci", "enabled": True}])
    worker = build_worker(client, work_root=tmp_path / "work")

    assert worker.forever(max_runs=1) == 1

    assert client.count("claim_analysis_work") == 1
    assert slept == []


def test_continuous_mode_waits_on_an_idle_claim_and_still_completes_its_runs(
        tmp_path, monkeypatch):
    # F7 (coverage): an empty queue must wait for the configured poll and then
    # keep going, rather than counting the idle claim as a completed run.
    slept: list[float] = []
    monkeypatch.setattr(factory_runtime.time, "sleep", lambda seconds: slept.append(seconds))
    queued = claim_row(source_url="https://gitlab.com/owner/repo")
    client = RecordingClient(answers={"claim_analysis_work": [queued, None, queued]},
                             registrations=[{"id": "r-1", "label": "ci", "enabled": True}])
    worker = build_worker(client, work_root=tmp_path / "work")

    assert worker.forever(max_runs=2) == 2

    assert client.count("claim_analysis_work") == 3
    assert slept == [worker.poll_seconds]


# -- control-plane availability ------------------------------------------

def test_new_durable_error_codes_are_enumerated_short_codes():
    # F3 / DR-004: a dead control plane, a moved upstream and an unresolvable
    # commit each need their own code instead of arriving as either
    # source_fetch_failed or worker_error.
    expected = {
        ControlPlaneUnavailable: "control_plane_unavailable",
        SourceIdentityConflict: "source_identity_conflict",
        SourceCommitUnresolved: "source_commit_unresolved",
    }
    for exception_type, code in expected.items():
        assert issubclass(exception_type, FactoryRuntimeError)
        # An unreachable control plane is not a rejected credential, so the
        # continuous loop must not treat it as immediately terminal.
        assert not issubclass(exception_type, CredentialError)
        assert error_code(exception_type("unavailable")) == code
        assert ERROR_CODE_PATTERN.fullmatch(code)


@pytest.mark.parametrize("failure", [
    httpx.ConnectError("connection refused"),
    httpx.ReadTimeout("the control plane stopped responding"),
])
def test_an_rpc_transport_failure_is_a_control_plane_failure(tmp_path, failure):
    # F3: a bare httpx error here would be reported as source_fetch_failed,
    # blaming GitHub for the worker's own control plane.
    path = write_credentials(tmp_path / "secrets", access_token="still-valid-access",
                             expires_at=time.time() + 3600)

    def handle(request: httpx.Request) -> httpx.Response:
        raise failure

    with FactoryRuntimeClient(WorkerCredentials.load(path),
                              transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ControlPlaneUnavailable):
            client.rpc_row("claim_analysis_work", {"p_project_id": PROJECT_ID})


def test_an_auth_transport_failure_is_a_control_plane_failure(tmp_path):
    # F3: a refresh that never reaches Auth is neither a refused credential nor
    # a GitHub failure, and it must not consume the provisioned token.
    path = write_credentials(tmp_path / "secrets")

    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed")

    with FactoryRuntimeClient(WorkerCredentials.load(path),
                              transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ControlPlaneUnavailable):
            client.access_token()

    assert json.loads(path.read_text(encoding="utf-8"))["refresh_token"] == FIRST_REFRESH_TOKEN


def test_a_heartbeat_transport_blip_is_retried_inside_the_lease(
        tmp_path, fast_supervision, fast_control_plane_retry, spawned_children, monkeypatch):
    # F3: an unreachable heartbeat must not abandon the attempt and kill the
    # child, burning one of two attempts on a momentary blip while the lease
    # still has minutes of margin.
    archive = github_archive({"README.md": "# demo\n"})
    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo",
                        lambda url, ref=None: ("owner/repo", archive))
    blips: list[int] = []

    def heartbeat(payload, index):
        checkpoint = payload.get("p_checkpoint") or {}
        if (payload.get("p_phase") is None and checkpoint.get("step") == "analyzing"
                and not blips):
            blips.append(index)
            raise ControlPlaneUnavailable(
                "POST /rest/v1/rpc/heartbeat_analysis_run is unreachable")
        return live_lease_state()

    client = RecordingClient(answers={"heartbeat_analysis_run": heartbeat})
    worker = build_worker(client, script=SLOW_RESULT_CHILD, work_root=tmp_path / "work")

    worker._execute(claim_row(lease_expires_at=lease_expiry_in(300)))

    assert blips, "the in-analysis heartbeat never ran, so no blip was delivered"
    # The blip was retried, the child was left to finish and the run completed.
    assert client.count("finish_analysis_run") == 1
    assert client.count("fail_analysis_run") == 0
    assert spawned_children[0].returncode == 0


def test_exhausted_heartbeat_retries_are_a_control_plane_not_a_source_failure(
        tmp_path, fast_supervision, fast_control_plane_retry, spawned_children, monkeypatch):
    # F3: when the control plane really is gone the attempt is abandoned and
    # reported as control_plane_unavailable, not as source_fetch_failed, which
    # would send the operator to GitHub's status page.
    archive = github_archive({"README.md": "# demo\n"})
    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo",
                        lambda url, ref=None: ("owner/repo", archive))

    def heartbeat(payload, index):
        if payload.get("p_phase") is None:
            raise ControlPlaneUnavailable(
                "POST /rest/v1/rpc/heartbeat_analysis_run is unreachable")
        return live_lease_state()

    client = RecordingClient(answers={"heartbeat_analysis_run": heartbeat})
    worker = build_worker(client, script=SLEEPING_CHILD, work_root=tmp_path / "work")

    worker._execute(claim_row(lease_expires_at=lease_expiry_in(300)))

    assert client.payloads("fail_analysis_run")[0]["p_error_code"] == "control_plane_unavailable"
    assert client.count("finish_analysis_run") == 0
    # The child is not left burning CPU on a result nobody can accept.
    assert wait_until_exited(spawned_children[0]) is not None
    # The retry is bounded: the first attempt plus at most three more.
    attempts = [beat for beat in client.payloads("heartbeat_analysis_run")
                if beat["p_phase"] is None]
    assert 2 <= len(attempts) <= 4

    # The same worker still blames the source when the source is what is down.
    def unreachable(url: str, ref: str | None = None):
        raise httpx.ConnectError("name resolution failed")

    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo", unreachable)
    source = RecordingClient()
    build_worker(source, work_root=tmp_path / "source-work")._execute(claim_row())
    assert source.payloads("fail_analysis_run")[0]["p_error_code"] == "source_fetch_failed"


def test_heartbeat_retries_stop_once_the_lease_margin_is_gone(
        tmp_path, fast_supervision, fast_control_plane_retry, spawned_children, monkeypatch):
    # F3: retrying past the lease the control plane granted would hammer a dead
    # endpoint and still publish nothing, so an attempt with under two seconds
    # of margin is abandoned on the first failure.
    archive = github_archive({"README.md": "# demo\n"})
    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo",
                        lambda url, ref=None: ("owner/repo", archive))

    def heartbeat(payload, index):
        if payload.get("p_phase") is None:
            raise ControlPlaneUnavailable(
                "POST /rest/v1/rpc/heartbeat_analysis_run is unreachable")
        # The lease this run holds is about to expire and be reclaimed.
        return live_lease_state(lease_expires_at=lease_expiry_in(1))

    client = RecordingClient(answers={"heartbeat_analysis_run": heartbeat})
    worker = build_worker(client, script=SLEEPING_CHILD, work_root=tmp_path / "work")

    worker._execute(claim_row(lease_expires_at=lease_expiry_in(1)))

    attempts = [beat for beat in client.payloads("heartbeat_analysis_run")
                if beat["p_phase"] is None]
    assert len(attempts) == 1
    assert client.payloads("fail_analysis_run")[0]["p_error_code"] == "control_plane_unavailable"
    assert wait_until_exited(spawned_children[0]) is not None


# -- pinned source identity ----------------------------------------------

def test_a_retry_fetches_the_work_items_pinned_commit(tmp_path, fast_supervision, monkeypatch):
    # DR-004: today a retry calls the fetch seam with the URL alone, so it
    # re-resolves HEAD and can analyse a different commit than the attempt it
    # is retrying, while finish_analysis_run still accepts the digest.
    requested: list[object] = []
    archive = github_archive({"README.md": "# demo\n"})

    def fetch(url: str, ref: str | None = None) -> tuple[str, bytes]:
        requested.append(ref)
        return "owner/repo", archive

    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo", fetch)
    client = RecordingClient()
    worker = build_worker(client, script=RESULT_CHILD, work_root=tmp_path / "work")

    worker._execute(claim_row(attempt=2, pinned_source_ref="github.com/owner/repo",
                              pinned_source_commit=ARCHIVE_SHA,
                              previous_source_digest="sha256:" + "1" * 64))

    # The pin is what was requested: no default-branch fallback on a retry.
    assert requested == [ARCHIVE_SHA]
    assert client.count("finish_analysis_run") == 1
    identity = [beat for beat in client.payloads("heartbeat_analysis_run")
                if beat["p_source_digest"]]
    assert len(identity) == 1
    # The whole identity travels in one heartbeat, so finish_analysis_run can
    # require ref, commit and digest together.
    assert identity[0]["p_source_ref"] == "github.com/owner/repo"
    assert identity[0]["p_source_commit"] == ARCHIVE_SHA
    assert identity[0]["p_source_digest"].startswith("sha256:")
    # previous_source_digest stays, and still reports an upstream that moved.
    checkpoint = identity[0]["p_checkpoint"]
    assert checkpoint["resumed_attempt"] is True
    assert checkpoint["source_matches_previous_attempt"] is False


def test_an_archive_that_is_not_the_pinned_commit_is_refused(tmp_path, monkeypatch):
    # DR-004: a pin that can be silently ignored is worse than no pin, so an
    # archive resolving to another commit fails the attempt instead of being
    # analysed and accepted on its digest alone.
    archive = github_archive({"README.md": "# demo\n"})
    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo",
                        lambda url, ref=None: ("owner/repo", archive))
    client = RecordingClient()
    worker = build_worker(client, script=RESULT_CHILD, work_root=tmp_path / "work")

    worker._execute(claim_row(attempt=2, pinned_source_ref="github.com/owner/repo",
                              pinned_source_commit="f" * 40))

    assert client.count("finish_analysis_run") == 0
    assert client.payloads("fail_analysis_run")[0]["p_error_code"] == "source_identity_conflict"


def test_a_heartbeat_whose_source_identity_is_refused_is_a_source_conflict(
        tmp_path, monkeypatch):
    # DR-004: the control plane raises when another attempt pinned this work
    # item first. That is a source conflict, not an unknown worker failure, and
    # the distinction is what tells an operator the upstream moved.
    archive = github_archive({"README.md": "# demo\n"})
    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo",
                        lambda url, ref=None: ("owner/repo", archive))

    def heartbeat(payload, index):
        if payload.get("p_source_commit"):
            raise FactoryRuntimeError(
                "POST /rest/v1/rpc/heartbeat_analysis_run failed with HTTP 400: "
                '{"message":"source identity conflicts with the work item pin"}')
        return live_lease_state()

    client = RecordingClient(answers={"heartbeat_analysis_run": heartbeat})
    worker = build_worker(client, script=RESULT_CHILD, work_root=tmp_path / "work")

    worker._execute(claim_row())

    assert client.count("finish_analysis_run") == 0
    assert client.payloads("fail_analysis_run")[0]["p_error_code"] == "source_identity_conflict"


def test_a_first_attempt_without_a_resolvable_commit_is_refused(tmp_path, monkeypatch):
    # DR-004: the work item's pin is set from the first attempt's resolved
    # commit, so an archive that resolves to no commit cannot be allowed to
    # produce a result whose source identity can never be completed.
    archive = github_archive({"README.md": "# demo\n"}, root="repo")
    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo",
                        lambda url, ref=None: ("owner/repo", archive))
    client = RecordingClient()
    worker = build_worker(client, script=RESULT_CHILD, work_root=tmp_path / "work")

    worker._execute(claim_row())

    assert client.count("finish_analysis_run") == 0
    assert client.payloads("fail_analysis_run")[0]["p_error_code"] == "source_commit_unresolved"


# -- orphan containment --------------------------------------------------

def test_a_run_directory_is_marked_so_a_dead_attempt_can_be_identified(
        tmp_path, fast_supervision, monkeypatch):
    # F4: a leaked snapshot tree can only be reclaimed if the worker leaves a
    # marker naming the owning process and run before the child starts.
    archive = github_archive({"README.md": "# demo\n"})
    monkeypatch.setattr(factory_runtime, "fetch_public_github_repo",
                        lambda url, ref=None: ("owner/repo", archive))
    client = RecordingClient()
    worker = build_worker(client, script=MARKER_REPORTING_CHILD, work_root=tmp_path / "work")

    worker._execute(claim_row())

    assert client.count("finish_analysis_run") == 1
    summary = client.payloads("finish_analysis_run")[0]["p_result"]["summary"]
    marker = summary["marker"]
    assert marker["worker_pid"] == os.getpid()
    assert marker["run_id"] == RUN_ID
    assert marker["started_at"]
    # The marker is read by a sweep, so it carries no credential or fencing value.
    assert LEASE_TOKEN not in json.dumps(marker)
    # F4: the child leads its own process group, so the worker can signal the
    # whole analysis rather than a single PID.
    assert summary["pgid"] == summary["pid"]


def test_fencing_stops_the_whole_analysis_process_group(
        tmp_path, fast_supervision, fast_termination, spawned_children):
    # F4: today `_terminate` signals the direct child only, so an analysis that
    # forked leaves a descendant running after the attempt has been fenced.
    client = RecordingClient(answers={"heartbeat_analysis_run": [
        {"lease_valid": False, "reason": "cancelled", "run_status": "cancelled",
         "work_item_status": "cancelled", "cancel_requested": True, "phase": "analyzing"},
    ]})
    worker = build_worker(client, script=GRANDCHILD_SPAWNING_CHILD)
    directory, snapshot = prepared_run(tmp_path)

    assert worker._analyse_in_child(claim_row(), snapshot, directory) is None

    assert wait_until_exited(spawned_children[0]) is not None
    descendant = recorded_pid(directory / "grandchild.pid")
    try:
        assert wait_until_gone(descendant), (
            "F4: a descendant of the fenced analysis child kept running")
    finally:
        kill_if_alive(descendant)


def test_a_child_that_ignores_sigterm_is_escalated_to_sigkill(
        tmp_path, fast_supervision, fast_termination, spawned_children):
    # F7 (coverage): the SIGTERM, grace, SIGKILL escalation had no test, so a
    # child that refuses to stop could have been left running.
    client = RecordingClient(answers={"heartbeat_analysis_run": [
        {"lease_valid": False, "reason": "cancelled"},
    ]})
    worker = build_worker(client, script=SIGTERM_IGNORING_CHILD)
    directory, snapshot = prepared_run(tmp_path)

    assert worker._analyse_in_child(claim_row(), snapshot, directory) is None

    child = spawned_children[0]
    assert wait_until_exited(child) is not None
    # SIGTERM was ignored, so only the escalation could have ended it.
    assert child.returncode == -signal.SIGKILL


def test_analysis_child_exits_on_its_own_deadline_without_writing_a_result(tmp_path):
    # F4: a worker whose own process is killed cannot fence its child, so the
    # child carries its own bound. Today a third argument is a usage error.
    directory, snapshot = prepared_run(tmp_path)
    result_path = directory / "result.json"
    started = time.monotonic()
    child = subprocess.Popen(
        [sys.executable, "-c", SLOW_ANALYSIS_HARNESS, str(snapshot), str(result_path), "1"],
        cwd=str(directory), env=minimal_child_environment(directory),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        errors = child.communicate(timeout=20)[1].decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        raise AssertionError("F4: analysis_child ignored its max-seconds deadline") from None
    elapsed = time.monotonic() - started

    assert child.returncode != 0
    # Refusing the argument before analysing anything is not a deadline.
    assert "usage" not in errors
    assert elapsed >= 0.5
    assert not result_path.exists()


def test_analysis_child_accepts_a_disabled_deadline_argument(tmp_path):
    # F4: `max-seconds` is additive and 0 disables it, so the existing two
    # argument behaviour is unchanged. Today the third argument is refused.
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "main.py").write_text("value = 1\n", encoding="utf-8")
    result_path = tmp_path / "result.json"

    assert analysis_child_main([str(snapshot), str(result_path), "0"]) == 0

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["summary"]["source_files_analyzed"] == 1


def test_analysis_child_refuses_an_already_orphaned_start(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "main.py").write_text("value = 1\n", encoding="utf-8")
    result_path = tmp_path / "result.json"
    original_parent = os.getppid()
    monkeypatch.setattr(os, "getppid", lambda: original_parent + 1)

    assert analysis_child_main(
        [str(snapshot), str(result_path), "0", str(original_parent)]) == 3
    assert not result_path.exists()


def test_analysis_child_exits_when_the_worker_process_that_started_it_dies(tmp_path):
    # F4: when the worker process alone is killed hard, the child it started in
    # its own session has nothing left to fence it. The child must notice its
    # parent is gone and stop by itself; today it analyses on indefinitely.
    directory, snapshot = prepared_run(tmp_path)
    result_path = directory / "result.json"
    pid_path = directory / "analysis-child.pid"
    standin = subprocess.Popen(
        [sys.executable, "-c", WORKER_STANDIN, SLOW_ANALYSIS_HARNESS, str(snapshot),
         str(result_path), "0", str(pid_path)],
        cwd=str(directory), env=minimal_child_environment(directory),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    assert wait_until_exited(standin) is not None
    orphan = recorded_pid(pid_path)
    try:
        assert wait_until_gone(orphan, limit=8.0), (
            "F4: the analysis child kept running after its worker process died")
    finally:
        kill_if_alive(orphan)
    # An attempt whose worker is gone publishes nothing.
    assert not result_path.exists()


def test_the_sweep_reclaims_a_dead_attempts_run_directory(tmp_path):
    # F4: a worker whose process was killed hard leaves its snapshot tree
    # behind, and nothing reclaims it today.
    root = tmp_path / "work"
    dead = root / "oryveta-run-dead"
    run_marker(dead, pid=reaped_pid())
    outside = tmp_path / "elsewhere" / "oryveta-run-dead"
    run_marker(outside, pid=reaped_pid())

    reclaimed = sweep_stale_work_roots(root)

    assert not dead.exists()
    # The caller reports what was reclaimed, so the sweep has to say so.
    assert reclaimed == 1
    # Only entries directly under the given work root are considered.
    assert outside.is_dir()


def test_the_sweep_keeps_everything_it_cannot_positively_identify(tmp_path):
    # F4: removing a directory on age alone would delete a live attempt's
    # snapshot, so a tree goes only when its marker names a process that is
    # positively gone. PID reuse therefore errs toward keeping a directory.
    root = tmp_path / "work"
    live = root / "oryveta-run-live"
    run_marker(live, pid=os.getpid())
    unmarked = root / "oryveta-run-unmarked"
    (unmarked / "source").mkdir(parents=True)
    gone = reaped_pid()
    malformed = root / "oryveta-run-malformed"
    run_marker(malformed, pid=gone, body="{not json")
    incomplete = root / "oryveta-run-incomplete"
    run_marker(incomplete, pid=gone, body=json.dumps({"run_id": RUN_ID}))
    unrelated = root / "someone-elses-directory"
    run_marker(unrelated, pid=gone)
    target = tmp_path / "linked-run"
    run_marker(target, pid=gone)
    link = root / "oryveta-run-linked"
    link.symlink_to(target, target_is_directory=True)

    reclaimed = sweep_stale_work_roots(root)

    assert live.is_dir()
    assert unmarked.is_dir()
    assert malformed.is_dir()
    assert incomplete.is_dir()
    assert unrelated.is_dir()
    # A symlink is never removed and never followed.
    assert link.is_symlink()
    assert (target / RUN_MARKER_NAME).is_file()
    assert reclaimed == 0


def test_the_sweep_leaves_a_run_directory_this_user_does_not_own(tmp_path, monkeypatch):
    # F4: a work root shared with another account is not swept on this worker's
    # behalf, however dead the attempt that left it looks.
    root = tmp_path / "work"
    dead = root / "oryveta-run-dead"
    run_marker(dead, pid=reaped_pid())
    another_account = os.getuid() + 1
    monkeypatch.setattr(factory_runtime.os, "getuid", lambda: another_account)
    monkeypatch.setattr(factory_runtime.os, "geteuid", lambda: another_account)

    assert sweep_stale_work_roots(root) == 0
    assert dead.is_dir()


def test_worker_startup_sweeps_stale_run_directories(tmp_path, monkeypatch, capsys):
    # F4: the sweep reclaims nothing unless the worker runs it at startup,
    # before it claims its first work item.
    swept: list[tuple] = []
    monkeypatch.setattr(
        factory_runtime, "sweep_stale_work_roots",
        lambda *arguments, **keywords: swept.append((arguments, keywords)) or 0)
    credentials = write_credentials(tmp_path / "secrets")
    client = RecordingClient(registrations=[{"id": "r-1", "label": "ci", "enabled": True}])
    monkeypatch.setattr(factory_runtime, "FactoryRuntimeClient",
                        lambda provisioned: ClientContext(client))
    work_root = tmp_path / "work"

    assert factory_runtime.main([
        "--credentials", str(credentials), "--project", PROJECT_ID, "--once",
        "--work-root", str(work_root)]) == 0

    assert swept, "F4: worker startup did not sweep stale run directories"
    # The sweep is pointed at the work root this worker was configured with.
    assert str(work_root) in str(swept[0])
    assert "no queued work item" in capsys.readouterr().out
