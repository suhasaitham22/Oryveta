"""Durable single-host worker with fenced leases and bounded retries.

The SQLite lease token is a fencing token: a worker that loses its lease
must never commit results or emit a misleading completion event.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path

from oryveta_api.config import Settings
from oryveta_api.database import Database

from .analysis import analyze_repository
from .benchmarks import run_benchmark

LEASE_SECONDS = 900
MAX_ATTEMPTS = 2


@dataclass
class Worker:
    db: Database
    workspace_root: str = ".oryveta/workspaces"

    def claim(self) -> dict | None:
        now = time.time()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # An expired final attempt must not remain 'running' indefinitely.
            conn.execute(
                """UPDATE jobs SET status='failed',error='WorkerLeaseExpired',
                   lease_until=NULL,lease_token=NULL,updated_at=?
                   WHERE status='running' AND lease_until<? AND attempts>=?""",
                (now, now, MAX_ATTEMPTS),
            )
            row = conn.execute(
                """SELECT * FROM jobs WHERE kind IN ('benchmark','analyze') AND
                   (status='queued' OR (status='running' AND lease_until<?))
                   AND attempts<? ORDER BY created_at ASC LIMIT 1""",
                (now, MAX_ATTEMPTS),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            token = str(uuid.uuid4())
            conn.execute(
                """UPDATE jobs SET status='running',attempts=attempts+1,
                   lease_until=?,lease_token=?,updated_at=? WHERE id=?""",
                (now + LEASE_SECONDS, token, now, row["id"]),
            )
            conn.commit()
            job = dict(row)
            job["lease_token"] = token
            return job

    def renew_lease(self, job: dict) -> bool:
        """Extend only an unexpired lease owned by this exact worker token."""
        now = time.time()
        with self.db.connect() as conn:
            updated = conn.execute(
                """UPDATE jobs SET lease_until=?,updated_at=?
                   WHERE id=? AND status='running' AND lease_token=? AND lease_until>=?""",
                (now + LEASE_SECONDS, now, job["id"], job["lease_token"], now),
            )
        return updated.rowcount == 1

    def _heartbeat(self, job: dict, stopped: threading.Event) -> None:
        # Each heartbeat opens a new connection: SQLite connections are not
        # shared between worker and heartbeat threads.
        while not stopped.wait(max(0.05, LEASE_SECONDS / 3)):
            try:
                if not self.renew_lease(job):
                    return  # Cancellation, expiry or takeover fenced the worker.
            except Exception:
                # A transient DB error must not bypass the fencing check at
                # completion. Avoid logging task contents or credentials.
                print("Oryveta worker heartbeat failed", flush=True)
                return

    def _finish(self, job: dict, result: dict) -> bool:
        """Atomically fence result, analysis and project status behind the lease."""
        now = time.time()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            updated = conn.execute(
                """UPDATE jobs SET status='succeeded',result_json=?,error=NULL,
                   lease_until=NULL,lease_token=NULL,updated_at=?
                   WHERE id=? AND status='running' AND lease_token=? AND lease_until>=?""",
                (json.dumps(result), now, job["id"], job["lease_token"], now),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return False
            if job["kind"] == "analyze":
                conn.execute(
                    """INSERT INTO project_analyses(id,project_id,result_json,created_at)
                       VALUES(?,?,?,?)""",
                    (self.db.new_id(), job["project_id"], json.dumps(result), now),
                )
                conn.execute(
                    "UPDATE projects SET status='analyzed' WHERE id=? AND user_id=?",
                    (job["project_id"], job["user_id"]),
                )
            conn.commit()
        return True

    def _fail(self, job: dict, error_name: str) -> bool:
        now = time.time()
        with self.db.connect() as conn:
            updated = conn.execute(
                """UPDATE jobs SET status='failed',error=?,lease_until=NULL,
                   lease_token=NULL,updated_at=?
                   WHERE id=? AND status='running' AND lease_token=? AND lease_until>=?""",
                (error_name, now, job["id"], job["lease_token"], now),
            )
        return updated.rowcount == 1

    def run_once(self) -> bool:
        job = self.claim()
        if job is None:
            return False
        self.db.add_event(job["user_id"], "job_started", f"Started {job['kind']}", job["id"])
        stopped = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat, args=(job, stopped), daemon=True)
        heartbeat.start()
        try:
            try:
                if job["kind"] == "analyze":
                    root = Path(self.workspace_root) / job["user_id"] / job["project_id"]
                    if not root.is_dir():
                        raise FileNotFoundError("Project workspace missing")
                    result = analyze_repository(root)
                else:
                    result = run_benchmark(job["challenge"], job["seed"])
            finally:
                stopped.set()
                heartbeat.join()
            if self._finish(job, result):
                self.db.add_event(
                    job["user_id"], "job_completed",
                    "Repository analysis completed" if job["kind"] == "analyze"
                    else f"Benchmark completed: {job['challenge']}", job["id"],
                )
        except Exception as exc:
            # Full traceback is operator-only; user-facing errors contain the type.
            print(traceback.format_exc(), flush=True)
            if self._fail(job, type(exc).__name__):
                self.db.add_event(job["user_id"], "job_failed", "Execution failed", job["id"])
        return True

    def forever(self, poll_seconds: float = 2.0) -> None:
        print("Oryveta worker ready; press Ctrl+C to stop", flush=True)
        while True:
            if not self.run_once():
                time.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Oryveta durable analysis and evaluation worker")
    parser.add_argument("--once", action="store_true", help="Complete one queued job and exit")
    args = parser.parse_args()
    settings = Settings.from_environment()
    settings.validate()
    worker = Worker(Database(settings.database_path), settings.workspace_root)
    if args.once:
        print("Processed task" if worker.run_once() else "No queued task")
    else:
        worker.forever()


if __name__ == "__main__":
    main()
