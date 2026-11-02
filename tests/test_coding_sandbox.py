"""Isolation, limit and cleanup behaviour of the container check runner.

The deterministic tests drive a real Docker CLI *replacement* process: a small
program that keeps container state on disk and records every invocation, so the
runner is exercised through actual subprocesses, pipes, timeouts and exit codes
rather than through an in-process mock. The real Docker tests are opt in and
only run when the operator exports a context and a local image ID.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from oryveta_engine.coding_contract import CheckSpec, CodingError, RunnerSpec, strict_json
from oryveta_engine.coding_sandbox import (
    CONTAINER_PREFIX,
    DockerRunner,
    INPUT_DIR,
    WORK_DIR,
    control_environment,
)

IMAGE_ID = "sha256:" + "ab" * 32
CONTEXT = "test-context"

FAKE_DOCKER = '''
import json
import os
import sys
import time
from pathlib import Path

STATE = Path("__STATE__")


def plan():
    path = STATE / "scenario.json"
    return json.loads(path.read_text()) if path.exists() else {}


def record(entry):
    with (STATE / "calls.jsonl").open("a") as handle:
        handle.write(json.dumps(entry) + "\\n")


def load():
    path = STATE / "containers.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save(store):
    (STATE / "containers.json").write_text(json.dumps(store))


def emit(value):
    sys.stdout.write(json.dumps(value))
    sys.stdout.flush()


def main():
    args = sys.argv[1:]
    record({"argv": args, "env": dict(os.environ)})
    if args[:1] in (["--context"], ["--host"]):
        args = args[2:]
    scenario = plan()
    if args[:2] == ["context", "inspect"]:
        host = scenario.get("endpoint", "unix:///var/run/docker.sock")
        emit([{"Name": scenario.get("context_name", args[2]),
               "Endpoints": {"docker": {"Host": host, "SkipTLSVerify": False}}}])
        return 0
    if args[:1] == ["version"]:
        emit(scenario.get("server", {"Os": "linux", "Arch": "arm64", "Version": "27.3.1"}))
        return 0
    if args[:2] == ["image", "inspect"]:
        if scenario.get("image_missing"):
            sys.stderr.write("Error response from daemon: No such image\\n")
            return 1
        image = dict(scenario.get("image", {}))
        image.setdefault("Id", args[2])
        image.setdefault("Os", "linux")
        image.setdefault("Architecture", "arm64")
        image.setdefault("RepoDigests", ["registry.example/img@sha256:" + "0" * 64])
        image.setdefault("Config", {})
        emit([image])
        return 0
    if args[:2] == ["container", "create"]:
        if scenario.get("create_sleep"):
            time.sleep(float(scenario["create_sleep"]))
        if scenario.get("create_fails"):
            sys.stderr.write("Error response from daemon: invalid configuration\\n")
            return 125
        name = args[args.index("--name") + 1]
        store = load()
        store[name] = {"Status": "created", "Running": False, "Dead": False,
                       "OOMKilled": False, "ExitCode": 0, "Error": ""}
        save(store)
        sys.stdout.write("f" * 64 + "\\n")
        return 0
    if args[:2] == ["container", "start"]:
        name = args[-1]
        store = load()
        if name not in store:
            sys.stderr.write("Error response from daemon: No such container\\n")
            return 1
        (STATE / ("pid-" + name)).write_text(str(os.getpid()))
        store[name].update({"Status": "running", "Running": True})
        save(store)
        (STATE / ("stdin-" + name)).write_bytes(sys.stdin.buffer.read())
        chunk = scenario.get("stdout", "").encode()
        for _ in range(int(scenario.get("stdout_repeat", 1))):
            sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        sys.stderr.buffer.write(scenario.get("stderr", "").encode())
        sys.stderr.buffer.flush()
        if scenario.get("run_sleep"):
            time.sleep(float(scenario["run_sleep"]))
        code = int(scenario.get("exit_code", 0))
        store = load()
        if scenario.get("linger"):
            store[name].update({"Status": "running", "Running": True, "ExitCode": 0})
        else:
            store[name].update({"Status": "exited", "Running": False, "ExitCode": code,
                                "OOMKilled": bool(scenario.get("oom")),
                                "Error": scenario.get("state_error", "")})
        save(store)
        return int(scenario.get("cli_exit_code", code))
    if args[:2] == ["container", "ls"]:
        if (STATE / "daemon-down").exists():
            sys.stderr.write("Cannot connect to the Docker daemon\\n")
            return 1
        name = args[args.index("--filter") + 1].removeprefix("name=")
        if name in load():
            sys.stdout.write("f" * 64 + "\\n")
        return 0
    if args[:2] == ["container", "inspect"]:
        name = args[2]
        if (STATE / "daemon-down").exists():
            sys.stderr.write("Cannot connect to the Docker daemon\\n")
            return 1
        store = load()
        if name not in store:
            sys.stderr.write("Error: No such object\\n")
            return 1
        if "State" in args[-1]:
            emit(store[name])
        else:
            sys.stdout.write("f" * 64 + "\\n")
        return 0
    if args[:2] == ["container", "rm"]:
        name = args[-1]
        if scenario.get("daemon_lost_during_cleanup"):
            (STATE / "daemon-down").write_text("unreachable")
            return 1
        if scenario.get("rm_fails"):
            sys.stderr.write("Error response from daemon: removal is in progress\\n")
            return 1
        if scenario.get("rm_leaks"):
            return 0
        store = load()
        if name not in store:
            sys.stderr.write("Error: No such container\\n")
            return 1
        del store[name]
        save(store)
        sys.stdout.write(name + "\\n")
        return 0
    sys.stderr.write("unsupported command\\n")
    return 64


sys.exit(main())
'''


class DockerStub:
    """A deterministic stand-in for the Docker CLI with on-disk container state."""

    def __init__(self, binary: Path, state: Path):
        self.binary = binary
        self.state = state

    def plan(self, **scenario) -> None:
        (self.state / "scenario.json").write_text(json.dumps(scenario))

    def calls(self) -> list[dict]:
        path = self.state / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line]

    def commands(self) -> list[list[str]]:
        return [call["argv"] for call in self.calls()]

    def actions(self) -> list[tuple[str, ...]]:
        """Each recorded command with its resolved connection flag removed."""
        actions = []
        for argv in self.commands():
            actions.append(tuple(argv[2:] if argv[:1] in (["--context"], ["--host"]) else argv))
        return actions

    def command_with(self, *needles: str) -> list[str]:
        for argv in self.commands():
            if all(needle in argv for needle in needles):
                return argv
        raise AssertionError(f"No recorded docker command contains {needles}")

    def containers(self) -> dict:
        path = self.state / "containers.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def stdin_of(self, name: str) -> bytes:
        return (self.state / f"stdin-{name}").read_bytes()

    def pid_of(self, name: str) -> int:
        return int((self.state / f"pid-{name}").read_text())


@pytest.fixture
def stub(tmp_path):
    state = tmp_path / "docker-state"
    state.mkdir()
    binary = tmp_path / "fake-docker"
    binary.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER.replace("__STATE__", str(state)))
    binary.chmod(0o755)
    return DockerStub(binary, state)


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path.resolve() / "snapshot"
    path.mkdir()
    (path / "solver.py").write_text("print('hello')\n")
    return path


def spec(**overrides) -> RunnerSpec:
    values = {"image": IMAGE_ID, "docker_context": CONTEXT, "timeout_seconds": 7}
    values.update(overrides)
    return RunnerSpec(**values)


def runner(stub: DockerStub, **overrides) -> DockerRunner:
    return DockerRunner(spec(**overrides), docker_cli=str(stub.binary))


def check(argv=("/bin/sh", "-c", "echo hi"), stdin="", **overrides) -> CheckSpec:
    values = {"name": "unit", "argv": argv, "stdin": stdin, "expected_json": {"ok": True}}
    values.update(overrides)
    return CheckSpec(**values)




def run(coro):
    return asyncio.run(coro)


# --- configuration the operator owns ----------------------------------------


@pytest.mark.parametrize("image", [
    "python:3.12", "sha256:" + "AB" * 32, "sha256:" + "ab" * 20, "ab" * 32,
    "registry.example/img@sha256:" + "ab" * 32, "",
])
def test_runner_requires_an_immutable_local_image_id(stub, image):
    with pytest.raises(CodingError, match="image ID") as raised:
        DockerRunner(spec(image=image), docker_cli=str(stub.binary))
    assert raised.value.code == "runner_spec"


@pytest.mark.parametrize("overrides", [
    {"docker_context": "bad context"}, {"timeout_seconds": 0}, {"memory_mb": 16},
    {"cpus": 0}, {"pids": 2}, {"tmpfs_mb": 0}, {"output_bytes": 16},
    {"timeout_seconds": 10_000},
])
def test_runner_rejects_unenforceable_bounds(stub, overrides):
    with pytest.raises(CodingError) as raised:
        DockerRunner(spec(**overrides), docker_cli=str(stub.binary))
    assert raised.value.code == "runner_spec"


def test_runner_rejects_scratch_larger_than_the_memory_bound(stub):
    with pytest.raises(CodingError, match="scratch"):
        DockerRunner(spec(memory_mb=64, tmpfs_mb=64), docker_cli=str(stub.binary))
    DockerRunner(spec(memory_mb=256, tmpfs_mb=64), docker_cli=str(stub.binary))


# --- preflight identity ------------------------------------------------------


def test_preflight_reports_the_observed_endpoint_daemon_and_image(stub):
    stub.plan()
    observed = run(runner(stub).preflight())
    assert observed == {"context": CONTEXT, "endpoint": "unix:///var/run/docker.sock",
                        "daemon_os": "linux", "daemon_arch": "arm64",
                        "daemon_version": "27.3.1", "image_id": IMAGE_ID, "image_os": "linux",
                        "image_arch": "arm64",
                        "image_digests": ["registry.example/img@sha256:" + "0" * 64]}
    assert stub.containers() == {}
    assert not any("create" in argv for argv in stub.commands())


def test_preflight_passes_the_context_explicitly_and_hides_the_host_environment(
        stub, monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://untrusted.example:2375")
    monkeypatch.setenv("DOCKER_CONTEXT", "other")
    monkeypatch.setenv("ORYVETA_TEST_SECRET_MARKER", "top-secret-value")
    stub.plan()
    run(runner(stub).preflight())
    for call in stub.calls():
        assert not {"DOCKER_HOST", "DOCKER_CONTEXT", "ORYVETA_TEST_SECRET_MARKER"} & set(call["env"])
        assert "top-secret-value" not in json.dumps(call["env"])


@pytest.mark.parametrize("endpoint", [
    "tcp://127.0.0.1:2375", "ssh://builder@remote.example", "npipe:////./pipe/docker_engine",
    "unix://relative.sock",
])
def test_preflight_requires_a_local_unix_endpoint(stub, endpoint):
    stub.plan(endpoint=endpoint)
    with pytest.raises(CodingError) as raised:
        run(runner(stub).preflight())
    assert raised.value.code == "runner_context"


def test_preflight_requires_the_context_to_identify_itself(stub):
    stub.plan(context_name="a-different-context")
    with pytest.raises(CodingError) as raised:
        run(runner(stub).preflight())
    assert raised.value.code == "runner_context"


def test_preflight_requires_a_linux_daemon(stub):
    stub.plan(server={"Os": "windows", "Arch": "amd64", "Version": "27.3.1"})
    with pytest.raises(CodingError, match="Linux") as raised:
        run(runner(stub).preflight())
    assert raised.value.code == "runner_daemon"


def test_preflight_requires_the_local_image_to_match_the_spec(stub):
    stub.plan(image={"Id": "sha256:" + "cd" * 32})
    with pytest.raises(CodingError) as raised:
        run(runner(stub).preflight())
    assert raised.value.code == "runner_image"


def test_preflight_requires_a_linux_image(stub):
    stub.plan(image={"Os": "windows"})
    with pytest.raises(CodingError) as raised:
        run(runner(stub).preflight())
    assert raised.value.code == "runner_image"


def test_image_declared_volumes_cannot_bypass_the_scratch_limit(stub):
    stub.plan(image={"Config": {"Volumes": {"/data": {}}}})
    with pytest.raises(CodingError) as raised:
        run(runner(stub).preflight())
    assert raised.value.code == "runner_image"
    assert not stub.containers()


def test_missing_image_is_an_error_and_never_a_pull(stub):
    stub.plan(image_missing=True)
    with pytest.raises(CodingError) as raised:
        run(runner(stub).preflight())
    assert raised.value.code == "runner_image"
    assert all("pull" not in argv for argv in stub.commands())



# --- results come from the recorded container state --------------------------


def test_run_reports_the_actual_exit_code_and_streams(stub, workspace):
    stub.plan(stdout='{"failures": 2}', stderr="warning: slow\n", exit_code=5, cli_exit_code=0)
    result = run(runner(stub).run(workspace, check()))
    assert result.exit_code == 5
    assert strict_json(result.stdout) == {"failures": 2}
    assert result.stderr == b"warning: slow\n"
    assert stub.containers() == {}




def test_an_out_of_memory_run_is_not_a_result(stub, workspace):
    stub.plan(stdout='{"ok": true}', exit_code=137, oom=True)
    with pytest.raises(CodingError) as raised:
        run(runner(stub).run(workspace, check()))
    assert raised.value.code == "runner_oom"
    assert stub.containers() == {}


def test_a_daemon_failure_is_not_a_result(stub, workspace):
    stub.plan(state_error="runtime exec format error", exit_code=0)
    with pytest.raises(CodingError) as raised:
        run(runner(stub).run(workspace, check()))
    assert raised.value.code == "runner_start"
    assert stub.containers() == {}


def test_a_container_that_never_exited_is_not_a_result(stub, workspace):
    stub.plan(stdout='{"ok": true}', linger=True)
    with pytest.raises(CodingError) as raised:
        run(runner(stub).run(workspace, check()))
    assert raised.value.code == "runner_start"
    assert stub.containers() == {}


@pytest.mark.parametrize("exit_code, code", [
    (123, "runner_setup"), (125, "runner_setup"), (124, "runner_timeout"),
    (137, "runner_timeout"),
])
def test_matching_output_followed_by_a_sandbox_stop_is_never_accepted(
        stub, workspace, exit_code, code):
    stub.plan(stdout='{"ok": true}', exit_code=exit_code)
    with pytest.raises(CodingError) as raised:
        run(runner(stub).run(workspace, check()))
    assert raised.value.code == code
    assert stub.containers() == {}


def test_a_failed_creation_leaves_nothing_behind(stub, workspace):
    stub.plan(create_fails=True)
    with pytest.raises(CodingError) as raised:
        run(runner(stub).run(workspace, check()))
    assert raised.value.code == "runner_create"
    assert not any(action[:2] == ("container", "start") for action in stub.actions())


# --- limits, cancellation and cleanup ----------------------------------------


def test_a_creation_timeout_cannot_launch_code(stub, workspace):
    stub.plan(create_sleep=30)
    started = time.monotonic()
    with pytest.raises(CodingError) as raised:
        run(runner(stub).run(workspace, check(), timeout_seconds=0.2))
    assert raised.value.code == "runner_create"
    assert time.monotonic() - started < 20
    assert not any(action[:2] == ("container", "start") for action in stub.actions())
    assert stub.containers() == {}
    assert any(action[:2] == ("container", "rm") for action in stub.actions())


def test_host_supervision_stops_a_run_that_outlives_its_budget(stub, workspace):
    stub.plan(stdout='{"ok": true}', run_sleep=120)
    instance = runner(stub)
    started = time.monotonic()
    with pytest.raises(CodingError) as raised:
        run(instance.run(workspace, check(), timeout_seconds=0.2))
    elapsed = time.monotonic() - started
    assert raised.value.code == "runner_timeout"
    assert elapsed < 30
    assert stub.containers() == {}
    name = [action[-1] for action in stub.actions() if action[:2] == ("container", "rm")][0]
    pid = stub.pid_of(name)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_unbounded_output_stops_the_run_and_removes_the_container(stub, workspace, monkeypatch):
    start = asyncio.create_subprocess_exec
    processes = []

    async def record_process(*args, **kwargs):
        process = await start(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", record_process)
    stub.plan(stdout="x" * 4096, stdout_repeat=512, run_sleep=120)
    with pytest.raises(CodingError) as raised:
        run(runner(stub, output_bytes=8192).run(workspace, check()))
    assert raised.value.code == "runner_output_limit"
    assert stub.containers() == {}
    name = [action[-1] for action in stub.actions() if action[:2] == ("container", "rm")][0]
    with pytest.raises(ProcessLookupError):
        os.kill(stub.pid_of(name), 0)
    assert all(process.stdout.at_eof() and process.stderr.at_eof() for process in processes)


def test_cancellation_removes_the_container_and_reaps_the_cli(stub, workspace):
    stub.plan(stdout="{}", run_sleep=120)
    instance = runner(stub)

    async def scenario():
        task = asyncio.ensure_future(instance.run(workspace, check()))
        for _ in range(200):
            await asyncio.sleep(0.05)
            if any(action[:2] == ("container", "start") for action in stub.actions()):
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())
    assert stub.containers() == {}
    name = [action[-1] for action in stub.actions() if action[:2] == ("container", "rm")][0]
    with pytest.raises(ProcessLookupError):
        os.kill(stub.pid_of(name), 0)


def test_daemon_loss_cannot_be_mistaken_for_confirmed_removal(stub, workspace):
    stub.plan(stdout="{}", daemon_lost_during_cleanup=True)
    instance = runner(stub)
    with pytest.raises(CodingError) as raised:
        run(instance.run(workspace, check()))
    assert raised.value.code == "runner_cleanup"
    with pytest.raises(CodingError) as blocked:
        run(instance.preflight())
    assert blocked.value.code == "runner_unusable"


def test_an_unconfirmed_cleanup_is_explicit_and_stops_further_use(stub, workspace):
    stub.plan(stdout="{}", rm_leaks=True)
    instance = runner(stub)
    with pytest.raises(CodingError) as raised:
        run(instance.run(workspace, check()))
    assert raised.value.code == "runner_cleanup"
    assert len([action for action in stub.actions() if action[:2] == ("container", "rm")]) == 2
    for attempt in (instance.run(workspace, check()), instance.preflight()):
        with pytest.raises(CodingError) as blocked:
            run(attempt)
        assert blocked.value.code == "runner_unusable"


def test_a_failing_removal_command_also_stops_the_runner(stub, workspace):
    stub.plan(stdout="{}", rm_fails=True)
    instance = runner(stub)
    with pytest.raises(CodingError) as raised:
        run(instance.run(workspace, check()))
    assert raised.value.code == "runner_cleanup"
    with pytest.raises(CodingError) as blocked:
        run(instance.preflight())
    assert blocked.value.code == "runner_unusable"


def test_a_missing_docker_cli_is_reported_without_a_host_fallback(tmp_path, workspace):
    instance = DockerRunner(spec(), docker_cli=str(tmp_path / "absent-docker"))
    with pytest.raises(CodingError) as raised:
        run(instance.run(workspace, check()))
    assert raised.value.code == "runner_cli"


# --- workspace and check admission -------------------------------------------


def test_workspace_must_be_an_existing_resolved_directory(stub, tmp_path, workspace):
    root = tmp_path.resolve()
    (root / "file.txt").write_text("not a directory")
    (root / "link").symlink_to(workspace, target_is_directory=True)
    (root / "alias").symlink_to(root / "real", target_is_directory=True)
    (root / "real").mkdir()
    (root / "real" / "snap").mkdir()
    (root / "comma,path").mkdir()
    (root / "line\nbreak").mkdir()
    unsafe = [
        Path("snapshot"), root / "missing", root / "file.txt", root / "link",
        root / "alias" / "snap", root / "comma,path", root / "line\nbreak", Path("/"),
        Path(f"{root}/real/../real"),
    ]
    instance = runner(stub)
    for candidate in unsafe:
        with pytest.raises(CodingError) as raised:
            run(instance.run(candidate, check()))
        assert raised.value.code == "runner_workspace", candidate
    assert stub.calls() == []


@pytest.mark.parametrize("argv", [(), ("",), ("ok", "with\x00null"), ("x",) * 65, (1,)])
def test_check_argv_must_be_bounded_text(stub, workspace, argv):
    with pytest.raises(CodingError) as raised:
        run(runner(stub).run(workspace, check(argv=argv)))
    assert raised.value.code == "runner_check"


@pytest.mark.parametrize("expected", [123, 124, 125, 137, -1, 256])
def test_reserved_and_invalid_expected_exit_codes_are_refused(stub, workspace, expected):
    with pytest.raises(CodingError) as raised:
        run(runner(stub).run(workspace, check(expected_exit_code=expected)))
    assert raised.value.code == "runner_check"


def test_oversized_check_stdin_is_refused(stub, workspace):
    with pytest.raises(CodingError) as raised:
        run(runner(stub).run(workspace, check(stdin="a" * (1_048_576 + 1))))
    assert raised.value.code == "runner_check"


@pytest.mark.parametrize("timeout", [0, -1, 7200, "10", float("nan")])
def test_invalid_timeouts_are_refused(stub, workspace, timeout):
    with pytest.raises(CodingError) as raised:
        run(runner(stub).run(workspace, check(), timeout_seconds=timeout))
    assert raised.value.code == "runner_spec"


# --- optional real Docker coverage -------------------------------------------

REAL_CONTEXT = os.environ.get("ORYVETA_TEST_DOCKER_CONTEXT", "")
REAL_IMAGE = os.environ.get("ORYVETA_TEST_DOCKER_IMAGE", "")
REAL_ROOT = os.environ.get("ORYVETA_TEST_RUN_ROOT", "")

real_docker = pytest.mark.skipif(
    not (REAL_CONTEXT and REAL_IMAGE),
    reason=("Set ORYVETA_TEST_DOCKER_CONTEXT and ORYVETA_TEST_DOCKER_IMAGE (a local "
            "sha256 image ID with sh, cp and GNU timeout) to run real Docker tests"),
)


def real_spec(**overrides) -> RunnerSpec:
    values = {"image": REAL_IMAGE, "docker_context": REAL_CONTEXT, "timeout_seconds": 10,
              "memory_mb": 256, "tmpfs_mb": 32}
    values.update(overrides)
    return RunnerSpec(**values)


def docker(*args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "--context", REAL_CONTEXT, *args], capture_output=True,
                          env=control_environment(), timeout=timeout, check=False)


def leftovers() -> list[str]:
    listed = docker("ps", "--all", "--filter", f"name={CONTAINER_PREFIX}",
                    "--format", "{{.Names}}")
    return listed.stdout.decode().split()


@pytest.fixture
def real_workspace():
    root = Path(REAL_ROOT).resolve() if REAL_ROOT else Path(tempfile.gettempdir()).resolve()
    path = Path(tempfile.mkdtemp(prefix="oryveta-snapshot-", dir=root)).resolve()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@real_docker
def test_real_docker_preflight_observes_a_linux_daemon_and_the_pinned_image():
    observed = run(DockerRunner(real_spec()).preflight())
    assert observed["endpoint"].startswith("unix:///")
    assert observed["daemon_os"] == "linux"
    assert observed["image_id"] == REAL_IMAGE
    assert observed["image_os"] == "linux"


@real_docker
def test_real_docker_runs_the_snapshot_with_stdin_and_returns_json(real_workspace):
    (real_workspace / "payload.txt").write_text("snapshot-contents")
    script = ('printf \'{"source":"%s","stdin":"%s"}\' "$(cat payload.txt)" "$(cat)"')
    result = run(DockerRunner(real_spec()).run(
        real_workspace, check(argv=("/bin/sh", "-c", script), stdin="from-controller")))
    assert result.exit_code == 0
    assert strict_json(result.stdout) == {"source": "snapshot-contents",
                                          "stdin": "from-controller"}
    assert leftovers() == []


@real_docker
def test_real_docker_cannot_write_to_the_host_or_the_root_filesystem(real_workspace):
    script = (f"if (printf x > {INPUT_DIR}/escape.txt) 2>/dev/null; then echo input-writable; fi; "
              "if (printf x > /var/tmp/oryveta-rootfs-probe) 2>/dev/null; then echo root-writable; fi; "
              f"echo changed > {WORK_DIR}/scratch.txt && echo work-writable")
    result = run(DockerRunner(real_spec()).run(
        real_workspace, check(argv=("/bin/sh", "-c", script))))
    assert result.exit_code == 0
    assert result.stdout == b"work-writable\n"
    assert not (real_workspace / "escape.txt").exists()
    assert not (real_workspace / "scratch.txt").exists()
    assert leftovers() == []


@real_docker
def test_real_docker_exposes_no_host_secrets_or_environment(real_workspace, monkeypatch):
    monkeypatch.setenv("ORYVETA_TEST_SECRET_MARKER", "top-secret-value")
    secret = real_workspace.parent / f"{real_workspace.name}-secret.txt"
    secret.write_text("top-secret-value")
    try:
        script = f"env; cat '{secret}' 2>&1; ls -a /; ls /var/run 2>&1"
        result = run(DockerRunner(real_spec()).run(
            real_workspace, check(argv=("/bin/sh", "-c", script))))
    finally:
        secret.unlink(missing_ok=True)
    assert b"top-secret-value" not in result.stdout + result.stderr
    assert b"ORYVETA_TEST_SECRET_MARKER" not in result.stdout
    assert b"docker.sock" not in result.stdout
    assert b"HOME=/tmp" in result.stdout
    assert leftovers() == []


@real_docker
def test_real_docker_has_no_network(real_workspace):
    result = run(DockerRunner(real_spec()).run(
        real_workspace, check(argv=("/bin/sh", "-c", "ls /sys/class/net; cat /proc/net/route"))))
    interfaces = result.stdout.decode().split("\n")[0].split()
    assert interfaces == ["lo"]
    routes = [line for line in result.stdout.decode().splitlines()[1:]
              if line and not line.startswith("Iface")]
    assert all(line.split()[0] == "lo" for line in routes), result.stdout


@real_docker
def test_real_docker_bounds_output(real_workspace):
    script = 'while : ; do printf "%s" "aaaaaaaaaaaaaaaa"; done'
    with pytest.raises(CodingError) as raised:
        run(DockerRunner(real_spec(output_bytes=8192)).run(
            real_workspace, check(argv=("/bin/sh", "-c", script))))
    assert raised.value.code == "runner_output_limit"
    assert leftovers() == []


@real_docker
def test_real_docker_bounds_scratch_space(real_workspace):
    script = f"dd if=/dev/zero of={WORK_DIR}/fill bs=1M count=64 2>/dev/null"
    result = run(DockerRunner(real_spec(tmpfs_mb=16)).run(
        real_workspace, check(argv=("/bin/sh", "-c", script))))
    assert result.exit_code != 0
    assert leftovers() == []


@real_docker
def test_real_docker_watchdog_stops_a_hanging_check(real_workspace):
    started = time.monotonic()
    with pytest.raises(CodingError) as raised:
        run(DockerRunner(real_spec()).run(
            real_workspace, check(argv=("/bin/sh", "-c", "sleep 300")), timeout_seconds=3))
    assert raised.value.code == "runner_timeout"
    assert time.monotonic() - started < 60
    assert leftovers() == []


@real_docker
def test_real_docker_watchdog_also_stops_a_check_that_ignores_termination(real_workspace):
    script = "trap '' TERM; sleep 300 & sleep 300"
    with pytest.raises(CodingError) as raised:
        run(DockerRunner(real_spec()).run(
            real_workspace, check(argv=("/bin/sh", "-c", script)), timeout_seconds=3))
    assert raised.value.code == "runner_timeout"
    assert leftovers() == []


@real_docker
def test_real_docker_returns_the_exit_code_and_removes_the_container(real_workspace):
    result = run(DockerRunner(real_spec()).run(
        real_workspace, check(argv=("/bin/sh", "-c", "exit 3"))))
    assert result.exit_code == 3
    assert result.container_name.startswith(CONTAINER_PREFIX)
    assert docker("container", "inspect", result.container_name).returncode != 0
    assert leftovers() == []


ORPHAN_CONTROLLER = """
import asyncio
import os
from pathlib import Path

from oryveta_engine.coding_contract import CheckSpec, RunnerSpec
from oryveta_engine.coding_sandbox import DockerRunner

spec = RunnerSpec(image=os.environ["ORYVETA_TEST_DOCKER_IMAGE"],
                  docker_context=os.environ["ORYVETA_TEST_DOCKER_CONTEXT"],
                  timeout_seconds=5, memory_mb=256, tmpfs_mb=32)
check = CheckSpec(name="hang", argv=("/bin/sh", "-c", "sleep 300"), stdin="",
                  expected_json=None)
asyncio.run(DockerRunner(spec).run(Path(os.environ["ORYVETA_TEST_SNAPSHOT"]), check))
"""


@real_docker
def test_real_docker_container_stops_itself_when_the_controller_is_killed(real_workspace):
    """A SIGKILLed controller must not leave repository code running."""
    assert leftovers() == []
    environment = {**control_environment(), "PYTHONPATH": str(Path(__file__).parents[1] / "engine"),
                   "ORYVETA_TEST_DOCKER_IMAGE": REAL_IMAGE,
                   "ORYVETA_TEST_DOCKER_CONTEXT": REAL_CONTEXT,
                   "ORYVETA_TEST_SNAPSHOT": str(real_workspace)}
    child = subprocess.Popen([sys.executable, "-c", ORPHAN_CONTROLLER], env=environment,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    name = ""
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not name:
            running = docker("ps", "--filter", f"name={CONTAINER_PREFIX}", "--format",
                             "{{.Names}}").stdout.decode().split()
            name = running[0] if running else ""
            time.sleep(0.2)
        assert name, "the orphan controller never started a container"
        child.send_signal(signal.SIGKILL)
        assert child.wait(timeout=30) != 0
        state = {}
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            probe = docker("container", "inspect", name, "--format", "{{json .State}}")
            if probe.returncode != 0:
                break
            state = strict_json(probe.stdout)
            if state.get("Running") is False:
                break
            time.sleep(0.5)
        assert state.get("Running") is False, state
        assert state.get("ExitCode") in (124, 137), state
    finally:
        if name:
            docker("container", "rm", "--force", "--volumes", name)
        if child.poll() is None:  # pragma: no cover - only on an unexpected failure
            child.kill()
            child.wait(timeout=30)


@real_docker
def test_real_docker_kernel_enforces_identity_and_resource_bounds(real_workspace):
    script = (
        "import json,os,pathlib; "
        "p=pathlib.Path('/proc/self/status'); "
        "s=dict(line.split(':',1) for line in p.read_text().splitlines()); "
        "c=pathlib.Path('/sys/fs/cgroup'); "
        "print(json.dumps({'uid':os.getuid(),'caps':int(s['CapEff'].strip(),16),"
        "'nnp':int(s['NoNewPrivs'].strip()),'memory':(c/'memory.max').read_text().strip(),"
        "'swap':(c/'memory.swap.max').read_text().strip(),"
        "'pids':(c/'pids.max').read_text().strip(),'cpu':(c/'cpu.max').read_text().strip()}))"
    )
    result = run(DockerRunner(real_spec(cpus=0.125)).run(
        real_workspace, check(argv=("python", "-c", script))))
    observed = strict_json(result.stdout)
    assert observed["uid"] != 0
    assert observed["caps"] == 0 and observed["nnp"] == 1
    assert int(observed["memory"]) == 256 * 1024 * 1024
    assert int(observed["swap"]) == 0
    assert int(observed["pids"]) == 64
    quota, period = map(int, observed["cpu"].split())
    assert quota / period <= 0.125


@real_docker
def test_real_docker_pins_context_and_does_not_inherit_proxy_credentials(
        real_workspace, tmp_path, monkeypatch):
    observed = run(DockerRunner(real_spec()).preflight())
    home = tmp_path / "docker-home"
    config = home / ".docker"
    config.mkdir(parents=True)
    context = "repair-proxy-test"
    create = subprocess.run(
        ["docker", "--config", str(config), "context", "create", context,
         "--docker", f"host={observed['endpoint']}"],
        env=control_environment(), capture_output=True, timeout=30)
    assert create.returncode == 0, create.stderr
    (config / "config.json").write_text(json.dumps({"proxies": {"default": {
        "httpProxy": "http://synthetic-user:private-proxy-marker@127.0.0.1:1",
        "httpsProxy": "http://synthetic-user:private-proxy-marker@127.0.0.1:1"}}}))
    with monkeypatch.context() as scoped:
        scoped.setenv("HOME", str(home))
        scoped.setenv("DOCKER_CONFIG", str(config))
        instance = DockerRunner(real_spec(docker_context=context))
        run(instance.preflight())
        update = subprocess.run(
            ["docker", "--config", str(config), "context", "update", context,
             "--docker", "host=tcp://127.0.0.1:1"],
            env=control_environment(), capture_output=True, timeout=30)
        assert update.returncode == 0, update.stderr
        result = run(instance.run(real_workspace, check(argv=("python", "-c",
            "import json,os; print(json.dumps({k:v for k,v in os.environ.items() if k.lower().endswith('_proxy')}))"))))
    assert b"private-proxy-marker" not in result.stdout
    assert all(not value for value in strict_json(result.stdout).values())
    assert leftovers() == []
