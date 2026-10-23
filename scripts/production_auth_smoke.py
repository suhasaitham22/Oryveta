"""Opt-in production authorization smoke using real, temporary Auth users.

Creates three confirmed test identities with the Auth admin API, obtains normal
password-grant sessions, and exercises the deployed UI/RLS as those identities.
This does NOT claim email delivery or GitHub-consent coverage; those are separate
login checks. No auth responses are mocked, no test endpoint is added to the app,
and the administrative key is never placed in a browser. Temporary users and
their application rows are removed by ID in finally; provider audit logs may remain.

Connection JSON comes from stdin and must include project_ref, API_URL,
PUBLISHABLE_KEY and SERVICE_ROLE_KEY. A matching --confirm-project is required.
Never commit that JSON or record a browser trace containing authenticated state.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit
import uuid

import httpx
from playwright.sync_api import sync_playwright, expect

import auth_ui_smoke as ui

SITE = "https://oryveta.vercel.app"
PROJECT = "nydtmiseclkwauiepqxn"


def checked(response, operation):
    if response.is_error:
        raise RuntimeError(f"{operation} failed: HTTP {response.status_code}")
    return response.json() if response.content else None


def run(connection: dict, evidence: Path):
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
            for label in ("owner", "member", "guest"):
                email = f"oryveta-release-{suffix}-{label}@example.invalid"
                password = secrets.token_urlsafe(32)
                payload = checked(admin.post("/auth/v1/admin/users", json={
                    "email": email, "password": password, "email_confirm": True,
                    "app_metadata": {"oryveta_release_test": suffix},
                }), "Create controlled test identity")
                user = payload.get("user", payload)
                if user.get("email") != email or not user.get("id"):
                    raise RuntimeError("Auth returned an unexpected test identity")
                created.append({"id": user["id"], "email": email})
                with httpx.Client(base_url=api_url, headers={"apikey": connection["PUBLISHABLE_KEY"]}, trust_env=False, timeout=30) as auth:
                    session = checked(auth.post("/auth/v1/token?grant_type=password", json={"email": email, "password": password}), "Authenticate controlled test identity")
                if session["user"]["id"] != user["id"]:
                    raise RuntimeError("Auth session identity mismatch")
                sessions.append(session)
                password = None

            with contextlib.ExitStack() as stack, sync_playwright() as playwright:
                owner, member, guest = [stack.enter_context(ui.api_client(connection, session)) for session in sessions]
                for client, account in zip((owner, member, guest), created):
                    if ui.ok(client.get("/auth/v1/user"))["id"] != account["id"]:
                        raise RuntimeError("Real user verification failed")
                browser = playwright.chromium.launch()
                try:
                    pages = []
                    storage_key = f"sb-{urlsplit(api_url).hostname.split('.')[0]}-auth-token"
                    for session in sessions:
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
        finally:
            failures = []
            # Delete the creator first so owned projects/chats and their accepted
            # invitations cascade before recipient identities are removed.
            for account in created:
                try:
                    payload = checked(admin.get(f"/auth/v1/admin/users/{account['id']}"), "Verify test cleanup identity")
                    user = payload.get("user", payload)
                    if user.get("email") != account["email"] or user.get("app_metadata", {}).get("oryveta_release_test") != suffix:
                        raise RuntimeError("Refusing to delete an identity not owned by this test")
                    checked(admin.delete(f"/auth/v1/admin/users/{account['id']}"), "Delete controlled test identity")
                except Exception:
                    failures.append(account["id"])
            if failures:
                raise RuntimeError("Controlled test identities require cleanup by ID: " + ", ".join(failures))
            print(f"Removed {len(created)} controlled production test identities and their cascading application rows.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-project", required=True)
    parser.add_argument("--evidence", default="/tmp/oryveta-release-evidence")
    args = parser.parse_args()
    connection = json.load(sys.stdin)
    if args.confirm_project != PROJECT or connection.get("project_ref") != PROJECT:
        raise ValueError("Explicit confirmation of the Oryveta production project is required")
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    run(connection, evidence)


if __name__ == "__main__":
    main()
