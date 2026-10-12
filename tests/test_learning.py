"""Test the no-regression and human-review safeguards of agent evolution."""
import pytest
from oryveta_engine.learning import Outcome, evaluate

SHA1="a"*64
SHA2="b"*64

def row(i, version, ok, cost=10, security=True):
    return Outcome(str(i),version,SHA1,SHA2,ok,security,cost)

def pairs(n=5):
    return [row(i,"baseline",i!=0) for i in range(n)]+[row(i,"candidate",True) for i in range(n)]

def test_verified_improvement_still_needs_human_approval():
    result=evaluate(pairs())
    assert result.status=="NEEDS_HUMAN_REVIEW"
    assert result.baseline_passed==4 and result.candidate_passed==5
    assert result.evidence_sha256==evaluate(list(reversed(pairs()))).evidence_sha256

def test_security_failure_is_veto():
    data=pairs()
    data[-1]=row(4,"candidate",True,security=False)
    assert "security failure" in evaluate(data).reasons

def test_regression_is_veto_even_if_net_success_is_higher():
    data=pairs(7)
    data[8]=row(1,"candidate",False)
    assert "regression in previously passing task" in evaluate(data).reasons

def test_cost_and_insufficient_pairs_are_vetoes():
    data=pairs()
    data[-1]=row(4,"candidate",True,cost=20)
    assert "cost budget exceeded" in evaluate(data).reasons
    assert "insufficient paired tasks" in evaluate(pairs(3)).reasons

def test_unpaired_duplicate_and_mismatched_dataset_rejected():
    with pytest.raises(ValueError,match="unpaired"):
        evaluate(pairs()[:-1])
    with pytest.raises(ValueError,match="duplicate"):
        evaluate(pairs()+[row(0,"baseline",True)])
    items=pairs()
    items[-1]=Outcome("4","candidate","c"*64,SHA2,True,True,10)
    with pytest.raises(ValueError,match="non-equivalent"):
        evaluate(items)

def test_invalid_cost_and_non_boolean_rejected():
    with pytest.raises(ValueError):
        row(0,"candidate",True,cost=float("nan"))
    with pytest.raises(ValueError):
        Outcome("x","baseline",SHA1,SHA2,1,True,10)

def test_equal_success_rejected():
    data=[row(i,variant,True) for i in range(5) for variant in ("baseline","candidate")]
    assert "no improvement" in evaluate(data).reasons
