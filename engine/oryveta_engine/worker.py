"""Durable benchmark worker. Process-independent of browser sessions and API server."""

from __future__ import annotations

import argparse
import json
import time
import traceback
import uuid
from dataclasses import dataclass

from oryveta_api.config import Settings
from oryveta_api.database import Database
from .benchmarks import run_benchmark
from .analysis import analyze_repository
from pathlib import Path

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
            # Expired leases at the retry limit must become terminal, not stay
            # 'running' forever. The update and claim share one transaction.
            conn.execute("""UPDATE jobs SET status='failed',error='WorkerLeaseExpired',
                lease_until=NULL,lease_token=NULL,updated_at=?
                WHERE status='running' AND lease_until<? AND attempts>=?""",
                (now, now, MAX_ATTEMPTS))
            row = conn.execute("""SELECT * FROM jobs WHERE kind IN ('benchmark','analyze') AND
                (status='queued' OR (status='running' AND lease_until<?))
                AND attempts<? ORDER BY created_at ASC LIMIT 1""",
                (now, MAX_ATTEMPTS)).fetchone()
            if not row:
                conn.commit()
                return None
            token = str(uuid.uuid4())
            conn.execute("""UPDATE jobs SET status='running',attempts=attempts+1,
                lease_until=?,lease_token=?,updated_at=? WHERE id=?""",
                (now + LEASE_SECONDS, token, now, row["id"]))
            conn.commit()
            job = dict(row)
            job["lease_token"] = token
            return job

    def run_once(self) -> bool:
        job = self.claim()
        if not job:
            return False
        self.db.add_event(job["user_id"], "job_started", f"Started {job['kind']}", job["id"])
        try:
            if job["kind"] == "analyze":
                root = Path(self.workspace_root) / job["user_id"] / job["project_id"]
                if not root.is_dir():
                    raise FileNotFoundError("Project workspace missing")
                result = analyze_repository(root)
                with self.db.connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    lease = conn.execute("SELECT lease_token FROM jobs WHERE id=? AND status='running'",
                                         (job["id"],)).fetchone()
                    if not lease or lease["lease_token"] != job["lease_token"]:
                        conn.commit()
                        return True  # Another worker has reclaimed this expired lease.
                    conn.execute("INSERT INTO project_analyses(id,project_id,result_json,created_at) VALUES(?,?,?,?)",
                                 (self.db.new_id(), job["project_id"], json.dumps(result), time.time()))
                    conn.execute("UPDATE projects SET status='analyzed' WHERE id=?", (job["project_id"],))
                    conn.commit()
            else:
                result = run_benchmark(job["challenge"], job["seed"])
            with self.db.connect() as conn:
                conn.execute("""UPDATE jobs SET status='succeeded',result_json=?,error=NULL,
                    lease_until=NULL,lease_token=NULL,updated_at=?
                    WHERE id=? AND status='running' AND lease_token=?""",
                    (json.dumps(result), time.time(), job["id"], job["lease_token"]))
            self.db.add_event(job["user_id"], "job_completed",
                              "Repository analysis completed" if job["kind"] == "analyze"
                              else f"Benchmark completed: {job['challenge']}", job["id"])
        except Exception as exc:
            # Sanitize error displayed in the UI. Detailed stack traces belong in operator logs.
            print(traceback.format_exc(), flush=True)
            with self.db.connect() as conn:
                conn.execute("""UPDATE jobs SET status='failed', error=?, lease_until=NULL,
                    lease_token=NULL,updated_at=? WHERE id=? AND lease_token=?""",
                    (type(exc).__name__, time.time(), job["id"], job["lease_token"]))
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
