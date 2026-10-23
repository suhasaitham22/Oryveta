"""Exercise the real stage-2 durable factory runtime against the local stack.

What is real: Supabase Auth sessions obtained with the ordinary password grant,
PostgREST RPCs and RLS reads, the committed stage-2 migration, the worker CLI
running as a separate operating-system process with its own rotating credential
file, and a genuine public GitHub archive analysed by a real child process.

What is deliberately refused: non-loopback service endpoints, stubbed auth,
intercepted HTTP, any production mutation, and the service-role key anywhere
near worker code. The service key is used only by the administrative Auth admin
calls that create the test accounts and designate the two worker service
identities; it is never written to a credential file, never passed to the worker
process and never used for an application call.

This script performs a real archive download, so it needs outbound HTTPS access
to api.github.com and the GitHub archive hosts. A missing egress path, a rate
limit or an oversized repository fails loudly with an actionable message instead
of silently skipping the analysis.

Pass JSON from `supabase status --output-format json` (or from `supabase start
--output-format json`) on stdin, or name a file with --connections. Supabase CLI
2.121.0 and the repository's supabase/config.toml provide PostgreSQL, Auth and
PostgREST. Requires httpx, `psql` on PATH (or SUPABASE_HOME pointing at the test
stack) and `pgrep`. No Playwright, no Node, no browser.

Timing is bounded and explicit. A worker checks its fence every lease/3 seconds,
so on a repository small enough to stay inside the importer's limits the analysis
child frequently exits on its own before the fence check lands. The cancellation
step therefore asserts the invariant that actually matters - a fenced attempt
leaves no analysis child behind and publishes no result - rather than claiming to
have observed a signal. The restart step SIGKILLs the worker's own process
group only: the analysis child leads a group of its own, so that step proves
the child stops itself once its worker is gone and that the snapshot tree it
left behind is reclaimed by the next worker's startup sweep. Nothing here
simulates losing the host; a work item whose worker disappears is recovered by
its lease expiring.

Usage:
    supabase status --output-format json | python scripts/factory_runtime_smoke.py
"""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"

# Explicit order, never a glob: durable_factory_runtime.sql builds on the
# project membership helpers, and an alphabetical sweep would load it first.
SQL_FILES = (
    "supabase/schema.sql",
    "supabase/migrations/private_chats_and_explicit_sharing.sql",
    "supabase/migrations/projects_and_project_membership.sql",
    "supabase/migrations/durable_factory_runtime.sql",
)

# Measured against the GitHub API on 2026-10-22: 5.0 MB of repository history,
# 204 tree entries, 91 files in the analyzer's source extensions. That is
# comfortably inside the importer's limits (15 MB repository, 12 MB archive,
# 1800 archive entries, 32 MB unpacked) while still giving the analysis child a
# lifetime long enough to be observed, killed and cancelled.
DEFAULT_REPOSITORY = "https://github.com/pallets/click"
GITHUB_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100})$")

# The worker heartbeats at lease/3 and the bounded GitHub fetch happens between
# two heartbeats, so a short lease can legitimately expire mid-fetch and be
# reclaimed. Paths that must succeed on the first attempt use the long lease;
# only the restart/reclaim path uses the short one, because it waits the lease
# out on purpose.
SUCCESS_LEASE_SECONDS = 60
RECLAIM_LEASE_SECONDS = 15

WORKER_EXIT_TIMEOUT = 300.0
ANALYSIS_START_TIMEOUT = 180.0
FENCE_TIMEOUT = 120.0
EXPIRY_SLACK_SECONDS = 3.0
FETCH_KILL_DELAY_SECONDS = 1.5
FAST_POLL_SECONDS = 0.05
SLOW_POLL_SECONDS = 0.25

PGREP = shutil.which("pgrep")


def loopback(url: str) -> str:
    if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Factory runtime smoke only accepts isolated loopback services")
    return url.rstrip("/")


class Secrets:
    """Values that must never surface in worker output, a run row or a log.

    Registered by purpose rather than by value, so a leak report can name what
    escaped without reprinting it.
    """

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def add(self, name: str, value: str | None) -> None:
        if value:
            self._values[name] = value

    def assert_absent(self, label: str, text: str) -> None:
        for name, value in self._values.items():
            if value in text:
                raise AssertionError(f"{label} disclosed {name}")

    def scrub(self, text: str) -> str:
        for name, value in self._values.items():
            text = text.replace(value, f"<{name} redacted>")
        return text


@dataclass
class Account:
    """One real Auth account created for this run."""

    name: str
    email: str
    user_id: str
    password: str = field(repr=False, default="")


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


def apply_sql(connection: dict, sql_tests: bool) -> None:
    database = loopback(connection["DB_URL"])
    binary = psql_binary()
    for relative in SQL_FILES:
        run_sql_file(binary, database, ROOT / relative)
    if sql_tests:
        # Optional and strictly last: the transactional authorization cases roll
        # back their own fixtures and are not part of the stage-2 flow below.
        for path in sorted((ROOT / "supabase/tests").glob("*.sql")):
            run_sql_file(binary, database, path)
    subprocess.run(
        [binary, "--no-psqlrc", "--dbname", database, "--set", "ON_ERROR_STOP=1",
         "--command", "NOTIFY pgrst, 'reload schema'"],
        check=True, capture_output=True, text=True,
    )


def assert_github_reachable(repository: str) -> None:
    """Prove the real archive fetch can happen before any work item exists.

    trust_env stays on, exactly like the importer, so this probe traverses the
    same proxy and TLS trust configuration the worker will use.
    """
    parts = GITHUB_URL.fullmatch(repository.rstrip("/"))
    if not parts:
        raise AssertionError(
            f"--repository must be https://github.com/owner/repo, not {repository!r}")
    owner, repo = parts.groups()
    try:
        with httpx.Client(timeout=25, follow_redirects=False, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "oryveta-smoke/0.1",
        }) as client:
            response = client.get(f"https://api.github.com/repos/{owner}/{repo}")
    except httpx.HTTPError as exception:
        raise AssertionError(
            f"This smoke test really downloads {repository}; reaching api.github.com "
            f"failed ({type(exception).__name__}). Run it on a host with outbound HTTPS "
            "access to github.com, or pass --repository with a reachable small public "
            "repository. The fetch is deliberately not stubbed.") from exception
    if response.status_code in {403, 429}:
        raise AssertionError(
            "api.github.com rate limited this host (HTTP "
            f"{response.status_code}). Wait for the unauthenticated quota to reset and "
            "re-run; the analysis step cannot be faked.")
    if response.is_error:
        raise AssertionError(
            f"api.github.com returned HTTP {response.status_code} for {repository}. "
            "Pass --repository with a reachable public repository.")
    info = response.json()
    if info.get("private") or info.get("size", 0) > 15000:
        raise AssertionError(
            f"{repository} is private or larger than the importer's 15 MB limit "
            f"(size {info.get('size', 0)} KB). Pass --repository with a smaller public "
            "repository.")
    print(f"Ready: {repository} is public, {info.get('size', 0)} KB, default branch "
          f"{info.get('default_branch')}; the archive fetch will be real", flush=True)


# ---------------------------------------------------------------------------
# Auth, clients and assertions
# ---------------------------------------------------------------------------

def admin_client(connection: dict, service_key: str) -> httpx.Client:
    """Administrative setup only. Nothing below the account fixtures uses this."""
    return httpx.Client(
        base_url=connection["API_URL"], trust_env=False, timeout=20,
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
    )


def create_account(admin: httpx.Client, suffix: str, name: str, designated: bool,
                   secrets: Secrets) -> Account:
    """Create one confirmed account with the Auth admin API.

    This is the administrative step the migration documents as out of scope for
    any RPC: only the service role can confirm an address, and only the service
    role can mark an account app_metadata.oryveta_role = 'factory_worker'. A
    project admin cannot promote a colleague's account by calling an RPC.
    """
    email = f"oryveta-{suffix}-{name}@example.test"
    password = f"Oryveta-{uuid.uuid4().hex}"
    payload: dict[str, object] = {"email": email, "password": password, "email_confirm": True}
    if designated:
        payload["app_metadata"] = {"oryveta_role": "factory_worker"}
    created = ok(admin.post("/auth/v1/admin/users", json=payload))
    metadata = created.get("app_metadata") or {}
    marker = metadata.get("oryveta_role")
    if designated and marker != "factory_worker":
        raise AssertionError(f"{name} was not designated as a factory worker service identity")
    if not designated and marker is not None:
        raise AssertionError(f"{name} must not carry the factory worker designation")
    if not created.get("email_confirmed_at"):
        raise AssertionError(f"{name} was created without a confirmed address")
    secrets.add(f"the {name} password", password)
    return Account(name=name, email=email, user_id=created["id"], password=password)


def password_session(connection: dict, account: Account, secrets: Secrets) -> dict:
    """An ordinary password grant: the same session a browser would receive."""
    with httpx.Client(base_url=connection["API_URL"], trust_env=False, timeout=20,
                      headers={"apikey": connection["PUBLISHABLE_KEY"]}) as client:
        response = client.post("/auth/v1/token", params={"grant_type": "password"},
                               json={"email": account.email, "password": account.password})
    if response.is_error:
        # The body can echo the submitted credential; report the status only.
        raise AssertionError(
            f"Password grant for {account.name} failed with HTTP {response.status_code}")
    session = response.json()
    if not session.get("access_token") or not session.get("refresh_token"):
        raise AssertionError(f"Auth returned no usable session for {account.name}")
    if session["user"]["id"] != account.user_id:
        raise AssertionError(f"Password grant returned another identity for {account.name}")
    secrets.add(f"a {account.name} access token", session["access_token"])
    secrets.add(f"a {account.name} refresh token", session["refresh_token"])
    return session


def api_client(connection: dict, session: dict) -> httpx.Client:
    return httpx.Client(
        base_url=connection["API_URL"], trust_env=False, timeout=20,
        headers={"apikey": connection["PUBLISHABLE_KEY"],
                 "Authorization": f"Bearer {session['access_token']}",
                 "Prefer": "return=representation"},
    )


def anonymous_client(connection: dict) -> httpx.Client:
    return httpx.Client(
        base_url=connection["API_URL"], trust_env=False, timeout=20,
        headers={"apikey": connection["PUBLISHABLE_KEY"]},
    )


def sign_in(connection: dict, account: Account, secrets: Secrets,
            resources: contextlib.ExitStack) -> httpx.Client:
    client = resources.enter_context(api_client(connection, password_session(
        connection, account, secrets)))
    if ok(client.get("/auth/v1/user"))["id"] != account.user_id:
        raise AssertionError(f"Session for {account.name} does not identify that account")
    return client


def sign_out(client: httpx.Client, label: str) -> None:
    """End the session the way a browser does, then close it for good."""
    response = client.post("/auth/v1/logout")
    if response.is_error and response.status_code not in {401, 403}:
        raise AssertionError(f"Sign-out for {label} failed: HTTP {response.status_code}")
    check = client.get("/auth/v1/user")
    if check.status_code not in {401, 403}:
        raise AssertionError(
            f"{label} session still answers after sign-out: HTTP {check.status_code}")
    client.close()
    if not client.is_closed:
        raise AssertionError(f"The {label} client is still open")


def ok(response: httpx.Response):
    if response.is_error:
        raise AssertionError(
            f"API {response.request.method} {response.request.url.path}: "
            f"{response.status_code} {response.text[:500]}")
    return response.json() if response.content else None


def rpc(client: httpx.Client, name: str, values: dict):
    return ok(client.post(f"/rest/v1/rpc/{name}", json=values))


def row(value):
    return value[0] if isinstance(value, list) else value


def one(rows, description: str) -> dict:
    if not isinstance(rows, list) or len(rows) != 1:
        count = len(rows) if isinstance(rows, list) else "a non-list result"
        raise AssertionError(f"Expected exactly one {description}, got {count}")
    return rows[0]


def refused(client: httpx.Client, name: str, values: dict, expected: str) -> str:
    """An RPC that must be refused, with the guard that fired named in the error."""
    response = client.post(f"/rest/v1/rpc/{name}", json=values)
    if not 400 <= response.status_code < 500:
        raise AssertionError(
            f"{name} was expected to be refused, got HTTP {response.status_code}: "
            f"{response.text[:300]}")
    body = response.json() if response.content else {}
    message = str(body.get("message", "")) if isinstance(body, dict) else ""
    if expected not in message:
        raise AssertionError(
            f"{name} refusal reason {message!r} does not name {expected!r}")
    return message


def denied_write(response: httpx.Response, description: str) -> None:
    if response.status_code not in {401, 403, 404, 405}:
        raise AssertionError(
            f"{description} was expected to be refused, got HTTP "
            f"{response.status_code}: {response.text[:300]}")


def wait_until(description: str, timeout: float, probe, interval: float = SLOW_POLL_SECONDS):
    deadline = time.monotonic() + timeout
    while True:
        value = probe()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f"Timed out after {timeout:.0f}s waiting for {description}")
        time.sleep(interval)


def expired(timestamp: str) -> bool:
    return datetime.fromisoformat(timestamp) <= datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Persisted state readers
# ---------------------------------------------------------------------------

def work_item(client: httpx.Client, work_item_id: str) -> dict:
    return one(ok(client.get("/rest/v1/work_items", params={
        "id": f"eq.{work_item_id}", "select": "*"})), f"work item {work_item_id}")


def newest_run(client: httpx.Client, work_item_id: str) -> dict | None:
    rows = ok(client.get("/rest/v1/factory_runs", params={
        "work_item_id": f"eq.{work_item_id}", "select": "*", "order": "attempt.desc"}))
    return rows[0] if rows else None


def attempt_run(client: httpx.Client, work_item_id: str, attempt: int) -> dict:
    return one(ok(client.get("/rest/v1/factory_runs", params={
        "work_item_id": f"eq.{work_item_id}", "attempt": f"eq.{attempt}", "select": "*"})),
        f"attempt {attempt} of work item {work_item_id}")


def run_events(client: httpx.Client, run_id: str) -> list[dict]:
    return ok(client.get("/rest/v1/factory_run_events", params={
        "run_id": f"eq.{run_id}", "select": "kind,phase,detail", "order": "id"}))


def assert_no_lease_token(run: dict) -> None:
    exposed = [key for key in run if "token" in key.lower()]
    if exposed:
        raise AssertionError(f"factory_runs select=* exposed {exposed}")
    if "lease_expires_at" not in run:
        raise AssertionError("factory_runs select=* did not return the liveness column")


# ---------------------------------------------------------------------------
# Worker process control
# ---------------------------------------------------------------------------

def worker_environment(home: Path) -> dict[str, str]:
    """A minimal environment for the worker CLI: nothing inherited but egress.

    The parent's environment is not passed through. Proxy and TLS trust
    variables are forwarded deliberately, because the worker has to reach
    github.com through the same egress path this script just probed.
    """
    environment = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(ENGINE),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "HOME": str(home),
        "TMPDIR": str(home),
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
    }
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY",
                 "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def work_root(home: Path) -> Path:
    """The worker's explicit snapshot root, so a leaked tree can be observed."""
    root = home / "factory-runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def run_directories(root: Path) -> list[Path]:
    """The per-run snapshot trees currently under a worker's work root."""
    return sorted(entry for entry in root.iterdir()
                  if entry.is_dir() and entry.name.startswith("oryveta-run-"))


def process_gone(pid: int) -> bool:
    """Whether a process this script does not own has really gone away."""
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    return False


def worker_command(credentials: Path, project_id: str, lease_seconds: int,
                   home: Path) -> list[str]:
    return [sys.executable, "-m", "oryveta_engine.factory_runtime",
            "--credentials", str(credentials), "--project", project_id,
            "--once", "--lease-seconds", str(lease_seconds),
            "--work-root", str(work_root(home))]


def assert_worker_imports(home: Path) -> None:
    """Fail early if the minimal worker environment cannot import the engine.

    The worker runs with a deliberately bare environment, so a dependency that
    is only reachable through the invoking shell's HOME or PYTHONPATH would
    otherwise surface much later as an opaque worker exit.
    """
    probe = subprocess.run(
        [sys.executable, "-c", "import oryveta_engine.factory_runtime"],
        cwd=str(home), env=worker_environment(home), capture_output=True, text=True,
        check=False)
    if probe.returncode:
        raise RuntimeError(
            "The worker environment cannot import oryveta_engine.factory_runtime with "
            f"{sys.executable}:\n{probe.stderr.strip()[:500]}\nInstall httpx for this "
            "interpreter (a virtualenv rather than a --user install) and re-run.")


def start_worker(credentials: Path, project_id: str, lease_seconds: int, home: Path,
                 log: Path) -> tuple[subprocess.Popen, object]:
    """Start the worker CLI as a real process in its own session.

    Its own session means a later kill reaches the worker and nothing beyond
    it, which is how a supervisor that signals only the entry process behaves.
    The analysis child leads a session of its own and has to stop itself.
    """
    handle = log.open("wb")
    process = subprocess.Popen(
        worker_command(credentials, project_id, lease_seconds, home),
        cwd=str(home), env=worker_environment(home), stdin=subprocess.DEVNULL,
        stdout=handle, stderr=subprocess.STDOUT, start_new_session=True,
    )
    return process, handle


def worker_output(log: Path, secrets: Secrets) -> str:
    text = log.read_text(encoding="utf-8", errors="replace")
    secrets.assert_absent("Worker output", text)
    return text


def kill_worker_process_group(process: subprocess.Popen) -> None:
    """SIGKILL the worker's own process group, and nothing beyond it.

    The analysis child leads its own group, so this never reaches it. That is
    the point: a killed worker is exactly the case where the child has to
    notice its parent is gone. This is not a stand-in for losing the host.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=30)


def analysis_children(worker_pid: int) -> list[int]:
    """Direct children of the worker: its supervised analysis child process."""
    result = subprocess.run([PGREP, "-P", str(worker_pid)], capture_output=True,
                            text=True, check=False)
    return [int(value) for value in result.stdout.split() if value.isdigit()]


def run_worker_to_completion(credentials: Path, project_id: str, lease_seconds: int,
                             home: Path, log: Path, secrets: Secrets) -> str:
    process, handle = start_worker(credentials, project_id, lease_seconds, home, log)
    try:
        code = process.wait(timeout=WORKER_EXIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        kill_worker_process_group(process)
        handle.close()
        raise AssertionError(
            f"Worker did not finish within {WORKER_EXIT_TIMEOUT:.0f}s\n"
            f"{secrets.scrub(log.read_text(encoding='utf-8', errors='replace'))}")
    finally:
        handle.close()
    output = worker_output(log, secrets)
    if code != 0:
        raise AssertionError(f"Worker exited with status {code}\n{secrets.scrub(output)}")
    return output


def wait_for_analysis_child(client: httpx.Client, work_item_id: str,
                            process: subprocess.Popen, log: Path, secrets: Secrets) -> int:
    """Wait until the supervised child exists, which means the attempt is analysing.

    The worker starts the child only after the heartbeat that records phase
    'analyzing', so a visible child is proof the attempt reached that phase.
    """
    def probe():
        children = analysis_children(process.pid)
        if children:
            return children
        if process.poll() is not None:
            raise AssertionError(
                "Worker exited before its analysis child could be observed\n"
                f"{secrets.scrub(log.read_text(encoding='utf-8', errors='replace'))}")
        run = newest_run(client, work_item_id)
        if run and run["status"] != "running":
            raise AssertionError(
                f"The attempt reached {run['status']} before its analysis child could be "
                "observed. The chosen repository analyses too quickly to exercise this "
                "path; pass --repository with a larger (still bounded) public repository.")
        return None

    return wait_until("the analysis child process to start", ANALYSIS_START_TIMEOUT,
                      probe, interval=FAST_POLL_SECONDS)[0]


def wait_for_children_gone(process: subprocess.Popen, description: str) -> None:
    wait_until(description, FENCE_TIMEOUT,
               lambda: not analysis_children(process.pid) or None,
               interval=FAST_POLL_SECONDS)


# ---------------------------------------------------------------------------
# Worker credential file
# ---------------------------------------------------------------------------

def write_worker_credentials(path: Path, connection: dict, project_id: str,
                             refresh_token: str) -> None:
    """Exactly what the worker needs, and nothing else.

    The Supabase origin, the publishable key, the project it serves and its own
    refresh token. No service key, no password and no access token: the worker
    has to perform a normal refresh-token grant to obtain one.
    """
    payload = json.dumps({
        "supabase_url": connection["API_URL"],
        "publishable_key": connection["PUBLISHABLE_KEY"],
        "project_id": project_id,
        "refresh_token": refresh_token,
    }, indent=2) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
    os.chmod(path, 0o600)


def credential_state(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise AssertionError(f"Worker credential file mode is {oct(mode)}, expected 0o600")
    return data


# ---------------------------------------------------------------------------
# Stage 1: project, membership and worker registration
# ---------------------------------------------------------------------------

def create_project_fixture(submitter: httpx.Client, owner: Account, workspace_id: str,
                           name: str, repository: str) -> dict:
    project = row(rpc(submitter, "create_project", {
        "p_workspace_id": workspace_id, "p_name": name,
        "p_brief": "Stage 2 durable work and events verified against the real local stack.",
        "p_kind": "evolve", "p_source_url": repository,
    }))
    if project["source_url"] != repository or project["created_by"] != owner.user_id:
        raise AssertionError("create_project did not persist the requested source identity")
    return project


def invite_and_accept(submitter: httpx.Client, member: httpx.Client, account: Account,
                      project_id: str, role: str) -> str:
    invitation = row(rpc(submitter, "invite_project_member", {
        "p_project_id": project_id, "p_recipient": account.email, "p_role": role}))
    pending = [entry for entry in rpc(member, "list_project_invitations", {})
               if entry["id"] == invitation["id"]]
    if not pending:
        raise AssertionError(
            f"{account.name} cannot see the invitation addressed to its confirmed address")
    accepted = row(rpc(member, "accept_project_invitation", {
        "p_invitation_id": invitation["id"]}))
    if accepted["project_id"] != project_id:
        raise AssertionError("accept_project_invitation returned another project")
    return invitation["id"]


def prove_registration_guards(submitter: httpx.Client, viewer: httpx.Client,
                              worker_b_client: httpx.Client, accounts: dict[str, Account],
                              project_id: str, suffix: str) -> None:
    owner = accounts["owner"]
    registration = row(rpc(submitter, "register_project_worker", {
        "p_project_id": project_id, "p_worker_user_id": accounts["worker-a"].user_id,
        "p_label": f"Smoke worker A {suffix}"}))
    if not registration["enabled"] or registration["worker_user_id"] != accounts["worker-a"].user_id:
        raise AssertionError("register_project_worker did not enable the requested identity")
    persisted = one(ok(submitter.get("/rest/v1/project_workers", params={
        "project_id": f"eq.{project_id}", "select": "id,worker_user_id,label,enabled"})),
        "worker registration")
    if persisted["id"] != registration["id"] or not persisted["enabled"]:
        raise AssertionError("the worker registration was not persisted as enabled")

    refused(submitter, "register_project_worker", {
        "p_project_id": project_id, "p_worker_user_id": owner.user_id,
        "p_label": f"Owner as worker {suffix}"},
        "a worker must be a separate service identity")
    refused(submitter, "register_project_worker", {
        "p_project_id": project_id, "p_worker_user_id": accounts["nonmember"].user_id,
        "p_label": f"Undesignated account {suffix}"},
        "not a provisioned factory worker service identity")
    refused(submitter, "register_project_worker", {
        "p_project_id": project_id, "p_worker_user_id": accounts["viewer"].user_id,
        "p_label": f"Project member {suffix}"},
        "not a provisioned factory worker service identity")
    refused(viewer, "register_project_worker", {
        "p_project_id": project_id, "p_worker_user_id": accounts["worker-a"].user_id,
        "p_label": f"Viewer attempt {suffix}"},
        "not allowed to manage this project")

    # A designated service identity that is also a human participant is refused
    # on the membership overlap, not merely on the designation marker. Worker B
    # is briefly made a project member to prove that branch, then removed so it
    # can serve as a worker identity later.
    invite_and_accept(submitter, worker_b_client, accounts["worker-b"], project_id, "viewer")
    refused(submitter, "register_project_worker", {
        "p_project_id": project_id, "p_worker_user_id": accounts["worker-b"].user_id,
        "p_label": f"Member worker {suffix}"},
        "a project or workspace member cannot also be a worker identity")
    rpc(submitter, "revoke_project_member", {
        "p_project_id": project_id, "p_user_id": accounts["worker-b"].user_id})
    if ok(worker_b_client.get("/rest/v1/projects", params={
            "id": f"eq.{project_id}", "select": "id"})) != []:
        raise AssertionError("revoke_project_member left the worker identity with project access")
    print("Proven: worker registration requires project admin authority and a designated "
          "service identity; the admin's own account, an undesignated account, a project "
          "member and a non-admin caller are each refused for the documented reason",
          flush=True)


# ---------------------------------------------------------------------------
# Stage 2: admission
# ---------------------------------------------------------------------------

def prove_admission(submitter: httpx.Client, viewer: httpx.Client, nonmember: httpx.Client,
                    project_id: str, repository: str, key: str) -> str:
    submission = row(rpc(submitter, "submit_repository_analysis", {
        "p_project_id": project_id, "p_idempotency_key": key}))
    if submission["status"] != "queued" or submission["replayed"]:
        raise AssertionError(f"submit_repository_analysis returned {submission}")
    if submission["source_url"] != repository or submission["kind"] != "repository_analysis":
        raise AssertionError("the submitted work item did not freeze the project source URL")
    if not re.fullmatch(r"[0-9a-f]{64}", submission["input_digest"]):
        raise AssertionError("the work item carries no canonical input digest")
    if submission["attempts"] != 0 or submission["max_attempts"] != 2:
        raise AssertionError("bounded attempts were not initialised as documented")
    work_item_id = submission["work_item_id"]

    persisted = work_item(submitter, work_item_id)
    if persisted["status"] != "queued" or persisted["project_id"] != project_id:
        raise AssertionError("the accepted work item was not committed as queued")
    if persisted["source_url"] != repository or persisted["cancel_requested_at"] is not None:
        raise AssertionError("the committed work item does not match the admitted request")
    if newest_run(submitter, work_item_id) is not None:
        raise AssertionError("a run existed before any worker claimed the work item")

    replay = row(rpc(submitter, "submit_repository_analysis", {
        "p_project_id": project_id, "p_idempotency_key": key}))
    if replay["work_item_id"] != work_item_id or not replay["replayed"]:
        raise AssertionError("an idempotent replay created a second work item")
    stored = ok(submitter.get("/rest/v1/work_items", params={
        "project_id": f"eq.{project_id}", "idempotency_key": f"eq.{key}", "select": "id"}))
    one(stored, f"work item for idempotency key {key}")

    refused(viewer, "submit_repository_analysis", {"p_project_id": project_id},
            "not allowed to submit work for this project")
    refused(nonmember, "submit_repository_analysis", {"p_project_id": project_id},
            "not allowed to submit work for this project")
    if ok(nonmember.get("/rest/v1/work_items", params={
            "project_id": f"eq.{project_id}", "select": "id"})) != []:
        raise AssertionError("a nonmember could read the project's work items")
    print(f"Proven: work item {work_item_id} is committed as queued before anything runs, "
          "its idempotent replay returns the same id, a read-only viewer cannot submit "
          "and a nonmember cannot even read", flush=True)
    return work_item_id


# ---------------------------------------------------------------------------
# Stage 3: the worker completes the work without any browser present
# ---------------------------------------------------------------------------

def prove_first_success(owner: httpx.Client, work_item_id: str, repository: str,
                        worker_a: Account) -> dict:
    item = work_item(owner, work_item_id)
    if item["status"] != "succeeded" or item["attempts"] != 1 or item["error_code"] is not None:
        raise AssertionError(f"work item did not succeed on the first attempt: {item}")
    run = newest_run(owner, work_item_id)
    if run is None or run["status"] != "succeeded" or run["attempt"] != 1:
        raise AssertionError(f"the newest run is not a first-attempt success: {run}")
    if run["worker_user_id"] != worker_a.user_id or run["phase"] != "done":
        raise AssertionError("the completed run was not attributed to the worker identity")
    assert_no_lease_token(run)

    summary = (run.get("result") or {}).get("summary")
    if not isinstance(summary, dict):
        raise AssertionError("the succeeded run stored no analysis summary")
    if not isinstance(summary.get("source_files_analyzed"), int) or summary["source_files_analyzed"] < 1:
        raise AssertionError(
            f"the stored summary analysed no source files: {summary.get('source_files_analyzed')!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(summary.get("input_fingerprint_sha256", ""))):
        raise AssertionError("the stored summary carries no analyzer fingerprint")
    if "findings_persisted" not in summary:
        raise AssertionError("the stored summary was not bounded by the worker")

    if run["source_ref"] != repository.removeprefix("https://"):
        raise AssertionError(f"source_ref {run['source_ref']!r} does not name the frozen source")
    if not re.fullmatch(r"[0-9a-f]{40}", str(run["source_commit"] or "")):
        raise AssertionError("the attempt recorded no resolved commit")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(run["source_digest"] or "")):
        raise AssertionError("the attempt recorded no archive digest")

    kinds = [event["kind"] for event in run_events(owner, run["id"])]
    for required in ("claimed", "source_resolved", "phase_changed", "succeeded"):
        if required not in kinds:
            raise AssertionError(f"the event log is missing {required}: {kinds}")

    print(f"Proven: the worker process completed work item {work_item_id} with "
          f"{summary['source_files_analyzed']} analysed source files from "
          f"{run['source_ref']} at commit {run['source_commit'][:12]}, with no browser "
          "session open; the event log records claimed, source_resolved, phase_changed and "
          "succeeded", flush=True)
    return run


def prove_credential_rotation(credentials: Path, before: dict, service_key: str,
                              output: str, secrets: Secrets) -> None:
    after = credential_state(credentials)
    if after["refresh_token"] == before["refresh_token"]:
        raise AssertionError("the worker did not rotate its refresh token")
    if not after.get("access_token"):
        raise AssertionError("the worker stored no access token from its refresh grant")
    if after["supabase_url"] != before["supabase_url"] or after["project_id"] != before["project_id"]:
        raise AssertionError("the rewritten credential file changed its service binding")
    text = credentials.read_text(encoding="utf-8")
    if service_key in text:
        raise AssertionError("the worker credential file contains the service key")
    secrets.add("the rotated worker refresh token", after["refresh_token"])
    secrets.add("the rotated worker access token", after["access_token"])
    secrets.assert_absent("Worker output", output)
    print("Proven: the worker refreshed its own Auth session with the ordinary "
          "refresh-token grant, rewrote its 0600 credential file with a rotated token, and "
          "printed no token, key or credential content", flush=True)


# ---------------------------------------------------------------------------
# Stage 4: scoped reads
# ---------------------------------------------------------------------------

def prove_scoped_reads(owner: httpx.Client, viewer: httpx.Client,
                       nonmember: httpx.Client, worker_a: httpx.Client,
                       anonymous: httpx.Client, project_id: str, second_project_id: str,
                       work_item_id: str, run_id: str) -> None:
    for label, client in (("submitter", owner), ("viewer", viewer)):
        item = work_item(client, work_item_id)
        if item["status"] != "succeeded":
            raise AssertionError(f"the {label} cannot read the completed work item")
        run = one(ok(client.get("/rest/v1/factory_runs", params={
            "id": f"eq.{run_id}", "select": "*"})), f"run {run_id} for the {label}")
        assert_no_lease_token(run)
        if not (run.get("result") or {}).get("summary"):
            raise AssertionError(f"the {label} cannot read the stored analysis result")
        if not run_events(client, run_id):
            raise AssertionError(f"the {label} cannot read the run's event log")

    for table in ("work_items", "factory_runs", "factory_run_events"):
        if ok(nonmember.get(f"/rest/v1/{table}", params={
                "project_id": f"eq.{project_id}", "select": "id"})) != []:
            raise AssertionError(f"a nonmember read {table}")
        denied = anonymous.get(f"/rest/v1/{table}", params={"select": "id"})
        if denied.status_code not in {401, 403}:
            raise AssertionError(
                f"anon was not refused on {table}: HTTP {denied.status_code} "
                f"{denied.text[:200]}")

    # The authenticated role holds SELECT only; mutation exists solely in the
    # RPCs, so a forgotten policy cannot turn into a write.
    denied_write(owner.post("/rest/v1/work_items", json={
        "project_id": project_id, "kind": "repository_analysis"}),
        "an owner insert into work_items")
    denied_write(owner.patch(f"/rest/v1/factory_runs?id=eq.{run_id}",
                             json={"status": "failed"}), "an owner update of factory_runs")
    denied_write(owner.delete(f"/rest/v1/factory_run_events?run_id=eq.{run_id}"),
                 "an owner delete of factory_run_events")
    denied_write(owner.patch(f"/rest/v1/project_workers?project_id=eq.{project_id}",
                             json={"enabled": False}), "an owner update of project_workers")

    # The fencing token lives in the unexposed `private` schema: PostgREST
    # serves only `public`, so there is no path to it at all.
    leases = owner.get("/rest/v1/factory_run_leases", params={"select": "*"})
    if leases.status_code != 404:
        raise AssertionError(
            f"private.factory_run_leases is reachable over PostgREST: HTTP "
            f"{leases.status_code} {leases.text[:200]}")

    if ok(worker_a.get("/rest/v1/work_items", params={
            "project_id": f"eq.{second_project_id}", "select": "id"})) != []:
        raise AssertionError("the worker identity read another project's work items")
    refused(worker_a, "claim_analysis_work",
            {"p_project_id": second_project_id, "p_lease_seconds": SUCCESS_LEASE_SECONDS},
            "worker identity is not registered for this project")
    served = ok(worker_a.get("/rest/v1/work_items", params={
        "project_id": f"eq.{project_id}", "select": "id"}))
    if not any(entry["id"] == work_item_id for entry in served):
        raise AssertionError("the worker identity cannot read the project it serves")
    print("Proven: RLS exposes the work item, run and events to the submitter and the "
          "viewer only, select=* on factory_runs returns no lease token, anon and every "
          "authenticated write are refused, private.factory_run_leases is unreachable, and "
          "the worker identity can neither read nor claim a project it is not registered "
          "for", flush=True)


# ---------------------------------------------------------------------------
# Stage 5: restart and reclaim
# ---------------------------------------------------------------------------

def prove_reclaim(owner: httpx.Client, credentials: Path, project_id: str, home: Path,
                  logs: Path, secrets: Secrets, work_item_id: str) -> None:
    process, handle = start_worker(credentials, project_id, RECLAIM_LEASE_SECONDS, home,
                                   logs / "worker-killed.log")
    killed_phase = "unknown"
    analysis_child = 0
    leaked: list[Path] = []
    started = time.monotonic()
    try:
        def probe():
            nonlocal killed_phase, analysis_child
            children = analysis_children(process.pid)
            if children:
                killed_phase = "analyzing"
                analysis_child = children[0]
                return True
            if process.poll() is not None:
                raise AssertionError(
                    "Worker exited before its attempt could be killed\n"
                    f"{secrets.scrub((logs / 'worker-killed.log').read_text(errors='replace'))}")
            run = newest_run(owner, work_item_id)
            if run is None:
                return None
            if run["status"] != "running":
                raise AssertionError(
                    f"The attempt reached {run['status']} before it could be killed; pass "
                    "--repository with a larger (still bounded) public repository.")
            # A slow archive fetch is a perfectly good moment to kill the
            # worker, and it keeps this step independent of network speed.
            if (run["phase"] == "fetching_source"
                    and time.monotonic() - started > FETCH_KILL_DELAY_SECONDS):
                killed_phase = "fetching_source"
                return True
            return None

        wait_until("a live first attempt to kill", ANALYSIS_START_TIMEOUT, probe,
                   interval=FAST_POLL_SECONDS)
        leaked = run_directories(work_root(home))
        kill_worker_process_group(process)
    finally:
        handle.close()
        if process.poll() is None:
            kill_worker_process_group(process)

    if not leaked:
        raise AssertionError(
            f"the live attempt had no snapshot directory under {work_root(home)}")
    if analysis_child:
        # Only the child's own parent-death check can end it now: its group was
        # never signalled and its supervisor is gone.
        wait_until(f"the orphaned analysis child {analysis_child} to stop itself",
                   FENCE_TIMEOUT, lambda: process_gone(analysis_child) or None,
                   interval=FAST_POLL_SECONDS)
    orphan = attempt_run(owner, work_item_id, 1)
    item = work_item(owner, work_item_id)
    if item["status"] != "running" or item["attempts"] != 1:
        raise AssertionError(f"the killed attempt did not leave the work item running: {item}")
    if orphan["status"] != "running" or orphan["result"] is not None:
        raise AssertionError(f"the killed attempt is not an orphaned running run: {orphan}")
    print(f"Proven: the worker's own process group was SIGKILLed while {killed_phase}; "
          f"its analysis child stopped itself, the snapshot tree it owned was left "
          f"behind, and work item {work_item_id} is still running with an orphaned "
          f"attempt 1 and no result", flush=True)

    # Bounded, explicit wait: the lease is RECLAIM_LEASE_SECONDS long and nothing
    # in the background expires it, so the next claim performs the transition.
    deadline = RECLAIM_LEASE_SECONDS + EXPIRY_SLACK_SECONDS + 10
    wait_until(f"the {RECLAIM_LEASE_SECONDS}s lease of the killed attempt to expire",
               deadline, lambda: expired(attempt_run(owner, work_item_id, 1)["lease_expires_at"]))
    time.sleep(EXPIRY_SLACK_SECONDS)
    if work_item(owner, work_item_id)["status"] != "running":
        raise AssertionError("the work item changed state without a worker claiming it")

    reclaim_output = run_worker_to_completion(
        credentials, project_id, SUCCESS_LEASE_SECONDS, home,
        logs / "worker-reclaim.log", secrets)
    if "reclaimed stale run directories: 1" not in reclaim_output:
        raise AssertionError(
            "the reclaiming worker did not sweep the killed attempt's snapshot "
            f"directory at startup\n{secrets.scrub(reclaim_output)}")
    still_there = [entry for entry in leaked if entry.exists()]
    if still_there:
        raise AssertionError(f"the killed attempt's snapshot tree survived: {still_there}")
    dead = attempt_run(owner, work_item_id, 1)
    if dead["status"] != "failed" or dead["error_code"] != "lease_expired" or dead["result"]:
        raise AssertionError(f"the expired attempt was not settled as lease_expired: {dead}")
    dead_kinds = [event["kind"] for event in run_events(owner, dead["id"])]
    for required in ("lease_expired", "retry_scheduled"):
        if required not in dead_kinds:
            raise AssertionError(f"the dead attempt is missing {required}: {dead_kinds}")
    retry = attempt_run(owner, work_item_id, 2)
    if retry["status"] != "succeeded" or not (retry.get("result") or {}).get("summary"):
        raise AssertionError(f"the reclaiming attempt did not complete the work: {retry}")
    if retry["id"] == dead["id"] or retry["source_digest"] is None:
        raise AssertionError("the reclaiming attempt did not record its own snapshot identity")
    if dead.get("source_commit") and retry.get("source_commit") != dead.get("source_commit"):
        raise AssertionError(
            "the reclaiming attempt analysed a different commit than the attempt it "
            f"retried: {retry.get('source_commit')} after {dead.get('source_commit')}")
    item = work_item(owner, work_item_id)
    if item["status"] != "succeeded" or item["attempts"] != 2 or item["error_code"] is not None:
        raise AssertionError(f"the reclaimed work item did not finish cleanly: {item}")
    print("Proven: a second worker process swept the dead attempt's snapshot tree at "
          "startup, reclaimed the expired attempt as attempt 2, recorded lease_expired "
          "and retry_scheduled for the dead attempt, re-fetched the pinned snapshot and "
          "completed the work item within its two bounded attempts", flush=True)


# ---------------------------------------------------------------------------
# Stage 6: cancellation terminates the attempt
# ---------------------------------------------------------------------------

def prove_cancellation(owner: httpx.Client, credentials: Path, project_id: str, home: Path,
                       logs: Path, secrets: Secrets, work_item_id: str) -> None:
    log = logs / "worker-cancelled.log"
    process, handle = start_worker(credentials, project_id, SUCCESS_LEASE_SECONDS, home, log)
    try:
        child = wait_for_analysis_child(owner, work_item_id, process, log, secrets)
        outcome = row(rpc(owner, "cancel_work_item", {"p_work_item_id": work_item_id}))
        if outcome["status"] != "cancelled" or outcome["already_terminal"]:
            raise AssertionError(f"cancel_work_item refused a live work item: {outcome}")
        if outcome["fenced_runs"] != 1:
            raise AssertionError(f"cancellation fenced {outcome['fenced_runs']} runs, expected 1")
        wait_for_children_gone(
            process, f"the analysis child {child} of the fenced attempt to disappear")
        try:
            code = process.wait(timeout=FENCE_TIMEOUT)
        except subprocess.TimeoutExpired:
            kill_worker_process_group(process)
            raise AssertionError(
                "the fenced worker did not exit\n"
                f"{secrets.scrub(log.read_text(encoding='utf-8', errors='replace'))}")
    finally:
        handle.close()
        if process.poll() is None:
            kill_worker_process_group(process)
    output = worker_output(log, secrets)
    if code != 0:
        raise AssertionError(f"the fenced worker exited with status {code}\n"
                             f"{secrets.scrub(output)}")

    item = work_item(owner, work_item_id)
    run = attempt_run(owner, work_item_id, 1)
    if item["status"] != "cancelled" or item["cancelled_by"] is None:
        raise AssertionError(f"the cancelled work item is not terminal: {item}")
    if run["status"] != "cancelled" or run["error_code"] != "cancelled":
        raise AssertionError(f"the fenced run was not cancelled: {run}")
    if run["result"] is not None:
        raise AssertionError("a fenced attempt published a result")
    events = run_events(owner, run["id"])
    kinds = [event["kind"] for event in events]
    if "succeeded" in kinds:
        raise AssertionError(f"a fenced attempt recorded success: {kinds}")
    if "cancelled" not in kinds:
        raise AssertionError(f"the cancellation was not recorded: {kinds}")
    phases = [event["phase"] for event in events]
    if "analyzing" not in phases:
        raise AssertionError(f"the cancelled attempt never reached analysis: {phases}")
    print(f"Proven: cancelling work item {work_item_id} while attempt 1 was analysing left "
          f"no analysis child (child {child} is gone), exited the worker cleanly without "
          "publishing, and settled the work item and its run as cancelled with no stored "
          "result", flush=True)


# ---------------------------------------------------------------------------
# Stage 7: a real lease token cannot publish after the fence
# ---------------------------------------------------------------------------

DENIED_RESULT = {
    "summary": {"source_files_analyzed": 0, "note": "late completion probe"},
    "findings": [],
}


def prove_denied_late_completion(owner: httpx.Client, worker_b: httpx.Client,
                                 project_id: str, work_item_id: str) -> None:
    claim = one(rpc(worker_b, "claim_analysis_work", {
        "p_project_id": project_id, "p_lease_seconds": SUCCESS_LEASE_SECONDS}),
        "claimed attempt for the second worker identity")
    if claim["work_item_id"] != work_item_id or claim["attempt"] != 1:
        raise AssertionError(f"the second worker identity did not claim the work item: {claim}")
    if not claim.get("lease_token"):
        raise AssertionError("the claim returned no lease token to its own worker")
    outcome = row(rpc(owner, "cancel_work_item", {"p_work_item_id": work_item_id}))
    if outcome["fenced_runs"] != 1:
        raise AssertionError(f"cancellation did not fence the claimed run: {outcome}")

    beat = row(rpc(worker_b, "heartbeat_analysis_run", {
        "p_run_id": claim["run_id"], "p_lease_token": claim["lease_token"],
        "p_phase": "analyzing", "p_lease_seconds": SUCCESS_LEASE_SECONDS}))
    if beat["lease_valid"] or beat["reason"] != "cancelled":
        raise AssertionError(f"a fenced heartbeat was not reported as cancelled: {beat}")
    late = row(rpc(worker_b, "finish_analysis_run", {
        "p_run_id": claim["run_id"], "p_lease_token": claim["lease_token"],
        "p_result": DENIED_RESULT}))
    if late["accepted"] or late["reason"] != "cancelled":
        raise AssertionError(f"a fenced completion was accepted: {late}")
    run = attempt_run(owner, work_item_id, 1)
    if run["status"] != "cancelled" or run["result"] is not None:
        raise AssertionError(f"the fenced run stored a late result: {run}")
    if work_item(owner, work_item_id)["status"] != "cancelled":
        raise AssertionError("the cancelled work item was revived by a late completion")
    print("Proven: a genuine, unexpired lease token held across a cancellation can neither "
          "heartbeat nor publish; finish_analysis_run answers accepted=false reason=cancelled "
          "and no result lands", flush=True)


# ---------------------------------------------------------------------------
# Stage 8: revocation fences a live run
# ---------------------------------------------------------------------------

def prove_revocation(owner: httpx.Client, worker_b: httpx.Client, worker_b_id: str,
                     project_id: str, work_item_id: str) -> None:
    claim = one(rpc(worker_b, "claim_analysis_work", {
        "p_project_id": project_id, "p_lease_seconds": SUCCESS_LEASE_SECONDS}),
        "claimed attempt for the worker identity about to be revoked")
    if claim["work_item_id"] != work_item_id:
        raise AssertionError(f"the worker identity did not claim the work item: {claim}")
    revocation = row(rpc(owner, "revoke_project_worker", {
        "p_project_id": project_id, "p_worker_user_id": worker_b_id}))
    if revocation["enabled"] or revocation["fenced_runs"] != 1:
        raise AssertionError(f"revocation did not fence the live run: {revocation}")

    run = attempt_run(owner, work_item_id, 1)
    if run["status"] != "cancelled" or run["error_code"] != "worker_revoked" or run["result"]:
        raise AssertionError(f"the revoked worker's run was not fenced: {run}")
    refused(worker_b, "claim_analysis_work",
            {"p_project_id": project_id, "p_lease_seconds": SUCCESS_LEASE_SECONDS},
            "worker identity is not registered for this project")
    beat = row(rpc(worker_b, "heartbeat_analysis_run", {
        "p_run_id": claim["run_id"], "p_lease_token": claim["lease_token"],
        "p_lease_seconds": SUCCESS_LEASE_SECONDS}))
    if beat["lease_valid"] or beat["reason"] != "worker_not_registered":
        raise AssertionError(f"a revoked heartbeat was not refused: {beat}")
    if ok(worker_b.get("/rest/v1/work_items", params={
            "project_id": f"eq.{project_id}", "select": "id"})) != []:
        raise AssertionError("a revoked worker identity can still read the project")

    requeued = work_item(owner, work_item_id)
    if requeued["status"] != "queued" or requeued["error_code"] != "worker_revoked":
        raise AssertionError(f"the fenced work item was not requeued for retry: {requeued}")
    final = row(rpc(owner, "cancel_work_item", {"p_work_item_id": work_item_id}))
    if final["status"] != "cancelled" or final["already_terminal"]:
        raise AssertionError(f"the requeued work item could not be cancelled: {final}")
    print("Proven: revoking a worker registration immediately fenced its live run as "
          "worker_revoked, requeued the bounded work item, and left that identity unable to "
          "claim, heartbeat or read the project", flush=True)


# ---------------------------------------------------------------------------
# Stage 9: a reused idempotency key cannot change the frozen input
# ---------------------------------------------------------------------------

def prove_frozen_input(submitter: httpx.Client, project: dict, project_id: str, key: str,
                       repository: str) -> None:
    # Structurally valid and guaranteed different from the frozen source, but
    # never fetched: admission is refused before any work item can exist.
    other = f"{repository}-alternate"
    rpc(submitter, "update_project", {
        "p_project_id": project_id, "p_name": project["name"], "p_brief": project["brief"],
        "p_source_url": other})
    refused(submitter, "submit_repository_analysis",
            {"p_project_id": project_id, "p_idempotency_key": key},
            "idempotency key already used for a different input")
    restored = row(rpc(submitter, "update_project", {
        "p_project_id": project_id, "p_name": project["name"], "p_brief": project["brief"],
        "p_source_url": repository}))
    if restored["source_url"] != repository:
        raise AssertionError("the project source URL was not restored")
    print("Proven: reusing an idempotency key after the project's source URL changed is "
          "refused instead of silently replaying a different input", flush=True)


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------

def exercise(connection: dict, repository: str, service_key: str, home: Path) -> None:
    suffix = uuid.uuid4().hex[:12]
    secrets = Secrets()
    secrets.add("the stack service key", service_key)
    logs = home / "logs"
    logs.mkdir()
    credentials = home / "worker-a.json"

    with contextlib.ExitStack() as resources:
        admin = resources.enter_context(admin_client(connection, service_key))
        accounts = {name: create_account(admin, suffix, name, designated, secrets)
                    for name, designated in (("owner", False), ("viewer", False),
                                             ("nonmember", False), ("worker-a", True),
                                             ("worker-b", True))}
        print("Ready: five confirmed Auth accounts created administratively; only the two "
              "worker identities carry app_metadata.oryveta_role=factory_worker", flush=True)

        # The submitter's session is a browser-equivalent session and is closed
        # before any worker runs.
        submitter = sign_in(connection, accounts["owner"], secrets, resources)
        viewer = sign_in(connection, accounts["viewer"], secrets, resources)
        nonmember = sign_in(connection, accounts["nonmember"], secrets, resources)
        worker_a_client = sign_in(connection, accounts["worker-a"], secrets, resources)
        worker_b_client = sign_in(connection, accounts["worker-b"], secrets, resources)
        anonymous = resources.enter_context(anonymous_client(connection))

        workspace = row(ok(submitter.post("/rest/v1/workspaces", json={
            "name": "Durable factory runtime", "slug": f"factory-{suffix}",
            "created_by": accounts["owner"].user_id})))
        project = create_project_fixture(submitter, accounts["owner"], workspace["id"],
                                         f"Durable runtime {suffix}", repository)
        project_id = project["id"]
        invite_and_accept(submitter, viewer, accounts["viewer"], project_id, "viewer")
        if one(ok(viewer.get("/rest/v1/projects", params={
                "id": f"eq.{project_id}", "select": "id"})), "project for the viewer")["id"] != project_id:
            raise AssertionError("the accepted viewer cannot read the project")
        if ok(nonmember.get("/rest/v1/projects", params={
                "id": f"eq.{project_id}", "select": "id"})) != []:
            raise AssertionError("a nonmember can read the project")
        second = create_project_fixture(submitter, accounts["owner"], workspace["id"],
                                        f"Second project {suffix}", repository)
        print(f"Proven: project {project_id} froze {repository} as its analysable source, "
              "the invited read-only member accepted through the verified-email path and a "
              "nonmember sees nothing", flush=True)

        prove_registration_guards(submitter, viewer, worker_b_client, accounts, project_id,
                                  suffix)

        first_key = f"smoke-{suffix}-first"
        work_item_id = prove_admission(submitter, viewer, nonmember, project_id, repository,
                                       first_key)

        # A separate password grant, so the credential file's refresh token is
        # independent of the session this script uses to read as the worker.
        worker_file_session = password_session(connection, accounts["worker-a"], secrets)
        write_worker_credentials(credentials, connection, project_id,
                                 worker_file_session["refresh_token"])
        before = credential_state(credentials)
        if stat.S_IMODE(home.stat().st_mode) != 0o700:
            raise AssertionError("the worker credential directory is not 0700")
        if before.get("access_token") or service_key in credentials.read_text(encoding="utf-8"):
            raise AssertionError("the worker credential file carries more than a refresh token")

        sign_out(submitter, "the submitter")
        print("Proven: the submitting session is signed out and unusable before the worker "
              "starts; the accepted work item survives it", flush=True)

        output = run_worker_to_completion(credentials, project_id, SUCCESS_LEASE_SECONDS,
                                          home, logs / "worker-first.log", secrets)
        owner = sign_in(connection, accounts["owner"], secrets, resources)
        run = prove_first_success(owner, work_item_id, repository, accounts["worker-a"])
        prove_credential_rotation(credentials, before, service_key, output, secrets)

        second_item = row(rpc(owner, "submit_repository_analysis",
                              {"p_project_id": second["id"]}))["work_item_id"]
        prove_scoped_reads(owner, viewer, nonmember, worker_a_client, anonymous,
                           project_id, second["id"], work_item_id, run["id"])
        rpc(owner, "cancel_work_item", {"p_work_item_id": second_item})

        reclaim_item = row(rpc(owner, "submit_repository_analysis", {
            "p_project_id": project_id, "p_idempotency_key": f"smoke-{suffix}-reclaim"}))
        prove_reclaim(owner, credentials, project_id, home, logs, secrets,
                      reclaim_item["work_item_id"])

        cancel_item = row(rpc(owner, "submit_repository_analysis", {
            "p_project_id": project_id, "p_idempotency_key": f"smoke-{suffix}-cancel"}))
        prove_cancellation(owner, credentials, project_id, home, logs, secrets,
                           cancel_item["work_item_id"])

        # Worker identity B serves the same project for the next two stages, which
        # claim over the RPCs so this script legitimately holds a real lease token.
        row(rpc(owner, "register_project_worker", {
            "p_project_id": project_id, "p_worker_user_id": accounts["worker-b"].user_id,
            "p_label": f"Smoke worker B {suffix}"}))
        late_item = row(rpc(owner, "submit_repository_analysis", {
            "p_project_id": project_id, "p_idempotency_key": f"smoke-{suffix}-late"}))
        prove_denied_late_completion(owner, worker_b_client, project_id,
                                     late_item["work_item_id"])

        revoke_item = row(rpc(owner, "submit_repository_analysis", {
            "p_project_id": project_id, "p_idempotency_key": f"smoke-{suffix}-revoke"}))
        prove_revocation(owner, worker_b_client, accounts["worker-b"].user_id, project_id,
                         revoke_item["work_item_id"])

        prove_frozen_input(owner, project, project_id, first_key, repository)

        after = credential_state(credentials)
        if after["refresh_token"] == before["refresh_token"]:
            raise AssertionError("the worker credential file was never rotated")
        print("Passed: real password-grant sessions, project-authorized admission, "
              "browser-independent completion by a separate worker process with a rotating "
              "credential file, a genuine GitHub snapshot analysed in a child process, "
              "scoped RLS reads without lease tokens, SIGKILL reclaim as a bounded second "
              "attempt, cancellation that leaves no child and publishes nothing, a refused "
              "late completion holding a real lease token, and revocation that fences a "
              "live run.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connections", default="-",
                        help="Local Supabase status JSON; '-' reads stdin")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY,
                        help="Small public https://github.com/owner/repo to analyse for real")
    parser.add_argument("--skip-sql", action="store_true",
                        help="Reuse an already bootstrapped isolated stack")
    parser.add_argument("--sql-tests", action="store_true",
                        help="Also run supabase/tests/*.sql after the prerequisite files")
    args = parser.parse_args()
    if not PGREP:
        raise RuntimeError(
            "pgrep is required to observe the worker's analysis child process; install "
            "procps or run this on a host that provides it")
    status = (json.load(sys.stdin) if args.connections == "-"
              else json.loads(Path(args.connections).read_text()))
    # `supabase start --output-format json` nests the values under 'env';
    # `supabase status --output-format json` emits them at the top level.
    connection = status["env"] if isinstance(status.get("env"), dict) else status
    for key in ("API_URL", "DB_URL"):
        if key not in connection:
            raise RuntimeError(f"The Supabase status JSON has no {key}")
        connection[key] = loopback(connection[key])
    if not connection.get("PUBLISHABLE_KEY"):
        raise RuntimeError("The Supabase status JSON has no PUBLISHABLE_KEY")
    service_key = connection.get("SERVICE_ROLE_KEY") or connection.get("SECRET_KEY")
    if not service_key:
        raise RuntimeError(
            "The Supabase status JSON has no SERVICE_ROLE_KEY (or SECRET_KEY); the Auth "
            "admin API is needed to create confirmed accounts and to designate the worker "
            "service identities")
    if not ENGINE.is_dir():
        raise RuntimeError(f"The engine package is missing at {ENGINE}")
    if not args.skip_sql:
        apply_sql(connection, args.sql_tests)
    repository = args.repository.rstrip("/")
    assert_github_reachable(repository)
    with tempfile.TemporaryDirectory(prefix="oryveta-factory-smoke-") as directory:
        home = Path(directory)
        os.chmod(home, 0o700)
        assert_worker_imports(home)
        exercise(connection, repository, service_key, home)


if __name__ == "__main__":
    main()
