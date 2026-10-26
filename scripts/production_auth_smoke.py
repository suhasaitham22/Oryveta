"""Opt-in production authorization smoke using real, temporary Auth users.

By default, creates three confirmed test identities with the Auth admin API,
obtains normal password-grant sessions, and exercises the deployed UI/RLS.
This does NOT claim email delivery or GitHub-consent coverage; those are separate
login checks. No auth responses are mocked, no test endpoint is added to the app,
and the administrative key is never placed in a browser. Temporary users and
their application rows are removed by ID in finally; provider audit logs may remain.

With --runtime, adds a worker and successor identity, submits a production
analysis, runs one temporary local worker, and verifies result download,
cancellation, revocation and retained attribution. This is not always-on hosting.

Connection JSON comes from stdin and must include project_ref, API_URL,
PUBLISHABLE_KEY and SERVICE_ROLE_KEY. A matching --confirm-project is required.
Never commit that JSON or record a browser trace containing authenticated state.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import uuid

import httpx
from playwright.sync_api import sync_playwright, expect

import auth_ui_smoke as ui

SITE = "https://oryveta.vercel.app"
PROJECT = "nydtmiseclkwauiepqxn"
ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/pallets/click"


def checked(response, operation):
    if response.is_error:
        raise RuntimeError(f"{operation} failed: HTTP {response.status_code}")
    return response.json() if response.content else None


def _create_identity(admin, connection, suffix, label, created, email=None):
    email = email or f"oryveta-release-{suffix}-{label}@example.invalid"
    if not email.startswith(f"oryveta-release-{suffix}-") or not email.endswith("@example.invalid"):
        raise ValueError("Only this verification's disposable identities may be created")
    metadata = {"oryveta_release_test": suffix}
    if label == "worker":
        metadata["oryveta_role"] = "factory_worker"
    password = "Aa1!" + secrets.token_urlsafe(32)
    payload = checked(admin.post("/auth/v1/admin/users", json={
        "email": email, "password": password, "email_confirm": True,
        "app_metadata": metadata,
    }), "Create controlled test identity")
    user = payload.get("user", payload)
    if user.get("email") != email or not user.get("id"):
        raise RuntimeError("Auth returned an unexpected test identity")
    created.append({"id": user["id"], "email": email})
    with httpx.Client(base_url=connection["API_URL"],
                      headers={"apikey": connection["PUBLISHABLE_KEY"]},
                      trust_env=False, timeout=30) as auth:
        session = checked(auth.post("/auth/v1/token?grant_type=password", json={
            "email": email, "password": password,
        }), "Authenticate controlled test identity")
    if session["user"]["id"] != user["id"]:
        raise RuntimeError("Auth session identity mismatch")
    return session


def _delete_identity(admin, account, suffix):
    if account.get("deleted"):
        return
    payload = checked(admin.get(f"/auth/v1/admin/users/{account['id']}"),
                      "Verify test cleanup identity")
    user = payload.get("user", payload)
    if (user.get("email") != account["email"]
            or user.get("app_metadata", {}).get("oryveta_release_test") != suffix):
        raise RuntimeError("Refusing to delete an identity not owned by this test")
    checked(admin.delete(f"/auth/v1/admin/users/{account['id']}"),
            "Delete controlled test identity")
    account["deleted"] = True


def _project_page(browser, connection, session, name):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(SITE + "/workspace/projects")
    if not page.url.startswith(SITE + "/"):
        raise RuntimeError("Refusing to install a test session on another origin")
    key = f"sb-{urlsplit(connection['API_URL']).hostname.split('.')[0]}-auth-token"
    page.evaluate("state => localStorage.setItem(state.key, JSON.stringify(state.session))",
                  {"key": key, "session": session})
    ui.open_project(page, name)
    return page


def _runtime_checks(connection, evidence, admin, created, sessions, suffix, workspace):
    owner_account, member_account, _, worker_account = created[:4]
    with contextlib.ExitStack() as stack:
        owner, member, outsider = [
            stack.enter_context(ui.api_client(connection, session)) for session in sessions[:3]
        ]
        project = ui.row(ui.rpc(owner, "create_project", {
            "p_workspace_id": workspace["id"], "p_name": f"Runtime release check {suffix}",
            "p_brief": "Temporary production runtime verification; removed after checking.",
            "p_kind": "evolve", "p_source_url": REPOSITORY,
        }))
        project_id = project["id"]
        registered = ui.row(ui.rpc(owner, "register_project_worker", {
            "p_project_id": project_id, "p_worker_user_id": worker_account["id"],
            "p_label": "Temporary release verifier",
        }))
        assert registered["enabled"]
        denied = owner.post("/rest/v1/rpc/claim_analysis_work", json={"p_project_id": project_id})
        assert 400 <= denied.status_code < 500, "A human session acquired worker authority"

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = _project_page(browser, connection, sessions[0], project["name"])
                with page.expect_response(
                    lambda response: urlsplit(response.url).path
                    == "/rest/v1/rpc/submit_repository_analysis"
                ) as pending:
                    page.get_by_role("button", name="Analyze public repository", exact=True).click()
                submitted = pending.value
                assert submitted.ok
                item = ui.row(submitted.json())
                submission_key = submitted.request.post_data_json["p_idempotency_key"]
            finally:
                browser.close()

        work_path = f"/rest/v1/work_items?id=eq.{item['work_item_id']}"
        assert ui.row(ui.ok(owner.get(work_path)))["status"] == "queued"
        assert ui.ok(outsider.get(work_path)) == []
        denied = outsider.post("/rest/v1/rpc/cancel_work_item", json={
            "p_work_item_id": item["work_item_id"],
        })
        assert 400 <= denied.status_code < 500
        replay = ui.row(ui.rpc(owner, "submit_repository_analysis", {
            "p_project_id": project_id, "p_idempotency_key": submission_key,
        }))
        assert replay["replayed"] and replay["work_item_id"] == item["work_item_id"]

        with tempfile.TemporaryDirectory(prefix="oryveta-production-worker-") as directory:
            home = Path(directory)
            credentials = home / "worker.json"
            descriptor = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as file:
                json.dump({
                    "supabase_url": connection["API_URL"],
                    "publishable_key": connection["PUBLISHABLE_KEY"],
                    "project_id": project_id, "refresh_token": sessions[3]["refresh_token"],
                }, file)
            try:
                result = subprocess.run([
                    sys.executable, "-m", "oryveta_engine.factory_runtime",
                    "--credentials", str(credentials), "--project", project_id,
                    "--once", "--lease-seconds", "120", "--max-run-seconds", "60",
                    "--work-root", str(home / "work"),
                ], cwd=ROOT, env={
                    "PATH": "/usr/bin:/bin", "HOME": str(home),
                    "PYTHONPATH": str(ROOT / "engine"), "PYTHONIOENCODING": "utf-8",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }, capture_output=True, text=True, timeout=240)
            except subprocess.TimeoutExpired:
                raise RuntimeError("The one-off production worker timed out; output withheld") from None
            worker_state = json.loads(credentials.read_text())
            private_values = [connection["SERVICE_ROLE_KEY"]]
            for session in [*sessions, worker_state]:
                private_values.extend(session.get(key, "") for key in ("access_token", "refresh_token"))
            if any(value and value in result.stdout + result.stderr for value in private_values):
                raise RuntimeError("Worker output disclosed a credential; output withheld")
            if result.returncode:
                raise RuntimeError(f"The one-off worker exited {result.returncode}; output withheld")
            completed = ui.row(ui.ok(owner.get(work_path)))
            assert completed["status"] == "succeeded"
            run = ui.row(ui.ok(owner.get("/rest/v1/factory_runs", params={
                "work_item_id": f"eq.{item['work_item_id']}", "select": "*",
            })))
            assert run["status"] == "succeeded" and run["worker_user_id"] == worker_account["id"]
            assert run["source_ref"] == "github.com/pallets/click"
            assert re.fullmatch(r"[0-9a-f]{40}", run["source_commit"])
            assert "lease_token" not in run
            assert completed["pinned_source_commit"] == run["source_commit"]
            assert run["result"]["summary"]["source_files_analyzed"] > 0
            events = ui.ok(owner.get("/rest/v1/factory_run_events", params={
                "run_id": f"eq.{run['id']}", "select": "kind",
            }))
            assert {"claimed", "source_resolved", "succeeded"} <= {event["kind"] for event in events}
            assert worker_state["refresh_token"] != sessions[3]["refresh_token"]

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = _project_page(browser, connection, sessions[0], project["name"])
                    with page.expect_download() as download:
                        page.get_by_role("button", name="Download analysis JSON", exact=True).click()
                    assert json.loads(download.value.path().read_text()) == run["result"]
                    page.screenshot(path=str(evidence / "production-runtime-completed.png"),
                                    full_page=True)
                finally:
                    browser.close()

            invitation = ui.row(ui.rpc(owner, "invite_project_member", {
                "p_project_id": project_id, "p_recipient": member_account["email"],
                "p_role": "engineer",
            }))
            ui.rpc(member, "accept_project_invitation", {"p_invitation_id": invitation["id"]})
            cancelled_item = ui.row(ui.rpc(owner, "submit_repository_analysis", {
                "p_project_id": project_id, "p_idempotency_key": uuid.uuid4().hex,
            }))
            worker = stack.enter_context(ui.api_client(connection, worker_state))
            assert ui.ok(worker.get("/auth/v1/user"))["id"] == worker_account["id"]
            lease = ui.row(ui.rpc(worker, "claim_analysis_work", {
                "p_project_id": project_id, "p_lease_seconds": 120,
            }))
            assert lease["work_item_id"] == cancelled_item["work_item_id"]
            ui.rpc(member, "cancel_work_item", {"p_work_item_id": lease["work_item_id"]})
            fenced = ui.row(ui.rpc(worker, "heartbeat_analysis_run", {
                "p_run_id": lease["run_id"], "p_lease_token": lease["lease_token"],
            }))
            assert fenced["lease_valid"] is False
            late = ui.row(ui.rpc(worker, "finish_analysis_run", {
                "p_run_id": lease["run_id"], "p_lease_token": lease["lease_token"],
                "p_result": run["result"],
            }))
            assert late["accepted"] is False
            cancelled_run = ui.row(ui.ok(owner.get("/rest/v1/factory_runs", params={
                "id": f"eq.{lease['run_id']}", "select": "status,result",
            })))
            assert cancelled_run == {"status": "cancelled", "result": None}
            ui.rpc(owner, "revoke_project_worker", {
                "p_project_id": project_id, "p_worker_user_id": worker_account["id"],
            })
            assert ui.ok(worker.get(work_path)) == []
            denied = worker.post("/rest/v1/rpc/claim_analysis_work", json={"p_project_id": project_id})
            assert 400 <= denied.status_code < 500

        chat = ui.row(ui.ok(owner.post("/rest/v1/chats", json={
            "owner_id": owner_account["id"], "workspace_id": workspace["id"],
            "project_id": project_id, "title": f"Runtime retention check {suffix}",
        })))
        share = ui.row(ui.ok(owner.post("/rest/v1/chat_shares", json={
            "chat_id": chat["id"], "invited_by": owner_account["id"],
            "recipient_email": member_account["email"], "permission": "viewer",
        })))
        ui.ok(member.patch(f"/rest/v1/chat_shares?id=eq.{share['id']}", json={
            "status": "accepted", "accepted_by": member_account["id"],
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        }))
        _delete_identity(admin, member_account, suffix)
        retained = ui.row(ui.ok(owner.get("/rest/v1/work_items", params={
            "id": f"eq.{cancelled_item['work_item_id']}",
            "select": "status,cancelled_by,cancel_requested_at",
        })))
        assert retained["status"] == "cancelled" and retained["cancelled_by"] is None
        assert retained["cancel_requested_at"]
        for table, identifier in (("project_invitations", invitation["id"]), ("chat_shares", share["id"])):
            retained = ui.row(ui.ok(owner.get(f"/rest/v1/{table}", params={
                "id": f"eq.{identifier}", "select": "status,accepted_by,accepted_at",
            })))
            assert retained["status"] == "accepted" and retained["accepted_by"] is None
            assert retained["accepted_at"]
        successor_session = _create_identity(
            admin, connection, suffix, "successor", created, member_account["email"])
        successor = stack.enter_context(ui.api_client(connection, successor_session))
        denied = successor.post("/rest/v1/rpc/accept_project_invitation", json={
            "p_invitation_id": invitation["id"],
        })
        assert 400 <= denied.status_code < 500
        assert ui.ok(successor.get("/rest/v1/projects", params={"id": f"eq.{project_id}"})) == []
        assert ui.ok(successor.get("/rest/v1/chats", params={"id": f"eq.{chat['id']}"})) == []
        print("PASS: production browser-submitted analysis completed with the browser closed, "
              "using a one-off LOCAL worker with its own rotating session; persisted JSON "
              "download matched, cancellation fenced late publication, revocation removed "
              "worker access, and deleted attribution granted nothing to a successor account.")


def run(connection: dict, evidence: Path, *, runtime: bool = False):
    api_url = connection["API_URL"].rstrip("/")
    if api_url != f"https://{PROJECT}.supabase.co":
        raise ValueError("Refusing to test an unapproved production API origin")
    ui.ORIGIN = SITE
    suffix = uuid.uuid4().hex[:12]
    created = []
    browser_errors = []
    admin_headers = {
        "apikey": connection["SERVICE_ROLE_KEY"],
        "Authorization": "Bearer " + connection["SERVICE_ROLE_KEY"],
    }
    with httpx.Client(base_url=api_url, headers=admin_headers, trust_env=False, timeout=30) as admin:
        try:
            sessions = []
            labels = ("owner", "member", "guest", "worker") if runtime else ("owner", "member", "guest")
            for label in labels:
                sessions.append(_create_identity(admin, connection, suffix, label, created))

            with contextlib.ExitStack() as stack, sync_playwright() as playwright:
                owner, member, guest = [stack.enter_context(ui.api_client(connection, session)) for session in sessions[:3]]
                for client, account in zip((owner, member, guest), created):
                    if ui.ok(client.get("/auth/v1/user"))["id"] != account["id"]:
                        raise RuntimeError("Real user verification failed")
                browser = playwright.chromium.launch()
                try:
                    pages = []
                    storage_key = f"sb-{urlsplit(api_url).hostname.split('.')[0]}-auth-token"
                    for session in sessions[:3]:
                        context = browser.new_context(viewport={"width": 1280, "height": 900})
                        page = context.new_page()
                        page.on("pageerror", lambda error: browser_errors.append(str(error)))
                        page.goto(SITE + "/workspace/projects")
                        if not page.url.startswith(SITE + "/"):
                            raise RuntimeError("Refusing to install a test session on another origin")
                        # One-time setup with a real Auth-issued session. No persistent
                        # init script can reauthenticate after logout or leak to redirects.
                        page.evaluate("(state) => localStorage.setItem(state.key, JSON.stringify(state.session))",
                                      {"key": storage_key, "session": session})
                        pages.append(page)
                    workspace = ui.row(ui.ok(owner.post("/rest/v1/workspaces", json={
                        "name": f"Release verification {suffix}", "slug": f"release-{suffix}", "created_by": created[0]["id"],
                    })))
                    name = f"Release check {suffix}"
                    pages[0].goto(SITE + "/workspace/projects")
                    expect(pages[0].get_by_role("button", name="Sign out", exact=True)).to_be_visible(timeout=20000)
                    pages[0].get_by_label("Workspace", exact=True).select_option(workspace["id"])
                    pages[0].get_by_label("Project name", exact=True).fill(name)
                    pages[0].get_by_label("What is this project for?", exact=True).fill("Temporary production authorization verification; deleted after the test.")
                    ui.click_rpc(pages[0], "Create project", "create_project")
                    project = ui.row(ui.ok(owner.get("/rest/v1/projects", params={"name": f"eq.{name}", "select": "id,name,brief"})))
                    project_path = f"/rest/v1/projects?id=eq.{project['id']}&select=id,name,brief"
                    assert ui.ok(member.get(project_path)) == []
                    assert ui.ok(guest.get(project_path)) == []
                    pages[0].get_by_label("Recipient", exact=True).fill(created[1]["email"])
                    pages[0].get_by_label("Role", exact=True).select_option("viewer")
                    ui.click_rpc(pages[0], "Send invitation", "invite_project_member")
                    invitation = ui.row(ui.rpc(member, "list_project_invitations", {}))
                    assert ui.ok(member.get(project_path)) == []
                    pages[1].goto(SITE + "/workspace/projects")
                    ui.click_rpc(pages[1], f"Accept invitation to {name}", "accept_project_invitation")
                    assert ui.row(ui.ok(member.get(project_path)))["id"] == project["id"]
                    denied = member.post("/rest/v1/rpc/update_project", json={"p_project_id": project["id"], "p_name": "Denied edit", "p_brief": "Must not persist", "p_source_url": None})
                    assert 400 <= denied.status_code < 500
                    assert ui.row(ui.ok(owner.get(project_path)))["name"] == name
                    ui.open_project(pages[1], name)
                    expect(pages[1].get_by_role("button", name="Save project", exact=True)).to_have_count(0)
                    pages[1].screenshot(path=str(evidence / "production-project-viewer.png"), full_page=True)

                    chat = ui.row(ui.ok(owner.post("/rest/v1/chats", json={"owner_id": created[0]["id"], "workspace_id": workspace["id"], "project_id": project["id"], "title": f"Release session {suffix}"})))
                    chat_path = f"/rest/v1/chats?id=eq.{chat['id']}&select=id,title,project_id"
                    assert ui.ok(member.get(chat_path)) == []
                    share = ui.row(ui.ok(owner.post("/rest/v1/chat_shares", json={"chat_id": chat["id"], "invited_by": created[0]["id"], "recipient_email": created[2]["email"], "permission": "viewer"})))
                    assert ui.ok(guest.get(chat_path)) == []
                    ui.ok(guest.patch(f"/rest/v1/chat_shares?id=eq.{share['id']}", json={"status": "accepted", "accepted_by": created[2]["id"], "accepted_at": datetime.now(timezone.utc).isoformat()}))
                    assert ui.row(ui.ok(guest.get(chat_path)))["id"] == chat["id"]
                    assert ui.ok(guest.get(project_path)) == []
                    denied = guest.post("/rest/v1/chat_messages", json={"chat_id": chat["id"], "author_id": created[2]["id"], "role": "user", "content": "Viewer write must be rejected"})
                    assert 400 <= denied.status_code < 500
                    pages[2].set_viewport_size({"width": 390, "height": 844})
                    pages[2].goto(SITE + "/workspace/chats")
                    expect(pages[2].get_by_text(chat["title"], exact=True).first).to_be_visible(timeout=20000)
                    assert pages[2].evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    pages[2].screenshot(path=str(evidence / "production-session-guest-mobile.png"), full_page=True)

                    ui.open_project(pages[0], name)
                    ui.click_rpc(pages[0], f"Remove account {created[1]['id'][:8]}… from this project", "revoke_project_member")
                    assert ui.ok(member.get(project_path)) == []
                    member.post("/rest/v1/rpc/accept_project_invitation", json={"p_invitation_id": invitation["id"]})
                    assert ui.ok(member.get(project_path)) == []
                    assert ui.visit_data_page(pages[1], "/workspace/projects", "projects") == []
                    ui.ok(owner.delete(f"/rest/v1/chat_shares?id=eq.{share['id']}"))
                    assert ui.ok(guest.get(chat_path)) == []
                    assert ui.visit_data_page(pages[2], "/workspace/chats", "chats") == []
                    assert not browser_errors, "The deployed application raised browser errors"
                    print("PASS: production real Auth-issued sessions, deployed project create/invite/accept, viewer denial, private-session isolation, session-only sharing, revoke/replay and mobile rendering. No email-delivery or OAuth-consent claim.")
                finally:
                    browser.close()
            if runtime:
                _runtime_checks(connection, evidence, admin, created, sessions, suffix, workspace)
        finally:
            failures = []
            # Delete the creator first so owned projects/chats and their accepted
            # invitations cascade before recipient identities are removed.
            for account in created:
                try:
                    _delete_identity(admin, account, suffix)
                except Exception:
                    failures.append(account["id"])
            if failures:
                raise RuntimeError("Controlled test identities require cleanup by ID: " + ", ".join(failures))
            print(f"Removed {len(created)} controlled production test identities and their cascading application rows.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-project", required=True)
    parser.add_argument("--evidence", default="/tmp/oryveta-release-evidence")
    parser.add_argument("--runtime", action="store_true",
                        help="Also verify the deployed queue with one temporary local worker")
    args = parser.parse_args()
    connection = json.load(sys.stdin)
    if args.confirm_project != PROJECT or connection.get("project_ref") != PROJECT:
        raise ValueError("Explicit confirmation of the Oryveta production project is required")
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    run(connection, evidence, runtime=args.runtime)


if __name__ == "__main__":
    main()
