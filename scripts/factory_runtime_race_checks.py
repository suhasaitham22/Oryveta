"""Prove the stage-2 durable runtime's concurrency contract with real concurrent sessions.

What is real: four independent PostgreSQL backends against the local Supabase
stack, driven as separate `psql` processes so their transactions genuinely
interleave. Every transition is performed by the committed RPCs through
`set local role authenticated` plus a real `request.jwt.claim.sub`, so real
grants, real policies and real `auth.uid()` apply. Lock waits are observed from
the database itself with `pg_blocking_pids`, so "this session is blocked" is a
fact read out of the server, not a guess about timing.

What is deliberately refused: non-loopback database endpoints, a Python
PostgreSQL driver (the project has none, so concurrency is driven with `psql`
subprocesses), any production mutation, any stubbed function, any worker
process and any GitHub fetch. Nothing here runs the engine: the three findings
below are metadata-authority races, so the analyzer, the archive importer and
the worker CLI are out of scope and stay untouched.

Why this script exists: single-connection psql cannot interleave transactions,
so `supabase/tests/factory_runtime_rls.sql` structurally cannot reach DR-002,
DR-003 or DR-005. This harness supplies exactly that missing coverage.

Cases, each with its interleaving written out at the call site:
  * completion_versus_cancellation      DR-002  finish  vs cancel_work_item
  * failure_versus_cancellation         DR-002  fail    vs cancel_work_item
  * completion_versus_reclaim           DR-002  finish  vs claim's reclaim path
  * completion_versus_revocation        DR-002  finish  vs revoke_project_worker
  * claim_versus_revocation             DR-003  claim   vs revoke_project_worker
  * fenced_lease_after_reregistration   DR-003  a missed lease must stay dead
  * concurrent_source_pinning           DR-004  two attempts at one pin
  * concurrent_idempotent_submission    DR-005  identical simultaneous submits
  * conflicting_idempotent_submission   DR-005  one key, two different inputs

Against the pre-fix migration these cases fail, and that failure is the point:
DR-002 aborts a session with SQLSTATE 40P01 (deadlock detected) because
finish/fail lock the run before the work item while cancel, revoke and reclaim
lock them the other way round; DR-003 lets `revoke_project_worker` commit
without ever seeing the run a concurrent claim is about to commit, leaving a
running attempt with a live lease that revocation did not fence; DR-004 lets the
second of two simultaneous source resolutions overwrite what the first one
recorded, so one work item ends up analysed against two different commits;
DR-005 raises SQLSTATE 23505 (unique_violation) instead of replaying the first
submission.
Every failure message names the finding and prints the SQLSTATE it observed.

Race windows are pinned open with real row locks and bounded waits instead of
sleeps, and a window that cannot be reached fails with "the race window was not
reproduced" rather than passing silently. Two facts cannot be produced from
inside this harness and are staged explicitly, exactly as
supabase/tests/factory_runtime_rls.sql stages them: a lease is aged by moving
public.factory_runs.lease_expires_at into the past (standing in for elapsed
wall-clock time), and a worker service identity is designated by writing
auth.users.raw_app_meta_data as the Auth admin API would. Every fixture this
script creates is deleted again before it returns.

Pass connection JSON on stdin, or name a file with --connections. Either shape
the Supabase CLI emits is accepted: `supabase status --output-format json`
prints a flat map of connection values, `supabase start --output-format json`
nests the same values under "env", and only DB_URL is read. Requires `psql` on
PATH (or SUPABASE_HOME pointing at the test stack). It assumes psql flushes its
output stream at each `\\echo`, which is how the session replies are delimited;
a stack where that does not hold fails loudly during session setup instead of
hanging.

Usage:
    supabase status --output-format json | python scripts/factory_runtime_race_checks.py
"""
from __future__ import annotations

import argparse
import collections
import contextlib
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]

# Explicit order, never a glob: durable_factory_runtime.sql builds on the
# project membership helpers, and an alphabetical sweep would load it first.
SQL_FILES = (
    "supabase/schema.sql",
    "supabase/migrations/private_chats_and_explicit_sharing.sql",
    "supabase/migrations/projects_and_project_membership.sql",
    "supabase/migrations/durable_factory_runtime.sql",
)

INSTANCE = "00000000-0000-0000-0000-000000000000"
WORKER_METADATA = '{"oryveta_role":"factory_worker"}'

# Never fetched: this harness performs no HTTP at all. The URLs only have to be
# admissible to private.github_repo_parts and to differ from one another.
SOURCE_URL = "https://github.com/octocat/Hello-World"
SOURCE_URL_ALTERNATE = "https://github.com/octocat/Spoon-Knife"
SOURCE_REF = "github.com/octocat/Hello-World"
SOURCE_COMMIT = "5a" * 20
SOURCE_DIGEST = "sha256:" + "7b" * 32
# A second resolution of the same repository, for the case where two sessions
# try to pin one work item at the same time.
SOURCE_COMMIT_ALTERNATE = "6c" * 20
SOURCE_DIGEST_ALTERNATE = "sha256:" + "8d" * 32
RESULT = '{"summary":{"source_files_analyzed":7},"findings":[]}'

PROJECT_BRIEF = "Durable runtime concurrency regressions"
# The post-fix completion path requires the whole source identity, so each
# claimed attempt records ref, commit and digest before it races.
IDENTITY_ARGS = (f"p_source_ref => '{SOURCE_REF}', p_source_commit => '{SOURCE_COMMIT}', "
                 f"p_source_digest => '{SOURCE_DIGEST}'")

# Long enough that no case can be disturbed by a lease ageing out underneath it;
# the one case that needs an expired lease ages it on purpose.
LEASE_SECONDS = 900
AGED_LEASE = "now() - interval '2 minutes'"

SQLSTATE_DEADLOCK = "40P01"
SQLSTATE_UNIQUE_VIOLATION = "23505"

# Longer than PostgreSQL's 1s default deadlock_timeout, so a real deadlock
# surfaces as an error reply instead of being misreported as a lock wait.
WINDOW_SECONDS = 6.0
MARKER_TIMEOUT = 120.0
SETUP_TIMEOUT = 20.0
POLL_SECONDS = 0.05

ROW = "ROW~"
MARK = "MARK~"
SQLSTATE_LINE = re.compile(r"ERROR:\s+([0-9A-Z]{5}):\s*(.*)$")


def loopback(url: str) -> str:
    if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Factory runtime race checks only accept isolated loopback services")
    return url.rstrip("/")


def tagged(*expressions: str) -> str:
    """A select list that emits one unambiguously parseable line per result row.

    psql's own output lines, command tags and error reports are all untagged, so
    tagging the values this harness actually reads keeps parsing exact instead of
    guessing which line of a merged stdout/stderr stream was data.
    """
    values = ", ".join(f"coalesce(({expression})::text, '<null>')" for expression in expressions)
    return f"'{ROW}' || concat_ws('~', {values})"


def actor(user_id: str) -> str:
    """Become a real authenticated caller for the rest of this transaction."""
    return ("set local role authenticated;\n"
            f"select set_config('request.jwt.claim.sub', '{user_id}', true);")


SESSION_SETUP = "\n".join((
    # A backstop, not a race mechanism: every intended wait in this harness is
    # released explicitly, so a statement still running after a minute is a bug
    # and must surface as an error reply rather than wedging the harness.
    "set statement_timeout = '60s';",
    # 0, deliberately: lock waits are the thing under test and must resolve
    # naturally rather than being cut short by a timeout.
    "set lock_timeout = 0;",
    # The harness holds transactions open on purpose while it pins a window.
    "set idle_in_transaction_session_timeout = 0;",
    f"select {tagged('pg_backend_pid()')};",
))


# ---------------------------------------------------------------------------
# Local stack bootstrap
# ---------------------------------------------------------------------------

def psql_binary() -> str:
    binary = shutil.which("psql")
    if binary:
        return binary
    home = Path(os.environ.get("SUPABASE_HOME", Path.home() / ".supabase"))
    matches = list((home / "cache/stack").glob("**/bin/psql"))
    if len(matches) != 1:
        raise RuntimeError("Set PATH to the test stack's PostgreSQL bin directory")
    return str(matches[0])


def run_sql_file(binary: str, database: str, path: Path) -> None:
    result = subprocess.run(
        [binary, "--no-psqlrc", "--dbname", database, "--set", "ON_ERROR_STOP=1",
         "--file", str(path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"SQL failed: {path.name}\n{result.stderr}")
    print(f"SQL passed: {path.relative_to(ROOT)}", flush=True)


def apply_sql(binary: str, database: str) -> None:
    for relative in SQL_FILES:
        run_sql_file(binary, database, ROOT / relative)


# ---------------------------------------------------------------------------
# One real PostgreSQL session per psql subprocess
# ---------------------------------------------------------------------------

class Reply:
    """Everything one session printed for one batch of statements."""

    def __init__(self, label: str, sql: str, lines: list[str]) -> None:
        self.label = label
        self.sql = sql
        self.lines = lines

    @property
    def rows(self) -> list[list[str]]:
        return [line[len(ROW):].split("~") for line in self.lines if line.startswith(ROW)]

    @property
    def failures(self) -> list[tuple[str, str]]:
        found = []
        for line in self.lines:
            match = SQLSTATE_LINE.search(line)
            if match:
                found.append((match.group(1), match.group(2)))
        return found

    @property
    def sqlstates(self) -> list[str]:
        return [state for state, _ in self.failures]

    def transcript(self) -> str:
        body = "\n".join(f"    {line}" for line in self.lines) or "    <no output>"
        return f"  session {self.label} ran:\n{self.sql}\n  and printed:\n{body}"

    def clean(self, description: str) -> "Reply":
        if self.failures:
            raise AssertionError(
                f"{description}: session {self.label} failed with "
                f"{', '.join(f'{state} {message}' for state, message in self.failures)}\n"
                f"{self.transcript()}")
        return self

    def only(self, description: str) -> list[str]:
        self.clean(description)
        if len(self.rows) != 1:
            raise AssertionError(
                f"{description}: expected exactly one result row, got {len(self.rows)}\n"
                f"{self.transcript()}")
        return self.rows[0]


class Session:
    """A psql subprocess fed statement batches, each closed by an \\echo marker.

    Replies are read back incrementally so a batch that has not returned yet is
    distinguishable from one that returned or failed; combined with
    pg_blocking_pids that is how this harness tells "blocked" from "finished".
    """

    def __init__(self, label: str, binary: str, database: str) -> None:
        self.label = label
        self.pid = 0
        self._sequence = 0
        self._pending: collections.deque[tuple[str, str]] = collections.deque()
        self._buffer: list[str] = []
        self._lines: queue.Queue = queue.Queue()
        self._closed = False
        self._process = subprocess.Popen(
            [binary, "--no-psqlrc", "--dbname", database, "--quiet", "--no-align",
             "--tuples-only", "--variable", "VERBOSITY=verbose"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        self._reader = threading.Thread(target=self._pump, name=f"psql-{label}", daemon=True)
        self._reader.start()
        self.send(SESSION_SETUP)
        reply = self.poll(SETUP_TIMEOUT)
        if reply is None:
            self.close()
            raise RuntimeError(
                f"Session {label} printed no marker within {SETUP_TIMEOUT:.0f}s. This harness "
                "delimits replies with \\echo and needs psql to flush its output stream; "
                "check that `psql` is the test stack's own binary and that nothing is "
                "buffering its output.")
        self.pid = int(reply.only(f"session {label} backend pid")[0])

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _pump(self) -> None:
        for line in self._process.stdout:
            self._lines.put(line.rstrip("\n"))
        self._lines.put(None)

    def send(self, sql: str) -> None:
        """Queue a batch. psql executes batches in order, so this may be called
        while an earlier batch is still blocked inside the server."""
        if self._closed:
            raise AssertionError(f"session {self.label} is closed")
        self._sequence += 1
        marker = f"{MARK}{self.label}~{self._sequence}"
        body = sql.strip()
        self._pending.append((marker, body))
        self._process.stdin.write(f"{body}\n\\echo {marker}\n")
        self._process.stdin.flush()

    def poll(self, timeout: float) -> Reply | None:
        """The oldest queued batch's reply, or None while it has not returned."""
        if not self._pending:
            raise AssertionError(f"session {self.label}: nothing was sent to collect")
        marker, sql = self._pending[0]
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                return None
            if line is None:
                transcript = "\n".join(self._buffer) or "<no output>"
                raise AssertionError(
                    f"session {self.label} exited while running:\n{sql}\nand printed:\n{transcript}")
            if line == marker:
                self._pending.popleft()
                lines, self._buffer = self._buffer, []
                return Reply(self.label, sql, lines)
            self._buffer.append(line)

    def collect(self, description: str, timeout: float = MARKER_TIMEOUT) -> Reply:
        reply = self.poll(timeout)
        if reply is None:
            marker, sql = self._pending[0]
            transcript = "\n".join(self._buffer) or "<no output>"
            raise AssertionError(
                f"{description}: session {self.label} did not return within {timeout:.0f}s "
                f"while running:\n{sql}\npartial output:\n{transcript}")
        return reply

    def run(self, sql: str, description: str = "statement") -> Reply:
        self.send(sql)
        return self.collect(description)

    def ok(self, sql: str, description: str) -> Reply:
        return self.run(sql, description).clean(description)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(OSError, ValueError):
            self._process.stdin.write("\\q\n")
            self._process.stdin.flush()
        with contextlib.suppress(OSError, ValueError):
            self._process.stdin.close()
        for terminate in (None, self._process.terminate, self._process.kill):
            if terminate is not None:
                terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self._process.wait(timeout=5)
                return
        raise RuntimeError(f"psql session {self.label} could not be stopped")


# ---------------------------------------------------------------------------
# Observing the server rather than guessing about timing
# ---------------------------------------------------------------------------

def blocking_pids(control: Session, session: Session) -> list[int]:
    """Which backends the server says this one is waiting on, if any."""
    reply = control.run("select " + tagged(f"pg_blocking_pids({session.pid})") + ";",
                        "pg_blocking_pids")
    return [int(value) for value in re.findall(r"\d+", reply.only("pg_blocking_pids")[0])]


def settle(control: Session, session: Session, description: str,
           timeout: float = WINDOW_SECONDS) -> Reply | None:
    """Wait until the session's batch either returned or is provably blocked.

    Returns the Reply when it returned, None when the server reports it waiting
    on another backend. Neither outcome within the bound means the interleaving
    this case depends on did not happen, which is a failure, never a pass.
    """
    deadline = time.monotonic() + timeout
    while True:
        reply = session.poll(POLL_SECONDS)
        if reply is not None:
            return reply
        if blocking_pids(control, session):
            return None
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"{description}: session {session.label} neither returned nor blocked within "
                f"{timeout:.1f}s, so the race window was not reproduced. Re-check the lock "
                "the pinning session takes against the locks the call under test takes.")


def must_block(control: Session, session: Session, description: str) -> None:
    reply = settle(control, session, description)
    if reply is not None:
        raise AssertionError(
            f"{description}: session {session.label} ran to completion instead of waiting for "
            f"the session that holds the conflicting lock.\n{reply.transcript()}")


def assert_no_deadlock(case: str, finding: str, replies: dict[str, Reply]) -> None:
    for label, reply in replies.items():
        for state, message in reply.failures:
            if state == SQLSTATE_DEADLOCK:
                raise AssertionError(
                    f"{case} ({finding}): session {label} aborted with SQLSTATE {state}: "
                    f"{message}. finish_analysis_run and fail_analysis_run lock "
                    "public.factory_runs before public.work_items, while cancel_work_item, "
                    "revoke_project_worker and the claim reclaim path lock them in the "
                    "opposite order. One lock order everywhere removes this cycle.\n"
                    f"{reply.transcript()}")


# ---------------------------------------------------------------------------
# Persisted state readers, always on the owner connection
# ---------------------------------------------------------------------------

def run_state(control: Session, run_id: str) -> dict[str, str]:
    reply = control.run(
        "select " + tagged(
            "r.status", "r.error_code", "r.result is not null", "r.phase",
            "(select count(*) from private.factory_run_leases l where l.run_id = r.id)")
        + f" from public.factory_runs r where r.id = '{run_id}';", "run state")
    fields = reply.only(f"run {run_id}")
    return dict(zip(("status", "error_code", "has_result", "phase", "leases"), fields))


def item_state(control: Session, work_item_id: str) -> dict[str, str]:
    reply = control.run(
        "select " + tagged("w.status", "w.error_code", "w.attempts", "w.max_attempts",
                           "w.cancel_requested_at is not null")
        + f" from public.work_items w where w.id = '{work_item_id}';", "work item state")
    fields = reply.only(f"work item {work_item_id}")
    return dict(zip(("status", "error_code", "attempts", "max_attempts", "cancelled"), fields))


def registration_state(control: Session, project_id: str, worker_id: str) -> dict[str, str]:
    reply = control.run(
        "select " + tagged("k.id", "k.enabled")
        + f" from public.project_workers k where k.project_id = '{project_id}'"
          f" and k.worker_user_id = '{worker_id}';", "registration state")
    fields = reply.only(f"registration of {worker_id}")
    return dict(zip(("id", "enabled"), fields))


def source_identity(control: Session, attempt: "Attempt") -> dict[str, str]:
    """The work item's pinned source identity and the attempt's recorded one."""
    reply = control.run(
        "select " + tagged("w.pinned_source_ref", "w.pinned_source_commit",
                           "r.source_ref", "r.source_commit", "r.source_digest")
        + " from public.work_items w join public.factory_runs r on r.work_item_id = w.id"
          f" where w.id = '{attempt.work_item_id}' and r.id = '{attempt.run_id}';",
        "source identity")
    fields = reply.only(f"source identity of attempt {attempt.run_id}")
    return dict(zip(("pinned_ref", "pinned_commit", "ref", "commit", "digest"), fields))


def live_attempts(control: Session, project_id: str, worker_id: str) -> int:
    """Committed running attempts of one identity that still hold a lease row."""
    reply = control.run(
        "select " + tagged("count(*)")
        + " from public.factory_runs r join private.factory_run_leases l on l.run_id = r.id"
          f" where r.project_id = '{project_id}' and r.worker_user_id = '{worker_id}'"
          " and r.status = 'running';", "live attempts")
    return int(reply.only("live attempt count")[0])


# ---------------------------------------------------------------------------
# Fixtures. Created through the real RPCs, deleted again before this returns.
# ---------------------------------------------------------------------------

@dataclass
class Attempt:
    work_item_id: str
    run_id: str
    attempt: int
    lease_token: str


@dataclass
class Harness:
    control: Session
    a: Session
    b: Session
    c: Session
    suffix: str
    owner: str
    worker_a: str
    worker_b: str
    slug: str
    project_one: str = ""
    project_two: str = ""


def build_fixtures(h: Harness) -> None:
    accounts = (
        (h.owner, f"oryveta-race-owner-{h.suffix}@example.invalid", "{}"),
        (h.worker_a, f"oryveta-race-worker-a-{h.suffix}@example.invalid", WORKER_METADATA),
        (h.worker_b, f"oryveta-race-worker-b-{h.suffix}@example.invalid", WORKER_METADATA),
    )
    # Designating a worker service identity is an Auth admin API write to
    # auth.users.raw_app_meta_data. These rows are staged exactly as the admin
    # API would write them; every transition afterwards is the real one.
    values = ",\n".join(
        f"('{user_id}','{INSTANCE}','authenticated','authenticated','{email}','',now(),"
        f"'{metadata}'::jsonb,now(),now())" for user_id, email, metadata in accounts)
    h.control.ok(
        "insert into auth.users (id,instance_id,aud,role,email,encrypted_password,"
        f"email_confirmed_at,raw_app_meta_data,created_at,updated_at) values\n{values};",
        "fixture accounts")

    projects = h.control.ok(
        "begin;\n" + actor(h.owner) + "\n"
        f"insert into public.workspaces(name,slug,created_by) values "
        f"('Oryveta race {h.suffix}','{h.slug}','{h.owner}');\n"
        "select " + tagged("t.id") + " from public.create_project("
        f"(select w.id from public.workspaces w where w.slug = '{h.slug}'),"
        f" 'Race runtime alpha', '{PROJECT_BRIEF}', 'evolve', '{SOURCE_URL}') t;\n"
        "select " + tagged("t.id") + " from public.create_project("
        f"(select w.id from public.workspaces w where w.slug = '{h.slug}'),"
        f" 'Race runtime beta', '{PROJECT_BRIEF}', 'evolve', '{SOURCE_URL}') t;\n"
        "commit;", "fixture projects")
    if len(projects.rows) != 2:
        raise AssertionError(f"the project fixtures were not created\n{projects.transcript()}")
    h.project_one = projects.rows[0][0]
    h.project_two = projects.rows[1][0]

    for worker, label in ((h.worker_a, "Race worker A"), (h.worker_b, "Race worker B")):
        register_worker(h, worker, label)
    print(f"Fixtures: workspace {h.slug}, project one {h.project_one} with two registered "
          f"worker identities, project two {h.project_two} for the submission races", flush=True)


def register_worker(h: Harness, worker_id: str, label: str) -> str:
    reply = h.control.ok(
        "begin;\n" + actor(h.owner) + "\n"
        "select " + tagged("t.id", "t.enabled") + " from public.register_project_worker("
        f"p_project_id => '{h.project_one}', p_worker_user_id => '{worker_id}',"
        f" p_label => '{label}') t;\n"
        "commit;", f"registering {label}")
    fields = reply.only(f"registration of {label}")
    if fields[1] != "true":
        raise AssertionError(f"{label} was not registered enabled\n{reply.transcript()}")
    return fields[0]


def submit_item(h: Harness, project_id: str) -> str:
    reply = h.control.ok(
        "begin;\n" + actor(h.owner) + "\n"
        "select " + tagged("t.work_item_id", "t.status") + " from public.submit_repository_analysis("
        f"p_project_id => '{project_id}', p_idempotency_key => null) t;\n"
        "commit;", "submitting work")
    fields = reply.only("submitted work item")
    if fields[1] != "queued":
        raise AssertionError(f"a fresh submission was not queued\n{reply.transcript()}")
    return fields[0]


def claim_bare(h: Harness, session: Session, worker_id: str, work_item_id: str) -> Attempt:
    """One real claimed attempt that has not resolved any source identity yet."""
    reply = session.ok(
        "begin;\n" + actor(worker_id) + "\n"
        "select " + tagged("t.work_item_id", "t.run_id", "t.attempt", "t.lease_token")
        + f" from public.claim_analysis_work(p_project_id => '{h.project_one}',"
          f" p_lease_seconds => {LEASE_SECONDS}) t;\n"
        "commit;", "claiming work")
    fields = reply.only("claimed attempt")
    if fields[0] != work_item_id:
        raise AssertionError(
            f"the claim handed out work item {fields[0]} instead of {work_item_id}; another "
            f"claimable item is interfering with this case\n{reply.transcript()}")
    return Attempt(fields[0], fields[1], int(fields[2]), fields[3])


def claim_attempt(h: Harness, session: Session, worker_id: str, work_item_id: str) -> Attempt:
    """One real claimed attempt that has already recorded its source identity."""
    attempt = claim_bare(h, session, worker_id, work_item_id)
    heartbeat = session.ok(
        "begin;\n" + actor(worker_id) + "\n"
        "select " + tagged("t.lease_valid", "t.reason") + " from public.heartbeat_analysis_run("
        f"p_run_id => '{attempt.run_id}', p_lease_token => '{attempt.lease_token}',"
        f" p_phase => 'analyzing', {IDENTITY_ARGS}, p_lease_seconds => {LEASE_SECONDS}) t;\n"
        "commit;", "recording the source identity")
    fields = heartbeat.only("heartbeat")
    if fields[0] != "true":
        raise AssertionError(
            f"the fixture attempt could not record its source identity ({fields[1]})\n"
            f"{heartbeat.transcript()}")
    return attempt


def age_lease(h: Harness, run_id: str) -> None:
    # now() never advances inside one transaction, so moving lease_expires_at
    # into the past is how elapsed wall-clock time is staged here. The owner
    # connection does it because no client role holds UPDATE on this table.
    h.control.ok(
        f"update public.factory_runs r set lease_expires_at = {AGED_LEASE} where r.id = '{run_id}';",
        "ageing a lease")


def settle_project_one(h: Harness) -> None:
    """Leave no claimable or running item behind between cases.

    Each case depends on exactly which item the claim scan and the reclaim scan
    can see, so every case starts from a project with no live work.
    """
    h.control.ok(
        "begin;\n" + actor(h.owner) + "\n"
        "do $settle$\n"
        "declare v_item record;\n"
        "begin\n"
        "  for v_item in select w.id from public.work_items w\n"
        f"   where w.project_id = '{h.project_one}' and w.status in ('queued','running') loop\n"
        "    perform 1 from public.cancel_work_item(v_item.id) t;\n"
        "  end loop;\n"
        "end\n"
        "$settle$;\n"
        "commit;", "settling outstanding work")


def remove_fixtures(control: Session, h: Harness) -> None:
    """Delete every row this script created, then prove none survived."""
    scope = (" using public.projects p, public.workspaces w"
             f" where {{column}} = p.id and p.workspace_id = w.id and w.slug = '{h.slug}'")
    users = ", ".join(f"'{user_id}'" for user_id in (h.owner, h.worker_a, h.worker_b))
    control.ok(
        "begin;\n"
        "delete from public.factory_runs r" + scope.format(column="r.project_id") + ";\n"
        "delete from public.work_items i" + scope.format(column="i.project_id") + ";\n"
        "delete from public.project_workers k" + scope.format(column="k.project_id") + ";\n"
        "delete from public.projects p using public.workspaces w"
        f" where p.workspace_id = w.id and w.slug = '{h.slug}';\n"
        f"delete from public.workspaces w where w.slug = '{h.slug}';\n"
        f"delete from auth.users u where u.id in ({users});\n"
        "commit;", "removing fixtures")
    remaining = control.ok(
        "select " + tagged(
            f"(select count(*) from public.workspaces w where w.slug = '{h.slug}')",
            f"(select count(*) from auth.users u where u.id in ({users}))",
            f"(select count(*) from public.work_items i where i.created_by in ({users}))",
            f"(select count(*) from public.factory_runs r where r.worker_user_id in ({users}))",
            f"(select count(*) from public.project_workers k where k.worker_user_id in ({users}))")
        + ";", "verifying fixture removal")
    counts = remaining.only("fixture residue")
    if any(count != "0" for count in counts):
        raise AssertionError(
            "fixture rows survived cleanup (workspaces, users, work items, runs, registrations): "
            f"{', '.join(counts)}")
    print("Cleanup: every fixture account, workspace, project, work item, attempt, lease and "
          "registration this run created was deleted", flush=True)


# ---------------------------------------------------------------------------
# DR-002. One lock order, or a deadlock.
# ---------------------------------------------------------------------------

def race_against_attempt(h: Harness, case: str, closing_sql: str, opponent_sql: str,
                         work_item_id: str, opponent_actor: str) -> tuple[Reply, Reply]:
    """Drive a completion and a competing transition into the same two rows.

    The window is pinned open with the identical work-item row lock the
    competing call takes first, so session B's lock sequence is exactly the one
    it would have in an unsynchronized race, held open long enough to be
    observed. Session A's completion is released into that window and the
    competing RPC follows in the same transaction as the pin.
    """
    h.b.ok(f"begin;\nselect 1 from public.work_items w where w.id = '{work_item_id}' for update;",
           f"{case}: pinning the work item row lock")
    h.a.send(f"begin;\n{actor(h.worker_a)}\n{closing_sql}")
    must_block(h.control, h.a,
               f"{case}: the completion must wait for the work item row lock")
    # Both commits are queued now, so neither session's outcome depends on which
    # of the two the server lets through first.
    h.b.send(f"{actor(opponent_actor)}\n{opponent_sql}")
    h.b.send("commit;")
    h.a.send("commit;")
    opponent = h.b.collect(f"{case}: the competing transition")
    h.b.collect(f"{case}: the competing transition's commit")
    closing = h.a.collect(f"{case}: the completion")
    h.a.collect(f"{case}: the completion's commit")
    assert_no_deadlock(case, "DR-002", {"A": closing, "B": opponent})
    return closing, opponent


def assert_refused(case: str, reply: Reply, reasons: set[str]) -> str:
    fields = reply.only(f"{case}: the completion's verdict")
    accepted, reason = fields[0], fields[1]
    if accepted != "false":
        raise AssertionError(
            f"{case} (DR-002): the completion was accepted even though a competing transition "
            f"had already taken the work item (reason {reason})\n{reply.transcript()}")
    if reason not in reasons:
        raise AssertionError(
            f"{case} (DR-002): the completion was refused with reason '{reason}', which is not "
            f"one of the documented outcomes {sorted(reasons)}\n{reply.transcript()}")
    return reason


def assert_attempt_closed(case: str, control: Session, attempt: Attempt,
                          item_statuses: set[str]) -> dict[str, str]:
    run = run_state(control, attempt.run_id)
    if run["status"] == "running":
        raise AssertionError(
            f"{case} (DR-002): attempt {attempt.run_id} is still running after a competing "
            "transition claimed its work item")
    if run["has_result"] != "false":
        raise AssertionError(
            f"{case} (DR-002): a refused completion still published a result on attempt "
            f"{attempt.run_id}")
    if run["leases"] != "0":
        raise AssertionError(
            f"{case} (DR-002): attempt {attempt.run_id} ended as {run['status']} but its lease "
            "row survived, so the fence is incomplete")
    item = item_state(control, attempt.work_item_id)
    if item["status"] not in item_statuses:
        raise AssertionError(
            f"{case} (DR-002): work item {attempt.work_item_id} ended as '{item['status']}', "
            f"not one of {sorted(item_statuses)}")
    return item


def prove_completion_versus_cancellation(h: Harness) -> None:
    # DR-002. Interleaving:
    #   B  begin; SELECT ... FROM work_items WHERE id = X FOR UPDATE
    #      (the same row lock cancel_work_item's first statement takes)
    #   A  begin; finish_analysis_run(run of X, token, result)
    #      pre-fix : locks public.factory_runs first, then waits for X
    #      post-fix: resolves the item id unlocked, then waits for X
    #   B  cancel_work_item(X); commit
    #      pre-fix : fence_running_runs waits for A's run lock, closing the
    #                cycle, and a session aborts with 40P01
    #      post-fix: the run is unlocked, the attempt is fenced, B commits, and
    #                A wakes up, revalidates and refuses to publish
    case = "completion_versus_cancellation"
    item = submit_item(h, h.project_one)
    attempt = claim_attempt(h, h.a, h.worker_a, item)
    closing, opponent = race_against_attempt(
        h, case,
        "select " + tagged("t.accepted", "t.reason", "t.work_item_status")
        + f" from public.finish_analysis_run(p_run_id => '{attempt.run_id}',"
          f" p_lease_token => '{attempt.lease_token}', p_result => '{RESULT}'::jsonb) t;",
        "select " + tagged("t.status", "t.already_terminal", "t.fenced_runs")
        + f" from public.cancel_work_item(p_work_item_id => '{item}') t;",
        item, h.owner)
    cancellation = opponent.only(f"{case}: the cancellation")
    if cancellation[0] != "cancelled" or cancellation[1] != "false":
        raise AssertionError(
            f"{case} (DR-002): the cancellation did not take the work item\n"
            f"{opponent.transcript()}")
    if int(cancellation[2]) < 1:
        raise AssertionError(
            f"{case} (DR-002): the cancellation fenced {cancellation[2]} attempts, so it never "
            f"saw the attempt it raced\n{opponent.transcript()}")
    reason = assert_refused(case, closing, {"cancelled", "not_running"})
    assert_attempt_closed(case, h.control, attempt, {"cancelled"})
    settle_project_one(h)
    print(f"{case} (DR-002): finish_analysis_run and cancel_work_item contended for the same "
          f"work item and attempt without a deadlock; the cancellation fenced the attempt and "
          f"the completion was refused with '{reason}', publishing no result", flush=True)


def prove_failure_versus_cancellation(h: Harness) -> None:
    # DR-002. Identical interleaving to completion_versus_cancellation, with
    # fail_analysis_run in A's place: it takes the run lock before the work item
    # lock too, so it closes the same cycle against cancel_work_item.
    case = "failure_versus_cancellation"
    item = submit_item(h, h.project_one)
    attempt = claim_attempt(h, h.a, h.worker_a, item)
    closing, opponent = race_against_attempt(
        h, case,
        "select " + tagged("t.accepted", "t.reason", "t.work_item_status", "t.retry_scheduled")
        + f" from public.fail_analysis_run(p_run_id => '{attempt.run_id}',"
          f" p_lease_token => '{attempt.lease_token}', p_error_code => 'race_probe') t;",
        "select " + tagged("t.status", "t.already_terminal", "t.fenced_runs")
        + f" from public.cancel_work_item(p_work_item_id => '{item}') t;",
        item, h.owner)
    opponent.only(f"{case}: the cancellation")
    reason = assert_refused(case, closing, {"cancelled", "not_running"})
    # A cancelled work item is terminal: a failed attempt may not requeue it.
    assert_attempt_closed(case, h.control, attempt, {"cancelled"})
    settle_project_one(h)
    print(f"{case} (DR-002): fail_analysis_run and cancel_work_item contended for the same work "
          f"item and attempt without a deadlock; the failure report was refused with '{reason}' "
          f"and the cancelled work item stayed terminal", flush=True)


def prove_completion_versus_reclaim(h: Harness) -> None:
    # DR-002. The third competing lock order is the reclaim path inside
    # claim_analysis_work, which private.expire_stale_runs reaches with the work
    # item locked before the run:
    #   B  begin; SELECT ... FROM work_items WHERE id = X FOR UPDATE
    #   A  begin; finish_analysis_run(expired run of X, token, result)
    #      pre-fix : holds the run lock and waits for X
    #   B  claim_analysis_work(project) as the other worker identity; commit
    #      pre-fix : expire_stale_runs waits for A's run lock -> 40P01
    #      post-fix: the expired attempt is reclaimed, the item is requeued and
    #                reclaimed as the next attempt, and A then refuses
    case = "completion_versus_reclaim"
    item = submit_item(h, h.project_one)
    attempt = claim_attempt(h, h.a, h.worker_a, item)
    age_lease(h, attempt.run_id)
    closing, opponent = race_against_attempt(
        h, case,
        "select " + tagged("t.accepted", "t.reason", "t.work_item_status")
        + f" from public.finish_analysis_run(p_run_id => '{attempt.run_id}',"
          f" p_lease_token => '{attempt.lease_token}', p_result => '{RESULT}'::jsonb) t;",
        "select " + tagged("t.work_item_id", "t.run_id", "t.attempt")
        + f" from public.claim_analysis_work(p_project_id => '{h.project_one}',"
          f" p_lease_seconds => {LEASE_SECONDS}) t;",
        item, h.worker_b)
    opponent.clean(f"{case}: the reclaiming claim")
    reason = assert_refused(case, closing, {"not_running", "lease_lost", "cancelled"})
    run = run_state(h.control, attempt.run_id)
    if run["status"] != "failed" or run["error_code"] != "lease_expired":
        raise AssertionError(
            f"{case} (DR-002): the expired attempt ended as {run['status']}/{run['error_code']} "
            "instead of being reclaimed as a lease_expired failure")
    assert_attempt_closed(case, h.control, attempt, {"queued", "running", "failed"})
    settle_project_one(h)
    print(f"{case} (DR-002): finish_analysis_run and the claim reclaim path contended for the "
          f"same work item and attempt without a deadlock; the expired attempt was reclaimed as "
          f"lease_expired and the late completion was refused with '{reason}'", flush=True)


def prove_completion_versus_revocation(h: Harness) -> None:
    # DR-002. The fourth competing lock order is revoke_project_worker, which
    # locks project_workers, then the work item, then the run:
    #   B  begin; SELECT ... FROM work_items WHERE id = X FOR UPDATE
    #   A  begin; finish_analysis_run(run of X, token, result)
    #   B  revoke_project_worker(project, worker A); commit
    #      pre-fix : the fencing UPDATE waits for A's run lock -> 40P01
    #      post-fix: revocation fences the attempt and A then refuses
    case = "completion_versus_revocation"
    item = submit_item(h, h.project_one)
    attempt = claim_attempt(h, h.a, h.worker_a, item)
    closing, opponent = race_against_attempt(
        h, case,
        "select " + tagged("t.accepted", "t.reason", "t.work_item_status")
        + f" from public.finish_analysis_run(p_run_id => '{attempt.run_id}',"
          f" p_lease_token => '{attempt.lease_token}', p_result => '{RESULT}'::jsonb) t;",
        "select " + tagged("t.id", "t.enabled", "t.fenced_runs")
        + f" from public.revoke_project_worker(p_project_id => '{h.project_one}',"
          f" p_worker_user_id => '{h.worker_a}') t;",
        item, h.owner)
    revocation = opponent.only(f"{case}: the revocation")
    if revocation[1] != "false" or int(revocation[2]) < 1:
        raise AssertionError(
            f"{case} (DR-002): revocation reported enabled={revocation[1]} and "
            f"fenced_runs={revocation[2]}, so it did not fence the attempt it raced\n"
            f"{opponent.transcript()}")
    reason = assert_refused(case, closing, {"worker_not_registered", "not_running", "cancelled"})
    run = run_state(h.control, attempt.run_id)
    if run["error_code"] != "worker_revoked":
        raise AssertionError(
            f"{case} (DR-002): the fenced attempt recorded error_code "
            f"'{run['error_code']}' instead of 'worker_revoked'")
    assert_attempt_closed(case, h.control, attempt, {"queued", "failed", "cancelled"})
    settle_project_one(h)
    register_worker(h, h.worker_a, "Race worker A")
    print(f"{case} (DR-002): finish_analysis_run and revoke_project_worker contended for the "
          f"same work item and attempt without a deadlock; revocation fenced the attempt as "
          f"worker_revoked and the completion was refused with '{reason}'", flush=True)


# ---------------------------------------------------------------------------
# DR-003. A claim may not commit around a revocation.
# ---------------------------------------------------------------------------

def prove_claim_versus_revocation(h: Harness) -> Attempt | None:
    # DR-003. claim_analysis_work reads its registration without a lock, so a
    # revocation that commits during the claim neither stops the claim nor sees
    # the run it is about to commit. Pausing mid-RPC needs a deliberate
    # mechanism, and this uses a real lock the claim itself takes rather than a
    # sleep or an advisory lock bolted on outside the function: the project's
    # previous attempt is left with an expired lease, so the claim must enter
    # private.expire_stale_runs and lock that work item row. Session C holds
    # that exact row lock, which parks session A inside claim_analysis_work
    # after it has read the registration and before it inserts the run - the
    # real window, held open by a real contention this path can meet in
    # production (a cancellation or a sibling reclaim holding the same row).
    #
    #   C  begin; SELECT ... FROM work_items WHERE id = Y FOR UPDATE
    #   A  begin; claim_analysis_work(project) as worker A
    #      -> parked inside expire_stale_runs, registration already read
    #   B  begin; revoke_project_worker(project, worker A)
    #      pre-fix : nothing serializes the two, so B commits with fenced_runs=0
    #                and A then commits a running attempt with a live lease for
    #                an identity that is no longer registered
    #      post-fix: the claim holds FOR SHARE on its registration row, so B's
    #                FOR UPDATE on that row waits for A to commit and then
    #                fences the run it can finally see
    #   C  rollback (releases A)
    #   A  commit, B commit (both queued, so the order the server chooses is
    #      whichever the fix implies)
    case = "claim_versus_revocation"
    item = submit_item(h, h.project_one)
    stale = claim_attempt(h, h.b, h.worker_b, item)
    age_lease(h, stale.run_id)

    h.c.ok(f"begin;\nselect 1 from public.work_items w where w.id = '{item}' for update;",
           f"{case}: pinning the reclaim path's work item row lock")
    h.a.send(f"begin;\n{actor(h.worker_a)}\n"
             + "select " + tagged("t.work_item_id", "t.run_id", "t.attempt", "t.lease_token")
             + f" from public.claim_analysis_work(p_project_id => '{h.project_one}',"
               f" p_lease_seconds => {LEASE_SECONDS}) t;")
    must_block(h.control, h.a,
               f"{case}: the claim must park inside its reclaim path on the pinned work item")
    h.b.send(f"begin;\n{actor(h.owner)}\n"
             + "select " + tagged("t.id", "t.enabled", "t.fenced_runs")
             + f" from public.revoke_project_worker(p_project_id => '{h.project_one}',"
               f" p_worker_user_id => '{h.worker_a}') t;")
    early = settle(h.control, h.b, f"{case}: the revocation")

    h.c.ok("rollback;", f"{case}: releasing the pinned work item")
    h.a.send("commit;")
    h.b.send("commit;")
    claim = h.a.collect(f"{case}: the claim")
    h.a.collect(f"{case}: the claim's commit")
    revocation = early if early is not None else h.b.collect(f"{case}: the revocation")
    h.b.collect(f"{case}: the revocation's commit")
    claim.clean(f"{case}: the claim")
    revocation.clean(f"{case}: the revocation")

    registration = registration_state(h.control, h.project_one, h.worker_a)
    if registration["enabled"] != "false":
        raise AssertionError(f"{case} (DR-003): the registration is still enabled after "
                             f"revocation\n{revocation.transcript()}")
    outstanding = live_attempts(h.control, h.project_one, h.worker_a)
    if early is not None:
        raise AssertionError(
            f"{case} (DR-003): revoke_project_worker ran to completion while the claim was still "
            f"in flight, so the two were never serialized. It reported "
            f"fenced_runs={revocation.rows[0][2] if revocation.rows else 'none'} and the claim "
            f"then committed {len(claim.rows)} attempt(s), leaving {outstanding} running "
            f"attempt(s) with a live lease for the revoked identity. claim_analysis_work must "
            f"take FOR SHARE on its enabled project_workers row before any item or run lock and "
            f"hold it to commit.\n{revocation.transcript()}\n{claim.transcript()}")
    if outstanding:
        raise AssertionError(
            f"{case} (DR-003): {outstanding} attempt(s) of the revoked identity are still "
            f"running with a live lease, so revocation missed a lease the claim committed")
    if not claim.rows:
        # The other documented resolution: revocation won and the claim took
        # nothing. Nothing is left to fence, and nothing can be resurrected.
        print(f"{case} (DR-003): the revocation was serialized ahead of the claim, which then "
              f"handed out no work; no attempt of the revoked identity exists", flush=True)
        return None
    fields = claim.only(f"{case}: the claim")
    attempt = Attempt(fields[0], fields[1], int(fields[2]), fields[3])
    run = run_state(h.control, attempt.run_id)
    if run["status"] != "cancelled" or run["error_code"] != "worker_revoked":
        raise AssertionError(
            f"{case} (DR-003): the claimed attempt ended as {run['status']}/{run['error_code']} "
            "instead of being fenced as cancelled/worker_revoked by the revocation that "
            "followed it")
    if run["leases"] != "0":
        raise AssertionError(
            f"{case} (DR-003): the fenced attempt's lease row survived, so its worker could "
            "still publish")
    print(f"{case} (DR-003): the claim and the revocation were serialized on the registration "
          f"row; the claim committed attempt {attempt.attempt} and the revocation then fenced "
          f"it as worker_revoked with its lease deleted", flush=True)
    return attempt


def prove_fenced_lease_after_reregistration(h: Harness, attempt: Attempt | None) -> None:
    # DR-003, the follow-on the review calls out: re-registering the identity
    # inside the original lease window must not make a lease revocation already
    # fenced usable again. Nothing in the lease token itself expresses the
    # fence, so this has to be proven against the real RPCs.
    case = "fenced_lease_after_reregistration"
    if attempt is None:
        register_worker(h, h.worker_a, "Race worker A")
        settle_project_one(h)
        print(f"{case} (DR-003): no attempt survived the revocation, so there is no lease to "
              f"resurrect; the identity was re-registered for the remaining cases", flush=True)
        return
    register_worker(h, h.worker_a, "Race worker A")
    heartbeat = h.a.ok(
        "begin;\n" + actor(h.worker_a) + "\n"
        "select " + tagged("t.lease_valid", "t.reason", "t.run_status")
        + f" from public.heartbeat_analysis_run(p_run_id => '{attempt.run_id}',"
          f" p_lease_token => '{attempt.lease_token}', p_lease_seconds => {LEASE_SECONDS}) t;\n"
        "commit;", f"{case}: heartbeating the fenced attempt")
    fields = heartbeat.only(f"{case}: the heartbeat")
    if fields[0] != "false":
        raise AssertionError(
            f"{case} (DR-003): the fenced attempt's lease became valid again after the identity "
            f"was re-registered inside the original lease window (reason '{fields[1]}', run "
            f"status '{fields[2]}'). A lease revocation fenced must stay dead.\n"
            f"{heartbeat.transcript()}")
    completion = h.a.ok(
        "begin;\n" + actor(h.worker_a) + "\n"
        "select " + tagged("t.accepted", "t.reason")
        + f" from public.finish_analysis_run(p_run_id => '{attempt.run_id}',"
          f" p_lease_token => '{attempt.lease_token}', p_result => '{RESULT}'::jsonb) t;\n"
        "commit;", f"{case}: finishing the fenced attempt")
    verdict = completion.only(f"{case}: the completion")
    if verdict[0] != "false":
        raise AssertionError(
            f"{case} (DR-003): the fenced attempt published a result after the identity was "
            f"re-registered\n{completion.transcript()}")
    run = run_state(h.control, attempt.run_id)
    if run["has_result"] != "false":
        raise AssertionError(f"{case} (DR-003): a result was stored on the fenced attempt")
    settle_project_one(h)
    print(f"{case} (DR-003): after re-registering the identity inside the original lease window "
          f"the fenced attempt could neither heartbeat ('{fields[1]}') nor publish "
          f"('{verdict[1]}')", flush=True)


# ---------------------------------------------------------------------------
# DR-004. One work item, one pinned source identity.
# ---------------------------------------------------------------------------

def prove_concurrent_source_pinning(h: Harness) -> None:
    # DR-004. The pin is what holds every attempt of a work item to one commit,
    # so it may not be decided by whichever session writes last. Two sessions
    # resolving different commits for the same attempt is the reachable form of
    # that race: a worker whose heartbeat is retried after a connection reset,
    # or two processes started on the same claim, both report a snapshot.
    #
    #   A  begin; heartbeat(run of X, token, ref, commit one, digest one)
    #      -> holds X's work item row lock and X's run row lock, uncommitted
    #   B  begin; heartbeat(run of X, token, ref, commit two, digest two)
    #      pre-fix : nothing locks the work item, so both resolutions are
    #                coalesced into the run and no pin exists at all; the work
    #                item can then be completed against either commit
    #      post-fix: B waits for X's work item lock, then revalidates against
    #                what A recorded and refuses its own conflicting identity
    #   A  commit; B rolls back
    case = "concurrent_source_pinning"
    item = submit_item(h, h.project_one)
    attempt = claim_bare(h, h.a, h.worker_a, item)
    resolve = ("select " + tagged("t.lease_valid", "t.reason")
               + f" from public.heartbeat_analysis_run(p_run_id => '{attempt.run_id}',"
                 f" p_lease_token => '{attempt.lease_token}',"
                 " p_phase => 'fetching_source', p_source_ref => '{ref}',"
                 " p_source_commit => '{commit}', p_source_digest => '{digest}',"
                 f" p_lease_seconds => {LEASE_SECONDS}) t;")
    first = h.a.ok(
        f"begin;\n{actor(h.worker_a)}\n"
        + resolve.format(ref=SOURCE_REF, commit=SOURCE_COMMIT, digest=SOURCE_DIGEST),
        f"{case}: the first source resolution")
    if first.only(f"{case}: the first resolution")[0] != "true":
        raise AssertionError(
            f"{case} (DR-004): the first source resolution was refused\n{first.transcript()}")
    h.b.send(f"begin;\n{actor(h.worker_a)}\n"
             + resolve.format(ref=SOURCE_REF, commit=SOURCE_COMMIT_ALTERNATE,
                              digest=SOURCE_DIGEST_ALTERNATE))
    must_block(h.control, h.b,
               f"{case}: the second source resolution must wait for the work item row lock")
    h.a.send("commit;")
    h.a.collect(f"{case}: the first resolution's commit")
    second = h.b.collect(f"{case}: the second source resolution")
    h.b.send("rollback;")
    h.b.collect(f"{case}: the second resolution's rollback")
    messages = [message for _, message in second.failures]
    if not messages:
        raise AssertionError(
            f"{case} (DR-004): the second resolution reported {second.rows} instead of refusing "
            "a source identity that disagrees with the one already recorded. Two commits for "
            "one work item mean its result cannot be attributed to any single revision.\n"
            f"{second.transcript()}")
    if not any("source identity already recorded for this attempt" in message
               or "source identity conflicts with the work item pin" in message
               for message in messages):
        raise AssertionError(
            f"{case} (DR-004): the second resolution failed with {messages}, not with one of the "
            f"documented source identity refusals\n{second.transcript()}")
    identity = source_identity(h.control, attempt)
    if identity["pinned_commit"] != SOURCE_COMMIT or identity["pinned_ref"] != SOURCE_REF:
        raise AssertionError(
            f"{case} (DR-004): the work item is pinned to {identity['pinned_ref']} "
            f"{identity['pinned_commit']} instead of the first resolved "
            f"{SOURCE_REF} {SOURCE_COMMIT}")
    if identity["commit"] != SOURCE_COMMIT or identity["digest"] != SOURCE_DIGEST:
        raise AssertionError(
            f"{case} (DR-004): the attempt records commit {identity['commit']} and digest "
            f"{identity['digest']}, so the refused resolution still overwrote what the first "
            "one recorded")
    settle_project_one(h)
    print(f"{case} (DR-004): two simultaneous source resolutions of one attempt were serialized "
          f"on the work item row; the first pinned {SOURCE_COMMIT[:12]}... and the second was "
          f"refused without changing the pin or the recorded attempt identity", flush=True)

# ---------------------------------------------------------------------------
# DR-005. Two identical submissions must replay, not collide.
# ---------------------------------------------------------------------------

def submit_concurrently(h: Harness, case: str, key: str) -> tuple[Reply, Reply]:
    """Both sessions inside the admission window at the same time.

    Session A submits and does not commit, so its row is invisible to session
    B's existence check: B passes that check and reaches the insert, which is
    exactly the state both callers are in during a real simultaneous
    submission. B is then provably waiting on A's transaction, which is what
    makes the window reproducible instead of timing dependent.
    """
    columns = tagged("t.work_item_id", "t.status", "t.replayed", "t.input_digest")
    call = ("select " + columns + " from public.submit_repository_analysis("
            f"p_project_id => '{h.project_two}', p_idempotency_key => '{key}') t;")
    first = h.a.ok(f"begin;\n{actor(h.owner)}\n{call}", f"{case}: the first submission")
    h.b.send(f"begin;\n{actor(h.owner)}\n{call}")
    must_block(h.control, h.b,
               f"{case}: the second submission must reach the insert and wait for the first")
    h.a.send("commit;")
    h.a.collect(f"{case}: the first submission's commit")
    second = h.b.collect(f"{case}: the second submission")
    h.b.send("commit;")
    h.b.collect(f"{case}: the second submission's commit")
    for label, reply in (("A", first), ("B", second)):
        if SQLSTATE_UNIQUE_VIOLATION in reply.sqlstates:
            raise AssertionError(
                f"{case} (DR-005): session {label} failed with SQLSTATE "
                f"{SQLSTATE_UNIQUE_VIOLATION} (unique_violation) on "
                "work_items_idempotency_idx. Two callers inside the admission window must not "
                "race the unique index: submit_repository_analysis needs INSERT ... ON CONFLICT "
                "(project_id, created_by, idempotency_key) WHERE idempotency_key IS NOT NULL DO "
                f"NOTHING followed by a fresh locked read.\n{reply.transcript()}")
    return first, second


def prove_concurrent_idempotent_submission(h: Harness) -> None:
    case = "concurrent_idempotent_submission"
    key = f"race-same-{h.suffix}"
    first, second = submit_concurrently(h, case, key)
    second.clean(f"{case}: the second submission")
    one = first.only(f"{case}: the first submission")
    two = second.only(f"{case}: the second submission")
    if one[0] != two[0]:
        raise AssertionError(
            f"{case} (DR-005): the two submissions returned different work items {one[0]} and "
            f"{two[0]} for one idempotency key")
    if sorted((one[2], two[2])) != ["false", "true"]:
        raise AssertionError(
            f"{case} (DR-005): replayed flags were {one[2]} and {two[2]}; exactly one submission "
            "must report replayed=false")
    if one[3] != two[3]:
        raise AssertionError(
            f"{case} (DR-005): the replay returned input digest {two[3]} instead of {one[3]}")
    count = h.control.ok(
        "select " + tagged("count(*)")
        + f" from public.work_items w where w.project_id = '{h.project_two}'"
          f" and w.created_by = '{h.owner}' and w.idempotency_key = '{key}';",
        f"{case}: counting admitted rows").only(f"{case}: row count")[0]
    if count != "1":
        raise AssertionError(
            f"{case} (DR-005): {count} work items exist for one idempotency key")
    print(f"{case} (DR-005): two simultaneous identical submissions both returned work item "
          f"{one[0]}, exactly one of them as a replay, with one admitted row and no "
          f"unique-violation", flush=True)


def prove_conflicting_idempotent_submission(h: Harness) -> None:
    # DR-005, differing-input variant. The frozen input is the project's source
    # URL, so an authorized edit between the two submissions is what makes the
    # second submission's digest differ while the key stays the same. The edit
    # commits before B starts, so B genuinely computes the other digest.
    case = "conflicting_idempotent_submission"
    key = f"race-diff-{h.suffix}"
    h.control.ok(
        "begin;\n" + actor(h.owner) + "\n"
        "select " + tagged("t.source_url") + " from public.update_project("
        f"p_project_id => '{h.project_two}', p_name => 'Race runtime beta',"
        f" p_brief => '{PROJECT_BRIEF}', p_source_url => '{SOURCE_URL}') t;\n"
        "commit;", f"{case}: restoring the frozen source")
    columns = tagged("t.work_item_id", "t.status", "t.replayed", "t.input_digest")
    call = ("select " + columns + " from public.submit_repository_analysis("
            f"p_project_id => '{h.project_two}', p_idempotency_key => '{key}') t;")
    first = h.a.ok(f"begin;\n{actor(h.owner)}\n{call}", f"{case}: the first submission")
    h.control.ok(
        "begin;\n" + actor(h.owner) + "\n"
        "select " + tagged("t.source_url") + " from public.update_project("
        f"p_project_id => '{h.project_two}', p_name => 'Race runtime beta',"
        f" p_brief => '{PROJECT_BRIEF}', p_source_url => '{SOURCE_URL_ALTERNATE}') t;\n"
        "commit;", f"{case}: editing the project source between the two submissions")
    h.b.send(f"begin;\n{actor(h.owner)}\n{call}")
    must_block(h.control, h.b,
               f"{case}: the mismatched submission must reach the insert and wait for the first")
    h.a.send("commit;")
    h.a.collect(f"{case}: the first submission's commit")
    second = h.b.collect(f"{case}: the mismatched submission")
    h.b.send("rollback;")
    h.b.collect(f"{case}: the mismatched submission's rollback")
    if SQLSTATE_UNIQUE_VIOLATION in second.sqlstates:
        raise AssertionError(
            f"{case} (DR-005): the mismatched submission failed with SQLSTATE "
            f"{SQLSTATE_UNIQUE_VIOLATION} (unique_violation) instead of the documented "
            "'idempotency key already used for a different input'. The caller is told the wrong "
            f"thing about its own request.\n{second.transcript()}")
    messages = [message for _, message in second.failures]
    if not any("idempotency key already used for a different input" in message
               for message in messages):
        raise AssertionError(
            f"{case} (DR-005): the mismatched submission was not refused with the documented "
            f"message; it reported {messages or 'no error'} and returned "
            f"{second.rows}\n{second.transcript()}")
    count = h.control.ok(
        "select " + tagged("count(*)")
        + f" from public.work_items w where w.project_id = '{h.project_two}'"
          f" and w.created_by = '{h.owner}' and w.idempotency_key = '{key}';",
        f"{case}: counting admitted rows").only(f"{case}: row count")[0]
    if count != "1":
        raise AssertionError(
            f"{case} (DR-005): {count} work items exist for the reused key, so the mismatched "
            "submission was partly admitted")
    admitted = first.only(f"{case}: the first submission")[0]
    print(f"{case} (DR-005): a concurrent submission reusing the key with a different frozen "
          f"source was refused as a documented input mismatch, not as a uniqueness error, and "
          f"work item {admitted} stands alone", flush=True)


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------

def exercise(binary: str, database: str) -> None:
    suffix = uuid.uuid4().hex[:12]
    with contextlib.ExitStack() as resources:
        # control is the owner connection and stays out of every transaction it
        # is not fixturing, so it can always read state and ask the server which
        # backend is blocking which.
        control = resources.enter_context(Session("control", binary, database))
        workers = [resources.enter_context(Session(label, binary, database))
                   for label in ("A", "B", "C")]
        h = Harness(control=control, a=workers[0], b=workers[1], c=workers[2], suffix=suffix,
                    owner=str(uuid.uuid4()), worker_a=str(uuid.uuid4()),
                    worker_b=str(uuid.uuid4()), slug=f"race-{suffix}")
        print(f"Sessions: control pid {control.pid}, A pid {workers[0].pid}, "
              f"B pid {workers[1].pid}, C pid {workers[2].pid}", flush=True)
        try:
            build_fixtures(h)
            prove_completion_versus_cancellation(h)
            prove_failure_versus_cancellation(h)
            prove_completion_versus_reclaim(h)
            prove_completion_versus_revocation(h)
            claimed = prove_claim_versus_revocation(h)
            prove_fenced_lease_after_reregistration(h, claimed)
            prove_concurrent_source_pinning(h)
            prove_concurrent_idempotent_submission(h)
            prove_conflicting_idempotent_submission(h)
            print("All nine concurrency cases passed: DR-002's single lock order holds under "
                  "cancellation, revocation and reclaim, DR-003's claim cannot commit around a "
                  "revocation and a fenced lease stays dead, DR-004's source pin is decided "
                  "once under the work item lock, and DR-005's idempotent admission replays "
                  "instead of colliding.", flush=True)
        finally:
            # Close the racing sessions first: any transaction one of them still
            # holds would otherwise block the fixture deletion below.
            for session in workers:
                session.close()
            remove_fixtures(control, h)


def database_url(payload: object) -> str:
    """The stack's database URL, from either shape the Supabase CLI emits.

    `supabase status --output-format json` prints a flat map of connection
    values, while `supabase start --output-format json` nests the same values
    under "env". Both are accepted so a file captured from either command, or
    checked in for CI, works without being reshaped first.
    """
    if not isinstance(payload, dict):
        raise ValueError("Connection JSON must be an object of Supabase connection values")
    values = payload.get("env") if isinstance(payload.get("env"), dict) else payload
    url = values.get("DB_URL")
    if not isinstance(url, str) or not url:
        raise ValueError(
            "Connection JSON carries no DB_URL. Pass the output of `supabase status "
            "--output-format json` or `supabase start --output-format json`, either directly "
            "or with its values under \"env\".")
    return loopback(url)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connections", type=Path,
                        help="File holding `supabase status --output-format json` or "
                             "`supabase start --output-format json` output; stdin is read "
                             "when this is omitted")
    parser.add_argument("--skip-sql", action="store_true",
                        help="Do not re-apply the four schema files, for a stack that is "
                             "already at the stage-2 migration")
    arguments = parser.parse_args()
    text = (arguments.connections.read_text(encoding="utf-8") if arguments.connections
            else sys.stdin.read())
    database = database_url(json.loads(text))
    binary = psql_binary()
    if not arguments.skip_sql:
        apply_sql(binary, database)
    exercise(binary, database)


if __name__ == "__main__":
    main()
