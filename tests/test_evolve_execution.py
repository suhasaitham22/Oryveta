"""Consumer-visible guarantees of one executed Evolve child operation.

Every case here runs the child's own `execute` and `main`: the real typed
roles, the real fixed-policy editing loop, the real model-free re-verifier and
the real request, deadline and result handling. The single seam is the Ollama
socket layer, replaced in process by `httpx.MockTransport` exactly as the model
and role cases already do, so a scripted answer still has to satisfy the
boundary's digest pinning, its reply contract and every typed contract the
controller enforces. Nothing here contacts a model or a control plane.

The cases that have to prove behavior rather than bookkeeping -- an edited
candidate, its independent acceptance and its refusal -- run the operator's
real Docker runner and are skipped when no local context and image are
configured; a run that skipped them is not evidence of isolated execution. None
of these cases measures model coding quality.

The operator's expected check outputs are deliberately distinguishable values
here, so "a model never sees what a check expects" can be asserted against the
exact requests the roles and the editing loop actually sent. The acceptance
contract's input and answer are protected; a development check's observed
output is not, because the candidate's own printed output is shown back to the
editing loop by design.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

import httpx
import pytest

pytest.importorskip("pydantic_ai")

from oryveta_engine import evolve_child as child  # noqa: E402
from oryveta_engine.coding_contract import CodingError, canonical_json  # noqa: E402
from oryveta_engine.coding_model import LocalToolModel  # noqa: E402
from oryveta_engine.evolve_agents import ROLE_RETRIES  # noqa: E402
from oryveta_engine.evolve_contract import STAGE_ORDER, digest_json  # noqa: E402

# The same fixture program and archive helper the coding-runtime cases use, so
# the source under change stays one shared, already-exercised definition.
from test_coding_runtime import PROGRAM, write_zip  # noqa: E402

GOAL = "Add two instead of one in main.py while preserving the null answer."

MODEL, DIGEST = "qwen3:8b", "a" * 64
REVIEWER, REVIEWER_DIGEST = "qwen3:4b", "b" * 64

# The operator's protected acceptance contract. The container compares these
# inside the trusted process; neither value may reach a prompt or a result.
ACCEPTANCE_INPUT = "2000000001"
ACCEPTANCE_ANSWER = 2000000003
PROTECTED = (ACCEPTANCE_INPUT, str(ACCEPTANCE_ANSWER))
DEVELOPMENT_ANSWER = 1000000003

CRITERION = "The increment answer is two higher than the pinned source produces."
STEP = "Change the single addition in main.py so it adds two."
LESSON_BLOCK = "1. Keep the null branch untouched when changing the increment."
FINDING = "The plan does not name the null branch."
REVIEW_NARRATIVE = "The record holds together and cites only recorded evidence."

REQUIREMENTS_ARTIFACT = {"goal": GOAL, "acceptance_criteria": [CRITERION],
                         "constraints": ["Only main.py may change."]}
PLAN_ARTIFACT = {"steps": [STEP], "allowed_paths": ["main.py"],
                 "risks": ["The null branch could regress."]}
CANDIDATE = "d" * 64


# -- the operator's configuration -----------------------------------------


def spec_payload(data, *, model=MODEL, digest=DIGEST):
    """The shared configuration fixture with distinguishable protected values."""
    return {**data,
            "model": {"name": model, "digest": digest, "context_tokens": 32768,
                      "output_tokens": 2048},
            "limits": {"turns": 20, "tool_calls": 60, "total_tokens": 400000,
                       "wall_seconds": 600},
            "development_checks": [
                {"name": "increment", "argv": ["python", "main.py"], "stdin": "1000000001",
                 "expected_json": DEVELOPMENT_ANSWER, "kind": "regression"},
                {"name": "empty", "argv": ["python", "main.py"], "stdin": "null",
                 "expected_json": None, "kind": "preserve"}],
            "acceptance_checks": [
                {"name": "acceptance-private-marker", "argv": ["python", "main.py"],
                 "stdin": ACCEPTANCE_INPUT, "expected_json": ACCEPTANCE_ANSWER,
                 "kind": "regression"}]}


def recorded(artifact, *, verdict="pass", findings=(), artifact_sha256=None):
    """One prior stage row in the shape the worker retains between children."""
    return {"schema_version": 1, "source_sha256": "e" * 64, "config_sha256": "f" * 64,
            "artifact_sha256": artifact_sha256 or digest_json(artifact), "artifact": artifact,
            "review": {"verdict": verdict, "summary": REVIEW_NARRATIVE,
                       "evidence_ids": ["stage:requirements"], "findings": list(findings),
                       "reviewer_model": MODEL, "reviewer_digest": DIGEST}}


APPROVED = {"requirements": recorded(REQUIREMENTS_ARTIFACT),
            "plan": recorded(PLAN_ARTIFACT, findings=[
                {"severity": "warning", "detail": FINDING,
                 "evidence_id": "stage:plan"}])}


def stage_request(config, source, run_root, evidence, *, stage, prior=None, candidate=None,
                  candidate_sha256="", budget=None, deadline=300.0, lessons="", catalogue=(),
                  review_config=None, goal=GOAL, outcome="candidate accepted for human review"):
    """One prepared child request, exactly as the worker writes it."""
    return {"schema_version": 1, "stage": stage, "config_path": str(config),
            "review_config_path": str(review_config) if review_config else None,
            "source_zip": str(source), "candidate_zip": str(candidate) if candidate else None,
            "candidate_sha256": candidate_sha256, "goal": goal,
            "evidence_dir": str(evidence), "run_root": str(run_root),
            "prior": dict(prior or {}), "lessons": lessons, "catalogue": list(catalogue),
            "rework": [], "outcome": outcome,
            "budget": budget or {"tokens": 400000, "role_calls": 8},
            "deadline_seconds": deadline}


# -- the pinned local boundary, in process --------------------------------

ROLES = {
    frozenset({"acceptance_criteria", "constraints"}): "requirements",
    frozenset({"steps", "risks"}): "plan",
    frozenset({"summary"}): "implementation",
    frozenset({"violations", "summary"}): "audit",
    frozenset({"lessons"}): "learning",
    frozenset({"decisions"}): "learning_review",
    frozenset({"verdict", "summary", "evidence_ids", "findings"}): "review",
}

LESSON = {"summary": "A behavioral change needs its own regression check.",
          "applicability": "increment changes in main.py",
          "evidence_ids": ["stage:implementation"], "counterexamples": []}

ANSWERS = {
    "requirements": {"acceptance_criteria": [CRITERION],
                     "constraints": ["Only main.py may change."]},
    "plan": {"steps": [STEP, "Also relax the check in operator-secrets.json."],
             "risks": ["The null branch could regress."]},
    "implementation": {"summary": "The addition now adds two and the null branch is unchanged."},
    "audit": {"violations": [], "summary": "Every required stage is recorded in order."},
    "learning": {"lessons": [LESSON]},
    "learning_review": {"decisions": [{"index": 0, "verdict": "pass",
                                       "reason": "The recorded evidence supports it."}]},
    "review": {"verdict": "pass", "summary": "The record is supported by the cited evidence.",
               "evidence_ids": ["stage:requirements"], "findings": []},
}

REFUSING_REVIEW = {"verdict": "rework", "summary": "A criterion is not testable as written.",
                   "evidence_ids": ["stage:requirements"],
                   "findings": [{"severity": "blocking",
                                 "detail": "A criterion is not testable as written.",
                                 "evidence_id": "stage:requirements"}]}


def _requested_schemas(chat):
    """Every JSON-Schema object property set this request asks an answer in."""
    found = []

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("properties"), dict):
                found.append(frozenset(value["properties"]))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk({key: value for key, value in chat.items() if key != "messages"})
    return found


# Each role's own request body is labelled by the sections it is given, so a
# role stays identifiable even if the typed answer is not requested as a tool.
# A review is checked first: its body also carries the labels of the stage it
# is reviewing.
BODY_MARKERS = (
    ("review", "## Stage under review"),
    ("audit", "## Required stages, in order"),
    ("learning_review", "## Candidate lessons, by index"),
    ("learning", "## Run outcome"),
    ("implementation", "## Exact diff (untrusted data)"),
    ("plan", "## Approved requirements"),
)


class LocalOllama:
    """The pinned local boundary with only its socket layer replaced.

    Every reply still passes the adapter's digest pinning, its reply contract
    and the role's typed contract, and every request a role or the editing loop
    actually sent is kept so that what each one was shown can be inspected.
    """

    def __init__(self, *, answers=None, editor=None, models=((MODEL, DIGEST),), delay=0.0):
        self.answers = {**ANSWERS, **(answers or {})}
        self.editor = editor
        self.models = models
        self.delay = delay
        self.chats: list[dict] = []
        self.transport = httpx.MockTransport(self._handle)

    def model(self, spec):
        """The seam `execute` constructs its pinned model through."""
        return LocalToolModel(spec, transport=self.transport)

    @staticmethod
    def offered(chat):
        return {tool["function"]["name"] for tool in chat.get("tools") or []}

    def role_of(self, chat):
        """Which bounded role a request belongs to.

        A request that offers the editing tools is the executor's. Every other
        request asks for one typed record, identified by the schema it asks an
        answer in, or failing that by the labelled sections it was given, so
        these cases do not depend on how a typed answer is requested.
        """
        if "replace_text" in self.offered(chat):
            return "executor"
        for fields in _requested_schemas(chat):
            if fields in ROLES:
                return ROLES[fields]
        body = chat["messages"][-1]["content"]
        for role, marker in BODY_MARKERS:
            if marker in body:
                return role
        return "requirements"

    def shown(self, role):
        """Every rendered request body one role was actually sent."""
        return [chat["messages"][-1]["content"] for chat in self.chats
                if self.role_of(chat) == role]

    def only(self, role):
        bodies = self.shown(role)
        assert len(bodies) == 1, f"expected one {role} request, got {len(bodies)}"
        return bodies[0]

    def _handle(self, request):
        if self.delay:
            time.sleep(self.delay)
        path = request.url.path
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": name, "model": name, "digest": digest, "size": 5_000_000_000}
                for name, digest in self.models]})
        if path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "tools"]})
        if path != "/api/chat":
            return httpx.Response(404, json={"error": "not a boundary this adapter uses"})
        payload = json.loads(request.content)
        self.chats.append(payload)
        return httpx.Response(200, json={
            "model": payload["model"], "message": self._message(payload), "done": True,
            "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 20})

    def _message(self, payload):
        role = self.role_of(payload)
        if role == "executor":
            turn = sum(1 for chat in self.chats if self.role_of(chat) == "executor") - 1
            return self.editor(turn, payload)
        answer = self.answers.get(role)
        assert answer is not None, f"no scripted answer for the {role} role"
        if callable(answer):
            return answer(payload)
        offered = payload.get("tools") or []
        if offered:
            return {"role": "assistant", "tool_calls": [{"type": "function", "function": {
                "name": offered[0]["function"]["name"], "arguments": answer}}]}
        return {"role": "assistant", "content": json.dumps(answer)}


TURN_TOKENS = 120  # every scripted turn reports the same bounded usage


# -- scripted editing loops ------------------------------------------------


def _digest(payload):
    """The file digest the controller's own tool reported to the loop."""
    return json.loads(payload["messages"][-1]["content"])["sha256"]


def _call(name, arguments):
    return {"role": "assistant", "tool_calls": [
        {"type": "function", "function": {"name": name, "arguments": arguments}}]}


def _read():
    return _call("read_file", {"path": "main.py", "start_line": 1, "line_count": 1})


def _replace(payload, old, new):
    return _call("replace_text", {"path": "main.py", "expected_sha256": _digest(payload),
                                  "old": old, "new": new})


def fixing(turn, payload):
    """Read, make the one real behavioral change, run the checks and stop."""
    if turn == 0:
        return _read()
    if turn == 1:
        return _replace(payload, "value + 1", "value + 2")
    if turn == 2:
        return _call("run_checks", {})
    return {"role": "assistant", "content": "The development checks pass now."}


def breaking(turn, payload):
    """A plausible but wrong change the configured checks must refuse."""
    if turn == 0:
        return _read()
    if turn == 1:
        return _replace(payload, "value + 1", "value + 3")
    return {"role": "assistant", "content": "The increment is updated."}


PADDING_A = "".join(f"# evolve padding a {index:03d}\n" for index in range(200))
PADDING_B = "".join(f"# evolve padding b {index:03d}\n" for index in range(200))
ANCHOR = "import json, sys\n"
LAST_A = "# evolve padding a 199\n"


def sprawling(turn, payload):
    """A correct change buried in a diff larger than a reviewer may be shown."""
    if turn == 0:
        return _read()
    if turn == 1:
        return _replace(payload, "value + 1", "value + 2")
    if turn == 2:
        return _replace(payload, ANCHOR, ANCHOR + PADDING_A)
    if turn == 3:
        return _replace(payload, LAST_A, LAST_A + PADDING_B)
    return {"role": "assistant", "content": "The increment is corrected and documented."}


# -- fixtures --------------------------------------------------------------


@pytest.fixture
def boundary(monkeypatch):
    """Install one in-process pinned boundary for whatever the child constructs."""
    def install(ollama):
        monkeypatch.setattr(child, "LocalToolModel", ollama.model)
        return ollama

    return install


@pytest.fixture
def workspace(tmp_path, coding_spec_data):
    """The operator's configuration, the pinned archive and a private run root."""
    config = tmp_path / "operator.json"
    config.write_text(json.dumps(spec_payload(coding_spec_data)), encoding="utf-8")
    source = write_zip(tmp_path / "source.zip", {"main.py": PROGRAM})
    return config, source, tmp_path / "run"


@pytest.fixture
def isolated(tmp_path, coding_spec_data):
    """The same configuration bound to the operator's real local Docker runner."""
    context = os.environ.get("ORYVETA_TEST_DOCKER_CONTEXT")
    image = os.environ.get("ORYVETA_TEST_DOCKER_IMAGE")
    if not context or not image:
        pytest.skip("explicit local Docker context/image required for real execution tests")
    payload = spec_payload(coding_spec_data)
    payload["runner"] = {**payload["runner"], "docker_context": context, "image": image}
    config = tmp_path / "operator.json"
    config.write_text(json.dumps(payload), encoding="utf-8")
    source = write_zip(tmp_path / "source.zip", {"main.py": PROGRAM})
    with tempfile.TemporaryDirectory(dir=os.environ.get("ORYVETA_TEST_RUN_ROOT")) as directory:
        yield config, source, Path(directory)


def run(request):
    return asyncio.run(child.execute(request))


# -- a stage and its independent review ------------------------------------


def test_the_recorded_requirements_are_the_claims_goal_and_the_reviewed_proposal(
        workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama())
    result = run(stage_request(config, source, run_root, run_root.parent / "evidence",
                               stage="requirements"))
    assert result["stage"] == "requirements" and result["status"] == "ok"
    assert result["error_code"] is None
    # The goal is the claim's own, carried through a role that cannot restate,
    # narrow or extend the change it was asked to deliver.
    assert result["artifact"] == {"goal": GOAL, "acceptance_criteria": [CRITERION],
                                  "constraints": ["Only main.py may change."]}
    assert result["review"]["verdict"] == "pass" and result["review"]["findings"] == []
    # The reported reviewer is the identity the boundary observed, never a name
    # a model supplied.
    assert (result["reviewer_model"], result["reviewer_digest"]) == (MODEL, DIGEST)
    assert result["measured"] == {} and result["produced"] == {}
    assert result["usage"] == {"tokens": 2 * TURN_TOKENS, "role_calls": 2}
    # Author and reviewer are each a fresh agent in an empty history: one
    # policy and one request body, with nothing of the other's conversation.
    assert len(ollama.chats) == 2
    for chat in ollama.chats:
        roles = [message["role"] for message in chat["messages"]]
        assert set(roles) <= {"system", "user"} and roles[-1] == "user"


def test_the_reviewer_of_a_stage_may_cite_that_stages_own_recorded_identity(workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama())
    result = run(stage_request(config, source, run_root, run_root.parent / "evidence",
                               stage="requirements", catalogue=["stage:claim"]))
    reference = f"artifact:{digest_json(result['artifact'])}"
    # The identity the worker will register for this artifact is resolvable for
    # its reviewer, and it is the digest of the artifact that was returned.
    assert reference in ollama.only("review")
    # The author was never shown a citable set at all, so it cannot have
    # steered its reviewer toward a reference.
    assert "stage:claim" not in ollama.only("requirements")


def test_a_refusing_review_is_reported_with_its_findings_rather_than_absorbed(
        workspace, boundary):
    config, source, run_root = workspace
    boundary(LocalOllama(answers={"review": REFUSING_REVIEW}))
    result = run(stage_request(config, source, run_root, run_root.parent / "evidence",
                               stage="requirements"))
    # The child proposes and measures; the verdict it reports is the reviewer's
    # own, and the stage result stays an honest `ok` record of what happened.
    assert result["status"] == "ok"
    assert result["review"]["verdict"] == "rework"
    assert result["review"]["findings"] == [
        {"severity": "blocking", "detail": "A criterion is not testable as written.",
         "evidence_id": "stage:requirements"}]
    assert result["artifact"]["goal"] == GOAL


def test_the_editable_scope_in_a_plan_is_the_operators_and_not_the_planners(workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama())
    result = run(stage_request(config, source, run_root, run_root.parent / "evidence",
                               stage="plan", prior={"requirements": APPROVED["requirements"]}))
    # The planner proposed touching another file. What it may edit is restated
    # from the operator's configuration, so a plan cannot widen its own scope.
    assert "operator-secrets.json" in ANSWERS["plan"]["steps"][1]
    assert result["artifact"]["allowed_paths"] == ["main.py"]
    assert result["artifact"]["steps"] == ANSWERS["plan"]["steps"]
    # The planner worked from the approved requirements, not from the goal alone.
    assert CRITERION in ollama.only("plan")


def test_a_stage_whose_recorded_prior_is_missing_spends_nothing(workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama())
    with pytest.raises(CodingError, match="requirements") as refused:
        run(stage_request(config, source, run_root, run_root.parent / "evidence", stage="plan"))
    assert refused.value.code == "invalid_request"
    assert ollama.chats == []


def test_an_attempt_with_no_time_left_refuses_the_stage_instead_of_starting_it(
        workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama())
    with pytest.raises(CodingError) as refused:
        run(stage_request(config, source, run_root, run_root.parent / "evidence",
                          stage="requirements", deadline=child.ROLE_TIME_MARGIN))
    assert refused.value.code == "wall_budget"
    assert ollama.chats == []


def test_an_audit_sees_every_recorded_stage_and_review_but_no_reviewers_prose(
        workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama())
    prior = {**APPROVED,
             "implementation": recorded({"candidate_sha256": CANDIDATE, "patch_sha256": "c" * 64,
                                         "changed_paths": ["main.py"], "summary": "Adds two."},
                                        artifact_sha256=CANDIDATE),
             "verification": recorded({"candidate_sha256": CANDIDATE,
                                       "checks": [{"name": "increment", "passed": True}],
                                       "baseline_reproduced": True, "preservation_passed": True,
                                       "verification": "passed"}, artifact_sha256=CANDIDATE)}
    result = run(stage_request(config, source, run_root, run_root.parent / "evidence",
                               stage="audit", prior=prior, candidate_sha256=CANDIDATE,
                               catalogue=["stage:requirements"]))
    assert result["artifact"]["required_stages"] == list(STAGE_ORDER[:STAGE_ORDER.index("audit")])
    # The candidate the audit names is the one the worker pinned, not one a
    # model chose or restated.
    assert result["artifact"]["candidate_sha256"] == CANDIDATE
    assert result["artifact"]["violations"] == []
    shown = ollama.only("audit")
    # What decides process integrity is kept verbatim; only the reviewers'
    # narrative prose is projected away.
    assert FINDING in shown and '"verdict"' in shown
    assert REVIEW_NARRATIVE not in shown
    # The auditor may cite only what the worker recorded; its reviewer may also
    # cite the candidate this stage itself names.
    assert canonical_json(["stage:requirements"]) in shown
    assert canonical_json([f"artifact:{CANDIDATE}", "stage:requirements"]) in \
        ollama.only("review")


def test_nothing_extracted_leaves_nothing_to_adjudicate_and_asks_no_model(workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama())
    prior = {"learning": recorded({"candidate_sha256": CANDIDATE, "lessons": []},
                                  artifact_sha256=CANDIDATE)}
    result = run(stage_request(config, source, run_root, run_root.parent / "evidence",
                               stage="learning_review", prior=prior,
                               candidate_sha256=CANDIDATE))
    assert result["artifact"] == {"candidate_sha256": CANDIDATE, "decisions": []}
    # An empty decision set is the honest record, and no model was asked to
    # adjudicate nothing. The stage is still independently reviewed.
    assert ollama.shown("learning_review") == []
    assert len(ollama.shown("review")) == 1
    assert result["usage"] == {"tokens": TURN_TOKENS, "role_calls": 1}


def test_a_candidate_lesson_without_its_own_decision_cannot_be_recorded(workspace, boundary):
    config, source, run_root = workspace
    boundary(LocalOllama(answers={"learning_review": {"decisions": [
        {"index": 1, "verdict": "pass", "reason": "Only a second lesson was judged."}]}}))
    prior = {"learning": recorded({"candidate_sha256": CANDIDATE, "lessons": [LESSON]},
                                  artifact_sha256=CANDIDATE)}
    with pytest.raises(CodingError, match="exactly one decision") as refused:
        run(stage_request(config, source, run_root, run_root.parent / "evidence",
                          stage="learning_review", prior=prior, candidate_sha256=CANDIDATE))
    assert refused.value.code == "learning_undecided"


def test_a_learning_stage_reasons_about_the_recorded_outcome_it_was_given(workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama())
    outcome = "candidate rejected at the verification stage"
    result = run(stage_request(config, source, run_root, run_root.parent / "evidence",
                               stage="learning", prior=APPROVED, candidate_sha256=CANDIDATE,
                               outcome=outcome))
    assert result["artifact"] == {"candidate_sha256": CANDIDATE, "lessons": [LESSON]}
    assert outcome in ollama.only("learning")


def test_the_reviewer_identity_is_the_reviewer_models_own_pinned_identity(
        tmp_path, coding_spec_data, boundary):
    config = tmp_path / "operator.json"
    config.write_text(json.dumps(spec_payload(coding_spec_data)), encoding="utf-8")
    review_config = tmp_path / "reviewer.json"
    review_config.write_text(
        json.dumps(spec_payload(coding_spec_data, model=REVIEWER, digest=REVIEWER_DIGEST)),
        encoding="utf-8")
    source = write_zip(tmp_path / "source.zip", {"main.py": PROGRAM})
    ollama = boundary(LocalOllama(models=((MODEL, DIGEST), (REVIEWER, REVIEWER_DIGEST))))
    result = run(stage_request(config, source, tmp_path / "run", tmp_path / "evidence",
                               stage="requirements", review_config=review_config))
    # The review really ran on the second pinned model, and the identity the
    # record carries is that reviewer's rather than the author's.
    assert [chat["model"] for chat in ollama.chats] == [MODEL, REVIEWER]
    assert (result["reviewer_model"], result["reviewer_digest"]) == (REVIEWER, REVIEWER_DIGEST)


# -- a role answer the controller cannot use -------------------------------


def test_a_role_reply_this_boundary_cannot_account_for_fails_the_stage(workspace, boundary):
    config, source, run_root = workspace
    # A reply that calls a tool this role was never given cannot be accounted
    # for, whatever shape its typed answer was asked in.
    ollama = boundary(LocalOllama(answers={"requirements": lambda payload: _call(
        "run_checks", {})}))
    with pytest.raises(CodingError) as refused:
        run(stage_request(config, source, run_root, run_root.parent / "evidence",
                          stage="requirements"))
    assert refused.value.code == "provider_contract"
    assert len(ollama.chats) == 1


def test_a_role_that_cannot_answer_in_shape_is_refused_within_a_bounded_retry_budget(
        workspace, boundary):
    config, source, run_root = workspace
    # A requirements record with no acceptance criterion fails the contract the
    # controller enforces, so no stage artifact can come out of this attempt.
    ollama = boundary(LocalOllama(answers={
        "requirements": {"acceptance_criteria": [], "constraints": []}}))
    with pytest.raises(CodingError) as refused:
        run(stage_request(config, source, run_root, run_root.parent / "evidence",
                          stage="requirements"))
    # A durable operational code, never a framework error escaping the child,
    # and the retries are bounded instead of looping against the ledger.
    assert re.fullmatch(r"[a-z][a-z0-9_]{2,47}", refused.value.code)
    assert refused.value.code != "ok"
    assert 1 <= len(ollama.chats) <= 1 + ROLE_RETRIES
    assert ollama.shown("review") == []


def test_a_role_that_keeps_retrying_runs_out_of_the_attempts_call_ceiling(workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama(answers={
        "requirements": {"acceptance_criteria": [], "constraints": []}}))
    with pytest.raises(CodingError):
        run(stage_request(config, source, run_root, run_root.parent / "evidence",
                          stage="requirements", budget={"tokens": 400000, "role_calls": 1}))
    # One call was funded, so one turn is all the attempt could spend: a model
    # that cannot answer in shape exhausts a bounded allowance rather than
    # retrying until the deadline.
    assert len(ollama.chats) == 1


# -- what a check expects stays inside the trusted process -----------------


def test_a_check_report_reaches_a_model_as_name_kind_and_outcome_only():
    # Exactly the rows the controller's own check suite writes, including the
    # output a passing check produced, which is the operator's expected answer.
    rows = [{"name": "acceptance-private-marker", "kind": "regression", "passed": True,
             "exit_code": 0, "json_valid": True, "stdout": f"{ACCEPTANCE_ANSWER}\n",
             "stderr": "", "duration_seconds": 0.4, "container_name": "oryveta-check-1"}]
    outcomes = child._outcomes(rows)
    assert outcomes == [{"name": "acceptance-private-marker", "kind": "regression",
                         "passed": True}]
    rendered = canonical_json(outcomes)
    assert all(value not in rendered for value in PROTECTED)
    assert "stdout" not in rendered and "container_name" not in rendered


@pytest.mark.parametrize("rows", [
    {"name": "increment", "passed": True},
    [{"name": "increment", "passed": "yes", "kind": "regression"}],
    [{"kind": "regression", "passed": True}],
    ["increment"],
])
def test_an_unusable_check_report_is_refused_rather_than_interpreted(rows):
    with pytest.raises(CodingError) as refused:
        child._outcomes(rows)
    assert refused.value.code == "invalid_evidence"


def test_a_task_context_larger_than_the_executor_accepts_refuses_the_stage(workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama(editor=fixing))
    with pytest.raises(CodingError) as refused:
        run(stage_request(config, source, run_root, run_root.parent / "evidence",
                          stage="implementation", prior=APPROVED,
                          lessons="Keep the null branch untouched. " * 800))
    # The approved plan and the retrieved lessons are handed to the editing
    # loop as bounded data. A context that does not fit is refused outright
    # rather than silently trimmed to something the executor never approved.
    assert refused.value.code == "invalid_guidance"
    # Nothing was spent and no evidence directory was opened.
    assert ollama.chats == []
    assert not (run_root.parent / "evidence").exists()


def test_a_goal_longer_than_the_recorded_bound_refuses_the_stage(workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama(editor=fixing))
    with pytest.raises(CodingError) as refused:
        run(stage_request(config, source, run_root, run_root.parent / "evidence",
                          stage="implementation", prior=APPROVED, goal="g" * 4001))
    # A goal that does not fit what the control plane can record is refused
    # before a container starts or a turn is spent, rather than being carried
    # into work whose result could never be stored.
    assert refused.value.code == "invalid_goal"
    assert ollama.chats == []
    assert not (run_root.parent / "evidence").exists()


# -- real isolated execution ----------------------------------------------


def test_an_implementation_record_names_only_the_bytes_this_process_produced(
        isolated, tmp_path, boundary):
    config, source, run_root = isolated
    ollama = boundary(LocalOllama(editor=fixing))
    evidence = tmp_path / "implementation"
    result = run(stage_request(config, source, run_root, evidence, stage="implementation",
                               prior=APPROVED, lessons=LESSON_BLOCK,
                               catalogue=["stage:requirements", "stage:plan"]))
    output = evidence / "repair"
    candidate = (output / "candidate.zip").read_bytes()
    patch = (output / "verified.patch").read_text(encoding="utf-8")
    assert result["status"] == "ok"
    # Every recorded identity is the digest of bytes that exist on disk.
    assert result["artifact"]["candidate_sha256"] == hashlib.sha256(candidate).hexdigest()
    assert result["artifact"]["patch_sha256"] == \
        hashlib.sha256(patch.encode("utf-8")).hexdigest()
    assert result["measured"]["candidate_sha256"] == result["artifact"]["candidate_sha256"]
    assert result["measured"]["patch_sha256"] == result["artifact"]["patch_sha256"]
    # The change scope is re-derived by comparing the two archives' own trees.
    assert result["artifact"]["changed_paths"] == ["main.py"]
    assert result["measured"]["changed_paths"] == ["main.py"]
    assert result["produced"] == {
        "candidate_path": str(output / "candidate.zip"),
        "patch_path": str(output / "verified.patch"),
        "receipt_path": str(output / "receipt.json"),
        "trace_path": str(output / "events.jsonl")}
    assert all(Path(path).is_file() for path in result["produced"].values())
    assert "value + 2" in patch
    receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "needs_review" and receipt["verification"] == "passed"
    assert receipt["checks_passed"] == 3
    # The editing loop's turns and the roles draw on one aggregate ledger, and
    # only the roles are charged to the call ceiling.
    assert result["usage"] == {"tokens": TURN_TOKENS * len(ollama.chats), "role_calls": 2}
    assert len(ollama.shown("executor")) == 4


def test_the_implementation_reviewer_sees_the_whole_diff_and_no_protected_expectation(
        isolated, tmp_path, boundary):
    config, source, run_root = isolated
    ollama = boundary(LocalOllama(editor=fixing))
    evidence = tmp_path / "implementation"
    result = run(stage_request(config, source, run_root, evidence, stage="implementation",
                               prior=APPROVED, lessons=LESSON_BLOCK,
                               catalogue=["stage:requirements"]))
    output = evidence / "repair"
    patch = (output / "verified.patch").read_text(encoding="utf-8")
    review = ollama.only("review")
    # The reviewer is shown the exact diff that was verified, not a summary of
    # it, together with the identities its own record will be bound to.
    assert patch in review
    assert f"artifact:{result['artifact']['candidate_sha256']}" in review
    assert f"artifact:{result['artifact']['patch_sha256']}" in review
    # The author of the description never saw those references.
    assert "artifact:" not in ollama.only("implementation")
    # A check's name is public; what it expects is the operator's and stays in
    # this process, even though a container really compared it.
    observed = (output / "verification.json").read_text(encoding="utf-8")
    assert str(ACCEPTANCE_ANSWER) in observed
    assert "acceptance-private-marker" in review
    for chat in ollama.chats:
        rendered = json.dumps(chat)
        assert all(value not in rendered for value in PROTECTED)
    assert all(value not in json.dumps(result) for value in PROTECTED)


def test_the_editing_loop_works_from_the_approved_plan_and_the_approved_lessons(
        isolated, tmp_path, boundary):
    config, source, run_root = isolated
    ollama = boundary(LocalOllama(editor=fixing))
    evidence = tmp_path / "implementation"
    run(stage_request(config, source, run_root, evidence, stage="implementation",
                      prior=APPROVED, lessons=LESSON_BLOCK))
    opening = ollama.shown("executor")[0]
    # The reviewed requirements, the approved plan and the retrieved lessons
    # reach the executor as data, so the edit is made against what was already
    # reviewed rather than against the goal sentence alone.
    assert CRITERION in opening and STEP in opening and LESSON_BLOCK in opening
    # It is still recorded by digest and as its own evidence file.
    receipt = json.loads((evidence / "repair" / "receipt.json").read_text(encoding="utf-8"))
    guidance = json.loads((evidence / "repair" / "guidance.json").read_text(encoding="utf-8"))
    assert guidance["sha256"] == receipt["guidance_sha256"]
    assert guidance["text"] in opening
    assert all(value not in guidance["text"] for value in PROTECTED)


def test_an_unreviewable_diff_is_refused_instead_of_shown_in_part(isolated, tmp_path, boundary):
    config, source, run_root = isolated
    ollama = boundary(LocalOllama(editor=sprawling))
    evidence = tmp_path / "implementation"
    with pytest.raises(CodingError) as refused:
        run(stage_request(config, source, run_root, evidence, stage="implementation",
                          prior=APPROVED))
    assert refused.value.code == "review_context_exceeded"
    output = evidence / "repair"
    # The candidate really was produced and verified; it is the review that
    # cannot honestly happen, so no role was asked to perform one.
    receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "needs_review" and receipt["verification"] == "passed"
    patch = (output / "verified.patch").read_bytes()
    assert len(patch) > child.MAX_REVIEW_PATCH_BYTES
    assert ollama.shown("implementation") == [] and ollama.shown("review") == []


def test_an_editing_loop_that_fails_the_checks_produces_no_reviewed_stage(
        isolated, tmp_path, boundary):
    config, source, run_root = isolated
    ollama = boundary(LocalOllama(editor=breaking))
    evidence = tmp_path / "implementation"
    with pytest.raises(CodingError) as refused:
        run(stage_request(config, source, run_root, evidence, stage="implementation",
                          prior=APPROVED))
    assert refused.value.code == "verification_failed"
    output = evidence / "repair"
    # The attempt is kept as evidence, but nothing about it is reviewable: no
    # verified patch, no artifact and no role call on a refused candidate.
    assert not (output / "verified.patch").exists()
    assert (output / "unverified.patch").is_file() and (output / "candidate.zip").is_file()
    rows = json.loads((output / "verification.json").read_text(encoding="utf-8"))
    assert any(not row["passed"] for row in rows)
    assert ollama.shown("implementation") == [] and ollama.shown("review") == []


def test_an_independent_re_verification_accepts_the_same_bytes_without_a_model(
        isolated, tmp_path, boundary):
    config, source, run_root = isolated
    ollama = boundary(LocalOllama(editor=fixing))
    implemented = run(stage_request(config, source, run_root, tmp_path / "implementation",
                                    stage="implementation", prior=APPROVED))
    candidate_sha256 = implemented["artifact"]["candidate_sha256"]
    prior = {**APPROVED, "implementation": recorded(implemented["artifact"],
                                                    artifact_sha256=candidate_sha256)}
    before = len(ollama.chats)
    result = run(stage_request(config, source, run_root, tmp_path / "verification",
                               stage="verification",
                               candidate=tmp_path / "implementation" / "repair" / "candidate.zip",
                               candidate_sha256=candidate_sha256, prior=prior))
    # The archive is re-imported and re-run from its own bytes, so the identity
    # it is recorded under is the one the implementation produced.
    assert result["artifact"]["candidate_sha256"] == candidate_sha256
    assert result["artifact"]["verification"] == "passed"
    assert result["artifact"]["baseline_reproduced"] is True
    assert result["artifact"]["preservation_passed"] is True
    assert result["artifact"]["checks"] == [
        {"name": "increment", "passed": True}, {"name": "empty", "passed": True},
        {"name": "acceptance-private-marker", "passed": True}]
    assert result["measured"]["reproduced_failures"] == ["acceptance-private-marker", "increment"]
    assert result["measured"]["check_names"] == ["increment", "empty",
                                                 "acceptance-private-marker"]
    # Only the independent review spent inference: no model produced, claimed
    # or influenced this stage's artifact.
    assert len(ollama.chats) == before + 1
    assert result["usage"] == {"tokens": TURN_TOKENS, "role_calls": 1}
    review = ollama.shown("review")[-1]
    for name in result["measured"]["check_names"]:
        assert f"check:{name}" in review
    assert all(value not in json.dumps(result) for value in PROTECTED)


def test_a_candidate_that_fails_a_configured_check_cannot_be_recorded_as_verified(
        isolated, tmp_path, boundary):
    config, source, run_root = isolated
    ollama = boundary(LocalOllama())
    tampered = write_zip(tmp_path / "tampered.zip",
                         {"main.py": PROGRAM.replace("value + 1", "value + 3")})
    evidence = tmp_path / "verification"
    with pytest.raises(CodingError) as refused:
        run(stage_request(config, source, run_root, evidence, stage="verification",
                          candidate=tampered, candidate_sha256="c" * 64, prior=APPROVED))
    assert refused.value.code == "verification_failed"
    rows = json.loads((evidence / "verify" / "verification.json").read_text(encoding="utf-8"))
    assert any(not row["passed"] for row in rows)
    assert not (evidence / "verify" / "verified.patch").exists()
    # A refused candidate is never reviewed, so no inference is spent on it.
    assert ollama.chats == []


def test_verification_without_the_candidate_archive_is_refused(workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama())
    with pytest.raises(CodingError, match="candidate") as refused:
        run(stage_request(config, source, run_root, run_root.parent / "evidence",
                          stage="verification", prior=APPROVED))
    assert refused.value.code == "invalid_request"
    assert ollama.chats == []


# -- what the child publishes to its worker --------------------------------


def invoke(request_path, result_path, request, *, seconds="60", parent=None):
    request_path.write_text(json.dumps(request), encoding="utf-8")
    return child.main([str(request_path), str(result_path), seconds,
                       str(os.getppid() if parent is None else parent)])


def test_a_completed_stage_is_published_once_as_a_private_atomic_result(
        tmp_path, workspace, boundary):
    config, source, run_root = workspace
    boundary(LocalOllama())
    results = tmp_path / "results"
    results.mkdir()
    result_path = results / "requirements.json"
    request = stage_request(config, source, run_root, tmp_path / "evidence",
                            stage="requirements")
    assert invoke(tmp_path / "request.json", result_path, request) == 0
    published = json.loads(result_path.read_text(encoding="utf-8"))
    assert published["stage"] == "requirements" and published["status"] == "ok"
    assert published["artifact"]["goal"] == GOAL
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600
    assert [path.name for path in results.iterdir()] == ["requirements.json"]


def test_a_refused_stage_is_published_as_a_failure_and_never_as_a_result(
        tmp_path, workspace, boundary):
    config, source, run_root = workspace
    boundary(LocalOllama())
    result_path = tmp_path / "result.json"
    request = stage_request(config, source, run_root, tmp_path / "evidence", stage="plan")
    assert invoke(tmp_path / "request.json", result_path, request) == 0
    published = json.loads(result_path.read_text(encoding="utf-8"))
    assert published["status"] == "failed" and published["error_code"] == "invalid_request"
    # No fabricated stage result and no reviewer attributed to a model that was
    # never called.
    assert published["artifact"] is None and published["review"] is None
    assert published["reviewer_model"] is None and published["reviewer_digest"] is None
    assert published["measured"] == {} and published["produced"] == {}
    assert published["usage"] == {"tokens": 0, "role_calls": 0}
    assert published["details"] == {}


def test_an_unexpected_internal_failure_publishes_its_type_and_no_foreign_text(
        tmp_path, workspace, boundary):
    config, source, run_root = workspace
    boundary(LocalOllama())
    result_path = tmp_path / "result.json"
    request = stage_request(config, source, run_root, tmp_path / "evidence",
                            stage="requirements")
    request["deadline_seconds"] = "oryveta-operator-only-text"
    assert invoke(tmp_path / "request.json", result_path, request) == 0
    payload = result_path.read_text(encoding="utf-8")
    published = json.loads(payload)
    assert published["status"] == "failed"
    assert published["error_code"] == "stage_internal_error"
    assert published["details"] == {"failure": "ValueError"}
    # Only a code and a type: no message, no path and no operator text ever
    # becomes part of a durable record.
    assert "oryveta-operator-only-text" not in payload
    assert str(tmp_path) not in payload


@pytest.mark.parametrize("mutate", [
    lambda request: request.update(schema_version=2),
    lambda request: request.update(stage="promotion"),
    lambda request: request.update(budget={"tokens": True, "role_calls": 4}),
    lambda request: request.update(budget={"tokens": 4000}),
])
def test_an_inadmissible_request_is_published_as_a_failure_without_a_stage(
        tmp_path, workspace, boundary, mutate):
    config, source, run_root = workspace
    boundary(LocalOllama())
    result_path = tmp_path / "result.json"
    request = stage_request(config, source, run_root, tmp_path / "evidence",
                            stage="requirements")
    mutate(request)
    assert invoke(tmp_path / "request.json", result_path, request) == 0
    published = json.loads(result_path.read_text(encoding="utf-8"))
    assert published["status"] == "failed"
    assert published["error_code"] in {"invalid_request", "invalid_stage"}
    assert published["stage"] == "unknown"
    assert published["artifact"] is None


def test_a_request_larger_than_its_bound_is_refused_without_being_interpreted(
        tmp_path, workspace, boundary):
    config, source, run_root = workspace
    boundary(LocalOllama())
    result_path = tmp_path / "result.json"
    request = stage_request(config, source, run_root, tmp_path / "evidence",
                            stage="requirements")
    request["lessons"] = "l" * (child.MAX_REQUEST_BYTES + 1)
    assert invoke(tmp_path / "request.json", result_path, request) == 0
    published = json.loads(result_path.read_text(encoding="utf-8"))
    assert published["error_code"] == "invalid_request"
    assert published["stage"] == "unknown"


def test_a_stage_that_outlives_its_own_bound_publishes_nothing(tmp_path, workspace, boundary):
    config, source, run_root = workspace
    boundary(LocalOllama(delay=2.0))
    result_path = tmp_path / "result.json"
    request = stage_request(config, source, run_root, tmp_path / "evidence",
                            stage="requirements")
    assert invoke(tmp_path / "request.json", result_path, request, seconds="1") == \
        child.DEADLINE_EXIT
    # The worker's own bound is enforced here, and an interrupted stage leaves
    # no result for anybody to record.
    assert not result_path.exists()


def test_a_stage_whose_worker_is_already_gone_publishes_nothing(tmp_path, workspace, boundary):
    config, source, run_root = workspace
    ollama = boundary(LocalOllama())
    result_path = tmp_path / "result.json"
    request = stage_request(config, source, run_root, tmp_path / "evidence",
                            stage="requirements")
    # The caller supplies its own PID because it may die before this process
    # starts; a PID that is not this process's parent means nobody is left to
    # record a result, so none is produced and nothing is spent.
    assert invoke(tmp_path / "request.json", result_path, request,
                  parent=os.getpid()) == child.ORPHANED_EXIT
    assert not result_path.exists()
    assert ollama.chats == []


@pytest.mark.parametrize("arguments", [
    [], ["only-one"], ["a", "b", "c", "d", "e"], ["a", "b", "not-a-number"],
    ["a", "b", "-1"], ["a", "b", "10", "0"],
])
def test_a_malformed_invocation_creates_no_result_file(tmp_path, arguments):
    missing = tmp_path / "result.json"
    arguments = [str(tmp_path / "request.json") if value == "a" else
                 str(missing) if value == "b" else value for value in arguments]
    assert child.main(arguments) == 2
    assert not missing.exists()


def test_a_result_directory_that_does_not_exist_is_reported_before_any_work(tmp_path):
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    assert child.main([str(request), str(tmp_path / "absent" / "result.json"), "30",
                       str(os.getppid())]) == 2
