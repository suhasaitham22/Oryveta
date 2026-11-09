"""Behavioral regressions for the durable repair worker's uncertain boundaries.

`oryveta_engine.coding_worker` is the only component that both holds a Supabase
worker session and starts code execution, so it is only trustworthy if four
things hold under failure: it refuses to serve anything but its own approved
policy, the child it starts carries no credential of any kind, a fenced or
timed-out attempt really stops that child and publishes nothing, and a result
is published only when the private evidence on disk supports it.

These tests drive those paths with real OS child processes and a recorded
control plane. No network, no GitHub access, no Supabase stack, no Docker
daemon and no model participate: the SQL-side authorization and fencing rules
are proved by the SQL tests, and a real local Docker/Ollama repair is proved by
the integration smoke the parent runs. Nothing here fabricates model output and
calls it a repair: the scripted children stand in for the *process*, and every
published result is still derived from, and validated against, the evidence
files a child really wrote.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from oryveta_engine import coding_worker, factory_runtime
from oryveta_engine.coding_config import parse_spec
from oryveta_engine.coding_contract import CodingError
from oryveta_engine.coding_worker import (
    CHECKPOINT_COUNTERS,
    FORWARDED_CHILD_CODES,
    GENERIC_CHILD_CODE,
    MAX_PATCH_BYTES,
    RESULT_KEYS,
    CapacityUnavailable,
    ChildRequest,
    ClaimMismatch,
    PolicyUnavailable,
    RepairChildFailure,
    RepairProcessError,
    RepairResultInvalid,
    RepairResultTooLarge,
    RepairRuntimeError,
    RepairRuntimeWorker,
    RepairTimeout,
    bounded_repair_result,
    error_code,
    forwarded_child_code,
    frozen_configuration,
    private_docker_config,
    receipt_checkpoint,
    repair_child_environment,
    resolve_docker_cli,
)
from oryveta_engine.factory_runtime import (
    ControlPlaneUnavailable,
    CredentialError,
    FactoryRuntimeError,
    SourceCommitUnresolved,
    SourceIdentityConflict,
)
from oryveta_engine.repositories import InvalidRepository

PROJECT_ID = "3f0a1b2c-4d5e-4f60-8a71-9b0c1d2e3f40"
POLICY_ID = "7c6d5e4f-3a2b-4c1d-8e0f-9a8b7c6d5e4f"
WORKER_USER = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
RUN_ID = "22222222-2222-4222-8222-222222222222"
WORK_ITEM_ID = "11111111-1111-4111-8111-111111111111"
LEASE_TOKEN = "lease-fencing-value-for-tests"
LOCAL_RUN_ID = "4f3e2d1c0b9a8f7e6d5c4b3a29180706"

SOURCE_URL = "https://github.com/pypa/sampleproject"
SOURCE_COMMIT = "621e4974ca25ce531773def586ba3ed8e736b3fc"
OTHER_COMMIT = "0123456789abcdef0123456789abcdef01234567"
GOAL = "Keep add_one's name but increment by two, per the synthetic fixture task."

MODEL_DIGEST = "a" * 64
IMAGE_ID = "sha256:" + "b" * 64
PATCH = ("--- a/src/sample/simple.py\n+++ b/src/sample/simple.py\n"
         "@@ -1,2 +1,2 @@\n-    return x + 1\n+    return x + 2\n")

# The metadata authority's accepted shape for `work_items.error_code` and
# `fail_repair_run(p_error_code)`.
ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,47}$")

# Every key the control plane is ever offered in a repair checkpoint.
CHECKPOINT_KEYS = {
    "step", "elapsed_seconds", "source_commit", "configuration_sha256",
    "source_pinned", "archive_bytes", "archive_entries", *CHECKPOINT_COUNTERS,
}
CHECKPOINT_STEPS = {"fetching_source", "snapshot_ready", "repairing", "verifying",
                    "recording_result"}
PHASES = {"claimed", "fetching_source", "repairing", "verifying", "recording_result",
          "done"}

# The children are launched through the `child_command` seam, so a test chooses
# exactly which process transition and which evidence it needs. The evidence a
# scripted child writes is the only thing a published result may come from.
EVIDENCE_CHILD = (
    "import json, os, sys, time\n"
    "result, evidence, plan = sys.argv[1], sys.argv[2], sys.argv[3]\n"
    "with open(plan, encoding='utf-8') as handle:\n"
    "    payload = json.load(handle)\n"
    "os.makedirs(evidence, mode=0o700)\n"
    "if payload.get('patch') is not None:\n"
    "    with open(os.path.join(evidence, 'verified.patch'), 'w', encoding='utf-8') as handle:\n"
    "        handle.write(payload['patch'])\n"
    "if payload.get('receipt') is not None:\n"
    "    with open(os.path.join(evidence, 'receipt.json'), 'w', encoding='utf-8') as handle:\n"
    "        json.dump(payload['receipt'], handle)\n"
    "time.sleep(payload.get('sleep', 0))\n"
    "if payload.get('report') is not None:\n"
    "    with open(result, 'w', encoding='utf-8') as handle:\n"
    "        json.dump(payload['report'], handle)\n"
    "raise SystemExit(payload.get('exit', 0))\n"
)
# Writes a receipt, then waits: the worker has to read that receipt for
# progress and keep heartbeating while the child is still working.
PROGRESSING_CHILD = (
    "import json, os, sys, time\n"
    "result, evidence, plan = sys.argv[1], sys.argv[2], sys.argv[3]\n"
    "with open(plan, encoding='utf-8') as handle:\n"
    "    payload = json.load(handle)\n"
    "os.makedirs(evidence, mode=0o700)\n"
    "with open(os.path.join(evidence, 'receipt.json'), 'w', encoding='utf-8') as handle:\n"
    "    json.dump(payload['receipt'], handle)\n"
    "time.sleep(120)\n"
)
SLEEPING_CHILD = "import time\ntime.sleep(120)\n"
ENVIRONMENT_CHILD = (
    "import json, os, sys\n"
    "with open(sys.argv[1], 'w', encoding='utf-8') as handle:\n"
    "    json.dump(dict(os.environ), handle)\n"
)
SIGTERM_IGNORING_CHILD = (
    "import json, signal, sys, time\n"
    "from pathlib import Path\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "Path(json.loads(Path(sys.argv[3]).read_text())['ready_path']).touch()\n"
    "time.sleep(120)\n"
)

CONFIGURATION: dict = {
    "schema_version": 1,
    "model": {"name": "qwen3:8b", "digest": MODEL_DIGEST},
    "runner": {"image": IMAGE_ID, "docker_context": "default", "timeout_seconds": 20},
    "limits": {"turns": 8, "tool_calls": 40, "total_tokens": 64000, "wall_seconds": 300},
    "read_paths": ["src/sample/simple.py"],
    "write_paths": ["src/sample/simple.py"],
    # The checks run inside the container with the snapshot root as the working
    # directory; their expected values stay with the host verifier.
    "development_checks": [{
        "name": "add-one-increments-by-two",
        "argv": ["python", "-c",
                 "import json,sys;sys.path.insert(0,'src');import sample.simple as s;"
                 "print(json.dumps({'add_one': s.add_one(1)}))"],
        "stdin": "", "expected_json": {"add_one": 3}, "kind": "regression",
    }],
    "acceptance_checks": [{
        "name": "add-one-rejects-text",
        "argv": ["python", "-c",
                 "import json,sys;sys.path.insert(0,'src');import sample.simple as s\n"
                 "try: s.add_one('x'); out={'error': None}\n"
                 "except TypeError: out={'error': 'TypeError'}\n"
                 "print(json.dumps(out))"],
        "stdin": "", "expected_json": {"error": "TypeError"}, "kind": "preserve",
    }],
}


# -- helpers --------------------------------------------------------------

def configuration_bytes(**overrides) -> bytes:
    payload = {**CONFIGURATION, **overrides}
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def frozen_spec(**overrides):
    return parse_spec({**CONFIGURATION, **overrides})


SPEC = frozen_spec()
CONFIGURATION_SHA256 = SPEC.digest


def default_rpc_rows() -> dict[str, object]:
    return {
        "claim_repair_work": None,
        "heartbeat_repair_run": {
            "lease_valid": True, "reason": None, "run_status": "running",
            "work_item_status": "running", "cancel_requested": False,
            "lease_expires_at": lease_expiry_in(300), "phase": "repairing",
        },
        "finish_repair_run": {
            "accepted": True, "reason": None, "work_item_status": "succeeded",
        },
        "fail_repair_run": {
            "accepted": True, "reason": None, "work_item_status": "failed",
            "retry_scheduled": False,
        },
    }


def lease_expiry_in(seconds: float) -> str:
    import datetime
    moment = (datetime.datetime.now(datetime.timezone.utc)
              + datetime.timedelta(seconds=seconds))
    return moment.isoformat()


def live_lease_state(**overrides) -> dict:
    state = dict(default_rpc_rows()["heartbeat_repair_run"])
    state.update(overrides)
    return state


def policy_row(**overrides) -> dict:
    row = {
        "id": POLICY_ID,
        "project_id": PROJECT_ID,
        "worker_user_id": WORKER_USER,
        "label": "design-partner-repair",
        "enabled": True,
        "source_url": SOURCE_URL,
        "source_owner": "pypa",
        "source_repo": "sampleproject",
        "source_commit": SOURCE_COMMIT,
        "configuration_sha256": CONFIGURATION_SHA256,
        "revoked_at": None,
    }
    row.update(overrides)
    return row


def claim_row(**overrides) -> dict:
    """A `claim_repair_work` row as the SQL function returns it."""
    row = {
        "work_item_id": WORK_ITEM_ID,
        "run_id": RUN_ID,
        "attempt": 1,
        "max_attempts": 2,
        "lease_token": LEASE_TOKEN,
        "lease_expires_at": lease_expiry_in(300),
        "kind": "repository_repair",
        "project_id": PROJECT_ID,
        "source_url": SOURCE_URL,
        "source_owner": "pypa",
        "source_repo": "sampleproject",
        "pinned_source_ref": "github.com/pypa/sampleproject",
        "pinned_source_commit": SOURCE_COMMIT,
        "previous_source_digest": None,
        "previous_checkpoint": None,
        "repair_policy_id": POLICY_ID,
        "goal": GOAL,
        "configuration_sha256": CONFIGURATION_SHA256,
    }
    row.update(overrides)
    return row


def receipt_row(**overrides) -> dict:
    """A private receipt as `coding_runtime.repair` leaves it after success."""
    receipt = {
        "schema_version": 1,
        "run_id": LOCAL_RUN_ID,
        "mode": "repair",
        "status": "needs_review",
        "phase": "finished",
        "verification": "passed",
        "configuration_sha256": CONFIGURATION_SHA256,
        "source_tree_sha256": "1" * 64,
        "candidate_tree_sha256": "2" * 64,
        "patch_sha256": hashlib.sha256(PATCH.encode("utf-8")).hexdigest(),
        "checks_passed": 2,
        "turns": 3,
        "tool_calls": 5,
        "tokens_observed": 12_000,
        "model": {"name": "qwen3:8b", "digest": MODEL_DIGEST},
        "model_observed": {"name": "qwen3:8b", "digest": MODEL_DIGEST,
                           "capabilities": ["tools"]},
    }
    receipt.update(overrides)
    return receipt


def child_plan(*, patch: str | None = PATCH, receipt: dict | None = None,
               report: dict | None = None, exit_code: int = 0,
               sleep: float = 0.0) -> dict:
    return {
        "patch": patch,
        "receipt": receipt_row() if receipt is None else receipt,
        "report": ({"status": "needs_review", "error_code": None,
                    "verification": "passed", "mode": "repair",
                    "run_id": LOCAL_RUN_ID} if report is None else report),
        "exit": exit_code,
        "sleep": sleep,
    }


def github_archive(commit: str = SOURCE_COMMIT, *, slug: str = "pypa-sampleproject",
                   files: dict[str, str] | None = None) -> bytes:
    """An in-memory GitHub-shaped zipball; nothing is fetched."""
    import io
    files = files or {"src/sample/simple.py": "def add_one(x):\n    return x + 1\n"}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, body in files.items():
            archive.writestr(f"{slug}-{commit[:7]}/{name}", body)
        archive.comment = commit.encode()
    return stream.getvalue()


class RecordingClient:
    """Records the worker's RPC calls and answers them from a script.

    A list answer is consumed positionally per RPC name and its last element
    repeats; that is how "the lease goes invalid part-way through the repair" is
    expressed without a database.
    """

    def __init__(self, *, answers: dict[str, object] | None = None,
                 registrations: list[dict] | None = None,
                 policies: list[dict] | None = None,
                 worker_user: str = WORKER_USER) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.selects: list[tuple[str, dict]] = []
        self._answers = dict(answers or {})
        self._defaults = default_rpc_rows()
        self._registrations = ([{"id": "r-1", "label": "repair-runner", "enabled": True}]
                               if registrations is None else list(registrations))
        self._policies = [policy_row()] if policies is None else list(policies)
        self._worker_user = worker_user

    def rpc_row(self, name: str, payload: dict) -> dict | None:
        index = self.count(name)
        self.calls.append((name, payload))
        answer = self._answers.get(name, self._defaults.get(name))
        if callable(answer):
            return answer(payload, index)
        if isinstance(answer, list):
            return answer[min(index, len(answer) - 1)]
        return answer

    def select(self, table: str, params: dict[str, str]) -> list[dict]:
        self.selects.append((table, dict(params)))
        if table == "project_repair_policies":
            return list(self._policies)
        return list(self._registrations)

    def worker_user_id(self) -> str:
        return self._worker_user

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def payloads(self, name: str) -> list[dict]:
        return [payload for called, payload in self.calls if called == name]

    def count(self, name: str) -> int:
        return len(self.payloads(name))


class StubbedCapacityWorker(RepairRuntimeWorker):
    """A worker whose local-capacity probe is recorded instead of performed.

    Docker and Ollama are real external dependencies; the integration smoke
    covers them. What these tests need is the *order*: capacity is observed
    before any work is claimed.
    """

    def verify_capacity(self, *, force: bool = False) -> dict:
        self.probe_order = [*getattr(self, "probe_order", []), "capacity"]
        return {"runner": {"daemon_os": "linux", "image_id": IMAGE_ID},
                "model": {"name": "qwen3:8b", "digest": MODEL_DIGEST}}

    def claim(self) -> dict | None:
        self.probe_order = [*getattr(self, "probe_order", []), "claim"]
        return super().claim()


class ScriptedChildWorker(StubbedCapacityWorker):
    """Supervises a real child process chosen by the test.

    `child_command` exists as an overridable seam precisely so supervision,
    cancellation, timeout and evidence handling can be exercised against a
    genuine OS process without local inference or a container.
    """

    script = EVIDENCE_CHILD
    plan: dict = {}

    def child_command(self, request: ChildRequest) -> list[str]:
        plan_path = request.result.parent / "plan.json"
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        return [sys.executable, "-c", self.script, str(request.result),
                str(request.evidence), str(plan_path)]


def build_worker(client: RecordingClient, tmp_path: Path, *,
                 script: str | None = None, plan: dict | None = None,
                 worker_type: type[RepairRuntimeWorker] | None = None,
                 **overrides) -> RepairRuntimeWorker:
    if worker_type is None:
        worker_type = StubbedCapacityWorker if script is None else ScriptedChildWorker
    evidence = tmp_path / "evidence"
    work = tmp_path / "work"
    evidence.mkdir(mode=0o700, exist_ok=True)
    work.mkdir(mode=0o700, exist_ok=True)
    arguments = {
        "client": client, "project_id": PROJECT_ID, "policy_id": POLICY_ID,
        "spec": SPEC, "configuration": configuration_bytes(),
        "source_url": SOURCE_URL, "source_commit": SOURCE_COMMIT,
        "evidence_root": evidence, "work_root": work,
        "docker_cli": sys.executable, "docker_config": None,
        "lease_seconds": 15, "poll_seconds": 0.01,
    }
    arguments.update(overrides)
    worker = worker_type(**arguments)
    if script is not None:
        worker.script = script
        worker.plan = plan if plan is not None else child_plan()
    return worker


def evidence_runs(worker: RepairRuntimeWorker) -> list[Path]:
    """The private evidence directories a run left behind."""
    return sorted(worker.evidence_root.glob("*/run-*"))


def wait_until_gone(pid: int, limit: float = 5.0) -> bool:
    deadline = time.monotonic() + limit
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


@pytest.fixture
def pinned_fetch(monkeypatch):
    """Answer the importer with a GitHub-shaped archive for the pinned commit."""
    calls: list[tuple[str, str | None]] = []

    def fetch(url: str, ref: str | None = None) -> tuple[str, bytes]:
        calls.append((url, ref))
        return "pypa/sampleproject", github_archive(ref or SOURCE_COMMIT)

    monkeypatch.setattr(coding_worker, "fetch_public_github_repo", fetch)
    return calls


@pytest.fixture
def fast_supervision(monkeypatch):
    """Shorten the heartbeat poll so supervised-process tests stay quick."""
    monkeypatch.setattr(coding_worker, "MAX_HEARTBEAT_INTERVAL", 0.05)


@pytest.fixture
def fast_termination(monkeypatch):
    monkeypatch.setattr(coding_worker, "TERMINATE_GRACE_SECONDS", 0.2)


@pytest.fixture
def spawned_children(monkeypatch):
    """Capture the real children the worker starts, to prove termination."""
    processes: list[subprocess.Popen] = []

    class Recorded(subprocess.Popen):
        def __init__(self, *arguments, **keywords):
            super().__init__(*arguments, **keywords)
            processes.append(self)

    monkeypatch.setattr(coding_worker.subprocess, "Popen", Recorded)
    return processes


# -- frozen operator inputs -----------------------------------------------

def test_configuration_is_frozen_from_the_bytes_that_were_parsed(tmp_path):
    path = tmp_path / "repair.json"
    path.write_bytes(configuration_bytes())

    payload, spec = frozen_configuration(path)

    # The bytes handed to every child must reproduce the frozen fingerprint,
    # or a child's receipt could never match the approved policy digest.
    assert payload == configuration_bytes()
    assert spec.digest == CONFIGURATION_SHA256
    assert parse_spec(json.loads(payload)).digest == spec.digest


def test_configuration_symlink_is_refused(tmp_path):
    real = tmp_path / "repair.json"
    real.write_bytes(configuration_bytes())
    link = tmp_path / "linked.json"
    link.symlink_to(real)

    with pytest.raises(CodingError) as failure:
        frozen_configuration(link)
    assert failure.value.code == "invalid_config"


def test_oversized_configuration_is_refused(tmp_path):
    path = tmp_path / "repair.json"
    path.write_bytes(b"{" + b" " * (128 * 1024 + 8) + b"}")

    with pytest.raises(CodingError) as failure:
        frozen_configuration(path)
    assert failure.value.code == "invalid_config"


def test_worker_refuses_a_source_commit_that_is_not_an_exact_sha(tmp_path):
    client = RecordingClient()
    with pytest.raises(ValueError, match="40 lowercase hex"):
        build_worker(client, tmp_path, source_commit="main")


def test_child_bound_comes_from_the_frozen_wall_budget(tmp_path):
    worker = build_worker(RecordingClient(), tmp_path)

    assert worker.max_run_seconds == (SPEC.limits.wall_seconds
                                      + coding_worker.REPAIR_SETUP_GRACE_SECONDS)
    # Nothing in the CLI can widen the operator's own budget.
    assert "--max-run-seconds" not in coding_worker.build_parser().format_help()


# -- Docker resolution ----------------------------------------------------

def test_docker_cli_is_resolved_to_an_absolute_trusted_executable(tmp_path):
    executable = tmp_path / "docker"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    link = tmp_path / "docker-link"
    link.symlink_to(executable)
    resolved = resolve_docker_cli(str(link))

    assert Path(resolved).is_absolute()
    assert Path(resolved) == executable.resolve()


def test_missing_docker_cli_is_refused_with_an_actionable_message(tmp_path, monkeypatch):
    monkeypatch.setattr(coding_worker.shutil, "which", lambda _: None)

    with pytest.raises(RepairRuntimeError, match="--docker-cli"):
        resolve_docker_cli(None)


def test_world_writable_docker_cli_is_refused(tmp_path):
    # A binary another account can replace decides how untrusted candidate code
    # is confined, so it is not trusted to be the Docker CLI.
    fake = tmp_path / "docker"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o777)

    with pytest.raises(RepairRuntimeError, match="writable by other accounts"):
        resolve_docker_cli(str(fake))


def test_only_docker_context_metadata_is_copied_for_the_child(tmp_path):
    operator = tmp_path / "docker"
    context = "colima-oryveta-factory"
    context_id = hashlib.sha256(context.encode()).hexdigest()
    metadata = operator / "contexts" / "meta" / context_id / "meta.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(json.dumps({"Name": context, "Metadata": {"secret": "not-needed"},
                                   "Endpoints": {"docker": {"Host": "unix:///tmp/docker.sock"}}}))
    unrelated = operator / "contexts" / "tls" / "another-context" / "key.pem"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("unrelated private key")
    # A real Docker config directory also holds registry credentials.
    (operator / "config.json").write_text('{"auths":{"registry":{"auth":"c2VjcmV0"}}}',
                                          encoding="utf-8")
    destination = tmp_path / "private"

    resolved = private_docker_config(operator, destination, "colima-oryveta-factory")

    assert Path(resolved) == destination
    copied_metadata = destination / metadata.relative_to(operator)
    assert json.loads(copied_metadata.read_text()) == {
        "Name": context, "Endpoints": {"docker": {"Host": "unix:///tmp/docker.sock", "SkipTLSVerify": False}}}
    assert not (destination / "config.json").exists()
    copied = [path.name for path in destination.rglob("*") if path.is_file()]
    assert copied == ["meta.json"]
    assert destination.stat().st_mode & 0o777 == 0o700


def test_named_docker_context_without_metadata_is_refused(tmp_path):
    with pytest.raises(RepairRuntimeError, match="docker-config"):
        private_docker_config(None, tmp_path / "private", "colima-oryveta-factory")


def test_default_docker_context_needs_no_operator_configuration(tmp_path):
    resolved = private_docker_config(None, tmp_path / "private", "default")

    assert Path(resolved).is_dir()


def test_docker_context_symlinks_are_refused(tmp_path):
    operator = tmp_path / "docker"
    context = "colima-oryveta-factory"
    metadata = operator / "contexts" / "meta" / hashlib.sha256(context.encode()).hexdigest()
    metadata.mkdir(parents=True)
    (metadata / "meta.json").symlink_to(tmp_path)

    with pytest.raises(RepairRuntimeError, match="symlink"):
        private_docker_config(operator, tmp_path / "private", context)


# -- the child's environment ----------------------------------------------

def test_child_environment_carries_no_credential_of_any_kind(tmp_path, monkeypatch):
    for leaked in ("ORYVETA_REPAIR_CREDENTIALS", "ORYVETA_WORKER_CREDENTIALS",
                   "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY",
                   "ORYVETA_WORKER_BOOTSTRAP", "AWS_SECRET_ACCESS_KEY",
                   "HTTPS_PROXY", "DOCKER_HOST"):
        monkeypatch.setenv(leaked, "must-not-be-inherited")

    environment = repair_child_environment(tmp_path, docker_cli="/usr/bin/docker",
                                           docker_config=str(tmp_path / "cfg"))

    assert set(environment) == {
        "PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING",
        "TMPDIR", "LC_ALL", "LANG", "HOME", "DOCKER_CONFIG",
    }
    assert "must-not-be-inherited" not in "".join(environment.values())
    # The child must not be able to redirect Docker at another daemon.
    assert "DOCKER_HOST" not in environment
    assert environment["HOME"] == str(tmp_path)
    assert environment["TMPDIR"] == str(tmp_path)
    assert environment["PATH"].split(os.pathsep)[0] == "/usr/bin"


def test_child_environment_omits_docker_config_when_there_is_none(tmp_path):
    environment = repair_child_environment(tmp_path, docker_cli="/usr/bin/docker",
                                           docker_config=None)

    assert "DOCKER_CONFIG" not in environment


def test_child_environment_points_python_at_the_engine_package(tmp_path):
    environment = repair_child_environment(tmp_path, docker_cli="/usr/bin/docker",
                                           docker_config=None)
    root = Path(environment["PYTHONPATH"])

    assert (root / "oryveta_engine" / "coding_child.py").is_file()


def test_a_real_child_process_sees_no_worker_secret(tmp_path, monkeypatch,
                                                    fast_supervision):
    """The strongest form of the claim: inspect a real child's own environ."""
    monkeypatch.setenv("ORYVETA_REPAIR_CREDENTIALS", "/operator/worker-credentials.json")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-must-not-leak")
    dump = tmp_path / "environment.json"
    client = RecordingClient(answers={"claim_repair_work": [claim_row(), None]})

    class EnvironmentWorker(ScriptedChildWorker):
        def child_command(self, request: ChildRequest) -> list[str]:
            return [sys.executable, "-c", ENVIRONMENT_CHILD, str(dump)]

    worker = build_worker(client, tmp_path, worker_type=EnvironmentWorker)
    monkeypatch.setattr(coding_worker, "fetch_public_github_repo",
                        lambda url, ref=None: ("pypa/sampleproject", github_archive()))
    worker.run_once()

    observed = json.loads(dump.read_text(encoding="utf-8"))
    assert "service-role-must-not-leak" not in json.dumps(observed)
    assert not any("CREDENTIAL" in key.upper() or "SUPABASE" in key.upper()
                   or "TOKEN" in key.upper() for key in observed)
    assert LEASE_TOKEN not in json.dumps(observed)
    assert POLICY_ID not in json.dumps(observed)


def test_the_child_argument_vector_carries_no_secret_or_goal_text(tmp_path):
    worker = build_worker(RecordingClient(), tmp_path)
    request = ChildRequest(
        configuration=tmp_path / "configuration.json", source_zip=tmp_path / "source.zip",
        goal_file=tmp_path / "goal.txt", evidence=tmp_path / "evidence",
        run_root=tmp_path / "runs", result=tmp_path / "child-result.json",
        max_seconds=480, parent_pid=os.getpid(), docker_cli=sys.executable)

    command = worker.child_command(request)

    joined = " ".join(command)
    assert GOAL not in joined
    assert LEASE_TOKEN not in joined
    assert POLICY_ID not in joined
    assert PROJECT_ID not in joined
    assert "oryveta_engine.coding_child" in joined


# -- policy authority -----------------------------------------------------

def test_an_approved_policy_is_accepted_and_scoped_to_this_worker(tmp_path):
    client = RecordingClient()
    worker = build_worker(client, tmp_path)

    assert worker.verify_policy()["label"] == "design-partner-repair"

    table, params = client.selects[-1]
    assert table == "project_repair_policies"
    assert params["id"] == f"eq.{POLICY_ID}"
    assert params["project_id"] == f"eq.{PROJECT_ID}"
    # A worker must never be able to read a lease token out of a read model.
    assert "lease_token" not in params["select"]


@pytest.mark.parametrize("policies, expected", [
    ([], "no readable repair policy"),
    ([policy_row(enabled=False)], "revoked or disabled"),
    ([policy_row(revoked_at="2026-11-05T00:00:00+00:00")], "revoked or disabled"),
    ([policy_row(worker_user_id="00000000-0000-4000-8000-000000000000")],
     "different worker identity"),
    ([policy_row(source_url="https://github.com/other/repo")], "source_url"),
    ([policy_row(source_commit=OTHER_COMMIT)], "source_commit"),
    ([policy_row(configuration_sha256="c" * 64)], "configuration_sha256"),
    ([policy_row(source_owner="attacker")], "frozen repository"),
])
def test_a_policy_that_is_not_the_approved_one_is_refused(tmp_path, policies, expected):
    client = RecordingClient(policies=policies)
    worker = build_worker(client, tmp_path)

    with pytest.raises(PolicyUnavailable, match=expected):
        worker.verify_policy()


def test_registration_loss_is_as_terminal_as_a_missing_policy(tmp_path):
    client = RecordingClient(registrations=[{"id": "r-1", "label": "x", "enabled": False}])
    worker = build_worker(client, tmp_path)

    with pytest.raises(FactoryRuntimeError, match="no enabled registration"):
        worker.verify_registration()


def test_lost_policy_stops_the_loop_instead_of_spinning(tmp_path):
    """A revoked policy must stop a polling worker, not be polled forever."""
    client = RecordingClient(policies=[policy_row(enabled=False)])
    worker = build_worker(client, tmp_path)

    with pytest.raises(PolicyUnavailable):
        worker.forever(max_runs=3)
    assert client.count("claim_repair_work") == 0


def test_capacity_is_observed_before_any_work_is_claimed(tmp_path):
    client = RecordingClient()
    worker = build_worker(client, tmp_path)

    assert worker.run_once() is False
    assert worker.probe_order[:2] == ["capacity", "claim"]


def test_missing_local_capacity_refuses_readiness_without_a_fallback(tmp_path,
                                                                    monkeypatch):
    client = RecordingClient()
    worker = build_worker(client, tmp_path, worker_type=RepairRuntimeWorker)

    class BrokenRunner:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def preflight(self) -> dict:
            raise CodingError("runner_image",
                              "The configured runner image is not present locally")

    monkeypatch.setattr(coding_worker, "DockerRunner", BrokenRunner)

    with pytest.raises(CapacityUnavailable) as failure:
        worker.verify_capacity()
    assert failure.value.code == "runner_image"
    # Nothing was claimed, and no substitute runner or hosted model was tried.
    assert client.calls == []


# -- claim matching -------------------------------------------------------

@pytest.mark.parametrize("overrides, expected", [
    ({"kind": "repository_analysis"}, "kind"),
    ({"project_id": "00000000-0000-4000-8000-000000000000"}, "project_id"),
    ({"repair_policy_id": "00000000-0000-4000-8000-000000000000"}, "repair_policy_id"),
    ({"configuration_sha256": "c" * 64}, "configuration_sha256"),
    ({"source_url": "https://github.com/other/repo"}, "source_url"),
    ({"pinned_source_commit": OTHER_COMMIT}, "pinned_source_commit"),
    ({"pinned_source_commit": None}, "pinned_source_commit"),
    ({"goal": "   "}, "bounded repair goal"),
    ({"goal": "x" * 5000}, "bounded repair goal"),
    ({"goal": None}, "bounded repair goal"),
])
def test_a_claim_that_is_not_this_policys_work_is_refused(tmp_path, overrides, expected):
    client = RecordingClient(answers={"claim_repair_work": claim_row(**overrides)})
    worker = build_worker(client, tmp_path)

    assert worker.run_once() is True

    assert client.count("heartbeat_repair_run") == 0
    assert client.count("finish_repair_run") == 0
    assert client.payloads("fail_repair_run")[0]["p_error_code"] == "policy_mismatch"


def test_a_mismatched_claim_never_reaches_the_network_or_a_child(tmp_path, monkeypatch):
    def forbidden(*_: object, **__: object):
        raise AssertionError("a refused claim must not fetch any source")

    monkeypatch.setattr(coding_worker, "fetch_public_github_repo", forbidden)
    client = RecordingClient(answers={
        "claim_repair_work": claim_row(kind="repository_analysis")})
    worker = build_worker(client, tmp_path, script=SLEEPING_CHILD)

    worker.run_once()

    assert client.payloads("fail_repair_run")[0]["p_error_code"] == "policy_mismatch"


def test_the_claim_presents_the_policy_and_its_frozen_digest(tmp_path):
    client = RecordingClient()
    worker = build_worker(client, tmp_path)

    worker.run_once()

    assert client.payloads("claim_repair_work")[0] == {
        "p_policy_id": POLICY_ID,
        "p_configuration_sha256": CONFIGURATION_SHA256,
        "p_lease_seconds": 15,
    }


# -- source identity ------------------------------------------------------

def test_only_the_approved_pinned_commit_is_ever_fetched(tmp_path, pinned_fetch,
                                                         fast_supervision):
    client = RecordingClient(answers={"claim_repair_work": [claim_row(), None]})
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD)

    worker.run_once()

    assert pinned_fetch == [(SOURCE_URL, SOURCE_COMMIT)]
    identity = client.payloads("heartbeat_repair_run")[1]
    assert identity["p_source_commit"] == SOURCE_COMMIT
    assert identity["p_source_ref"] == "github.com/pypa/sampleproject"
    assert identity["p_source_digest"].startswith("sha256:")


@pytest.mark.parametrize("archive, expected_code", [
    (github_archive(OTHER_COMMIT), "source_identity_conflict"),
    (github_archive(SOURCE_COMMIT, slug="attacker-sampleproject"), "invalid_repository"),
])
def test_a_fetched_archive_that_is_not_the_approved_source_is_refused(
        tmp_path, monkeypatch, archive, expected_code):
    def fetch(url: str, ref: str | None = None) -> tuple[str, bytes]:
        slug = "pypa/sampleproject" if expected_code == "source_identity_conflict" \
            else "attacker/sampleproject"
        return slug, archive

    monkeypatch.setattr(coding_worker, "fetch_public_github_repo", fetch)
    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=SLEEPING_CHILD)

    worker.run_once()

    assert client.count("finish_repair_run") == 0
    assert client.payloads("fail_repair_run")[0]["p_error_code"] == expected_code


def test_an_archive_without_a_commit_identity_is_refused(tmp_path, monkeypatch):
    import io
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("sampleproject/src/sample/simple.py", "x = 1\n")
    monkeypatch.setattr(coding_worker, "fetch_public_github_repo",
                        lambda url, ref=None: ("pypa/sampleproject", stream.getvalue()))
    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=SLEEPING_CHILD)

    worker.run_once()

    assert client.payloads("fail_repair_run")[0]["p_error_code"] == "source_commit_unresolved"


def test_a_pinned_reference_that_moved_is_refused(tmp_path, pinned_fetch):
    client = RecordingClient(answers={
        "claim_repair_work": claim_row(pinned_source_ref="github.com/other/repo")})
    worker = build_worker(client, tmp_path, script=SLEEPING_CHILD)

    worker.run_once()

    assert client.payloads("fail_repair_run")[0]["p_error_code"] == "source_identity_conflict"


# -- progress -------------------------------------------------------------

def test_only_bounded_numbers_hashes_and_one_step_are_ever_reported():
    receipt = {
        "phase": "model_call", "turns": 4, "tool_calls": 9, "tokens_observed": 2048,
        "unsettled_token_reservation": 512,
        # None of this may ever reach the control plane.
        "goal_sha256": "deadbeef", "model_summary": "I edited the file",
        "implementation": {"files": {"coding_runtime.py": "abc"}},
        "active_tool": "replace_once", "candidate_patch_sha256": "f" * 64,
        "checkpointed_at": "2026-11-05T00:00:00+00:00",
    }

    checkpoint = receipt_checkpoint(receipt, step="repairing", elapsed_seconds=12.7,
                                   source_commit=SOURCE_COMMIT,
                                   configuration_sha256=CONFIGURATION_SHA256)

    assert set(checkpoint) <= CHECKPOINT_KEYS
    assert checkpoint == {
        "step": "repairing", "elapsed_seconds": 12, "source_commit": SOURCE_COMMIT,
        "configuration_sha256": CONFIGURATION_SHA256, "source_pinned": True,
        "turns": 4, "tool_calls": 9, "tokens_observed": 2048,
        "unsettled_token_reservation": 512,
    }


@pytest.mark.parametrize("value", ["12", -1, 1.5, True, None, 10 ** 12])
def test_an_implausible_counter_is_left_out_rather_than_forwarded(value):
    checkpoint = receipt_checkpoint({"turns": value}, step="repairing",
                                    elapsed_seconds=0, source_commit=SOURCE_COMMIT,
                                    configuration_sha256=CONFIGURATION_SHA256)

    assert "turns" not in checkpoint


def test_a_missing_or_unreadable_receipt_still_reports_the_step(tmp_path):
    assert coding_worker.read_receipt(tmp_path / "absent.json") is None
    partial = tmp_path / "receipt.json"
    partial.write_text('{"phase": "model_ca', encoding="utf-8")
    assert coding_worker.read_receipt(partial) is None

    checkpoint = receipt_checkpoint(None, step="repairing", elapsed_seconds=3,
                                    source_commit=SOURCE_COMMIT,
                                    configuration_sha256=CONFIGURATION_SHA256)
    assert checkpoint["step"] == "repairing"
    assert set(checkpoint).isdisjoint(CHECKPOINT_COUNTERS)


def test_the_worker_reports_the_childs_own_recorded_progress(tmp_path, pinned_fetch,
                                                             fast_supervision,
                                                             fast_termination,
                                                             spawned_children):
    """A running repair's progress comes from the receipt the child really wrote."""
    states = [live_lease_state()] * 4 + [live_lease_state(lease_valid=False,
                                                          reason="cancel_requested")]
    client = RecordingClient(answers={
        "claim_repair_work": claim_row(),
        "heartbeat_repair_run": states,
    })
    plan = {"receipt": receipt_row(phase="verification", turns=2, tool_calls=7,
                                   tokens_observed=3333,
                                   unsettled_token_reservation=0)}
    worker = build_worker(client, tmp_path, script=PROGRESSING_CHILD, plan=plan)

    worker.run_once()

    checkpoints = [payload["p_checkpoint"]
                   for payload in client.payloads("heartbeat_repair_run")]
    phases = [payload["p_phase"] for payload in client.payloads("heartbeat_repair_run")]
    assert all(set(checkpoint) <= CHECKPOINT_KEYS for checkpoint in checkpoints)
    assert all(checkpoint["step"] in CHECKPOINT_STEPS for checkpoint in checkpoints)
    assert all(phase in PHASES for phase in phases if phase is not None)
    # The child recorded "verification", so the honest phase is `verifying`.
    progressed = [checkpoint for checkpoint in checkpoints
                  if checkpoint["step"] == "verifying"]
    assert progressed, checkpoints
    assert progressed[-1]["turns"] == 2
    assert progressed[-1]["tool_calls"] == 7
    assert progressed[-1]["tokens_observed"] == 3333
    assert "verifying" in phases
    assert client.count("finish_repair_run") == 0


def test_the_snapshot_checkpoint_reports_the_archive_it_really_fetched(
        tmp_path, pinned_fetch, fast_supervision):
    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD)

    worker.run_once()

    snapshot = [payload["p_checkpoint"]
                for payload in client.payloads("heartbeat_repair_run")
                if payload["p_checkpoint"]["step"] == "snapshot_ready"]
    assert len(snapshot) == 1
    assert snapshot[0]["archive_bytes"] == len(github_archive())
    assert snapshot[0]["archive_entries"] == 1
    assert snapshot[0]["source_pinned"] is True


# -- supervision and fencing ----------------------------------------------

def test_a_lost_lease_stops_the_real_child_and_publishes_nothing(
        tmp_path, pinned_fetch, fast_supervision, fast_termination, spawned_children):
    client = RecordingClient(answers={
        "claim_repair_work": claim_row(),
        "heartbeat_repair_run": [live_lease_state(), live_lease_state(),
                                 live_lease_state(lease_valid=False,
                                                  reason="worker_revoked")],
    })
    worker = build_worker(client, tmp_path, script=SLEEPING_CHILD)

    worker.run_once()

    assert spawned_children, "no real child process was started"
    child = spawned_children[-1]
    assert wait_until_gone(child.pid), "the repair child survived its fencing"
    assert child.poll() is not None
    assert client.count("finish_repair_run") == 0
    assert client.count("fail_repair_run") == 0  # The fence already settled it.


def test_a_child_that_ignores_sigterm_is_still_stopped(
        tmp_path, pinned_fetch, fast_supervision, fast_termination, spawned_children):
    ready = tmp_path / "sigterm-handler-ready"
    client = RecordingClient(answers={
        "claim_repair_work": claim_row(),
        "heartbeat_repair_run": lambda *_: (
            live_lease_state(lease_valid=False, reason="cancel_requested")
            if ready.exists() else live_lease_state()),
    })
    worker = build_worker(client, tmp_path, script=SIGTERM_IGNORING_CHILD,
                          plan={"ready_path": str(ready)})

    worker.run_once()

    assert ready.exists(), "the child never installed its SIGTERM handler"
    child = spawned_children[-1]
    assert wait_until_gone(child.pid)
    assert child.returncode == -signal.SIGKILL
    assert client.count("finish_repair_run") == 0


def test_a_repair_that_outlives_its_bound_is_stopped_and_reported(
        tmp_path, pinned_fetch, fast_supervision, fast_termination, spawned_children):
    class ShortBoundWorker(ScriptedChildWorker):
        """The bound comes from the frozen budget, so only a subclass shortens it.

        No CLI flag and no claim field can widen or narrow what the operator's
        own configuration allows, which is why this is overridden here rather
        than configured.
        """

        @property
        def max_run_seconds(self) -> int:
            return 1

    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=SLEEPING_CHILD,
                          worker_type=ShortBoundWorker)

    worker.run_once()

    child = spawned_children[-1]
    assert wait_until_gone(child.pid)
    assert client.payloads("fail_repair_run")[0]["p_error_code"] == "repair_timeout"
    assert client.count("finish_repair_run") == 0


def test_a_child_that_refuses_is_reported_with_its_own_bounded_code(
        tmp_path, pinned_fetch, fast_supervision):
    plan = child_plan(patch=None, receipt=receipt_row(status="rejected",
                                                      verification="not_accepted"),
                      report={"status": "rejected", "error_code": "verification_failed",
                              "verification": "not_accepted", "mode": "repair",
                              "run_id": LOCAL_RUN_ID},
                      exit_code=1)
    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD, plan=plan)

    worker.run_once()

    assert client.count("finish_repair_run") == 0
    assert client.payloads("fail_repair_run")[0]["p_error_code"] == "verification_failed"


def test_an_unknown_child_code_is_collapsed_rather_than_forwarded(
        tmp_path, pinned_fetch, fast_supervision):
    plan = child_plan(patch=None, receipt=receipt_row(status="failed"),
                      report={"status": "failed", "error_code": "brand_new_code",
                              "verification": "not_accepted", "mode": "repair",
                              "run_id": LOCAL_RUN_ID},
                      exit_code=1)
    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD, plan=plan)

    worker.run_once()

    assert client.payloads("fail_repair_run")[0]["p_error_code"] == GENERIC_CHILD_CODE


def test_a_child_that_writes_no_outcome_is_a_process_failure(
        tmp_path, pinned_fetch, fast_supervision):
    plan = child_plan(patch=None, receipt=None, report=None, exit_code=0)
    plan["report"] = None
    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD, plan=plan)

    worker.run_once()

    assert client.payloads("fail_repair_run")[0]["p_error_code"] == GENERIC_CHILD_CODE
    assert client.count("finish_repair_run") == 0


def test_the_evidence_of_a_fenced_attempt_is_still_preserved(
        tmp_path, pinned_fetch, fast_supervision, fast_termination):
    client = RecordingClient(answers={
        "claim_repair_work": claim_row(),
        "heartbeat_repair_run": [live_lease_state(), live_lease_state(),
                                 live_lease_state(lease_valid=False, reason="cancelled")],
    })
    worker = build_worker(client, tmp_path, script=PROGRESSING_CHILD,
                          plan={"receipt": receipt_row(phase="model_call")})

    worker.run_once()

    runs = evidence_runs(worker)
    assert len(runs) == 1
    assert (runs[0] / "receipt.json").is_file()
    # The disposable snapshot tree is gone; the private evidence is not.
    assert not list(worker.work_root.glob(f"{factory_runtime.RUN_DIRECTORY_PREFIX}*"))


# -- publishing a result --------------------------------------------------

def test_a_verified_candidate_is_published_from_the_private_evidence(
        tmp_path, pinned_fetch, fast_supervision):
    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD)

    worker.run_once()

    result = client.payloads("finish_repair_run")[0]["p_result"]
    assert set(result) == set(RESULT_KEYS)
    assert result["kind"] == "repository_repair"
    assert result["status"] == "needs_review"
    assert result["verification"] == "passed"
    assert result["patch"] == PATCH
    assert result["patch_sha256"] == hashlib.sha256(PATCH.encode("utf-8")).hexdigest()
    assert result["source_commit"] == SOURCE_COMMIT
    assert result["configuration_sha256"] == CONFIGURATION_SHA256
    assert result["model_digest"] == MODEL_DIGEST
    assert result["checks_passed"] == 2
    # Nothing private, local or path-shaped may ride along.
    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized
    assert LEASE_TOKEN not in serialized
    assert len(serialized.encode("utf-8")) <= coding_worker.MAX_REPAIR_RESULT_BYTES


def test_the_result_is_recorded_only_while_the_lease_is_still_valid(
        tmp_path, pinned_fetch, fast_supervision):
    def heartbeat(payload: dict, index: int) -> dict:
        if payload["p_phase"] == "recording_result":
            return live_lease_state(lease_valid=False, reason="lease_expired")
        return live_lease_state()

    client = RecordingClient(answers={"claim_repair_work": claim_row(),
                                      "heartbeat_repair_run": heartbeat})
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD)

    worker.run_once()

    # A verified candidate in hand is still not a licence to publish.
    assert client.count("finish_repair_run") == 0


def test_a_refused_result_is_reported_without_pretending_to_succeed(
        tmp_path, pinned_fetch, fast_supervision):
    client = RecordingClient(answers={
        "claim_repair_work": claim_row(),
        "finish_repair_run": {"accepted": False, "reason": "stale_lease",
                              "work_item_status": "running"},
    })
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD)

    worker.run_once()

    assert client.count("finish_repair_run") == 1


def test_evidence_records_the_attempt_it_belongs_to(tmp_path, pinned_fetch,
                                                    fast_supervision):
    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD)

    worker.run_once()

    index = json.loads((evidence_runs(worker)[0] / "worker-run.json")
                       .read_text(encoding="utf-8"))
    assert index["work_item_id"] == WORK_ITEM_ID
    assert index["source_commit"] == SOURCE_COMMIT
    assert index["local_run_id"] == LOCAL_RUN_ID
    assert LEASE_TOKEN not in json.dumps(index)


# -- result validation ----------------------------------------------------

def test_a_receipt_backed_patch_becomes_exactly_the_contract_keys():
    result = bounded_repair_result(
        receipt_row(), PATCH.encode("utf-8"), run_id=LOCAL_RUN_ID,
        configuration_sha256=CONFIGURATION_SHA256, source_commit=SOURCE_COMMIT,
        model_digest=MODEL_DIGEST)

    assert tuple(sorted(result)) == tuple(sorted(RESULT_KEYS))


def test_a_patch_the_receipt_does_not_vouch_for_is_refused():
    # The worker recomputes the hash instead of trusting the recorded one.
    with pytest.raises(RepairResultInvalid, match="does not match the hash"):
        bounded_repair_result(
            receipt_row(), b"--- a/x\n+++ b/x\n@@ -1 +1 @@\n-1\n+2\n",
            run_id=LOCAL_RUN_ID, configuration_sha256=CONFIGURATION_SHA256,
            source_commit=SOURCE_COMMIT, model_digest=MODEL_DIGEST)


def test_an_overlarge_patch_is_refused_and_never_truncated():
    patch = "+" + "x" * MAX_PATCH_BYTES
    receipt = receipt_row(patch_sha256=hashlib.sha256(patch.encode()).hexdigest())

    with pytest.raises(RepairResultTooLarge, match="not truncated"):
        bounded_repair_result(receipt, patch.encode("utf-8"), run_id=LOCAL_RUN_ID,
                              configuration_sha256=CONFIGURATION_SHA256,
                              source_commit=SOURCE_COMMIT, model_digest=MODEL_DIGEST)


def test_a_receipt_from_another_run_is_never_published():
    """Reclaim safety: a leftover evidence tree is not this attempt's result."""
    stale = receipt_row(run_id="0" * 32)

    with pytest.raises(RepairResultInvalid, match="different run"):
        bounded_repair_result(stale, PATCH.encode("utf-8"), run_id=LOCAL_RUN_ID,
                              configuration_sha256=CONFIGURATION_SHA256,
                              source_commit=SOURCE_COMMIT, model_digest=MODEL_DIGEST)


@pytest.mark.parametrize("overrides, expected", [
    ({"status": "failed"}, "no verified candidate"),
    ({"verification": "not_accepted"}, "no verified candidate"),
    ({"mode": "verification"}, "not a repair run"),
    ({"configuration_sha256": "c" * 64}, "different configuration"),
    ({"source_tree_sha256": "nope"}, "source_tree_sha256"),
    ({"candidate_tree_sha256": None}, "candidate_tree_sha256"),
    ({"checks_passed": 0}, "checks_passed"),
    ({"checks_passed": 49}, "checks_passed"),
    ({"turns": 0}, "turns"),
    ({"turns": 51}, "turns"),
    ({"tool_calls": 101}, "tool_calls"),
    ({"tokens_observed": 500_001}, "tokens_observed"),
    ({"tool_calls": True}, "tool_calls"),
    ({"model_observed": None}, "no verified local model"),
    ({"model_observed": {"name": "qwen3:8b", "digest": "f" * 64}},
     "not the one the configuration pins"),
    ({"model_observed": {"name": "../../etc/passwd", "digest": MODEL_DIGEST}},
     "not an accepted identifier"),
])
def test_evidence_that_does_not_support_a_result_is_refused(overrides, expected):
    with pytest.raises(RepairResultInvalid, match=expected):
        bounded_repair_result(receipt_row(**overrides), PATCH.encode("utf-8"),
                              run_id=LOCAL_RUN_ID,
                              configuration_sha256=CONFIGURATION_SHA256,
                              source_commit=SOURCE_COMMIT, model_digest=MODEL_DIGEST)


@pytest.mark.parametrize("patch, expected", [
    (b"", "empty"),
    (b"\xff\xfe not utf-8", "not UTF-8"),
])
def test_a_patch_that_is_not_publishable_text_is_refused(patch, expected):
    receipt = receipt_row(patch_sha256=hashlib.sha256(patch).hexdigest())

    with pytest.raises(RepairResultInvalid, match=expected):
        bounded_repair_result(receipt, patch, run_id=LOCAL_RUN_ID,
                              configuration_sha256=CONFIGURATION_SHA256,
                              source_commit=SOURCE_COMMIT, model_digest=MODEL_DIGEST)


def test_a_run_whose_evidence_is_for_another_configuration_is_reported(
        tmp_path, pinned_fetch, fast_supervision):
    plan = child_plan(receipt=receipt_row(configuration_sha256="c" * 64))
    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD, plan=plan)

    worker.run_once()

    assert client.count("finish_repair_run") == 0
    assert client.payloads("fail_repair_run")[0]["p_error_code"] == "repair_output_invalid"


def test_an_overlarge_result_is_reported_rather_than_trimmed(
        tmp_path, pinned_fetch, fast_supervision):
    patch = "+" + "x" * MAX_PATCH_BYTES
    plan = child_plan(patch=patch,
                      receipt=receipt_row(
                          patch_sha256=hashlib.sha256(patch.encode()).hexdigest()))
    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD, plan=plan)

    worker.run_once()

    assert client.count("finish_repair_run") == 0
    assert (client.payloads("fail_repair_run")[0]["p_error_code"]
            == "repair_result_too_large")


def test_a_run_whose_child_wrote_no_patch_is_not_a_success(
        tmp_path, pinned_fetch, fast_supervision):
    plan = child_plan(patch=None)
    client = RecordingClient(answers={"claim_repair_work": claim_row()})
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD, plan=plan)

    worker.run_once()

    assert client.count("finish_repair_run") == 0
    assert client.payloads("fail_repair_run")[0]["p_error_code"] == "repair_output_invalid"


# -- continuous operation -------------------------------------------------

def test_the_worker_serves_more_than_one_task_in_sequence(tmp_path, pinned_fetch,
                                                          fast_supervision):
    client = RecordingClient(answers={
        "claim_repair_work": [claim_row(), claim_row(run_id="33333333-3333-4333-"
                                                            "8333-333333333333")],
    })
    worker = build_worker(client, tmp_path, script=EVIDENCE_CHILD)

    assert worker.forever(max_runs=2) == 2

    assert client.count("finish_repair_run") == 2
    assert len(evidence_runs(worker)) == 2


def test_an_empty_queue_is_polled_without_claiming_work(tmp_path):
    client = RecordingClient()
    worker = build_worker(client, tmp_path)

    assert worker.run_once() is False
    assert client.count("heartbeat_repair_run") == 0


def test_a_refused_credential_stops_the_loop_at_once(tmp_path):
    def claim(payload: dict, index: int) -> dict:
        raise CredentialError("worker session refresh was refused (HTTP 400)")

    client = RecordingClient(answers={"claim_repair_work": claim})
    worker = build_worker(client, tmp_path)

    with pytest.raises(CredentialError):
        worker.forever(max_runs=5)
    assert client.count("claim_repair_work") == 1


def test_a_control_plane_that_keeps_refusing_stops_the_worker(tmp_path):
    def claim(payload: dict, index: int) -> dict:
        raise ControlPlaneUnavailable("the control plane could not be reached")

    client = RecordingClient(answers={"claim_repair_work": claim})
    worker = build_worker(client, tmp_path)

    with pytest.raises(ControlPlaneUnavailable):
        worker.forever(max_runs=50)
    assert client.count("claim_repair_work") == coding_worker.MAX_CONSECUTIVE_CLAIM_FAILURES


def test_a_failure_report_that_cannot_be_recorded_leaves_the_lease_to_expire(
        tmp_path, monkeypatch, pinned_fetch):
    def fail(payload: dict, index: int) -> dict:
        raise ControlPlaneUnavailable("the control plane could not be reached")

    client = RecordingClient(answers={
        "claim_repair_work": claim_row(kind="repository_analysis"),
        "fail_repair_run": fail,
    })
    worker = build_worker(client, tmp_path)

    # The attempt is abandoned, not retried forever, and nothing is published.
    worker.run_once()
    assert client.count("finish_repair_run") == 0


# -- error codes ----------------------------------------------------------

@pytest.mark.parametrize("exception, expected", [
    (ClaimMismatch("x"), "policy_mismatch"),
    (PolicyUnavailable("x"), "policy_mismatch"),
    (RepairTimeout("x"), "repair_timeout"),
    (RepairProcessError("x"), "repair_process_failed"),
    (RepairResultInvalid("x"), "repair_output_invalid"),
    (RepairResultTooLarge("x"), "repair_result_too_large"),
    (RepairChildFailure("verification_failed", "x"), "verification_failed"),
    (CapacityUnavailable("runner_daemon", "x"), "runner_daemon"),
    (CodingError("model_unavailable", "x"), "model_unavailable"),
    (CodingError("some_new_code", "x"), GENERIC_CHILD_CODE),
    (InvalidRepository("x"), "invalid_repository"),
    (SourceIdentityConflict("x"), "source_identity_conflict"),
    (SourceCommitUnresolved("x"), "source_commit_unresolved"),
    (CredentialError("x"), "worker_credentials_rejected"),
    (ControlPlaneUnavailable("x"), "control_plane_unavailable"),
    (OSError("x"), "worker_storage_error"),
    (ValueError("x"), "repair_output_invalid"),
    (RuntimeError("x"), "worker_error"),
])
def test_every_failure_maps_to_one_accepted_short_code(exception, expected):
    code = error_code(exception)

    assert code == expected
    assert ERROR_CODE_PATTERN.fullmatch(code)
    # A code is an enumerated identifier, never a message that could carry a
    # path, a goal or a credential.
    assert str(exception) not in code


def test_a_policy_level_source_conflict_is_classified_as_a_source_conflict(tmp_path):
    """The control plane's third refusal means the same thing to a worker."""
    def heartbeat(payload: dict, index: int) -> dict:
        raise FactoryRuntimeError(
            "POST /rest/v1/rpc/heartbeat_repair_run failed with HTTP 400: "
            "source identity conflicts with the repair policy")

    client = RecordingClient(answers={"heartbeat_repair_run": heartbeat})
    worker = build_worker(client, tmp_path)

    with pytest.raises(SourceIdentityConflict):
        worker.heartbeat(claim_row())
    # The client only preserves protocol messages it knows, so the refusal has
    # to be in the shared allowlist to be classifiable at all.
    assert ("source identity conflicts with the repair policy"
            in factory_runtime.SOURCE_CONFLICT_REFUSALS)


def test_an_authority_refusal_of_a_failure_report_stops_the_worker(tmp_path,
                                                                   pinned_fetch):
    client = RecordingClient(answers={
        "claim_repair_work": claim_row(kind="repository_analysis"),
        "fail_repair_run": {"accepted": False, "reason": "policy_revoked",
                            "work_item_status": "cancelled"},
    })
    worker = build_worker(client, tmp_path)

    with pytest.raises(PolicyUnavailable, match="policy_revoked"):
        worker.forever(max_runs=3)
    assert client.count("claim_repair_work") == 1


def test_a_fencing_refusal_of_a_failure_report_is_not_terminal(tmp_path, pinned_fetch):
    client = RecordingClient(answers={
        "claim_repair_work": [claim_row(kind="repository_analysis"), None],
        "fail_repair_run": {"accepted": False, "reason": "lease_lost",
                            "work_item_status": "queued"},
    })
    worker = build_worker(client, tmp_path)

    # The attempt was already settled by a fence; the worker keeps serving.
    assert worker.run_once() is True


def test_a_candidate_identical_to_the_source_is_not_a_repair():
    receipt = receipt_row(candidate_tree_sha256="1" * 64)

    with pytest.raises(RepairResultInvalid, match="identical to the source"):
        bounded_repair_result(receipt, PATCH.encode("utf-8"), run_id=LOCAL_RUN_ID,
                              configuration_sha256=CONFIGURATION_SHA256,
                              source_commit=SOURCE_COMMIT, model_digest=MODEL_DIGEST)


def test_the_forwarded_code_set_is_closed_and_well_shaped():
    for code in FORWARDED_CHILD_CODES:
        assert ERROR_CODE_PATTERN.fullmatch(code), code
    assert forwarded_child_code("verification_failed") == "verification_failed"
    assert forwarded_child_code("anything_else") == GENERIC_CHILD_CODE
    assert forwarded_child_code(None) == GENERIC_CHILD_CODE
    assert ERROR_CODE_PATTERN.fullmatch(GENERIC_CHILD_CODE)


# -- the analysis service is untouched ------------------------------------

def test_the_analysis_worker_still_claims_only_analysis_work(tmp_path):
    """A repair worker existing must not change what the analysis service does."""
    analysis = factory_runtime.AnalysisRuntimeWorker(
        client=RecordingClient(), project_id=PROJECT_ID, lease_seconds=15)

    analysis.claim()

    assert analysis.client.names() == ["claim_analysis_work"]
    assert analysis.client.payloads("claim_analysis_work")[0] == {
        "p_project_id": PROJECT_ID, "p_lease_seconds": 15,
    }


def test_the_analysis_cli_gained_no_repair_or_execution_option():
    help_text = factory_runtime.build_parser().format_help()

    for flag in ("--policy", "--config", "--source-url", "--source-commit",
                 "--evidence-root", "--docker-cli", "--docker-config"):
        assert flag not in help_text
    assert factory_runtime.CREDENTIALS_ENV != coding_worker.CREDENTIALS_ENV


def test_repair_is_opt_in_at_the_command_line():
    parser = coding_worker.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--credentials", "/tmp/c.json"])
    arguments = parser.parse_args([
        "--credentials", "/tmp/c.json", "--policy", POLICY_ID,
        "--config", "/tmp/repair.json", "--source-url", SOURCE_URL,
        "--source-commit", SOURCE_COMMIT, "--evidence-root", "/tmp/evidence",
    ])
    # Continuous polling is the default; the finite modes are explicit.
    assert arguments.once is False
    assert arguments.max_runs is None
    assert arguments.lease_seconds == factory_runtime.DEFAULT_LEASE_SECONDS
    finite = parser.parse_args([
        "--credentials", "/tmp/c.json", "--policy", POLICY_ID,
        "--config", "/tmp/repair.json", "--source-url", SOURCE_URL,
        "--source-commit", SOURCE_COMMIT, "--evidence-root", "/tmp/evidence",
        "--once", "--max-runs", "2", "--work-root", "/tmp/work",
        "--docker-cli", "/usr/bin/docker", "--docker-config", "/operator/.docker",
        "--poll-seconds", "0.5",
    ])
    assert (finite.once, finite.max_runs, finite.poll_seconds) == (True, 2, 0.5)
