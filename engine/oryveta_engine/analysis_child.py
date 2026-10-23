"""Child-process entry point for the trusted static analyzer.

The durable worker runs this module as a real child process so a cancelled,
revoked or fenced run can be terminated instead of burning CPU on a result that
may no longer be written. The child receives a prepared snapshot directory, an
output path, optional wall-clock bound and original worker PID: no credentials,
no lease token and no network identity. Imported repository source is read, never
executed.

The child does not depend on its parent to stop it. A worker that is killed
hard cannot fence anything, so this process enforces its own deadline and exits
when the process that started it disappears, writing no result. Neither makes
an attempt safe against losing the host: a work item whose worker is gone is
recovered by its lease expiring, not by anything here.
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import sys
import tempfile
import threading
from pathlib import Path

from .analysis import analyze_repository

USAGE = ("usage: python -m oryveta_engine.analysis_child <snapshot-root> "
         "<result-path> [max-seconds [worker-pid]]")

# How often the child checks that the worker which started it is still there.
PARENT_POLL_SECONDS = 0.25
ORPHANED_EXIT = 3
DEADLINE_EXIT = 4


class _Deadline(BaseException):
    """The child's own wall-clock bound expired during the analysis.

    A `BaseException` so no `except Exception` inside the analyzer can absorb
    the bound the worker handed this process.
    """


def _write_atomically(path: Path, payload: str) -> None:
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=".analysis-", delete=False)
    try:
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
    """Interrupt the analysis once its own wall-clock bound expires.

    Zero disables the bound, for a caller that supervises this process some
    other way.
    """
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
    """Exit when the worker process that started this child is gone.

    This process leads its own process group, so a worker that dies hard
    signals nothing: the only sign left is the parent PID changing when the
    kernel reparents an orphan. The analysis is abandoned without writing a
    result, because nobody is left to publish one.
    """
    while not stop.wait(PARENT_POLL_SECONDS):
        if os.getppid() != parent:
            print("the worker process that started this analysis is gone",
                  file=sys.stderr, flush=True)
            # The analysis is running in the main thread, so this is the only
            # way to end it from here.
            os._exit(ORPHANED_EXIT)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else list(argv)
    if not 2 <= len(arguments) <= 4:
        print(USAGE, file=sys.stderr)
        return 2
    root = Path(arguments[0])
    output = Path(arguments[1])
    try:
        max_seconds = float(arguments[2]) if len(arguments) >= 3 else 0.0
        parent = int(arguments[3]) if len(arguments) == 4 else os.getppid()
    except ValueError:
        print(USAGE, file=sys.stderr)
        return 2
    if max_seconds < 0 or parent <= 0:
        print(USAGE, file=sys.stderr)
        return 2
    if not root.is_dir() or root.is_symlink():
        print("snapshot root must be an existing directory", file=sys.stderr)
        return 2
    if not output.parent.is_dir():
        print("result directory does not exist", file=sys.stderr)
        return 2
    # The caller supplies its PID because it may die before this interpreter
    # starts. Sampling getppid() in the watcher would adopt the orphan reaper.
    if os.getppid() != parent:
        return ORPHANED_EXIT
    stop = threading.Event()
    threading.Thread(target=_watch_parent, args=(stop, parent), daemon=True).start()
    try:
        with _bounded(max_seconds):
            result = analyze_repository(root)
    except _Deadline:
        print(f"analysis exceeded its own {max_seconds:g}s bound", file=sys.stderr)
        return DEADLINE_EXIT
    finally:
        stop.set()
    if os.getppid() != parent:
        return ORPHANED_EXIT
    # Separators keep the payload compact: the parent bounds it before it is
    # offered to the metadata authority.
    _write_atomically(output, json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
