"""Container-friendly startup for the existing project-scoped analysis worker.

Only the credential directory is persistent. A bootstrap secret initializes a
missing credential once; it must never replace a rotated or rejected session.
This does not provision identities, grant project access, or execute client code.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import signal
import stat
import sys
import tempfile
from pathlib import Path

from . import factory_runtime
from .factory_runtime import CredentialError, WorkerCredentials

BOOTSTRAP_ENV = "ORYVETA_WORKER_BOOTSTRAP"
DEFAULT_CREDENTIALS = Path("/data/worker/credentials.json")
WORKER_UID = 65532
WORKER_GID = 65532


def prepare_directory(credentials: Path) -> None:
    """Prepare a private directory, dropping root before handling any session."""
    root = os.geteuid() == 0
    if "RAILWAY_ENVIRONMENT_ID" in os.environ:
        if (os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") != "/data"
                or credentials != DEFAULT_CREDENTIALS or not os.path.ismount("/data")):
            raise CredentialError("the Railway worker requires a persistent volume at /data "
                                  "and the default credential path")
    if root and (credentials != DEFAULT_CREDENTIALS or not os.path.ismount("/data")):
        raise CredentialError("root startup is only allowed with a mounted /data volume "
                              "and the default credential path")
    directory = credentials.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fchmod(descriptor, 0o700)
        if root:
            os.fchown(descriptor, WORKER_UID, WORKER_GID)
    finally:
        os.close(descriptor)
    if root:
        os.setgroups([])
        os.setgid(WORKER_GID)
        os.setuid(WORKER_UID)


@contextlib.contextmanager
def session_lock(directory: Path):
    """One service per private directory, including across credential replacement."""
    descriptor = os.open(directory / ".service.lock",
                         os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CredentialError("worker session lock must be a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CredentialError("another worker service holds this credential directory") from None
        yield
    finally:
        os.close(descriptor)


def bootstrap_credentials(path: Path, payload: str | None) -> None:
    """Publish a validated first credential without overwriting existing state."""
    if path.exists() or path.is_symlink():
        WorkerCredentials.load(path)
        return
    if not payload:
        raise CredentialError(f"first startup requires ${BOOTSTRAP_ENV}; "
                              "later starts reuse the persisted credential")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".bootstrap-", delete=False) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        WorkerCredentials.load(temporary)
        # Unlike replace(), link() cannot overwrite a credential created while
        # initializing. Readers see the fully written, validated file or nothing.
        os.link(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _stop(signum, frame) -> None:
    # The existing worker catches KeyboardInterrupt and tears down its analysis
    # process group. Install an explicit handler so container PID 1 handles TERM.
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = factory_runtime.build_parser()
    parser.prog = "python -m oryveta_engine.factory_service"
    parser.description = "Unattended Oryveta analysis worker with persistent session state"
    arguments = parser.parse_args(argv)
    path = Path(arguments.credentials or DEFAULT_CREDENTIALS).absolute()
    payload = os.environ.pop(BOOTSTRAP_ENV, None)
    try:
        prepare_directory(path)
        with session_lock(path.parent):
            bootstrap_credentials(path, payload)
            payload = None
            with contextlib.ExitStack() as resources:
                work_root = arguments.work_root or resources.enter_context(
                    tempfile.TemporaryDirectory(prefix="oryveta-service-"))
                previous = signal.signal(signal.SIGTERM, _stop)
                resources.callback(signal.signal, signal.SIGTERM, previous)
                return factory_runtime.main([
                    *argv, "--credentials", str(path), "--work-root", str(work_root)])
    except KeyboardInterrupt:
        return 0
    except CredentialError as exception:
        print(str(exception), file=sys.stderr)
        return 2
    except OSError as exception:
        print(f"worker service setup failed ({type(exception).__name__}); "
              "check the private credential directory and volume permissions", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
