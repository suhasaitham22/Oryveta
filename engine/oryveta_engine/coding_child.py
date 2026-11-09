"""Child-process entry point for the real local repair loop.

The durable repair worker runs this module as a separate process so a
cancelled, revoked or fenced attempt can actually be stopped instead of burning
local inference and container time on a result that may no longer be written.

What this process receives is deliberately minimal: a private copy of the
operator's frozen configuration, the pinned source archive, the submitted goal
in a file, its own private evidence and work directories, a deadline, the
worker's PID and the resolved Docker executable. It receives no Supabase
credentials, no lease token, no project or policy identity and none of the
worker's environment, so there is nothing here to leak into a container, a
model prompt or a receipt.

It also does not depend on its parent to stop it. A worker that is killed hard
can fence nothing, so this process enforces its own deadline and watches for
its parent disappearing. Either way the repair task is cancelled rather than
abandoned, which lets the existing loop close its evidence and remove the
container it owns, and nothing is reported once there is no worker left to
publish it. Neither makes an attempt safe against losing the host: a work item
whose worker is gone is recovered by its lease expiring, not by anything here.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sys
import tempfile
import threading
from pathlib import Path

from .coding_config import load_spec
from .coding_contract import CodingError, canonical_json
from .coding_runtime import repair
from .coding_sandbox import DockerRunner

MAX_GOAL_BYTES = 4096

# How often the child checks that the worker which started it is still there.
PARENT_POLL_SECONDS = 0.25
# How long a cancelled repair is given to close its evidence and remove its
# container after the worker disappeared, before this process exits anyway.
ORPHAN_GRACE_SECONDS = 20.0

ORPHANED_EXIT = 3
DEADLINE_EXIT = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m oryveta_engine.coding_child",
        description="Supervised credential-free local repair child; not a CLI for "
                    "operators to run directly")
    parser.add_argument("--config", required=True,
                        help="private copy of the operator's frozen specification")
    parser.add_argument("--source-zip", required=True,
                        help="pinned source archive, never modified")
    parser.add_argument("--goal-file", required=True,
                        help="file holding the bounded submitted repair goal")
    parser.add_argument("--output", required=True,
                        help="new private evidence directory for this run")
    parser.add_argument("--run-root", required=True,
                        help="private work directory shared with the local Docker daemon")
    parser.add_argument("--result", required=True,
                        help="path for this child's bounded outcome report")
    parser.add_argument("--max-seconds", type=float, default=0.0,
                        help="this child's own wall-clock bound; 0 disables it")
    parser.add_argument("--parent-pid", type=int, default=0,
                        help="the worker PID whose disappearance ends this run")
    parser.add_argument("--docker-cli", default="docker",
                        help="trusted docker executable resolved by the worker")
    return parser


def read_goal(path: Path) -> str:
    """Read the bounded submitted goal, which is data and never an instruction."""
    with path.open("rb") as handle:
        payload = handle.read(MAX_GOAL_BYTES + 1)
    if len(payload) > MAX_GOAL_BYTES:
        raise CodingError("invalid_goal", "the repair goal exceeds its bounded size")
    goal = payload.decode("utf-8")
    if not goal.strip():
        raise CodingError("invalid_goal", "a bounded nonempty repair goal is required")
    return goal


def write_atomically(path: Path, payload: str) -> None:
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=".repair-", delete=False)
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


class _Orphaned:
    """Tracks the worker's disappearance from a watcher thread."""

    def __init__(self) -> None:
        self.stop = threading.Event()
        self.lost = False


def _cancelled_receipt() -> dict:
    """The outcome of a run that was stopped before it could be verified."""
    return {"status": "cancelled", "error_code": "cancelled",
            "verification": "not_accepted", "mode": "repair"}


def _watch_parent(state: _Orphaned, parent: int, cancel) -> None:
    """Cancel the repair once the worker process that started it is gone.

    This process leads its own process group, so a worker that dies hard
    signals nothing: the only sign left is the parent PID changing when the
    kernel reparents an orphan. The repair is cancelled rather than killed, so
    the existing loop closes its evidence and removes its container; if that
    does not finish within the grace, this process leaves anyway. Nothing is
    reported either way, because nobody is left to publish it.
    """
    while not state.stop.wait(PARENT_POLL_SECONDS):
        if os.getppid() != parent:
            state.lost = True
            print("the worker process that started this repair is gone",
                  file=sys.stderr, flush=True)
            cancel()
            if not state.stop.wait(ORPHAN_GRACE_SECONDS):
                os._exit(ORPHANED_EXIT)
            return


async def _run(spec, arguments, goal: str, state: _Orphaned) -> tuple[dict, bool]:
    """Run one bounded repair, returning its receipt and whether time ran out.

    SIGTERM and SIGINT cancel the task rather than killing the process, so a
    fenced attempt still closes its evidence and tears down its container. The
    deadline does the same, so even the receipt of a timed-out or fenced run is
    a real, closed record of what happened.
    """
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(repair(
        spec, Path(arguments.source_zip), goal, Path(arguments.output),
        Path(arguments.run_root),
        runner=DockerRunner(spec.runner, docker_cli=arguments.docker_cli)))

    def cancel() -> None:
        # The watcher thread may race a loop that is already shutting down.
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(task.cancel)

    threading.Thread(target=_watch_parent,
                     args=(state, arguments.parent_pid, cancel), daemon=True).start()
    for number in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(number, task.cancel)
    try:
        bound = arguments.max_seconds if arguments.max_seconds > 0 else None
        done, _ = await asyncio.wait({task}, timeout=bound)
        if task not in done:
            task.cancel()
            # `repair` absorbs the cancellation to close its evidence, so the
            # receipt is awaited rather than discarded.
            with contextlib.suppress(asyncio.CancelledError):
                return await task, True
            return _cancelled_receipt(), True
        if task.cancelled():
            # Reached only if the loop ever stops absorbing its cancellation.
            return _cancelled_receipt(), False
        return task.result(), False
    finally:
        state.stop.set()
        for number in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.remove_signal_handler(number)


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    result_path = Path(arguments.result)
    output = Path(arguments.output)
    if arguments.max_seconds < 0 or arguments.parent_pid <= 0:
        print("a positive worker PID and a non-negative bound are required",
              file=sys.stderr)
        return 2
    if not result_path.parent.is_dir() or not Path(arguments.run_root).is_dir():
        print("the result and run-root directories must exist", file=sys.stderr)
        return 2
    if output.exists() or output.is_symlink():
        # The local loop refuses to overwrite evidence; say so before any work.
        print("the evidence directory must not already exist", file=sys.stderr)
        return 2
    # The worker supplies its PID because it may die before this interpreter
    # starts. Sampling getppid() in the watcher would adopt the orphan reaper.
    if os.getppid() != arguments.parent_pid:
        return ORPHANED_EXIT
    state = _Orphaned()
    timed_out = False
    try:
        spec = load_spec(arguments.config)
        goal = read_goal(Path(arguments.goal_file))
        receipt, timed_out = asyncio.run(_run(spec, arguments, goal, state))
    except CodingError as error:
        receipt = {"status": "rejected", "error_code": error.code,
                   "verification": "not_accepted", "mode": "repair"}
    except (OSError, ValueError, UnicodeError):
        receipt = {"status": "failed", "error_code": "local_io_error",
                   "verification": "not_accepted", "mode": "repair"}
    except asyncio.CancelledError:
        # A signal or the parent watcher stopped the run; report it, do not
        # let a bare cancellation escape as an unhandled traceback.
        receipt = _cancelled_receipt()
    finally:
        state.stop.set()
    if state.lost or os.getppid() != arguments.parent_pid:
        # No worker is left to publish anything, so nothing is reported. The
        # work item is recovered by its lease expiring.
        return ORPHANED_EXIT
    write_atomically(result_path, canonical_json({
        "status": receipt.get("status"),
        "error_code": receipt.get("error_code"),
        "verification": receipt.get("verification"),
        "mode": receipt.get("mode"),
        "run_id": receipt.get("run_id"),
    }) + "\n")
    if timed_out:
        return DEADLINE_EXIT
    return 0 if receipt.get("status") == "needs_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
