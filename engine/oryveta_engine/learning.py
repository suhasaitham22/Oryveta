"""Deterministic, fail-closed evidence comparison; never self-deploys."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from typing import Sequence


@dataclass(frozen=True)
class Outcome:
    task: str
    variant: str
    dataset_sha: str
    evaluator_sha: str
    passed: bool
    security_passed: bool
    cost: float

    def __post_init__(self) -> None:
        if not self.task or len(self.task) > 128:
            raise ValueError("invalid task ID")
        if self.variant not in ("baseline", "candidate"):
            raise ValueError("invalid variant")
        for value in (self.dataset_sha, self.evaluator_sha):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("dataset and evaluator must have SHA-256 fingerprints")
        if type(self.passed) is not bool or type(self.security_passed) is not bool:
            raise ValueError("pass results must be booleans")
        if not isinstance(self.cost, (int, float)) or not math.isfinite(self.cost) or self.cost < 0:
            raise ValueError("cost must be a nonnegative finite number")


@dataclass(frozen=True)
class Decision:
    status: str
    reasons: tuple[str, ...]
    task_count: int
    baseline_passed: int
    candidate_passed: int
    evidence_sha256: str


def evaluate(outcomes: Sequence[Outcome], min_tasks: int = 5,
             max_cost_multiplier: float = 1.15) -> Decision:
    """Compare identically evaluated task pairs; human approval always required."""
    if not 2 <= min_tasks <= 1000:
        raise ValueError("min_tasks outside 2..1000")
    if not math.isfinite(max_cost_multiplier) or not 1 <= max_cost_multiplier <= 3:
        raise ValueError("invalid cost multiplier")
    rows: dict[tuple[str, str], Outcome] = {}
    for result in outcomes:
        if not isinstance(result, Outcome):
            raise TypeError("expected Outcome objects")
        key = (result.task, result.variant)
        if key in rows:
            raise ValueError("duplicate task/variant evidence")
        rows[key] = result
    names = sorted(set(task for task, _ in rows))
    base = []
    cand = []
    for name in names:
        if (name, "baseline") not in rows or (name, "candidate") not in rows:
            raise ValueError("unpaired task")
        b, c = rows[name, "baseline"], rows[name, "candidate"]
        if (b.dataset_sha, b.evaluator_sha) != (c.dataset_sha, c.evaluator_sha):
            raise ValueError("non-equivalent evaluator or dataset")
        base.append(b)
        cand.append(c)
    old = sum(r.passed for r in base)
    new = sum(r.passed for r in cand)
    reasons = []
    if len(names) < min_tasks:
        reasons.append("insufficient paired tasks")
    if any(not r.security_passed for r in cand):
        reasons.append("security failure")
    if any(a.passed and not b.passed for a, b in zip(base, cand)):
        reasons.append("regression in previously passing task")
    if new <= old:
        reasons.append("no improvement")
    if sum(r.cost for r in cand) > sum(r.cost for r in base) * max_cost_multiplier:
        reasons.append("cost budget exceeded")
    digest = sha256(json.dumps([asdict(rows[key]) for key in sorted(rows)],
                               sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return Decision("REJECTED" if reasons else "NEEDS_HUMAN_REVIEW",
                    tuple(reasons), len(names), old, new, digest)
