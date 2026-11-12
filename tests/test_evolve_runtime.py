"""Consumer-visible guarantees of the reviewed Evolve worker.

Every case runs against an in-process control plane and artifact store: no
sockets, no Supabase, no Docker, no model weights and no token spend. The
supervised stage child is replaced at the one seam that launches it, so the
worker's own ordering, identity, fencing and secrecy decisions are the thing
under test. The live workflow is exercised against a provisioned local stack
after integration.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import time

import pytest

from oryveta_engine import evolve_runtime as runtime
from oryveta_engine.coding_contract import CodingError
from oryveta_engine.evolve_contract import (
    NONRETRYABLE_CODES, EvidenceIndex, digest_json,
)
from oryveta_engine.evolve_lessons import approved_lessons
from oryveta_engine.evolve_runtime import EvolveRuntimeWorker, EvolveStageRejected

GOAL = "Extend make_str to accept a memoryview while preserving existing behavior."
RUN = "11111111-1111-4111-8111-111111111111"
TOKEN = "22222222-2222-4222-8222-222222222222"
WORK = "33333333-3333-4333-8333-333333333333"
PROJECT = "44444444-4444-4444-8444-444444444444"
SOURCE = "a" * 64
REVIEWER = {"reviewer_model": "qwen3:8b", "reviewer_digest": "d" * 64}
CANDIDATE_BYTES = b"PK\x03\x04 candidate archive bytes"
PATCH_BYTES = b"--- a/main.py\n+++ b/main.py\n"
CANDIDATE_SHA = hashlib.sha256(CANDIDATE_BYTES).hexdigest()
PATCH_SHA = hashlib.sha256(PATCH_BYTES).hexdigest()

REQUIREMENTS = {"goal": GOAL, "acceptance_criteria": ["A memoryview decodes as its bytes"],
                "constraints": ["str inputs keep their current result"]}


def future(seconds: int = 300) -> str:
    moment = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
    return moment.isoformat()


class StubClient:
    """Records every control-plane call and answers with canned rows."""

    def __init__(self, heartbeats=None, rows=None):
        self.calls: list[tuple[str, str, dict]] = []
        self.heartbeats = list(heartbeats or [])
        self.rows = dict(rows or {})

    def worker_user_id(self) -> str:
        return "worker-identity"

    def select(self, table, params):
        self.calls.append(("select", table, dict(params)))
        return self.rows.get(table, [])

    def rpc_row(self, name, payload):
        self.calls.append(("rpc", name, dict(payload)))
        if name == "heartbeat_evolve_run":
            if self.heartbeats:
                return self.heartbeats.pop(0)
            return {"lease_valid": True, "reason": None, "lease_expires_at": future()}
        if name == "record_evolve_stage":
            return {"id": "stage-row", "stage": payload["p_stage"], "replayed": False}
        return self.rows.get(name, {})

    def named(self, name: str) -> list[dict]:
        return [payload for kind, called, payload in self.calls
                if kind == "rpc" and called == name]


class StubStore:
    """An artifact store that records publications without any HTTP."""

    def __init__(self):
        self.published: list[tuple[str, str, int]] = []

    def publish(self, run_id, lease_token, kind, payload):
        digest = hashlib.sha256(payload).hexdigest()
        self.published.append((kind, digest, len(payload)))
        return {"kind": kind, "sha256": digest, "bytes": len(payload),
                "storage_path": f"{run_id}/{kind}/{digest}"}

    def close(self):
        return None

    def kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.published]


@pytest.fixture
def worker(tmp_path, coding_spec_data):
    config = tmp_path / "operator.json"
    config.write_text(json.dumps(coding_spec_data), encoding="utf-8")
    config.chmod(0o600)
    built = EvolveRuntimeWorker(
        client=StubClient(), project_id=PROJECT, config_path=config,
        work_root=tmp_path / "runs", max_rework=0, store=StubStore())
    return built


@pytest.fixture
def attempt(worker, tmp_path):
    evidence = runtime._private_directory(tmp_path / "evidence")
    sandbox = runtime._private_directory(tmp_path / "sandbox")
    source = evidence / "source.zip"
    source.write_bytes(b"PK\x03\x04 source archive bytes")
    return runtime._Attempt(
        claim={"run_id": RUN, "lease_token": TOKEN, "work_item_id": WORK, "attempt": 1,
               "max_attempts": 3, "lease_expires_at": future()},
        lease=future(), evidence=evidence, sandbox=sandbox, source_zip=source,
        source_sha256=SOURCE, config_sha256=worker.spec.digest, goal=GOAL,
        deadline=time.monotonic() + 600, tokens=worker.spec.limits.total_tokens,
        role_calls=48, index=EvidenceIndex(checks=frozenset()), lessons="")


def child_result(stage, artifact, *, verdict="pass", evidence_ids=None, findings=(),
                 produced=None, usage=None):
    return {"schema_version": 1, "stage": stage, "status": "ok", "error_code": None,
            "artifact": artifact,
            "review": {"verdict": verdict, "summary": "Reviewed the recorded evidence.",
                       "evidence_ids": list(evidence_ids or []), "findings": list(findings)},
            **REVIEWER, "measured": {}, "produced": dict(produced or {}),
            "usage": dict(usage or {"tokens": 1200, "role_calls": 2})}


def answer(worker, *results):
    """Replace the one seam that launches a supervised child."""
    queue = list(results)

    def supervise(claim, operation, directory, request, lease, seconds, *, phase=None):
        supervise.requests.append(request)
        supervise.phases.append(phase)
        return queue.pop(0)

    supervise.requests = []
    supervise.phases = []
    worker._supervise = supervise
    return supervise


def implementation_evidence(attempt):
    directory = runtime._private_directory(attempt.evidence / "produced")
    candidate = directory / "candidate.zip"
    patch = directory / "verified.patch"
    candidate.write_bytes(CANDIDATE_BYTES)
    patch.write_bytes(PATCH_BYTES)
    return {"candidate_path": str(candidate), "patch_path": str(patch)}


def record_requirements(worker, attempt):
    answer(worker, child_result("requirements", REQUIREMENTS,
                                evidence_ids=["artifact:" + digest_json(REQUIREMENTS)]))
    assert worker._stage(attempt, "requirements") is True


# -- fencing ---------------------------------------------------------------


def test_a_lost_lease_stops_a_stage_before_any_inference_is_spent(worker, attempt):
    worker.client.heartbeats = [{"lease_valid": False, "reason": "cancelled"}]
    seam = answer(worker)  # An empty queue: launching a child would raise.
    assert worker._stage(attempt, "requirements") is False
    assert seam.requests == []
    assert worker.client.named("record_evolve_stage") == []
    assert worker.store.published == []


def test_a_lease_lost_while_a_child_runs_publishes_nothing(worker, attempt):
    answer(worker, None)  # The supervisor reports a fenced, terminated child.
    assert worker._stage(attempt, "implementation") is False
    assert worker.client.named("record_evolve_stage") == []
    assert worker.store.published == []


def test_a_fenced_attempt_is_not_reported_as_a_failure(worker, attempt):
    worker.client.heartbeats = [{"lease_valid": False, "reason": "worker_not_registered"}]
    answer(worker)
    assert worker._stage(attempt, "requirements") is False
    assert worker.client.named("fail_evolve_run") == []
    assert worker.client.named("finish_evolve_run") == []


# -- recorded identity -----------------------------------------------------


def test_a_recorded_stage_is_bound_to_the_pinned_source_and_configuration(worker, attempt):
    record_requirements(worker, attempt)
    payload = worker.client.named("record_evolve_stage")[0]["p_payload"]
    assert payload["source_sha256"] == SOURCE
    assert payload["config_sha256"] == worker.spec.digest
    assert payload["artifact_sha256"] == digest_json(REQUIREMENTS)
    assert payload["review"]["reviewer_digest"] == REVIEWER["reviewer_digest"]
    assert attempt.recorded["requirements"] == payload


def test_a_restated_goal_is_refused_rather_than_recorded(worker, attempt):
    answer(worker, child_result("requirements", {**REQUIREMENTS, "goal": GOAL + " Also refactor."},
                                evidence_ids=["stage:requirements"]))
    with pytest.raises(CodingError, match="goal"):
        worker._stage(attempt, "requirements")
    assert worker.client.named("record_evolve_stage") == []


def test_a_review_citing_a_later_stage_is_refused_rather_than_recorded(worker, attempt):
    answer(worker, child_result("requirements", REQUIREMENTS,
                                evidence_ids=["stage:verification"]))
    with pytest.raises(CodingError, match="evidence"):
        worker._stage(attempt, "requirements")
    assert worker.client.named("record_evolve_stage") == []


def test_a_check_cannot_be_cited_before_a_verification_stage_reports_it(worker, attempt):
    name = worker.spec.development_checks[0].name
    answer(worker, child_result("requirements", REQUIREMENTS, evidence_ids=[f"check:{name}"]))
    with pytest.raises(CodingError, match="evidence"):
        worker._stage(attempt, "requirements")
    assert worker.client.named("record_evolve_stage") == []


# -- the candidate ---------------------------------------------------------


def test_the_recorded_candidate_identity_comes_from_the_uploaded_bytes(worker, attempt):
    record_requirements(worker, attempt)
    plan = {"steps": ["Extend the decode path"], "allowed_paths": list(worker.spec.write_paths),
            "risks": []}
    answer(worker, child_result("plan", plan, evidence_ids=["stage:requirements"]))
    assert worker._stage(attempt, "plan") is True
    produced = implementation_evidence(attempt)
    artifact = {"candidate_sha256": CANDIDATE_SHA, "patch_sha256": PATCH_SHA,
                "changed_paths": ["main.py"], "summary": "Decodes a memoryview as bytes."}
    answer(worker, child_result("implementation", artifact, produced=produced,
                                evidence_ids=["artifact:" + CANDIDATE_SHA,
                                              "artifact:" + PATCH_SHA]))
    assert worker._stage(attempt, "implementation") is True
    # Registered before the stage row exists, so a review can cite them and a
    # reader can never resolve a record to bytes that were never stored.
    assert worker.store.kinds() == ["candidate", "patch"]
    payload = worker.client.named("record_evolve_stage")[-1]["p_payload"]
    assert payload["artifact_sha256"] == CANDIDATE_SHA
    assert attempt.candidate_sha256 == CANDIDATE_SHA


@pytest.mark.parametrize("field,value", [
    ("candidate_sha256", "e" * 64),
    ("patch_sha256", "e" * 64),
])
def test_a_reported_digest_that_is_not_the_produced_bytes_is_refused(worker, attempt, field,
                                                                     value):
    produced = implementation_evidence(attempt)
    artifact = {"candidate_sha256": CANDIDATE_SHA, "patch_sha256": PATCH_SHA,
                "changed_paths": ["main.py"], "summary": "Decodes a memoryview as bytes.",
                field: value}
    answer(worker, child_result("implementation", artifact, produced=produced,
                                evidence_ids=["artifact:" + CANDIDATE_SHA]))
    with pytest.raises(CodingError, match="candidate_identity_conflict|produced archives"):
        worker._stage(attempt, "implementation")
    assert worker.store.published == []
    assert worker.client.named("record_evolve_stage") == []


def test_a_later_stage_cannot_name_a_different_candidate(worker, attempt):
    attempt.candidate_sha256 = CANDIDATE_SHA
    attempt.index.add_artifact(CANDIDATE_SHA)
    verification = {"candidate_sha256": "e" * 64,
                    "checks": [{"name": "increment", "passed": True}],
                    "baseline_reproduced": True, "preservation_passed": True,
                    "verification": "passed"}
    answer(worker, child_result("verification", verification,
                                evidence_ids=["artifact:" + CANDIDATE_SHA]))
    with pytest.raises(CodingError, match="candidate"):
        worker._stage(attempt, "verification")
    assert worker.client.named("record_evolve_stage") == []


# -- refusals --------------------------------------------------------------


def test_a_terminal_review_refusal_is_recorded_and_then_fails_the_run(worker, attempt):
    blocking = {"severity": "blocking", "detail": "A criterion is not testable.",
                "evidence_id": "stage:requirements"}
    answer(worker, child_result("requirements", REQUIREMENTS, verdict="rework",
                                evidence_ids=["stage:requirements"], findings=[blocking]))
    with pytest.raises(EvolveStageRejected) as refused:
        worker._stage(attempt, "requirements")
    assert refused.value.code == "review_rejected"
    payload = worker.client.named("record_evolve_stage")[0]["p_payload"]
    assert payload["review"]["verdict"] == "rework"
    assert payload["review"]["findings"] == [blocking]
    # The refusal is retained as evidence, because the findings are the most
    # useful thing the attempt produced and the failure-learning branch reasons
    # about them. Retaining it is not treating it as a completed step.
    assert attempt.rejected == "requirements"
    assert attempt.recorded["requirements"] == payload
    assert attempt.index.stages == {"requirements"}
    assert attempt.index.artifacts == set()


def test_a_refused_implementation_does_not_spend_the_single_candidate_slot(worker, attempt):
    produced = implementation_evidence(attempt)
    artifact = {"candidate_sha256": CANDIDATE_SHA, "patch_sha256": PATCH_SHA,
                "changed_paths": ["main.py"], "summary": "Decodes a memoryview as bytes."}
    answer(worker, child_result("implementation", artifact, verdict="escalate", produced=produced,
                                evidence_ids=["artifact:" + CANDIDATE_SHA],
                                findings=[{"severity": "blocking",
                                           "detail": "The change breaks str inputs.",
                                           "evidence_id": "artifact:" + CANDIDATE_SHA}]))
    with pytest.raises(EvolveStageRejected):
        worker._stage(attempt, "implementation")
    assert worker.store.published == []
    recorded = worker.client.named("record_evolve_stage")[0]["p_payload"]
    assert recorded["artifact_sha256"] == CANDIDATE_SHA
    assert attempt.candidate_sha256 == ""


def test_an_audit_cannot_pass_while_naming_process_violations(worker, attempt):
    attempt.candidate_sha256 = CANDIDATE_SHA
    attempt.index.add_artifact(CANDIDATE_SHA)
    audit = {"candidate_sha256": CANDIDATE_SHA,
             "required_stages": ["requirements", "plan", "implementation", "verification"],
             "violations": ["The plan stage was never reviewed."],
             "summary": "The record is incomplete."}
    answer(worker, child_result("audit", audit, evidence_ids=["artifact:" + CANDIDATE_SHA]))
    with pytest.raises(CodingError, match="process_rejected|violations"):
        worker._stage(attempt, "audit")
    assert worker.client.named("record_evolve_stage") == []


def test_a_stage_child_failure_is_a_durable_code_and_not_a_passing_review(worker, attempt):
    answer(worker, {"schema_version": 1, "stage": "implementation", "status": "failed",
                    "error_code": "model_unavailable", "artifact": None, "review": None,
                    "measured": {}, "produced": {}, "usage": {"tokens": 0, "role_calls": 0}})
    with pytest.raises(EvolveStageRejected) as refused:
        worker._stage(attempt, "implementation")
    assert refused.value.code == "model_unavailable"
    assert worker.client.named("record_evolve_stage") == []


@pytest.mark.parametrize("code", sorted(NONRETRYABLE_CODES))
def test_a_verdict_about_the_work_is_reported_with_a_nonretryable_code(code):
    assert runtime.CODE_PATTERN.fullmatch(code)
    assert runtime.evolve_error_code(EvolveStageRejected(code, "refused")) == code


def test_an_unexpected_failure_never_becomes_a_review_rejection():
    assert runtime.evolve_error_code(RuntimeError("boom")) == "worker_error"
    assert runtime.evolve_error_code(CodingError("Weird Code", "x")) == "worker_error"
    assert runtime.evolve_error_code(runtime.EvolveTimeout("late")) == "evolve_timeout"


# -- the shared aggregate budget ------------------------------------------


def test_every_stage_draws_on_one_aggregate_budget(worker, attempt):
    record_requirements(worker, attempt)
    assert attempt.tokens_spent == 1200
    assert attempt.calls_spent == 2
    plan = {"steps": ["Extend the decode path"], "allowed_paths": list(worker.spec.write_paths),
            "risks": []}
    seam = answer(worker, child_result("plan", plan, evidence_ids=["stage:requirements"],
                                       usage={"tokens": 900, "role_calls": 2}))
    assert worker._stage(attempt, "plan") is True
    # The second stage was offered what the first one left, not a fresh budget.
    offered = seam.requests[0]["budget"]
    assert offered["tokens"] == worker.spec.limits.total_tokens - 1200
    assert offered["role_calls"] == 46
    assert (attempt.tokens_spent, attempt.calls_spent) == (2100, 4)


def test_a_stage_child_is_never_offered_the_citations_it_has_not_earned(worker, attempt):
    record_requirements(worker, attempt)
    plan = {"steps": ["Extend the decode path"], "allowed_paths": list(worker.spec.write_paths),
            "risks": []}
    seam = answer(worker, child_result("plan", plan, evidence_ids=["stage:requirements"]))
    assert worker._stage(attempt, "plan") is True
    catalogue = seam.requests[0]["catalogue"]
    assert catalogue == ["stage:requirements", "artifact:" + digest_json(REQUIREMENTS)]
    assert not any(reference.startswith("check:") for reference in catalogue)


# -- secrecy of the worker's own identity ---------------------------------


def test_a_stage_child_environment_carries_no_session_or_credential(worker, tmp_path,
                                                                    monkeypatch):
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "docker"))
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")
    monkeypatch.setenv("ORYVETA_WORKER_BOOTSTRAP", "bootstrap-secret")
    environment = worker.child_environment(tmp_path)
    rendered = json.dumps(environment)
    # The approved Docker pointer and a usable PATH survive, because a named
    # context has to resolve; nothing else from the worker's world does.
    assert environment["DOCKER_CONFIG"] == str(tmp_path / "docker")
    assert environment["PATH"] and environment["TMPDIR"] == str(tmp_path)
    for leaked in ("service-role-secret", "bootstrap-secret", "proxy.invalid",
                   "SUPABASE_SERVICE_ROLE_KEY", "HTTPS_PROXY", TOKEN):
        assert leaked not in rendered
    assert set(environment) == {"PATH", "HOME", "DOCKER_CONFIG", "PYTHONPATH",
                                "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING", "TMPDIR",
                                "LC_ALL", "LANG"}


def test_a_stage_child_is_told_a_configuration_path_and_never_a_protected_value(
        tmp_path, coding_spec_data):
    # A distinctive expected output, so its absence from the request is a fact
    # rather than a coincidence of short JSON values.
    marker = "PROTECTED-EXPECTED-9f3c1a"
    coding_spec_data["acceptance_checks"][0]["expected_json"] = marker
    config = tmp_path / "operator.json"
    config.write_text(json.dumps(coding_spec_data), encoding="utf-8")
    built = EvolveRuntimeWorker(client=StubClient(), project_id=PROJECT, config_path=config,
                                work_root=tmp_path / "runs", max_rework=0, store=StubStore())
    assert any(check.expected_json == marker for check in built.spec.acceptance_checks)
    evidence = runtime._private_directory(tmp_path / "evidence")
    source = evidence / "source.zip"
    source.write_bytes(b"PK\x03\x04 source archive bytes")
    state = runtime._Attempt(
        claim={"run_id": RUN, "lease_token": TOKEN, "work_item_id": WORK, "attempt": 1,
               "max_attempts": 3, "lease_expires_at": future()},
        lease=future(), evidence=evidence,
        sandbox=runtime._private_directory(tmp_path / "sandbox"), source_zip=source,
        source_sha256=SOURCE, config_sha256=built.spec.digest, goal=GOAL,
        deadline=time.monotonic() + 600, tokens=built.spec.limits.total_tokens, role_calls=48,
        index=EvidenceIndex(checks=frozenset()), lessons="")
    seam = answer(built, child_result("requirements", REQUIREMENTS,
                                      evidence_ids=["artifact:" + digest_json(REQUIREMENTS)]))
    assert built._stage(state, "requirements") is True
    request = json.dumps(seam.requests[0])
    # The trusted specification is named by path and read by the child itself;
    # the expected outputs, the check names and this worker's lease never
    # travel in the request, so they cannot reach a prompt or a container.
    assert seam.requests[0]["config_path"] == str(built.config_path)
    assert marker not in request
    assert "expected_json" not in request
    for check in built.spec.development_checks + built.spec.acceptance_checks:
        assert check.name not in request
    assert TOKEN not in request and "lease_token" not in request
    assert "p_lease_token" not in request


# -- scoped retrieval of approved memory ----------------------------------


def test_only_this_snapshot_and_configuration_can_retrieve_an_approved_lesson(worker):
    lesson = {"summary": "Decode a buffer through tobytes.", "applicability": "memoryview inputs",
              "evidence_ids": ["stage:verification"], "counterexamples": []}
    client = StubClient(rows={"evolve_lessons": [
        {"id": "l1", "lesson_index": 0, "lesson": lesson, "created_at": future()},
        {"id": "l2", "lesson_index": 1, "lesson": {"summary": "incomplete"},
         "created_at": future()},
        {"id": "l3", "lesson_index": 2, "lesson": "not an object", "created_at": future()},
    ]})
    retrieved = approved_lessons(client, PROJECT, source_sha256=SOURCE,
                                 config_sha256=worker.spec.digest)
    # A row that does not satisfy the lesson contract is dropped, not repaired.
    assert retrieved == [lesson]
    _, table, params = client.calls[0]
    assert table == "evolve_lessons"
    assert params["project_id"] == f"eq.{PROJECT}"
    assert params["status"] == "eq.approved"
    assert params["source_sha256"] == f"eq.{SOURCE}"
    assert params["config_sha256"] == f"eq.{worker.spec.digest}"


def test_retrieval_is_bounded_and_cannot_be_widened_by_its_caller(worker):
    client = StubClient()
    approved_lessons(client, PROJECT, source_sha256=SOURCE, config_sha256=worker.spec.digest,
                     limit=5000)
    assert client.calls[0][2]["limit"] == "5"


# -- the whole attempt -----------------------------------------------------


def test_a_whole_attempt_records_every_stage_in_order_and_nothing_else(worker, tmp_path):
    """One attempt, from the pinned snapshot to awaiting human approval.

    The source fetch and the supervised children are the two seams that reach
    outside this process; everything between them is the worker's own ordering,
    registration and completion logic.
    """
    worker.client.rows["finish_evolve_run"] = {"accepted": True, "reason": "ok",
                                               "work_item_status": "awaiting_approval"}
    payload = b"PK\x03\x04 source archive bytes"
    source_sha = hashlib.sha256(payload).hexdigest()
    worker._pinned_source = lambda claim: ("github.com/pallets/click", payload, "c" * 40,
                                           source_sha)
    produced = tmp_path / "produced"
    produced.mkdir()
    (produced / "candidate.zip").write_bytes(CANDIDATE_BYTES)
    (produced / "verified.patch").write_bytes(PATCH_BYTES)
    (produced / "receipt.json").write_text(json.dumps(
        {"schema_version": 1, "status": "needs_review", "verification": "passed",
         "candidate_archive_sha256": CANDIDATE_SHA}), encoding="utf-8")
    (produced / "events.jsonl").write_text(json.dumps(
        {"sequence": 0, "kind": "run_started", "time": "2026-11-11T10:00:00Z",
         "run_id": RUN, "mode": "repair"}) + "\n", encoding="utf-8")
    evidence = {"candidate_path": str(produced / "candidate.zip"),
                "patch_path": str(produced / "verified.patch"),
                "receipt_path": str(produced / "receipt.json"),
                "trace_path": str(produced / "events.jsonl")}
    names = [check.name for check in
             worker.spec.development_checks + worker.spec.acceptance_checks]
    staged = {
        "requirements": (REQUIREMENTS, ["artifact:" + digest_json(REQUIREMENTS)], {}),
        "plan": ({"steps": ["Extend the decode path"],
                  "allowed_paths": list(worker.spec.write_paths), "risks": []},
                 ["stage:requirements"], {}),
        "implementation": ({"candidate_sha256": CANDIDATE_SHA, "patch_sha256": PATCH_SHA,
                            "changed_paths": ["main.py"], "summary": "Decodes a memoryview."},
                           ["artifact:" + CANDIDATE_SHA, "artifact:" + PATCH_SHA], evidence),
        "verification": ({"candidate_sha256": CANDIDATE_SHA,
                          "checks": [{"name": name, "passed": True} for name in names],
                          "baseline_reproduced": True, "preservation_passed": True,
                          "verification": "passed"},
                         ["stage:implementation", "check:" + names[0]], evidence),
        "audit": ({"candidate_sha256": CANDIDATE_SHA,
                   "required_stages": list(runtime.STAGE_ORDER[:4]),
                   "violations": [], "summary": "Every required stage is present."},
                  ["stage:verification"], {}),
        "learning": ({"candidate_sha256": CANDIDATE_SHA,
                      "lessons": [{"summary": "Decode a buffer through tobytes.",
                                   "applicability": "memoryview inputs",
                                   "evidence_ids": ["stage:verification"],
                                   "counterexamples": []}]}, ["stage:audit"], {}),
        "learning_review": ({"candidate_sha256": CANDIDATE_SHA,
                             "decisions": [{"index": 0, "verdict": "pass",
                                            "reason": "Supported by verification."}]},
                            ["stage:learning"], {}),
    }

    def supervise(claim, operation, directory, request, lease, seconds, *, phase=None):
        supervise.requests.append(request)
        artifact, citations, evidence_paths = staged[operation]
        return child_result(operation, artifact, evidence_ids=citations,
                            produced=evidence_paths)

    supervise.requests = []
    worker._supervise = supervise
    worker._evolve({"run_id": RUN, "lease_token": TOKEN, "work_item_id": WORK, "attempt": 1,
                    "max_attempts": 3, "lease_expires_at": future(), "goal": GOAL,
                    "source_owner": "pallets", "source_repo": "click",
                    "source_url": "https://github.com/pallets/click"},
                   runtime._private_directory(tmp_path / "run"), runtime._Progress())
    assert [call["p_stage"] for call in worker.client.named("record_evolve_stage")] \
        == list(runtime.STAGE_ORDER)
    # Exactly one candidate, and no artifact outside the four authorized kinds.
    assert worker.store.kinds() == ["candidate", "patch", "receipt", "trace"]
    assert len(worker.client.named("finish_evolve_run")) == 1
    assert worker.client.named("fail_evolve_run") == []
    phases = [call["p_phase"] for call in worker.client.named("heartbeat_evolve_run")
              if call["p_phase"]]
    assert phases[0] == "claimed" and phases[-1] == "awaiting_approval"
    # Every stage payload is bound to the same pinned snapshot and configuration.
    for call in worker.client.named("record_evolve_stage"):
        assert call["p_payload"]["source_sha256"] == source_sha
        assert call["p_payload"]["config_sha256"] == worker.spec.digest


def test_the_audit_can_cite_the_receipt_and_trace_because_they_are_registered_first(
        worker, tmp_path):
    test_a_whole_attempt_records_every_stage_in_order_and_nothing_else(worker, tmp_path)
    audit_request = next(request for request in worker._supervise.requests
                         if request["stage"] == "audit")
    registered = {digest for _, digest, _ in worker.store.published}
    cited = {reference.removeprefix("artifact:") for reference in audit_request["catalogue"]
             if reference.startswith("artifact:")}
    assert registered <= cited
    assert all(f"check:{check.name}" in audit_request["catalogue"]
               for check in worker.spec.development_checks)


# -- the failed-run diagnostic report -------------------------------------

# The reviewer identity the trusted configuration pins. A failure review that
# reports any other identity was not performed by the pinned reviewer.
PINNED_REVIEWER = {"reviewer_model": "qwen3:8b", "reviewer_digest": "a" * 64}
LESSON = {"summary": "A memoryview decode needs its own regression check.",
          "applicability": "buffer inputs to make_str",
          "evidence_ids": ["failure:verification_failed", "check:increment"],
          "counterexamples": ["plain str inputs"]}
DECISION = {"index": 0, "verdict": "pass", "reason": "The failing check supports it."}
# A distinctive expected output, so its absence from a report is a fact rather
# than a coincidence of short JSON values.
PROTECTED_OUTPUT = "PROTECTED-EXPECTED-9f3c1a"


def learning_result(lessons=(), decisions=(), *, usage=None, **overrides):
    """What the supervised failure-learning child reports to the worker."""
    return {"schema_version": 1, "stage": runtime.FAILURE_LEARNING, "status": "ok",
            "error_code": None, "lessons": [dict(item) for item in lessons],
            "decisions": [dict(item) for item in decisions], **PINNED_REVIEWER,
            "usage": dict(usage or {"tokens": 800, "role_calls": 2}), **overrides}


def check_report(attempt, relative, rows, *, stage="verification", round_index=0):
    """Write one controller-shaped check report into the private evidence tree."""
    path = attempt.evidence / f"{stage}-{round_index}" / relative
    runtime._private_directory(path.parent)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def failed_verification(attempt, **kwargs):
    """The real file the independent verifier leaves when a check fails."""
    return check_report(attempt, "verify/verification.json", [
        {"name": "increment", "kind": "regression", "passed": False, "exit_code": 1,
         "json_valid": True, "stdout": PROTECTED_OUTPUT, "stderr": "", "duration_seconds": 0.4},
        {"name": "empty", "kind": "preserve", "passed": True, "exit_code": 0,
         "json_valid": True, "stdout": PROTECTED_OUTPUT, "stderr": "", "duration_seconds": 0.3},
    ], **kwargs)


def at(attempt, phase):
    return runtime._Progress(phase=phase, attempt=attempt)


def test_a_failed_verification_is_reported_with_the_checks_that_actually_failed(worker, attempt):
    failed_verification(attempt)
    answer(worker, learning_result([LESSON], [DECISION]))
    report = worker._failure_report(attempt.claim, at(attempt, "verification"),
                                    "verification_failed")
    # The failure is observable as outcomes, not as an opaque code.
    assert report["checks"] == [{"name": "increment", "passed": False},
                                {"name": "empty", "passed": True}]
    assert report["error_code"] == "verification_failed"
    assert report["failed_stage"] == "verification"
    assert report["source_sha256"] == SOURCE
    assert report["config_sha256"] == worker.spec.digest
    assert (report["learning_status"], report["learning_reason"]) == ("reviewed", "completed")
    assert report["lessons"] == [LESSON] and report["decisions"] == [DECISION]
    assert report["reviewer_model"] == "qwen3:8b" and report["reviewer_digest"] == "a" * 64
    # A passing check's output is the operator's protected expected output, and
    # a report carries outcomes rather than anything a check printed.
    rendered = json.dumps(report)
    assert PROTECTED_OUTPUT not in rendered
    for leaked in ("stdout", "exit_code", "duration_seconds", str(attempt.evidence), TOKEN):
        assert leaked not in rendered


def test_a_failure_report_cannot_name_a_candidate_or_a_passing_verification(worker, attempt):
    failed_verification(attempt)
    attempt.candidate_sha256 = CANDIDATE_SHA
    answer(worker, learning_result())
    report = worker._failure_report(attempt.claim, at(attempt, "verification"),
                                    "verification_failed")
    # There is no approvable candidate and no successful stage to point at, so
    # the report has nowhere to claim either.
    assert CANDIDATE_SHA not in json.dumps(report)
    assert set(report) == {"schema_version", "error_code", "failed_stage", "source_sha256",
                           "config_sha256", "checks", "learning_status", "learning_reason",
                           "lessons", "decisions", "reviewer_model", "reviewer_digest"}
    assert worker.client.named("record_evolve_stage") == []
    assert worker.store.published == []


def test_a_verification_failure_that_observed_no_failing_check_is_not_reported(worker, attempt):
    # Every check passing contradicts the code this run is failing with, so
    # there is nothing honest to record and no inference to spend on it: the
    # report exists to point at the check that failed.
    check_report(attempt, "verify/verification.json", [
        {"name": "increment", "kind": "regression", "passed": True}])
    seam = answer(worker)
    worker._record_failure_report(attempt.claim, at(attempt, "verification"),
                                  "verification_failed")
    assert worker.client.named("record_evolve_failure_report") == []
    assert seam.requests == []


def test_the_latest_observation_is_what_a_failure_reports(worker, attempt):
    # The editing loop's own earlier run is real evidence, but the independent
    # verification that refused the candidate is the later and closer one.
    check_report(attempt, "repair/verification.json",
                 [{"name": "increment", "kind": "regression", "passed": True}],
                 stage="implementation")
    failed_verification(attempt)
    answer(worker, learning_result())
    report = worker._failure_report(attempt.claim, at(attempt, "verification"),
                                    "verification_failed")
    assert {check["name"]: check["passed"] for check in report["checks"]} \
        == {"increment": False, "empty": True}


def test_a_baseline_that_did_not_reproduce_is_reported_from_its_own_evidence(worker, attempt):
    check_report(attempt, "verify/baseline.json", [
        {"name": "increment", "kind": "regression", "passed": True, "stdout": PROTECTED_OUTPUT}])
    answer(worker, learning_result())
    report = worker._failure_report(attempt.claim, at(attempt, "verification"), "not_reproduced")
    assert report["checks"] == [{"name": "increment", "passed": True}]
    assert report["error_code"] == "not_reproduced"


@pytest.mark.parametrize("code,reason", [
    ("model_unavailable", "model_unavailable"),
    ("model_changed", "model_unavailable"),
    ("provider_contract", "model_unavailable"),
    ("token_budget", "budget_exhausted"),
    ("role_budget", "budget_exhausted"),
    ("evolve_timeout", "budget_exhausted"),
    ("cancelled", "worker_interrupted"),
    ("worker_credentials_rejected", "authority_lost"),
])
def test_a_failure_the_model_or_budget_caused_spends_no_further_inference(worker, attempt, code,
                                                                         reason):
    seam = answer(worker)  # An empty queue: launching a child would raise.
    report = worker._failure_report(attempt.claim, at(attempt, "implementation"), code)
    assert (report["learning_status"], report["learning_reason"]) == ("unavailable", reason)
    assert report["lessons"] == [] and report["decisions"] == []
    # Honest unavailability still names the reviewer the operator pinned, and
    # states plainly that it did not run.
    assert report["reviewer_model"] == "qwen3:8b"
    assert seam.requests == []


@pytest.mark.parametrize("spend", ["tokens", "role_calls", "time"])
def test_an_exhausted_aggregate_allowance_cannot_fund_failure_learning(worker, attempt, spend):
    if spend == "tokens":
        attempt.tokens_spent = attempt.tokens
    elif spend == "role_calls":
        attempt.calls_spent = attempt.role_calls
    else:
        attempt.deadline = time.monotonic() + 1
    seam = answer(worker)
    report = worker._failure_report(attempt.claim, at(attempt, "audit"), "process_rejected")
    assert (report["learning_status"], report["learning_reason"]) \
        == ("unavailable", "budget_exhausted")
    assert seam.requests == []


def test_a_run_that_never_fetched_its_source_admits_no_lesson(worker):
    seam = answer(worker)
    report = worker._failure_report(
        {"run_id": RUN, "lease_token": TOKEN, "work_item_id": WORK}, at(None, "fetching_source"),
        "source_fetch_failed")
    assert report["source_sha256"] is None
    assert (report["learning_status"], report["learning_reason"]) == ("unavailable", "no_source")
    assert report["checks"] == [] and report["lessons"] == []
    assert report["config_sha256"] == worker.spec.digest
    assert seam.requests == []


@pytest.mark.parametrize("pinned,claim_pin", [(True, None), (False, "c" * 40)])
def test_an_attempt_that_never_reached_the_pinned_snapshot_records_no_report(worker, pinned,
                                                                            claim_pin):
    # The run's own record already names a snapshot, from this attempt's pin or
    # from an earlier one, so `no_source` would contradict it and the attempt
    # has nothing else it observed.
    claim = {"run_id": RUN, "lease_token": TOKEN, "work_item_id": WORK,
             "pinned_source_commit": claim_pin}
    seam = answer(worker)
    worker._record_failure_report(
        claim, runtime._Progress(phase="fetching_source", pinned=pinned), "source_fetch_failed")
    assert worker.client.named("record_evolve_failure_report") == []
    assert seam.requests == []


def test_a_failure_after_a_passing_stage_adds_no_diagnostic_report(worker, attempt):
    record_requirements(worker, attempt)
    seam = answer(worker)
    # The requirements stage is on the record with a passing review, so this
    # failure happened after it rather than in it: there is no failing stage to
    # name and the record already holds what the attempt proved.
    worker._record_failure_report(attempt.claim, at(attempt, "requirements"),
                                  "worker_storage_error")
    assert worker.client.named("record_evolve_failure_report") == []
    assert seam.requests == []


def test_an_attempt_that_lost_its_lease_records_no_report_and_no_inference(worker, attempt):
    worker.client.heartbeats = [{"lease_valid": False, "reason": "cancelled"}]
    seam = answer(worker)
    worker._record_failure_report(attempt.claim, at(attempt, "implementation"), "review_rejected")
    # The run is no longer this attempt's to record anything for; the control
    # plane's own terminal record is the only honest one left.
    assert worker.client.named("record_evolve_failure_report") == []
    assert seam.requests == []


def test_a_lease_lost_while_learning_runs_records_nothing(worker, attempt):
    answer(worker, None)  # The supervisor reports a fenced, terminated child.
    worker._record_failure_report(attempt.claim, at(attempt, "verification"), "review_rejected")
    assert worker.client.named("record_evolve_failure_report") == []


def test_failure_learning_is_not_a_stage_and_leaves_the_phase_untouched(worker, attempt):
    answer(worker, learning_result())
    seam = worker._supervise
    worker._failure_report(attempt.claim, at(attempt, "audit"), "process_rejected")
    assert seam.requests[0]["stage"] == runtime.FAILURE_LEARNING
    assert runtime.FAILURE_LEARNING not in runtime.STAGE_ORDER
    # Nothing is recorded as a stage, and the run's last phase is left exactly
    # where the failure left it.
    assert worker.client.named("record_evolve_stage") == []
    assert seam.phases == [None]
    assert all(not call["p_phase"] for call in worker.client.named("heartbeat_evolve_run"))


def test_failure_learning_is_offered_only_what_the_attempt_left_of_one_ledger(worker, attempt):
    attempt.tokens_spent = 4000
    attempt.calls_spent = 9
    answer(worker, learning_result(usage={"tokens": 700, "role_calls": 2}))
    seam = worker._supervise
    worker._failure_report(attempt.claim, at(attempt, "audit"), "process_rejected")
    offered = seam.requests[0]["budget"]
    assert offered["tokens"] == attempt.tokens - 4000
    assert offered["role_calls"] == attempt.role_calls - 9
    # And what it spent is charged to the same ledger, not to a second one.
    assert (attempt.tokens_spent, attempt.calls_spent) == (4700, 11)
    assert seam.requests[0]["deadline_seconds"] <= worker.spec.limits.wall_seconds


def test_a_refused_review_is_the_evidence_a_failure_learns_from(worker, attempt):
    blocking = {"severity": "blocking", "detail": "A criterion is not testable.",
                "evidence_id": "stage:requirements"}
    answer(worker, child_result("requirements", REQUIREMENTS, verdict="rework",
                                evidence_ids=["stage:requirements"], findings=[blocking]))
    with pytest.raises(EvolveStageRejected):
        worker._stage(attempt, "requirements")
    lesson = {**LESSON, "evidence_ids": ["stage:requirements", "failure:review_rejected"]}
    answer(worker, learning_result([lesson], [DECISION]))
    seam = worker._supervise
    report = worker._failure_report(attempt.claim, at(attempt, "requirements"), "review_rejected")
    request = seam.requests[0]
    # The refusing review and its findings are what the extraction reasons
    # about, and the refusal itself is citable.
    assert request["prior"]["requirements"]["review"]["verdict"] == "rework"
    assert request["prior"]["requirements"]["review"]["findings"] == [blocking]
    assert request["catalogue"] == ["stage:requirements", "failure:review_rejected"]
    assert "no candidate is approvable" in request["outcome"]
    assert "requirements review refused it" in request["outcome"]
    assert report["lessons"] == [lesson]


def test_a_failure_lesson_citing_evidence_this_run_does_not_have_is_refused(worker, attempt):
    failed_verification(attempt)
    # `stage:audit` is a real stage name this attempt never recorded, and the
    # other citation is some other run's failure.
    answer(worker, learning_result([{**LESSON, "evidence_ids": ["stage:audit",
                                                               "failure:no_change"]}],
                                   [DECISION]))
    report = worker._failure_report(attempt.claim, at(attempt, "verification"),
                                    "verification_failed")
    assert (report["learning_status"], report["learning_reason"]) \
        == ("unavailable", "extraction_failed")
    assert report["lessons"] == [] and report["decisions"] == []
    # The observable failure survives: only the unsupported lessons are dropped.
    assert report["checks"] == [{"name": "increment", "passed": False},
                                {"name": "empty", "passed": True}]


@pytest.mark.parametrize("identity", [
    {"reviewer_digest": "d" * 64},
    {"reviewer_model": "some-other-model"},
    {"reviewer_model": ""},
])
def test_a_review_by_a_model_this_worker_never_pinned_is_not_reviewed_learning(worker, attempt,
                                                                               identity):
    failed_verification(attempt)
    answer(worker, learning_result([LESSON], [DECISION], **identity))
    report = worker._failure_report(attempt.claim, at(attempt, "verification"),
                                    "verification_failed")
    assert (report["learning_status"], report["learning_reason"]) \
        == ("unavailable", "extraction_failed")
    assert report["lessons"] == []


def test_an_undecided_lesson_set_is_never_recorded_as_adjudicated(worker, attempt):
    failed_verification(attempt)
    answer(worker, learning_result([LESSON, {**LESSON, "summary": "A second note."}], [DECISION]))
    report = worker._failure_report(attempt.claim, at(attempt, "verification"),
                                    "verification_failed")
    assert (report["learning_status"], report["learning_reason"]) \
        == ("unavailable", "extraction_failed")


def test_extracting_nothing_is_a_reviewed_outcome_and_not_a_failure(worker, attempt):
    failed_verification(attempt)
    answer(worker, learning_result())
    report = worker._failure_report(attempt.claim, at(attempt, "verification"),
                                    "verification_failed")
    assert (report["learning_status"], report["learning_reason"]) == ("reviewed", "completed")
    assert report["lessons"] == [] and report["decisions"] == []


@pytest.mark.parametrize("code,reason", [
    ("learning_undecided", "extraction_failed"),
    ("stage_internal_error", "extraction_failed"),
    ("model_unavailable", "model_unavailable"),
    ("token_budget", "budget_exhausted"),
    ("cancelled", "worker_interrupted"),
])
def test_an_extraction_that_failed_is_recorded_honestly(worker, attempt, code, reason):
    failed_verification(attempt)
    answer(worker, {"schema_version": 1, "stage": runtime.FAILURE_LEARNING, "status": "failed",
                    "error_code": code, "lessons": None, "decisions": None,
                    "reviewer_model": None, "reviewer_digest": None,
                    "usage": {"tokens": 300, "role_calls": 1}})
    report = worker._failure_report(attempt.claim, at(attempt, "verification"),
                                    "verification_failed")
    assert (report["learning_status"], report["learning_reason"]) == ("unavailable", reason)
    # A failed extraction still spent what it spent.
    assert attempt.tokens_spent == 300


def test_the_report_is_recorded_before_the_run_is_failed(worker, attempt):
    failed_verification(attempt)
    worker.client.rows["record_evolve_failure_report"] = {"accepted": True, "reason": "ok"}
    worker.client.rows["fail_evolve_run"] = {"accepted": True, "reason": "ok",
                                             "retry_scheduled": False}
    answer(worker, learning_result([LESSON], [DECISION]))

    def evolve(claim, directory, progress):
        progress.phase = "verification"
        progress.attempt = attempt
        raise EvolveStageRejected("verification_failed", "a configured check did not pass")

    worker._evolve = evolve
    worker._execute(attempt.claim)
    recorded = [name for kind, name, _ in worker.client.calls if kind == "rpc"]
    assert recorded.index("record_evolve_failure_report") < recorded.index("fail_evolve_run")
    # The original code stays authoritative, and the report carries the same one.
    report = worker.client.named("record_evolve_failure_report")[0]
    assert report["p_report"]["error_code"] == "verification_failed"
    assert report["p_run_id"] == RUN and report["p_lease_token"] == TOKEN
    assert worker.client.named("fail_evolve_run")[0]["p_error_code"] == "verification_failed"
    assert worker.client.named("finish_evolve_run") == []


def test_an_unrecordable_report_never_masks_the_failure_it_describes(worker, attempt):
    failed_verification(attempt)

    def refuse(name, payload):
        worker.client.calls.append(("rpc", name, dict(payload)))
        if name == "record_evolve_failure_report":
            raise runtime.FactoryRuntimeError("the control plane refused the report")
        if name == "heartbeat_evolve_run":
            return {"lease_valid": True, "reason": None, "lease_expires_at": future()}
        return {}

    worker.client.rpc_row = refuse
    answer(worker, learning_result())
    worker._record_failure_report(attempt.claim, at(attempt, "verification"),
                                  "verification_failed")
    worker._report_failure(attempt.claim, "verification_failed")
    assert worker.client.named("fail_evolve_run")[0]["p_error_code"] == "verification_failed"
