"""Exercise real local Supabase email auth, RLS, invitations, and the built Studio.

No request interception, fake login, or production mutations. Pass JSON from
`supabase status --output-format json` on stdin. This script refuses non-loopback
service endpoints. Supabase CLI 2.121.0 and the repository's local config supply
PostgreSQL, Auth, PostgREST, and Mailpit. Requires httpx and Playwright.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import uuid

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "apps/web/studio"
ORIGIN = "http://127.0.0.1:4173"


def loopback(url: str) -> str:
    if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Auth smoke only accepts isolated loopback services")
    return url.rstrip("/")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.urls.extend(value for key, value in attrs if key == "href" and value)


def apply_sql(connection: dict) -> None:
    database = loopback(connection["DB_URL"])
    binary = shutil.which("psql")
    if not binary:
        home = Path(os.environ.get("SUPABASE_HOME", Path.home() / ".supabase"))
        matches = list((home / "cache/stack").glob("**/bin/psql"))
        if len(matches) != 1:
            raise RuntimeError("Set PATH to the test stack's PostgreSQL bin directory")
        binary = str(matches[0])
    # Explicit order, never a glob: every file here builds on the ones before
    # it, and an alphabetical sweep of supabase/migrations would load them in
    # the wrong order. The transactional SQL regressions come last; each one
    # rolls its own fixtures back.
    files = [ROOT / relative for relative in (
        "supabase/schema.sql",
        "supabase/migrations/private_chats_and_explicit_sharing.sql",
        "supabase/migrations/projects_and_project_membership.sql",
        "supabase/migrations/durable_factory_runtime.sql",
        "supabase/migrations/retained_attribution_and_lease_clock.sql",
    )]
    files.extend(sorted((ROOT / "supabase/tests").glob("*.sql")))
    for path in files:
        result = subprocess.run(
            [binary, "--no-psqlrc", "--dbname", database, "--set", "ON_ERROR_STOP=1", "--file", str(path)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise RuntimeError(f"SQL failed: {path.name}\n{result.stderr}")
        print(f"SQL passed: {path.relative_to(ROOT)}", flush=True)
    subprocess.run(
        [binary, "--no-psqlrc", "--dbname", database, "--set", "ON_ERROR_STOP=1", "--command", "NOTIFY pgrst, 'reload schema'"],
        check=True, capture_output=True, text=True,
    )


@contextlib.contextmanager
def studio(connection: dict):
    with tempfile.TemporaryDirectory(prefix="oryveta-auth-build-") as directory:
        env = dict(os.environ)
        env.update(VITE_SUPABASE_URL=connection["API_URL"], VITE_SUPABASE_PUBLISHABLE_KEY=connection["PUBLISHABLE_KEY"])
        subprocess.run(
            ["npm", "run", "build", "--", "--outDir", directory],
            cwd=STUDIO, env=env, check=True,
        )
        with tempfile.TemporaryFile(mode="w+") as logs:
            process = subprocess.Popen(
                ["node", "node_modules/vite/bin/vite.js", "preview", "--host", "127.0.0.1", "--port", "4173", "--strictPort", "--outDir", directory],
                cwd=STUDIO, env=env, stdout=logs, stderr=logs,
            )
            try:
                with httpx.Client(trust_env=False, timeout=1) as client:
                    for _ in range(100):
                        if process.poll() is not None:
                            logs.seek(0)
                            raise RuntimeError(logs.read())
                        try:
                            if client.get(ORIGIN).status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Built Studio did not become ready")
                yield
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def email_link(mail: httpx.Client, address: str, api_url: str) -> str:
    for _ in range(100):
        response = mail.get("/api/v1/messages")
        response.raise_for_status()
        for message in response.json()["messages"]:
            if not any(recipient["Address"].lower() == address for recipient in message["To"]):
                continue
            detail = mail.get(f"/api/v1/message/{message['ID']}")
            detail.raise_for_status()
            parser = Links()
            parser.feed(detail.json()["HTML"])
            for url in parser.urls:
                if urlsplit(url).netloc == urlsplit(api_url).netloc and urlsplit(url).path == "/auth/v1/verify":
                    return url
        time.sleep(0.2)
    raise RuntimeError("Real Auth email did not arrive in local Mailpit")


def sign_in(page, mail: httpx.Client, api_url: str, address: str) -> dict:
    page.goto(f"{ORIGIN}/sign-in")
    page.get_by_label("Your work email").fill(address)
    page.get_by_role("button", name="Continue with email", exact=True).click()
    # Mail applications normally open a new tab, not the requesting tab.
    verification = page.context.new_page()
    try:
        verification.goto(email_link(mail, address, api_url))
        expect(verification.get_by_role("button", name="Sign out", exact=True)).to_be_visible(timeout=20000)
    finally:
        verification.close()
    page.reload()
    expect(page.get_by_role("button", name="Sign out", exact=True)).to_be_visible(timeout=20000)
    session = page.evaluate("""() => {
      const key = Object.keys(localStorage).find(key => key.endsWith('-auth-token'));
      return key ? JSON.parse(localStorage.getItem(key)) : null;
    }""")
    if not session or not session.get("access_token"):
        raise RuntimeError("Real authenticated session was not persisted")
    return session


def api_client(connection: dict, session: dict) -> httpx.Client:
    return httpx.Client(
        base_url=connection["API_URL"], trust_env=False, timeout=15,
        headers={"apikey": connection["PUBLISHABLE_KEY"], "Authorization": f"Bearer {session['access_token']}", "Prefer": "return=representation"},
    )


def ok(response: httpx.Response):
    if response.is_error:
        raise AssertionError(f"API {response.request.method} {response.request.url.path}: {response.status_code} {response.text[:500]}")
    return response.json() if response.content else None


def rpc(client: httpx.Client, name: str, values: dict):
    return ok(client.post(f"/rest/v1/rpc/{name}", json=values))


def row(value):
    return value[0] if isinstance(value, list) else value


def click_rpc(page, button_name: str, method: str):
    with page.expect_response(lambda response: urlsplit(response.url).path == f"/rest/v1/rpc/{method}") as pending:
        page.get_by_role("button", name=button_name, exact=True).click()
    response = pending.value
    if not response.ok:
        raise AssertionError(f"Browser RPC {method}: {response.status} {response.text()[:500]}")


def open_project(page, name: str):
    page.goto(f"{ORIGIN}/workspace/projects")
    page.get_by_role("button", name=re.compile(f"^{re.escape(name)}")).click()
    expect(page.get_by_label("Project name", exact=True)).to_have_value(name)


def visit_data_page(page, path: str, table: str):
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and urlsplit(response.url).path == f"/rest/v1/{table}"
    ) as pending:
        page.goto(f"{ORIGIN}{path}")
    response = pending.value
    if not response.ok:
        raise AssertionError(f"Page data {table}: HTTP {response.status}")
    expect(page.get_by_role("heading", level=1)).to_be_visible()
    expect(page.get_by_role("alert")).to_have_count(0)
    return response.json()


def exercise(connection: dict, evidence: Path):
    suffix = uuid.uuid4().hex[:12]
    addresses = [f"oryveta-{suffix}-{name}@example.test" for name in ("owner", "member", "guest")]
    with httpx.Client(base_url=connection["MAILPIT_URL"], trust_env=False, timeout=10) as mail, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        pages = []
        browser_errors = []
        try:
            contexts = [browser.new_context(viewport={"width": 1280, "height": 900}) for _ in addresses]
            for context in contexts:
                context.on("page", lambda page: page.on("pageerror", lambda error: browser_errors.append(str(error))))
            pages = [context.new_page() for context in contexts]
            sessions = [sign_in(page, mail, connection["API_URL"], address) for page, address in zip(pages, addresses)]
            with contextlib.ExitStack() as resources:
                owner, member, guest = [resources.enter_context(api_client(connection, session)) for session in sessions]
                for client, session in zip((owner, member, guest), sessions):
                    assert ok(client.get("/auth/v1/user"))["id"] == session["user"]["id"]
                owner_id, member_id, guest_id = [session["user"]["id"] for session in sessions]
                workspace = row(ok(owner.post("/rest/v1/workspaces", json={"name": "Auth verification", "slug": f"auth-{suffix}", "created_by": owner_id})))
                project_name = f"Private project {suffix}"
                pages[0].goto(f"{ORIGIN}/workspace/projects")
                pages[0].get_by_label("Workspace", exact=True).select_option(workspace["id"])
                pages[0].get_by_label("Project name", exact=True).fill(project_name)
                pages[0].get_by_label("What is this project for?", exact=True).fill("A confidential project brief used to verify actual authorization.")
                click_rpc(pages[0], "Create project", "create_project")
                project = row(ok(owner.get("/rest/v1/projects", params={"name": f"eq.{project_name}", "select": "*"})))
                project_path = f"/rest/v1/projects?id=eq.{project['id']}&select=*"
                assert ok(member.get(project_path)) == []
                assert ok(guest.get(project_path)) == []
                pages[0].get_by_label("Recipient", exact=True).fill(addresses[1])
                pages[0].get_by_label("Role", exact=True).select_option("viewer")
                click_rpc(pages[0], "Send invitation", "invite_project_member")
                invitation = row(rpc(member, "list_project_invitations", {}))
                assert ok(member.get(project_path)) == [], "Pending invitation granted project access"
                pages[1].goto(f"{ORIGIN}/workspace/projects")
                click_rpc(pages[1], f"Accept invitation to {project_name}", "accept_project_invitation")
                assert row(ok(member.get(project_path)))["id"] == project["id"]
                assert ok(member.get(f"/rest/v1/workspaces?id=eq.{workspace['id']}&select=*")) == [], "Project invite granted workspace access"
                denied = member.post("/rest/v1/rpc/update_project", json={"p_project_id": project["id"], "p_name": "Unauthorized edit", "p_brief": "Denied viewer edit", "p_source_url": None})
                assert 400 <= denied.status_code < 500, denied.text
                assert row(ok(owner.get(project_path)))["name"] == project_name
                pages[0].get_by_label("What is this project for?", exact=True).fill("Owner update retained without changing membership or workspace.")
                click_rpc(pages[0], "Save project", "update_project")
                assert row(ok(owner.get(project_path)))["brief"] == "Owner update retained without changing membership or workspace."
                for page in pages[:2]:
                    open_project(page, project_name)
                assert visit_data_page(pages[2], "/workspace/projects", "projects") == []
                expect(pages[2].get_by_text(project_name, exact=True)).to_have_count(0)
                expect(pages[1].get_by_role("button", name="Save project", exact=True)).to_have_count(0)
                pages[1].screenshot(path=str(evidence / "project-viewer.png"), full_page=True)

                chat = row(ok(owner.post("/rest/v1/chats", json={"owner_id": owner_id, "workspace_id": workspace["id"], "project_id": project["id"], "title": f"Private session {suffix}"})))
                chat_path = f"/rest/v1/chats?id=eq.{chat['id']}&select=*"
                assert ok(member.get(chat_path)) == [], "Project membership exposed a private session"
                share = row(ok(owner.post("/rest/v1/chat_shares", json={"chat_id": chat["id"], "invited_by": owner_id, "recipient_email": addresses[2], "permission": "viewer"})))
                assert ok(guest.get(chat_path)) == []
                ok(guest.patch(f"/rest/v1/chat_shares?id=eq.{share['id']}", json={"status": "accepted", "accepted_by": guest_id, "accepted_at": datetime.now(timezone.utc).isoformat()}))
                assert row(ok(guest.get(chat_path)))["id"] == chat["id"]
                assert ok(guest.get(project_path)) == [], "Session sharing exposed the project"
                denied = guest.post("/rest/v1/chat_messages", json={"chat_id": chat["id"], "author_id": guest_id, "role": "user", "content": "Viewer must not append messages"})
                assert denied.status_code in {401, 403}, denied.text
                pages[2].set_viewport_size({"width": 390, "height": 844})
                pages[2].goto(f"{ORIGIN}/workspace/chats")
                expect(pages[2].get_by_text(chat["title"], exact=True).first).to_be_visible(timeout=15000)
                assert pages[2].evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                pages[2].screenshot(path=str(evidence / "shared-session-mobile.png"), full_page=True)

                open_project(pages[0], project_name)
                click_rpc(pages[0], f"Remove account {member_id[:8]}… from this project", "revoke_project_member")
                assert ok(member.get(project_path)) == []
                replay = member.post("/rest/v1/rpc/accept_project_invitation", json={"p_invitation_id": invitation["id"]})
                assert replay.status_code in {200, 400, 403, 404, 409}
                assert ok(member.get(project_path)) == [], "Acceptance replay restored revoked membership"
                assert visit_data_page(pages[1], "/workspace/projects", "projects") == []
                expect(pages[1].get_by_text(project_name, exact=True)).to_have_count(0)

                # A deliberately re-invited admin may remove their own grant.
                # The open page must immediately discard the editable project.
                admin_invitation = row(rpc(owner, "invite_project_member", {
                    "p_project_id": project["id"], "p_recipient": addresses[1], "p_role": "admin",
                }))
                rpc(member, "accept_project_invitation", {"p_invitation_id": admin_invitation["id"]})
                open_project(pages[1], project_name)
                click_rpc(pages[1], f"Remove account {member_id[:8]}… from this project", "revoke_project_member")
                expect(pages[1].get_by_role("button", name="Save project", exact=True)).to_have_count(0)
                expect(pages[1].get_by_text(project_name, exact=True)).to_have_count(0)
                assert ok(member.get(project_path)) == []
                ok(owner.delete(f"/rest/v1/chat_shares?id=eq.{share['id']}"))
                assert ok(guest.get(chat_path)) == []
                assert visit_data_page(pages[2], "/workspace/chats", "chats") == []
                expect(pages[2].get_by_text(chat["title"], exact=True)).to_have_count(0)
                pages[0].get_by_role("button", name="Sign out", exact=True).click()
                expect(pages[0].get_by_role("button", name="Sign out", exact=True)).to_have_count(0)
                pages[0].goto(f"{ORIGIN}/workspace/projects")
                expect(pages[0].get_by_role("button", name="Return to sign in", exact=True)).to_be_visible()
                expect(pages[0].get_by_text(project_name, exact=True)).to_have_count(0)
                assert not browser_errors, browser_errors
                print("Passed: real new-tab email/PKCE login, reload, project invite/accept/viewer denial, private-session isolation, session-only sharing, revoke/replay/self-removal, sign-out, desktop/mobile rendering.", flush=True)
        except Exception:
            for index, page in enumerate(pages):
                if not page.is_closed():
                    page.screenshot(path=str(evidence / f"failure-user-{index}.png"), full_page=True)
            raise
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connections", default="-", help="Local Supabase status JSON; '-' reads stdin")
    parser.add_argument("--evidence", default="/tmp/oryveta-auth-evidence")
    parser.add_argument("--skip-sql", action="store_true", help="Reuse an already bootstrapped isolated stack while iterating on browser failures")
    args = parser.parse_args()
    status = json.load(sys.stdin) if args.connections == "-" else json.loads(Path(args.connections).read_text())
    connection = status["env"]
    for key in ("API_URL", "DB_URL", "MAILPIT_URL"):
        connection[key] = loopback(connection[key])
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    if not args.skip_sql:
        apply_sql(connection)
    with studio(connection):
        exercise(connection, evidence)


if __name__ == "__main__":
    main()
