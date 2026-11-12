"""Child-process entry point for one bounded Evolve stage.

The Evolve worker runs every stage that spends inference or starts a container
in a real child process, so a cancelled, revoked or fenced attempt can be
terminated instead of continuing to spend a model and a Docker daemon on a
result nobody may record. The child receives a prepared request file naming a
pinned source archive, the operator's own trusted configuration path and the
remaining budget: no credentials, no lease token, no Supabase origin and no
session. It cannot reach the control plane at all.

Running one child per stage is what makes the role contexts independent in the
strongest available sense: a reviewer is a fresh agent in a fresh process, and
nothing of the previous stage's conversation exists to leak into it.

The child does not depend on its parent to stop it. A worker that is killed
hard cannot fence anything, so this process enforces its own wall-clock bound
and exits when the process that started it disappears, writing no result.

It proposes and measures; it never records. Digests, artifact registration,
evidence validation and the stage payload are the parent's, and the operator's
protected expected check outputs stay inside this trusted process: they are
compared against container output here and never enter a prompt or a result.

One operation here is not a stage. `failure_learning` is the diagnostic side
branch of an attempt that already failed: it extracts candidate lessons from
the attempt's own recorded evidence, including a review that refused a stage,
and has them adjudicated by an independent reviewer. It produces no artifact,
names no candidate and claims no stage, because there is no approvable work
left to claim one for.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .coding_config import load_spec
from .coding_contract import CodingError, FactorySpec, canonical_json, strict_json
from .coding_model import LocalToolModel
from .coding_runtime import file_digests, repair, scoped_changes, verify_candidate
from .coding_sandbox import DockerRunner
from .evolve_agents import (
    LedgerModel, RoleBudget, RoleContext, adjudicate_lessons, audit_process,
    describe_implementation, extract_lessons, propose_plan, propose_requirements, review_stage,
)
from .evolve_contract import (
    CANDIDATE_BOUND_STAGES, FAILURE_LEARNING, OPERATIONS, STAGE_ORDER, digest_json,
    process_evidence,
)
from .repositories import snapshot_zip

USAGE = ("usage: python -m oryveta_engine.evolve_child <request-path> "
         "<result-path> [max-seconds [worker-pid]]")

PARENT_POLL_SECONDS = 0.25
ORPHANED_EXIT = 3
DEADLINE_EXIT = 4

MAX_REQUEST_BYTES = 1024 * 1024
# The largest candidate diff a reviewer may be shown whole. A change that does
# not fit is refused rather than reviewed from part of itself: an approval
# resting on a truncated diff would be an approval of unreviewed lines. This
# workflow can honestly ask for a smaller change instead.
MAX_REVIEW_PATCH_BYTES = 8192
# Leave room for the role to answer before its stage deadline.
ROLE_TIME_MARGIN = 5.0


class _Deadline(BaseException):
    """This child's own wall-clock bound expired.

    A `BaseException` so no `except Exception` in a model client, an agent or a
    container helper can absorb the bound the worker handed this process.
    """


def _write_atomically(path: Path, payload: str) -> None:
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=".evolve-", delete=False)
    try:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(handle.name, path)
    except BaseException:
        handle.close()
        with contextlib.suppress(OSError):
            os.unlink(handle.name)
        raise


@contextlib.contextmanager
def _bounded(seconds: float):
    """Interrupt the stage once its own wall-clock bound expires."""
    if seconds <= 0:
        yield
        return

    def expired(*_: object) -> None:
        raise _Deadline()

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _watch_parent(stop: threading.Event, parent: int) -> None:
    """Exit when the worker process that started this stage is gone.

    This process leads its own group, so a worker that dies hard signals
    nothing: the only sign left is the parent PID changing when the kernel
    reparents an orphan. The stage is abandoned without writing a result,
    because nobody is left to record one.
    """
    while not stop.wait(PARENT_POLL_SECONDS):
        if os.getppid() != parent:
            print("the worker process that started this Evolve stage is gone",
                  file=sys.stderr, flush=True)
            os._exit(ORPHANED_EXIT)


# -- request -------------------------------------------------------------


def _request(path: Path) -> dict[str, Any]:
    """Read and bound the stage request the worker prepared."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as handle:
        payload = handle.read(MAX_REQUEST_BYTES + 1)
    if len(payload) > MAX_REQUEST_BYTES:
        raise CodingError("invalid_request", "the stage request exceeds its bounded size")
    try:
        request = strict_json(payload)
    except (ValueError, UnicodeError, RecursionError):
        raise CodingError("invalid_request",
                          "the stage request is not bounded, unambiguous UTF-8 JSON") from None
    if not isinstance(request, dict) or request.get("schema_version") != 1:
        raise CodingError("invalid_request", "unsupported stage request version")
    if request.get("stage") not in OPERATIONS:
        raise CodingError("invalid_stage", "unknown Evolve stage name")
    budget = request.get("budget")
    if not isinstance(budget, dict) or type(budget.get("tokens")) is not int \
            or type(budget.get("role_calls")) is not int:
        raise CodingError("invalid_request", "the stage request carries no bounded budget")
    return request


def _remaining(deadline: float, subject: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= ROLE_TIME_MARGIN:
        raise CodingError("wall_budget", f"no time remains for {subject}")
    return remaining


def _role_seconds(deadline: float, subject: str) -> float:
    return max(1.0, _remaining(deadline, subject) - ROLE_TIME_MARGIN)


def _check_names(spec: FactorySpec) -> tuple[str, ...]:
    """Check names only. What a check expects never leaves this process."""
    return tuple(check.name for check in spec.development_checks + spec.acceptance_checks)


def _outcomes(rows: object) -> list[dict[str, Any]]:
    """Reduce observed check reports to name, kind and outcome.

    A passing check's output is the operator's protected expected output, so a
    model is shown that a check passed and never what it printed.
    """
    if not isinstance(rows, list):
        raise CodingError("invalid_evidence", "a check report file is unusable")
    outcomes = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) \
                or not isinstance(row.get("passed"), bool):
            raise CodingError("invalid_evidence", "a check report row is unusable")
        outcomes.append({"name": row["name"], "kind": row.get("kind"), "passed": row["passed"]})
    return outcomes


def _evidence_file(path: Path) -> object:
    try:
        return strict_json(path.read_bytes())
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise CodingError("invalid_evidence",
                          "a controller evidence file is missing or unusable") from None


def _changed_paths(spec: FactorySpec, source: bytes, candidate: bytes, run_root: Path) -> list[str]:
    """Re-derive the candidate's scope from the two archives' own bytes.

    This repeats the inventory and allowlist decision against the exact
    archives that will be registered, so the recorded change scope comes from
    comparing real trees rather than from anything the editing loop reported.
    """
    with tempfile.TemporaryDirectory(dir=str(run_root), prefix="scope-") as scratch:
        base, proposed = Path(scratch) / "base", Path(scratch) / "candidate"
        snapshot_zip(base, source)
        snapshot_zip(proposed, candidate)
        return scoped_changes(file_digests(base), file_digests(proposed), spec.write_paths)


def _reviewable_patch(patch: str) -> str:
    """The exact diff a reviewer is shown, or a refusal to review part of one.

    A reviewer either sees the whole change or does not review it. Clipping the
    diff would let a bounded context turn into a passing implementation review
    of lines nobody read, which is precisely the approval this workflow must
    not be able to produce. The honest outcome is a durable code: the goal can
    be pursued again as a smaller change.
    """
    if len(patch.encode("utf-8")) > MAX_REVIEW_PATCH_BYTES:
        raise CodingError("review_context_exceeded",
                          "the candidate diff is larger than a reviewer can be shown whole")
    return patch


# -- stages --------------------------------------------------------------


async def _requirements(state: _State) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    proposal = await propose_requirements(
        state.model, state.budget, state.context,
        timeout_seconds=_role_seconds(state.deadline, "the requirements role"),
        rework=state.rework)
    # The goal is passed through from the claim verbatim. The control plane
    # compares it against the stored work item, so a model cannot restate,
    # narrow or extend the change it was asked to deliver.
    artifact = {"goal": state.goal, "acceptance_criteria": list(proposal.acceptance_criteria),
                "constraints": list(proposal.constraints)}
    return artifact, [("Proposed requirements", artifact)]


async def _plan(state: _State) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    requirements = state.prior_artifact("requirements")
    proposal = await propose_plan(
        state.model, state.budget, state.context, requirements=requirements,
        timeout_seconds=_role_seconds(state.deadline, "the plan role"), rework=state.rework)
    # The editable scope is the operator's, restated as a fact rather than
    # chosen by the planner: a model cannot widen what it may edit.
    artifact = {"steps": list(proposal.steps), "allowed_paths": list(state.spec.write_paths),
                "risks": list(proposal.risks)}
    return artifact, [("Approved requirements", requirements), ("Proposed plan", artifact)]


async def _implementation(state: _State) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    """Bounded model-driven editing, then an independent description for review.

    The existing fixed-policy repair loop does the editing: the model gets only
    its allowlisted file tools and the development checks, the runner is the
    operator's pinned image, and the loop refuses a candidate that fails the
    controller's own contracts. Its turns are charged to the same attempt ledger
    as every role, so editing and reviewing share one aggregate budget.
    """
    output = state.evidence / "repair"
    receipt = await repair(state.spec, state.source_zip, state.goal, output, state.run_root,
                           model=LedgerModel(state.model, state.budget, role="executor",
                                             role_call=False),
                           runner=DockerRunner(state.spec.runner),
                           guidance=canonical_json({
                               "requirements": state.prior_artifact("requirements"),
                               "plan": state.prior_artifact("plan"),
                               "approved_lessons": state.context.lessons,
                           }))
    if receipt.get("status") != "needs_review":
        raise CodingError(str(receipt.get("error_code") or "implementation_failed"),
                          "the bounded editing loop produced no reviewable candidate")
    candidate = (output / "candidate.zip").read_bytes()
    patch = (output / "verified.patch").read_text(encoding="utf-8")
    changed = _changed_paths(state.spec, state.source_bytes, candidate, state.run_root)
    outcomes = _outcomes(_evidence_file(output / "verification.json"))
    diff = _reviewable_patch(patch)
    state.produced.update({
        "candidate_path": str(output / "candidate.zip"),
        "patch_path": str(output / "verified.patch"),
        "receipt_path": str(output / "receipt.json"),
        "trace_path": str(output / "events.jsonl"),
    })
    requirements = state.prior_artifact("requirements")
    plan = state.prior_artifact("plan")
    proposal = await describe_implementation(
        state.model, state.budget, state.context, requirements=requirements, plan=plan,
        changed_paths=changed, patch=diff, development_outcomes=outcomes,
        timeout_seconds=_role_seconds(state.deadline, "the implementation role"))
    # The digests are reported from the archive bytes this process wrote, and
    # the worker re-derives both from the bytes it actually uploads and refuses
    # a mismatch, so the recorded identity is never a reported one.
    artifact = {"candidate_sha256": str(receipt.get("candidate_archive_sha256") or ""),
                "patch_sha256": str(receipt.get("patch_sha256") or ""),
                "changed_paths": changed, "summary": proposal.summary}
    state.measured.update({"candidate_sha256": artifact["candidate_sha256"],
                           "patch_sha256": artifact["patch_sha256"], "changed_paths": changed})
    return artifact, [("Approved requirements", requirements), ("Approved plan", plan),
                      ("Files the change touched", changed),
                      ("Exact diff (untrusted data)", diff),
                      ("Controller-observed check outcomes", outcomes)]


async def _verification(state: _State) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    """Independent, model-free re-verification of the candidate archive.

    No model is constructed for the artifact of this stage, and no model claim
    can create it: the existing verifier re-imports both archives, re-proves the
    baseline reproduces the defect and preserves existing behavior, and re-runs
    every configured check in fresh containers. The artifact's types only admit
    an all-passing result, so a failure here cannot be recorded as a success.
    """
    if state.candidate_zip is None:
        raise CodingError("invalid_request", "verification requires the candidate archive")
    output = state.evidence / "verify"
    receipt = await verify_candidate(state.spec, state.source_zip, state.candidate_zip, state.goal,
                                     output, state.run_root,
                                     runner=DockerRunner(state.spec.runner))
    if receipt.get("status") != "needs_review":
        raise CodingError(str(receipt.get("error_code") or "verification_failed"),
                          "independent verification did not accept the candidate")
    final = _outcomes(_evidence_file(output / "verification.json"))
    baseline = _outcomes(_evidence_file(output / "baseline.json"))
    # Re-derived from the evidence files rather than assumed from the verifier
    # reaching its end, so each recorded claim has its own observation behind it.
    reproduced = sorted(row["name"] for row in baseline
                        if not row["passed"] and row["kind"] == "regression")
    preserved = (all(row["passed"] for row in baseline if row["kind"] == "preserve")
                 and all(row["passed"] for row in final if row["kind"] == "preserve"))
    if not reproduced:
        raise CodingError("not_reproduced", "the baseline did not reproduce the requested defect")
    if not preserved:
        raise CodingError("invalid_baseline", "existing behavior was not preserved")
    if not all(row["passed"] for row in final):
        raise CodingError("verification_failed", "a configured check did not pass")
    checks = [{"name": row["name"], "passed": row["passed"]} for row in final]
    state.measured.update({"candidate_sha256": str(receipt.get("candidate_archive_sha256") or ""),
                           "reproduced_failures": reproduced,
                           "check_names": [row["name"] for row in final]})
    state.produced.update({"receipt_path": str(output / "receipt.json"),
                           "trace_path": str(output / "events.jsonl")})
    artifact = {"candidate_sha256": state.measured["candidate_sha256"], "checks": checks,
                "baseline_reproduced": True, "preservation_passed": True,
                "verification": "passed"}
    return artifact, [
        ("Independent check outcomes (controller-measured)", final),
        ("Baseline checks that reproduced the defect before any edit", reproduced),
        ("Implementation record under verification", state.prior_artifact("implementation")),
        ("Approved requirements", state.prior_artifact("requirements"))]


async def _audit(state: _State) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    required = list(STAGE_ORDER[:STAGE_ORDER.index("audit")])
    evidence = process_evidence(state.prior)
    proposal = await audit_process(
        state.model, state.budget, state.context, recorded_stages=evidence,
        required_stages=required,
        timeout_seconds=_role_seconds(state.deadline, "the audit role"))
    artifact = {"candidate_sha256": state.candidate_sha256, "required_stages": required,
                "violations": list(proposal.violations), "summary": proposal.summary}
    return artifact, [("Required stages, in order", required),
                      ("Exact recorded stage evidence", evidence),
                      ("Proposed audit", artifact)]


async def _learning(state: _State) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    evidence = process_evidence(state.prior)
    proposal = await extract_lessons(
        state.model, state.budget, state.context, recorded_stages=evidence, outcome=state.outcome,
        timeout_seconds=_role_seconds(state.deadline, "the learning role"))
    lessons = [{"summary": lesson.summary, "applicability": lesson.applicability,
                "evidence_ids": list(lesson.evidence_ids),
                "counterexamples": list(lesson.counterexamples)} for lesson in proposal.lessons]
    artifact = {"candidate_sha256": state.candidate_sha256, "lessons": lessons}
    return artifact, [("Run outcome", state.outcome),
                      ("Candidate lessons under review", lessons),
                      ("Exact recorded stage evidence", evidence)]


async def _learning_review(state: _State) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    lessons = state.prior_artifact("learning").get("lessons") or []
    if not lessons:
        # Nothing was extracted, so there is nothing to adjudicate and no model
        # is asked to. An empty decision set is the honest record.
        artifact: dict[str, Any] = {"candidate_sha256": state.candidate_sha256, "decisions": []}
        return artifact, [("Candidate lessons, by index", []), ("Adjudicated decisions", [])]
    proposal = await adjudicate_lessons(
        state.model, state.budget, state.context, lessons=lessons,
        recorded_stages=process_evidence(state.prior),
        timeout_seconds=_role_seconds(state.deadline, "the learning review role"))
    decisions = [{"index": item.index, "verdict": item.verdict, "reason": item.reason}
                 for item in proposal.decisions]
    if sorted(item["index"] for item in decisions) != list(range(len(lessons))):
        # Exactly one decision for each candidate. A missing or duplicated
        # index would leave an unvetted lesson eligible for activation.
        raise CodingError("learning_undecided",
                          "every candidate lesson needs exactly one decision")
    artifact = {"candidate_sha256": state.candidate_sha256, "decisions": decisions}
    return artifact, [("Candidate lessons, by index", lessons),
                      ("Adjudicated decisions", decisions)]


async def _failure_learning(state: _State, reviewer: LocalToolModel,
                            observed: dict[str, Any]) -> dict[str, Any]:
    """Extract and independently adjudicate lessons from an attempt that failed.

    This is not a stage and it produces no artifact. It reads exactly what the
    attempt recorded, which for a refused run includes the review that refused
    a stage and the findings it rested on, and it is told the failure it is
    reasoning about. Extraction and adjudication are separate role calls in
    separate contexts, drawn from the same aggregate ledger and the same
    remaining deadline as every other role in this attempt.

    An empty extraction is reviewed too: a completed report must not attribute
    a review to a model that was never called.

    Nothing here can promote a lesson. The worker records these as diagnostic
    candidates on a failed run, and only a human approving a successful run
    ever activates a lesson.
    """
    evidence = process_evidence(state.prior)
    if state.failure_checks:
        evidence["observed_failed_attempt_checks"] = state.failure_checks
    proposal = await extract_lessons(
        state.model, state.budget, state.context, recorded_stages=evidence,
        outcome=state.outcome,
        timeout_seconds=_role_seconds(state.deadline, "the failure learning role"))
    lessons = [{"summary": lesson.summary, "applicability": lesson.applicability,
                "evidence_ids": list(lesson.evidence_ids),
                "counterexamples": list(lesson.counterexamples)} for lesson in proposal.lessons]
    adjudicated = await adjudicate_lessons(
        reviewer, state.budget, state.context, lessons=lessons,
        recorded_stages=evidence,
        timeout_seconds=_role_seconds(state.deadline, "the failure learning review role"))
    decisions = [{"index": item.index, "verdict": item.verdict, "reason": item.reason}
                 for item in adjudicated.decisions]
    if sorted(item["index"] for item in decisions) != list(range(len(lessons))):
        raise CodingError("learning_undecided",
                          "every candidate lesson needs exactly one decision")
    return {"schema_version": 1, "stage": FAILURE_LEARNING, "status": "ok", "error_code": None,
            "lessons": lessons, "decisions": decisions,
            "reviewer_model": str(observed["name"]), "reviewer_digest": str(observed["digest"]),
            "usage": state.budget.usage()}


STAGES = {"requirements": _requirements, "plan": _plan, "implementation": _implementation,
          "verification": _verification, "audit": _audit, "learning": _learning,
          "learning_review": _learning_review}


class _State:
    """One stage's resolved inputs, measurements and shared budget."""

    def __init__(self, request: dict[str, Any], spec: FactorySpec, model: LocalToolModel,
                 deadline: float):
        self.spec = spec
        self.model = model
        self.deadline = deadline
        self.stage: str = request["stage"]
        self.goal: str = request["goal"]
        self.outcome: str = request.get("outcome") or "candidate accepted for human review"
        self.rework: list[str] = list(request.get("rework") or [])
        self.prior: dict[str, dict[str, Any]] = dict(request.get("prior") or {})
        self.failure_checks = list(request.get("failure_checks") or [])
        self.candidate_sha256: str = str(request.get("candidate_sha256") or "")
        self.source_zip = Path(request["source_zip"])
        self.candidate_zip = Path(request["candidate_zip"]) if request.get("candidate_zip") \
            else None
        self.evidence = Path(request["evidence_dir"])
        self.run_root = Path(request["run_root"])
        self.budget = RoleBudget(request["budget"]["tokens"], request["budget"]["role_calls"])
        self.measured: dict[str, Any] = {}
        self.produced: dict[str, Any] = {}
        self.context = RoleContext(
            goal=self.goal, read_paths=spec.read_paths, write_paths=spec.write_paths,
            check_names=_check_names(spec), evidence_catalogue=list(request.get("catalogue") or []),
            lessons=str(request.get("lessons") or ""))
        self._source_bytes: bytes | None = None

    @property
    def source_bytes(self) -> bytes:
        """The pinned archive's own bytes, read only by the stage that needs them."""
        if self._source_bytes is None:
            self._source_bytes = self.source_zip.read_bytes()
        return self._source_bytes

    def prior_artifact(self, stage: str) -> dict[str, Any]:
        payload = self.prior.get(stage)
        if not isinstance(payload, dict) or not isinstance(payload.get("artifact"), dict):
            raise CodingError("invalid_request", f"the recorded {stage} artifact is missing")
        return payload["artifact"]


def _own_references(stage: str, artifact: dict[str, Any], measured: dict[str, Any]) -> list[str]:
    """The references this stage's own record makes resolvable for its reviewer.

    A reviewer may cite the stage artifact it is reviewing, and from the
    implementation stage on, the candidate and patch digests that are registered
    before the stage row exists. Nothing else is added here: every other
    admissible reference was already recorded, and the worker re-checks the
    whole cited set against its own index before anything is persisted.
    """
    if stage in CANDIDATE_BOUND_STAGES:
        references = [f"artifact:{measured.get('candidate_sha256') or artifact['candidate_sha256']}"]
        if stage == "implementation":
            references.append(f"artifact:{artifact['patch_sha256']}")
        if stage == "verification":
            references.extend(f"check:{name}" for name in measured.get("check_names") or [])
        return references
    return [f"artifact:{digest_json(artifact)}"]


async def execute(request: dict[str, Any]) -> dict[str, Any]:
    """Run one operation: a stage and its independent review, or failure learning."""
    spec = load_spec(request["config_path"])
    review_path = request.get("review_config_path")
    review_spec = load_spec(review_path) if review_path else spec
    deadline = time.monotonic() + float(request["deadline_seconds"])
    model = LocalToolModel(spec.model)
    separate = review_spec is not spec
    reviewer = LocalToolModel(review_spec.model) if separate else model
    state = _State(request, spec, model, deadline)
    # Prove the pinned models are installed and locally served before spending
    # the stage on them, so an unavailable model fails honestly and early. The
    # repair loop performs its own verification for the executor.
    observed = await model.verify()
    if separate:
        observed = await reviewer.verify()
    if state.stage == FAILURE_LEARNING:
        # The diagnostic side branch: no stage artifact exists to review, and
        # the independent review here is the lesson adjudication itself.
        return await _failure_learning(state, reviewer, observed)

    artifact, sections = await STAGES[state.stage](state)
    # The reviewer is a fresh agent in a context that also admits this stage's
    # own identity; the author never saw these references.
    review_context = replace(state.context, evidence_catalogue=sorted(set(
        state.context.evidence_catalogue + _own_references(state.stage, artifact,
                                                           state.measured))))
    review = await review_stage(
        reviewer, state.budget, review_context, stage=state.stage, sections=sections,
        timeout_seconds=_role_seconds(deadline, f"the {state.stage} review role"))
    return {
        "schema_version": 1, "stage": state.stage, "status": "ok", "error_code": None,
        "artifact": artifact,
        "review": {"verdict": review.verdict, "summary": review.summary,
                   "evidence_ids": list(review.evidence_ids),
                   "findings": [{"severity": item.severity, "detail": item.detail,
                                 "evidence_id": item.evidence_id} for item in review.findings]},
        "reviewer_model": str(observed["name"]), "reviewer_digest": str(observed["digest"]),
        "measured": state.measured, "produced": state.produced,
        "usage": state.budget.usage(),
    }


def _failure(stage: str, error: BaseException, usage: dict[str, int] | None) -> dict[str, Any]:
    """An honest durable failure record; never a fabricated stage result."""
    if isinstance(error, CodingError):
        code, details = error.code, error.details
    elif isinstance(error, asyncio.CancelledError):
        code, details = "cancelled", {}
    elif isinstance(error, asyncio.TimeoutError):
        code, details = "wall_budget", {}
    elif isinstance(error, OSError):
        code, details = "worker_storage_error", {}
    else:
        code, details = "stage_internal_error", {"failure": type(error).__name__}
    return {"schema_version": 1, "stage": stage, "status": "failed", "error_code": code,
            "artifact": None, "review": None, "reviewer_model": None, "reviewer_digest": None,
            "measured": {}, "produced": {}, "usage": usage or {"tokens": 0, "role_calls": 0},
            "details": details}


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else list(argv)
    if not 2 <= len(arguments) <= 4:
        print(USAGE, file=sys.stderr)
        return 2
    request_path, output = Path(arguments[0]), Path(arguments[1])
    try:
        max_seconds = float(arguments[2]) if len(arguments) >= 3 else 0.0
        parent = int(arguments[3]) if len(arguments) == 4 else os.getppid()
    except ValueError:
        print(USAGE, file=sys.stderr)
        return 2
    if max_seconds < 0 or parent <= 0:
        print(USAGE, file=sys.stderr)
        return 2
    if not output.parent.is_dir():
        print("result directory does not exist", file=sys.stderr)
        return 2
    # The caller supplies its PID because it may die before this interpreter
    # starts. Sampling getppid() in the watcher would adopt the orphan reaper.
    if os.getppid() != parent:
        return ORPHANED_EXIT
    stage = "unknown"
    stop = threading.Event()
    threading.Thread(target=_watch_parent, args=(stop, parent), daemon=True).start()
    try:
        with _bounded(max_seconds):
            request = _request(request_path)
            stage = request["stage"]
            result = asyncio.run(execute(request))
    except _Deadline:
        print(f"Evolve stage exceeded its own {max_seconds:g}s bound", file=sys.stderr)
        return DEADLINE_EXIT
    except (CodingError, OSError, ValueError, UnicodeError, RecursionError) as error:
        # A refused or failed stage is a result the worker must be able to
        # record honestly, so it is written rather than left to a bare exit
        # code. The message is operator-only; only the code is ever persisted.
        print(f"Evolve stage {stage} failed: {type(error).__name__}: {error}",
              file=sys.stderr, flush=True)
        if os.getppid() != parent:
            return ORPHANED_EXIT
        _write_atomically(output, json.dumps(_failure(stage, error, None), separators=(",", ":")))
        return 0
    finally:
        stop.set()
    if os.getppid() != parent:
        return ORPHANED_EXIT
    _write_atomically(output, json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
