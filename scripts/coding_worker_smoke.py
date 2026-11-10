"""Controlled repair integration against isolated LOCAL Supabase, GitHub and Docker.

Default uses a real operator-selected Ollama model. --scripted-model is an
explicit CI protocol fixture, never a production fallback or quality result.
The task changes a sample project's requirement; it is not an upstream bug,
a customer repair, a benchmark or production rollout. Fixtures are removed.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

import auth_ui_smoke as ui
import factory_runtime_smoke as runtime
from oryveta_engine.coding_config import load_spec

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/pypa/sampleproject"
COMMIT = "621e4974ca25ce531773def586ba3ed8e736b3fc"
SOURCE_FILE = "src/sample/simple.py"
GOAL = (
    "Controlled synthetic integration task, not an upstream defect: change add_one "
    "in src/sample/simple.py so numeric inputs increase by two instead of one. "
    "Keep the function name and TypeError behavior for invalid types. Change only "
    "src/sample/simple.py. Preserve all other source files."
)
CHECK_PROGRAM = '''import json, os, sys, time
sys.path.insert(0, "src")
from sample.simple import add_one
value = json.load(sys.stdin)
time.sleep(2)
if isinstance(value, dict) and value.get("probe") == "environment":
    result = {"secret_present": any(name in os.environ for name in (
        "SUPABASE_SERVICE_ROLE_KEY", "ORYVETA_WORKER_BOOTSTRAP", "ORYVETA_REPAIR_SENTINEL"))}
else:
    try:
        result = add_one(value)
    except TypeError:
        result = {"error": "TypeError"}
print(json.dumps(result))
'''


def specification(model, digest, image, context):
    def case(name, value, expected, kind):
        return {"name": name, "argv": ["python", "-c", CHECK_PROGRAM],
                "stdin": json.dumps(value), "expected_json": expected, "kind": kind}
    return {
        "schema_version": 1,
        "model": {"name": model, "digest": digest},
        "runner": {"image": image, "docker_context": context, "timeout_seconds": 15},
        "read_paths": [SOURCE_FILE], "write_paths": [SOURCE_FILE],
        "development_checks": [
            case("requirement-change", 1, 3, "regression"),
            case("invalid-type", "bad", {"error": "TypeError"}, "preserve"),
            case("credential-boundary", {"probe": "environment"}, {"secret_present": False}, "preserve"),
        ],
        "acceptance_checks": [
            case("negative-input", -2, 0, "regression"),
            case("fractional-input", 0.5, 2.5, "regression"),
        ],
    }


def worker_command(credentials, policy, config, home, args, max_runs=None, lease_seconds=60):
    command = [sys.executable, "-m", "oryveta_engine.coding_worker",
               "--credentials", str(credentials), "--policy", policy,
               "--config", str(config), "--source-url", REPOSITORY,
               "--source-commit", COMMIT, "--evidence-root", str(Path(args.evidence) / "runs"),
               "--work-root", str(home / "work"), "--docker-cli", args.docker_cli,
               "--lease-seconds", str(lease_seconds), "--poll-seconds", "0.25"]
    if args.docker_config:
        command += ["--docker-config", args.docker_config]
    if max_runs:
        command += ["--max-runs", str(max_runs)]
    return command


@contextlib.contextmanager
def running_worker(credentials, policy, config, home, args, label, secrets, max_runs=None, lease_seconds=60):
    log = home / f"{label}.log"
    environment = runtime.worker_environment(home)
    environment["ORYVETA_REPAIR_SENTINEL"] = "must-not-enter-child-or-code"
    with log.open("wb") as output:
        process = subprocess.Popen(
            worker_command(credentials, policy, config, home, args, max_runs, lease_seconds),
            cwd=ROOT, env=environment, stdout=output, stderr=output, start_new_session=True)
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=15)
            if credentials.exists():
                secrets.add("rotated repair refresh token", runtime.credential_state(credentials).get("refresh_token"))
            text = log.read_text(errors="replace")
            Path(args.evidence, f"{label}.log").write_text(secrets.scrub(text))
            secrets.assert_absent(label, text)


def completed(client, work_id, process):
    def probe():
        item = runtime.work_item(client, work_id)
        if item["status"] in {"failed", "cancelled"}:
            raise AssertionError(f"repair ended {item['status']}: {item.get('error_code')}")
        if item["status"] == "succeeded":
            run = runtime.newest_run(client, work_id)
            result = run["result"]
            assert result["status"] == "needs_review" and result["verification"] == "passed"
            assert result["source_commit"] == COMMIT and result["checks_passed"] == 5
            assert hashlib.sha256(result["patch"].encode()).hexdigest() == result["patch_sha256"]
            runtime.assert_no_lease_token(run)
            return run
        if process.poll() is not None:
            raise AssertionError(f"worker exited {process.returncode} before completing {work_id}")
        return None
    return runtime.wait_until("repair completion", 600, probe, interval=0.25)


def active_child(client, work_id, process):
    def probe():
        if process.poll() is not None:
            raise AssertionError(f"worker exited {process.returncode} before its child was observed")
        run = runtime.newest_run(client, work_id)
        if run and run["status"] == "running" and run["phase"] in {"repairing", "verifying"}:
            children = runtime.analysis_children(process.pid)
            if children:
                return children[0]
        return None
    return runtime.wait_until("active coding child", 180, probe, interval=0.1)


def submit(client, project_id, policy_id, suffix):
    return runtime.row(runtime.rpc(client, "submit_repository_repair", {
        "p_project_id": project_id, "p_policy_id": policy_id,
        "p_goal": GOAL + " " + suffix, "p_idempotency_key": uuid.uuid4().hex,
    }))["work_item_id"]


def exercise(connection, args, home):
    key = connection.get("SERVICE_ROLE_KEY") or connection["SECRET_KEY"]
    secrets = runtime.Secrets()
    secrets.add("local setup administrative key", key)
    accounts = []
    suffix = uuid.uuid4().hex[:10]
    workspace_id = None
    owner_client = None
    config = home / "operator.json"
    config.write_text(json.dumps(specification(args.model, args.model_digest, args.image, args.docker_context)))
    config.chmod(0o600)
    digest = load_spec(config).digest
    report = {"proposer": "scripted_native_fixture" if args.scripted_model else "real_local_model",
              "repository": REPOSITORY, "commit": COMMIT, "synthetic_requirement_change": True}
    with runtime.admin_client(connection, key) as admin, contextlib.ExitStack() as resources:
        try:
            owner = runtime.create_account(admin, suffix, "repair-owner", False, secrets)
            accounts.append(owner)
            worker = runtime.create_account(admin, suffix, "repair-worker", True, secrets)
            accounts.append(worker)
            viewer = runtime.create_account(admin, suffix, "repair-viewer", False, secrets)
            accounts.append(viewer)
            owner_session = runtime.password_session(connection, owner, secrets)
            owner_client = resources.enter_context(runtime.api_client(connection, owner_session))
            viewer_client = runtime.sign_in(connection, viewer, secrets, resources)
            workspace = runtime.row(runtime.ok(owner_client.post("/rest/v1/workspaces", json={
                "name": "Controlled repair integration", "slug": f"repair-{suffix}", "created_by": owner.user_id})))
            workspace_id = workspace["id"]
            project = runtime.row(runtime.rpc(owner_client, "create_project", {
                "p_workspace_id": workspace_id, "p_name": f"Synthetic repair {suffix}",
                "p_brief": "Local integration fixture; not an upstream defect or customer result.",
                "p_kind": "evolve", "p_source_url": REPOSITORY}))
            project_id = project["id"]
            runtime.invite_and_accept(owner_client, viewer_client, viewer, project_id, "viewer")
            runtime.rpc(owner_client, "register_project_worker", {
                "p_project_id": project_id, "p_worker_user_id": worker.user_id,
                "p_label": "Controlled repair test worker"})
            credentials = home / "credentials" / "worker.json"
            credentials.parent.mkdir(mode=0o700)
            worker_session = runtime.password_session(connection, worker, secrets)
            runtime.write_worker_credentials(credentials, connection, project_id, worker_session["refresh_token"])

            with ui.studio(connection), sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context(viewport={"width": 1280, "height": 900},
                                              record_video_dir=str(Path(args.evidence) / "browser-recordings"))
                page = context.new_page()
                page.goto(ui.ORIGIN + "/workspace/projects")
                storage_key = f"sb-{urlsplit(connection['API_URL']).hostname.split('.')[0]}-auth-token"
                page.evaluate("state => localStorage.setItem(state.key, JSON.stringify(state.session))",
                              {"key": storage_key, "session": owner_session})
                ui.open_project(page, project["name"])
                panel = page.get_by_role("region", name="Controlled repair", exact=True)
                panel.get_by_text("Enroll a repair policy", exact=True).click()
                panel.get_by_label("Dedicated worker user ID", exact=True).fill(worker.user_id)
                panel.get_by_label("Policy label", exact=True).fill("Synthetic requirement policy")
                panel.get_by_label("Approved commit SHA (40 hex)", exact=True).fill(COMMIT)
                panel.get_by_label("Configuration SHA-256 (64 hex)", exact=True).fill(digest)
                with page.expect_response(lambda response: urlsplit(response.url).path.endswith("/register_project_repair_policy")) as pending:
                    panel.get_by_role("button", name="Enroll repair policy", exact=True).click()
                assert pending.value.ok
                policy = runtime.row(pending.value.json())
                policy_id = policy["id"]
                page.screenshot(path=str(Path(args.evidence) / "repair-policy.png"), full_page=True)
                denied = viewer_client.post("/rest/v1/rpc/submit_repository_repair", json={
                    "p_project_id": project_id, "p_policy_id": policy_id,
                    "p_goal": GOAL, "p_idempotency_key": uuid.uuid4().hex})
                assert 400 <= denied.status_code < 500
                with running_worker(credentials, policy_id, config, home, args, "continuous", secrets, 2) as process:
                    report["continuous_worker_pid"] = process.pid
                    for number in (1, 2):
                        if page.is_closed():
                            page = context.new_page()
                        viewport = {"width": 1280 if number == 1 else 390, "height": 900}
                        page.set_viewport_size(viewport)
                        ui.open_project(page, project["name"])
                        panel = page.get_by_role("region", name="Controlled repair", exact=True)
                        panel.get_by_label("What should the worker attempt?", exact=True).fill(GOAL + f" Task {number}.")
                        with page.expect_response(lambda response: urlsplit(response.url).path.endswith("/submit_repository_repair")) as pending:
                            panel.get_by_role("button", name="Queue repair under this policy", exact=True).click()
                        assert pending.value.ok
                        work_id = runtime.row(pending.value.json())["work_item_id"]
                        page.screenshot(path=str(Path(args.evidence) / f"repair-submitted-{number}.png"), full_page=True)
                        page.close()
                        run = completed(owner_client, work_id, process)
                        secrets.assert_absent("persisted repair result", json.dumps(run))
                        page = context.new_page()
                        page.set_viewport_size(viewport)
                        ui.open_project(page, project["name"])
                        panel = page.get_by_role("region", name="Controlled repair", exact=True)
                        download_button = panel.get_by_role("button", name="Download patch (.patch)", exact=True)
                        expect(download_button).to_be_visible(timeout=30000)
                        with page.expect_download() as download:
                            download_button.click()
                        assert Path(download.value.path()).read_bytes() == run["result"]["patch"].encode()
                        patch_view = panel.get_by_label("Proposed patch", exact=True)
                        assert patch_view.text_content() == run["result"]["patch"]
                        if patch_view.evaluate("node => node.scrollWidth > node.clientWidth"):
                            patch_view.focus()
                            page.keyboard.press("ArrowRight")
                            page.wait_for_function(
                                "node => node.scrollLeft > 0", arg=patch_view.element_handle(), timeout=5000)
                            patch_view.evaluate("node => { node.scrollLeft = 0; }")
                        layout = page.evaluate("""() => ({
                            viewport: innerWidth,
                            document: document.documentElement.scrollWidth,
                            overflowing: [...document.querySelectorAll("body *")]
                                .filter(node => {
                                    const box = node.getBoundingClientRect();
                                    return box.width > 0 && box.right > innerWidth + 1;
                                })
                                .slice(0, 20)
                                .map(node => ({
                                    tag: node.tagName, id: node.id, className: String(node.className),
                                    parentClass: String(node.parentElement?.className),
                                    right: node.getBoundingClientRect().right,
                                    width: node.getBoundingClientRect().width,
                                    minWidth: getComputedStyle(node).minWidth,
                                    whiteSpace: getComputedStyle(node).whiteSpace
                                }))
                        })""")
                        page.screenshot(path=str(Path(args.evidence) / f"repair-completed-{number}.png"), full_page=True)
                        assert layout["document"] <= layout["viewport"] + 1, json.dumps(layout)
                    assert process.wait(timeout=30) == 0
                report["continuous_tasks"] = 2
                report["browser_closed_during_execution"] = True
                context.close()
                browser.close()

            # A second continuous process is fenced while its child is running.
            with running_worker(credentials, policy_id, config, home, args, "cancel-and-kill", secrets, lease_seconds=15) as process:
                work_id = submit(owner_client, project_id, policy_id, "Cancellation case.")
                child_pid = active_child(owner_client, work_id, process)
                runtime.rpc(owner_client, "cancel_work_item", {"p_work_item_id": work_id})
                runtime.wait_until("cancelled child stops", 60,
                                   lambda: runtime.process_gone(child_pid) or None)
                assert runtime.work_item(owner_client, work_id)["status"] == "cancelled"
                assert runtime.newest_run(owner_client, work_id).get("result") is None
                report["cancellation"] = "fenced and child stopped"
                restart_id = submit(owner_client, project_id, policy_id, "Restart case.")
                child_pid = active_child(owner_client, restart_id, process)
                process.kill()
                assert process.wait(timeout=30) != 0
                runtime.wait_until("orphan coding child stops", 60,
                                   lambda: runtime.process_gone(child_pid) or None)
            with running_worker(credentials, policy_id, config, home, args, "reclaimed", secrets, 1, lease_seconds=15) as process:
                run = completed(owner_client, restart_id, process)
                assert run["attempt"] == 2
                assert process.wait(timeout=30) == 0
                first = runtime.attempt_run(owner_client, restart_id, 1)
                assert first["status"] == "failed" and first["error_code"] == "lease_expired"
                assert first.get("result") is None
                report["restart"] = "same commit, second fenced attempt completed"
            with running_worker(credentials, policy_id, config, home, args, "policy-revoked", secrets, lease_seconds=15) as process:
                work_id = submit(owner_client, project_id, policy_id, "Policy revocation case.")
                child_pid = active_child(owner_client, work_id, process)
                runtime.rpc(owner_client, "revoke_project_repair_policy", {"p_policy_id": policy_id})
                runtime.wait_until("revoked policy child stops", 60,
                                   lambda: runtime.process_gone(child_pid) or None)
                item = runtime.work_item(owner_client, work_id)
                assert item["status"] in {"failed", "cancelled"}
                assert item["error_code"] == "policy_revoked"
                assert runtime.newest_run(owner_client, work_id).get("result") is None
                process.wait(timeout=60)
                report["policy_revocation"] = "fenced and worker stopped"
            report["status"] = "passed"
        except BaseException as error:
            report["status"] = "failed"
            report["error"] = secrets.scrub(str(error))
            raise
        finally:
            if owner_client and workspace_id:
                runtime.ok(owner_client.delete("/rest/v1/workspaces", params={"id": f"eq.{workspace_id}"}))
                assert runtime.ok(owner_client.get("/rest/v1/workspaces", params={"id": f"eq.{workspace_id}", "select": "id"})) == []
            for account in reversed(accounts):
                runtime.ok(admin.delete(f"/auth/v1/admin/users/{account.user_id}"))
            Path(args.evidence, "repair-worker-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connections", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--docker-context", default="default")
    parser.add_argument("--docker-cli", default=shutil.which("docker"))
    parser.add_argument("--docker-config", default=os.environ.get("DOCKER_CONFIG"))
    parser.add_argument("--run-root", default=str(Path.home() / ".oryveta/repair-runs"))
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--model-digest", default="500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41")
    parser.add_argument("--scripted-model", action="store_true")
    parser.add_argument("--skip-sql", action="store_true")
    args = parser.parse_args()
    if not args.docker_cli:
        parser.error("a local Docker executable is required")
    data = json.loads(Path(args.connections).read_text())
    connection = data.get("env", data)
    for key in ("API_URL", "DB_URL"):
        runtime.loopback(connection[key])
    Path(args.evidence).mkdir(mode=0o700, parents=True, exist_ok=False)
    Path(args.run_root).mkdir(mode=0o700, parents=True, exist_ok=True)
    if not args.skip_sql:
        runtime.apply_sql(connection, True)
    with contextlib.ExitStack() as resources:
        if args.scripted_model:
            from repair_model_fixture import serve
            args.model, args.model_digest = resources.enter_context(serve())
        home = Path(resources.enter_context(tempfile.TemporaryDirectory(dir=args.run_root, prefix="controlled-repair-")))
        exercise(connection, args, home)


if __name__ == "__main__":
    main()
