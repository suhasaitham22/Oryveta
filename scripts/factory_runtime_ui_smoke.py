"""Real local Supabase + worker + built-browser analysis flow; no mocked APIs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

import auth_ui_smoke as ui
import factory_runtime_smoke as runtime


def exercise(connection, repository, evidence):
    secret_key = connection.get("SERVICE_ROLE_KEY") or connection["SECRET_KEY"]
    secrets = runtime.Secrets()
    secrets.add("administrative fixture key", secret_key)
    suffix = uuid.uuid4().hex[:12]
    accounts = []
    with runtime.admin_client(connection, secret_key) as admin:
        try:
            owner = runtime.create_account(admin, suffix, "ui-owner", False, secrets)
            accounts.append(owner)
            worker = runtime.create_account(admin, suffix, "ui-worker", True, secrets)
            accounts.append(worker)
            session = runtime.password_session(connection, owner, secrets)
            with runtime.api_client(connection, session) as client:
                workspace = runtime.row(runtime.ok(client.post("/rest/v1/workspaces", json={
                    "name": "Worker browser verification", "slug": f"worker-ui-{suffix}", "created_by": owner.user_id,
                })))
                project = runtime.create_project_fixture(client, owner, workspace["id"], f"Worker UI {suffix}", repository)
                runtime.rpc(client, "register_project_worker", {"p_project_id": project["id"], "p_worker_user_id": worker.user_id, "p_label": "Browser verification worker"})
                worker_session = runtime.password_session(connection, worker, secrets)
                with tempfile.TemporaryDirectory(prefix="oryveta-worker-ui-") as directory, sync_playwright() as p:
                    home = Path(directory)
                    os.chmod(home, 0o700)
                    credentials = home / "worker.json"
                    runtime.write_worker_credentials(credentials, connection, project["id"], worker_session["refresh_token"])
                    browser = p.chromium.launch()
                    try:
                        context = browser.new_context(viewport={"width":1280,"height":900})
                        page = context.new_page()
                        page.goto(ui.ORIGIN + "/workspace/projects")
                        storage_key = f"sb-{urlsplit(connection['API_URL']).hostname.split('.')[0]}-auth-token"
                        page.evaluate("state => localStorage.setItem(state.key, JSON.stringify(state.session))", {"key":storage_key,"session":session})
                        ui.open_project(page, project["name"])
                        panel = page.get_by_role("region", name="Repository analysis", exact=True)
                        with page.expect_response(lambda response: urlsplit(response.url).path == "/rest/v1/rpc/submit_repository_analysis") as pending:
                            panel.get_by_role("button", name="Analyze public repository", exact=True).click()
                        assert pending.value.ok
                        item = runtime.row(pending.value.json())
                        work_id = item["work_item_id"]
                        assert runtime.work_item(client, work_id)["status"] == "queued"
                        page.close()
                        runtime.run_worker_to_completion(credentials, project["id"], 120, home, home / "worker.log", secrets)
                        result = runtime.prove_first_success(client, work_id, repository, worker)
                        page = context.new_page()
                        ui.open_project(page, project["name"])
                        panel = page.get_by_role("region", name="Repository analysis", exact=True)
                        expect(panel.get_by_role("button", name="Download analysis JSON", exact=True)).to_be_visible(timeout=20000)
                        with page.expect_download() as download:
                            panel.get_by_role("button", name="Download analysis JSON", exact=True).click()
                        downloaded = json.loads(Path(download.value.path()).read_text())
                        assert downloaded == result["result"]
                        page.screenshot(path=str(evidence / "completed-worker-analysis.png"), full_page=True)
                        ui.click_rpc(page, "Analyze public repository", "submit_repository_analysis")
                        expect(panel.get_by_role("button", name="Cancel analysis", exact=True)).to_be_visible(timeout=20000)
                        expect(panel.get_by_role("button", name="Download analysis JSON", exact=True)).to_have_count(0)
                        ui.click_rpc(page, "Cancel analysis", "cancel_work_item")
                        expect(panel.get_by_role("button", name="Cancel analysis", exact=True)).to_have_count(0)
                        print("PASS: browser-submitted real analysis completed with browser closed; reopened UI downloads the persisted result; a new queued run does not display old evidence and can be canceled.")
                    finally:
                        browser.close()
        finally:
            for account in accounts:
                runtime.ok(admin.delete(f"/auth/v1/admin/users/{account.user_id}"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-sql", action="store_true")
    parser.add_argument("--repository", default=runtime.DEFAULT_REPOSITORY)
    parser.add_argument("--evidence", default="/tmp/oryveta-runtime-ui-evidence")
    args = parser.parse_args()
    status = json.load(sys.stdin)
    connection = status.get("env", status)
    for key in ("API_URL", "DB_URL"):
        runtime.loopback(connection[key])
    if not args.skip_sql:
        runtime.apply_sql(connection, False)
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    with ui.studio(connection):
        exercise(connection, args.repository, evidence)


if __name__ == "__main__":
    main()
