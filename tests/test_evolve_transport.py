"""Behavioural regressions for the Evolve worker's two transport boundaries.

The reviewed Evolve worker leaves its own process in exactly two places, and
both are where a durable record could quietly become a lie: the private bucket
it uploads artifact bytes to before registering them, and the real child
processes it supervises while it holds a lease. The rest of the workflow is
covered against an in-process control plane with the supervising seam replaced,
which cannot prove that an insert-only bucket is really insert-only, that an
interrupted upload is confirmed before it is reused, that a fenced child really
dies, or that a finished child's output is really refused once the lease is
gone.

These cases therefore drive the real code. `EvolveArtifactStore` runs against
an `httpx.MockTransport` stack that behaves the way Supabase Storage and
`register_evolve_artifact` behave - objects are insert-only, and a registration
is refused until the bytes are in the bucket at the canonical path - so the
publication order is proved by the server's own rules rather than by inspecting
a request header. `EvolveRuntimeWorker._supervise`, `run_once`, `forever` and
the pinned-source binding run against genuine short-lived OS child processes
chosen through the `child_command` seam. No sockets, no Supabase, no GitHub, no
Docker, no model weights and no token spend take part.
"""

from __future__ import annotations

from contextlib import nullcontext
import datetime
import hashlib
import io
import json
import os
import signal
import stat
import sys
import time
import traceback
import zipfile
from pathlib import Path

import httpx
import pytest

from oryveta_engine import evolve_runtime as runtime
from oryveta_engine.coding_contract import CodingError, canonical_json, strict_json
from oryveta_engine.evolve_contract import ARTIFACT_LIMITS
from oryveta_engine.evolve_runtime import (
    EvolveProcessError,
    EvolveRuntimeWorker,
    EvolveTimeout,
)
from oryveta_engine.evolve_storage import BUCKET, EvolveArtifactStore
from oryveta_engine.factory_runtime import (
    ControlPlaneUnavailable,
    CredentialError,
    FactoryRuntimeClient,
    FactoryRuntimeError,
    SourceCommitUnresolved,
    SourceIdentityConflict,
    WorkerCredentials,
)
from oryveta_engine.repositories import InvalidRepository

PROJECT_ID = "3f0a1b2c-4d5e-4f60-8a71-9b0c1d2e3f40"
RUN_ID = "22222222-2222-4222-8222-222222222222"
WORK_ITEM_ID = "11111111-1111-4111-8111-111111111111"
ARTIFACT_ID = "44444444-4444-4444-8444-444444444444"
LEASE_TOKEN = "55555555-5555-4555-8555-555555555555"
WORKER_USER_ID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
SUPABASE_URL = "https://stack.example.test"
PUBLISHABLE_KEY = "sb_publishable_test_only_value"
FIRST_REFRESH_TOKEN = "refresh-token-generation-0"
INITIAL_ACCESS = "access-token-provisioned-value"
ARCHIVE_SHA = "0123456789abcdef0123456789abcdef01234567"

GOAL = "Extend make_str to accept a memoryview while preserving existing behavior."

PATCH_BYTES = b"--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
PATCH_SHA = hashlib.sha256(PATCH_BYTES).hexdigest()
PATCH_PATH = f"{RUN_ID}/patch/{PATCH_SHA}"

# Values an ambient operator environment really holds. A stage child that can
# read any of them has been handed a credential, an endpoint or a session.
SECRET_ENVIRONMENT = {
    "ORYVETA_WORKER_CREDENTIALS": "/parentonlyvalue/worker-credentials.json",
    "SUPABASE_SERVICE_ROLE_KEY": "parentonlyvalue-service-role-key",
    "SUPABASE_URL": SUPABASE_URL,
    "GITHUB_TOKEN": "parentonlyvalue-github-token",
    "OLLAMA_HOST": "http://parentonlyvalue.invalid:11434",
}
# Everything a stage child may see: the minimal interpreter environment plus
# the Docker CLI policy, whose only retained value is a configuration path.
CHILD_ENVIRONMENT_KEYS = {
    "PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING",
    "TMPDIR", "LC_ALL", "LANG", "HOME", "DOCKER_CONFIG",
}
if sys.platform == "darwin":
    # CoreFoundation adds locale metadata after process creation.
    CHILD_ENVIRONMENT_KEYS.add("__CF_USER_TEXT_ENCODING")

CHILD_DIAGNOSTIC = "stage child refused /private/operator/evidence with token sk-not-a-secret\n"


# -- helpers --------------------------------------------------------------

def write_credentials(directory: Path, **overrides) -> Path:
    """Provision a worker credential file the way an operator does."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "worker-credentials.json"
    payload: dict[str, object] = {
        "supabase_url": SUPABASE_URL,
        "publishable_key": PUBLISHABLE_KEY,
        "project_id": PROJECT_ID,
        "refresh_token": FIRST_REFRESH_TOKEN,
        "access_token": INITIAL_ACCESS,
        "expires_at": int(time.time() + 3600),
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    return path


def expiry_in(seconds: float) -> str:
    """A `lease_expires_at` as the control plane renders it, N seconds out."""
    moment = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
    return moment.isoformat()


def live_lease(**overrides) -> dict:
    """A heartbeat state whose lease is valid and nowhere near expiry."""
    state = {
        "lease_valid": True, "reason": None, "run_status": "running",
        "work_item_status": "running", "cancel_requested": False,
        "lease_expires_at": expiry_in(300), "phase": "claimed",
    }
    state.update(overrides)
    return state


def claim_row(**overrides) -> dict:
    """A `claim_evolve_work` row with the columns the SQL function returns."""
    row = {
        "work_item_id": WORK_ITEM_ID, "run_id": RUN_ID, "attempt": 1, "max_attempts": 2,
        "lease_token": LEASE_TOKEN, "lease_expires_at": expiry_in(300), "kind": "evolve",
        "source_url": "https://github.com/owner/repo", "source_owner": "owner",
        "source_repo": "repo", "input_digest": "sha256:" + "0" * 64,
        "pinned_source_ref": None, "pinned_source_commit": None,
        "previous_source_digest": None, "previous_checkpoint": None, "goal": GOAL,
    }
    row.update(overrides)
    return row


def stage_request(stage: str) -> dict:
    """What `_run_stage` hands a child, reduced to what supervision needs."""
    return {"schema_version": 1, "stage": stage, "goal": GOAL, "rework": [],
            "budget": {"tokens": 4000, "role_calls": 4}, "deadline_seconds": 30.0}


def github_archive(files: dict[str, str], *, root: str | None = None,
                   comment: bytes | None = None) -> bytes:
    """An in-memory GitHub-shaped zipball; nothing is fetched.

    A real zipball abbreviates the commit in its single root folder and carries
    the whole commit in the ZIP archive comment, so that is the default shape.
    """
    prefix = f"owner-repo-{ARCHIVE_SHA[:7]}" if root is None else root
    declared = ARCHIVE_SHA.encode() if (root is None and comment is None) else comment
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, body in files.items():
            archive.writestr(f"{prefix}/{name}", body)
        if declared:
            archive.comment = declared
    return stream.getvalue()


def serve_archive(monkeypatch, payload: bytes, *, slug: str = "owner/repo") -> list[tuple]:
    """Answer the importer seam in process, recording what was asked for."""
    calls: list[tuple[str, str | None]] = []

    def fetch(url: str, ref: str | None = None) -> tuple[str, bytes]:
        calls.append((url, ref))
        return slug, payload

    monkeypatch.setattr(runtime, "fetch_public_github_repo", fetch)
    return calls


def recorded_pid(path: Path, limit: float = 5.0) -> int:
    """Read a PID a real child wrote, waiting for the write to land."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            time.sleep(0.02)
    raise AssertionError(f"no process recorded a PID in {path.name}")


def wait_until_gone(pid: int, limit: float = 5.0) -> bool:
    """Poll until a process this test does not own has really gone away."""
    deadline = time.monotonic() + limit
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def kill_recorded(*paths: Path) -> None:
    """Never leave a stray sleeper behind, even when an assertion fails.

    Each recorded process is signalled on its own PID rather than by group:
    a PID that has already been reused must not take a whole group with it.
    """
    for path in paths:
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def one_run_directory(root: Path) -> Path:
    """The single per-attempt private tree this worker created."""
    directories = sorted(path for path in root.iterdir() if path.is_dir())
    assert len(directories) == 1, f"expected one run directory, found {directories}"
    return directories[0]


def failure_code(client: ScriptedClient) -> str:
    return str(client.payloads("fail_evolve_run")[-1]["p_error_code"])


class LoopedTooLong(BaseException):
    """Stops a continuous-mode regression instead of hanging the suite.

    `forever()` absorbs ordinary failures, so a loop that should have stopped
    is broken out of with a `BaseException` it cannot swallow.
    """


# -- the private artifact bucket ------------------------------------------

class FakeArtifactStack:
    """Auth, PostgREST and Storage stand-in that keeps each one's own rules.

    The bucket is insert-only the way Supabase Storage is: a POST to a key that
    already holds bytes is refused with 409 unless the caller asks for an
    upsert, and an upsert is counted, so "insert-only" is proved by what the
    server does rather than by reading the worker's headers.
    `register_evolve_artifact` mirrors its SQL: it refuses a registration whose
    bytes are not already in the bucket at the canonical path, and one whose
    stored size disagrees with the declared size. Refresh tokens rotate and a
    spent one is refused, so a worker that reuses a stale session cannot pass
    by accident.
    """

    def __init__(self, *, upload_status: int | None = None,
                 upload_error: BaseException | None = None,
                 download=None, register=None, revoked: bool = False,
                 refusal_status: int = 401, refuse_refresh: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads: list[tuple[str, str, bytes]] = []
        self.downloads: list[tuple[str, str]] = []
        self.registrations: list[dict] = []
        self.registered: set[str] = set()
        self.unexpected: list[str] = []
        self.overwrites = 0
        self.refresh_calls = 0
        self.generation = 0
        self.refresh_token = FIRST_REFRESH_TOKEN
        self.valid_access = {INITIAL_ACCESS}
        self.upload_status = upload_status
        self.upload_error = upload_error
        self.download = download
        self.register = register
        self.revoked = revoked
        self.refusal_status = refusal_status
        self.refuse_refresh = refuse_refresh

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/auth/v1/token":
            return self._token(request)
        if path == "/rest/v1/rpc/register_evolve_artifact":
            return self._register(request)
        if path.startswith(f"/storage/v1/object/authenticated/{BUCKET}/"):
            return self._download(request)
        if path.startswith(f"/storage/v1/object/{BUCKET}/"):
            return self._upload(request)
        # A reach for a public object URL, another bucket or an unexpected RPC
        # is a finding in itself, not a 404 to shrug at.
        self.unexpected.append(f"{request.method} {path}")
        return httpx.Response(404, json={"message": "no such endpoint"})

    # -- session ----------------------------------------------------------
    def _token(self, request: httpx.Request) -> httpx.Response:
        self.refresh_calls += 1
        if self.refuse_refresh:
            # A real Auth refusal echoes the submitted token. None of this body
            # may reach the worker's message, its output or a persisted row.
            return httpx.Response(400, json={
                "error": "invalid_grant",
                "error_description": f"Refresh Token {self.refresh_token} Not Found"})
        body = json.loads(request.content or b"{}")
        if body.get("refresh_token") != self.refresh_token:
            return httpx.Response(400, json={"error": "invalid_grant"})
        self.generation += 1
        self.refresh_token = f"refresh-token-generation-{self.generation}"
        access = f"access-token-generation-{self.generation}"
        self.valid_access = {access}
        return httpx.Response(200, json={"access_token": access,
                                         "refresh_token": self.refresh_token,
                                         "expires_in": 3600})

    def _accepted(self, request: httpx.Request) -> bool:
        presented = request.headers.get("authorization", "")
        return not self.revoked and presented in {f"Bearer {token}"
                                                  for token in self.valid_access}

    def _echoing(self, status: int, request: httpx.Request, message: str) -> httpx.Response:
        """A refusal whose body reflects the request, as a real one can."""
        return httpx.Response(status, json={
            "message": message,
            "authorization": request.headers.get("authorization", ""),
            "payload": request.content.decode("utf-8", "replace")})

    # -- storage ----------------------------------------------------------
    def _upload(self, request: httpx.Request) -> httpx.Response:
        key = request.url.path.split(f"/storage/v1/object/{BUCKET}/", 1)[1]
        self.uploads.append((key, request.headers.get("authorization", ""), request.content))
        if self.upload_error is not None:
            raise self.upload_error
        if not self._accepted(request):
            return self._echoing(self.refusal_status, request,
                                 "new row violates row-level security policy")
        if self.upload_status is not None:
            return self._echoing(self.upload_status, request, "the object could not be stored")
        if key in self.objects:
            if request.headers.get("x-upsert", "false").lower() == "true":
                self.overwrites += 1
                self.objects[key] = request.content
                return httpx.Response(200, json={"Key": f"{BUCKET}/{key}"})
            return httpx.Response(409, json={"message": "The resource already exists"})
        self.objects[key] = request.content
        return httpx.Response(200, json={"Key": f"{BUCKET}/{key}"})

    def _download(self, request: httpx.Request) -> httpx.Response:
        key = request.url.path.split(f"/storage/v1/object/authenticated/{BUCKET}/", 1)[1]
        self.downloads.append((key, request.headers.get("authorization", "")))
        if self.download is not None:
            return self.download(key)
        if not self._accepted(request):
            return httpx.Response(401, json={"message": "JWT expired"})
        stored = self.objects.get(key)
        if stored is None:
            return httpx.Response(404, json={"message": "Object not found"})
        return httpx.Response(200, content=stored)

    # -- registration -----------------------------------------------------
    def _register(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}")
        self.registrations.append(payload)
        if not self._accepted(request):
            return httpx.Response(401, json={"message": "JWT expired"})
        path = f"{payload.get('p_run_id')}/{payload.get('p_kind')}/{payload.get('p_sha256')}"
        stored = self.objects.get(path)
        if stored is None:
            # The SQL refuses a record whose bytes are not in the bucket, which
            # is what makes "upload, then register" more than a comment.
            return httpx.Response(400, json={
                "message": "the artifact must be uploaded to the private bucket before it is "
                           "registered"})
        if len(stored) != payload.get("p_bytes"):
            return httpx.Response(400, json={
                "message": "the uploaded artifact size does not match the registered size"})
        row = {"id": ARTIFACT_ID, "run_id": payload["p_run_id"], "work_item_id": WORK_ITEM_ID,
               "project_id": PROJECT_ID, "kind": payload["p_kind"],
               "sha256": payload["p_sha256"], "bytes": payload["p_bytes"],
               "storage_path": path, "created_at": "2026-11-12T00:00:00+00:00",
               "replayed": path in self.registered}
        self.registered.add(path)
        if self.register is not None:
            return self.register(row)
        return httpx.Response(200, json=[row])


@pytest.fixture
def stacks(tmp_path):
    """Build a real client and store over one in-process Supabase-shaped stack."""
    opened: list[object] = []

    def build(*, session: bool = True, **options):
        stack = FakeArtifactStack(**options)
        overrides = {} if session else {"access_token": "", "expires_at": 0}
        path = write_credentials(tmp_path / f"secrets-{len(opened)}", **overrides)
        client = FactoryRuntimeClient(WorkerCredentials.load(path), transport=stack.transport())
        store = EvolveArtifactStore(client, transport=stack.transport())
        opened.extend([client, store])
        return stack, store, client

    yield build
    for closeable in opened:
        closeable.close()


def test_bytes_reach_the_private_bucket_before_the_record_that_reveals_them(stacks):
    stack, store, _ = stacks()

    row = store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)

    # The bucket refuses a registration whose bytes are not already stored at
    # the canonical path, so a returned row is itself the proof of ordering.
    assert stack.objects == {PATCH_PATH: PATCH_BYTES}
    assert stack.registrations == [{"p_run_id": RUN_ID, "p_lease_token": LEASE_TOKEN,
                                    "p_kind": "patch", "p_sha256": PATCH_SHA,
                                    "p_bytes": len(PATCH_BYTES)}]
    assert row["storage_path"] == PATCH_PATH == store.storage_path(RUN_ID, "patch", PATCH_SHA)
    assert (row["sha256"], row["bytes"]) == (PATCH_SHA, len(PATCH_BYTES))
    # A fresh upload has nothing to confirm, and nothing but the bucket and its
    # own registration RPC was touched.
    assert stack.downloads == []
    assert stack.unexpected == []


def test_a_mutable_buffer_is_published_as_the_bytes_it_held(stacks):
    stack, store, _ = stacks()
    buffer = bytearray(PATCH_BYTES)

    row = store.publish(RUN_ID, LEASE_TOKEN, "patch", buffer)
    buffer.extend(b" appended after publication")

    # The uploaded bytes are a copy, so a caller that keeps writing into its
    # buffer cannot change what a registered digest refers to.
    assert stack.objects == {PATCH_PATH: PATCH_BYTES}
    assert row["sha256"] == PATCH_SHA


def test_an_interrupted_upload_is_reused_only_after_its_bytes_are_confirmed(stacks):
    stack, store, _ = stacks()
    # What an attempt that died between upload and registration leaves behind.
    stack.objects[PATCH_PATH] = PATCH_BYTES

    row = store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)

    assert row["storage_path"] == PATCH_PATH
    # The existing object was never overwritten, and the worker did not retry
    # the insert as a fresh one: one refused attempt, then confirmation.
    assert len(stack.uploads) == 1
    assert stack.overwrites == 0
    assert stack.objects == {PATCH_PATH: PATCH_BYTES}
    # Confirmation went through this worker's own authenticated session; the
    # bucket has no public URL to read.
    assert [key for key, _ in stack.downloads] == [PATCH_PATH]
    assert stack.downloads[0][1].startswith("Bearer ")
    assert stack.unexpected == []


@pytest.mark.parametrize("answered,message", [
    (b"y" * len(PATCH_BYTES), "does not match its recorded digest"),
    (PATCH_BYTES[:-8], "does not match its recorded digest"),
    (PATCH_BYTES + b" trailing bytes", "exceeds its declared size"),
])
def test_recovered_bytes_that_are_not_the_artifact_are_never_accepted(stacks, answered, message):
    # The registration says the right thing; what this worker reads back does
    # not. The bytes it would publish are the ones it must refuse.
    stack, store, _ = stacks(download=lambda key: httpx.Response(200, content=answered))
    stack.objects[PATCH_PATH] = PATCH_BYTES

    with pytest.raises(FactoryRuntimeError, match=message):
        store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)

    # The caller gets no row at all, so nothing downstream can cite this
    # artifact as evidence.
    assert len(stack.registrations) == 1
    assert [key for key, _ in stack.downloads] == [PATCH_PATH]


def test_a_bucket_that_answers_without_end_is_abandoned_rather_than_drained(stacks):
    chunks = 0

    def endless(key: str) -> httpx.Response:
        def body():
            nonlocal chunks
            while True:
                chunks += 1
                yield b"z" * 65536

        return httpx.Response(200, content=body())

    stack, store, _ = stacks(download=endless)
    stack.objects[PATCH_PATH] = PATCH_BYTES

    with pytest.raises(FactoryRuntimeError, match="exceeds its declared size"):
        store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)

    # The first chunk already exceeds the size the record declares, so the
    # stream is dropped instead of being read into the worker's memory.
    assert chunks <= 2


@pytest.mark.parametrize("status", [403, 404, 500])
def test_an_existing_object_this_worker_cannot_read_is_not_confirmed(stacks, status):
    stack, store, _ = stacks(
        download=lambda key: httpx.Response(status, json={"message": "undisclosed detail"}))
    stack.objects[PATCH_PATH] = PATCH_BYTES

    with pytest.raises(FactoryRuntimeError, match="could not be verified"):
        store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)


def test_a_bucket_that_cannot_be_reached_for_confirmation_is_an_availability_failure(stacks):
    def unreachable(key: str) -> httpx.Response:
        raise httpx.ReadError("the bucket stopped responding")

    stack, store, _ = stacks(download=unreachable)
    stack.objects[PATCH_PATH] = PATCH_BYTES

    # An unreachable bucket is its own honest failure, not a corrupted object.
    with pytest.raises(ControlPlaneUnavailable, match="could not be read"):
        store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)


def test_a_refused_upload_registers_nothing_and_carries_no_echoed_request(stacks):
    stack, store, _ = stacks(upload_status=500)

    with pytest.raises(FactoryRuntimeError) as failure:
        store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)

    assert "HTTP 500" in str(failure.value)
    # Nothing readable exists: an unregistered path is not readable under the
    # bucket's policies, and no record was created either.
    assert stack.registrations == []
    assert stack.objects == {}
    # The refusal body echoed the session and the bytes; neither may travel
    # with the worker's own failure or its traceback.
    report = "".join(traceback.format_exception(failure.value))
    for secret in (INITIAL_ACCESS, PATCH_BYTES.decode("utf-8")):
        assert secret not in str(failure.value)
        assert secret not in report


@pytest.mark.parametrize("failure", [
    httpx.ConnectError("connection refused"),
    httpx.WriteError("the connection broke mid-upload"),
])
def test_an_unreachable_bucket_is_an_availability_failure_and_registers_nothing(stacks, failure):
    stack, store, _ = stacks(upload_error=failure)

    with pytest.raises(ControlPlaneUnavailable, match="could not be reached"):
        store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)

    assert stack.registrations == []
    assert stack.objects == {}


@pytest.mark.parametrize("refusal", [401, 403])
def test_a_revoked_grant_gets_one_fresh_session_and_is_then_refused(stacks, refusal):
    stack, store, _ = stacks(revoked=True, refusal_status=refusal)

    with pytest.raises(FactoryRuntimeError) as failure:
        store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)

    assert f"HTTP {refusal}" in str(failure.value)
    # Exactly one refresh and exactly one retry, and the retry really presented
    # the rotated session rather than repeating the refused one.
    assert stack.refresh_calls == 1
    assert [bearer for _, bearer, _ in stack.uploads] == [
        f"Bearer {INITIAL_ACCESS}", "Bearer access-token-generation-1"]
    # A worker whose grant was revoked registers nothing and stores nothing.
    assert stack.registrations == []
    assert stack.objects == {}
    assert INITIAL_ACCESS not in str(failure.value)


def test_a_worker_whose_session_is_refused_never_sends_the_bytes(stacks):
    stack, store, _ = stacks(session=False, refuse_refresh=True)

    with pytest.raises(CredentialError) as failure:
        store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)

    # It could not prove who it is, so the artifact bytes never left it.
    assert stack.uploads == []
    assert stack.registrations == []
    assert FIRST_REFRESH_TOKEN not in str(failure.value)


@pytest.mark.parametrize("field,value", [
    ("sha256", "e" * 64),
    ("bytes", len(PATCH_BYTES) + 1),
    ("storage_path", f"{RUN_ID}/patch/{'f' * 64}"),
])
def test_a_registration_that_names_other_bytes_is_refused(stacks, field, value):
    stack, store, _ = stacks(
        register=lambda row: httpx.Response(200, json=[{**row, field: value}]))

    with pytest.raises(FactoryRuntimeError,
                       match="does not match the uploaded bytes|names another storage path"):
        store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)

    # The bytes are in the bucket, but the caller receives no row, so nothing
    # downstream can cite an artifact whose record disagrees with its bytes.
    assert stack.objects == {PATCH_PATH: PATCH_BYTES}
    assert stack.downloads == []


@pytest.mark.parametrize("answer", [[], "a row", None])
def test_a_registration_without_a_row_is_not_a_published_artifact(stacks, answer):
    stack, store, _ = stacks(register=lambda row: httpx.Response(200, json=answer))

    with pytest.raises(FactoryRuntimeError, match="returned no row"):
        store.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)

    assert stack.downloads == []


@pytest.mark.parametrize("kind,payload,code", [
    ("summary", PATCH_BYTES, "invalid_artifact"),
    ("", PATCH_BYTES, "invalid_artifact"),
    ("patch", b"", "invalid_artifact"),
    ("patch", "a patch rendered as text", "invalid_artifact"),
    ("patch", b"x" * (ARTIFACT_LIMITS["patch"] + 1), "artifact_limit"),
])
def test_an_artifact_the_contract_refuses_never_reaches_the_bucket(stacks, kind, payload, code):
    stack, store, _ = stacks()

    with pytest.raises(CodingError) as failure:
        store.publish(RUN_ID, LEASE_TOKEN, kind, payload)

    assert failure.value.code == code
    # Refused before anything is spent: no upload, no record, not even a
    # session refresh.
    assert stack.uploads == []
    assert stack.registrations == []
    assert stack.refresh_calls == 0


def test_closing_the_store_leaves_the_worker_its_own_control_plane_session(stacks):
    stack, store, client = stacks()

    with store as opened:
        assert opened.publish(RUN_ID, LEASE_TOKEN, "patch", PATCH_BYTES)["sha256"] == PATCH_SHA

    # The store holds its own upload session. Closing it must not take the
    # worker's control-plane session with it: the attempt continues.
    row = client.rpc_row("register_evolve_artifact", {
        "p_run_id": RUN_ID, "p_lease_token": LEASE_TOKEN, "p_kind": "patch",
        "p_sha256": PATCH_SHA, "p_bytes": len(PATCH_BYTES)})
    assert row["storage_path"] == PATCH_PATH
    assert row["replayed"] is True
    assert stack.unexpected == []


# -- supervised stage children --------------------------------------------

DEFAULT_ROWS: dict[str, object] = {
    "heartbeat_evolve_run": lambda payload, index: live_lease(),
    "claim_evolve_work": None,
    "fail_evolve_run": {"accepted": True, "reason": None, "retry_scheduled": False},
    "record_evolve_failure_report": {"accepted": True, "reason": None},
    "finish_evolve_run": {"accepted": True, "reason": None},
}


class ScriptedClient:
    """Answers the Evolve worker's control-plane calls from a script.

    A list answer is consumed positionally per RPC name and its last element
    repeats, which is how "the lease goes invalid part-way through" is
    expressed without a database.
    """

    def __init__(self, *, answers: dict[str, object] | None = None,
                 rows: dict[str, list[dict]] | None = None,
                 registrations: list[dict] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.selects: list[tuple[str, dict]] = []
        self._answers = dict(answers or {})
        self._rows = dict(rows or {})
        self._registrations = ([{"id": "r-1", "label": "evolve-ci", "enabled": True}]
                               if registrations is None else list(registrations))

    def worker_user_id(self) -> str:
        return WORKER_USER_ID

    def select(self, table: str, params: dict[str, str]) -> list[dict]:
        self.selects.append((table, dict(params)))
        if table == "project_workers":
            return list(self._registrations)
        return list(self._rows.get(table, []))

    def rpc_row(self, name: str, payload: dict) -> dict | None:
        index = self.count(name)
        self.calls.append((name, dict(payload)))
        answer = self._answers.get(name, DEFAULT_ROWS.get(name))
        if callable(answer):
            return answer(payload, index)
        if isinstance(answer, list):
            return answer[min(index, len(answer) - 1)] if answer else None
        return answer

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def payloads(self, name: str) -> list[dict]:
        return [payload for called, payload in self.calls if called == name]

    def count(self, name: str) -> int:
        return len(self.payloads(name))


class RefusingStore:
    """An artifact store that fails the test if anything is published.

    None of these attempts reaches a recordable stage, so a publication here
    would mean bytes were registered for an attempt that produced nothing.
    """

    def __init__(self) -> None:
        self.published: list[tuple[str, int]] = []

    def publish(self, run_id, lease_token, kind, payload):
        self.published.append((kind, len(payload)))
        raise AssertionError(f"nothing in this attempt may publish a {kind} artifact")

    def close(self) -> None:
        return None


# Children are chosen through the `child_command` seam, so each case picks the
# exact process behaviour it needs. `sys.argv[1]` is the request this worker
# wrote and `sys.argv[2]` is where a result would go.
PREAMBLE = (
    "import json, os, signal, subprocess, sys, time\n"
    "with open(sys.argv[1], encoding='utf-8') as handle:\n"
    "    request = json.load(handle)\n"
    "def write(result):\n"
    "    with open(sys.argv[2], 'w', encoding='utf-8') as handle:\n"
    "        json.dump(result, handle)\n"
    "        handle.flush()\n"
    "        os.fsync(handle.fileno())\n"
    "def record(name, value):\n"
    "    path = os.path.join(os.path.dirname(sys.argv[2]), name)\n"
    "    with open(path, 'w', encoding='utf-8') as handle:\n"
    "        handle.write(str(value))\n"
    "        handle.flush()\n"
    "        os.fsync(handle.fileno())\n"
    "def passing(stage):\n"
    "    return {'schema_version': 1, 'stage': stage, 'status': 'ok', 'error_code': None,\n"
    "            'artifact': {}, 'review': None, 'measured': {}, 'produced': {},\n"
    "            'usage': {'tokens': 10, 'role_calls': 1}}\n"
)

# A child that finished its work, left a descendant behind, and is still alive
# when the worker next checks its lease.
FINISHED_CHILD_THAT_LINGERS = PREAMBLE + (
    "grandchild = subprocess.Popen([sys.executable, '-c',\n"
    "    'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(120)'])\n"
    "record('grandchild.pid', grandchild.pid)\n"
    "record('child.pid', os.getpid())\n"
    "write(passing(request['stage']))\n"
    "time.sleep(120)\n"
)
# A child that will not stop when it is asked to.
LINGERING_CHILD = PREAMBLE + (
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "record('child.pid', os.getpid())\n"
    "time.sleep(120)\n"
)
# A child that reports its own view of its process, which is the only
# trustworthy evidence about what it was handed.
REPORTING_CHILD = PREAMBLE + (
    "with open(sys.argv[1], 'rb') as handle:\n"
    "    seen = handle.read().decode('utf-8')\n"
    "write({'schema_version': 1, 'stage': request['stage'], 'status': 'ok',\n"
    "       'error_code': None, 'environment': dict(os.environ), 'cwd': os.getcwd(),\n"
    "       'request_bytes': seen, 'usage': {'tokens': 0, 'role_calls': 0}})\n"
)
FAILING_STAGE_CHILD = PREAMBLE + (
    "write({'schema_version': 1, 'stage': request['stage'], 'status': 'failed',\n"
    "       'error_code': 'model_unavailable', 'artifact': None, 'review': None,\n"
    "       'measured': {}, 'produced': {}, 'usage': {'tokens': 0, 'role_calls': 0}})\n"
)
MISMATCHED_RESULT_CHILD = PREAMBLE + "write(passing('plan'))\n"
OVERSIZED_RESULT_CHILD = PREAMBLE + (
    "result = passing(request['stage'])\n"
    f"result['pad'] = 'x' * {runtime.MAX_CHILD_RESULT_BYTES + 1024}\n"
    "write(result)\n"
)
SILENT_CHILD = "pass\n"


def exiting(code: int, *, message: str = "") -> str:
    """A child that refuses with a chosen exit status, as the real one can."""
    return (PREAMBLE
            + (f"sys.stderr.write({message!r})\nsys.stderr.flush()\n" if message else "")
            + f"raise SystemExit({code})\n")


class ScriptedStageWorker(EvolveRuntimeWorker):
    """Supervises a real child process the test chose.

    `child_command` is an overridable seam precisely so fencing, deadlines and
    result handling can be exercised against a genuine OS process without
    spending a model call or starting a container.
    """

    script = SILENT_CHILD

    def child_command(self, request_path: Path, result_path: Path, seconds: int) -> list[str]:
        return [sys.executable, "-c", self.script, str(request_path), str(result_path),
                str(int(seconds))]


@pytest.fixture
def staged(tmp_path, coding_spec_data):
    """Build a worker whose stage children are short real processes."""
    config = tmp_path / "operator.json"
    config.write_text(json.dumps(coding_spec_data), encoding="utf-8")
    config.chmod(0o600)

    def build(client: ScriptedClient, *, script: str = SILENT_CHILD,
              max_run_seconds: int = 30) -> ScriptedStageWorker:
        worker = ScriptedStageWorker(
            client=client, project_id=PROJECT_ID, config_path=config,
            work_root=tmp_path / "runs", lease_seconds=15, max_run_seconds=max_run_seconds,
            poll_seconds=0.001, max_rework=0, store=RefusingStore())
        worker.script = script
        return worker

    return build


@pytest.fixture
def fast_termination(monkeypatch):
    """Shorten the SIGTERM grace so the escalation path is quick to observe."""
    monkeypatch.setattr(runtime, "TERMINATE_GRACE_SECONDS", 0.2)


@pytest.fixture
def fast_supervision(monkeypatch):
    """Shorten the heartbeat poll so supervised-process cases stay quick.

    The worker keeps its own one-second floor, so a fenced child still costs a
    real heartbeat interval; this only removes the thirty-second ceiling.
    """
    monkeypatch.setattr(runtime, "MAX_HEARTBEAT_INTERVAL", 0.05)


@pytest.fixture
def fast_control_plane_retry(monkeypatch):
    """Keep the bounded heartbeat retry's backoff out of the wall clock."""
    monkeypatch.setattr(runtime, "HEARTBEAT_RETRY_BACKOFF_SECONDS", 0.01)


def round_directory(tmp_path: Path, stage: str = "implementation") -> Path:
    return runtime._private_directory(tmp_path / f"{stage}-0")


def supervise(worker: ScriptedStageWorker, directory: Path, *, stage: str = "implementation",
              seconds: int = 30, lease: str | None = None):
    return worker._supervise(claim_row(), stage, directory, stage_request(stage),
                             lease or expiry_in(300), seconds, phase=stage)


def test_a_lease_lost_while_a_stage_child_runs_discards_the_output_it_finished(
        staged, tmp_path, fast_supervision, fast_termination, capsys):
    client = ScriptedClient(answers={"heartbeat_evolve_run": [
        live_lease(lease_valid=False, reason="cancelled", run_status="cancelled")]})
    worker = staged(client, script=FINISHED_CHILD_THAT_LINGERS)
    directory = round_directory(tmp_path)

    try:
        assert supervise(worker, directory) is None
        # The child had already written a complete result for exactly this
        # stage. The only reason it is not accepted is that this attempt no
        # longer owns the run.
        written = strict_json((directory / "result.json").read_bytes())
        assert (written["stage"], written["status"]) == ("implementation", "ok")
        # Inference and containers stop, not just their output: the whole
        # process group this attempt owned is gone, descendants included.
        child = recorded_pid(directory / "child.pid")
        grandchild = recorded_pid(directory / "grandchild.pid")
        assert wait_until_gone(child)
        assert wait_until_gone(grandchild)
    finally:
        kill_recorded(directory / "child.pid", directory / "grandchild.pid")

    assert "terminated the implementation child: cancelled" in capsys.readouterr().out
    # A fenced attempt reports nothing at all: it may no longer record anything.
    assert client.count("fail_evolve_run") == 0


@pytest.mark.parametrize("reason", ["cancelled", "lease_lost", "worker_not_registered"])
def test_every_fencing_reason_stops_the_child_and_accepts_no_result(
        staged, tmp_path, fast_supervision, fast_termination, reason):
    client = ScriptedClient(answers={"heartbeat_evolve_run": [
        live_lease(lease_valid=False, reason=reason)]})
    worker = staged(client, script=LINGERING_CHILD)
    directory = round_directory(tmp_path)

    try:
        assert supervise(worker, directory) is None
        assert wait_until_gone(recorded_pid(directory / "child.pid"))
    finally:
        kill_recorded(directory / "child.pid")


def test_an_attempt_out_of_time_kills_a_child_that_will_not_stop_when_asked(
        staged, tmp_path, fast_termination):
    worker = staged(ScriptedClient(), script=LINGERING_CHILD)
    directory = round_directory(tmp_path)

    try:
        with pytest.raises(EvolveTimeout, match="bounded runtime"):
            supervise(worker, directory, seconds=1)
        # SIGTERM was ignored, so the bound is enforced by escalation rather
        # than by politely waiting for a child that never intends to exit.
        assert wait_until_gone(recorded_pid(directory / "child.pid"))
    finally:
        kill_recorded(directory / "child.pid")

    assert not (directory / "result.json").exists()


def test_a_stage_child_that_writes_no_result_is_a_process_failure(staged, tmp_path):
    worker = staged(ScriptedClient(), script=SILENT_CHILD)

    with pytest.raises(EvolveProcessError, match="wrote no result") as failure:
        supervise(worker, round_directory(tmp_path))

    assert runtime.evolve_error_code(failure.value) == "evolve_process_failed"


def test_a_failing_child_reports_its_status_and_keeps_its_diagnostics_local(
        staged, tmp_path, capsys):
    worker = staged(ScriptedClient(), script=exiting(7, message=CHILD_DIAGNOSTIC))
    directory = round_directory(tmp_path)

    with pytest.raises(EvolveProcessError, match="exited with status 7") as failure:
        supervise(worker, directory)

    # The child's own words reach the operator's output and its private log,
    # and never the message behind a persisted code.
    assert CHILD_DIAGNOSTIC.strip() in capsys.readouterr().out
    assert CHILD_DIAGNOSTIC.strip() in (directory / "child-stderr.log").read_text(encoding="utf-8")
    assert CHILD_DIAGNOSTIC.strip() not in str(failure.value)
    assert runtime.evolve_error_code(failure.value) == "evolve_process_failed"


@pytest.mark.parametrize("code,expected,message", [
    (runtime.ORPHANED_EXIT, EvolveProcessError, "lost its worker"),
    (runtime.DEADLINE_EXIT, EvolveTimeout, "its own bound"),
])
def test_a_child_that_stopped_itself_is_distinguished_from_any_other_failure(
        staged, tmp_path, code, expected, message):
    # A child that noticed its worker was gone, and one that hit its own bound,
    # are each their own fact rather than an anonymous non-zero exit.
    worker = staged(ScriptedClient(), script=exiting(code))

    with pytest.raises(expected, match=message):
        supervise(worker, round_directory(tmp_path))


def test_an_implausibly_large_stage_result_is_refused(staged, tmp_path):
    worker = staged(ScriptedClient(), script=OVERSIZED_RESULT_CHILD)

    with pytest.raises(EvolveProcessError, match="implausibly large"):
        supervise(worker, round_directory(tmp_path))


def test_a_result_for_another_stage_is_never_accepted_as_this_one(staged, tmp_path):
    # A child cannot have one stage's work recorded as another's, which is what
    # keeps the ordered record meaningful.
    worker = staged(ScriptedClient(), script=MISMATCHED_RESULT_CHILD)

    with pytest.raises(EvolveProcessError, match="does not match its request"):
        supervise(worker, round_directory(tmp_path), stage="implementation")


def test_a_real_stage_child_sees_the_request_and_no_part_of_the_worker_session(
        staged, tmp_path, monkeypatch):
    for name, value in SECRET_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    docker_config = tmp_path / "docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_config))
    worker = staged(ScriptedClient(), script=REPORTING_CHILD)
    directory = round_directory(tmp_path)
    request = stage_request("implementation")

    result = worker._supervise(claim_row(), "implementation", directory, request,
                               expiry_in(300), 30, phase="implementation")

    assert result is not None
    # The child's own view of its process is the evidence, not the parent's
    # dictionary: it inherited nothing and was told only a configuration path.
    environment = result["environment"]
    assert set(environment) <= CHILD_ENVIRONMENT_KEYS
    assert environment["DOCKER_CONFIG"] == str(docker_config)
    rendered = json.dumps(environment)
    for secret in (*SECRET_ENVIRONMENT.values(), LEASE_TOKEN, PUBLISHABLE_KEY,
                   FIRST_REFRESH_TOKEN, INITIAL_ACCESS):
        assert secret not in rendered
    # It was handed exactly the request this worker canonicalised, in a
    # directory of its own.
    assert result["request_bytes"] == canonical_json(request) + "\n"
    assert Path(result["cwd"]).resolve() == directory.resolve()
    assert stat.S_IMODE((directory / "request.json").stat().st_mode) == 0o600


def test_a_control_plane_that_stays_unreachable_stops_the_child_it_cannot_fence(
        staged, tmp_path, fast_supervision, fast_control_plane_retry, fast_termination):
    def unreachable(payload, index):
        raise ControlPlaneUnavailable("the control plane could not be reached for a heartbeat")

    client = ScriptedClient(answers={"heartbeat_evolve_run": unreachable})
    worker = staged(client, script=LINGERING_CHILD)
    directory = round_directory(tmp_path)

    try:
        with pytest.raises(ControlPlaneUnavailable):
            supervise(worker, directory)
        # The retry is bounded, and a child nobody can fence is not left
        # holding inference or a container while the lease runs out.
        assert client.count("heartbeat_evolve_run") == runtime.MAX_HEARTBEAT_RETRIES + 1
        assert wait_until_gone(recorded_pid(directory / "child.pid"))
    finally:
        kill_recorded(directory / "child.pid")


def test_a_heartbeat_is_not_retried_past_the_lease_the_control_plane_granted(
        staged, tmp_path, fast_supervision, fast_control_plane_retry, fast_termination):
    def unreachable(payload, index):
        raise ControlPlaneUnavailable("the control plane could not be reached for a heartbeat")

    client = ScriptedClient(answers={"heartbeat_evolve_run": unreachable})
    worker = staged(client, script=LINGERING_CHILD)
    directory = round_directory(tmp_path)

    try:
        with pytest.raises(ControlPlaneUnavailable):
            supervise(worker, directory, lease=expiry_in(1))
        # With no room left in the granted lease there is nothing to retry
        # into: the attempt is given up at once so the lease can expire.
        assert client.count("heartbeat_evolve_run") == 1
        assert wait_until_gone(recorded_pid(directory / "child.pid"))
    finally:
        kill_recorded(directory / "child.pid")


# -- claiming and the pinned source ---------------------------------------

def test_the_pinned_binding_refuses_a_diverged_frozen_url_before_any_network_access(
        staged, monkeypatch):
    # The SQL mirror of parse_github_url froze owner/repo at admission, so a
    # frozen URL that now parses to something else must not be fetched at all.
    calls = serve_archive(monkeypatch, github_archive({"main.py": "value = 1\n"}))
    worker = staged(ScriptedClient())

    with pytest.raises(InvalidRepository, match="frozen source URL"):
        worker._pinned_source(claim_row(source_url="https://github.com/other/repo"))

    assert calls == []


def test_a_fetch_that_answers_with_another_repository_is_refused(staged, monkeypatch):
    # A redirect, a cache or an edited project must not be reasoned about under
    # the frozen work item's identity.
    serve_archive(monkeypatch, github_archive({"main.py": "value = 1\n"}), slug="other/repo")
    worker = staged(ScriptedClient())

    with pytest.raises(InvalidRepository, match="not the accepted work item's source"):
        worker._pinned_source(claim_row())


def test_the_pinned_binding_returns_the_identity_of_the_bytes_it_fetched(staged, monkeypatch):
    payload = github_archive({"main.py": "value = 1\n"})
    serve_archive(monkeypatch, payload)
    worker = staged(ScriptedClient())

    reference, fetched, commit, digest = worker._pinned_source(claim_row())

    assert (reference, commit) == ("github.com/owner/repo", ARCHIVE_SHA)
    assert fetched == payload
    assert digest == hashlib.sha256(payload).hexdigest()
    # The same work item once an earlier attempt pinned a commit this archive
    # is not: a pin that can be silently ignored is worse than no pin.
    with pytest.raises(SourceIdentityConflict, match="not the pinned commit"):
        worker._pinned_source(claim_row(pinned_source_commit="c" * 40))
    # An archive that names no commit leaves nothing a later attempt could pin
    # or compare against.
    serve_archive(monkeypatch, github_archive({"main.py": "value = 1\n"},
                                              root="owner-repo-main", comment=b""))
    with pytest.raises(SourceCommitUnresolved, match="names no commit"):
        worker._pinned_source(claim_row())


def test_an_empty_queue_leaves_no_run_directory_and_makes_no_further_call(staged):
    client = ScriptedClient(answers={"claim_evolve_work": None})
    worker = staged(client)

    assert worker.run_once() is False

    assert client.names() == ["claim_evolve_work"]
    assert not worker.work_root.exists()


def test_a_frozen_url_that_no_longer_names_the_recorded_repository_is_never_fetched(
        staged, monkeypatch):
    # The SQL mirror of parse_github_url froze owner/repo at admission, so a
    # frozen URL that now parses to something else must not reach the network.
    calls = serve_archive(monkeypatch, github_archive({"main.py": "value = 1\n"}))
    client = ScriptedClient(answers={
        "claim_evolve_work": claim_row(source_url="https://github.com/other/repo")})
    worker = staged(client)

    assert worker.run_once() is True

    assert calls == []
    assert failure_code(client) == "invalid_repository"
    assert client.count("record_evolve_stage") == 0
    # The diagnostic record says plainly that no snapshot was reached, rather
    # than naming one this attempt never had.
    report = client.payloads("record_evolve_failure_report")[-1]["p_report"]
    assert report["failed_stage"] == "fetching_source"
    assert report["source_sha256"] is None
    assert (report["learning_status"], report["learning_reason"]) == ("unavailable", "no_source")
    assert report["lessons"] == []


def test_an_archive_that_is_not_the_pinned_commit_refuses_the_attempt(staged, monkeypatch):
    pinned = "c" * 40
    calls = serve_archive(monkeypatch, github_archive({"main.py": "value = 1\n"}))
    client = ScriptedClient(answers={
        "claim_evolve_work": claim_row(pinned_source_commit=pinned)})
    worker = staged(client)

    assert worker.run_once() is True

    # The pin was asked for, and the archive that came back is not it, so no
    # stage runs against a snapshot this work item is not bound to.
    assert calls == [("https://github.com/owner/repo", pinned)]
    assert failure_code(client) == "source_identity_conflict"
    assert client.count("record_evolve_stage") == 0
    assert never_reached_a_stage(client)


def test_a_pinned_reference_that_is_not_the_fetched_source_refuses_the_attempt(
        staged, monkeypatch):
    serve_archive(monkeypatch, github_archive({"main.py": "value = 1\n"}))
    client = ScriptedClient(answers={
        "claim_evolve_work": claim_row(pinned_source_ref="github.com/other/repo")})
    worker = staged(client)

    assert worker.run_once() is True

    assert failure_code(client) == "source_identity_conflict"
    assert never_reached_a_stage(client)


def test_an_archive_that_names_no_commit_cannot_be_pinned(staged, monkeypatch):
    # The work item's pin is set from the first attempt's resolved commit, so an
    # archive with no identity cannot be allowed to produce a candidate whose
    # source can never be named.
    serve_archive(monkeypatch, github_archive({"main.py": "value = 1\n"},
                                              root="owner-repo-main", comment=b""))
    client = ScriptedClient(answers={"claim_evolve_work": claim_row()})
    worker = staged(client)

    assert worker.run_once() is True

    assert failure_code(client) == "source_commit_unresolved"
    assert never_reached_a_stage(client)


def test_a_claimed_work_item_without_a_goal_runs_nothing(staged, monkeypatch):
    serve_archive(monkeypatch, github_archive({"main.py": "value = 1\n"}))
    client = ScriptedClient(answers={"claim_evolve_work": claim_row(goal="")})
    worker = staged(client, script=FAILING_STAGE_CHILD)

    assert worker.run_once() is True

    assert failure_code(client) == "invalid_goal"
    assert never_reached_a_stage(client)


def never_reached_a_stage(client: ScriptedClient) -> bool:
    """Whether the control plane was never told this attempt began a stage."""
    phases = {payload["p_phase"] for payload in client.payloads("heartbeat_evolve_run")}
    return not phases - {None, "claimed", "fetching_source"}


def test_the_recorded_snapshot_identity_comes_from_the_bytes_that_were_fetched(
        staged, monkeypatch, capsys):
    payload = github_archive({"main.py": "value = 1\n", "README.md": "# demo\n"})
    calls = serve_archive(monkeypatch, payload)
    client = ScriptedClient(answers={"claim_evolve_work": claim_row()})
    worker = staged(client, script=FAILING_STAGE_CHILD)

    assert worker.run_once() is True

    assert calls == [("https://github.com/owner/repo", None)]
    # The identity the run is pinned to is derived here, from the archive this
    # worker holds, and not from anything the claim or a child reported.
    pinning = [call for call in client.payloads("heartbeat_evolve_run") if call["p_source_digest"]]
    assert len(pinning) == 1
    assert pinning[0]["p_source_ref"] == "github.com/owner/repo"
    assert pinning[0]["p_source_commit"] == ARCHIVE_SHA
    assert pinning[0]["p_source_digest"] == "sha256:" + hashlib.sha256(payload).hexdigest()

    # One real child ran, refused the attempt with its own durable code, and
    # nothing was recorded as a stage or published as an artifact.
    run = one_run_directory(worker.work_root)
    assert len(list(run.rglob("child-stderr.log"))) == 1
    assert client.count("record_evolve_stage") == 0
    assert worker.store.published == []
    assert failure_code(client) == "model_unavailable"
    assert "failed: model_unavailable" in capsys.readouterr().out

    # The private evidence is kept for the operator, readable by nobody else;
    # only the sandbox scratch a child could have written into is removed.
    source = run / "evidence" / "source.zip"
    assert source.read_bytes() == payload
    assert stat.S_IMODE(source.stat().st_mode) == 0o600
    assert stat.S_IMODE((run / "evidence").stat().st_mode) == 0o700
    assert not (run / "sandbox").exists()

    # The tree names the attempt that owns it, so a dead attempt is reclaimable
    # and never resumable.
    marker = json.loads((run / runtime.RUN_MARKER_NAME).read_text(encoding="utf-8"))
    assert (marker["run_id"], marker["attempt"]) == (RUN_ID, 1)
    assert marker["worker_pid"] == os.getpid()
    assert marker["resumable"] is False

    report = client.payloads("record_evolve_failure_report")[-1]["p_report"]
    assert report["error_code"] == "model_unavailable"
    assert report["failed_stage"] == "requirements"
    assert report["source_sha256"] == hashlib.sha256(payload).hexdigest()
    # A model that could not be reached cannot be asked to explain itself, so
    # the report says so instead of spending a second child on it.
    assert (report["learning_status"], report["learning_reason"]) == ("unavailable",
                                                                      "model_unavailable")


def test_a_fenced_attempt_fetches_nothing_and_reports_nothing(staged, monkeypatch):
    # Cancellation between the claim and the first fence: the work item is
    # reclaimable through its lease, and this attempt leaves no record at all.
    calls = serve_archive(monkeypatch, github_archive({"main.py": "value = 1\n"}))
    client = ScriptedClient(answers={
        "claim_evolve_work": claim_row(),
        "heartbeat_evolve_run": [live_lease(lease_valid=False, reason="cancelled")]})
    worker = staged(client)

    assert worker.run_once() is True

    assert calls == []
    assert client.count("fail_evolve_run") == 0
    assert client.count("record_evolve_failure_report") == 0
    assert client.count("finish_evolve_run") == 0


# -- continuous mode -------------------------------------------------------

def unparseable_claim(**overrides) -> dict:
    """A claim that fails inside the attempt, before any network access."""
    return claim_row(source_url="https://gitlab.com/owner/repo", **overrides)


def test_continuous_mode_stops_once_this_worker_has_no_enabled_registration(staged):
    def refusing(payload, index):
        if index >= 3:
            raise LoopedTooLong("forever() kept claiming after the registration was gone")
        raise FactoryRuntimeError("POST /rest/v1/rpc/claim_evolve_work failed with HTTP 403")

    client = ScriptedClient(answers={"claim_evolve_work": refusing}, registrations=[])
    worker = staged(client)

    with pytest.raises(FactoryRuntimeError, match="register_project_worker"):
        worker.forever()

    # A worker that is no longer designated stops instead of spinning against a
    # control plane that will never hand it work.
    assert client.count("claim_evolve_work") == 1
    assert [table for table, _ in client.selects] == ["project_workers"]


def test_a_refused_worker_credential_stops_the_loop_without_another_round_trip(staged):
    def refused(payload, index):
        raise CredentialError("worker session refresh was refused (HTTP 400)")

    client = ScriptedClient(answers={"claim_evolve_work": refused})
    worker = staged(client)

    with pytest.raises(CredentialError):
        worker.forever()

    assert client.count("claim_evolve_work") == 1
    assert client.selects == []


def test_continuous_mode_absorbs_one_refusal_while_the_registration_still_holds(staged):
    def claim(payload, index):
        if index == 0:
            raise FactoryRuntimeError("POST /rest/v1/rpc/claim_evolve_work failed with HTTP 503")
        return unparseable_claim()

    client = ScriptedClient(answers={"claim_evolve_work": claim})
    worker = staged(client)

    assert worker.forever(max_runs=1) == 1

    assert client.count("claim_evolve_work") == 2
    # The absorbed refusal was weighed against the registration exactly once.
    assert len(client.selects) == 1


def test_continuous_mode_gives_up_after_five_consecutive_refusals(staged, capsys):
    def refusing(payload, index):
        if index >= runtime.MAX_CONSECUTIVE_CLAIM_FAILURES + 1:
            raise LoopedTooLong("forever() never stopped after repeated refusals")
        raise FactoryRuntimeError("POST /rest/v1/rpc/claim_evolve_work failed with HTTP 503")

    client = ScriptedClient(answers={"claim_evolve_work": refusing})
    worker = staged(client)

    try:
        worker.forever()
    except FactoryRuntimeError:
        # Giving up may surface the last refusal; stopping is what matters.
        pass

    assert client.count("claim_evolve_work") == runtime.MAX_CONSECUTIVE_CLAIM_FAILURES
    assert "stopping after" in capsys.readouterr().out


def test_an_idle_queue_waits_the_configured_poll_and_is_not_counted_as_a_run(
        staged, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(runtime.time, "sleep", lambda seconds: slept.append(seconds))
    client = ScriptedClient(answers={
        "claim_evolve_work": [unparseable_claim(), None, unparseable_claim()]})
    worker = staged(client)

    assert worker.forever(max_runs=2) == 2

    assert client.count("claim_evolve_work") == 3
    assert slept == [worker.poll_seconds]


def test_one_requested_run_completes_without_an_idle_delay(staged, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(runtime.time, "sleep", lambda seconds: slept.append(seconds))
    client = ScriptedClient(answers={"claim_evolve_work": unparseable_claim()})
    worker = staged(client)

    assert worker.forever(max_runs=1) == 1

    assert client.count("claim_evolve_work") == 1
    assert slept == []


def test_worker_restart_retains_the_private_evidence_of_earlier_processes(
        tmp_path, coding_spec_data, monkeypatch):
    config = tmp_path / "operator.json"
    config.write_text(json.dumps(coding_spec_data))
    config.chmod(0o600)
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({
        "supabase_url": "http://127.0.0.1:54321",
        "publishable_key": "local-fixture-publishable",
        "refresh_token": "local-fixture-refresh",
        "project_id": PROJECT_ID,
    }))
    credentials.chmod(0o600)
    root = tmp_path / "runs"
    previous = root / "oryveta-run-previous"
    evidence = previous / "evidence"
    evidence.mkdir(parents=True)
    (previous / ".oryveta-run.json").write_text(json.dumps({
        "worker_pid": 1073741824, "run_id": RUN_ID, "attempt": 1,
    }))
    receipt = evidence / "receipt.json"
    original = b'{"status":"rejected","error_code":"verification_failed"}'
    receipt.write_bytes(original)
    idle = ScriptedClient(answers={"claim_evolve_work": None})
    monkeypatch.setattr(runtime, "FactoryRuntimeClient", lambda _: nullcontext(idle))
    assert runtime.main(["--config", str(config), "--credentials", str(credentials),
                         "--work-root", str(root), "--once"]) == 0
    assert receipt.read_bytes() == original
