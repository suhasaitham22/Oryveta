"""Real local Auth/PostgREST/Storage, Ollama, Docker and optional browser Evolve smoke.

The change is an explicitly requested extension to public Click, not an upstream
bug claim or a benchmark. No upstream repository is modified. All model calls
use the operator-pinned local model; all code checks use the existing sandbox.
This script refuses production Supabase endpoints and requires a new private
output directory. Source, credentials and model evidence must not be published.
"""
from __future__ import annotations

import argparse
import contextlib
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid

import factory_runtime_smoke as base

REPOSITORY = "https://github.com/pallets/click"
GOAL = (
    "Extend click.utils.make_str to accept memoryview inputs as their underlying bytes, "
    "using exactly the same decoding and invalid-byte replacement behavior as bytes. "
    "Preserve behavior for str, bytes, None, integers and other existing inputs. "
    "Handle empty, non-contiguous and non-byte-format memoryviews using their logical "
    "byte content. Change only src/click/utils.py. Do not change the check suite."
)
STAGES = ["requirements", "plan", "implementation", "verification", "audit",
          "learning", "learning_review"]


def specification(model: str, digest: str, image: str, docker_context: str) -> dict:
    def check(name, expression, expected, kind):
        return {"name": name, "kind": kind, "argv": ["python", "-c",
            "import sys,json,array; sys.path.insert(0,'src'); "
            "from click.utils import make_str; print(json.dumps(" + expression + "))"],
            "stdin": "", "expected_json": expected}

    return {
        "schema_version": 1,
        "model": {"name": model, "digest": digest, "context_tokens": 32768,
                  "output_tokens": 2048},
        "runner": {"image": image, "docker_context": docker_context,
                   "timeout_seconds": 30, "memory_mb": 512},
        "limits": {"turns": 40, "tool_calls": 80, "total_tokens": 400000,
                   "wall_seconds": 1800},
        "read_paths": ["src/click/utils.py"],
        "write_paths": ["src/click/utils.py"],
        "development_checks": [
            check("memoryview-ascii", "make_str(memoryview(b'hello'))", "hello", "regression"),
            check("existing-inputs", "[make_str('hello'),make_str(b'hello'),make_str(None),make_str(42)]",
                  ["hello", "hello", "None", "42"], "preserve"),
            check("invalid-bytes", "make_str(b'\\xff')", "\ufffd", "preserve"),
        ],
        "acceptance_checks": [
            check("empty-memoryview", "make_str(memoryview(b''))", "", "regression"),
            check("strided-memoryview", "make_str(memoryview(b'abcdef')[::2])", "ace", "regression"),
            check("memoryview-invalid-bytes", "make_str(memoryview(b'\\xff'))", "\ufffd", "regression"),
            check("formatted-memoryview", "make_str(memoryview(array.array('H',[65]))) == "
                  "make_str(memoryview(array.array('H',[65])).tobytes())", True, "regression"),
            check("unicode-preserved", "make_str('caf\u00e9')", "caf\u00e9", "preserve"),
        ],
    }


def denied(response, label):
    if response.status_code not in {400, 401, 403, 404, 409, 422}:
        raise AssertionError(f"{label}: expected refusal, got HTTP {response.status_code}")


def items(client, table, **params):
    return base.ok(client.get(f"/rest/v1/{table}", params=params))


def start_worker(credentials, project_id, config, root, log, lease_seconds):
    environment = base.worker_environment(root)
    environment["PATH"] = os.environ.get("PATH", "/usr/bin:/bin")
    environment["OLLAMA_NO_CLOUD"] = "1"
    if os.environ.get("DOCKER_CONFIG"):
        environment["DOCKER_CONFIG"] = os.environ["DOCKER_CONFIG"]
    command = [sys.executable, "-m", "oryveta_engine.factory_service",
               "--evolve-config", str(config), "--credentials", str(credentials),
               "--project", project_id, "--once", "--lease-seconds", str(lease_seconds),
               "--max-run-seconds", "1800", "--work-root", str(root / "runs")]
    review_config = config.parent / "reviewer.json"
    if review_config.is_file():
        command.extend(["--review-config", str(review_config)])
    handle = log.open("w", encoding="utf-8")
    process = subprocess.Popen(command, env=environment, stdout=handle,
                               stderr=subprocess.STDOUT, start_new_session=True)
    return process, handle


def stop_owned(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)


def wait_for_stage(client, work_id, stage, process, log):
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"worker exited before {stage}; inspect private {log.name}")
        if items(client, "evolve_stages", work_item_id=f"eq.{work_id}", stage=f"eq.{stage}"):
            return base.newest_run(client, work_id)
        time.sleep(0.25)
    raise AssertionError(f"worker did not record {stage} within 600 seconds")


def authenticate_browser(context, connection, session, origin, project):
    import auth_ui_smoke as ui

    ui.ORIGIN = origin
    page = context.new_page()
    page.goto(origin + "/workspace/projects")
    key = f"sb-{urlsplit(connection['API_URL']).hostname.split('.')[0]}-auth-token"
    page.evaluate("state => localStorage.setItem(state.key, JSON.stringify(state.session))",
                  {"key": key, "session": session})
    ui.open_project(page, project["name"])
    return page


def exercise(connection, args, home):
    secrets = base.Secrets()
    service_key = connection.get("SERVICE_ROLE_KEY") or connection["SECRET_KEY"]
    secrets.add("fixture administrative key", service_key)
    config = home / "operator.json"
    config.write_text(json.dumps(specification(args.model, args.model_digest,
                                              args.image, args.docker_context)))
    config.chmod(0o600)
    if args.review_model:
        review_config = home / "reviewer.json"
        review_config.write_text(json.dumps(specification(
            args.review_model, args.review_model_digest, args.image, args.docker_context)))
        review_config.chmod(0o600)
    credentials = home / "worker.json"
    suffix = uuid.uuid4().hex[:12]
    accounts = []
    processes = []
    project = None
    workspace = None
    with contextlib.ExitStack() as resources:
        admin = resources.enter_context(base.admin_client(connection, service_key))
        try:
            for name, worker in (("owner", False), ("viewer", False),
                                 ("outsider", False), ("worker", True)):
                accounts.append(base.create_account(admin, suffix, "evolve-" + name,
                                                    worker, secrets))
            owner_account, viewer_account, outsider_account, worker_account = accounts
            owner_session = base.password_session(connection, owner_account, secrets)
            owner = resources.enter_context(base.api_client(connection, owner_session))
            viewer = base.sign_in(connection, viewer_account, secrets, resources)
            outsider = base.sign_in(connection, outsider_account, secrets, resources)
            worker_api = base.sign_in(connection, worker_account, secrets, resources)
            workspace = base.row(base.ok(owner.post("/rest/v1/workspaces", json={
                "name": "Reviewed Evolve smoke", "slug": "evolve-" + suffix,
                "created_by": owner_account.user_id})))
            project = base.create_project_fixture(owner, owner_account, workspace["id"],
                                                  "Reviewed Evolve " + suffix, REPOSITORY)
            base.invite_and_accept(owner, viewer, viewer_account, project["id"], "viewer")
            base.rpc(owner, "register_project_worker", {
                "p_project_id": project["id"], "p_worker_user_id": worker_account.user_id,
                "p_label": "Isolated Evolve smoke"})
            file_session = base.password_session(connection, worker_account, secrets)
            base.write_worker_credentials(credentials, connection, project["id"],
                                          file_session["refresh_token"])
            submit = {"p_project_id": project["id"], "p_goal": GOAL,
                      "p_idempotency_key": "evolve-" + suffix}
            for label, actor in (("viewer", viewer), ("outsider", outsider), ("worker", worker_api)):
                denied(actor.post("/rest/v1/rpc/submit_evolve_work", json=submit), label + " submission")

            context = None
            if args.ui_origin:
                from playwright.sync_api import sync_playwright

                playwright = resources.enter_context(sync_playwright())
                browser = playwright.chromium.launch()
                resources.callback(browser.close)
                context = browser.new_context(viewport={"width": 1280, "height": 900},
                                              accept_downloads=True)
                page = authenticate_browser(context, connection, owner_session,
                                            args.ui_origin, project)
                panel = page.get_by_role("region", name="Reviewed Evolve", exact=True)
                panel.get_by_role("textbox", name="Change goal", exact=True).fill(GOAL)
                with page.expect_response(lambda response: urlsplit(response.url).path ==
                                          "/rest/v1/rpc/submit_evolve_work") as submitted:
                    panel.get_by_role("button", name="Submit Evolve work", exact=True).click()
                if not submitted.value.ok:
                    raise AssertionError("Browser submission was refused")
                submit = submitted.value.request.post_data_json
                item = base.row(submitted.value.json())
                page.close()
            else:
                item = base.row(base.rpc(owner, "submit_evolve_work", submit))
            work_id = item["id"]
            with ThreadPoolExecutor(max_workers=4) as duplicates:
                replies = list(duplicates.map(
                    lambda _: base.row(base.rpc(owner, "submit_evolve_work", submit))["id"],
                    range(4)))
            assert replies == [work_id] * 4
            denied(owner.post("/rest/v1/rpc/submit_evolve_work", json={
                **submit, "p_goal": GOAL + " Conflicting new scope."}), "changed idempotent input")
            print("PASS authorized durable submission, duplicate delivery and conflicting-input refusal", flush=True)

            log = home / "worker-first.log"
            process, handle = start_worker(credentials, project["id"], config, home, log,
                                           30 if args.crash_restart else 300)
            processes.append(process)
            resources.callback(handle.close)
            if args.crash_restart:
                interrupted = wait_for_stage(owner, work_id, "requirements", process, log)
                children = base.analysis_children(process.pid)
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=30)
                base.wait_until("interrupted child exits", 120,
                                lambda: all(base.process_gone(pid) for pid in children))
                base.wait_until("real lease expiry", 120,
                                lambda: base.expired(base.newest_run(owner, work_id)["lease_expires_at"]))
                log = home / "worker-restarted.log"
                process, handle = start_worker(credentials, project["id"], config, home, log, 300)
                processes.append(process)
                resources.callback(handle.close)
                print("PASS killed controller and child termination; restarting from pinned inputs", flush=True)
            result = process.wait(timeout=2100)
            handle.flush()
            secrets.assert_absent("worker output", log.read_text())
            if result != 0:
                raise AssertionError(f"Evolve worker exited {result}; inspect private {log.name}")
            run = base.newest_run(owner, work_id)
            current = base.work_item(owner, work_id)
            if current["status"] != "awaiting_approval":
                raise AssertionError(f"Evolve ended {current['status']} / {current.get('error_code')}; "
                                     f"inspect private evidence in {home}")
            if args.crash_restart:
                assert run["attempt"] == interrupted["attempt"] + 1
                assert run["source_commit"] == interrupted["source_commit"]
                assert run["id"] != interrupted["id"]
            stages = items(owner, "evolve_stages", run_id="eq." + run["id"])
            assert {entry["stage"] for entry in stages} == set(STAGES)
            assert all(entry["payload"]["review"]["verdict"] == "pass" for entry in stages)
            verification = next(entry["payload"]["artifact"] for entry in stages
                                if entry["stage"] == "verification")
            assert verification["baseline_reproduced"] and verification["preservation_passed"]
            assert all(check["passed"] for check in verification["checks"])
            artifacts = items(owner, "evolve_artifacts", run_id="eq." + run["id"])
            downloaded = {}
            for artifact in artifacts:
                response = owner.get("/storage/v1/object/authenticated/evolve-artifacts/" +
                                     artifact["storage_path"])
                response.raise_for_status()
                assert sha256(response.content).hexdigest() == artifact["sha256"]
                assert len(response.content) == artifact["bytes"]
                downloaded[artifact["kind"]] = response.content
                denied(outsider.get("/storage/v1/object/authenticated/evolve-artifacts/" +
                                    artifact["storage_path"]), "cross-tenant artifact")
            candidate = next(artifact for artifact in artifacts if artifact["kind"] == "candidate")
            assert candidate["sha256"] == verification["candidate_sha256"]
            assert "patch" in downloaded and "candidate" in downloaded
            for table in ("work_items", "factory_runs", "evolve_stages", "evolve_artifacts", "evolve_lessons"):
                assert items(outsider, table, project_id="eq." + project["id"]) == []
            decision = {"p_work_item_id": work_id, "p_run_id": run["id"],
                        "p_candidate_sha256": candidate["sha256"], "p_approve": True}
            denied(owner.post("/rest/v1/rpc/decide_evolve_work", json={
                **decision, "p_candidate_sha256": "0" * 64}), "stale candidate approval")
            denied(worker_api.post("/rest/v1/rpc/decide_evolve_work", json=decision), "worker self-approval")
            denied(viewer.post("/rest/v1/rpc/decide_evolve_work", json=decision), "viewer approval")
            print("PASS live model reviews, protected verification, process audit, private artifact hashes and access denial", flush=True)

            if context:
                from playwright.sync_api import expect

                page = authenticate_browser(context, connection, owner_session,
                                            args.ui_origin, project)
                panel = page.get_by_role("region", name="Reviewed Evolve", exact=True)
                for label, kind in (("Download candidate ZIP", "candidate"), ("Download patch", "patch")):
                    with page.expect_download() as transfer:
                        panel.get_by_role("button", name=label, exact=True).click()
                    assert Path(transfer.value.path()).read_bytes() == downloaded[kind]
                page.screenshot(path=str(home / "evolve-review-desktop.png"), full_page=True)
                for summary in panel.locator(".evolve-stages > details > summary").all():
                    summary.click()
                for width in (390, 320):
                    page.set_viewport_size({"width": width, "height": 844})
                    page.screenshot(path=str(home / f"evolve-review-mobile-{width}.png"),
                                    full_page=True)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                with page.expect_response(lambda response: urlsplit(response.url).path ==
                                          "/rest/v1/rpc/decide_evolve_work") as approval:
                    panel.get_by_role("button", name="Approve candidate", exact=True).click()
                assert approval.value.ok
                expect(panel.get_by_role("button", name="Approve candidate", exact=True)).to_have_count(0)
                page.close()
                print("PASS browser closure/reconnect, authenticated downloads, mobile layout and exact-candidate approval", flush=True)
            else:
                base.rpc(owner, "decide_evolve_work", decision)
            assert base.work_item(owner, work_id)["status"] == "succeeded"
            base.rpc(owner, "decide_evolve_work", decision)
            denied(owner.post("/rest/v1/rpc/decide_evolve_work", json={
                **decision, "p_approve": False}), "conflicting repeated decision")
            lessons = items(owner, "evolve_lessons", run_id="eq." + run["id"])
            for lesson in lessons:
                if lesson["status"] == "approved":
                    base.rpc(owner, "revoke_evolve_lesson", {"p_lesson_id": lesson["id"]})
                    assert items(worker_api, "evolve_lessons", id="eq." + lesson["id"],
                                 status="eq.approved") == []
            print(f"PASS human approval, idempotent decision and learning lifecycle ({len(lessons)} candidate lessons)", flush=True)

            if args.crash_restart:
                for action in ("cancel", "revoke"):
                    interrupted_item = base.row(base.rpc(owner, "submit_evolve_work", {
                        **submit, "p_idempotency_key": action + "-" + suffix}))
                    live_log = home / f"worker-{action}.log"
                    live_process, live_handle = start_worker(
                        credentials, project["id"], config, home, live_log, 60)
                    processes.append(live_process)
                    resources.callback(live_handle.close)
                    live_run = wait_for_stage(owner, interrupted_item["id"], "requirements",
                                              live_process, live_log)
                    live_children = base.analysis_children(live_process.pid)
                    if action == "cancel":
                        base.rpc(owner, "cancel_work_item",
                                 {"p_work_item_id": interrupted_item["id"]})
                    else:
                        base.rpc(owner, "revoke_project_worker", {
                            "p_project_id": project["id"],
                            "p_worker_user_id": worker_account.user_id})
                    live_process.wait(timeout=120)
                    base.wait_until("fenced execution exits", 120,
                                    lambda: all(base.process_gone(pid) for pid in live_children))
                    expected_status = "cancelled" if action == "cancel" else "queued"
                    assert base.work_item(owner, interrupted_item["id"])["status"] == expected_status
                    fenced_run = base.newest_run(owner, interrupted_item["id"])
                    assert fenced_run["status"] == "cancelled"
                    assert fenced_run["error_code"] == (
                        "cancelled" if action == "cancel" else "worker_revoked")
                    assert items(owner, "evolve_artifacts", run_id="eq." + live_run["id"]) == []
                    if action == "revoke":
                        # Revoking a worker preserves eligible work for another
                        # worker. Cancel this fixture before testing a new claim.
                        base.rpc(owner, "cancel_work_item",
                                 {"p_work_item_id": interrupted_item["id"]})
                        base.rpc(owner, "register_project_worker", {
                            "p_project_id": project["id"],
                            "p_worker_user_id": worker_account.user_id,
                            "p_label": "Isolated Evolve smoke"})
                print("PASS live cancellation and revocation stop stage processes without publishing artifacts",
                      flush=True)

            late = base.row(base.rpc(owner, "submit_evolve_work", {
                **submit, "p_idempotency_key": "late-" + suffix}))
            claim = base.row(base.rpc(worker_api, "claim_evolve_work", {"p_project_id": project["id"]}))
            assert claim["work_item_id"] == late["id"]
            base.rpc(owner, "cancel_work_item", {"p_work_item_id": late["id"]})
            response = worker_api.post("/rest/v1/rpc/finish_evolve_run", json={
                "p_run_id": claim["run_id"], "p_lease_token": claim["lease_token"]})
            if response.is_success:
                assert base.row(response.json())["accepted"] is False
            else:
                denied(response, "cancelled late completion")
            base.rpc(owner, "revoke_project_worker", {
                "p_project_id": project["id"], "p_worker_user_id": worker_account.user_id})
            denied(worker_api.post("/rest/v1/rpc/claim_evolve_work", json={
                "p_project_id": project["id"]}), "revoked worker admission")
            print("PASS cancellation fences late completion and revoked worker cannot claim", flush=True)
            (home / "result.json").write_text(json.dumps({
                "work_item_id": work_id, "run_id": run["id"], "source_commit": run["source_commit"],
                "candidate_sha256": candidate["sha256"], "stages": STAGES,
                "verification_checks": len(verification["checks"]),
                "lesson_candidates": len(lessons), "crash_restart": args.crash_restart,
                "browser": bool(context), "published": False}, indent=2))
        finally:
            for process in processes:
                stop_owned(process)
            if project is not None:
                fixture_runs = items(admin, "factory_runs", project_id="eq." + project["id"])
                for fixture_run in fixture_runs:
                    paths = []
                    for kind in ("candidate", "patch", "receipt", "trace"):
                        prefix = fixture_run["id"] + "/" + kind
                        objects = base.ok(admin.post(
                            "/storage/v1/object/list/evolve-artifacts",
                            json={"prefix": prefix, "limit": 100}))
                        paths.extend(prefix + "/" + obj["name"] for obj in objects)
                    if paths:
                        base.ok(admin.request("DELETE", "/storage/v1/object/evolve-artifacts",
                                              json={"prefixes": paths}))
                base.ok(admin.delete("/rest/v1/work_items",
                                     params={"project_id": "eq." + project["id"]}))
            if workspace is not None:
                base.ok(admin.delete("/rest/v1/workspaces",
                                     params={"id": "eq." + workspace["id"]}))
            for account in reversed(accounts):
                base.ok(admin.delete(f"/auth/v1/admin/users/{account.user_id}"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connections", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--review-model", help="Optional separately pinned local reviewer")
    parser.add_argument("--review-model-digest")
    parser.add_argument("--image", required=True)
    parser.add_argument("--docker-context", default="default")
    parser.add_argument("--ui-origin", help="Already built local Studio server; never a production origin")
    parser.add_argument("--crash-restart", action="store_true")
    parser.add_argument("--skip-sql", action="store_true")
    args = parser.parse_args()
    if bool(args.review_model) != bool(args.review_model_digest):
        parser.error("--review-model and --review-model-digest must be supplied together")
    payload = json.loads(Path(args.connections).read_text())
    connection = payload.get("env", payload)
    for key in ("API_URL", "DB_URL"):
        base.loopback(connection[key])
    if args.ui_origin:
        base.loopback(args.ui_origin)
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    if not args.skip_sql:
        base.apply_sql(connection, True)
    exercise(connection, args, args.output.resolve())


if __name__ == "__main__":
    main()
