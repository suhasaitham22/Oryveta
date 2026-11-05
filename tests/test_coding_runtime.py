"""Controller boundaries with scripted proposals and REAL isolated execution.

The model is scripted for determinism; no mocked check result can pass these
cases. The opt-in live-model smoke is separate from this regression suite.
"""
import asyncio
import hashlib
import io
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from oryveta_engine import coding_runtime
from oryveta_engine.coding_config import parse_spec
from oryveta_engine.coding_contract import CodingError, LoopLimits, ModelReply, ToolCall, canonical_json

PROGRAM = '''import json, sys
value = json.load(sys.stdin)
if value is None:
    print("null")
else:
    print(json.dumps(value + 1))
'''
REPAIRED = PROGRAM.replace("value + 1", "value + 2")


def write_zip(path: Path, files: dict[str, str], prefix: str = "repo/") -> Path:
    """Write a source archive the importer normalizes by dropping one wrapper."""
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(prefix + name, data)
    return path


def no_model(*_args, **_kwargs):
    raise AssertionError("re-verification must never construct a model client")


class ScriptedModel:
    def __init__(self, mode="fix"):
        self.mode = mode
        self.turns = 0
        self.verifications = 0
        self.seen = []

    async def verify(self):
        self.verifications += 1
        return {"name": "scripted test proposer", "digest": "a" * 64}

    async def turn(self, messages, _tools, **_limits):
        self.seen.append(canonical_json(messages))
        turn = self.turns
        self.turns += 1
        if self.mode == "claim_only":
            return ModelReply("Everything passed; publish it now", (), 1, 1)
        if self.mode == "escape":
            return (ModelReply("", (ToolCall("read_file", {"path": "../configuration.json"}),), 1, 1)
                    if turn == 0 else ModelReply("Done", (), 1, 1))
        if turn == 0:
            return ModelReply("", (ToolCall("read_file", {"path": "main.py"}),), 1, 1)
        if turn == 1:
            observed = json.loads(messages[-1]["content"])
            old, new = "value + 1", "value + 2"
            if self.mode == "wrong":
                new = "value + 3"
            elif self.mode == "empty_exit":
                old, new = "print(json.dumps(value + 1))", "raise SystemExit(0)"
            return ModelReply("", (ToolCall("replace_text", {
                "path": "main.py", "expected_sha256": observed["sha256"], "old": old, "new": new}),), 1, 1)
        if turn == 2 and self.mode == "fix":
            return ModelReply("", (ToolCall("run_checks", {}),), 1, 1)
        return ModelReply("All checks passed", (), 1, 1)


@pytest.fixture
def execution(tmp_path, coding_spec_data):
    context = os.environ.get("ORYVETA_TEST_DOCKER_CONTEXT")
    image = os.environ.get("ORYVETA_TEST_DOCKER_IMAGE")
    if not context or not image:
        pytest.skip("explicit local Docker context/image required for real execution tests")
    coding_spec_data["runner"].update(docker_context=context, image=image)
    spec = parse_spec(coding_spec_data)
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("repo/main.py", PROGRAM)
    with tempfile.TemporaryDirectory(dir=os.environ.get("ORYVETA_TEST_RUN_ROOT")) as directory:
        run_root = Path(directory)
        yield spec, archive, tmp_path / "evidence", run_root


def invoke(execution, model):
    spec, archive, output, run_root = execution
    return asyncio.run(coding_runtime.repair(spec, archive, "Add two; preserve null.", output,
                                            run_root, model=model))


def test_real_verifier_accepts_a_repair_and_keeps_private_cases_out_of_context(execution):
    spec, archive, output, run_root = execution
    original = hashlib.sha256(archive.read_bytes()).hexdigest()
    model = ScriptedModel()
    receipt = invoke(execution, model)
    assert receipt["status"] == "needs_review"
    assert receipt["verification"] == "passed"
    assert receipt["checks_passed"] == 3
    assert receipt["publication"] == "not_requested"
    assert receipt["configuration_sha256"] == spec.digest
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == original
    assert list(run_root.iterdir()) == []
    assert not (output / "unverified.patch").exists()
    patch = (output / "verified.patch").read_bytes()
    assert hashlib.sha256(patch).hexdigest() == receipt["patch_sha256"]
    candidate = (output / "candidate.zip").read_bytes()
    assert hashlib.sha256(candidate).hexdigest() == receipt["candidate_archive_sha256"]
    assert "acceptance-private-marker" not in "".join(model.seen)
    results = json.loads((output / "verification.json").read_text())
    assert {row["name"] for row in results if row["passed"]} == {
        "increment", "empty", "acceptance-private-marker"}
    assert json.loads((output / "baseline.json").read_text())[0]["passed"] is False
    assert json.loads((output / "receipt.json").read_text())["status"] == "needs_review"
    assert receipt["mode"] == "repair"
    assert receipt["model_calls"] == receipt["turns"] + 1


@pytest.mark.parametrize("mode", ["wrong", "empty_exit"])
def test_model_claims_and_exit_zero_cannot_override_behavioral_verification(execution, mode):
    receipt = invoke(execution, ScriptedModel(mode))
    assert receipt["status"] == "rejected"
    assert receipt["error_code"] == "verification_failed"
    assert not (execution[2] / "verified.patch").exists()
    assert (execution[2] / "unverified.patch").is_file()
    assert hashlib.sha256((execution[2] / "candidate.zip").read_bytes()).hexdigest() == \
        receipt["candidate_archive_sha256"]
    assert any(not row["passed"] for row in json.loads((execution[2] / "verification.json").read_text()))


@pytest.mark.parametrize("mode", ["claim_only", "escape"])
def test_no_change_or_unauthorized_tool_cannot_create_a_verified_patch(execution, mode):
    receipt = invoke(execution, ScriptedModel(mode))
    assert receipt["error_code"] == "no_change"
    assert not (execution[2] / "verified.patch").exists()
    if mode == "escape":
        events = [json.loads(line) for line in (execution[2] / "events.jsonl").read_text().splitlines()]
        denied = [row for row in events if row["kind"] == "tool_result"]
        assert denied[0]["result"]["error"] == "invalid_path"


def test_non_reproducing_source_stops_before_inference(execution):
    spec, archive, output, run_root = execution
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("repo/main.py", PROGRAM.replace("value + 1", "value + 2"))
    model = ScriptedModel()
    result = invoke(execution, model)
    assert result["error_code"] == "not_reproduced"
    assert model.turns == model.verifications == 0
    assert not (output / "verified.patch").exists()


def test_insufficient_model_budget_does_not_start_a_generation(execution):
    spec, archive, output, run_root = execution
    model = ScriptedModel()
    spec = replace(spec, limits=LoopLimits(total_tokens=1024))
    result = invoke((spec, archive, output, run_root), model)
    assert result["error_code"] == "token_budget"
    assert model.turns == 0


def test_turn_budget_stops_without_accepting_partial_work(execution):
    spec, archive, output, run_root = execution
    spec = replace(spec, limits=LoopLimits(turns=1))
    result = invoke((spec, archive, output, run_root), ScriptedModel())
    assert result["error_code"] == "turn_budget"
    assert result["turns"] == 1
    assert not (output / "verified.patch").exists()


def test_missing_argument_can_be_corrected_before_independent_verification(execution):
    class RecoveringModel(ScriptedModel):
        pending = None
        injected = False

        async def turn(self, messages, tools, **limits):
            if self.pending is not None:
                error = json.loads(messages[-1]["content"])
                assert error["details"]["missing_fields"] == ["path"]
                call, self.pending = self.pending, None
                return ModelReply("", (call,), 1, 1)
            reply = await super().turn(messages, tools, **limits)
            if reply.calls and reply.calls[0].name == "replace_text" and not self.injected:
                self.pending = reply.calls[0]
                self.injected = True
                arguments = {key: value for key, value in self.pending.arguments.items() if key != "path"}
                return ModelReply("", (ToolCall("replace_text", arguments),), 1, 1)
            return reply

    receipt = invoke(execution, RecoveringModel())
    assert receipt["status"] == "needs_review"
    assert receipt["checks_passed"] == 3
    assert receipt["turns"] == 5


@pytest.mark.parametrize("call", [
    ToolCall("read_file", {"path": "../configuration.json"}),
    ToolCall("run_checks", {}),
])
def test_repeated_failure_stops_without_exhausting_inference_budget(execution, call):
    class RepeatingModel(ScriptedModel):
        async def turn(self, *_args, **_limits):
            self.turns += 1
            return ModelReply("", (call,), 1, 1)

    model = RepeatingModel()
    receipt = invoke(execution, model)
    assert receipt["status"] == "failed"
    assert receipt["error_code"] == "no_progress"
    assert receipt["turns"] == receipt["tool_calls"] == model.turns == 2
    assert not (execution[2] / "verified.patch").exists()
    events = [json.loads(line) for line in (execution[2] / "events.jsonl").read_text().splitlines()]
    assert any(row["kind"] == "decision" and row["action"] == "stop" for row in events)


def test_failing_checks_can_be_retried_after_an_actual_source_edit(execution):
    class RevisingModel(ScriptedModel):
        async def turn(self, messages, _tools, **_limits):
            turn = self.turns
            self.turns += 1
            if turn in (0, 3, 6):
                call = ToolCall("run_checks", {})
            elif turn in (1, 4):
                call = ToolCall("read_file", {"path": "main.py"})
            elif turn in (2, 5):
                observed = json.loads(messages[-1]["content"])
                old, new = ("value + 1", "value + 3") if turn == 2 else ("value + 3", "value + 2")
                call = ToolCall("replace_text", {"path": "main.py", "expected_sha256": observed["sha256"],
                                                 "old": old, "new": new})
            else:
                return ModelReply("Done", (), 1, 1)
            return ModelReply("", (call,), 1, 1)

    receipt = invoke(execution, RevisingModel())
    assert receipt["status"] == "needs_review"
    assert receipt["checks_passed"] == 3
    assert receipt["turns"] == 8


def test_failed_evidence_commit_removes_the_verified_artifact(execution, monkeypatch):
    original = coding_runtime.Trace.event
    def fail_terminal(self, kind, **data):
        if kind == "run_finished":
            raise CodingError("trace_limit", "injected evidence storage failure")
        return original(self, kind, **data)
    monkeypatch.setattr(coding_runtime.Trace, "event", fail_terminal)
    result = invoke(execution, ScriptedModel())
    assert result["error_code"] == "evidence_write_failed"
    assert result["verification"] == "not_accepted"
    assert not (execution[2] / "verified.patch").exists()
    assert (execution[2] / "unverified.patch").exists()


def test_existing_evidence_is_never_overwritten(execution):
    execution[2].mkdir()
    marker = execution[2] / "keep.txt"
    marker.write_text("operator data")
    with pytest.raises(CodingError, match="new output"):
        invoke(execution, ScriptedModel())
    assert marker.read_text() == "operator data"


def test_cli_reports_a_verified_review_candidate(execution, monkeypatch, capsys):
    spec, archive, output, run_root = execution
    config = output.parent / "operator.json"
    data = asdict(spec)
    data.pop("digest")
    data["schema_version"] = 1
    config.write_text(json.dumps(data))
    monkeypatch.setattr(coding_runtime, "LocalToolModel", lambda _spec: ScriptedModel())
    monkeypatch.setattr("sys.argv", ["coding_runtime", "--config", str(config), "--source-zip", str(archive),
                                    "--goal", "Add two; preserve null", "--output", str(output),
                                    "--run-root", str(run_root)])
    assert coding_runtime.main() == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["status"] == "needs_review"
    assert rendered["verification"] == "passed"
    assert rendered["receipt"] == str(output / "receipt.json")


INTERRUPTED_CLI = r"""
import asyncio
import sys
sys.path.insert(0, "tests")
from test_coding_runtime import ScriptedModel
from oryveta_engine import coding_runtime
from oryveta_engine.coding_sandbox import DockerRunner

_, config, archive, output, run_root, boundary = sys.argv

async def pause():
    print("paused", flush=True)
    await asyncio.Event().wait()

class PausingModel(ScriptedModel):
    async def turn(self, messages, tools, **limits):
        if boundary == "model" or (boundary == "after_edit" and self.turns == 2):
            await pause()
        return await super().turn(messages, tools, **limits)

class PausingRunner(DockerRunner):
    async def run(self, workspace, check, **limits):
        if boundary in {"verification", "tool"} and workspace.name == "candidate":
            await pause()
        return await super().run(workspace, check, **limits)

coding_runtime.LocalToolModel = lambda spec: PausingModel("fix" if boundary == "tool" else "skip_development")
coding_runtime.DockerRunner = PausingRunner
sys.argv = ["coding_runtime", "--config", config, "--source-zip", archive,
            "--output", output, "--run-root", run_root, "--goal", "Add two; preserve null."]
raise SystemExit(coding_runtime.main())
"""


@pytest.mark.parametrize("boundary,turns,phase", [
    ("model", 1, "model_call"),
    ("after_edit", 3, "model_call"),
    ("verification", 3, "verification"),
    ("tool", 3, "tool_call"),
])
@pytest.mark.parametrize("stop", [signal.SIGKILL, signal.SIGTERM])
def test_interrupted_cli_preserves_accounting_and_unverified_work(execution, boundary, turns, phase, stop):
    spec, archive, output, run_root = execution
    config = output.parent / "operator.json"
    data = asdict(spec)
    data.pop("digest")
    config.write_text(json.dumps({"schema_version": 1, **data}))
    command = [sys.executable, "-c", INTERRUPTED_CLI, str(config), str(archive),
               str(output), str(run_root), boundary]
    checkout = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(
        str(checkout / path) for path in ("engine", "apps/api"))}
    with subprocess.Popen(command, cwd=checkout, env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=45), "controller did not reach the interruption boundary"
                assert child.stdout.readline() == b"paused\n"
            child.send_signal(stop)
            child.communicate(timeout=30)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["status"] == ("incomplete" if stop == signal.SIGKILL else "cancelled")
    assert receipt["turns"] == turns
    assert receipt["phase" if stop == signal.SIGKILL else "last_phase"] == phase
    if phase == "model_call":
        assert receipt["unsettled_token_reservation"] > 0
    else:
        assert receipt["unsettled_token_reservation"] == 0
    assert receipt["tokens_observed"] == (0 if boundary == "model" else 4 if boundary == "after_edit" else 6)
    assert receipt["tool_calls"] == (0 if boundary == "model" else 3 if boundary == "tool" else 2)
    if boundary == "tool" and stop == signal.SIGKILL:
        assert receipt["active_tool"] == "run_checks"
    assert receipt["source_archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert receipt["verification"] == "not_accepted"
    assert not (output / "verified.patch").exists()
    if boundary != "model":
        patch = (output / "unverified.patch").read_bytes()
        assert hashlib.sha256(patch).hexdigest() == receipt["candidate_patch_sha256"]
        assert b"+    print(json.dumps(value + 2))" in patch
        archived = (output / "candidate.zip").read_bytes()
        assert hashlib.sha256(archived).hexdigest() == receipt["candidate_archive_sha256"]
    else:
        assert not (output / "candidate.zip").exists()
    if stop == signal.SIGTERM:
        assert list(run_root.iterdir()) == []


def test_failed_admission_checkpoint_prevents_model_execution(execution, monkeypatch):
    write = coding_runtime._json_file
    def fail_admission(path, value):
        if path.name == "receipt.json" and value.get("phase") == "model_call":
            raise OSError("injected checkpoint storage failure")
        write(path, value)
    monkeypatch.setattr(coding_runtime, "_json_file", fail_admission)
    model = ScriptedModel()
    receipt = invoke(execution, model)
    assert receipt["error_code"] == "evidence_write_failed"
    assert receipt["verification"] == "not_accepted"
    assert model.turns == 0
    assert not (execution[2] / "verified.patch").exists()


def test_failed_terminal_checkpoint_demotes_the_verified_artifact(execution, monkeypatch):
    write = coding_runtime._json_file
    def fail_terminal(path, value):
        if path.name == "receipt.json" and value.get("phase") == "finished":
            raise OSError("injected terminal storage failure")
        write(path, value)
    monkeypatch.setattr(coding_runtime, "_json_file", fail_terminal)
    with pytest.raises(CodingError) as failure:
        invoke(execution, ScriptedModel())
    assert failure.value.code == "evidence_write_failed"
    receipt = json.loads((execution[2] / "receipt.json").read_text())
    assert receipt["status"] == "incomplete"
    assert receipt["verification"] == "not_accepted"
    assert not (execution[2] / "verified.patch").exists()
    assert (execution[2] / "unverified.patch").is_file()


def test_undoing_all_edits_removes_the_candidate_checkpoint(execution):
    class UndoingModel(ScriptedModel):
        async def turn(self, messages, tools, **limits):
            if self.turns == 2:
                self.turns += 1
                observed = json.loads(messages[-1]["content"])
                return ModelReply("", (ToolCall("replace_text", {
                    "path": "main.py", "expected_sha256": observed["sha256"],
                    "old": "value + 2", "new": "value + 1"}),), 1, 1)
            return await super().turn(messages, tools, **limits)
    receipt = invoke(execution, UndoingModel())
    assert receipt["error_code"] == "no_change"
    assert "candidate_patch_sha256" not in receipt
    assert "candidate_archive_sha256" not in receipt
    assert not (execution[2] / "unverified.patch").exists()
    assert not (execution[2] / "candidate.zip").exists()
    assert not (execution[2] / "verified.patch").exists()


def reverify(execution, candidate, name, goal="Re-verify the increment repair."):
    """Re-verify an archive through the real API; no model is ever passed in."""
    spec, archive, output, run_root = execution
    destination = output.parent / name
    receipt = asyncio.run(coding_runtime.verify_candidate(
        spec, archive, candidate, goal, destination, run_root))
    return receipt, destination


def test_exported_candidate_is_reverifiable_without_any_model(execution, monkeypatch):
    spec, archive, output, run_root = execution
    repaired = invoke(execution, ScriptedModel())
    candidate = output / "candidate.zip"
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == repaired["candidate_archive_sha256"]
    monkeypatch.setattr(coding_runtime, "LocalToolModel", no_model)
    receipt, second = reverify(execution, candidate, "reverified")
    assert (second / "candidate.zip").read_bytes() == candidate.read_bytes()
    assert receipt["status"] == "needs_review"
    assert receipt["verification"] == "passed"
    assert receipt["mode"] == "verification"
    assert receipt["checks_passed"] == 3
    assert receipt["publication"] == "not_requested"
    assert receipt["run_id"] != repaired["run_id"]
    assert receipt["model_calls"] == 0
    assert receipt["turns"] == receipt["tool_calls"] == receipt["tokens_observed"] == 0
    assert "model_observed" not in receipt
    assert "model_summary" not in receipt
    assert receipt["changed_paths"] == ["main.py"]
    assert receipt["reproduced_failures"] == ["acceptance-private-marker", "increment"]
    assert receipt["configuration_sha256"] == spec.digest
    assert receipt["checks_sha256"] == repaired["checks_sha256"]
    assert receipt["source_tree_sha256"] == repaired["source_tree_sha256"]
    assert receipt["candidate_tree_sha256"] == repaired["candidate_tree_sha256"]
    assert receipt["candidate_archive_sha256"] == repaired["candidate_archive_sha256"]
    assert receipt["patch_sha256"] == repaired["patch_sha256"]
    assert (second / "verified.patch").read_bytes() == (output / "verified.patch").read_bytes()
    assert not (second / "unverified.patch").exists()
    assert {row["name"] for row in json.loads((second / "verification.json").read_text())
            if row["passed"]} == {"increment", "empty", "acceptance-private-marker"}
    events = [json.loads(line) for line in (second / "events.jsonl").read_text().splitlines()]
    assert [row["kind"] for row in events] == ["run_started", "run_finished"]
    assert hashlib.sha256((second / "source.zip").read_bytes()).hexdigest() == \
        hashlib.sha256(archive.read_bytes()).hexdigest()
    assert list(run_root.iterdir()) == []


def test_reverification_refuses_a_candidate_that_fails_the_declared_cases(execution):
    output = execution[2]
    assert invoke(execution, ScriptedModel("wrong"))["error_code"] == "verification_failed"
    receipt, second = reverify(execution, output / "candidate.zip", "reverified")
    assert receipt["status"] == "rejected"
    assert receipt["error_code"] == "verification_failed"
    assert receipt["verification"] == "not_accepted"
    assert not (second / "verified.patch").exists()
    assert (second / "unverified.patch").is_file()
    assert any(not row["passed"] for row in json.loads((second / "verification.json").read_text()))


@pytest.mark.parametrize("program,code", [
    (REPAIRED, "not_reproduced"),
    (PROGRAM.replace('print("null")', 'print("0")'), "invalid_baseline"),
])
def test_reverification_requires_a_reproducing_and_preserved_baseline(execution, program, code):
    spec, _, output, run_root = execution
    source = write_zip(output.parent / "other-source.zip", {"main.py": program})
    candidate = write_zip(output.parent / "other-candidate.zip", {"main.py": program + "\n"})
    receipt = asyncio.run(coding_runtime.verify_candidate(
        spec, source, candidate, "Re-verify an unsuitable baseline.", output, run_root))
    assert receipt["status"] == "rejected"
    assert receipt["error_code"] == code
    assert (output / "baseline.json").is_file()
    assert not (output / "verification.json").exists()
    assert not (output / "verified.patch").exists()
    assert list(run_root.iterdir()) == []


def test_failed_reverification_evidence_commit_removes_the_verified_artifact(execution, monkeypatch):
    candidate = execution[2] / "candidate.zip"
    invoke(execution, ScriptedModel())
    original = coding_runtime.Trace.event
    def fail_terminal(self, kind, **data):
        if kind == "run_finished":
            raise CodingError("trace_limit", "injected evidence storage failure")
        return original(self, kind, **data)
    monkeypatch.setattr(coding_runtime.Trace, "event", fail_terminal)
    receipt, second = reverify(execution, candidate, "reverified")
    assert receipt["error_code"] == "evidence_write_failed"
    assert receipt["verification"] == "not_accepted"
    assert not (second / "verified.patch").exists()
    assert (second / "unverified.patch").is_file()


def test_cli_reverifies_a_candidate_with_no_inference_available(execution, monkeypatch, capsys):
    spec, archive, output, run_root = execution
    invoke(execution, ScriptedModel())
    config = output.parent / "operator.json"
    data = asdict(spec)
    data.pop("digest")
    data["schema_version"] = 1
    config.write_text(json.dumps(data))
    second = output.parent / "reverified"
    monkeypatch.setattr(coding_runtime, "LocalToolModel", no_model)
    monkeypatch.setattr("sys.argv", [
        "coding_runtime", "--config", str(config), "--source-zip", str(archive),
        "--candidate-zip", str(output / "candidate.zip"), "--goal", "Re-verify the increment repair",
        "--output", str(second), "--run-root", str(run_root)])
    assert coding_runtime.main() == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["status"] == "needs_review"
    assert rendered["mode"] == "verification"
    assert rendered["verification"] == "passed"
    assert rendered["receipt"] == str(second / "receipt.json")
    stored = json.loads((second / "receipt.json").read_text())
    assert stored["model_calls"] == 0
    assert stored["status"] == "needs_review"


@pytest.fixture
def reverify_offline(tmp_path, coding_spec_data):
    """Re-verification refusals that must be decided before a container exists."""
    def run(candidate_files, *, source_files=None, candidate_bytes=None, allowlists=None):
        data = dict(coding_spec_data)
        if allowlists is not None:
            data = dict(data, read_paths=list(allowlists[0]), write_paths=list(allowlists[1]))
        source = write_zip(tmp_path / "source.zip", source_files or {"main.py": PROGRAM})
        candidate = tmp_path / "candidate.zip"
        if candidate_bytes is None:
            write_zip(candidate, candidate_files)
        else:
            candidate.write_bytes(candidate_bytes)
        output, run_root = tmp_path / "evidence", tmp_path / "runs"
        receipt = asyncio.run(coding_runtime.verify_candidate(
            parse_spec(data), source, candidate, "Re-verify the supplied candidate.",
            output, run_root))
        return receipt, output, run_root
    return run


SCOPED = (("main.py", "notes.txt"), ("main.py",))


@pytest.mark.parametrize("candidate,source,allowlists,code", [
    ({"main.py": REPAIRED, "notes.txt": "added"}, None, None, "candidate_inventory"),
    ({"main.py": REPAIRED, "receipt.json": '{"status":"needs_review","verification":"passed"}',
      "operator.json": '{"write_paths":["notes.txt"]}'}, None, None, "candidate_inventory"),
    ({"main.py": REPAIRED}, {"main.py": PROGRAM, "notes.txt": "keep"}, SCOPED, "candidate_inventory"),
    ({"main.py": REPAIRED, "notes.txt": "tampered"}, {"main.py": PROGRAM, "notes.txt": "keep"},
     SCOPED, "candidate_scope"),
    ({"main.py": PROGRAM}, None, None, "no_change"),
])
def test_candidate_outside_the_declared_scope_is_refused_before_execution(
        reverify_offline, candidate, source, allowlists, code):
    receipt, output, run_root = reverify_offline(candidate, source_files=source, allowlists=allowlists)
    assert receipt["status"] == "rejected"
    assert receipt["error_code"] == code
    assert receipt["mode"] == "verification"
    assert receipt["verification"] == "not_accepted"
    assert receipt["model_calls"] == receipt["turns"] == receipt["tool_calls"] == 0
    assert (output / "candidate.zip").is_file()
    assert not (output / "baseline.json").exists()
    assert not (output / "verification.json").exists()
    assert not (output / "unverified.patch").exists()
    assert not (output / "verified.patch").exists()
    assert list(run_root.iterdir()) == []


@pytest.mark.parametrize("payload", [
    b"not a zip at all", b"PK\x03\x04 truncated", b"x" * (12 * 1024 * 1024 + 1),
])
def test_unusable_candidate_archive_is_refused(reverify_offline, payload):
    receipt, output, run_root = reverify_offline({}, candidate_bytes=payload)
    assert receipt["status"] == "rejected"
    assert receipt["error_code"] == "invalid_candidate"
    assert not (output / "verified.patch").exists()
    assert list(run_root.iterdir()) == []


def test_candidate_archive_with_a_symlink_entry_is_refused(reverify_offline):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("repo/main.py", REPAIRED)
        info = zipfile.ZipInfo("repo/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(info, "../../outside")
    receipt, output, _ = reverify_offline({}, candidate_bytes=buffer.getvalue())
    assert receipt["status"] == "rejected"
    assert receipt["error_code"] == "invalid_candidate"
    assert not (output / "verified.patch").exists()


def test_reverification_never_overwrites_existing_evidence(tmp_path, coding_spec_data):
    source = write_zip(tmp_path / "source.zip", {"main.py": PROGRAM})
    candidate = write_zip(tmp_path / "candidate.zip", {"main.py": REPAIRED})
    output = tmp_path / "evidence"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("operator data")
    with pytest.raises(CodingError, match="new output"):
        asyncio.run(coding_runtime.verify_candidate(
            parse_spec(coding_spec_data), source, candidate, "Re-verify a candidate.",
            output, tmp_path / "runs"))
    assert marker.read_text() == "operator data"
    assert list(output.iterdir()) == [marker]
