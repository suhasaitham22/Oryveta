"""Feature-demo generation must never convert agent metrics into unreviewed claims."""
import pytest
from oryveta_engine.demo import story_from_evidence
from oryveta_engine.learning import Outcome

A="a"*64
B="b"*64


def evidence(ok=True):
    return [
        Outcome(str(i),v,A,B,
                (i>0 if v=="baseline" else True),
                (ok if v=="candidate" else True),
                1)
        for i in range(5) for v in ("baseline","candidate")
    ]


def make(rows=None, feature_id="feature-demo"):
    return story_from_evidence(
        feature_id, "Test feature", "Users need verified changes.",
        "A bounded local prototype exists.", "Not hosted or customer-tested.",
        evidence() if rows is None else rows,
    )


def test_story_has_three_evidence_fenced_scenes():
    story=make()
    assert story["state"]=="storyboard"
    assert story["verified"] is False
    assert story["evaluation_status"]=="NEEDS_HUMAN_REVIEW"
    assert len(story["scenes"])==3
    assert all(x["receipt"] for x in story["scenes"])
    assert "No live deployment" in story["scenes"][-1]["receipt"]
    assert len(story["evidence_sha256"])==64


def test_rejected_candidate_does_not_become_verified_story():
    rows=evidence(False)
    story=make(rows)
    assert story["evaluation_status"]=="REJECTED"
    assert story["verified"] is False
    assert "Rejected" in story["scenes"][-1]["body"]
    assert "security failure" in story["scenes"][-1]["receipt"]


def test_invalid_feature_ids_and_unsupported_claims_fail():
    for name in ("..", "Feature_demo", "/tmp/a", "a" * 65):
        with pytest.raises(ValueError, match="feature ID"):
            make(feature_id=name)
    with pytest.raises(ValueError, match="problem"):
        story_from_evidence("abc","title","","cap","limitations",evidence())


def test_evidence_requires_matched_pairs():
    with pytest.raises(ValueError, match="unpaired"):
        make(evidence()[:-1])
