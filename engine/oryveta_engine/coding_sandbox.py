"""Isolated execution of untrusted repair candidates in local Linux containers.

Nothing here trusts the model. The operator fixes the Docker context, the
immutable image identity and the check command; this module only decides *how*
a fixed command runs, and that policy is not configurable by a caller:

* the validated host snapshot is the only bind mount, read only at ``/input``;
* a trusted wrapper copies the snapshot into a bounded ``tmpfs`` at ``/work``
  and runs the check there, so an execution can never write back to the host;
* that wrapper, not the check, is PID 1, and it supervises the check with an
  in-container watchdog, so losing the host controller cannot leave repository
  code running forever;
* no network, no capabilities, no new privileges, non-root user, read-only root
  filesystem, and explicit pids, memory, swap, cpu and scratch bounds;
* no host environment, no Docker socket, no image pull, no host fallback.

Expected check values stay with the host verifier and never enter a container,
and container output is never interpolated into an exception message.
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .coding_contract import CheckSpec, CodingError, ProcessResult, RunnerSpec, strict_json

INPUT_DIR = "/input"
WORK_DIR = "/work"
TEMP_DIR = "/tmp"
CONTAINER_PREFIX = "oryveta-check-"
# Reserved by the staging wrapper and by the in-container watchdog so that an
# infrastructure failure can never be mistaken for a check verdict. A check may
# not claim any of them as its own exit code.
SETUP_FAILURE_EXIT = 123
WATCHDOG_TIMEOUT_EXIT = 124
WATCHDOG_FAILURE_EXIT = 125
WATCHDOG_KILL_EXIT = 137
RESERVED_EXIT_CODES = frozenset({SETUP_FAILURE_EXIT, WATCHDOG_TIMEOUT_EXIT,
                                 WATCHDOG_FAILURE_EXIT, WATCHDOG_KILL_EXIT})
# Used when the host process runs as root: a container must never run as uid 0.
UNPRIVILEGED_ID = 65532
SHM_MB = 16

CONTROL_TIMEOUT_SECONDS = 20.0
CREATE_TIMEOUT_SECONDS = 30.0
MIN_CONTROL_SECONDS = 2.0
REAP_GRACE_SECONDS = 5.0
MAX_TIMEOUT_SECONDS = 3600.0
# The watchdog escalates from TERM to KILL after this grace. Host supervision
# waits for the whole in-container budget plus a small allowance, so the normal
# outcome of a slow check is a container that stopped itself.
WATCHDOG_KILL_GRACE_SECONDS = 3.0
ATTACH_OVERHEAD_SECONDS = 2.0
MIN_WATCHDOG_SECONDS = 0.1
MAX_CONTROL_OUTPUT_BYTES = 262_144
MAX_STDIN_BYTES = 1_048_576
MAX_ARGV_ITEMS = 64
MAX_ARGV_ITEM_BYTES = 4096
READ_CHUNK_BYTES = 65_536

# A tag or manifest list is mutable; only a resolved local image ID pins the
# exact bytes that will execute. `docker images --no-trunc --quiet` prints it.
IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
CONTEXT_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}\Z")
CONTAINER_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}\Z")
# A comma would split a `--mount` option list and a colon a `--tmpfs` spec, so
# a mount path that contains either is refused rather than quoted.
UNSAFE_MOUNT_CHARS = frozenset(',:"\\')

WRAPPER_ARGV0 = "oryveta-check"
# The image contract requires a POSIX shell, cp and GNU timeout at this path.
WATCHDOG_BINARY = "/usr/bin/timeout"


def wrapper_script(limit: float) -> str:
    """Build the trusted in-container program: stage the snapshot, then guard it.

    The check never becomes PID 1; the watchdog does. GNU ``timeout`` runs the
    check in its own process group and signals that whole group on expiry, and
    because it is PID 1 the kernel tears down anything the check left behind
    when it returns. The container therefore has its own lifetime bound that
    does not depend on the host controller surviving.
    """
    seconds = f"{max(float(limit), MIN_WATCHDOG_SECONDS):.3f}"
    return (
        f"if ! cp -R {INPUT_DIR}/. {WORK_DIR}/; then exit {SETUP_FAILURE_EXIT}; fi\n"
        f"cd {WORK_DIR} || exit {SETUP_FAILURE_EXIT}\n"
        f"if ! [ -x {WATCHDOG_BINARY} ] || ! {WATCHDOG_BINARY} --help >/dev/null 2>&1; then\n"
        f"exit {SETUP_FAILURE_EXIT}\n"
        "fi\n"
        f"exec {WATCHDOG_BINARY} --signal=TERM"
        f" --kill-after={WATCHDOG_KILL_GRACE_SECONDS:g}s {seconds} \"$@\"\n"
    )


class _OutputLimit(Exception):
    """A child produced more bytes than the configured bound allows."""


@dataclass(frozen=True)
class _CliResult:
    code: int
    stdout: bytes
    stderr: bytes


def control_environment() -> dict[str, str]:
    """Build the only environment the Docker CLI is allowed to see.

    Ambient endpoint overrides are dropped. The operator's configuration directory
    is retained to locate the named context; later commands use the resolved Unix
    endpoint, so a context change cannot redirect an active run. Client proxy
    settings are explicitly cleared from container environments.
    """
    environment = {"PATH": os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin",
                   "HOME": os.environ.get("HOME") or "/"}
    config = os.environ.get("DOCKER_CONFIG")
    if config:
        if not os.path.isabs(config) or any(ord(char) < 32 for char in config):
            raise CodingError("runner_context", "Docker configuration directory must be an absolute path")
        environment["DOCKER_CONFIG"] = config
    return environment


def unprivileged_identity() -> tuple[int, int]:
    """Pick the container user: the host identity unless it is privileged."""
    uid = os.getuid()
    gid = os.getgid()
    return (uid or UNPRIVILEGED_ID, gid or UNPRIVILEGED_ID)


def validate_runner_spec(spec: RunnerSpec) -> None:
    """Reject an operator runner configuration that cannot be enforced."""
    if not isinstance(spec, RunnerSpec):
        raise CodingError("runner_spec", "A RunnerSpec is required")
    if not isinstance(spec.image, str) or not IMAGE_ID_PATTERN.fullmatch(spec.image):
        raise CodingError("runner_spec", "Runner image must be a local sha256 image ID")
    if (not isinstance(spec.docker_context, str) or
            not CONTEXT_NAME_PATTERN.fullmatch(spec.docker_context)):
        raise CodingError("runner_spec", "Runner docker_context is not a valid context name")
    if (type(spec.timeout_seconds) is not int or
            not 1 <= spec.timeout_seconds <= MAX_TIMEOUT_SECONDS):
        raise CodingError("runner_spec", "Runner timeout_seconds is out of range")
    if type(spec.memory_mb) is not int or not 64 <= spec.memory_mb <= 65536:
        raise CodingError("runner_spec", "Runner memory_mb is out of range")
    if type(spec.cpus) not in (int, float) or not 0.1 <= spec.cpus <= 64:
        raise CodingError("runner_spec", "Runner cpus is out of range")
    if type(spec.pids) is not int or not 8 <= spec.pids <= 4096:
        raise CodingError("runner_spec", "Runner pids is out of range")
    if type(spec.tmpfs_mb) is not int or not 1 <= spec.tmpfs_mb <= 4096:
        raise CodingError("runner_spec", "Runner tmpfs_mb is out of range")
    if type(spec.output_bytes) is not int or not 1024 <= spec.output_bytes <= 64 * 1024 * 1024:
        raise CodingError("runner_spec", "Runner output_bytes is out of range")
    # Docker tmpfs pages are charged to the container memory cgroup, so scratch
    # larger than the memory bound would advertise space that cannot be used.
    if 2 * spec.tmpfs_mb + SHM_MB > spec.memory_mb:
        raise CodingError("runner_spec", "Runner scratch tmpfs must fit inside memory_mb")


def validate_workspace(workspace: Path | str | os.PathLike[str]) -> str:
    """Return a mountable source path, or refuse to build a mount at all.

    The path must be absolute, already resolved and symlink free: a symlinked
    component would bind host bytes the operator never allowlisted, and mount
    metacharacters would turn a path into extra Docker mount options.
    """
    try:
        text = os.fspath(workspace)
    except TypeError as exc:
        raise CodingError("runner_workspace", "Workspace path is not a path") from exc
    if not isinstance(text, str) or not text:
        raise CodingError("runner_workspace", "Workspace path must be a non-empty string")
    if not text.startswith("/") or text == "/":
        raise CodingError("runner_workspace", "Workspace path must be an absolute subdirectory")
    if text != os.path.normpath(text):
        raise CodingError("runner_workspace", "Workspace path must already be normalized")
    if any(not 0x20 <= ord(char) <= 0x7E for char in text):
        raise CodingError("runner_workspace", "Workspace path must be printable ASCII")
    if UNSAFE_MOUNT_CHARS.intersection(text):
        raise CodingError("runner_workspace", "Workspace path contains mount metacharacters")
    path = Path(text)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise CodingError("runner_workspace", "Workspace path must be free of symlinks")
    if not path.is_dir():
        raise CodingError("runner_workspace", "Workspace path is not an existing directory")
    return text


def validate_check(check: CheckSpec) -> tuple[list[str], bytes]:
    """Return the literal argv and the exact stdin bytes a container may see."""
    if not isinstance(check, CheckSpec):
        raise CodingError("runner_check", "A CheckSpec is required")
    argv = check.argv
    if not isinstance(argv, tuple) or not 1 <= len(argv) <= MAX_ARGV_ITEMS:
        raise CodingError("runner_check", "Check argv must be a tuple of 1 to 64 arguments")
    for item in argv:
        if (not isinstance(item, str) or not item or "\x00" in item or
                len(item.encode("utf-8")) > MAX_ARGV_ITEM_BYTES):
            raise CodingError("runner_check", "Check argv entries must be bounded text")
    if type(check.expected_exit_code) is not int or not 0 <= check.expected_exit_code <= 255:
        raise CodingError("runner_check", "Check expected_exit_code is out of range")
    if check.expected_exit_code in RESERVED_EXIT_CODES:
        raise CodingError("runner_check",
                          "Exit codes 123, 124, 125 and 137 are reserved by the sandbox")
    if not isinstance(check.stdin, str):
        raise CodingError("runner_check", "Check stdin must be text")
    stdin = check.stdin.encode("utf-8")
    if len(stdin) > MAX_STDIN_BYTES:
        raise CodingError("runner_check", "Check stdin exceeds the input limit")
    return list(argv), stdin


async def read_bounded(stream: asyncio.StreamReader, limit: int) -> bytes:
    """Stop at the limit while reading, so a chatty child cannot exhaust memory."""
    data = bytearray()
    while True:
        chunk = await stream.read(READ_CHUNK_BYTES)
        if not chunk:
            return bytes(data)
        if len(data) + len(chunk) > limit:
            raise _OutputLimit()
        data.extend(chunk)


async def write_once(writer: asyncio.StreamWriter, data: bytes) -> None:
    """Deliver exactly the check stdin and then signal end of input."""
    try:
        if data:
            writer.write(data)
            await writer.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


async def discard(tasks: tuple[asyncio.Future, ...]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def drain_discarded(stream: asyncio.StreamReader) -> None:
    """Release a paused pipe after killing its producer without retaining output."""
    while await stream.read(READ_CHUNK_BYTES):
        pass


async def reap(proc: asyncio.subprocess.Process) -> None:
    """Make sure no Docker CLI child keeps running with our pipes."""
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(asyncio.gather(
            proc.wait(), drain_discarded(proc.stdout), drain_discarded(proc.stderr),
        ), REAP_GRACE_SECONDS)
    except (TimeoutError, OSError):
        raise CodingError("runner_cli_cleanup", "The Docker CLI process and pipes could not be reaped") from None


async def shielded(coro) -> Any:
    """Run cleanup to completion even while this task is being cancelled.

    The cancellation request is absorbed here on purpose; the caller re-raises
    it after the container has been removed and the result confirmed.
    """
    task = asyncio.ensure_future(coro)
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    return task.result()


class DockerRunner:
    """Runs one operator-owned check per disposable container, or fails loudly."""

    def __init__(self, spec: RunnerSpec, *, docker_cli: str = "docker"):
        validate_runner_spec(spec)
        if (not isinstance(docker_cli, str) or not docker_cli or
                any(ord(char) < 0x20 for char in docker_cli)):
            raise CodingError("runner_spec", "Docker CLI path is not usable")
        self.spec = spec
        self._binary = docker_cli
        self._identity: dict[str, Any] | None = None
        self._broken: str | None = None
        self._endpoint: str | None = None
        self._uid, self._gid = unprivileged_identity()

    async def preflight(self) -> dict[str, Any]:
        """Observe the endpoint, the daemon and the image before anything runs."""
        self._require_usable()
        context = await self._inspect_context()
        self._endpoint = context["endpoint"]
        observed = {**context, **await self._inspect_daemon(), **await self._inspect_image()}
        self._identity = observed
        return dict(observed)

    async def run(self, workspace: Path, check: CheckSpec, *,
                  timeout_seconds: float | None = None) -> ProcessResult:
        """Execute one check in a fresh container and report what actually happened."""
        self._require_usable()
        limit = self._attempt_limit(timeout_seconds)
        source = validate_workspace(workspace)
        argv, stdin = validate_check(check)
        await self._ensure_verified()
        name = f"{CONTAINER_PREFIX}{secrets.token_hex(8)}"
        if not CONTAINER_NAME_PATTERN.fullmatch(name):  # pragma: no cover - generated name
            raise CodingError("runner_spec", "Generated container name is not valid")
        started = time.monotonic()
        # The container is created before it is started, so a creation timeout
        # cannot leave untrusted code running: nothing has been launched yet.
        try:
            await self._create(name, source, argv, limit,
                               min(CREATE_TIMEOUT_SECONDS, max(MIN_CONTROL_SECONDS, limit)))
            # Host supervision is deliberately looser than the watchdog so the
            # in-container bound is the one that normally ends a slow check.
            stdout, stderr = await self._attach(
                name, stdin, limit + WATCHDOG_KILL_GRACE_SECONDS + ATTACH_OVERHEAD_SECONDS)
            state = await self._state(name)
        except BaseException:
            await shielded(self._remove(name))
            raise
        elapsed = time.monotonic() - started
        await self._remove(name)
        return self._result(name, state, stdout, stderr, elapsed)

    def _require_usable(self) -> None:
        if self._broken:
            raise CodingError("runner_unusable",
                              f"Runner stopped after {self._broken} and cannot be reused")

    def _attempt_limit(self, timeout_seconds: float | None) -> float:
        """The operator timeout is a ceiling that a caller may tighten, never raise.

        A controller that passes what is left of a wall budget therefore cannot
        widen the per-check bound that the configuration fixed.
        """
        ceiling = float(self.spec.timeout_seconds)
        if timeout_seconds is None:
            return ceiling
        if type(timeout_seconds) not in (int, float):
            raise CodingError("runner_spec", "Check timeout must be a number")
        limit = float(timeout_seconds)
        if not 0 < limit <= MAX_TIMEOUT_SECONDS:
            raise CodingError("runner_spec", "Check timeout is out of range")
        return min(limit, ceiling)

    async def _ensure_verified(self) -> None:
        if self._identity is None:
            await self.preflight()

    async def _inspect_context(self) -> dict[str, Any]:
        name = self.spec.docker_context
        result = await self._cli(["context", "inspect", name, "--format", "{{json .}}"],
                                 timeout=CONTROL_TIMEOUT_SECONDS, code="runner_context")
        if result.code != 0:
            raise CodingError("runner_context", f"Docker context {name} is not available")
        payload = self._payload(result.stdout, "runner_context")
        if payload.get("Name") != name:
            raise CodingError("runner_context", f"Docker context {name} did not identify itself")
        endpoints = payload.get("Endpoints")
        endpoints = endpoints.get("docker") if isinstance(endpoints, dict) else None
        host = endpoints.get("Host") if isinstance(endpoints, dict) else None
        # A local unix socket is the only accepted endpoint: a tcp or ssh
        # endpoint would run untrusted code on a machine this host cannot bound.
        if (not isinstance(host, str) or not host.startswith("unix:///") or
                any(not 0x20 <= ord(char) <= 0x7E for char in host)):
            raise CodingError("runner_context",
                              f"Docker context {name} must use a local unix endpoint")
        return {"context": name, "endpoint": host}

    def _connection(self) -> list[str]:
        if self._endpoint is None:
            raise CodingError("runner_context", "The local Docker endpoint is not verified")
        return ["--host", self._endpoint]

    async def _inspect_daemon(self) -> dict[str, Any]:
        result = await self._cli([*self._connection(), "version", "--format", "{{json .Server}}"],
                                 timeout=CONTROL_TIMEOUT_SECONDS)
        if result.code != 0:
            raise CodingError("runner_daemon", "The configured Docker daemon is unreachable")
        payload = self._payload(result.stdout, "runner_daemon")
        family = payload.get("Os")
        if family != "linux":
            raise CodingError("runner_daemon", "Isolation requires a Linux Docker daemon")
        return {"daemon_os": family,
                "daemon_arch": _text(payload.get("Arch")),
                "daemon_version": _text(payload.get("Version"))}

    async def _inspect_image(self) -> dict[str, Any]:
        image = self.spec.image
        # `image inspect` never pulls, and no code path in this module pulls:
        # an image that is not already local is an operator provisioning error.
        result = await self._cli([*self._connection(), "image", "inspect", image, "--format", "{{json .}}"],
                                 timeout=CONTROL_TIMEOUT_SECONDS, code="runner_image")
        if result.code != 0:
            raise CodingError("runner_image", "The configured runner image is not present locally")
        payload = self._payload(result.stdout, "runner_image")
        if payload.get("Id") != image:
            raise CodingError("runner_image", "The local image identity does not match the spec")
        if payload.get("Os") != "linux":
            raise CodingError("runner_image", "The runner image is not a Linux image")
        configuration = payload.get("Config")
        if not isinstance(configuration, dict) or configuration.get("Volumes") not in (None, {}):
            raise CodingError("runner_image", "Images with implicit writable volumes are not supported")
        digests = payload.get("RepoDigests")
        digests = [item for item in digests if isinstance(item, str)][:8] \
            if isinstance(digests, list) else []
        return {"image_id": image, "image_os": "linux",
                "image_arch": _text(payload.get("Architecture")), "image_digests": digests}

    def _payload(self, raw: bytes, code: str) -> dict[str, Any]:
        """Parse daemon JSON strictly, without echoing it into an error."""
        try:
            payload = strict_json(raw.strip() or b"null")
        except (ValueError, UnicodeDecodeError) as exc:
            raise CodingError(code, "The Docker CLI returned unreadable JSON") from exc
        if isinstance(payload, list) and len(payload) == 1:
            payload = payload[0]
        if not isinstance(payload, dict):
            raise CodingError(code, "The Docker CLI returned an unexpected object")
        return payload

    def _create_command(self, name: str, source: str, argv: list[str],
                        limit: float) -> list[str]:
        """The complete container configuration: no caller-supplied Docker flags."""
        uid, gid = self._uid, self._gid
        spec = self.spec
        scratch = (f"rw,nosuid,nodev,exec,size={spec.tmpfs_mb}m,"
                   f"mode=0700,uid={uid},gid={gid}")
        return [
            self._binary, *self._connection(), "container", "create",
            "--name", name,
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", f"{uid}:{gid}",
            "--pids-limit", str(spec.pids),
            "--memory", f"{spec.memory_mb}m",
            # Equal memory and memory-swap disables swap for the container.
            "--memory-swap", f"{spec.memory_mb}m",
            "--cpus", str(float(spec.cpus)),
            "--shm-size", f"{SHM_MB}m",
            # Output is streamed over the attach connection; the daemon must not
            # also persist unbounded container logs on the host.
            "--log-driver", "none",
            "--no-healthcheck",
            "--pull", "never",
            "--workdir", WORK_DIR,
            # Fixed values only. No host variable is forwarded into a container.
            "--env", f"HOME={TEMP_DIR}",
            "--env", f"TMPDIR={TEMP_DIR}",
            # Docker also injects proxy settings from its client config. Explicit
            # empty values prevent those settings (and credentials) entering code.
            *[argument for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "FTP_PROXY",
                                   "http_proxy", "https_proxy", "all_proxy", "no_proxy", "ftp_proxy")
              for argument in ("--env", f"{key}=")],
            "--tmpfs", f"{TEMP_DIR}:{scratch}",
            "--tmpfs", f"{WORK_DIR}:{scratch}",
            # The snapshot is the single host mount and is read only, so an
            # execution can never change what the next attempt will see.
            "--mount", f"type=bind,source={source},target={INPUT_DIR},readonly",
            "--entrypoint", "/bin/sh",
            "-i",
            spec.image, "-c", wrapper_script(limit), WRAPPER_ARGV0, *argv,
        ]

    async def _create(self, name: str, source: str, argv: list[str], limit: float,
                      budget: float) -> None:
        command = self._create_command(name, source, argv, limit)
        result = await self._cli(command[1:], timeout=budget, code="runner_create")
        if result.code != 0:
            raise CodingError("runner_create", f"Docker refused to create container {name}")

    async def _attach(self, name: str, stdin: bytes, budget: float) -> tuple[bytes, bytes]:
        """Start the container with only the check stdin attached."""
        command = [self._binary, *self._connection(),
                   "container", "start", "--attach", "--interactive", name]
        try:
            proc = await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=control_environment())
        except OSError as exc:
            raise CodingError("runner_cli", "The Docker CLI could not be started") from exc
        cap = self.spec.output_bytes
        pumps = (asyncio.ensure_future(write_once(proc.stdin, stdin)),
                 asyncio.ensure_future(read_bounded(proc.stdout, cap)),
                 asyncio.ensure_future(read_bounded(proc.stderr, cap)))
        try:
            await asyncio.wait_for(asyncio.gather(*pumps), timeout=budget)
            await asyncio.wait_for(proc.wait(), REAP_GRACE_SECONDS)
        except TimeoutError:
            await discard(pumps)
            await shielded(reap(proc))
            raise CodingError("runner_timeout",
                              f"Isolated check outlived {budget:g} seconds of supervision"
                              ) from None
        except _OutputLimit:
            await discard(pumps)
            await shielded(reap(proc))
            raise CodingError("runner_output_limit",
                              f"Isolated check exceeded {cap} output bytes") from None
        except OSError as exc:
            await discard(pumps)
            await shielded(reap(proc))
            raise CodingError("runner_cli", "The attached Docker stream failed") from exc
        except asyncio.CancelledError:
            await shielded(discard(pumps))
            await shielded(reap(proc))
            raise
        return pumps[1].result(), pumps[2].result()

    async def _state(self, name: str) -> dict[str, Any]:
        result = await self._cli([*self._connection(), "container", "inspect",
                                  name, "--format", "{{json .State}}"],
                                 timeout=CONTROL_TIMEOUT_SECONDS, code="runner_state")
        if result.code != 0:
            raise CodingError("runner_state", f"Container {name} state is not readable")
        return self._payload(result.stdout, "runner_state")

    def _result(self, name: str, state: dict[str, Any], stdout: bytes, stderr: bytes,
                elapsed: float) -> ProcessResult:
        """Trust the recorded container state, not the exit code of the CLI."""
        if state.get("OOMKilled") is True:
            raise CodingError("runner_oom", f"Container {name} exceeded its memory bound")
        if state.get("Error"):
            raise CodingError("runner_start", f"The daemon reported a failure for {name}")
        code = state.get("ExitCode")
        if (state.get("Status") != "exited" or state.get("Running") is not False or
                state.get("Dead") is True or type(code) is not int):
            raise CodingError("runner_start", f"Container {name} reached no final exited state")
        if code == SETUP_FAILURE_EXIT:
            raise CodingError("runner_setup", f"Container {name} could not stage the snapshot")
        if code == WATCHDOG_FAILURE_EXIT:
            raise CodingError("runner_setup", f"Container {name} could not start its watchdog")
        # Output produced before a watchdog stop is never a result: a program
        # that printed the expected bytes and then hung has not passed.
        if code in (WATCHDOG_TIMEOUT_EXIT, WATCHDOG_KILL_EXIT):
            raise CodingError("runner_timeout",
                              f"Container {name} was stopped by its own watchdog")
        return ProcessResult(code, stdout, stderr, elapsed, name)

    async def _remove(self, name: str) -> None:
        """Remove the named container and confirm it is gone, or stop the runner."""
        for _ in range(2):
            try:
                await self._cli([*self._connection(), "container", "rm", "--force",
                                 "--volumes", name], timeout=CONTROL_TIMEOUT_SECONDS)
                present = await self._cli([*self._connection(), "container", "ls", "--all",
                                          "--filter", f"name={name}", "--format", "{{.ID}}"],
                                         timeout=CONTROL_TIMEOUT_SECONDS)
            except CodingError:
                continue
            if present.code == 0 and not present.stdout.strip():
                return
        self._broken = f"an unconfirmed cleanup of container {name}"
        raise CodingError("runner_cleanup", f"Container {name} removal could not be confirmed")

    async def _cli(self, args: list[str], *, timeout: float,
                   code: str = "runner_daemon") -> _CliResult:
        """Run one Docker CLI command with bounded time, output and environment."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary, *args, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=control_environment())
        except OSError as exc:
            raise CodingError("runner_cli", "The Docker CLI could not be started") from exc
        pumps = (asyncio.ensure_future(read_bounded(proc.stdout, MAX_CONTROL_OUTPUT_BYTES)),
                 asyncio.ensure_future(read_bounded(proc.stderr, MAX_CONTROL_OUTPUT_BYTES)))
        try:
            await asyncio.wait_for(asyncio.gather(*pumps), timeout=timeout)
            exit_code = await asyncio.wait_for(proc.wait(), REAP_GRACE_SECONDS)
        except TimeoutError:
            await discard(pumps)
            await shielded(reap(proc))
            raise CodingError(code, "A Docker CLI command exceeded its time bound") from None
        except _OutputLimit:
            await discard(pumps)
            await shielded(reap(proc))
            raise CodingError(code, "A Docker CLI command exceeded its output bound") from None
        except OSError as exc:
            await discard(pumps)
            await shielded(reap(proc))
            raise CodingError(code, "A Docker CLI command stream failed") from exc
        except asyncio.CancelledError:
            await shielded(discard(pumps))
            await shielded(reap(proc))
            raise
        return _CliResult(exit_code, pumps[0].result(), pumps[1].result())


def _text(value: Any) -> str:
    return value if isinstance(value, str) and len(value) <= 256 else ""
