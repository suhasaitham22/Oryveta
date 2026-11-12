"""Strict typed contract for the reviewed Evolve workflow.

Three kinds of value live here and must not be confused:

* **Proposals** are what a model may produce. They are bounded, reject unknown
  fields, and deliberately carry no digest, no path authority and no verdict a
  controller would otherwise compute. A model cannot name the candidate it is
  reviewing, claim a check passed, or declare its own reviewer identity.
* **Artifacts** are the recorded per-stage facts. The controller builds them by
  combining a proposal with values only it observed: archive digests, inventory
  digests, configured check names and real check outcomes.
* **Stage payloads** are what is persisted. Every one is bound to the pinned
  source digest, the resolved operator configuration digest and the digest of
  its own artifact, so stage publication is a SHA identity rather than a
  model-supplied claim.

Evidence identifiers are validated against what the controller actually knows
(`EvidenceIndex`), never against the model's own description of the world, and a
review that cites something unknown is refused instead of being recorded.

A run that fails has one further record available to it: a `FailureReport`, the
terminal diagnostic side branch of an attempt that cannot produce an approvable
candidate. It is not a stage. It carries the real check outcomes the controller
observed, including failing ones, and it states plainly whether failure
learning actually ran or was unavailable and why. It cannot carry a candidate
digest, a passing verification or a lesson this run's own evidence does not
support, and nothing in it can approve, publish or un-fail anything.

Operator-protected expected check outputs never appear in any type here, and the
sanitizers below exist so that the receipt and trace published to a project's
authorized users also cannot carry them: a *passing* check's actual output is
the expected output, so observed check text is reduced to outcomes before it
leaves the worker's private evidence directory.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError, model_validator

from .coding_contract import CodingError, canonical_json

SCHEMA_VERSION = 1

# Ordered admission: a stage may only be recorded once every earlier stage is.
STAGE_ORDER: tuple[str, ...] = (
    "requirements", "plan", "implementation", "verification", "audit", "learning",
    "learning_review",
)
# Heartbeat phases. `claimed` and `fetching_source` precede the stages, and the
# two terminal phases describe a run whose execution has ended.
PHASES: tuple[str, ...] = ("claimed", "fetching_source", *STAGE_ORDER, "awaiting_approval", "done")
ARTIFACT_KINDS: tuple[str, ...] = ("patch", "candidate", "receipt", "trace")
# Failed-run learning is a supervised child operation and deliberately not a
# stage: it is a terminal diagnostic side branch of an attempt that already
# cannot produce an approvable candidate, so it is never recorded in the stage
# order, never admitted by `record_evolve_stage`, and never part of a finish.
FAILURE_LEARNING = "failure_learning"
OPERATIONS: tuple[str, ...] = (*STAGE_ORDER, FAILURE_LEARNING)

MAX_STAGE_PAYLOAD_BYTES = 64 * 1024
MAX_CANDIDATE_BYTES = 12 * 1024 * 1024
MAX_SMALL_ARTIFACT_BYTES = 1024 * 1024
ARTIFACT_LIMITS: dict[str, int] = {
    "candidate": MAX_CANDIDATE_BYTES, "patch": MAX_SMALL_ARTIFACT_BYTES,
    "receipt": MAX_SMALL_ARTIFACT_BYTES, "trace": MAX_SMALL_ARTIFACT_BYTES,
}
MAX_GOAL_BYTES = 4000

# A review rejection or a failed controller-owned contract is a verdict about
# this work item, not an infrastructure hiccup, so it is never retried.
NONRETRYABLE_CODES = frozenset({
    "review_rejected", "verification_failed", "invalid_baseline", "not_reproduced", "no_change",
    "process_rejected",
})

HEX64 = re.compile(r"[0-9a-f]{64}")
# A short enumerated operational code. Only codes are ever persisted, so this
# is also what keeps a message, a path or a credential out of a stored row.
_CODE = r"[a-z][a-z0-9_]{2,47}"
_CHECK_NAME = r"[a-z][a-z0-9_-]{0,59}"
STAGE_REF = re.compile(r"stage:([a-z_]{1,40})")
CHECK_REF = re.compile(rf"check:({_CHECK_NAME})")
ARTIFACT_REF = re.compile(r"artifact:([0-9a-f]{64})")
# A failed attempt's own error code, citable only by that attempt's report.
FAILURE_REF = re.compile(rf"failure:({_CODE})")

# One line of readable text: no control characters at all, so a record cannot
# carry terminal escapes or embedded framing.
_LINE = r"[^\x00-\x1f\x7f]+"
# Readable prose, where a newline is the only control character allowed.
_TEXT = r"[^\x00-\x09\x0b-\x1f\x7f]+"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300,
                                        pattern=rf"^{_LINE}$")]
# Deliberately tight. Every list item and every narration has to fit, together
# with the whole prior record, inside the pinned model's context window, and an
# auditor that cannot be shown the complete evidence is worth nothing. A role
# that needs more room than this is answering the wrong question.
Sentence = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400,
                                            pattern=rf"^{_LINE}$")]
Prose = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200,
                                         pattern=rf"^{_TEXT}$")]
EvidenceRef = Annotated[str, StringConstraints(
    strip_whitespace=True, min_length=3, max_length=80,
    pattern=r"^(stage|check|artifact|failure):[A-Za-z0-9_-]+$")]
ErrorCode = Annotated[str, StringConstraints(pattern=rf"^{_CODE}$")]
CheckName = Annotated[str, StringConstraints(pattern=rf"^{_CHECK_NAME}$")]
MAX_LIST_ITEMS = 8
RelativePath = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                                max_length=240, pattern=r"^[^\x00-\x1f\x7f:\\]+$")]


class _Bounded(BaseModel):
    """Reject unknown fields so no caller or model can smuggle an extra claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class _Strict(_Bounded):
    """Controller-built records: no type coercion, because nothing needs it."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


# -- what a model may propose ---------------------------------------------


class RequirementsProposal(_Bounded):
    acceptance_criteria: list[Sentence]
    constraints: list[Sentence] = []

    @model_validator(mode="after")
    def _bounds(self) -> RequirementsProposal:
        if (not 1 <= len(self.acceptance_criteria) <= MAX_LIST_ITEMS
                or len(self.constraints) > MAX_LIST_ITEMS):
            raise ValueError("requirements need 1 to 8 acceptance criteria and up to 8 constraints")
        return self


class PlanProposal(_Bounded):
    steps: list[Sentence]
    risks: list[Sentence] = []

    @model_validator(mode="after")
    def _bounds(self) -> PlanProposal:
        if not 1 <= len(self.steps) <= MAX_LIST_ITEMS or len(self.risks) > MAX_LIST_ITEMS:
            raise ValueError("a plan needs 1 to 8 steps and up to 8 risks")
        return self


class SummaryProposal(_Bounded):
    """A bounded readable account of work the controller already measured."""

    summary: Prose


class AuditProposal(_Bounded):
    violations: list[Sentence] = []
    summary: Prose

    @model_validator(mode="after")
    def _bounds(self) -> AuditProposal:
        if len(self.violations) > MAX_LIST_ITEMS:
            raise ValueError("an audit records at most 8 violations")
        return self


class LessonProposal(_Bounded):
    summary: Sentence
    applicability: Sentence
    evidence_ids: list[EvidenceRef]
    counterexamples: list[Sentence] = []

    @model_validator(mode="after")
    def _bounds(self) -> LessonProposal:
        if not 1 <= len(self.evidence_ids) <= 6 or len(self.counterexamples) > 4:
            raise ValueError("a lesson cites 1 to 6 evidence ids and up to 4 counterexamples")
        return self


class LearningProposal(_Bounded):
    """No supported lesson is a valid, honest outcome; five is the ceiling."""

    lessons: list[LessonProposal] = []

    @model_validator(mode="after")
    def _bounds(self) -> LearningProposal:
        if len(self.lessons) > 5:
            raise ValueError("at most five candidate lessons may be extracted")
        return self


class LessonDecisionProposal(_Bounded):
    index: int
    verdict: Literal["pass", "reject"]
    reason: Sentence

    @model_validator(mode="after")
    def _bounds(self) -> LessonDecisionProposal:
        if not 0 <= self.index < 5:
            raise ValueError("a lesson decision index is out of range")
        return self


class LearningReviewProposal(_Bounded):
    decisions: list[LessonDecisionProposal] = []

    @model_validator(mode="after")
    def _bounds(self) -> LearningReviewProposal:
        if len(self.decisions) > 5:
            raise ValueError("at most five lesson decisions may be returned")
        return self


class FindingProposal(_Bounded):
    severity: Literal["blocking", "warning"]
    detail: Sentence
    evidence_id: EvidenceRef


class ReviewProposal(_Bounded):
    """A reviewer's observable verdict.

    The reviewer does not name itself: `reviewer_model` and `reviewer_digest` are
    the pinned identity the controller observed, so a model cannot attribute its
    verdict to another model or to another digest.
    """

    verdict: Literal["pass", "rework", "escalate"]
    summary: Prose
    evidence_ids: list[EvidenceRef]
    findings: list[FindingProposal] = []

    @model_validator(mode="after")
    def _bounds(self) -> ReviewProposal:
        if not 1 <= len(self.evidence_ids) <= 12 or len(self.findings) > MAX_LIST_ITEMS:
            raise ValueError("a review cites 1 to 12 evidence ids and records up to 8 findings")
        if self.verdict == "pass" and any(item.severity == "blocking" for item in self.findings):
            raise ValueError("a passing review cannot carry a blocking finding")
        return self


# -- what is recorded -----------------------------------------------------


class Finding(_Strict):
    severity: Literal["blocking", "warning"]
    detail: Sentence
    evidence_id: EvidenceRef


class Review(_Strict):
    verdict: Literal["pass", "rework", "escalate"]
    summary: Prose
    evidence_ids: list[EvidenceRef]
    findings: list[Finding]
    reviewer_model: Line
    reviewer_digest: Sha256

    @model_validator(mode="after")
    def _bounds(self) -> Review:
        if not 1 <= len(self.evidence_ids) <= 12 or len(self.findings) > MAX_LIST_ITEMS:
            raise ValueError("a review cites 1 to 12 evidence ids and records up to 8 findings")
        if self.verdict == "pass" and any(item.severity == "blocking" for item in self.findings):
            raise ValueError("a passing review cannot carry a blocking finding")
        return self


class RequirementsArtifact(_Strict):
    goal: Annotated[str, StringConstraints(min_length=1, max_length=MAX_GOAL_BYTES)]
    acceptance_criteria: list[Sentence]
    constraints: list[Sentence]


class PlanArtifact(_Strict):
    steps: list[Sentence]
    allowed_paths: list[RelativePath]
    risks: list[Sentence]


class ImplementationArtifact(_Strict):
    candidate_sha256: Sha256
    patch_sha256: Sha256
    changed_paths: list[RelativePath]
    summary: Prose


class CheckOutcome(_Strict):
    name: CheckName
    passed: bool


class VerificationArtifact(_Strict):
    """Only an all-passing, reproduced, preserved verification is representable.

    The literal types are the point: a verification artifact cannot be built to
    say anything other than that the controller's own contracts all held.

    A failed verification therefore has no artifact and no stage row at all.
    Its real check outcomes are recorded in the `FailureReport` below, which
    keeps a failure observable without there ever being a representable stage
    that says a failing verification passed.
    """

    candidate_sha256: Sha256
    checks: list[CheckOutcome]
    baseline_reproduced: Literal[True]
    preservation_passed: Literal[True]
    verification: Literal["passed"]

    @model_validator(mode="after")
    def _all_passed(self) -> VerificationArtifact:
        if not self.checks:
            raise ValueError("a verification artifact records at least one check")
        if not all(check.passed for check in self.checks):
            raise ValueError("a passed verification cannot contain a failing check")
        return self


class AuditArtifact(_Strict):
    candidate_sha256: Sha256
    required_stages: list[Line]
    violations: list[Sentence]
    summary: Prose


class Lesson(_Strict):
    summary: Sentence
    applicability: Sentence
    evidence_ids: list[EvidenceRef]
    counterexamples: list[Sentence]


class LearningArtifact(_Strict):
    candidate_sha256: Sha256
    lessons: list[Lesson]


class LessonDecision(_Strict):
    index: int
    verdict: Literal["pass", "reject"]
    reason: Sentence


class LearningReviewArtifact(_Strict):
    candidate_sha256: Sha256
    decisions: list[LessonDecision]


STAGE_ARTIFACTS: dict[str, type[_Strict]] = {
    "requirements": RequirementsArtifact, "plan": PlanArtifact,
    "implementation": ImplementationArtifact, "verification": VerificationArtifact,
    "audit": AuditArtifact, "learning": LearningArtifact,
    "learning_review": LearningReviewArtifact,
}
# Stages whose artifact digest is the candidate archive digest rather than the
# digest of the stage artifact's own canonical JSON.
CANDIDATE_BOUND_STAGES = frozenset(STAGE_ORDER[STAGE_ORDER.index("implementation"):])


class StagePayload(_Strict):
    schema_version: Literal[1]
    source_sha256: Sha256
    config_sha256: Sha256
    artifact_sha256: Sha256
    artifact: dict[str, Any]
    review: Review


def digest_json(value: Any) -> str:
    """The canonical-JSON identity of a record, used as its artifact digest."""
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def typed(model: type[BaseModel], value: Any, code: str, subject: str) -> BaseModel:
    """Validate against a bounded contract, reporting a safe operational code."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise CodingError(code, f"{subject} does not satisfy its bounded contract",
                          details={"errors": error.error_count()}) from None


@dataclass
class EvidenceIndex:
    """What the controller itself knows, as the only admissible evidence.

    A review, a finding or a lesson may cite a recorded stage, a configured
    check or a registered artifact digest. Anything else is unknown, and an
    unknown citation is refused rather than stored: a model must not be able to
    manufacture support by inventing a reference, nor cite a stage it has not
    been shown.

    A failed attempt's diagnostic index also carries that attempt's own error
    code, so a failure lesson can point at the refusal it was drawn from. Only
    that one code resolves: a report cannot cite a failure that is not its own.
    """

    checks: frozenset[str]
    stages: set[str] = field(default_factory=set)
    artifacts: set[str] = field(default_factory=set)
    failure: str | None = None

    def add_stage(self, stage: str) -> None:
        if stage not in STAGE_ORDER:
            raise CodingError("invalid_stage", "unknown Evolve stage name")
        self.stages.add(stage)

    def add_artifact(self, sha: str) -> None:
        if not HEX64.fullmatch(sha):
            raise CodingError("invalid_artifact", "an artifact digest must be SHA-256")
        self.artifacts.add(sha)

    def known(self, reference: str) -> bool:
        match = STAGE_REF.fullmatch(reference)
        if match:
            return match.group(1) in self.stages
        match = CHECK_REF.fullmatch(reference)
        if match:
            return match.group(1) in self.checks
        match = FAILURE_REF.fullmatch(reference)
        if match:
            return match.group(1) == self.failure
        match = ARTIFACT_REF.fullmatch(reference)
        return bool(match) and match.group(1) in self.artifacts

    def catalogue(self) -> list[str]:
        """Exactly the references a role may cite, in a stable order."""
        return ([f"stage:{name}" for name in STAGE_ORDER if name in self.stages]
                + [f"check:{name}" for name in sorted(self.checks)]
                + [f"artifact:{sha}" for sha in sorted(self.artifacts)]
                + ([f"failure:{self.failure}"] if self.failure else []))

    def validate(self, references: list[str], subject: str) -> None:
        unknown = sorted({item for item in references if not self.known(item)})
        if unknown:
            raise CodingError("evidence_unknown",
                              f"{subject} cites evidence this run does not have",
                              details={"unknown": unknown[:8]})


def review_record(proposal: ReviewProposal, *, reviewer_model: str, reviewer_digest: str,
                  evidence: EvidenceIndex, subject: str) -> dict[str, Any]:
    """Bind a reviewer's verdict to the identity and evidence the controller saw.

    Every cited reference, including the ones inside findings, is checked
    against the controller's own index before the verdict can be recorded.
    """
    references = list(proposal.evidence_ids) + [item.evidence_id for item in proposal.findings]
    evidence.validate(references, subject)
    record = Review(
        verdict=proposal.verdict, summary=proposal.summary,
        evidence_ids=list(proposal.evidence_ids),
        findings=[Finding(severity=item.severity, detail=item.detail,
                          evidence_id=item.evidence_id) for item in proposal.findings],
        reviewer_model=reviewer_model, reviewer_digest=reviewer_digest)
    return record.model_dump(mode="json")


def stage_payload(stage: str, *, artifact: dict[str, Any], review: dict[str, Any],
                  source_sha256: str, config_sha256: str,
                  candidate_sha256: str | None) -> dict[str, Any]:
    """Build and bound one recordable stage payload.

    The artifact digest is a SHA identity the controller computes: the canonical
    JSON digest of the stage record for the planning stages, and the candidate
    archive digest from the stage the candidate exists onwards.
    """
    if stage not in STAGE_ARTIFACTS:
        raise CodingError("invalid_stage", "unknown Evolve stage name")
    typed(STAGE_ARTIFACTS[stage], artifact, "invalid_stage_artifact", f"the {stage} artifact")
    if stage in CANDIDATE_BOUND_STAGES:
        if not isinstance(candidate_sha256, str) or not HEX64.fullmatch(candidate_sha256):
            raise CodingError("invalid_artifact",
                              f"the {stage} stage requires the candidate archive digest")
        artifact_sha256 = candidate_sha256
    else:
        artifact_sha256 = digest_json(artifact)
    payload = StagePayload(
        schema_version=SCHEMA_VERSION, source_sha256=source_sha256, config_sha256=config_sha256,
        artifact_sha256=artifact_sha256, artifact=artifact,
        review=typed(Review, review, "invalid_review", f"the {stage} review"),
    ).model_dump(mode="json")
    if len(canonical_json(payload).encode("utf-8")) > MAX_STAGE_PAYLOAD_BYTES:
        raise CodingError("stage_payload_limit", f"the {stage} payload exceeds 64 KiB")
    return payload


def process_evidence(recorded: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Project the recorded stages into the exact evidence a process role sees.

    Everything that decides process integrity is kept verbatim: which stages
    exist, the source and configuration they are bound to, their artifact
    identity, each artifact in full, and every review's verdict, findings and
    citations together with the reviewer identity the controller observed.

    Only each review's narrative `summary` is left out, and that is a
    projection rather than a truncation: an auditor judges whether the record
    holds together, which no reviewer's prose can establish or refute, and
    dropping it keeps the complete remaining evidence inside the pinned model's
    context instead of silently cutting the record in half when it does not fit.
    """
    evidence: dict[str, Any] = {}
    for stage in STAGE_ORDER:
        payload = recorded.get(stage)
        if payload is None:
            continue
        review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
        evidence[stage] = {
            "source_sha256": payload.get("source_sha256"),
            "config_sha256": payload.get("config_sha256"),
            "artifact_sha256": payload.get("artifact_sha256"),
            "artifact": payload.get("artifact"),
            "review": {key: review.get(key) for key in
                       ("verdict", "evidence_ids", "findings", "reviewer_model",
                        "reviewer_digest") if key in review},
        }
    return evidence


# -- the failed-run diagnostic report --------------------------------------

# Where an attempt stopped. These are phases rather than recorded stages,
# because an attempt can fail before it has recorded anything at all, and they
# are exactly the heartbeat phases that precede `awaiting_approval`.
FailedStage = Literal["claimed", "fetching_source", "requirements", "plan", "implementation",
                      "verification", "audit", "learning", "learning_review"]
FAILED_STAGES: tuple[str, ...] = get_args(FailedStage)

# Why a failed attempt has no reviewed learning. `completed` is the only reason
# a reviewed extraction may carry, and every other value names something the
# worker actually observed: no pinned snapshot to reason about, a model it could
# not reach, an exhausted aggregate budget, an extraction that failed its own
# contract, lost authority, or an interrupted worker.
LearningReason = Literal["completed", "no_source", "model_unavailable", "budget_exhausted",
                         "extraction_failed", "authority_lost", "worker_interrupted"]
LEARNING_REASONS: tuple[str, ...] = get_args(LearningReason)

MAX_FAILURE_LESSONS = 5
# A report carries outcomes for the configured checks and nothing else, so this
# matches the bound the published receipt already applies to observed checks.
MAX_REPORT_CHECKS = 48
MAX_FAILURE_REPORT_BYTES = MAX_STAGE_PAYLOAD_BYTES


class FailureReport(_Strict):
    """The one immutable diagnostic record an unsuccessful attempt may leave.

    This is what makes a failure observable rather than an opaque code: the
    stage it stopped in and the real outcomes of the controller's own checks,
    including the ones that failed. It is deliberately not a stage artifact. A
    failing verification has no successful artifact to record, and forging one
    is exactly what must stay impossible, so the facts live here instead.

    The learning fields are the other half, and they are honest by
    construction. `reviewed` requires that the extractor and the independent
    lesson reviewer both actually ran, with one decision for each candidate
    lesson; `unavailable` requires a reason that is not `completed` and admits
    no lesson and no decision at all, so an attempt that could not spend
    inference cannot appear to have learned something. Nothing here can
    activate a lesson: a failed run's lessons are diagnostic candidates that
    only ever reach `rejected`.
    """

    schema_version: Literal[1]
    error_code: ErrorCode
    failed_stage: FailedStage
    # JSON-null exactly when the pinned snapshot was never fetched, which is
    # also the one case where no lesson is admissible at all.
    source_sha256: Sha256 | None
    config_sha256: Sha256
    checks: list[CheckOutcome]
    learning_status: Literal["reviewed", "unavailable"]
    learning_reason: LearningReason
    lessons: list[Lesson]
    decisions: list[LessonDecision]
    reviewer_model: Line
    reviewer_digest: Sha256

    @model_validator(mode="after")
    def _honest(self) -> FailureReport:
        if len(self.checks) > MAX_REPORT_CHECKS:
            raise ValueError("a failure report records at most 48 check outcomes")
        if len({check.name for check in self.checks}) != len(self.checks):
            raise ValueError("a failure report records each check outcome once")
        if self.error_code == "verification_failed" \
                and all(check.passed for check in self.checks):
            # The whole point of this record is that the failure is observable.
            # A failed verification that names no failing check would be the
            # opaque code it exists to replace.
            raise ValueError("a failed verification names the check that failed")
        if self.learning_status == "reviewed":
            if self.learning_reason != "completed":
                raise ValueError("reviewed learning completed")
            if len(self.lessons) > MAX_FAILURE_LESSONS:
                raise ValueError("a failure report carries at most five candidate lessons")
            if sorted(item.index for item in self.decisions) != list(range(len(self.lessons))):
                raise ValueError("every candidate lesson needs exactly one decision")
        else:
            if self.learning_reason == "completed":
                raise ValueError("unavailable learning did not complete")
            if self.lessons or self.decisions:
                raise ValueError("unavailable learning records no lesson and no decision")
        if self.source_sha256 is None and self.lessons:
            raise ValueError("a run that never fetched its source supports no lesson")
        return self


def failure_report(*, error_code: str, failed_stage: str, source_sha256: str | None,
                   config_sha256: str, checks: list[dict[str, Any]], learning_status: str,
                   learning_reason: str, lessons: list[dict[str, Any]],
                   decisions: list[dict[str, Any]], reviewer_model: str, reviewer_digest: str,
                   evidence: EvidenceIndex) -> dict[str, Any]:
    """Build and bound one recordable failure report.

    Every row is validated against its own strict contract before the report
    exists, so an unusable check outcome, lesson or decision refuses the report
    instead of being stored half-typed.

    Every citation a candidate lesson makes is then checked against what this
    attempt actually recorded, registered and observed, exactly as a stage
    review's citations are: a lesson drawn from a failure may point at the
    refusal, a recorded stage, a measured check outcome or a registered
    artifact, and at nothing else.
    """
    code, subject = "invalid_failure_report", "the failure report"
    report = typed(FailureReport, {
        "schema_version": SCHEMA_VERSION, "error_code": error_code,
        "failed_stage": failed_stage, "source_sha256": source_sha256,
        "config_sha256": config_sha256,
        "checks": [typed(CheckOutcome, row, code, subject) for row in checks],
        "learning_status": learning_status, "learning_reason": learning_reason,
        "lessons": [typed(Lesson, row, code, subject) for row in lessons],
        "decisions": [typed(LessonDecision, row, code, subject) for row in decisions],
        "reviewer_model": reviewer_model, "reviewer_digest": reviewer_digest,
    }, code, subject)
    evidence.validate([reference for lesson in report.lessons
                       for reference in lesson.evidence_ids], "a failure lesson")
    payload = report.model_dump(mode="json")
    if len(canonical_json(payload).encode("utf-8")) > MAX_FAILURE_REPORT_BYTES:
        raise CodingError("failure_report_limit", "the failure report exceeds 64 KiB")
    return payload


# -- sanitized publication -------------------------------------------------

# Receipt fields that are safe for a project's authorized users: identities,
# budgets, outcomes and the model's own observable summary. Host facts
# (`runner_observed`, timestamps, local paths) and the resolved configuration
# (which contains the operator's protected expected outputs) are not here.
_RECEIPT_FIELDS: tuple[str, ...] = (
    "schema_version", "run_id", "mode", "status", "last_phase", "verification",
    "configuration_sha256", "checks_sha256", "verification_scope", "turns", "tool_calls",
    "model_calls", "tokens_observed", "publication", "goal_sha256", "source_archive_sha256",
    "source_tree_sha256", "candidate_tree_sha256", "candidate_archive_sha256",
    "candidate_patch_sha256", "patch_sha256", "checks_passed", "changed_paths",
    "reproduced_failures", "error_code", "message", "model_summary",
)
_MODEL_FIELDS: tuple[str, ...] = ("name", "digest", "context_tokens", "output_tokens")
_CHECK_OUTCOME_FIELDS: tuple[str, ...] = ("name", "kind", "passed", "exit_code", "json_valid",
                                          "duration_seconds")
# Trace event kinds that may be published, each with its own projection below.
_TRACE_KINDS = frozenset({"run_started", "model_turn", "development_checks", "tool_result",
                          "verification_started", "decision", "run_finished"})
MAX_PUBLISHED_TEXT = 2000


def _text(value: object, limit: int = MAX_PUBLISHED_TEXT) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = "".join(character for character in value
                      if character in "\n\t" or character >= " " and character != "\x7f")
    return cleaned[:limit]


def _check_outcomes(value: object) -> list[dict[str, Any]]:
    """Reduce observed check reports to outcomes.

    A passing check's actual output *is* the operator's protected expected
    output, so published evidence records that a check passed and never what it
    printed. The complete output stays in the worker's private evidence.
    """
    rows = value if isinstance(value, list) else []
    return [{key: row[key] for key in _CHECK_OUTCOME_FIELDS if key in row}
            for row in rows[:48] if isinstance(row, dict)]


def sanitize_receipt(receipt: object) -> dict[str, Any]:
    """Project a run receipt onto the fields that are safe to publish."""
    if not isinstance(receipt, dict):
        raise CodingError("invalid_receipt", "a run receipt must be a JSON object")
    safe: dict[str, Any] = {}
    for key in _RECEIPT_FIELDS:
        if key not in receipt:
            continue
        value = receipt[key]
        if isinstance(value, str):
            safe[key] = _text(value)
        elif isinstance(value, list):
            safe[key] = [_text(item, 240) for item in value[:128] if isinstance(item, str)]
        elif isinstance(value, (bool, int, float)):
            safe[key] = value
    model = receipt.get("model")
    if isinstance(model, dict):
        # Deliberately without the endpoint: a worker's local origin is not a
        # project fact, and the pinned identity is the name and digest.
        safe["model"] = {key: model[key] for key in _MODEL_FIELDS if key in model}
    observed = receipt.get("model_observed")
    if isinstance(observed, dict):
        safe["model_observed"] = {key: observed[key] for key in ("name", "digest") if key in observed}
    runner = receipt.get("runner")
    if isinstance(runner, dict) and isinstance(runner.get("image"), str):
        safe["runner_image"] = _text(runner["image"], 80)
    implementation = receipt.get("implementation")
    if isinstance(implementation, dict) and isinstance(implementation.get("sha256"), str):
        safe["implementation_sha256"] = _text(implementation["sha256"], 64)
    return safe


def sanitize_trace_event(event: object) -> dict[str, Any] | None:
    """Project one trace event, or drop it when its kind is not publishable."""
    if not isinstance(event, dict) or event.get("kind") not in _TRACE_KINDS:
        return None
    kind = event["kind"]
    row: dict[str, Any] = {"kind": kind}
    for key in ("sequence", "time"):
        value = event.get(key)
        if isinstance(value, int) or isinstance(value, str):
            row[key] = _text(value, 64) if isinstance(value, str) else value
    if kind == "run_started":
        for key in ("run_id", "mode", "configuration_sha256", "source_tree_sha256",
                    "candidate_tree_sha256"):
            if isinstance(event.get(key), str):
                row[key] = _text(event[key], 64)
        if isinstance(event.get("changed_paths"), list):
            row["changed_paths"] = [_text(item, 240) for item in event["changed_paths"][:128]
                                    if isinstance(item, str)]
    elif kind == "model_turn":
        row["turn"] = event.get("turn") if isinstance(event.get("turn"), int) else None
        row["content"] = _text(event.get("content")) or ""
        calls = event.get("tool_calls") if isinstance(event.get("tool_calls"), list) else []
        # Tool names and an argument digest: the arguments themselves can hold
        # whole replacement bodies, which belong in the patch, not the trace.
        row["tool_calls"] = [
            {"name": _text(call.get("name"), 64),
             "arguments_sha256": digest_json(call.get("arguments"))}
            for call in calls[:8] if isinstance(call, dict)]
        for key in ("input_tokens", "output_tokens"):
            if isinstance(event.get(key), int):
                row[key] = event[key]
    elif kind == "development_checks":
        row["checks"] = _check_outcomes(event.get("checks"))
    elif kind == "tool_result":
        row["tool"] = _text(event.get("tool"), 64)
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        # Shape and refusal code only: a tool result can contain file content.
        row["result_keys"] = sorted(key for key in result if isinstance(key, str))[:12]
        if isinstance(result.get("error"), str):
            row["result_error"] = _text(result["error"], 64)
        if isinstance(result.get("checks"), list):
            row["checks"] = _check_outcomes(result["checks"])
    elif kind == "verification_started":
        if isinstance(event.get("candidate_tree_sha256"), str):
            row["candidate_tree_sha256"] = _text(event["candidate_tree_sha256"], 64)
    elif kind == "decision":
        for key in ("action", "reason", "action_sha256"):
            if isinstance(event.get(key), str):
                row[key] = _text(event[key], 240)
        if isinstance(event.get("source_revision"), int):
            row["source_revision"] = event["source_revision"]
    else:
        row["receipt"] = sanitize_receipt({key: value for key, value in event.items()
                                           if key not in {"kind", "sequence", "time"}})
    return row
