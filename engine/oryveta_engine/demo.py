"""Build truthful demo storyboards from an agent's independent evidence.

This module never claims a video was rendered or a candidate deployed.
All output is explicitly a storyboard and needs a reviewer before publishing.
"""
from __future__ import annotations

from dataclasses import asdict
import re

from oryveta_engine.learning import Outcome, evaluate


def story_from_evidence(
    feature_id: str,
    title: str,
    problem: str,
    capability: str,
    limitations: str,
    outcomes: list[Outcome],
) -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,63}", feature_id):
        raise ValueError("invalid feature ID; use lower-case slug of length 3-64")
    for label, value, limit in (
        ("title", title, 100),
        ("problem", problem, 600),
        ("capability", capability, 600),
        ("limitations", limitations, 600),
    ):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"{label} must be meaningful and <= {limit} characters")
    decision = evaluate(outcomes)
    status = "Review required" if decision.status == "NEEDS_HUMAN_REVIEW" else "Rejected"
    reasons = "; ".join(decision.reasons) if decision.reasons else "human review required"
    return {
        "id": feature_id,
        "title": title.strip(),
        "description": problem.strip(),
        "version": 1,
        "state": "storyboard",
        "verified": False,
        "evidence_sha256": decision.evidence_sha256,
        "evaluation_status": decision.status,
        "scenes": [
            {
                "eyebrow": "01 / CUSTOMER PROBLEM",
                "headline": "Start with the problem.",
                "body": problem.strip(),
                "receipt": "User-supplied problem statement; not a verified customer outcome.",
            },
            {
                "eyebrow": "02 / PRODUCT CAPABILITY",
                "headline": "Show only what we can support.",
                "body": capability.strip(),
                "receipt": "Capability description needs independent feature/UX evidence before publication.",
            },
            {
                "eyebrow": "03 / EVIDENCE AND LIMITATIONS",
                "headline": "Make the proof visible.",
                "body": f"Offline evaluation: {status}. Baseline passed {decision.baseline_passed}/"
                f"{decision.task_count}; candidate passed {decision.candidate_passed}/"
                f"{decision.task_count}. Limitations: {limitations.strip()}",
                "receipt": f"SHA-256 {decision.evidence_sha256}; {reasons}. "
                "No live deployment, real-user test or MP4 rendering asserted.",
            },
        ],
    }
