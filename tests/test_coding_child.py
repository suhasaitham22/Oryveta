"""Behavioral regressions for the supervised repair child.

`oryveta_engine.coding_child` is the process that actually runs the local repair
loop, so its whole job is to be stoppable and to never report an outcome nobody
is left to publish. These tests pin that: a bad invocation refuses before any
work, the child's own bound cancels the run instead of abandoning it, the
resolved Docker executable is the one the runner is given, and a child whose
worker process disappears exits without writing an outcome at all.

The repair loop itself is not re-tested here; `test_coding_runtime.py` covers
it, and the real local model and Docker runs belong to the integration smoke
the parent performs. The stand-in loops here produce no patch and prove no
repair quality: they stand in for the *process*, which is what this module is.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from oryveta_engine import coding_child
from oryveta_engine.coding_child import DEADLINE_EXIT, ORPHANED_EXIT, main, read_goal
from oryveta_engine.coding_contract import CodingError
from oryveta_engine.coding_worker import repair_child_environment

LOCAL_RUN_ID = "4f3e2d1c0b9a8f7e6d5c4b3a29180706"
GOAL = "Keep add_one's name but increment by two, per the synthetic fixture task."
MODEL_DIGEST = "a" * 64
IMAGE_ID = "sha256:" + "b" * 64

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

# A real child process whose repair loop never finishes on its own, so only its
# own bound or its parent's disappearance can end it. The loop is replaced in
# the child's own namespace; nothing else about the child is changed.
CHILD_HARNESS = (
    "import asyncio, sys\n"
    "from oryveta_engine import coding_child\n"
    "async def never(spec, source_zip, goal, output, run_root, *,\n"
    "                model=None, runner=None):\n"
    "    output.mkdir(mode=0o700, parents=True)\n"
    "    await asyncio.sleep(120)\n"
    "coding_child.repair = never\n"
    "coding_child.DockerRunner = lambda spec, docker_cli='docker': None\n"
    "raise SystemExit(coding_child.main(sys.argv[1:]))\n"
)

# A stand-in for the worker process: it starts the child in its own session
# exactly as the worker does, records the child's PID and then has its own PID
# killed, leaving the child with no parent left to publish anything.
WORKER_STANDIN = (
    "import os, signal, subprocess, sys\n"
    "command = [sys.executable, '-c', sys.argv[1], *sys.argv[3:],\n"
    "           '--parent-pid', str(os.getpid())]\n"
    "child = subprocess.Popen(command, start_new_session=True)\n"
    "with open(sys.argv[2], 'w', encoding='utf-8') as handle:\n"
    "    handle.write(str(child.pid))\n"
    "    handle.flush()\n"
    "    os.fsync(handle.fileno())\n"
    "os.kill(os.getpid(), signal.SIGKILL)\n"
)


# -- helpers --------------------------------------------------------------

def receipt_row(**overrides) -> dict:
    receipt = {
        "run_id": LOCAL_RUN_ID, "mode": "repair", "status": "needs_review",
        "verification": "passed", "phase": "finished",
    }
    receipt.update(overrides)
    return receipt


def prepared(tmp_path: Path) -> dict[str, str]:
    """The private inputs a worker lays out before starting a child."""
    run = tmp_path / "run"
    run.mkdir(mode=0o700, exist_ok=True)
    configuration = run / "configuration.json"
    configuration.write_text(json.dumps(CONFIGURATION), encoding="utf-8")
    source = run / "source.zip"
    source.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    goal = run / "goal.txt"
    goal.write_text(GOAL, encoding="utf-8")
    runs = run / "runs"
    runs.mkdir(mode=0o700, exist_ok=True)
    return {
        "--config": str(configuration),
        "--source-zip": str(source),
        "--goal-file": str(goal),
        "--output": str(tmp_path / "evidence" / "run-1"),
        "--run-root": str(runs),
        "--result": str(run / "child-result.json"),
    }


def argv(inputs: dict[str, str], **overrides) -> list[str]:
    arguments = {**inputs, "--max-seconds": "30",
                 "--parent-pid": str(os.getppid()), "--docker-cli": sys.executable}
    arguments.update({key: str(value) for key, value in overrides.items()})
    return [item for pair in arguments.items() for item in pair]


def stub_repair(monkeypatch, receipt: dict, *, delay: float = 0.0,
                record: list | None = None):
    """Replace the real loop with one that records what it was handed."""
    async def loop(spec, source_zip, goal, output, run_root, *, model=None, runner=None):
        if record is not None:
            record.append({"spec": spec, "goal": goal, "output": output,
                           "run_root": run_root, "runner": runner,
                           "source_zip": source_zip})
        output.mkdir(mode=0o700, parents=True)
        if delay:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                # What `coding_runtime.repair` does: close the evidence and
                # report the run as cancelled rather than vanish.
                return {"run_id": LOCAL_RUN_ID, "mode": "repair", "status": "cancelled",
                        "error_code": "cancelled", "verification": "not_accepted"}
        return receipt

    monkeypatch.setattr(coding_child, "repair", loop)
    monkeypatch.setattr(coding_child, "DockerRunner",
                        lambda spec, docker_cli="docker": {"docker_cli": docker_cli})


def recorded_pid(path: Path, limit: float = 10.0) -> int:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            time.sleep(0.02)
    raise AssertionError("no process recorded a PID")


def wait_until_exited(child: subprocess.Popen, limit: float = 20.0) -> int | None:
    deadline = time.monotonic() + limit
    while child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    return child.poll()


def wait_until_gone(pid: int, limit: float = 20.0) -> bool:
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
    try:
        os.kill(pid, 9)
    except OSError:
        pass


# -- invocation -----------------------------------------------------------

@pytest.mark.parametrize("overrides", [
    {"--parent-pid": "0"},
    {"--parent-pid": "-1"},
    {"--max-seconds": "-1"},
])
def test_an_unusable_invocation_is_refused_before_any_work(tmp_path, overrides,
                                                           monkeypatch):
    def forbidden(*_: object, **__: object):
        raise AssertionError("a refused invocation must not start a repair")

    monkeypatch.setattr(coding_child, "repair", forbidden)

    assert main(argv(prepared(tmp_path), **overrides)) == 2


def test_an_existing_evidence_directory_is_refused(tmp_path, monkeypatch):
    def forbidden(*_: object, **__: object):
        raise AssertionError("prior evidence is never overwritten")

    monkeypatch.setattr(coding_child, "repair", forbidden)
    inputs = prepared(tmp_path)
    Path(inputs["--output"]).mkdir(mode=0o700, parents=True)

    assert main(argv(inputs)) == 2


def test_a_missing_run_root_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(coding_child, "repair", lambda *a, **k: None)
    inputs = prepared(tmp_path)
    inputs["--run-root"] = str(tmp_path / "absent")

    assert main(argv(inputs)) == 2


def test_a_child_whose_worker_is_already_gone_reports_nothing(tmp_path, monkeypatch):
    def forbidden(*_: object, **__: object):
        raise AssertionError("an orphan must not start a repair")

    monkeypatch.setattr(coding_child, "repair", forbidden)
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    inputs = prepared(tmp_path)

    assert main(argv(inputs, **{"--parent-pid": finished.pid})) == ORPHANED_EXIT
    assert not Path(inputs["--result"]).exists()


@pytest.mark.parametrize("goal, expected", [
    (b"", "bounded nonempty"),
    (b"   \n", "bounded nonempty"),
    (b"x" * 4097, "bounded size"),
])
def test_a_goal_that_is_not_bounded_text_is_refused(tmp_path, goal, expected):
    path = tmp_path / "goal.txt"
    path.write_bytes(goal)

    with pytest.raises(CodingError, match=expected):
        read_goal(path)


def test_a_refused_goal_becomes_a_bounded_outcome_code(tmp_path, monkeypatch):
    stub_repair(monkeypatch, receipt_row())
    inputs = prepared(tmp_path)
    Path(inputs["--goal-file"]).write_bytes(b"x" * 5000)

    assert main(argv(inputs)) == 1

    report = json.loads(Path(inputs["--result"]).read_text(encoding="utf-8"))
    assert report["error_code"] == "invalid_goal"
    assert report["status"] == "rejected"


# -- running one repair ---------------------------------------------------

def test_a_verified_run_reports_its_own_identity_and_nothing_private(tmp_path,
                                                                     monkeypatch):
    record: list[dict] = []
    stub_repair(monkeypatch, receipt_row(error_code=None), record=record)
    inputs = prepared(tmp_path)

    assert main(argv(inputs)) == 0

    report = json.loads(Path(inputs["--result"]).read_text(encoding="utf-8"))
    assert report == {"status": "needs_review", "error_code": None,
                      "verification": "passed", "mode": "repair",
                      "run_id": LOCAL_RUN_ID}
    # The goal is data the loop receives, never an argument the worker reads back.
    assert record[0]["goal"] == GOAL
    assert record[0]["output"] == Path(inputs["--output"])


def test_the_resolved_docker_executable_is_what_the_runner_is_given(tmp_path,
                                                                    monkeypatch):
    record: list[dict] = []
    stub_repair(monkeypatch, receipt_row(), record=record)
    inputs = prepared(tmp_path)

    main(argv(inputs, **{"--docker-cli": "/usr/local/bin/docker"}))

    # The child does not search a PATH it cannot vouch for.
    assert record[0]["runner"] == {"docker_cli": "/usr/local/bin/docker"}


def test_a_failed_run_is_reported_without_claiming_success(tmp_path, monkeypatch):
    stub_repair(monkeypatch, receipt_row(status="failed", error_code="verification_failed",
                                         verification="not_accepted"))
    inputs = prepared(tmp_path)

    assert main(argv(inputs)) == 1

    report = json.loads(Path(inputs["--result"]).read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["verification"] == "not_accepted"


def test_an_unusable_configuration_is_a_bounded_outcome(tmp_path, monkeypatch):
    stub_repair(monkeypatch, receipt_row())
    inputs = prepared(tmp_path)
    Path(inputs["--config"]).write_text('{"schema_version": 7}', encoding="utf-8")

    assert main(argv(inputs)) == 1

    report = json.loads(Path(inputs["--result"]).read_text(encoding="utf-8"))
    assert report["error_code"] == "invalid_config"


def test_the_childs_own_bound_cancels_the_run_rather_than_abandoning_it(tmp_path,
                                                                       monkeypatch):
    stub_repair(monkeypatch, receipt_row(), delay=30)
    inputs = prepared(tmp_path)

    assert main(argv(inputs, **{"--max-seconds": "0.3"})) == DEADLINE_EXIT

    report = json.loads(Path(inputs["--result"]).read_text(encoding="utf-8"))
    # Cancelled, not "timed out and discarded": the loop closed its own record.
    assert report["status"] == "cancelled"
    assert report["error_code"] == "cancelled"
    assert report["verification"] == "not_accepted"


def test_a_bound_of_zero_lets_the_worker_do_the_supervising(tmp_path, monkeypatch):
    stub_repair(monkeypatch, receipt_row())
    inputs = prepared(tmp_path)

    assert main(argv(inputs, **{"--max-seconds": "0"})) == 0


# -- losing the worker ----------------------------------------------------

def test_a_child_whose_worker_dies_exits_without_reporting_anything(tmp_path):
    """The real transition: a worker killed hard cannot fence anything.

    The child is left with no parent, so it stops its own repair and writes no
    outcome at all. The work item is recovered by its lease expiring, which is
    the only guarantee the worker makes.
    """
    inputs = prepared(tmp_path)
    pid_path = tmp_path / "child.pid"
    command = [sys.executable, "-c", WORKER_STANDIN, CHILD_HARNESS, str(pid_path)]
    for key, value in inputs.items():
        command += [key, value]
    command += ["--max-seconds", "60", "--docker-cli", sys.executable]
    standin = subprocess.Popen(
        command, cwd=str(tmp_path),
        env=repair_child_environment(tmp_path, docker_cli=sys.executable,
                                     docker_config=None),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    assert wait_until_exited(standin) is not None
    child_pid = recorded_pid(pid_path)
    try:
        assert wait_until_gone(child_pid), "the orphaned repair child kept running"
        assert not Path(inputs["--result"]).exists()
    finally:
        kill_if_alive(child_pid)


def test_the_orphan_watcher_cancels_instead_of_killing(monkeypatch):
    """Cancellation is what lets the loop close evidence and remove containers."""
    state = coding_child._Orphaned()
    cancelled: list[bool] = []
    monkeypatch.setattr(coding_child, "PARENT_POLL_SECONDS", 0.01)

    def cancel() -> None:
        cancelled.append(True)
        # The run ends, so the watcher stops instead of hard-exiting.
        state.stop.set()

    # A PID this process was never started by: the watcher must notice at once.
    coding_child._watch_parent(state, 424242, cancel)

    assert state.lost is True
    assert cancelled == [True]


def test_a_cancelled_loop_is_reported_as_cancelled(tmp_path, monkeypatch):
    async def cancelling(spec, source_zip, goal, output, run_root, *,
                         model=None, runner=None):
        output.mkdir(mode=0o700, parents=True)
        raise asyncio.CancelledError()

    monkeypatch.setattr(coding_child, "repair", cancelling)
    monkeypatch.setattr(coding_child, "DockerRunner",
                        lambda spec, docker_cli="docker": None)
    inputs = prepared(tmp_path)

    assert main(argv(inputs)) == 1

    report = json.loads(Path(inputs["--result"]).read_text(encoding="utf-8"))
    assert report["status"] == "cancelled"
