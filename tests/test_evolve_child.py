"""Consumer-visible guarantees of one supervised Evolve child operation.

No model weights, no container and no control plane: the two role calls are
replaced at the seam the child imports them through, so what is under test is
the child's own admission, evidence and refusal decisions. The live roles are
exercised against a provisioned local stack after integration.
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("pydantic_ai")

from oryveta_engine import evolve_child as child  # noqa: E402
from oryveta_engine.coding_config import load_spec  # noqa: E402
from oryveta_engine.coding_contract import CodingError  # noqa: E402
from oryveta_engine.evolve_contract import (  # noqa: E402
    FAILURE_LEARNING, LearningProposal, LearningReviewProposal,
)

GOAL = "Extend make_str to accept a memoryview while preserving existing behavior."
OBSERVED = {"name": "qwen3:8b", "digest": "a" * 64}
LESSON = {"summary": "A buffer decode needs its own regression check.",
          "applicability": "memoryview inputs to make_str",
          "evidence_ids": ["failure:review_rejected", "stage:requirements"],
          "counterexamples": ["plain str inputs"]}
# What the worker retains for a stage whose review refused the attempt.
REFUSED_REQUIREMENTS = {
    "schema_version": 1, "source_sha256": "a" * 64, "config_sha256": "b" * 64,
    "artifact_sha256": "c" * 64,
    "artifact": {"goal": GOAL, "acceptance_criteria": ["A memoryview decodes as its bytes"],
                 "constraints": []},
    "review": {"verdict": "rework", "summary": "A criterion is not testable.",
               "evidence_ids": ["stage:requirements"],
               "findings": [{"severity": "blocking", "detail": "A criterion is not testable.",
                             "evidence_id": "stage:requirements"}],
               "reviewer_model": "qwen3:8b", "reviewer_digest": "d" * 64},
}


@pytest.fixture
def spec(tmp_path, coding_spec_data):
    config = tmp_path / "operator.json"
    config.write_text(json.dumps(coding_spec_data), encoding="utf-8")
    return load_spec(config)


@pytest.fixture
def state(tmp_path, spec):
    source = tmp_path / "source.zip"
    source.write_bytes(b"PK\x03\x04 source archive bytes")
    request = {
        "schema_version": 1, "stage": FAILURE_LEARNING, "goal": GOAL,
        "source_zip": str(source), "candidate_zip": None, "candidate_sha256": "",
        "evidence_dir": str(tmp_path), "run_root": str(tmp_path),
        "prior": {"requirements": REFUSED_REQUIREMENTS},
        "catalogue": ["stage:requirements", "failure:review_rejected"], "lessons": "",
        "outcome": "this attempt failed with review_rejected at the requirements stage",
        "budget": {"tokens": 40000, "role_calls": 6}, "deadline_seconds": 300.0,
    }
    # `None` stands in for the pinned model: every role call is replaced below,
    # so a real boundary is never constructed and nothing is ever spent.
    return child._State(request, spec, None, child.time.monotonic() + 300)


def roles(monkeypatch, *, lessons=(), decisions=()):
    """Replace the two role calls this operation is allowed to make."""
    calls: list[tuple[str, dict]] = []

    async def extract(model, budget, context, *, recorded_stages, outcome, timeout_seconds):
        calls.append(("extract", {"recorded_stages": recorded_stages, "outcome": outcome,
                                  "catalogue": list(context.evidence_catalogue)}))
        budget.tokens_spent += 900
        budget.calls_spent += 1
        return LearningProposal.model_validate({"lessons": list(lessons)})

    async def adjudicate(model, budget, context, *, lessons, recorded_stages, timeout_seconds):
        calls.append(("adjudicate", {"lessons": lessons, "recorded_stages": recorded_stages}))
        budget.tokens_spent += 400
        budget.calls_spent += 1
        return LearningReviewProposal.model_validate({"decisions": list(decisions)})

    monkeypatch.setattr(child, "extract_lessons", extract)
    monkeypatch.setattr(child, "adjudicate_lessons", adjudicate)
    return calls


def run(state):
    return asyncio.run(child._failure_learning(state, None, OBSERVED))


# -- admission -------------------------------------------------------------


def test_failure_learning_is_an_operation_and_not_a_recordable_stage(tmp_path):
    path = tmp_path / "request.json"
    body = {"schema_version": 1, "stage": FAILURE_LEARNING,
            "budget": {"tokens": 1000, "role_calls": 2}}
    path.write_text(json.dumps(body), encoding="utf-8")
    assert child._request(path)["stage"] == FAILURE_LEARNING
    path = tmp_path / "other.json"
    path.write_text(json.dumps({**body, "stage": "promotion"}), encoding="utf-8")
    with pytest.raises(CodingError, match="stage"):
        child._request(path)


# -- an unreviewable change ------------------------------------------------


def test_a_diff_a_reviewer_cannot_be_shown_whole_is_refused_rather_than_clipped():
    diff = "--- a/main.py\n+++ b/main.py\n" + "+a line of change\n" * 40
    assert child._reviewable_patch(diff) == diff
    oversized = "+x" * child.MAX_REVIEW_PATCH_BYTES
    with pytest.raises(CodingError, match="review_context_exceeded|whole") as refused:
        child._reviewable_patch(oversized)
    assert refused.value.code == "review_context_exceeded"


# -- learning from a failure ----------------------------------------------


def test_the_refusing_review_is_the_evidence_the_extraction_is_given(monkeypatch, state):
    calls = roles(monkeypatch, lessons=[LESSON],
                  decisions=[{"index": 0, "verdict": "pass", "reason": "The refusal supports it."}])
    result = run(state)
    kind, seen = calls[0]
    assert kind == "extract"
    # The review that refused the attempt, its verdict and its findings are
    # exactly what the extraction reasons about.
    recorded = seen["recorded_stages"]["requirements"]
    assert recorded["review"]["verdict"] == "rework"
    assert recorded["review"]["findings"] == REFUSED_REQUIREMENTS["review"]["findings"]
    assert "review_rejected" in seen["outcome"]
    assert seen["catalogue"] == ["stage:requirements", "failure:review_rejected"]
    assert result["stage"] == FAILURE_LEARNING and result["status"] == "ok"
    assert result["lessons"] == [LESSON]
    assert result["decisions"] == [{"index": 0, "verdict": "pass",
                                    "reason": "The refusal supports it."}]


def test_the_reported_reviewer_is_the_identity_the_controller_observed(monkeypatch, state):
    roles(monkeypatch, lessons=[LESSON],
          decisions=[{"index": 0, "verdict": "reject", "reason": "Unsupported by the record."}])
    result = run(state)
    # A role cannot name the model that answered; the observed identity does.
    assert result["reviewer_model"] == OBSERVED["name"]
    assert result["reviewer_digest"] == OBSERVED["digest"]
    assert result["decisions"][0]["verdict"] == "reject"


def test_both_role_calls_draw_on_the_one_aggregate_ledger(monkeypatch, state):
    roles(monkeypatch, lessons=[LESSON],
          decisions=[{"index": 0, "verdict": "pass", "reason": "The refusal supports it."}])
    result = run(state)
    assert result["usage"] == {"tokens": 1300, "role_calls": 2}




def test_an_unadjudicated_lesson_is_refused_rather_than_reported(monkeypatch, state):
    roles(monkeypatch, lessons=[LESSON, {**LESSON, "summary": "A second note."}],
          decisions=[{"index": 0, "verdict": "pass", "reason": "Only the first was judged."}])
    with pytest.raises(CodingError, match="exactly one decision") as refused:
        run(state)
    assert refused.value.code == "learning_undecided"


def test_a_duplicated_decision_cannot_stand_in_for_a_missing_one(monkeypatch, state):
    roles(monkeypatch, lessons=[LESSON, {**LESSON, "summary": "A second note."}],
          decisions=[{"index": 0, "verdict": "pass", "reason": "Judged."},
                     {"index": 0, "verdict": "reject", "reason": "Judged again."}])
    with pytest.raises(CodingError, match="exactly one decision"):
        run(state)


def test_a_failure_learning_result_names_no_candidate_and_no_stage_artifact(monkeypatch, state):
    roles(monkeypatch, lessons=[LESSON],
          decisions=[{"index": 0, "verdict": "pass", "reason": "The refusal supports it."}])
    result = run(state)
    assert set(result) == {"schema_version", "stage", "status", "error_code", "lessons",
                           "decisions", "reviewer_model", "reviewer_digest", "usage"}
    assert "artifact" not in result and "candidate_sha256" not in json.dumps(result)
