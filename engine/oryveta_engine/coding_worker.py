"""Operator-provisioned durable repair worker for the Supabase metadata authority.

This worker is the repair counterpart of `factory_runtime.AnalysisRuntimeWorker`.
It claims `repository_repair` work items for exactly one approved repair policy
and performs one real task per attempt: fetch the policy's pinned public GitHub
commit, run the existing local `coding_runtime.repair` loop in a supervised
credential-free child, and publish one bounded patch result that was validated
against the private evidence the child actually wrote.

Deliberate boundaries:
  * Repair is opt-in and explicit. Nothing starts without a policy id, the
    operator's reviewed configuration file, the approved source URL and the
    approved 40-hex commit, and every one of those is compared against the
    policy row and against each claim. The analysis service is untouched: an
    analysis worker never gains code-execution authority by this module
    existing.
  * The parsed specification is frozen once at startup from the exact bytes
    that were hashed, and a copy of those bytes is placed in every private run
    directory. A mid-attempt edit of the operator's file can therefore not
    become the authority for a run already under way.
  * The child receives no Supabase credentials, no lease token, no project
    registration and no inherited parent environment. It gets a config copy, a
    source archive, a goal file, its own evidence and work directories, a
    deadline, the worker's PID and the resolved Docker executable.
  * The lease token is a fencing value. Cancellation, policy or worker or
    creator revocation, a stolen lease, an expired lease, SIGTERM and the loss
    of the worker process all stop the child's whole process group and prevent
    publication, so a fenced attempt never produces a misleading success.
  * Only `needs_review` output that the private receipt and the verified patch
    file both support is published, with the patch hash recomputed here. An
    over-limit patch is refused; it is never truncated and never replaced by a
    metadata-only "completion".
  * Private evidence is preserved per run under the operator's evidence root.
    What reaches the control plane is the bounded result and bounded numeric
    progress: no host paths, no stdout, no expected check values, no prompts
    and no model trajectory.
  * There is no automatic fallback. One local model, one local Docker runner,
    one frozen configuration: if local capacity is missing the worker refuses
    to become ready instead of reaching for a paid or remote substitute.
  * Always-on here means a supervised process that polls independently of any
    browser. It is not unlimited work and not an uptime guarantee: an attempt
    whose worker host disappears is recovered by its lease expiring.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import factory_runtime
from .coding_config import MAX_CONFIG_BYTES, parse_spec
from .coding_contract import CodingError, FactorySpec, strict_json
from .coding_model import LocalToolModel
from .coding_sandbox import DockerRunner
from .factory_runtime import (
    CHILD_DEADLINE_GRACE_SECONDS,
    DEFAULT_LEASE_SECONDS,
    DEFAULT_POLL_SECONDS,
    HEARTBEAT_RETRY_BACKOFF_SECONDS,
    LEASE_RETRY_MARGIN_SECONDS,
    MAX_CONSECUTIVE_CLAIM_FAILURES,
    MAX_HEARTBEAT_INTERVAL,
    MAX_HEARTBEAT_RETRIES,
    MAX_LEASE_SECONDS,
    MIN_LEASE_SECONDS,
    RUN_DIRECTORY_PREFIX,
    RUN_MARKER_NAME,
    SOURCE_CONFLICT_REFUSALS,
    TERMINATE_GRACE_SECONDS,
    ControlPlaneUnavailable,
    CredentialError,
    FactoryRuntimeClient,
    FactoryRuntimeError,
    SourceCommitUnresolved,
    SourceIdentityConflict,
    WorkerCredentials,
    archive_commit,
    enabled_registration,
    lease_seconds_left,
    minimal_child_environment,
    signal_process_group,
    sweep_stale_work_roots,
)
from .factory_service import session_lock
from .repositories import InvalidRepository, fetch_public_github_repo, parse_github_url

CREDENTIALS_ENV = "ORYVETA_REPAIR_CREDENTIALS"
DOCKER_CONFIG_ENV = "DOCKER_CONFIG"

WORK_ITEM_KIND = "repository_repair"

# Control-plane phases, and the derived checkpoint steps. Both sets are closed:
# the control plane accepts no other value, and nothing else is ever sent.
PHASE_CLAIMED = "claimed"
PHASE_FETCHING_SOURCE = "fetching_source"
PHASE_REPAIRING = "repairing"
PHASE_VERIFYING = "verifying"
PHASE_RECORDING_RESULT = "recording_result"

STEP_FETCHING_SOURCE = "fetching_source"
STEP_SNAPSHOT_READY = "snapshot_ready"
STEP_REPAIRING = "repairing"
STEP_VERIFYING = "verifying"
STEP_RECORDING_RESULT = "recording_result"

# The local loop's own receipt phase while the controller-owned checks run. Any
# other receipt phase is reported as `repairing`, because that is what it is.
RECEIPT_VERIFYING_PHASE = "verification"

# Fetching, snapshotting, candidate export and result validation sit outside the
# configuration's own wall budget, so the supervised child gets that budget plus
# this allowance and nothing more.
REPAIR_SETUP_GRACE_SECONDS = 180

# Local capacity is re-observed at least this often before a claim. The probe
# spends no inference tokens and runs no container; it inspects the Docker
# context, daemon and image and the installed local model.
CAPACITY_MAX_AGE_SECONDS = 120.0

# The registration and the policy are re-read at least this often before a
# claim, so an owner's revocation stops a polling worker instead of leaving it
# asking a control plane that will refuse it forever.
AUTHORITY_MAX_AGE_SECONDS = 120.0

# The control plane answers a failure report with one of these when the attempt
# was already settled by an authority or fencing path. The first group means
# this worker has lost the right to serve the policy at all, which is terminal;
# the rest mean this attempt was already closed, which is not.
TERMINAL_FAILURE_REASONS = frozenset({
    "worker_not_registered", "policy_revoked", "creator_unauthorized", "wrong_kind",
})

# The control plane's own bound on a reported elapsed time.
MAX_CHECKPOINT_ELAPSED_SECONDS = 86_400

# Bounds for the persisted result. The patch is published untruncated or not at
# all, and the whole document must fit the metadata authority's repair limit.
MAX_PATCH_BYTES = 64 * 1024
MAX_REPAIR_RESULT_BYTES = 192 * 1024
MAX_CHILD_RESULT_BYTES = 64 * 1024
MAX_CHILD_ERROR_BYTES = 2048
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_GOAL_BYTES = 4096

# The published result's exact key set; nothing else is ever sent.
RESULT_KEYS = (
    "kind", "status", "verification", "configuration_sha256", "source_commit",
    "source_tree_sha256", "candidate_tree_sha256", "patch_sha256", "patch",
    "checks_passed", "turns", "tool_calls", "tokens_observed", "model_name",
    "model_digest",
)
RESULT_COUNTERS = {
    "checks_passed": (1, 48),
    "turns": (1, 50),
    "tool_calls": (0, 100),
    "tokens_observed": (0, 500_000),
}

# Bounded numeric progress copied out of the private receipt. Nothing textual
# is forwarded, so a prompt, a path or a tool argument cannot reach an event.
CHECKPOINT_COUNTERS = ("turns", "tool_calls", "tokens_observed",
                       "unsettled_token_reservation")
MAX_CHECKPOINT_COUNTER = 1_000_000_000

HEX64 = re.compile(r"[0-9a-f]{64}")
HEX40 = re.compile(r"[0-9a-f]{40}")
# The same safe native model name pattern `coding_config` accepts.
MODEL_NAME = re.compile(r"[A-Za-z0-9._:-]{1,100}")

# Only the operator's Docker context metadata is handed to a child. A config
# directory also holds registry credentials, and the runner never pulls, so
# nothing else is copied.
DOCKER_CONTEXT_DIRECTORY = "contexts"
DOCKER_CONFIG_DIRECTORY = "docker-config"
MAX_DOCKER_CONTEXT_BYTES = 1024 * 1024

# Child exit codes, mirrored from `coding_child`.
CHILD_ORPHANED_EXIT = 3
CHILD_DEADLINE_EXIT = 4

# Codes the local repair loop produces that are forwarded to the control plane
# verbatim. The set is closed so a new upstream code can never widen what a
# project member is shown; anything else becomes `repair_failed`.
FORWARDED_CHILD_CODES = frozenset({
    "verification_failed", "not_reproduced", "no_change", "invalid_baseline",
    "candidate_scope", "candidate_inventory", "candidate_limit", "invalid_source",
    "invalid_goal", "invalid_config", "no_progress", "turn_budget", "tool_budget",
    "token_budget", "context_budget", "wall_budget", "model_unavailable",
    "model_changed", "model_timeout", "provider_contract", "evidence_write_failed",
    "trace_limit", "runner_context", "runner_daemon", "runner_image",
    "runner_create", "runner_start", "runner_state", "runner_timeout", "runner_oom",
    "runner_setup", "runner_cleanup", "runner_cli", "runner_output_limit",
    "runner_unusable",
})
GENERIC_CHILD_CODE = "repair_failed"


class RepairRuntimeError(FactoryRuntimeError):
    """A repair-worker-side failure reported with a short durable code."""


class PolicyUnavailable(RepairRuntimeError):
    """The repair policy this worker was started for cannot be served."""


class ClaimMismatch(RepairRuntimeError):
    """A claimed work item is not the one this worker's policy binds."""


class CapacityUnavailable(RepairRuntimeError):
    """Local Docker or local model capacity is not ready for a repair."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RepairChildFailure(RepairRuntimeError):
    """The local repair loop finished without a reviewable candidate."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RepairTimeout(RepairRuntimeError):
    """The supervised repair child exceeded its bounded runtime."""


class RepairProcessError(RepairRuntimeError):
    """The supervised repair child exited without a usable outcome."""


class RepairResultInvalid(RepairRuntimeError):
    """The private evidence does not support a publishable result."""


class RepairResultTooLarge(RepairRuntimeError):
    """A verified patch or result exceeds the persisted limit."""


def forwarded_child_code(code: object) -> str:
    """Narrow a local failure code to the closed set the control plane accepts."""
    return code if code in FORWARDED_CHILD_CODES else GENERIC_CHILD_CODE


def error_code(exception: BaseException) -> str:
    """Map an exception to a short code the metadata authority accepts.

    Codes are enumerated and lower-case, so an exception message, a credential,
    a goal or a host filesystem path can never reach a persisted row or event.
    """
    if isinstance(exception, (RepairChildFailure, CapacityUnavailable)):
        return exception.code
    if isinstance(exception, CodingError):
        return forwarded_child_code(exception.code)
    if isinstance(exception, (ClaimMismatch, PolicyUnavailable)):
        return "policy_mismatch"
    if isinstance(exception, RepairResultTooLarge):
        return "repair_result_too_large"
    if isinstance(exception, RepairResultInvalid):
        return "repair_output_invalid"
    if isinstance(exception, RepairTimeout):
        return "repair_timeout"
    if isinstance(exception, RepairProcessError):
        return "repair_process_failed"
    if isinstance(exception, InvalidRepository):
        return "invalid_repository"
    if isinstance(exception, (json.JSONDecodeError, ValueError)):
        # A malformed receipt or child report, rather than an analysis result.
        return "repair_output_invalid"
    # Shared transport, credential, storage and source-identity categories.
    return factory_runtime.error_code(exception)


# -- operator inputs ------------------------------------------------------

def frozen_configuration(path: str | os.PathLike[str]) -> tuple[bytes, FactorySpec]:
    """Read the operator's configuration once and parse those exact bytes.

    Hashing one read and parsing another would let an edit between the two
    produce a run whose receipt digest can never match the policy. The bytes
    returned here are the ones copied into every private run directory.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("not a regular file")
            payload = handle.read(MAX_CONFIG_BYTES + 1)
        if len(payload) > MAX_CONFIG_BYTES:
            raise ValueError("too large")
    except (OSError, ValueError):
        raise CodingError(
            "invalid_config",
            "the repair configuration must be a bounded regular JSON file") from None
    return payload, parse_spec(strict_json(payload))


def resolve_docker_cli(value: str | None) -> str:
    """Resolve one trusted Docker executable, or refuse to run repairs at all.

    The child is handed this absolute path instead of searching a PATH it could
    not vouch for. A binary another account can replace is refused, because it
    would decide how untrusted candidate code is confined.
    """
    candidate = value or shutil.which("docker")
    if not candidate:
        raise RepairRuntimeError(
            "no docker executable was found; install Docker or pass --docker-cli")
    resolved = Path(candidate).resolve()
    try:
        info = resolved.stat()
    except OSError:
        raise RepairRuntimeError("the docker executable does not exist") from None
    if not stat.S_ISREG(info.st_mode) or not os.access(resolved, os.X_OK):
        raise RepairRuntimeError("the docker executable must be a runnable regular file")
    if info.st_uid not in {0, os.geteuid()}:
        raise RepairRuntimeError(
            "the docker executable must be owned by root or by this operator account")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise RepairRuntimeError(
            "the docker executable must not be writable by other accounts")
    return str(resolved)


def private_docker_config(source: str | os.PathLike[str] | None, destination: Path,
                          docker_context: str) -> str:
    """Expose only the approved local socket, never other contexts or credentials."""
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destination, 0o700)
    if any(destination.iterdir()):
        raise RepairRuntimeError("the private Docker configuration directory must be empty")
    if docker_context == "default":
        return str(destination)
    if not source:
        raise RepairRuntimeError("the named Docker context requires --docker-config")
    root = Path(source)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise RepairRuntimeError("the Docker configuration directory must be an absolute real directory")
    context_id = hashlib.sha256(docker_context.encode("utf-8")).hexdigest()
    relative = Path(DOCKER_CONTEXT_DIRECTORY) / "meta" / context_id / "meta.json"
    metadata = root / relative
    if any(path.is_symlink() for path in
           (root / DOCKER_CONTEXT_DIRECTORY, metadata.parent.parent, metadata.parent, metadata)):
        raise RepairRuntimeError("the Docker context metadata must not contain symlinks")
    try:
        descriptor = os.open(metadata, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("not a regular metadata file")
            payload = handle.read(MAX_DOCKER_CONTEXT_BYTES + 1)
        if len(payload) > MAX_DOCKER_CONTEXT_BYTES:
            raise ValueError("metadata too large")
        data = strict_json(payload)
        endpoint = data["Endpoints"]["docker"]["Host"]
        if data["Name"] != docker_context or not isinstance(endpoint, str) or not endpoint.startswith("unix:///"):
            raise ValueError("not the approved local context")
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise RepairRuntimeError(
            "the approved local Docker context metadata is missing or invalid; check --docker-config") from None
    target = destination / relative
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_write(target, json.dumps({
        "Name": docker_context,
        "Endpoints": {"docker": {"Host": endpoint, "SkipTLSVerify": False}},
    }).encode("utf-8"))
    return str(destination)


def repair_child_environment(work_directory: Path, *, docker_cli: str,
                             docker_config: str | None) -> dict[str, str]:
    """Environment for the repair child: no worker or production credentials.

    The credential-free analysis child environment plus exactly what the Docker
    CLI needs: its own directory on PATH, a private HOME inside the disposable
    run directory so the operator's home is never read or written, and the
    sanitized context-only configuration directory. No DOCKER_HOST, no proxy
    variables and no inherited parent variables: the runner resolves its
    endpoint from the named context and clears proxy settings itself.
    """
    environment = minimal_child_environment(work_directory)
    binary = Path(docker_cli).parent
    environment["PATH"] = os.pathsep.join(
        dict.fromkeys([str(binary), *environment["PATH"].split(os.pathsep)]))
    environment["HOME"] = str(work_directory)
    if docker_config:
        environment[DOCKER_CONFIG_ENV] = str(docker_config)
    return environment


def prepare_private_root(path: Path, what: str) -> Path:
    """Create or adopt a private operator directory, mode 0700 and owned by us."""
    if path.is_symlink():
        raise RepairRuntimeError(f"the {what} must not be a symlink")
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.stat()
    except OSError as exception:
        raise RepairRuntimeError(
            f"the {what} could not be prepared ({type(exception).__name__})") from None
    if not stat.S_ISDIR(info.st_mode):
        raise RepairRuntimeError(f"the {what} must be a directory")
    if info.st_uid != os.geteuid():
        raise RepairRuntimeError(f"the {what} must be owned by this operator account")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise RepairRuntimeError(
            f"the {what} must not be group or world accessible (chmod 700)")
    return path.resolve()


# -- evidence and progress ------------------------------------------------

def private_write(path: Path, payload: bytes) -> None:
    """Write operator-only bytes, replacing the destination atomically."""
    handle = tempfile.NamedTemporaryFile(
        "wb", dir=str(path.parent), prefix=".repair-", delete=False)
    try:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(handle.name, path)
    except BaseException:
        handle.close()
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def read_receipt(path: Path) -> dict | None:
    """Read the child's private receipt for progress, tolerating a partial write.

    The receipt is rewritten at every checkpoint, so a read can land between
    writes. A receipt that is missing or not yet parseable simply means there is
    no newer progress to report.
    """
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_RECEIPT_BYTES + 1)
    except OSError:
        return None
    if len(payload) > MAX_RECEIPT_BYTES:
        return None
    try:
        receipt = strict_json(payload)
    except (ValueError, UnicodeError, RecursionError):
        return None
    return receipt if isinstance(receipt, dict) else None


def receipt_progress(receipt: dict | None) -> tuple[str, str]:
    """The control-plane phase and checkpoint step a receipt corresponds to."""
    phase = receipt.get("phase") if isinstance(receipt, dict) else None
    if phase == RECEIPT_VERIFYING_PHASE:
        return PHASE_VERIFYING, STEP_VERIFYING
    return PHASE_REPAIRING, STEP_REPAIRING


def receipt_checkpoint(receipt: dict | None, *, step: str, elapsed_seconds: float,
                       source_commit: str, configuration_sha256: str) -> dict:
    """Bounded progress for the control plane: numbers, hashes and one step.

    Only non-negative integer counters within their bound are copied, so a
    receipt field that is missing, textual, negative or implausible is left out
    rather than forwarded. Nothing textual from the model, the source tree or
    the host filesystem is included at all.
    """
    checkpoint = {
        "step": step,
        "elapsed_seconds": min(max(0, int(elapsed_seconds)),
                               MAX_CHECKPOINT_ELAPSED_SECONDS),
        "source_commit": source_commit,
        "configuration_sha256": configuration_sha256,
        "source_pinned": True,
    }
    for key in CHECKPOINT_COUNTERS:
        value = (receipt or {}).get(key)
        if type(value) is int and 0 <= value <= MAX_CHECKPOINT_COUNTER:
            checkpoint[key] = value
    return checkpoint


def archive_entry_count(payload: bytes) -> int:
    """Count the archive's file entries, for bounded progress only."""
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            return sum(1 for member in archive.infolist() if not member.is_dir())
    except (zipfile.BadZipFile, OSError, ValueError):
        return 0


def _counter(receipt: dict, key: str) -> int:
    lower, upper = RESULT_COUNTERS[key]
    value = receipt.get(key)
    if type(value) is not int or not lower <= value <= upper:
        raise RepairResultInvalid(
            f"the private receipt's {key} is not within the persisted result range")
    return value


def _digest(receipt: dict, key: str, pattern: re.Pattern[str]) -> str:
    value = receipt.get(key)
    text = value.removeprefix("sha256:").lower() if isinstance(value, str) else ""
    if not pattern.fullmatch(text):
        raise RepairResultInvalid(f"the private receipt's {key} is not a usable digest")
    return text


def bounded_repair_result(receipt: dict, patch: bytes, *, run_id: str,
                          configuration_sha256: str, source_commit: str,
                          model_digest: str) -> dict:
    """Build the one publishable result, validated against the private evidence.

    Everything here comes from what the child really wrote: its receipt and its
    `verified.patch`. The patch hash is recomputed from the file's bytes rather
    than trusted, the configuration and source identities must be the frozen
    ones, and an over-limit patch or document is refused instead of truncated.
    """
    if receipt.get("run_id") != run_id:
        # A leftover evidence directory from another run can never be published.
        raise RepairResultInvalid("the private receipt belongs to a different run")
    if receipt.get("mode") != "repair":
        raise RepairResultInvalid("the private receipt is not a repair run")
    if receipt.get("status") != "needs_review" or receipt.get("verification") != "passed":
        raise RepairResultInvalid("the private receipt records no verified candidate")
    if _digest(receipt, "configuration_sha256", HEX64) != configuration_sha256:
        raise RepairResultInvalid(
            "the private receipt was produced under a different configuration")
    if len(patch) > MAX_PATCH_BYTES:
        raise RepairResultTooLarge(
            "the verified patch exceeds the persisted patch limit and is not truncated")
    try:
        text = patch.decode("utf-8")
    except UnicodeError:
        raise RepairResultInvalid("the verified patch is not UTF-8 text") from None
    if not text:
        raise RepairResultInvalid("the verified patch is empty")
    if hashlib.sha256(patch).hexdigest() != _digest(receipt, "patch_sha256", HEX64):
        raise RepairResultInvalid(
            "the verified patch does not match the hash its receipt recorded")
    observed = receipt.get("model_observed")
    if not isinstance(observed, dict):
        raise RepairResultInvalid("the private receipt records no verified local model")
    name = observed.get("name")
    if not isinstance(name, str) or not MODEL_NAME.fullmatch(name):
        raise RepairResultInvalid("the observed model name is not an accepted identifier")
    digest = observed.get("digest")
    digest = digest.removeprefix("sha256:").lower() if isinstance(digest, str) else ""
    if digest != model_digest:
        raise RepairResultInvalid(
            "the observed local model is not the one the configuration pins")
    result = {
        "kind": WORK_ITEM_KIND,
        "status": "needs_review",
        "verification": "passed",
        "configuration_sha256": configuration_sha256,
        "source_commit": source_commit,
        "source_tree_sha256": _digest(receipt, "source_tree_sha256", HEX64),
        "candidate_tree_sha256": _digest(receipt, "candidate_tree_sha256", HEX64),
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "patch": text,
        "checks_passed": _counter(receipt, "checks_passed"),
        "turns": _counter(receipt, "turns"),
        "tool_calls": _counter(receipt, "tool_calls"),
        "tokens_observed": _counter(receipt, "tokens_observed"),
        "model_name": name,
        "model_digest": digest,
    }
    if result["candidate_tree_sha256"] == result["source_tree_sha256"]:
        # A candidate identical to the source changed nothing, so there is no
        # patch to review however convincing the receipt looks.
        raise RepairResultInvalid(
            "the candidate tree is identical to the source tree")
    if set(result) != set(RESULT_KEYS):  # pragma: no cover - guards the key set
        raise RepairResultInvalid("the repair result key set is not the accepted one")
    if len(json.dumps(result).encode("utf-8")) > MAX_REPAIR_RESULT_BYTES:
        raise RepairResultTooLarge(
            "the repair result exceeds the persisted limit and is not truncated")
    return result


@dataclass(frozen=True)
class ChildRequest:
    """Everything the credential-free repair child is told, and nothing else."""

    configuration: Path
    source_zip: Path
    goal_file: Path
    evidence: Path
    run_root: Path
    result: Path
    max_seconds: int
    parent_pid: int
    docker_cli: str


@dataclass
class RepairRuntimeWorker:
    """Claims and completes one policy's repository-repair work items."""

    client: FactoryRuntimeClient
    project_id: str
    policy_id: str
    spec: FactorySpec
    configuration: bytes
    source_url: str
    source_commit: str
    evidence_root: Path
    work_root: Path
    docker_cli: str
    docker_config: str | None = None
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    poll_seconds: float = DEFAULT_POLL_SECONDS
    capacity_max_age: float = CAPACITY_MAX_AGE_SECONDS
    authority_max_age: float = AUTHORITY_MAX_AGE_SECONDS

    def __post_init__(self) -> None:
        if not MIN_LEASE_SECONDS <= self.lease_seconds <= MAX_LEASE_SECONDS:
            raise ValueError(
                f"lease seconds must be between {MIN_LEASE_SECONDS} and {MAX_LEASE_SECONDS}")
        if not HEX40.fullmatch(self.source_commit):
            raise ValueError("the approved source commit must be 40 lowercase hex characters")
        # Parsing the frozen bytes must reproduce the frozen fingerprint.
        if not HEX64.fullmatch(self.spec.digest):
            raise ValueError("the frozen configuration fingerprint is not a SHA-256 digest")
        self.evidence_root = Path(self.evidence_root)
        self.work_root = Path(self.work_root)
        self._capacity: dict | None = None
        self._capacity_observed_at = 0.0
        self._authority: dict | None = None
        self._authority_observed_at = 0.0

    @property
    def configuration_sha256(self) -> str:
        return self.spec.digest

    @property
    def max_run_seconds(self) -> int:
        """The child's bound: the frozen wall budget plus fixed setup overhead."""
        return int(self.spec.limits.wall_seconds) + REPAIR_SETUP_GRACE_SECONDS

    # -- authority --------------------------------------------------------
    def verify_registration(self) -> dict:
        """The worker's own enabled project registration, or an actionable failure."""
        return enabled_registration(self.client, self.project_id)

    def verify_policy(self) -> dict:
        """Confirm the approved policy still binds this worker to these inputs.

        The policy is the rollout boundary, so every part of it is compared
        against what this process was explicitly started with. A revoked,
        disabled, re-pointed or reconfigured policy is refused rather than
        reinterpreted.
        """
        rows = self.client.select("project_repair_policies", {
            "id": f"eq.{self.policy_id}",
            "project_id": f"eq.{self.project_id}",
            "select": "id,project_id,worker_user_id,label,enabled,source_url,"
                      "source_owner,source_repo,source_commit,configuration_sha256,revoked_at",
        })
        if len(rows) != 1:
            raise PolicyUnavailable(
                "this project has no readable repair policy with the requested id; "
                "a project owner or admin must call register_project_repair_policy")
        policy = rows[0]
        if policy.get("revoked_at") or not policy.get("enabled"):
            raise PolicyUnavailable("this repair policy is revoked or disabled")
        if policy.get("worker_user_id") != self.client.worker_user_id():
            raise PolicyUnavailable(
                "this repair policy designates a different worker identity")
        for field, expected in (("source_url", self.source_url),
                                ("source_commit", self.source_commit),
                                ("configuration_sha256", self.configuration_sha256)):
            if policy.get(field) != expected:
                raise PolicyUnavailable(
                    f"the repair policy's {field} is not the one this worker was started "
                    "with; register a new policy instead of changing an approved one")
        owner, repo = parse_github_url(self.source_url)
        if (policy.get("source_owner"), policy.get("source_repo")) != (owner, repo):
            raise PolicyUnavailable(
                "the repair policy's frozen repository is not the approved source URL")
        return policy

    def verify_authority(self, *, force: bool = False) -> dict:
        """Re-read the registration and the policy when the last read is stale.

        A revoked policy or registration must stop a polling worker rather than
        leave it asking a control plane that will refuse it forever, and a
        worker that is idle for hours must not keep claiming authority it was
        granted at startup.
        """
        fresh = (self._authority is not None
                 and time.monotonic() - self._authority_observed_at < self.authority_max_age)
        if fresh and not force:
            return dict(self._authority or {})
        observed = {"registration": self.verify_registration(),
                    "policy": self.verify_policy()}
        self._authority = observed
        self._authority_observed_at = time.monotonic()
        return dict(observed)

    def verify_capacity(self, *, force: bool = False) -> dict:
        """Observe local Docker and the installed local model, spending no tokens.

        This is the readiness gate: the context, daemon and immutable image are
        inspected and the pinned model's local installation is confirmed. No
        container is started, no image is pulled and no inference is requested.
        """
        fresh = (self._capacity is not None
                 and time.monotonic() - self._capacity_observed_at < self.capacity_max_age)
        if fresh and not force:
            return dict(self._capacity or {})

        async def observe() -> dict:
            runner = DockerRunner(self.spec.runner, docker_cli=self.docker_cli)
            model = LocalToolModel(self.spec.model)
            return {"runner": await runner.preflight(), "model": await model.verify()}

        try:
            observed = asyncio.run(observe())
        except CodingError as exception:
            raise CapacityUnavailable(
                forwarded_child_code(exception.code),
                f"local repair capacity is not ready: {exception}") from None
        self._capacity = observed
        self._capacity_observed_at = time.monotonic()
        return dict(observed)

    def _confirm_authority(self) -> None:
        """Re-check the registration and the policy, propagating their loss.

        An unreachable control plane cannot answer the question at all, so that
        is left to the next poll rather than mistaken for a revocation.
        """
        try:
            self.verify_authority(force=True)
        except ControlPlaneUnavailable:
            return

    # -- transitions ------------------------------------------------------
    def claim(self) -> dict | None:
        return self.client.rpc_row("claim_repair_work", {
            "p_policy_id": self.policy_id,
            "p_configuration_sha256": self.configuration_sha256,
            "p_lease_seconds": self.lease_seconds,
        })

    def heartbeat(self, claim: dict, *, phase: str | None = None,
                  checkpoint: dict | None = None, source_ref: str | None = None,
                  source_commit: str | None = None,
                  source_digest: str | None = None) -> dict:
        try:
            state = self.client.rpc_row("heartbeat_repair_run", {
                "p_run_id": claim["run_id"],
                "p_lease_token": claim["lease_token"],
                "p_phase": phase,
                "p_checkpoint": checkpoint,
                "p_source_ref": source_ref,
                "p_source_commit": source_commit,
                "p_source_digest": source_digest,
                "p_lease_seconds": self.lease_seconds,
            })
        except FactoryRuntimeError as exception:
            # A refused identity means another attempt pinned this work item
            # first, or this attempt already recorded a different ref, commit or
            # digest. The refused call recorded nothing and extended no lease, so
            # it is a source conflict rather than an unknown worker failure.
            if any(refusal in str(exception) for refusal in SOURCE_CONFLICT_REFUSALS):
                raise SourceIdentityConflict(
                    "the control plane refused this attempt's source identity") from exception
            raise
        if state is None:
            raise RepairRuntimeError("heartbeat returned no run state")
        return state

    def _heartbeat_inside_lease(self, claim: dict, expires_at: str | None,
                                **fields: object) -> dict:
        """Heartbeat, absorbing a brief control-plane outage.

        An unreachable control plane is not a reason to abandon an attempt that
        still holds minutes of lease, so the call is retried while the lease has
        room for another try. Once that room is gone the attempt is given up and
        the lease expires, which is what makes it reclaimable.
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

    def _still_fenced_in(self, claim: dict, state: dict) -> bool:
        if state.get("lease_valid"):
            return True
        print(f"run {claim['run_id']} stopped: {state.get('reason', 'lease_lost')}", flush=True)
        return False

    # -- loop -------------------------------------------------------------
    def run_once(self) -> bool:
        """Claim and complete at most one repair work item.

        Authority and local capacity are both confirmed before anything is
        claimed, so a revoked policy or a missing local runner never turns into
        a claimed attempt that cannot be served.
        """
        self.verify_authority()
        self.verify_capacity()
        claim = self.claim()
        if claim is None:
            return False
        print(f"claimed repair run {claim['run_id']} attempt {claim['attempt']}"
              f"/{claim['max_attempts']}", flush=True)
        self._execute(claim)
        return True

    def forever(self, max_runs: int | None = None) -> int:
        """Claim and complete repairs until stopped, or until it cannot work.

        Supervision absorbs a transient refusal but never spins: a credential
        this identity can no longer refresh, a registration or policy an owner
        revoked and a control plane that keeps refusing all stop the worker
        instead of printing the same traceback forever. There is no fallback
        model, runner or configuration to widen to.
        """
        completed = 0
        failures = 0
        print(f"Oryveta repair worker ready for policy {self.policy_id} "
              f"in project {self.project_id}; press Ctrl+C to stop", flush=True)
        while max_runs is None or completed < max_runs:
            try:
                worked = self.run_once()
            except (CredentialError, PolicyUnavailable):
                # Already conclusive: no further round trip can change it.
                raise
            except Exception:
                traceback.print_exc()
                # A claim is the only place lost authority surfaces, so the
                # grant and the policy are re-checked before polling again;
                # losing either is as terminal as a refused credential.
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

    # -- execution --------------------------------------------------------
    def _execute(self, claim: dict) -> None:
        self.work_root.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix=RUN_DIRECTORY_PREFIX,
                                          dir=str(self.work_root)))
        try:
            self._mark_run_directory(claim, directory)
            self._repair(claim, directory)
        except Exception as exception:
            code = error_code(exception)
            # The traceback is operator-only; only the short code is persisted.
            traceback.print_exc()
            print(f"run {claim['run_id']} failed: {code}", flush=True)
            self._report_failure(claim, code)
        finally:
            # The disposable snapshot tree goes; the private evidence stays.
            shutil.rmtree(directory, ignore_errors=True)

    @staticmethod
    def _mark_run_directory(claim: dict, directory: Path) -> None:
        """Name the attempt that owns this tree, for a later startup sweep.

        The marker carries only what identifies a dead attempt: no lease token,
        no credential, no goal and no source payload.
        """
        private_write(directory / RUN_MARKER_NAME, json.dumps({
            "worker_pid": os.getpid(),
            "run_id": claim["run_id"],
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }).encode("utf-8"))

    def _accept_claim(self, claim: dict) -> str:
        """Refuse any claim that is not this policy's frozen, pinned work.

        A worker that executes code must never widen its own scope, so a claim
        whose kind, policy, project, configuration or source is not the one this
        process was started with is a mismatch, not something to interpret.
        """
        for field, expected in (("kind", WORK_ITEM_KIND),
                                ("project_id", self.project_id),
                                ("repair_policy_id", self.policy_id),
                                ("configuration_sha256", self.configuration_sha256),
                                ("source_url", self.source_url),
                                ("pinned_source_commit", self.source_commit)):
            if claim.get(field) != expected:
                raise ClaimMismatch(
                    f"the claimed work item's {field} is not this repair policy's")
        goal = claim.get("goal")
        if (not isinstance(goal, str) or not goal.strip()
                or not 1 <= len(goal.encode("utf-8")) <= MAX_GOAL_BYTES):
            raise ClaimMismatch("the claimed work item carries no bounded repair goal")
        # The frozen owner/repo were parsed by the migration's SQL mirror of
        # parse_github_url at admission. Re-parse the frozen URL with the real
        # importer parser and require all three identities to agree, so a
        # divergence between the two parsers cannot redirect this attempt.
        owner, repo = parse_github_url(claim["source_url"])
        if f"{owner}/{repo}" != f"{claim.get('source_owner')}/{claim.get('source_repo')}":
            raise InvalidRepository(
                "frozen source URL does not match the recorded repository")
        return goal

    def _evidence_directory(self, claim: dict) -> Path:
        """A fresh private evidence directory for exactly this execution.

        The directory must not already exist: the local loop refuses to reuse
        one, and a unique name per launch is what makes a leftover tree from an
        earlier attempt unreadable as this attempt's result.
        """
        parent = self.evidence_root / str(claim["work_item_id"])
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = parent / (f"run-{claim['run_id']}-attempt-{claim['attempt']}"
                              f"-{secrets.token_hex(4)}")
        if directory.exists() or directory.is_symlink():
            raise RepairResultInvalid(
                "a private evidence directory for this execution already exists")
        return directory

    def _repair(self, claim: dict, directory: Path) -> None:
        goal = self._accept_claim(claim)
        lease = claim.get("lease_expires_at")
        state = self._heartbeat_inside_lease(
            claim, lease, phase=PHASE_FETCHING_SOURCE,
            checkpoint=self._checkpoint(STEP_FETCHING_SOURCE, 0))
        lease = state.get("lease_expires_at") or lease
        if not self._still_fenced_in(claim, state):
            return
        # Only the approved pinned commit is ever fetched. There is no
        # default-branch fallback: a pin that can be silently ignored is worse
        # than no pin at all.
        slug, payload = fetch_public_github_repo(self.source_url, ref=self.source_commit)
        expected = f"{claim['source_owner']}/{claim['source_repo']}"
        if slug != expected:
            raise InvalidRepository("fetched repository is not the approved policy source")
        reference = f"github.com/{slug}"
        pinned_ref = claim.get("pinned_source_ref") or None
        if pinned_ref and pinned_ref != reference:
            raise SourceIdentityConflict("the fetched source is not the pinned reference")
        commit = archive_commit(payload)
        if not commit:
            raise SourceCommitUnresolved("the fetched archive names no commit")
        if commit != self.source_commit:
            raise SourceIdentityConflict("the fetched archive is not the approved commit")
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        private_write(directory / "source.zip", payload)
        checkpoint = self._checkpoint(STEP_SNAPSHOT_READY, 0)
        checkpoint["archive_bytes"] = len(payload)
        checkpoint["archive_entries"] = archive_entry_count(payload)
        state = self._heartbeat_inside_lease(
            claim, lease, phase=PHASE_REPAIRING, checkpoint=checkpoint,
            source_ref=reference, source_commit=commit, source_digest=digest)
        lease = state.get("lease_expires_at") or lease
        if not self._still_fenced_in(claim, state):
            return
        request = self._prepare_child(claim, directory, goal)
        outcome = self._repair_in_child(claim, request, lease)
        if outcome is None:
            return
        lease = outcome.get("lease_expires_at") or lease
        result = self._publish_result(claim, request, outcome["run_id"])
        state = self._heartbeat_inside_lease(
            claim, lease, phase=PHASE_RECORDING_RESULT,
            checkpoint=self._checkpoint(STEP_RECORDING_RESULT, outcome["elapsed_seconds"]))
        if not self._still_fenced_in(claim, state):
            # The lease was lost while the result was being validated. A stale
            # attempt must not publish, even with a verified candidate in hand.
            return
        published = self.client.rpc_row("finish_repair_run", {
            "p_run_id": claim["run_id"],
            "p_lease_token": claim["lease_token"],
            "p_result": result,
        }) or {}
        if published.get("accepted"):
            print(f"run {claim['run_id']} completed: a candidate patch of "
                  f"{len(result['patch'].encode('utf-8'))} bytes is ready for review",
                  flush=True)
        else:
            print(f"run {claim['run_id']} result refused: "
                  f"{published.get('reason', 'unknown')}", flush=True)

    def _checkpoint(self, step: str, elapsed_seconds: float,
                    receipt: dict | None = None) -> dict:
        return receipt_checkpoint(
            receipt, step=step, elapsed_seconds=elapsed_seconds,
            source_commit=self.source_commit,
            configuration_sha256=self.configuration_sha256)

    def _prepare_child(self, claim: dict, directory: Path, goal: str) -> ChildRequest:
        """Lay out the private inputs for one credential-free child process."""
        configuration = directory / "configuration.json"
        private_write(configuration, self.configuration)
        goal_file = directory / "goal.txt"
        private_write(goal_file, goal.encode("utf-8"))
        run_root = directory / "runs"
        run_root.mkdir(mode=0o700, exist_ok=True)
        return ChildRequest(
            configuration=configuration,
            source_zip=directory / "source.zip",
            goal_file=goal_file,
            evidence=self._evidence_directory(claim),
            run_root=run_root,
            result=directory / "child-result.json",
            max_seconds=self.max_run_seconds,
            parent_pid=os.getpid(),
            docker_cli=self.docker_cli,
        )

    def child_command(self, request: ChildRequest) -> list[str]:
        """The repair child's argument vector, as an overridable seam.

        The child carries its own wall-clock bound, a little past the worker's,
        so a worker that is killed hard still leaves a child that stops by
        itself without pre-empting the worker's own timeout. No credential,
        lease token, project identity or goal text appears in this vector.
        """
        bound = int(request.max_seconds + CHILD_DEADLINE_GRACE_SECONDS)
        return [sys.executable, "-m", "oryveta_engine.coding_child",
                "--config", str(request.configuration),
                "--source-zip", str(request.source_zip),
                "--goal-file", str(request.goal_file),
                "--output", str(request.evidence),
                "--run-root", str(request.run_root),
                "--result", str(request.result),
                "--max-seconds", str(bound),
                "--parent-pid", str(request.parent_pid),
                "--docker-cli", str(request.docker_cli)]

    def _repair_in_child(self, claim: dict, request: ChildRequest,
                         lease_expires_at: str | None) -> dict | None:
        """Supervise the repair child, terminating it when the lease is lost.

        The parent keeps heartbeating while the child waits on local inference
        and on the controller-owned checks, and reports the child's own recorded
        progress. Cancellation, revocation, a stolen lease and the worker's own
        bound all stop the child's whole process group, and a stopped attempt
        publishes nothing.
        """
        error_path = request.result.parent / "child-stderr.log"
        command = self.child_command(request)
        interval = max(1.0, min(self.lease_seconds / 3.0, MAX_HEARTBEAT_INTERVAL))
        deadline = time.monotonic() + request.max_seconds
        started = time.monotonic()
        lease = lease_expires_at or claim.get("lease_expires_at")
        receipt_path = request.evidence / "receipt.json"
        with error_path.open("wb") as errors:
            child = subprocess.Popen(
                command, cwd=str(request.result.parent),
                env=repair_child_environment(
                    request.result.parent, docker_cli=request.docker_cli,
                    docker_config=self.docker_config),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                # The child leads its own process group, so fencing can stop a
                # forked repair, its runner and its containers' client processes
                # and never the worker itself.
                start_new_session=True,
            )
            try:
                while True:
                    try:
                        remaining = max(0.0, deadline - time.monotonic())
                        code = child.wait(timeout=min(interval, remaining))
                        if time.monotonic() >= deadline:
                            raise RepairTimeout("the repair exceeded its bounded runtime")
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    if time.monotonic() >= deadline:
                        self._terminate(child)
                        raise RepairTimeout("the repair exceeded its bounded runtime")
                    receipt = read_receipt(receipt_path)
                    phase, step = receipt_progress(receipt)
                    state = self._heartbeat_inside_lease(
                        claim, lease, phase=phase,
                        checkpoint=self._checkpoint(
                            step, time.monotonic() - started, receipt))
                    lease = state.get("lease_expires_at") or lease
                    if not state.get("lease_valid"):
                        # Cancellation, revocation or a stolen lease: stop the
                        # repair, do not attempt to publish anything.
                        self._terminate(child)
                        print(f"run {claim['run_id']} terminated repair child: "
                              f"{state.get('reason', 'lease_lost')}", flush=True)
                        return None
            finally:
                self._terminate(child)
        elapsed = time.monotonic() - started
        if code == CHILD_ORPHANED_EXIT:
            raise RepairProcessError("the repair child lost its worker process")
        if code == CHILD_DEADLINE_EXIT:
            raise RepairTimeout("the repair child stopped at its own bound")
        report = self._child_report(request.result)
        if code != 0:
            print(self._child_error(error_path), flush=True)
            raise RepairChildFailure(
                forwarded_child_code(report.get("error_code")),
                f"the repair child reported {report.get('status', 'no outcome')}")
        if report.get("status") != "needs_review":
            raise RepairChildFailure(
                forwarded_child_code(report.get("error_code")),
                "the repair child produced no reviewable candidate")
        run_id = report.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise RepairResultInvalid("the repair child reported no usable run identity")
        return {"run_id": run_id, "elapsed_seconds": elapsed, "lease_expires_at": lease}

    def _publish_result(self, claim: dict, request: ChildRequest, run_id: str) -> dict:
        """Validate the private evidence and record what was kept for the operator."""
        receipt = read_receipt(request.evidence / "receipt.json")
        if receipt is None:
            raise RepairResultInvalid("the repair child wrote no readable receipt")
        patch_path = request.evidence / "verified.patch"
        try:
            with patch_path.open("rb") as handle:
                patch = handle.read(MAX_PATCH_BYTES + 1)
        except OSError:
            raise RepairResultInvalid("the repair child wrote no verified patch") from None
        result = bounded_repair_result(
            receipt, patch, run_id=run_id,
            configuration_sha256=self.configuration_sha256,
            source_commit=self.source_commit,
            model_digest=self.spec.model.digest)
        # An operator-only index of the attempt this evidence belongs to. No
        # lease token, no credential and nothing client-visible.
        private_write(request.evidence / "worker-run.json", json.dumps({
            "work_item_id": claim["work_item_id"],
            "run_id": claim["run_id"],
            "attempt": claim["attempt"],
            "project_id": self.project_id,
            "repair_policy_id": self.policy_id,
            "configuration_sha256": self.configuration_sha256,
            "source_url": self.source_url,
            "source_commit": self.source_commit,
            "local_run_id": run_id,
            "published_patch_sha256": result["patch_sha256"],
            "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }, indent=2).encode("utf-8"))
        return result

    def _child_report(self, path: Path) -> dict:
        """Read the child's bounded outcome report, tolerating its absence."""
        try:
            with path.open("rb") as handle:
                payload = handle.read(MAX_CHILD_RESULT_BYTES + 1)
        except OSError:
            return {}
        if len(payload) > MAX_CHILD_RESULT_BYTES:
            raise RepairResultInvalid("the repair child's outcome report is too large")
        try:
            report = strict_json(payload)
        except (ValueError, UnicodeError, RecursionError):
            raise RepairResultInvalid(
                "the repair child's outcome report is not readable JSON") from None
        return report if isinstance(report, dict) else {}

    @staticmethod
    def _child_error(path: Path) -> str:
        try:
            with path.open("rb") as handle:
                return handle.read(MAX_CHILD_ERROR_BYTES).decode("utf-8", "replace")
        except OSError:
            return "the repair child produced no diagnostics"

    @staticmethod
    def _terminate(child: subprocess.Popen) -> None:
        """Stop the owned process group, even if its original leader exited."""
        signal_process_group(child, signal.SIGTERM)
        try:
            child.wait(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # Leader exit is not proof that its helpers exited. Kill remaining
            # group members without relying on platform-specific signal-0 probes.
            signal_process_group(child, signal.SIGKILL)
            child.wait()

    def _report_failure(self, claim: dict, code: str) -> None:
        try:
            outcome = self.client.rpc_row("fail_repair_run", {
                "p_run_id": claim["run_id"],
                "p_lease_token": claim["lease_token"],
                "p_error_code": code,
            }) or {}
        except Exception:
            # Reporting failed too. The lease expires and the next claim
            # reclaims the attempt, so the work item never stays silently
            # 'running'.
            print(f"run {claim['run_id']} failure could not be recorded; "
                  "the lease will expire and be reclaimed", flush=True)
            return
        if not outcome.get("accepted"):
            reason = outcome.get("reason", "unknown")
            print(f"run {claim['run_id']} failure report refused: {reason}", flush=True)
            if reason in TERMINAL_FAILURE_REASONS:
                # The attempt was settled by an authority path, not a fence:
                # this worker has lost the right to serve the policy, so it
                # stops instead of claiming again.
                raise PolicyUnavailable(
                    "the control plane no longer accepts this worker for the policy "
                    f"({reason}); a project owner or admin must re-enable it")
        elif outcome.get("retry_scheduled"):
            print(f"run {claim['run_id']} will be retried against the same commit",
                  flush=True)
        else:
            print(f"work item {claim['work_item_id']} failed terminally", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m oryveta_engine.coding_worker",
        description="Oryveta policy-scoped durable repository-repair worker. Repair is "
                    "opt-in: the policy, the operator configuration and the approved "
                    "source commit must all be named explicitly.")
    parser.add_argument("--credentials", default=os.environ.get(CREDENTIALS_ENV),
                        help=f"protected dedicated worker credential file "
                             f"(or ${CREDENTIALS_ENV})")
    parser.add_argument("--project", default=None,
                        help="project UUID to serve; defaults to the credential file's "
                             "project_id")
    parser.add_argument("--policy", required=True,
                        help="approved project_repair_policies id this worker serves")
    parser.add_argument("--config", required=True,
                        help="operator-owned JSON repair specification, frozen at startup")
    parser.add_argument("--source-url", required=True,
                        help="approved public https://github.com/owner/repo source URL")
    parser.add_argument("--source-commit", required=True,
                        help="approved 40-character lowercase commit SHA")
    parser.add_argument("--evidence-root", required=True,
                        help="private directory that retains full per-run evidence")
    parser.add_argument("--work-root", default=None,
                        help="private parent directory for disposable per-run trees, "
                             "swept for the trees of dead attempts at startup; it must "
                             "be visible to the local Docker daemon")
    parser.add_argument("--docker-cli", default=None,
                        help="trusted docker executable; resolved from PATH when omitted")
    parser.add_argument("--docker-config", default=os.environ.get(DOCKER_CONFIG_ENV),
                        help="operator Docker configuration directory; only its context "
                             f"metadata is copied for the child (or ${DOCKER_CONFIG_ENV})")
    parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS,
                        help=f"lease length, {MIN_LEASE_SECONDS}-{MAX_LEASE_SECONDS} seconds")
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS,
                        help="idle delay between claim attempts in continuous mode")
    parser.add_argument("--once", action="store_true",
                        help="claim and complete at most one work item, then exit")
    parser.add_argument("--max-runs", type=int, default=None,
                        help="stop after this many completed claims (continuous mode)")
    return parser


def _stop(signum, frame) -> None:
    # The supervision loop tears down the repair process group on
    # KeyboardInterrupt, so SIGTERM must reach the same path.
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if not arguments.credentials:
        print(f"--credentials or ${CREDENTIALS_ENV} is required", file=sys.stderr)
        return 2
    credentials_path = Path(arguments.credentials).absolute()
    try:
        credentials = WorkerCredentials.load(credentials_path)
    except CredentialError as exception:
        print(str(exception), file=sys.stderr)
        return 2
    project_id = arguments.project or credentials.project_id
    if not project_id:
        print("--project is required when the credential file has no project_id",
              file=sys.stderr)
        return 2
    try:
        configuration, spec = frozen_configuration(arguments.config)
        docker_cli = resolve_docker_cli(arguments.docker_cli)
        evidence_root = prepare_private_root(Path(arguments.evidence_root).absolute(),
                                             "evidence root")
        # One service per credential directory, held for this worker's whole
        # life, including across credential rotation.
        with session_lock(credentials_path.parent), contextlib.ExitStack() as resources:
            # An operator-supplied work root is kept; a worker-made one is
            # disposable and goes when this process does.
            work_root = prepare_private_root(
                Path(arguments.work_root).absolute() if arguments.work_root
                else Path(resources.enter_context(
                    tempfile.TemporaryDirectory(prefix="oryveta-repair-"))),
                "work root")
            # The sanitized context-only configuration is what both this process
            # and its children use, so what was validated is what will run.
            context_root = Path(resources.enter_context(
                tempfile.TemporaryDirectory(prefix=DOCKER_CONFIG_DIRECTORY + "-", dir=work_root)))
            docker_config = private_docker_config(
                arguments.docker_config, context_root, spec.runner.docker_context)
            os.environ[DOCKER_CONFIG_ENV] = docker_config
            previous = signal.signal(signal.SIGTERM, _stop)
            try:
                with FactoryRuntimeClient(credentials) as client:
                    worker = RepairRuntimeWorker(
                        client=client, project_id=project_id, policy_id=arguments.policy,
                        spec=spec, configuration=configuration,
                        source_url=arguments.source_url,
                        source_commit=arguments.source_commit,
                        evidence_root=evidence_root, work_root=work_root,
                        docker_cli=docker_cli, docker_config=docker_config,
                        lease_seconds=arguments.lease_seconds,
                        poll_seconds=arguments.poll_seconds,
                    )
                    authority = worker.verify_authority(force=True)
                    registration, policy = authority["registration"], authority["policy"]
                    print(f"worker registration {registration['label']} is enabled; "
                          f"repair policy {policy['label']} is approved for "
                          f"{policy['source_url']} at {worker.source_commit} "
                          f"under configuration {worker.configuration_sha256}", flush=True)
                    reclaimed = sweep_stale_work_roots(work_root)
                    if reclaimed:
                        print(f"reclaimed stale run directories: {reclaimed}", flush=True)
                    capacity = worker.verify_capacity(force=True)
                    print("local capacity observed: Docker "
                          f"{capacity['runner'].get('daemon_version', 'unknown')} on "
                          f"{capacity['runner'].get('daemon_os', 'unknown')}, image "
                          f"{capacity['runner'].get('image_id', 'unknown')}, model "
                          f"{capacity['model'].get('name', 'unknown')}", flush=True)
                    if arguments.once:
                        print("processed one repair work item" if worker.run_once()
                              else "no queued repair work item", flush=True)
                        return 0
                    worker.forever(max_runs=arguments.max_runs)
            finally:
                signal.signal(signal.SIGTERM, previous)
        return 0
    except KeyboardInterrupt:
        print("stopped", flush=True)
        return 0
    except (FactoryRuntimeError, CodingError, ValueError) as exception:
        print(str(exception), file=sys.stderr)
        return 1
    except OSError as exception:
        print(f"repair worker setup failed ({type(exception).__name__}); check the "
              "private credential, evidence and work directories", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
