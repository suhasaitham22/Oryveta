"""Project-scoped durable analysis worker for the Supabase metadata authority.

This worker is a client of `supabase/migrations/durable_factory_runtime.sql`.
It authenticates as its own Supabase Auth service identity, claims work only in
projects where an owner/admin registered that identity, and performs exactly one
real task: a bounded public-GitHub snapshot plus the existing static analyzer.

Deliberate boundaries:
  * The service-role key never participates. The worker holds a normal Auth
    session, refreshes it with the ordinary refresh-token grant, and stores the
    rotating credential in a protected local file that is replaced atomically.
  * Credentials are never printed, never passed to the child process and never
    written to a run row or event.
  * The lease token is a fencing value. A cancelled, revoked, stolen or expired
    lease terminates the owned child process and cannot publish a result, so a
    fenced attempt never produces a misleading success.
  * Analysis runs in a real child process, so cancellation actually stops the
    CPU work instead of only discarding its output. Imported source is read,
    never executed.
  * Nothing here resumes partial analysis. A reclaimed attempt re-fetches the
    work item's pinned commit and recomputes from scratch; what carries over is
    the frozen input and that pin, so a retry analyses the commit the first
    attempt resolved instead of wherever the default branch has moved to.
  * The analysis child leads its own process group and carries both its own
    wall-clock bound and a parent-death check, and a startup sweep reclaims the
    snapshot trees of attempts whose worker is gone. None of that survives
    losing the host: an attempt whose worker disappears is recovered by its
    lease expiring, which is the only guarantee this worker makes.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import httpx

from .repositories import InvalidRepository, fetch_public_github_repo, parse_github_url, snapshot_zip

CREDENTIALS_ENV = "ORYVETA_WORKER_CREDENTIALS"

MIN_LEASE_SECONDS = 15
MAX_LEASE_SECONDS = 900
DEFAULT_LEASE_SECONDS = 300
DEFAULT_POLL_SECONDS = 5.0
DEFAULT_MAX_RUN_SECONDS = 900
MAX_HEARTBEAT_INTERVAL = 30.0
TERMINATE_GRACE_SECONDS = 5.0
REFRESH_SKEW_SECONDS = 60.0

# The child's own bound sits this far past the worker's, which is longer than
# any heartbeat interval. A live worker therefore always reports the timeout
# itself, and the child's bound only matters once no worker is left to report.
CHILD_DEADLINE_GRACE_SECONDS = 2 * MAX_HEARTBEAT_INTERVAL

# A momentary control-plane outage must not spend one of a work item's few
# attempts, so a failed heartbeat is retried while the granted lease still has
# room for another try plus this margin.
HEARTBEAT_RETRY_BACKOFF_SECONDS = 2.0
MAX_HEARTBEAT_RETRIES = 3
LEASE_RETRY_MARGIN_SECONDS = 2.0

# Continuous mode stops instead of spinning: lost authority is terminal at
# once, and a control plane that keeps refusing gets this many tries.
MAX_CONSECUTIVE_CLAIM_FAILURES = 5

# Per-run snapshot directories, and the marker naming the attempt that owns
# one so a startup sweep can tell a dead attempt from a live one.
RUN_DIRECTORY_PREFIX = "oryveta-run-"
RUN_MARKER_NAME = ".oryveta-run.json"

# The control plane raises, rather than returns, when a heartbeat's resolved
# source identity is not the one this attempt or this work item is bound to.
# These are its two messages; both mean the same thing to a worker.
SOURCE_CONFLICT_REFUSALS = (
    # Per attempt, and raised for a changed ref, commit or digest alike.
    "source identity already recorded for this attempt",
    # Raised when the effective identity is not the work item's pin.
    "source identity conflicts with the work item pin",
)

# The metadata authority refuses results above 256 KB. Keep a margin and cap
# persisted findings, flagging the cap instead of silently dropping evidence.
MAX_RESULT_BYTES = 262_144
MAX_PERSISTED_FINDINGS = 200
MAX_CHILD_RESULT_BYTES = 8 * 1024 * 1024
MAX_CHILD_ERROR_BYTES = 2048


class FactoryRuntimeError(RuntimeError):
    """A worker-side failure that is reported with a short durable code."""


class CredentialError(FactoryRuntimeError):
    """The worker credential file or its Auth session is unusable."""


class AnalysisTimeout(FactoryRuntimeError):
    """The supervised analysis child exceeded its bounded runtime."""


class AnalysisProcessError(FactoryRuntimeError):
    """The supervised analysis child exited without a usable result."""


class ControlPlaneUnavailable(FactoryRuntimeError):
    """The metadata authority could not be reached for this call."""


class SourceIdentityConflict(FactoryRuntimeError):
    """The fetched source is not the identity this work item pinned."""


class SourceCommitUnresolved(FactoryRuntimeError):
    """The fetched archive does not identify the commit it was produced from."""


def error_code(exception: BaseException) -> str:
    """Map an exception to a short code the metadata authority accepts.

    Codes are enumerated and lower-case, so an exception message, a credential
    or a host filesystem path can never reach a persisted row or event.
    """
    if isinstance(exception, InvalidRepository):
        return "invalid_repository"
    if isinstance(exception, AnalysisTimeout):
        return "analysis_timeout"
    if isinstance(exception, AnalysisProcessError):
        return "analysis_process_failed"
    if isinstance(exception, CredentialError):
        return "worker_credentials_rejected"
    if isinstance(exception, ControlPlaneUnavailable):
        return "control_plane_unavailable"
    if isinstance(exception, SourceIdentityConflict):
        return "source_identity_conflict"
    if isinstance(exception, SourceCommitUnresolved):
        return "source_commit_unresolved"
    # Control-plane transport failures are raised as ControlPlaneUnavailable
    # above, so an httpx error reaching here really is the source fetch.
    if isinstance(exception, (httpx.HTTPError, httpx.StreamError)):
        return "source_fetch_failed"
    if isinstance(exception, (json.JSONDecodeError, ValueError)):
        return "analysis_output_invalid"
    if isinstance(exception, OSError):
        return "worker_storage_error"
    return "worker_error"


# A GitHub zipball carries the full commit in the ZIP archive comment and
# abbreviates it in its single root folder ('pallets-click-2247b35/'). Reading
# both costs no extra request and does not trust a mutable branch name.
ARCHIVE_COMMENT_COMMIT = re.compile(r"[0-9a-f]{40}")
ARCHIVE_ROOT_COMMIT = re.compile(r".*-([0-9a-f]{7,40})")


def archive_commit(payload: bytes) -> str | None:
    """Resolve the commit a GitHub archive was produced from, or None.

    The archive comment is the authority because it holds the whole commit; the
    root folder's abbreviation is a cross-check. An archive whose root names a
    different commit than its comment is self-contradictory and is refused
    rather than resolved to either value. Without a comment only an unabridged
    commit in the root resolves, because a short prefix alone is not an
    identity a later attempt could pin or compare.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            comment = archive.comment
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    declared = comment.decode("ascii", "replace").strip() if comment else ""
    commit = declared if ARCHIVE_COMMENT_COMMIT.fullmatch(declared) else ""
    parts = PurePosixPath(names[0]).parts if names else ()
    root = ARCHIVE_ROOT_COMMIT.fullmatch(parts[0]) if parts else None
    abbreviated = root.group(1) if root else ""
    if not commit:
        return abbreviated if len(abbreviated) == 40 else None
    if abbreviated and not commit.startswith(abbreviated):
        raise SourceIdentityConflict(
            "the archive's root folder and its comment name different commits")
    return commit


def _safe_service_url(value: str) -> str:
    """Accept an HTTPS Supabase endpoint, or plain HTTP only on loopback."""
    url = str(value or "").strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise CredentialError("worker credentials must name an http(s) Supabase endpoint")
    if parts.username or parts.password or parts.query or parts.fragment or parts.path:
        raise CredentialError("worker credential endpoint must be a bare origin")
    if parts.scheme == "http" and parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise CredentialError("plain HTTP is only accepted for a loopback test stack")
    return url


@dataclass
class WorkerCredentials:
    """A dedicated Supabase Auth session held in a protected local file.

    Token fields are excluded from `repr` so an accidental log line, traceback
    or debugger frame cannot disclose them.
    """

    path: Path
    supabase_url: str
    publishable_key: str = field(repr=False)
    project_id: str | None = None
    refresh_token: str = field(default="", repr=False)
    access_token: str = field(default="", repr=False)
    expires_at: float = field(default=0.0, repr=False)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> WorkerCredentials:
        file = Path(path)
        if file.is_symlink():
            raise CredentialError("worker credential file must not be a symlink")
        try:
            info = file.stat()
        except FileNotFoundError as exc:
            raise CredentialError("worker credential file does not exist") from exc
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise CredentialError(
                "worker credential file must not be group or world accessible (chmod 600)")
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialError("worker credential file is not readable JSON") from exc
        if not isinstance(data, dict):
            raise CredentialError("worker credential file must contain a JSON object")
        refresh = str(data.get("refresh_token") or "")
        publishable = str(data.get("publishable_key") or data.get("anon_key") or "")
        if not refresh or not publishable:
            raise CredentialError(
                "worker credentials require publishable_key and refresh_token")
        expires = data.get("expires_at") or 0
        return cls(
            path=file,
            supabase_url=_safe_service_url(str(data.get("supabase_url") or "")),
            publishable_key=publishable,
            project_id=(str(data["project_id"]) if data.get("project_id") else None),
            refresh_token=refresh,
            access_token=str(data.get("access_token") or ""),
            expires_at=float(expires) if isinstance(expires, (int, float)) else 0.0,
        )

    def record_session(self, access_token: str, refresh_token: str, expires_at: float) -> None:
        """Persist a refreshed session, replacing the file atomically.

        Supabase rotates refresh tokens, so the new credential must be durable
        before it is relied upon: a crash between refresh and write would
        otherwise leave the worker holding a spent token.
        """
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        payload = json.dumps({
            "supabase_url": self.supabase_url,
            "publishable_key": self.publishable_key,
            "project_id": self.project_id,
            "refresh_token": self.refresh_token,
            "access_token": self.access_token,
            "expires_at": int(self.expires_at),
        }, indent=2) + "\n"
        directory = self.path.parent
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(directory), prefix=".oryveta-worker-", delete=False)
        try:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.replace(handle.name, self.path)
        except BaseException:
            handle.close()
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise


@contextlib.contextmanager
def _reachable(what: str):
    """Report a control-plane transport failure as its own, honest failure.

    Without this, an unreachable PostgREST or Auth endpoint raises the same
    httpx errors the GitHub importer raises, and the project owner is told the
    repository fetch failed when GitHub was never involved.
    """
    try:
        yield
    except (httpx.HTTPError, httpx.StreamError) as exception:
        # Malformed HTTP status lines can echo credentials too. Keep the
        # transport category, but never chain untrusted protocol text into logs.
        raise ControlPlaneUnavailable(
            f"the control plane could not be reached for {what} "
            f"({type(exception).__name__})") from None


class FactoryRuntimeClient:
    """Authenticated PostgREST/Auth client for one worker identity."""

    def __init__(self, credentials: WorkerCredentials, timeout: float = 25.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.credentials = credentials
        self._http = httpx.Client(
            base_url=credentials.supabase_url, timeout=timeout, trust_env=False,
            follow_redirects=False, transport=transport,
            headers={"apikey": credentials.publishable_key, "Accept": "application/json"},
        )

    def __enter__(self) -> FactoryRuntimeClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # -- session ----------------------------------------------------------
    def _refresh(self) -> None:
        with _reachable("a worker session refresh"):
            response = self._http.post(
                "/auth/v1/token", params={"grant_type": "refresh_token"},
                json={"refresh_token": self.credentials.refresh_token},
            )
        if response.status_code != 200:
            # The body may echo the submitted credential; report status only.
            raise CredentialError(
                f"worker session refresh was refused (HTTP {response.status_code}); "
                "re-provision the worker credential file")
        payload = response.json()
        access = str(payload.get("access_token") or "")
        refresh = str(payload.get("refresh_token") or "") or self.credentials.refresh_token
        if not access:
            raise CredentialError("worker session refresh returned no access token")
        expires_in = payload.get("expires_in")
        lifetime = float(expires_in) if isinstance(expires_in, (int, float)) else 3600.0
        self.credentials.record_session(access, refresh, time.time() + lifetime)

    def access_token(self, force_refresh: bool = False) -> str:
        if (force_refresh or not self.credentials.access_token
                or self.credentials.expires_at - time.time() <= REFRESH_SKEW_SECONDS):
            self._refresh()
        return self.credentials.access_token

    def worker_user_id(self) -> str:
        payload = self._request("GET", "/auth/v1/user")
        identity = str((payload or {}).get("id") or "")
        if not identity:
            raise CredentialError("worker session does not identify an Auth user")
        return identity

    # -- requests ---------------------------------------------------------
    def _request(self, method: str, path: str, *, json_body: object | None = None,
                 params: dict[str, str] | None = None) -> object:
        for attempt in (0, 1):
            token = self.access_token(force_refresh=attempt == 1)
            with _reachable(f"{method} {path}"):
                response = self._http.request(
                    method, path, json=json_body, params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            if response.status_code in {401, 403} and attempt == 0:
                continue  # An expired or rotated session gets exactly one retry.
            if response.is_error:
                # Response bodies can reflect Authorization headers or lease
                # arguments. Preserve only the two fixed protocol refusals
                # needed for source-conflict classification, never raw details.
                detail = ""
                try:
                    problem = response.json()
                except ValueError:
                    problem = None
                if isinstance(problem, dict) and problem.get("message") in SOURCE_CONFLICT_REFUSALS:
                    detail = f": {problem['message']}"
                raise FactoryRuntimeError(
                    f"{method} {path} failed with HTTP {response.status_code}{detail}")
            if not response.content:
                return None
            return response.json()
        raise FactoryRuntimeError(f"{method} {path} failed after a session refresh")

    def rpc(self, name: str, payload: dict[str, object]) -> object:
        return self._request("POST", f"/rest/v1/rpc/{name}", json_body=payload)

    def rpc_row(self, name: str, payload: dict[str, object]) -> dict | None:
        result = self.rpc(name, payload)
        if isinstance(result, list):
            return result[0] if result else None
        return result if isinstance(result, dict) else None

    def select(self, table: str, params: dict[str, str]) -> list[dict]:
        result = self._request("GET", f"/rest/v1/{table}", params=params)
        return result if isinstance(result, list) else []


def minimal_child_environment(work_directory: Path) -> dict[str, str]:
    """Environment for the analysis child: no worker or production credentials.

    Only what the interpreter needs to import the engine package and write its
    temporary files. The parent's environment is not inherited.
    """
    return {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "TMPDIR": str(work_directory),
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
    }


def bound_result(result: object) -> dict:
    """Shrink an analysis result to the persisted limit, flagging what was cut."""
    if not isinstance(result, dict) or not isinstance(result.get("summary"), dict):
        raise ValueError("analysis child produced no summary object")
    summary = dict(result["summary"])
    findings = result.get("findings")
    findings = list(findings) if isinstance(findings, list) else []
    kept = findings[:MAX_PERSISTED_FINDINGS]
    summary["findings_persisted"] = len(kept)
    summary["findings_persisted_truncated"] = len(kept) < len(findings)
    bounded = {"summary": summary, "findings": kept}
    if len(json.dumps(bounded).encode("utf-8")) <= MAX_RESULT_BYTES:
        return bounded
    # An unusually large summary still has to fit; drop evidence rows rather
    # than failing the whole attempt, and say so in the summary.
    summary["findings_persisted"] = 0
    summary["findings_persisted_truncated"] = bool(findings)
    bounded = {"summary": summary, "findings": []}
    if len(json.dumps(bounded).encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("analysis summary exceeds the persisted result limit")
    return bounded


def lease_seconds_left(expires_at: str | None) -> float:
    """Seconds until the control plane's own lease expiry, 0.0 when unknown."""
    try:
        moment = datetime.datetime.fromisoformat(str(expires_at or ""))
    except ValueError:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return (moment - datetime.datetime.now(datetime.timezone.utc)).total_seconds()


def _signal_analysis_group(child: subprocess.Popen, number: int) -> None:
    """Signal the whole analysis, which the child leads as its process group.

    The child is started with `start_new_session`, so its PID is its own group
    ID: signalling that group stops an analysis that forked and can never
    reach the worker's own group.
    """
    try:
        os.killpg(child.pid, number)
    except OSError:
        with contextlib.suppress(OSError):
            child.send_signal(number)


def _process_is_gone(pid: int) -> bool:
    """True only when signal 0 proves the process no longer exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False  # It exists but belongs to another account.
    return False


def sweep_stale_work_roots(root: str | os.PathLike[str]) -> int:
    """Remove the snapshot trees of attempts whose worker process is gone.

    A worker that is killed hard cannot run its own cleanup, so its per-run
    directory survives. A tree is removed only when it is a real directory
    directly under this work root, owned by this user, named like a run and
    carrying a marker whose worker PID is positively gone. An unreadable
    marker, a reused PID, a symlink or an unfamiliar name all mean the tree is
    kept: deleting a live attempt's snapshot is worse than leaving a dead
    attempt's behind. Returns how many trees were reclaimed.
    """
    try:
        entries = sorted(Path(root).iterdir())
    except OSError:
        return 0
    reclaimed = 0
    for entry in entries:
        if entry.is_symlink() or not entry.name.startswith(RUN_DIRECTORY_PREFIX):
            continue
        try:
            if not entry.is_dir() or entry.stat().st_uid != os.geteuid():
                continue
            marker = json.loads((entry / RUN_MARKER_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(marker, dict) or not str(marker.get("run_id") or ""):
            continue
        pid = marker.get("worker_pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
            continue
        if not _process_is_gone(pid):
            continue
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            reclaimed += 1
    return reclaimed


@dataclass
class AnalysisRuntimeWorker:
    """Claims and completes one project's repository-analysis work items."""

    client: FactoryRuntimeClient
    project_id: str
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    max_run_seconds: int = DEFAULT_MAX_RUN_SECONDS
    poll_seconds: float = DEFAULT_POLL_SECONDS
    work_root: Path | None = None

    def __post_init__(self) -> None:
        if not MIN_LEASE_SECONDS <= self.lease_seconds <= MAX_LEASE_SECONDS:
            raise ValueError(
                f"lease seconds must be between {MIN_LEASE_SECONDS} and {MAX_LEASE_SECONDS}")
        if self.max_run_seconds < 1:
            raise ValueError("maximum run seconds must be positive")

    # -- registration -----------------------------------------------------
    def verify_registration(self) -> dict:
        """Fail fast with an actionable message when the grant is missing.

        A worker can read its own registration row, so this needs no elevated
        privilege and proves scope before any work is claimed.
        """
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
        return self.client.rpc_row("claim_analysis_work", {
            "p_project_id": self.project_id, "p_lease_seconds": self.lease_seconds,
        })

    def heartbeat(self, claim: dict, *, phase: str | None = None,
                  checkpoint: dict | None = None, source_ref: str | None = None,
                  source_commit: str | None = None,
                  source_digest: str | None = None) -> dict:
        try:
            state = self.client.rpc_row("heartbeat_analysis_run", {
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
            # first, or this attempt already recorded a different ref, commit
            # or digest. Either way the attempt cannot name one snapshot, and
            # the refused call recorded nothing and extended no lease, so it is
            # a source conflict rather than an unknown worker failure.
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

    def run_once(self) -> bool:
        claim = self.claim()
        if claim is None:
            return False
        print(f"claimed run {claim['run_id']} attempt {claim['attempt']}"
              f"/{claim['max_attempts']}", flush=True)
        self._execute(claim)
        return True

    def forever(self, max_runs: int | None = None) -> int:
        """Claim and complete work until stopped, or until it cannot work.

        Supervision absorbs a transient refusal but never spins: a credential
        this identity can no longer refresh, a registration an owner revoked
        and a control plane that keeps refusing all stop the worker instead of
        printing the same traceback forever.
        """
        completed = 0
        failures = 0
        print(f"Oryveta factory worker ready for project {self.project_id}; "
              "press Ctrl+C to stop", flush=True)
        while max_runs is None or completed < max_runs:
            try:
                worked = self.run_once()
            except CredentialError:
                # Already conclusive: no further round trip can change it.
                raise
            except Exception:
                traceback.print_exc()
                # A claim is the only place lost authority surfaces, so the
                # grant is re-checked before polling again; losing it is as
                # terminal as a refused credential.
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
        """Re-check this worker's registration, propagating its loss.

        An unreachable control plane cannot answer the question at all, so that
        is left to the next poll rather than mistaken for a revocation.
        """
        try:
            self.verify_registration()
        except ControlPlaneUnavailable:
            return

    # -- execution --------------------------------------------------------
    def _execute(self, claim: dict) -> None:
        parent = str(self.work_root) if self.work_root else None
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix=RUN_DIRECTORY_PREFIX, dir=parent))
        try:
            self._mark_run_directory(claim, directory)
            self._analyse(claim, directory)
        except Exception as exception:
            code = error_code(exception)
            # The traceback is operator-only; only the short code is persisted.
            traceback.print_exc()
            print(f"run {claim['run_id']} failed: {code}", flush=True)
            self._report_failure(claim, code)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    @staticmethod
    def _mark_run_directory(claim: dict, directory: Path) -> None:
        """Name the attempt that owns this tree, for a later startup sweep.

        The marker carries only what identifies a dead attempt: no lease token,
        no credential, no source payload.
        """
        (directory / RUN_MARKER_NAME).write_text(json.dumps({
            "worker_pid": os.getpid(),
            "run_id": claim["run_id"],
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }), encoding="utf-8")

    def _analyse(self, claim: dict, directory: Path) -> None:
        # The frozen owner/repo were parsed by the migration's SQL mirror of
        # parse_github_url at admission time. Re-parse the frozen URL with the
        # real importer parser before any network access and require all three
        # identities to agree, so a divergence between the two parsers or an
        # edited project cannot redirect this attempt at another repository.
        expected = f"{claim['source_owner']}/{claim['source_repo']}"
        owner, repo = parse_github_url(claim["source_url"])
        if f"{owner}/{repo}" != expected:
            raise InvalidRepository("frozen source URL does not match the recorded repository")
        lease = claim.get("lease_expires_at")
        state = self._heartbeat_inside_lease(claim, lease, phase="fetching_source",
                                             checkpoint={"step": "fetching_source"})
        lease = state.get("lease_expires_at") or lease
        if not self._still_fenced_in(claim, state):
            return
        # The work item pins its source identity from the first attempt that
        # resolves a commit, so every later attempt fetches that exact commit.
        # There is no default-branch fallback: a pin that can be silently
        # ignored is worse than no pin at all.
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
            # The pin is set from this attempt's resolved commit, so a result
            # whose source identity could never be completed is refused.
            raise SourceCommitUnresolved("the fetched archive names no commit")
        # The snapshot identity persisted with the result: these exact bytes.
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        # snapshot_zip creates this directory itself (exist_ok=False) and
        # removes a half-written tree on failure, so it must not exist yet.
        snapshot = directory / "source"
        entries = snapshot_zip(snapshot, payload)
        previous_digest = claim.get("previous_source_digest")
        checkpoint = {
            "step": "snapshot_ready",
            "archive_bytes": len(payload),
            "archive_entries": entries,
            # Honest reclaim semantics: nothing of the previous analysis is
            # reused. The commit is pinned, but GitHub's archive bytes are not
            # reproducible, so the digest is recorded and compared as well.
            "resumed_attempt": claim["attempt"] > 1,
            "source_commit": commit,
            "source_pinned": pinned_commit is not None,
            "source_matches_previous_attempt": (
                None if not previous_digest else previous_digest == digest),
        }
        state = self._heartbeat_inside_lease(
            claim, lease, phase="analyzing", checkpoint=checkpoint,
            source_ref=reference, source_commit=commit, source_digest=digest)
        lease = state.get("lease_expires_at") or lease
        if not self._still_fenced_in(claim, state):
            return
        result = self._analyse_in_child(claim, snapshot, directory, lease)
        if result is None:
            return
        state = self._heartbeat_inside_lease(claim, lease, phase="recording_result",
                                             checkpoint={"step": "recording_result"})
        if not self._still_fenced_in(claim, state):
            return
        outcome = self.client.rpc_row("finish_analysis_run", {
            "p_run_id": claim["run_id"],
            "p_lease_token": claim["lease_token"],
            "p_result": result,
        }) or {}
        if outcome.get("accepted"):
            print(f"run {claim['run_id']} completed: "
                  f"{result['summary'].get('findings_persisted', 0)} findings persisted",
                  flush=True)
        else:
            print(f"run {claim['run_id']} result refused: "
                  f"{outcome.get('reason', 'unknown')}", flush=True)

    def _still_fenced_in(self, claim: dict, state: dict) -> bool:
        if state.get("lease_valid"):
            return True
        print(f"run {claim['run_id']} stopped: {state.get('reason', 'lease_lost')}", flush=True)
        return False

    def child_command(self, snapshot: Path, result_path: Path) -> list[str]:
        """The analysis child's argument vector, as an overridable seam.

        The child carries its own wall-clock bound, a little past the worker's,
        so a worker that is killed hard still leaves a child that stops by
        itself without pre-empting the worker's own timeout.
        """
        bound = int(self.max_run_seconds + CHILD_DEADLINE_GRACE_SECONDS)
        return [sys.executable, "-m", "oryveta_engine.analysis_child",
                str(snapshot), str(result_path), str(bound), str(os.getpid())]

    def _analyse_in_child(self, claim: dict, snapshot: Path, directory: Path,
                          lease_expires_at: str | None = None) -> dict | None:
        """Supervise the analysis child, terminating it when the lease is lost."""
        result_path = directory / "result.json"
        error_path = directory / "child-stderr.log"
        command = self.child_command(snapshot, result_path)
        interval = max(1.0, min(self.lease_seconds / 3.0, MAX_HEARTBEAT_INTERVAL))
        deadline = time.monotonic() + self.max_run_seconds
        started = time.monotonic()
        lease = lease_expires_at or claim.get("lease_expires_at")
        with error_path.open("wb") as errors:
            child = subprocess.Popen(
                command, cwd=str(directory), env=minimal_child_environment(directory),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                # The child leads its own process group, so fencing can stop a
                # forked analysis and never the worker itself.
                start_new_session=True,
            )
            try:
                while True:
                    try:
                        remaining = max(0.0, deadline - time.monotonic())
                        code = child.wait(timeout=min(interval, remaining))
                        if time.monotonic() >= deadline:
                            raise AnalysisTimeout("analysis exceeded the bounded runtime")
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    if time.monotonic() >= deadline:
                        self._terminate(child)
                        raise AnalysisTimeout("analysis exceeded the bounded runtime")
                    state = self._heartbeat_inside_lease(claim, lease, checkpoint={
                        "step": "analyzing",
                        "elapsed_seconds": int(time.monotonic() - started),
                    })
                    lease = state.get("lease_expires_at") or lease
                    if not state.get("lease_valid"):
                        # Cancellation, revocation or a stolen lease: stop the
                        # CPU work, do not attempt to publish anything.
                        self._terminate(child)
                        print(f"run {claim['run_id']} terminated child: "
                              f"{state.get('reason', 'lease_lost')}", flush=True)
                        return None
            finally:
                self._terminate(child)
        if code != 0:
            print(self._child_error(error_path), flush=True)
            raise AnalysisProcessError(f"analysis child exited with status {code}")
        try:
            size = result_path.stat().st_size
        except OSError as exception:
            raise AnalysisProcessError("analysis child wrote no result") from exception
        if size > MAX_CHILD_RESULT_BYTES:
            raise ValueError("analysis child result is implausibly large")
        return bound_result(json.loads(result_path.read_text(encoding="utf-8")))

    @staticmethod
    def _child_error(path: Path) -> str:
        try:
            with path.open("rb") as handle:
                return handle.read(MAX_CHILD_ERROR_BYTES).decode("utf-8", "replace")
        except OSError:
            return "analysis child produced no diagnostics"

    @staticmethod
    def _terminate(child: subprocess.Popen) -> None:
        """Stop the owned process group, even if its original leader exited."""
        _signal_analysis_group(child, signal.SIGTERM)
        try:
            child.wait(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # Leader exit is not proof that its helpers exited. Kill remaining
            # group members without relying on platform-specific signal-0 probes.
            _signal_analysis_group(child, signal.SIGKILL)
            child.wait()

    def _report_failure(self, claim: dict, code: str) -> None:
        try:
            outcome = self.client.rpc_row("fail_analysis_run", {
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
            print(f"run {claim['run_id']} failure report refused: "
                  f"{outcome.get('reason', 'unknown')}", flush=True)
        elif outcome.get("retry_scheduled"):
            print(f"run {claim['run_id']} will be retried", flush=True)
        else:
            print(f"work item {claim['work_item_id']} failed terminally", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m oryveta_engine.factory_runtime",
        description="Oryveta project-scoped durable repository-analysis worker")
    parser.add_argument("--credentials", default=os.environ.get(CREDENTIALS_ENV),
                        help=f"protected worker credential file (or ${CREDENTIALS_ENV})")
    parser.add_argument("--project", default=None,
                        help="project UUID to serve; defaults to the credential file's project_id")
    parser.add_argument("--once", action="store_true",
                        help="claim and complete at most one work item, then exit")
    parser.add_argument("--max-runs", type=int, default=None,
                        help="stop after this many completed claims (continuous mode)")
    parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS,
                        help=f"lease length, {MIN_LEASE_SECONDS}-{MAX_LEASE_SECONDS} seconds")
    parser.add_argument("--max-run-seconds", type=int, default=DEFAULT_MAX_RUN_SECONDS,
                        help="bounded runtime for one analysis child, enforced by "
                             "the worker and by the child itself")
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS,
                        help="idle delay between claim attempts in continuous mode")
    parser.add_argument("--work-root", default=None,
                        help="parent directory for disposable per-run snapshots, "
                             "swept for the trees of dead attempts at startup")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if not arguments.credentials:
        print(f"--credentials or ${CREDENTIALS_ENV} is required", file=sys.stderr)
        return 2
    try:
        credentials = WorkerCredentials.load(arguments.credentials)
    except CredentialError as exception:
        print(str(exception), file=sys.stderr)
        return 2
    project_id = arguments.project or credentials.project_id
    if not project_id:
        print("--project is required when the credential file has no project_id",
              file=sys.stderr)
        return 2
    try:
        with FactoryRuntimeClient(credentials) as client:
            worker = AnalysisRuntimeWorker(
                client=client, project_id=project_id,
                lease_seconds=arguments.lease_seconds,
                max_run_seconds=arguments.max_run_seconds,
                poll_seconds=arguments.poll_seconds,
                work_root=Path(arguments.work_root) if arguments.work_root else None,
            )
            registration = worker.verify_registration()
            print(f"worker registration {registration['label']} is enabled", flush=True)
            if worker.work_root is not None:
                # An attempt whose worker was killed hard could not clean up
                # after itself; reclaim those trees before adding another.
                reclaimed = sweep_stale_work_roots(worker.work_root)
                if reclaimed:
                    print(f"reclaimed stale run directories: {reclaimed}", flush=True)
            if arguments.once:
                print("processed one work item" if worker.run_once() else "no queued work item",
                      flush=True)
                return 0
            worker.forever(max_runs=arguments.max_runs)
        return 0
    except KeyboardInterrupt:
        print("stopped", flush=True)
        return 0
    except (FactoryRuntimeError, ValueError) as exception:
        print(str(exception), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
