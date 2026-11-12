"""Durable project-scoped worker for the reviewed Evolve workflow.

One attempt takes a queued `evolve` work item from the project's existing work
queue to `awaiting_approval`: it pins the project's frozen public source, then
runs requirements, plan, implementation, verification, audit, learning and
learning review, recording each stage with an independent review, and registers
the exact candidate a human may approve. It publishes nothing. Approval is a
human decision on a named candidate digest, and no model in this workflow can
reach it.

Authority stays with this controller and with the control plane:

* Every stage that spends inference or starts a container runs in a supervised
  child process with a minimal environment. The worker's credential, session and
  lease token never enter that environment, a model, or a container.
* The worker heartbeats while a child runs. A cancelled, revoked or stolen lease
  terminates the child's whole process group and publishes nothing; it does not
  even report a failure, because the attempt no longer owns the run.
* Digests are taken from the bytes this worker uploads, never from a child's
  report, and the two are compared. Cited evidence is checked against what this
  worker actually recorded and registered.
* An interrupted attempt is never resumed. A new attempt re-fetches the same
  pinned commit into a fresh private directory and starts from the immutable
  inputs; no earlier trace, receipt or candidate is carried forward.
* A model that is unavailable, drifts from its pinned digest, or cannot answer
  in contract produces a durable, honest failure. Nothing fabricates a passing
  review, and a stage whose review does not pass is recorded as it stands and
  then fails the run.

A failed attempt records one further thing before it fails: a bounded failure
report naming where it stopped, the real outcomes of the controller's own
checks as this worker observed them, and whether failure learning actually ran.
That branch is attempted only while this worker still holds the lease, still
has a pinned snapshot to reason about and still has budget left; otherwise the
report says plainly that learning was unavailable and why. Nothing it produces
is a stage, a candidate or an approvable artifact, and a lesson drawn from a
failure stays a diagnostic candidate.

Private evidence (full receipts, traces, archives and container output) stays in
the worker's own run directory. Only sanitized, bounded artifacts are uploaded,
because a passing check's output is the operator's protected expected output.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .coding_config import load_spec
from .coding_contract import CheckSpec, CodingError, FactorySpec, canonical_json, strict_json
from .coding_sandbox import control_environment
from .evolve_contract import (
    CANDIDATE_BOUND_STAGES, FAILURE_LEARNING, MAX_REPORT_CHECKS, NONRETRYABLE_CODES, PHASES,
    STAGE_ORDER, CheckOutcome, EvidenceIndex, digest_json, failure_report, review_record,
    sanitize_receipt, sanitize_trace_event, stage_payload, typed, ReviewProposal,
)
from .evolve_lessons import approved_lessons, lesson_block
from .evolve_storage import EvolveArtifactStore
from .factory_runtime import (
    CHILD_DEADLINE_GRACE_SECONDS, CREDENTIALS_ENV, DEFAULT_LEASE_SECONDS, DEFAULT_POLL_SECONDS,
    HEARTBEAT_RETRY_BACKOFF_SECONDS, LEASE_RETRY_MARGIN_SECONDS, MAX_CHILD_ERROR_BYTES,
    MAX_CONSECUTIVE_CLAIM_FAILURES, MAX_HEARTBEAT_INTERVAL, MAX_HEARTBEAT_RETRIES,
    MAX_LEASE_SECONDS, MIN_LEASE_SECONDS, RUN_DIRECTORY_PREFIX, RUN_MARKER_NAME,
    SOURCE_CONFLICT_REFUSALS, TERMINATE_GRACE_SECONDS, ControlPlaneUnavailable, CredentialError,
    FactoryRuntimeClient, FactoryRuntimeError, SourceCommitUnresolved, SourceIdentityConflict,
    WorkerCredentials, _signal_analysis_group, archive_commit, error_code, lease_seconds_left,
    minimal_child_environment,
)
from .repositories import InvalidRepository, fetch_public_github_repo, parse_github_url

# The whole attempt, not one stage: seven stages share this bound, and each
# child gets what is left of it.
DEFAULT_MAX_RUN_SECONDS = 1800
# Bounded aggregate rework. A review that still refuses after this many
# corrections is a verdict about the work, not a transient wobble.
DEFAULT_MAX_REWORK = 1
# Explicit aggregate ceiling on model calls for a whole attempt, covering every
# author role, every independent review and every rework round. The token
# ceiling is the operator configuration's own `limits.total_tokens`.
DEFAULT_MAX_ROLE_CALLS = 48

MAX_CHILD_RESULT_BYTES = 256 * 1024
# A published trace is a bounded, sanitized manifest; the complete trace stays
# in the worker's private evidence directory.
MAX_PUBLISHED_TRACE_BYTES = 768 * 1024
MAX_TRACE_LINES = 4000

CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{2,47}")
# A refusal the next round of the same stage could plausibly fix.
REWORK_CODES = frozenset({"role_output_invalid", "evidence_unknown", "learning_undecided",
                          "invalid_review", "invalid_stage_artifact"})
# When the model itself is what failed, a further extraction call would only
# fail the same way; the honest record is that no learning was available.
MODEL_FAILURE_CODES = frozenset({
    "model_unavailable", "model_changed", "model_timeout", "provider_contract",
    "role_output_invalid",
})
# When the attempt ran out of its aggregate allowance or its clock, there is
# nothing left to spend on learning either.
BUDGET_FAILURE_CODES = frozenset({
    "token_budget", "role_budget", "wall_budget", "context_budget", "evolve_timeout",
})
# A child whose own work was cut short. Spending a further model call on an
# interrupted attempt is exactly what must not happen.
INTERRUPTED_CODES = frozenset({"cancelled"})
# When this worker's own standing has ended, it spends no inference at all: it
# may not even be permitted to record the report it is building.
AUTHORITY_FAILURE_CODES = frozenset({"worker_credentials_rejected"})
# Below this, the remaining attempt deadline cannot fund a supervised child and
# the role deadline inside it; `budget_exhausted` is the honest answer.
MIN_LEARNING_SECONDS = 20

# What the learning role is told about a successful attempt's outcome. A failed
# attempt is given its own, equally factual sentence.
APPROVABLE_OUTCOME = "candidate accepted for human review"

ORPHANED_EXIT = 3
DEADLINE_EXIT = 4


class EvolveStageRejected(FactoryRuntimeError):
    """A stage's own contract or its independent review refused the attempt."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class EvolveTimeout(FactoryRuntimeError):
    """The attempt exceeded its bounded whole-run time."""


class EvolveProcessError(FactoryRuntimeError):
    """A supervised stage child exited without a usable result."""


def evolve_error_code(exception: BaseException) -> str:
    """Map a failure onto a short enumerated code the control plane accepts.

    Only codes are persisted, so an exception message, a host path, a container
    name or a credential can never reach a stored row.
    """
    if isinstance(exception, EvolveStageRejected):
        return exception.code if CODE_PATTERN.fullmatch(exception.code) else "process_rejected"
    if isinstance(exception, CodingError):
        return exception.code if CODE_PATTERN.fullmatch(exception.code) else "worker_error"
    if isinstance(exception, EvolveTimeout):
        return "evolve_timeout"
    if isinstance(exception, EvolveProcessError):
        return "evolve_process_failed"
    return error_code(exception)


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _private_file(path: Path, payload: bytes) -> Path:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return path


def sanitized_trace(paths: list[Path]) -> bytes:
    """Project private run traces into one bounded publishable manifest.

    Each event is reduced to its publishable projection, and observed check
    text is dropped rather than trimmed: a passing check prints exactly the
    operator's protected expected output, so publishing it would publish the
    answer. Truncation is recorded instead of being silent.
    """
    rows: list[str] = []
    size = 0
    truncated = False
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines[:MAX_TRACE_LINES]:
            if not line.strip():
                continue
            try:
                event = strict_json(line)
            except (ValueError, UnicodeError, RecursionError):
                continue
            projected = sanitize_trace_event(event)
            if projected is None:
                continue
            projected["source"] = path.parent.name
            row = canonical_json(projected)
            if size + len(row) + 1 > MAX_PUBLISHED_TRACE_BYTES:
                truncated = True
                break
            rows.append(row)
            size += len(row) + 1
        if len(lines) > MAX_TRACE_LINES:
            truncated = True
        if truncated:
            break
    if truncated:
        rows.append(canonical_json({"kind": "trace_truncated",
                                    "detail": "the published trace reached its bounded size"}))
    return ("\n".join(rows) + "\n").encode("utf-8")


def _check_names(spec: FactorySpec) -> tuple[CheckSpec, ...]:
    return spec.development_checks + spec.acceptance_checks


# The controller-written check reports a stage child leaves in this worker's
# private evidence tree, in the order a later one supersedes an earlier one:
# the independent verifier's final run first, then its baseline, then the
# editing loop's own. Both `repair` and `verify_candidate` write these files
# before refusing a candidate, so a failed verification has real outcomes on
# disk even though it has no recordable verification artifact.
_CHECK_REPORTS: tuple[str, ...] = ("verify/verification.json", "verify/baseline.json",
                                   "repair/verification.json", "repair/baseline.json")


def _observed_outcomes(rows: object) -> list[dict[str, Any]]:
    """Reduce one controller-written check report to bounded outcomes.

    A name and a pass flag, and nothing else: a passing check's output is the
    operator's protected expected output, and an exit code, a duration or a
    path is not an outcome a failure report needs. A row that does not satisfy
    the check-outcome contract is dropped rather than guessed at.
    """
    if not isinstance(rows, list):
        return []
    outcomes: dict[str, dict[str, Any]] = {}
    for row in rows:
        if len(outcomes) >= MAX_REPORT_CHECKS:
            break
        if not isinstance(row, dict):
            continue
        try:
            outcome = typed(CheckOutcome, {"name": row.get("name"), "passed": row.get("passed")},
                            "invalid_evidence", "an observed check outcome")
        except CodingError:
            continue
        outcomes.setdefault(str(outcome.name), outcome.model_dump(mode="json"))
    return list(outcomes.values())


def _check_report(path: Path) -> list[dict[str, Any]]:
    try:
        return _observed_outcomes(strict_json(path.read_bytes()))
    except (OSError, ValueError, UnicodeError, RecursionError):
        return []


def _passed(payload: dict[str, Any] | None) -> bool:
    """Whether a recorded stage payload carries a passing review."""
    if not isinstance(payload, dict):
        return False
    review = payload.get("review")
    return isinstance(review, dict) and review.get("verdict") == "pass"


def _unavailable_reason(code: str) -> str | None:
    """Why this code already rules out failure learning, when it does.

    A model that cannot be reached or cannot answer in contract would answer
    an extraction call exactly the same way; an exhausted token, call or
    wall-clock allowance cannot fund one; an interrupted child and a worker
    whose standing has ended must not be given one at all. `None` means the
    failure says nothing about learning either way, so it may be attempted.
    """
    if code in MODEL_FAILURE_CODES:
        return "model_unavailable"
    if code in BUDGET_FAILURE_CODES:
        return "budget_exhausted"
    if code in INTERRUPTED_CODES:
        return "worker_interrupted"
    if code in AUTHORITY_FAILURE_CODES:
        return "authority_lost"
    return None


def _failure_outcome(code: str, failed_stage: str, rejected: str | None) -> str:
    """What the learning roles are told about an attempt that failed.

    Observable facts only: the code this run will fail with, where it stopped,
    and which review refused it when one did. The roles are also told plainly
    that nothing here is approvable, so a lesson cannot be written as though it
    were describing accepted work.
    """
    refusal = f", where its {rejected} review refused it" if rejected else ""
    return (f"this attempt failed with {code} at the {failed_stage} stage{refusal}; "
            "no candidate is approvable and no lesson drawn from it can be activated")


@dataclass
class EvolveRuntimeWorker:
    """Claims and completes one project's reviewed Evolve work items."""

    client: FactoryRuntimeClient
    project_id: str
    config_path: Path
    work_root: Path
    review_config_path: Path | None = None
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    max_run_seconds: int = DEFAULT_MAX_RUN_SECONDS
    poll_seconds: float = DEFAULT_POLL_SECONDS
    max_rework: int = DEFAULT_MAX_REWORK
    max_role_calls: int = DEFAULT_MAX_ROLE_CALLS
    store: EvolveArtifactStore | None = None
    spec: FactorySpec = field(init=False)
    # The reviewer's own trusted configuration, which is the main one unless the
    # operator pinned a separate reviewing model. Kept so this worker can check
    # a reported reviewer identity against the identity it actually pinned.
    review_spec: FactorySpec = field(init=False)

    def __post_init__(self) -> None:
        if not MIN_LEASE_SECONDS <= self.lease_seconds <= MAX_LEASE_SECONDS:
            raise ValueError(
                f"lease seconds must be between {MIN_LEASE_SECONDS} and {MAX_LEASE_SECONDS}")
        if self.max_run_seconds < 1:
            raise ValueError("maximum run seconds must be positive")
        if self.max_rework < 0 or self.max_role_calls < 1:
            raise ValueError("rework and role-call ceilings must be nonnegative and positive")
        # The trusted operator specification is loaded here, from a path outside
        # any imported source, so the model, runner, scope, budgets and checks
        # are fixed before a work item is claimed.
        self.config_path = Path(self.config_path).absolute()
        self.spec = load_spec(self.config_path)
        if self.review_config_path is None:
            self.review_spec = self.spec
        else:
            self.review_config_path = Path(self.review_config_path).absolute()
            self.review_spec = load_spec(self.review_config_path)
        self.work_root = Path(self.work_root).absolute()

    # -- registration -----------------------------------------------------
    def verify_registration(self) -> dict:
        """Prove this worker identity's grant before any work is claimed."""
        rows = self.client.select("project_workers", {
            "project_id": f"eq.{self.project_id}",
            "worker_user_id": f"eq.{self.client.worker_user_id()}",
            "select": "id,label,enabled",
        })
        enabled = [row for row in rows if row.get("enabled")]
        if not enabled:
            raise FactoryRuntimeError(
                "this worker identity has no enabled registration for the requested project; "
                "a project owner or admin must call register_project_worker")
        return enabled[0]

    # -- transitions ------------------------------------------------------
    def claim(self) -> dict | None:
        return self.client.rpc_row("claim_evolve_work", {
            "p_project_id": self.project_id, "p_lease_seconds": self.lease_seconds,
        })

    def heartbeat(self, claim: dict, *, phase: str | None = None, source_ref: str | None = None,
                  source_commit: str | None = None, source_digest: str | None = None) -> dict:
        if phase is not None and phase not in PHASES:
            raise CodingError("invalid_phase", "unknown Evolve heartbeat phase")
        try:
            state = self.client.rpc_row("heartbeat_evolve_run", {
                "p_run_id": claim["run_id"],
                "p_lease_token": claim["lease_token"],
                "p_phase": phase,
                "p_source_ref": source_ref,
                "p_source_commit": source_commit,
                "p_source_digest": source_digest,
                "p_lease_seconds": self.lease_seconds,
            })
        except FactoryRuntimeError as exception:
            # A refused identity means another attempt pinned this work item
            # first, or this attempt already recorded a different identity.
            if any(refusal in str(exception) for refusal in SOURCE_CONFLICT_REFUSALS):
                raise SourceIdentityConflict(
                    "the control plane refused this attempt's source identity") from exception
            raise
        if state is None:
            raise FactoryRuntimeError("heartbeat returned no run state")
        return state

    def _heartbeat_inside_lease(self, claim: dict, expires_at: str | None,
                                **fields: object) -> dict:
        """Heartbeat, absorbing a brief control-plane outage.

        An unreachable control plane is not a reason to abandon an attempt that
        still holds minutes of lease, so the call is retried while the lease
        has room for another try. Once that room is gone the attempt is given
        up and the lease expires, which is what makes it reclaimable.
        """
        attempts = 0
        while True:
            try:
                return self.heartbeat(claim, **fields)
            except ControlPlaneUnavailable:
                attempts += 1
                needed = LEASE_RETRY_MARGIN_SECONDS + HEARTBEAT_RETRY_BACKOFF_SECONDS
                if (attempts > MAX_HEARTBEAT_RETRIES
                        or lease_seconds_left(expires_at) <= needed):
                    raise
                print(f"run {claim['run_id']} heartbeat retrying: "
                      "the control plane is unreachable", flush=True)
                time.sleep(HEARTBEAT_RETRY_BACKOFF_SECONDS)

    def _fence(self, claim: dict, lease: str | None, **fields: object) -> str | None:
        """Heartbeat and report the renewed lease, or None once fenced out.

        None means this attempt no longer owns the run: it stops without
        finishing, failing or publishing anything, and the lease expiry is what
        makes the work item reclaimable.
        """
        state = self._heartbeat_inside_lease(claim, lease, **fields)
        if not state.get("lease_valid"):
            print(f"run {claim['run_id']} stopped: {state.get('reason', 'lease_lost')}", flush=True)
            return None
        return state.get("lease_expires_at") or lease

    # -- supervision ------------------------------------------------------
    def child_command(self, request_path: Path, result_path: Path, seconds: int) -> list[str]:
        """The stage child's argument vector, as an overridable seam.

        The child carries its own wall-clock bound a little past the worker's,
        so a worker that is killed hard still leaves a child that stops by
        itself without pre-empting the worker's own timeout.
        """
        bound = int(seconds + CHILD_DEADLINE_GRACE_SECONDS)
        return [sys.executable, "-m", "oryveta_engine.evolve_child",
                str(request_path), str(result_path), str(bound), str(os.getpid())]

    def child_environment(self, directory: Path) -> dict[str, str]:
        """The only environment a stage child sees.

        It starts from the worker's minimal child environment, which inherits
        nothing, and adds exactly the Docker CLI policy the sandbox already
        defines: a usable PATH, a HOME and the operator's approved
        configuration directory, so a named context resolves. That policy emits
        nothing else, so no credential, session, Supabase origin, lease token
        or proxy setting can reach the child, a model or a container.
        """
        environment = minimal_child_environment(directory)
        environment.update(control_environment())
        return environment

    @staticmethod
    def _terminate(child: subprocess.Popen) -> None:
        """Stop the owned process group, even if its original leader exited."""
        _signal_analysis_group(child, signal.SIGTERM)
        try:
            child.wait(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        finally:
            _signal_analysis_group(child, signal.SIGKILL)
            child.wait()

    @staticmethod
    def _child_error(path: Path) -> str:
        try:
            with path.open("rb") as handle:
                return handle.read(MAX_CHILD_ERROR_BYTES).decode("utf-8", "replace")
        except OSError:
            return "the Evolve stage child produced no diagnostics"

    def _supervise(self, claim: dict, operation: str, directory: Path, request: dict[str, Any],
                   lease: str | None, seconds: int, *,
                   phase: str | None) -> dict[str, Any] | None:
        """Run one supervised child while holding the lease, or stop when fenced.

        `phase` is what the control plane is told while the child runs, and it
        is not the operation's name: the diagnostic failure-learning branch is
        not a phase this workflow has, so it passes None and leaves the run's
        last phase exactly as it stands.

        Returning None means the lease was lost while the child was running:
        the child's whole process group is terminated and no result is read,
        because this attempt may no longer record anything.
        """
        request_path = _private_file(directory / "request.json",
                                     (canonical_json(request) + "\n").encode("utf-8"))
        result_path = directory / "result.json"
        error_path = directory / "child-stderr.log"
        command = self.child_command(request_path, result_path, seconds)
        interval = max(1.0, min(self.lease_seconds / 3.0, MAX_HEARTBEAT_INTERVAL))
        deadline = time.monotonic() + seconds
        with error_path.open("wb") as errors:
            child = subprocess.Popen(
                command, cwd=str(directory), env=self.child_environment(directory),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                # The child leads its own process group, so fencing can stop a
                # model call and a container and never the worker itself.
                start_new_session=True)
            try:
                while True:
                    try:
                        remaining = max(0.0, deadline - time.monotonic())
                        code = child.wait(timeout=min(interval, remaining))
                        if time.monotonic() >= deadline:
                            raise EvolveTimeout("the attempt exceeded its bounded runtime")
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    if time.monotonic() >= deadline:
                        self._terminate(child)
                        raise EvolveTimeout("the attempt exceeded its bounded runtime")
                    state = self._heartbeat_inside_lease(claim, lease, phase=phase)
                    lease = state.get("lease_expires_at") or lease
                    if not state.get("lease_valid"):
                        # Cancellation, revocation or a stolen lease: stop the
                        # inference and the containers, publish nothing, and do
                        # not spend a further model call on this attempt.
                        self._terminate(child)
                        print(f"run {claim['run_id']} terminated the {operation} child: "
                              f"{state.get('reason', 'lease_lost')}", flush=True)
                        return None
            finally:
                self._terminate(child)
        if code == ORPHANED_EXIT:
            raise EvolveProcessError("the Evolve stage child lost its worker")
        if code == DEADLINE_EXIT:
            raise EvolveTimeout("the Evolve stage child exceeded its own bound")
        if code != 0:
            print(self._child_error(error_path), flush=True)
            raise EvolveProcessError(f"the Evolve stage child exited with status {code}")
        try:
            size = result_path.stat().st_size
        except OSError as exception:
            raise EvolveProcessError("the Evolve stage child wrote no result") from exception
        if size > MAX_CHILD_RESULT_BYTES:
            raise EvolveProcessError("the Evolve stage result is implausibly large")
        result = strict_json(result_path.read_bytes())
        if not isinstance(result, dict) or result.get("stage") != operation:
            raise EvolveProcessError("the Evolve stage result does not match its request")
        return result

    # -- the attempt ------------------------------------------------------
    def run_once(self) -> bool:
        claim = self.claim()
        if claim is None:
            return False
        print(f"claimed Evolve run {claim['run_id']} attempt {claim['attempt']}"
              f"/{claim['max_attempts']}", flush=True)
        self._execute(claim)
        return True

    def forever(self, max_runs: int | None = None) -> int:
        """Claim and complete work until stopped, or until it cannot work."""
        completed = 0
        failures = 0
        print(f"Oryveta Evolve worker ready for project {self.project_id}; "
              "press Ctrl+C to stop", flush=True)
        while max_runs is None or completed < max_runs:
            try:
                worked = self.run_once()
            except CredentialError:
                raise
            except Exception:
                traceback.print_exc()
                self._confirm_authority()
                failures += 1
                if failures >= MAX_CONSECUTIVE_CLAIM_FAILURES:
                    print(f"stopping after {failures} consecutive failures", flush=True)
                    raise
                time.sleep(self.poll_seconds)
                continue
            failures = 0
            if worked:
                completed += 1
            else:
                time.sleep(self.poll_seconds)
        return completed

    def _confirm_authority(self) -> None:
        try:
            self.verify_registration()
        except ControlPlaneUnavailable:
            return

    def _execute(self, claim: dict) -> None:
        _private_directory(self.work_root)
        directory = Path(tempfile.mkdtemp(prefix=RUN_DIRECTORY_PREFIX, dir=str(self.work_root)))
        progress = _Progress()
        try:
            self._mark_run_directory(claim, directory)
            self._evolve(claim, directory, progress)
        except Exception as exception:
            code = evolve_error_code(exception)
            # The traceback is operator-only; only the short code is persisted.
            traceback.print_exc()
            print(f"Evolve run {claim['run_id']} failed: {code}", flush=True)
            # The diagnostic report is recorded first, while this attempt still
            # holds the lease that lets it record anything at all. The failure
            # itself is reported afterwards and keeps the original code.
            self._record_failure_report(claim, progress, code)
            self._report_failure(claim, code)
        finally:
            # The private evidence tree is deliberately kept: it is the only
            # complete record of what ran, and it is the operator's, not the
            # project's. Only the sandbox scratch is removed here.
            shutil.rmtree(directory / "sandbox", ignore_errors=True)

    @staticmethod
    def _mark_run_directory(claim: dict, directory: Path) -> None:
        """Name the attempt that owns this tree, for a later startup sweep."""
        (directory / RUN_MARKER_NAME).write_text(json.dumps({
            "worker_pid": os.getpid(),
            "run_id": claim["run_id"],
            "attempt": claim["attempt"],
            # Honest reclaim semantics: a later attempt re-fetches the pinned
            # inputs into its own tree. Nothing here is resumable evidence.
            "resumable": False,
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }), encoding="utf-8")

    def _pinned_source(self, claim: dict) -> tuple[str, bytes, str, str]:
        """Fetch exactly the snapshot this work item is bound to.

        The frozen owner and repository were parsed at admission time; the
        importer's own parser re-parses the frozen URL before any network
        access and all three identities must agree, so a divergence or an
        edited project cannot redirect this attempt at another repository.
        """
        expected = f"{claim['source_owner']}/{claim['source_repo']}"
        owner, repo = parse_github_url(claim["source_url"])
        if f"{owner}/{repo}" != expected:
            raise InvalidRepository("frozen source URL does not match the recorded repository")
        pinned_commit = claim.get("pinned_source_commit") or None
        pinned_ref = claim.get("pinned_source_ref") or None
        slug, payload = fetch_public_github_repo(claim["source_url"], ref=pinned_commit)
        if slug != expected:
            raise InvalidRepository("fetched repository is not the accepted work item's source")
        reference = f"github.com/{slug}"
        if pinned_ref and pinned_ref != reference:
            raise SourceIdentityConflict("the fetched source is not the pinned reference")
        commit = archive_commit(payload)
        if pinned_commit and commit != pinned_commit:
            raise SourceIdentityConflict("the fetched archive is not the pinned commit")
        if not commit:
            raise SourceCommitUnresolved("the fetched archive names no commit")
        return reference, payload, commit, hashlib.sha256(payload).hexdigest()

    def _evolve(self, claim: dict, directory: Path, progress: _Progress) -> None:
        """Take one claimed work item as far as it can honestly go.

        `progress` is this attempt's visible position, and it is what lets a
        failure be reported as the stage it actually stopped in rather than as
        a bare code.
        """
        lease = self._fence(claim, claim.get("lease_expires_at"), phase="claimed")
        if lease is None:
            return
        progress.phase = "fetching_source"
        lease = self._fence(claim, lease, phase="fetching_source")
        if lease is None:
            return
        reference, payload, commit, source_sha256 = self._pinned_source(claim)
        evidence = _private_directory(directory / "evidence")
        sandbox = _private_directory(directory / "sandbox")
        source_zip = _private_file(evidence / "source.zip", payload)
        lease = self._fence(claim, lease, phase="fetching_source", source_ref=reference,
                            source_commit=commit, source_digest="sha256:" + source_sha256)
        if lease is None:
            return
        # The run's own record now names this snapshot, for this attempt and
        # every later one.
        progress.pinned = True
        config_sha256 = self.spec.digest
        attempt = _Attempt(
            claim=claim, lease=lease, evidence=evidence, sandbox=sandbox, source_zip=source_zip,
            source_sha256=source_sha256, config_sha256=config_sha256,
            goal=str(claim.get("goal") or ""),
            deadline=time.monotonic() + self.max_run_seconds,
            tokens=self.spec.limits.total_tokens, role_calls=self.max_role_calls,
            index=EvidenceIndex(checks=frozenset()),
            lessons=lesson_block(approved_lessons(
                self.client, self.project_id, source_sha256=source_sha256,
                config_sha256=config_sha256)))
        progress.attempt = attempt
        if not attempt.goal:
            raise CodingError("invalid_goal", "the claimed work item carries no goal")
        print(f"run {claim['run_id']} pinned {reference} at {commit[:12]}; "
              f"{len(attempt.lessons.splitlines()) and 'retrieved approved lessons' or 'no lessons'}",
              flush=True)
        for stage in STAGE_ORDER:
            progress.phase = stage
            if not self._stage(attempt, stage):
                return
        attempt.lease = self._fence(claim, attempt.lease, phase="awaiting_approval")
        if attempt.lease is None:
            return
        outcome = self.client.rpc_row("finish_evolve_run", {
            "p_run_id": claim["run_id"], "p_lease_token": claim["lease_token"],
        }) or {}
        if outcome.get("accepted"):
            print(f"run {claim['run_id']} is awaiting human approval of candidate "
                  f"{attempt.candidate_sha256[:12]}", flush=True)
        else:
            print(f"run {claim['run_id']} completion refused: "
                  f"{outcome.get('reason', 'unknown')}", flush=True)

    def _stage(self, attempt: _Attempt, stage: str) -> bool:
        """Run, review, validate and record one stage. False once fenced out."""
        rework: list[str] = []
        for attempt_round in range(self.max_rework + 1):
            attempt.lease = self._fence(attempt.claim, attempt.lease, phase=stage)
            if attempt.lease is None:
                return False
            result = self._run_stage(attempt, stage, attempt_round, rework)
            if result is None:
                return False
            if result.get("status") != "ok":
                code = str(result.get("error_code") or "stage_internal_error")
                if code in REWORK_CODES and attempt_round < self.max_rework:
                    rework = [f"the previous {stage} round failed its own contract ({code})"]
                    continue
                raise EvolveStageRejected(code, f"the {stage} stage did not produce a record")
            try:
                prepared = self._prepare(attempt, stage, result)
            except CodingError as error:
                if error.code in REWORK_CODES and attempt_round < self.max_rework:
                    rework = [f"the previous {stage} review cited unusable evidence "
                              f"({error.code})"]
                    continue
                raise
            verdict = result["review"]["verdict"]
            blocking = [str(item.get("detail")) for item in result["review"].get("findings") or []
                        if item.get("severity") == "blocking"]
            if verdict == "rework" and attempt_round < self.max_rework:
                rework = blocking or [str(result["review"].get("summary") or "")]
                continue
            # A passing stage is committed and the attempt continues. A terminal
            # refusal is committed too, so the rejection's own findings survive
            # on the record, and then the run fails: the control plane admits
            # nothing after a stage whose review did not pass.
            self._commit(attempt, stage, prepared)
            if verdict == "pass":
                return True
            attempt.rejected = stage
            raise EvolveStageRejected(
                "review_rejected", f"the independent {stage} review refused this attempt")
        raise EvolveStageRejected("review_rejected",
                                  f"the {stage} stage exhausted its rework budget")

    def _run_stage(self, attempt: _Attempt, stage: str, round_index: int,
                   rework: list[str]) -> dict[str, Any] | None:
        remaining = attempt.deadline - time.monotonic()
        if remaining <= 1:
            raise EvolveTimeout("the attempt exceeded its bounded runtime")
        seconds = int(min(remaining, self.spec.limits.wall_seconds))
        directory = _private_directory(attempt.evidence / f"{stage}-{round_index}")
        request: dict[str, Any] = {
            "schema_version": 1, "stage": stage, "config_path": str(self.config_path),
            "review_config_path": str(self.review_config_path) if self.review_config_path else None,
            "source_zip": str(attempt.source_zip), "candidate_zip": attempt.candidate_zip,
            "candidate_sha256": attempt.candidate_sha256, "goal": attempt.goal,
            "evidence_dir": str(directory), "run_root": str(attempt.sandbox),
            "prior": attempt.recorded, "lessons": attempt.lessons,
            "catalogue": attempt.index.catalogue(), "rework": rework,
            "outcome": APPROVABLE_OUTCOME,
            "budget": {"tokens": max(0, attempt.tokens - attempt.tokens_spent),
                       "role_calls": max(0, attempt.role_calls - attempt.calls_spent)},
            "deadline_seconds": float(seconds),
        }
        result = self._supervise(attempt.claim, stage, directory, request, attempt.lease, seconds,
                                 phase=stage)
        if result is None:
            return None
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        # The ledger spans the whole attempt, so what a child spent is charged
        # before the next child is given what remains.
        attempt.tokens_spent += int(usage.get("tokens") or 0)
        attempt.calls_spent += int(usage.get("role_calls") or 0)
        return result

    def _prepare(self, attempt: _Attempt, stage: str,
                 result: dict[str, Any]) -> _Prepared:
        """Re-derive every recordable identity and validate the cited evidence.

        Nothing a child reported is taken on trust: digests come from the bytes
        this worker will upload, the candidate identity must be the same one
        across every stage that names it, and each cited reference must resolve
        against what this worker has itself recorded or registered.
        """
        artifact = result.get("artifact")
        if not isinstance(artifact, dict):
            raise CodingError("invalid_stage_artifact", f"the {stage} stage produced no artifact")
        proposal = typed(ReviewProposal, result.get("review"), "invalid_review",
                         f"the {stage} review")
        produced = result.get("produced") if isinstance(result.get("produced"), dict) else {}
        uploads: list[tuple[str, bytes]] = []
        candidate_sha256 = attempt.candidate_sha256 or None
        if stage == "implementation":
            candidate = self._artifact_bytes(produced.get("candidate_path"), "candidate")
            patch = self._artifact_bytes(produced.get("patch_path"), "patch")
            candidate_sha256 = hashlib.sha256(candidate).hexdigest()
            patch_sha256 = hashlib.sha256(patch).hexdigest()
            if artifact.get("candidate_sha256") != candidate_sha256 \
                    or artifact.get("patch_sha256") != patch_sha256:
                raise CodingError("candidate_identity_conflict",
                                  "the implementation record does not name the produced archives")
            # Registered only once this stage actually passes, so a reworked
            # implementation never spends the attempt's single candidate slot.
            uploads = [("candidate", candidate), ("patch", patch)]
        elif stage in CANDIDATE_BOUND_STAGES:
            if artifact.get("candidate_sha256") != candidate_sha256:
                raise CodingError("candidate_identity_conflict",
                                  f"the {stage} record names a different candidate")
        if stage == "requirements" and artifact.get("goal") != attempt.goal:
            raise CodingError("invalid_stage_artifact",
                              "the requirements record does not carry the work item's goal")
        if stage == "audit" and artifact.get("violations") and proposal.verdict == "pass":
            # The auditor named process defects while its reviewer passed the
            # stage. That record contradicts itself, so it is not recorded at
            # all: a passing audit with violations is exactly the combination
            # that must never become an approvable candidate.
            raise CodingError("process_rejected",
                              "a passing audit cannot record process violations")
        own = candidate_sha256 if stage in CANDIDATE_BOUND_STAGES else digest_json(artifact)
        if own is None:
            raise CodingError("invalid_artifact", f"the {stage} stage has no artifact identity")
        checks = attempt.index.checks
        if stage == "verification":
            checks = frozenset(str(row.get("name")) for row in artifact.get("checks") or [])
        # A scratch index: a reference only becomes permanently citable once
        # this worker has actually recorded or registered what it names. This
        # stage's own identity and its own name resolve here, because both are
        # about to be part of the record the reviewer is reviewing.
        scratch = EvidenceIndex(checks=checks, stages=set(attempt.index.stages) | {stage},
                                artifacts=set(attempt.index.artifacts)
                                | {own} | {hashlib.sha256(payload).hexdigest()
                                           for _, payload in uploads})
        review = review_record(
            proposal,
            reviewer_model=str(result.get("reviewer_model") or ""),
            reviewer_digest=str(result.get("reviewer_digest") or ""),
            evidence=scratch, subject=f"the {stage} review")
        payload = stage_payload(stage, artifact=artifact, review=review,
                               source_sha256=attempt.source_sha256,
                               config_sha256=attempt.config_sha256,
                               candidate_sha256=candidate_sha256)
        return _Prepared(stage=stage, payload=payload, uploads=uploads, own=own, checks=checks,
                         candidate_sha256=candidate_sha256, produced=produced,
                         artifact=artifact)

    @staticmethod
    def _artifact_bytes(path: object, kind: str) -> bytes:
        if not isinstance(path, str) or not path:
            raise CodingError("invalid_artifact", f"the stage produced no {kind} artifact")
        try:
            return Path(path).read_bytes()
        except OSError:
            raise CodingError("invalid_artifact",
                              f"the {kind} artifact could not be read") from None

    def _commit(self, attempt: _Attempt, stage: str, prepared: _Prepared) -> None:
        """Register this stage's artifacts, then record the stage itself.

        The bytes are uploaded and registered before the stage row exists, so a
        review can cite them and a reader can never resolve a registration to
        bytes that were never stored.

        A stage whose review did not pass is still recorded, because its
        findings are the most useful thing the attempt produced, but it
        registers nothing: an attempt may hold exactly one candidate, and a
        refused change must not be the one that occupies it.

        Recorded evidence is then retained whatever the verdict, and the
        stage's name becomes citable, because the failure-learning branch
        reasons about exactly what is on the record, a refusing review
        included. Retaining it is not treating it as passed: nothing below the
        verdict check promotes a refused stage's candidate, its artifacts, its
        check outcomes or its position in the order.
        """
        verdict = prepared.payload["review"]["verdict"]
        passed = verdict == "pass"
        if passed:
            for kind, payload in prepared.uploads:
                row = self.artifacts().publish(
                    attempt.claim["run_id"], attempt.claim["lease_token"], kind, payload)
                attempt.index.add_artifact(str(row["sha256"]))
                print(f"run {attempt.claim['run_id']} registered {kind} artifact "
                      f"{row['sha256'][:12]} ({row['bytes']} bytes)", flush=True)
            if prepared.candidate_sha256:
                attempt.candidate_sha256 = prepared.candidate_sha256
            if stage == "implementation":
                attempt.candidate_zip = str(prepared.produced.get("candidate_path"))
            attempt.index.checks = prepared.checks
        recorded = self.client.rpc_row("record_evolve_stage", {
            "p_run_id": attempt.claim["run_id"], "p_lease_token": attempt.claim["lease_token"],
            "p_stage": stage, "p_payload": prepared.payload,
        })
        if not isinstance(recorded, dict) or recorded.get("stage") != stage:
            raise FactoryRuntimeError(f"the {stage} stage was not recorded")
        print(f"run {attempt.claim['run_id']} recorded {stage} ({verdict})", flush=True)
        attempt.recorded[stage] = prepared.payload
        attempt.index.add_stage(stage)
        if not passed:
            return
        attempt.index.add_artifact(prepared.own)
        attempt.evidence_paths.setdefault(stage, dict(prepared.produced))
        if stage == "verification":
            # The receipt and trace manifests cover the implementation and the
            # verification together, and the audit cites them, so they are
            # registered before the audit stage can be recorded.
            self._publish_evidence(attempt)

    def artifacts(self) -> EvolveArtifactStore:
        if self.store is None:
            self.store = EvolveArtifactStore(self.client)
        return self.store

    def _publish_evidence(self, attempt: _Attempt) -> None:
        """Upload the sanitized receipt and trace once the candidate is verified.

        These are manifests, not the private evidence: the resolved operator
        configuration, the protected expected check outputs and every observed
        check output stay in the worker's own run directory.
        """
        receipts: dict[str, Any] = {}
        traces: list[Path] = []
        for stage in ("implementation", "verification"):
            produced = attempt.evidence_paths.get(stage) or {}
            receipt_path = produced.get("receipt_path")
            trace_path = produced.get("trace_path")
            if isinstance(receipt_path, str):
                try:
                    receipts[stage] = sanitize_receipt(strict_json(Path(receipt_path).read_bytes()))
                except (OSError, ValueError, UnicodeError, RecursionError, CodingError):
                    receipts[stage] = {"status": "unavailable"}
            if isinstance(trace_path, str):
                traces.append(Path(trace_path))
        manifest = {"schema_version": 1, "run_id": attempt.claim["run_id"],
                    "attempt": attempt.claim["attempt"], "source_sha256": attempt.source_sha256,
                    "config_sha256": attempt.config_sha256,
                    "candidate_sha256": attempt.candidate_sha256,
                    "verification_scope": "configured JSON contracts, re-run without a model",
                    "stages": receipts}
        for kind, payload in (("receipt", (canonical_json(manifest) + "\n").encode("utf-8")),
                              ("trace", sanitized_trace(traces))):
            row = self.artifacts().publish(attempt.claim["run_id"],
                                           attempt.claim["lease_token"], kind, payload)
            attempt.index.add_artifact(str(row["sha256"]))
            print(f"run {attempt.claim['run_id']} registered {kind} artifact "
                  f"{row['sha256'][:12]} ({row['bytes']} bytes)", flush=True)

    def _record_failure_report(self, claim: dict, progress: _Progress, code: str) -> None:
        """Record this attempt's one diagnostic report, before the run fails.

        This is what makes a refusal observable: where the attempt stopped,
        what the controller's own checks actually did, and whether failure
        learning ran or was unavailable and why.

        It never masks the original failure. Anything that goes wrong building
        or recording the report is the operator's to read in full, and the run
        still fails with exactly the code it already had.
        """
        try:
            report = self._failure_report(claim, progress, code)
            if report is None:
                return
            outcome = self.client.rpc_row("record_evolve_failure_report", {
                "p_run_id": claim["run_id"], "p_lease_token": claim["lease_token"],
                "p_report": report,
            }) or {}
        except Exception:
            print(f"Evolve run {claim['run_id']} recorded no diagnostic report for {code}",
                  flush=True)
            traceback.print_exc()
            return
        if outcome.get("accepted"):
            print(f"Evolve run {claim['run_id']} recorded a diagnostic report for {code} "
                  f"(learning {report['learning_status']}: {report['learning_reason']})",
                  flush=True)
        else:
            print(f"Evolve run {claim['run_id']} diagnostic report refused: "
                  f"{outcome.get('reason', 'unknown')}", flush=True)

    def _failure_report(self, claim: dict, progress: _Progress,
                        code: str) -> dict[str, Any] | None:
        """Build this attempt's failure report, with learning where it is due.

        One bounded extraction and one independent lesson review are attempted
        only when this worker still holds the run, still has a pinned snapshot
        to reason about, and still has budget and time left. Every other case
        records explicit unavailability with the reason the worker observed,
        and no further model call is made to produce it.

        Returning None means no report is recorded at all, and each case is one
        where a report could only contradict the run's own record or add
        nothing to it: the lease is gone, so this attempt no longer owns the
        run; the attempt never reached a snapshot the run already pins; the
        stage it was in is already recorded as passing, so the failure came
        after it; or a verification failed without this worker observing the
        check that failed. The failure code is reported in every case.
        """
        attempt = progress.attempt
        if attempt is None and (progress.pinned or claim.get("pinned_source_commit")):
            # This run's record already names a snapshot, from this attempt's
            # own pin or from an earlier attempt, so `no_source` would
            # contradict it. An attempt that never reached that snapshot
            # observed no check, recorded no stage and can support no lesson,
            # so its failure code is the whole honest story and the diagnostic
            # report would add nothing.
            print(f"run {claim['run_id']} reached no evidence of its pinned snapshot; "
                  f"{code} is reported without a diagnostic report", flush=True)
            return None
        if attempt is not None and _passed(attempt.recorded.get(progress.phase)):
            # The stage this attempt was in is on the record with a passing
            # review, so the failure came after that stage rather than in it.
            # There is no failing stage to name, the record already holds what
            # the attempt proved, and the run's failure code carries the rest.
            print(f"run {claim['run_id']} failed after recording {progress.phase}; "
                  f"{code} is reported without a diagnostic report", flush=True)
            return None
        checks = self._observed_checks(attempt)
        if code == "verification_failed" and all(check["passed"] for check in checks):
            # This report exists to make the failure observable, and this
            # worker did not observe the check that failed: its own evidence
            # file is missing or unusable. A verification failure that names no
            # failing check is not recordable, and spending inference on a
            # report that cannot be recorded would be waste.
            print(f"run {claim['run_id']} observed no failing check for {code}; "
                  "no diagnostic report is recordable", flush=True)
            return None
        reviewer_model, reviewer_digest = self._pinned_reviewer()
        # Exactly what this attempt recorded, registered and measured, plus its
        # own failure code: the only references a failure lesson may cite.
        index = EvidenceIndex(
            checks=frozenset(str(check["name"]) for check in checks),
            stages=set(attempt.recorded) if attempt else set(),
            artifacts=set(attempt.index.artifacts) if attempt else set(),
            failure=code)

        def report(status: str, reason: str, lessons: list[dict[str, Any]],
                   decisions: list[dict[str, Any]]) -> dict[str, Any]:
            return failure_report(
                error_code=code, failed_stage=progress.phase,
                source_sha256=attempt.source_sha256 if attempt else None,
                config_sha256=attempt.config_sha256 if attempt else self.spec.digest,
                checks=checks, learning_status=status, learning_reason=reason,
                lessons=lessons, decisions=decisions, reviewer_model=reviewer_model,
                reviewer_digest=reviewer_digest, evidence=index)

        # Without a pinned snapshot there is no evidence a lesson could rest
        # on, so no lesson is admissible at all.
        if attempt is None or not attempt.source_sha256:
            return report("unavailable", "no_source", [], [])
        reason = _unavailable_reason(code) or self._unfunded(attempt)
        if reason is not None:
            return report("unavailable", reason, [], [])
        # Authority is confirmed immediately before any inference is spent.
        attempt.lease = self._fence(attempt.claim, attempt.lease)
        if attempt.lease is None:
            return None
        result = self._failure_lessons(attempt, code, progress.phase, index)
        if result is None:
            return None
        if result.get("status") != "ok":
            return report("unavailable",
                          _unavailable_reason(str(result.get("error_code") or ""))
                          or "extraction_failed", [], [])
        lessons, decisions = result.get("lessons"), result.get("decisions")
        if (str(result.get("reviewer_model") or ""),
                str(result.get("reviewer_digest") or "")) != (reviewer_model, reviewer_digest):
            # The branch did not answer as the reviewer this worker's trusted
            # configuration pins, so nothing it produced was independently
            # reviewed by that reviewer and none of it is recorded as such.
            print(f"run {claim['run_id']} refused a failure review it did not pin", flush=True)
            return report("unavailable", "extraction_failed", [], [])
        if not isinstance(lessons, list) or not isinstance(decisions, list):
            print(f"run {claim['run_id']} refused an unusable failure learning result",
                  flush=True)
            return report("unavailable", "extraction_failed", [], [])
        try:
            return report("reviewed", "completed", lessons, decisions)
        except CodingError as error:
            # A lesson that cites evidence this run does not have, or that does
            # not satisfy its own contract, is refused rather than repaired.
            # The report survives as the honest record that nothing was learnt.
            print(f"run {claim['run_id']} refused its failure lessons ({error.code})", flush=True)
            return report("unavailable", "extraction_failed", [], [])

    def _failure_lessons(self, attempt: _Attempt, code: str, failed_stage: str,
                         index: EvidenceIndex) -> dict[str, Any] | None:
        """One bounded supervised extraction and independent lesson review.

        Deliberately not a stage: nothing it produces is recorded in the stage
        order, and it leaves the run's heartbeat phase exactly where the
        failure left it. It runs in its own child, in fresh role contexts, with
        what remains of this attempt's deadline and of the same aggregate token
        and role-call ledger every other role drew on, so a failed run cannot
        buy itself a second allowance.
        """
        seconds = int(min(attempt.deadline - time.monotonic(), self.spec.limits.wall_seconds))
        directory = _private_directory(attempt.evidence / FAILURE_LEARNING)
        request: dict[str, Any] = {
            "schema_version": 1, "stage": FAILURE_LEARNING, "config_path": str(self.config_path),
            "review_config_path": str(self.review_config_path) if self.review_config_path else None,
            "source_zip": str(attempt.source_zip), "candidate_zip": None,
            "candidate_sha256": attempt.candidate_sha256, "goal": attempt.goal,
            "evidence_dir": str(directory), "run_root": str(attempt.sandbox),
            "prior": attempt.recorded, "lessons": attempt.lessons,
            "failure_checks": self._observed_checks(attempt),
            "catalogue": index.catalogue(), "rework": [],
            "outcome": _failure_outcome(code, failed_stage, attempt.rejected),
            "budget": {"tokens": max(0, attempt.tokens - attempt.tokens_spent),
                       "role_calls": max(0, attempt.role_calls - attempt.calls_spent)},
            "deadline_seconds": float(seconds),
        }
        result = self._supervise(attempt.claim, FAILURE_LEARNING, directory, request,
                                 attempt.lease, seconds, phase=None)
        if result is None:
            return None
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        # Charged to the one ledger, like every other child this attempt ran.
        attempt.tokens_spent += int(usage.get("tokens") or 0)
        attempt.calls_spent += int(usage.get("role_calls") or 0)
        return result

    def _observed_checks(self, attempt: _Attempt | None) -> list[dict[str, Any]]:
        """The real check outcomes this attempt observed, closest to its failure.

        The paths are this worker's own: it created every round directory and
        the controller's own verifier and editing loop wrote the reports inside
        them, so nothing a child reported chooses the file that is read. The
        latest stage wins, which is how a failed independent verification is
        reported as itself rather than as the editing loop's earlier run.
        """
        if attempt is None:
            return []
        for stage in reversed(STAGE_ORDER):
            for round_index in reversed(range(self.max_rework + 1)):
                directory = attempt.evidence / f"{stage}-{round_index}"
                for name in _CHECK_REPORTS:
                    outcomes = _check_report(directory / name)
                    if outcomes:
                        return outcomes
        return []

    def _pinned_reviewer(self) -> tuple[str, str]:
        """The reviewer identity this worker's trusted configuration pins.

        A reported identity is checked against this instead of being recorded
        as given: a child cannot name the model that reviewed its lessons, and
        a report that claims an identity this worker did not pin is refused.
        """
        model = self.review_spec.model
        return model.name, model.digest.removeprefix("sha256:").lower()

    def _unfunded(self, attempt: _Attempt) -> str | None:
        """`budget_exhausted` when nothing is left to fund one more role call."""
        if attempt.deadline - time.monotonic() <= MIN_LEARNING_SECONDS:
            return "budget_exhausted"
        if attempt.tokens_spent >= attempt.tokens or attempt.calls_spent >= attempt.role_calls:
            return "budget_exhausted"
        return None

    def _report_failure(self, claim: dict, code: str) -> None:
        try:
            outcome = self.client.rpc_row("fail_evolve_run", {
                "p_run_id": claim["run_id"], "p_lease_token": claim["lease_token"],
                "p_error_code": code,
            }) or {}
        except Exception:
            print(f"Evolve run {claim['run_id']} failure could not be recorded; "
                  "the lease will expire and be reclaimed", flush=True)
            return
        if not outcome.get("accepted"):
            print(f"Evolve run {claim['run_id']} failure report refused: "
                  f"{outcome.get('reason', 'unknown')}", flush=True)
        elif outcome.get("retry_scheduled"):
            if code in NONRETRYABLE_CODES:
                print(f"Evolve run {claim['run_id']} reported {code} and a retry was scheduled",
                      flush=True)
            else:
                print(f"Evolve run {claim['run_id']} will be retried", flush=True)
        else:
            print(f"work item {claim['work_item_id']} failed terminally ({code})", flush=True)


@dataclass
class _Prepared:
    """One validated, recordable stage, with the bytes it must register first."""

    stage: str
    payload: dict[str, Any]
    uploads: list[tuple[str, bytes]]
    own: str
    checks: frozenset[str]
    candidate_sha256: str | None
    produced: dict[str, Any]
    artifact: dict[str, Any]


@dataclass
class _Attempt:
    """One attempt's pinned inputs, shared ledger and accumulating record."""

    claim: dict
    lease: str | None
    evidence: Path
    sandbox: Path
    source_zip: Path
    source_sha256: str
    config_sha256: str
    goal: str
    deadline: float
    tokens: int
    role_calls: int
    index: EvidenceIndex
    lessons: str
    candidate_sha256: str = ""
    candidate_zip: str | None = None
    tokens_spent: int = 0
    calls_spent: int = 0
    # The stage whose review was recorded as refused, after which the control
    # plane admits nothing further for this attempt. It is a fact about the
    # record, not a step the attempt completed.
    rejected: str | None = None
    recorded: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence_paths: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class _Progress:
    """Where an attempt got to, as its own supervisor can see it.

    An attempt can fail before it has an `_Attempt` at all, so the phase is
    tracked separately from the pinned inputs: a failure is then reportable as
    the stage it actually stopped in rather than as a bare code, and a failure
    with no snapshot behind it cannot pretend to have one.
    """

    phase: str = "claimed"
    attempt: _Attempt | None = None
    # Whether the run now carries a pinned snapshot identity. A run that has
    # one cannot honestly be reported as having no source, even by an attempt
    # that never reached it.
    pinned: bool = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m oryveta_engine.evolve_runtime",
        description="Oryveta project-scoped durable reviewed Evolve worker")
    parser.add_argument("--credentials", default=os.environ.get(CREDENTIALS_ENV),
                        help=f"protected worker credential file (or ${CREDENTIALS_ENV})")
    parser.add_argument("--project", default=None,
                        help="project UUID to serve; defaults to the credential file's project_id")
    parser.add_argument("--config", default=None,
                        help="trusted operator specification: model, runner, scope and checks")
    parser.add_argument("--review-config", default=None,
                        help="optional trusted specification for the independent review roles; "
                             "defaults to the same pinned model in separate contexts")
    parser.add_argument("--once", action="store_true",
                        help="claim and complete at most one work item, then exit")
    parser.add_argument("--max-runs", type=int, default=None,
                        help="stop after this many completed claims (continuous mode)")
    parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS,
                        help=f"lease length, {MIN_LEASE_SECONDS}-{MAX_LEASE_SECONDS} seconds")
    parser.add_argument("--max-run-seconds", type=int, default=DEFAULT_MAX_RUN_SECONDS,
                        help="bounded runtime for one whole attempt, shared by every stage and "
                             "enforced by the worker and by each stage child itself")
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS,
                        help="idle delay between claim attempts in continuous mode")
    parser.add_argument("--work-root", default=None,
                        help="persistent private parent for per-attempt evidence, swept for the "
                             "trees of dead attempts at startup")
    parser.add_argument("--max-rework", type=int, default=DEFAULT_MAX_REWORK,
                        help="bounded corrections allowed per stage before a review is terminal")
    parser.add_argument("--max-role-calls", type=int, default=DEFAULT_MAX_ROLE_CALLS,
                        help="aggregate model calls for one attempt, covering every author "
                             "role, every independent review and every rework round")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if not arguments.credentials:
        print(f"--credentials or ${CREDENTIALS_ENV} is required", file=sys.stderr)
        return 2
    if not arguments.config:
        print("--config is required: Evolve runs only a trusted operator specification",
              file=sys.stderr)
        return 2
    if not arguments.work_root:
        print("--work-root is required for persistent private Evolve evidence", file=sys.stderr)
        return 2
    try:
        credentials = WorkerCredentials.load(arguments.credentials)
    except CredentialError as exception:
        print(str(exception), file=sys.stderr)
        return 2
    project_id = arguments.project or credentials.project_id
    if not project_id:
        print("--project is required when the credential file has no project_id", file=sys.stderr)
        return 2
    try:
        with FactoryRuntimeClient(credentials) as client:
            worker = EvolveRuntimeWorker(
                client=client, project_id=project_id, config_path=Path(arguments.config),
                work_root=Path(arguments.work_root),
                review_config_path=Path(arguments.review_config) if arguments.review_config
                else None,
                lease_seconds=arguments.lease_seconds,
                max_run_seconds=arguments.max_run_seconds,
                poll_seconds=arguments.poll_seconds,
                max_rework=arguments.max_rework,
                max_role_calls=arguments.max_role_calls)
            registration = worker.verify_registration()
            print(f"worker registration {registration['label']} is enabled; "
                  f"configuration {worker.spec.digest[:12]} with "
                  f"{len(_check_names(worker.spec))} configured checks", flush=True)
            # Unlike disposable analysis trees, these directories contain the
            # complete private audit evidence. A restart must never erase it.
            # Ordinary exits remove sandbox scratch; hard-kill cleanup and
            # evidence retention are explicit operator actions.
            try:
                if arguments.once:
                    print("processed one work item" if worker.run_once()
                          else "no queued work item", flush=True)
                    return 0
                worker.forever(max_runs=arguments.max_runs)
            finally:
                if worker.store is not None:
                    worker.store.close()
        return 0
    except KeyboardInterrupt:
        print("stopped", flush=True)
        return 0
    except (FactoryRuntimeError, CodingError, ValueError) as exception:
        print(str(exception), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
