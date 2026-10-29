"""Real Chromium consumer checks for the compiled React Studio.

The default mode serves ``studio/dist`` as a hosted-style preview. Set
``ORYVETA_SMOKE_API_URL`` to a running self-hosted FastAPI origin to exercise
the local cookie login, ZIP analysis and persisted job timeline. No external
credentials or production mutations are used.
"""
from __future__ import annotations

import io
import json
import os
import re
import threading
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "apps" / "web" / "studio" / "dist"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_args):
        pass

    def translate_path(self, path):
        if "?" in path:
            path = path.split("?", 1)[0]
        clean = path.strip("/")
        first = clean.split("/", 1)[0].lower() if clean else ""
        if clean and "." not in clean and first not in {"api", "auth", "assets", "static"}:
            path = "/index.html"
        elif path == "/":
            path = "/index.html"
        return super().translate_path(path)


def _archive() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("snapshot/app.py", "def run():\n    return 'ok'\n")
    return stream.getvalue()


def _assert_no_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def _assert_no_back_control(page):
    expect(page.get_by_role("button", name=re.compile(r"^Back\b"))).to_have_count(0)


def _open_nav(page, label):
    page.locator(".workspace-shell").wait_for(state="visible")
    if page.get_by_role("button", name="Open workspace menu").is_visible():
        page.get_by_role("button", name="Open workspace menu").click()
        nav = page.get_by_role("dialog", name="Workspace menu").get_by_role(
            "navigation", name="Workspace navigation"
        )
    else:
        nav = page.get_by_role("navigation", name="Workspace navigation")
    nav.get_by_role("link", name=label, exact=True).first.click()


def _click_primary(page, label):
    if page.get_by_role("button", name="Open navigation").is_visible():
        page.get_by_role("button", name="Open navigation").click()
        nav = page.get_by_role("navigation", name="Mobile primary navigation")
    else:
        nav = page.get_by_role("navigation", name="Primary navigation")
    nav.get_by_role("link", name=label, exact=True).click()


def _check_navigation(page, origin, prefix=""):
    """Exercise browser-owned route/query history, not component implementation."""
    root = f"{origin}{prefix}/"
    about = f"{origin}{prefix}/about"
    what_we_do = f"{origin}{prefix}/what-we-do"
    workspace = f"{origin}{prefix}/workspace"
    new = f"{origin}{prefix}/workspace/new"

    response = page.goto(about, wait_until="domcontentloaded", timeout=30000)
    assert response is not None and response.status == 200
    assert page.url == about
    _assert_no_back_control(page)
    if page.get_by_role("button", name="Open navigation").is_visible():
        page.get_by_role("button", name="Open navigation").click()
        mobile = page.get_by_role("navigation", name="Mobile primary navigation")
        assert mobile.is_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("button", name="Open navigation")).to_be_focused()
    page.get_by_role("navigation", name="Breadcrumb").get_by_role("link", name="Home", exact=True).click()
    page.wait_for_url(root)
    _assert_no_back_control(page)

    page.goto(what_we_do, wait_until="domcontentloaded")
    page.get_by_role("link", name="Home", exact=True).last.click()
    page.wait_for_url(root)
    _click_primary(page, "About")
    page.wait_for_url(about)
    page.go_back()
    page.wait_for_url(root)
    page.go_forward()
    page.wait_for_url(about)
    page.go_back()
    page.wait_for_url(root)

    page.goto(f"{new}?tab=brief", wait_until="domcontentloaded")
    page.get_by_label("Project name").fill("History draft")
    page.get_by_label("Describe the product").fill(
        "A draft retained while navigating public pages and returning to the workflow."
    )
    _click_primary(page, "Home")
    page.wait_for_url(root)
    _assert_no_back_control(page)
    page.go_back()
    page.wait_for_url(f"{new}?tab=brief")
    assert page.get_by_label("Project name").input_value() == "History draft"
    assert page.get_by_label("Describe the product").input_value().startswith("A draft retained")
    page.get_by_role("navigation", name="Breadcrumb").get_by_role(
        "link", name="Home", exact=True
    ).click()
    page.wait_for_url(root)
    _click_primary(page, "About")
    page.wait_for_url(about)
    page.go_back()
    page.wait_for_url(root)
    page.go_forward()
    page.wait_for_url(about)
    page.go_back()
    page.wait_for_url(root)
    _click_primary(page, "Workspace")
    page.wait_for_url(workspace)
    _open_nav(page, "Start New")
    page.wait_for_url(new)
    assert page.get_by_label("Project name").input_value() == "History draft"
    assert page.get_by_label("Describe the product").input_value().startswith("A draft retained")

    page.get_by_role("tab", name="Demo Studio", exact=True).click()
    page.wait_for_url(f"{new}?tab=demo")
    page.go_back(wait_until="commit")
    page.wait_for_timeout(100)
    assert page.url == new, page.url
    assert page.get_by_role("tab", name="Brief", exact=True).get_attribute("data-state") == "active"
    page.go_forward(wait_until="commit")
    page.wait_for_timeout(100)
    assert page.url == f"{new}?tab=demo", page.url
    assert page.get_by_role("tab", name="Demo Studio", exact=True).get_attribute("data-state") == "active"

    nested = page.goto(f"{new}?tab=demo", wait_until="domcontentloaded", timeout=30000)
    assert nested is not None and nested.status == 200
    assert page.url == f"{new}?tab=demo"
    page.get_by_role("button", name="Back to brief", exact=True).click()
    page.wait_for_url(f"{new}?tab=brief")
    expect(page.get_by_role("tab", name="Brief", exact=True)).to_be_focused()
    _assert_no_back_control(page)
    page.go_back()
    page.wait_for_url(f"{new}?tab=demo")
    page.get_by_role("navigation", name="Breadcrumb").get_by_role(
        "link", name="Workspace", exact=True
    ).click()
    page.wait_for_url(workspace)
    page.go_back()
    page.wait_for_url(f"{new}?tab=demo")
    missing_asset = page.request.get(f"{origin}{prefix}/assets/navigation-smoke-missing.js")
    assert missing_asset.status == 404


def _check_hosted(page, base_url):
    deep_response = page.goto(f"{base_url}/about", wait_until="domcontentloaded", timeout=30000)
    assert deep_response is not None and deep_response.status == 200
    page.goto(f"{base_url}/workspace/new?tab=brief", wait_until="domcontentloaded", timeout=30000)
    page.get_by_role("heading", name="Start New").wait_for()
    start_tabs = page.get_by_label("Start New workflow")
    start_tabs.get_by_role("tab", name="Local run").click()
    start_tabs.get_by_role("tab", name="Brief").click()
    page.get_by_label("Project name").fill("Browser draft")
    page.get_by_label("Describe the product").fill("A small product brief for browser smoke coverage.")
    start_tabs.get_by_role("tab", name="Demo Studio").click()
    page.get_by_role("button", name="Edit script").click()
    page.get_by_label("Headline").fill("Edited start headline")
    page.get_by_role("button", name="Back to brief", exact=True).click()
    expect(start_tabs.get_by_role("tab", name="Brief", exact=True)).to_be_focused()
    assert page.get_by_label("Project name").input_value() == "Browser draft"
    _assert_no_back_control(page)
    start_tabs.get_by_role("tab", name="Demo Studio").click()
    assert page.get_by_label("Headline").input_value() == "Edited start headline"
    _open_nav(page, "Evolve")
    evolve_tabs = page.get_by_label("Evolve workflow")
    evolve_tabs.get_by_role("tab", name="Brief").click()
    page.get_by_label("Repository URL or name").fill("Billing service")
    page.get_by_label("What should be improved?").fill("Review a bounded change in the billing service.")
    evolve_tabs.get_by_role("tab", name="Demo Studio").click()
    page.get_by_role("button", name="Edit script").click()
    page.get_by_label("Headline").fill("Edited evolve headline")
    with page.expect_download() as download_info:
        page.get_by_role("button", name="Export storyboard").click()
    exported = json.loads(download_info.value.path().read_text())
    assert exported["id"] == "evolve"
    assert exported["context"]["journey"] == "evolve"
    assert exported["context"]["title"] == "Billing service"
    assert exported["context"]["brief"] == "Review a bounded change in the billing service."
    assert any(scene["headline"] == "Edited evolve headline" for scene in exported["scenes"])
    page.get_by_role("button", name="Back to brief", exact=True).click()
    expect(evolve_tabs.get_by_role("tab", name="Brief", exact=True)).to_be_focused()
    assert page.get_by_label("Repository URL or name").input_value() == "Billing service"
    _assert_no_back_control(page)
    _open_nav(page, "Start New")
    page.get_by_role("tab", name="Demo Studio").click()
    assert page.get_by_label("Headline").input_value() == "Edited start headline"
    _assert_no_overflow(page)


def _check_local(page, api_url):
    deep_response = page.goto(f"{api_url}/studio/about", wait_until="domcontentloaded", timeout=30000)
    assert deep_response is not None and deep_response.status == 200
    page.goto(f"{api_url}/studio", wait_until="domcontentloaded", timeout=30000)
    assert page.url.endswith("/studio/")
    _click_primary(page, "Workspace")
    page.wait_for_url(f"{api_url}/studio/workspace")
    _open_nav(page, "Evolve")
    page.get_by_role("tab", name="Local run", exact=True).click()
    page.get_by_role("button", name="Sign in to local demo").click()
    page.get_by_role("button", name="Import & analyze").wait_for()
    page.get_by_label("Repository ZIP").set_input_files({
        "name": "smoke.zip",
        "mimeType": "application/zip",
        "buffer": _archive(),
    })
    page.get_by_role("button", name="Import & analyze").click()
    page.get_by_text("Task timeline").wait_for(timeout=20000)
    page.get_by_text("Import another snapshot", exact=True).click()
    archive_input = page.get_by_label("Repository ZIP")
    import_button = page.get_by_role("button", name="Import & analyze", exact=True)
    assert archive_input.evaluate("(input) => input.files.length") == 0
    assert import_button.is_disabled(), "A new import must require a fresh file selection"
    archive_input.set_input_files({
        "name": "another-snapshot.zip",
        "mimeType": "application/zip",
        "buffer": _archive(),
    })
    assert import_button.is_enabled()
    archive_input.set_input_files([])
    assert import_button.is_disabled()
    page.get_by_text("Import another snapshot", exact=True).click()
    page.get_by_role("button", name="Cancel analysis").click()
    page.get_by_role("heading", name="Canceled").wait_for(timeout=20000)
    page.get_by_text("recorded events").wait_for()
    _assert_no_overflow(page)


def _check_spatial_scene(page, origin):
    """The optional renderer must really draw, update while paused, and stop."""
    page.goto(origin, wait_until="domcontentloaded")
    scene = page.get_by_label("Illustrative product scene")
    scene.get_by_role("button", name="Open spatial view").click()
    canvas = scene.locator("canvas")
    expect(canvas).to_be_visible(timeout=20000)
    scene.get_by_role("button", name="Pause motion", exact=True).click()
    painted = "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    page.evaluate(painted)
    before = canvas.screenshot()
    scene.get_by_role("button", name="Code review", exact=True).click()
    page.evaluate(painted)
    selected = canvas.screenshot()
    assert selected != before, "Changing chapters while paused must update the visible scene"
    page.evaluate(painted)
    assert canvas.screenshot() == selected, "A paused scene must stay still between frames"
    page.emulate_media(reduced_motion="reduce")
    expect(canvas).to_have_count(0)
    expect(scene.get_by_role("article")).to_be_visible()
    expect(scene.get_by_role("button", name="Code review", exact=True)).to_have_attribute(
        "aria-pressed", "true")
    page.emulate_media(reduced_motion="no-preference")
    scene.get_by_role("button", name="Close spatial view", exact=True).click()
    expect(canvas).to_have_count(0)
    expect(scene.get_by_role("button", name="Open spatial view")).to_be_focused()
    print("PASS real spatial rendering, paused visual update, reduced motion and close focus")


def run():
    assert (ROOT / "index.html").is_file(), "Run npm build in apps/web/studio before browser smoke"
    api_url = os.environ.get("ORYVETA_SMOKE_API_URL")
    server = None
    thread = None
    if not api_url:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        api_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for label, width in (("desktop", 1440), ("tablet", 768), ("mobile", 390)):
                context = browser.new_context(viewport={"width": width, "height": 880})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                if os.environ.get("ORYVETA_SMOKE_API_URL"):
                    _check_navigation(page, api_url, "/studio")
                    _check_local(page, api_url)
                else:
                    _check_navigation(page, api_url)
                    _check_hosted(page, api_url)
                    if label == "desktop":
                        _check_spatial_scene(page, api_url)
                assert not errors, (label, errors)
                scenario = "local API lifecycle" if os.environ.get("ORYVETA_SMOKE_API_URL") else "hosted boundary and contextual story"
                print("PASS", label, scenario, "overflow")
                context.close()
            reduced = browser.new_context(reduced_motion="reduce", viewport={"width": 390, "height": 844})
            reduced_page = reduced.new_page()
            reduced_page.goto(f"{api_url}/studio/" if os.environ.get("ORYVETA_SMOKE_API_URL") else api_url, wait_until="domcontentloaded")
            if os.environ.get("ORYVETA_SMOKE_API_URL"):
                _check_local(reduced_page, api_url)
                assert reduced_page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
                completed_icon = reduced_page.locator(".lifecycle-tasks .task-complete svg")
                assert completed_icon.count() >= 1
                reduced_page.evaluate(
                    "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
                )
                assert reduced_page.locator(".lifecycle-tasks").evaluate(
                    "(node) => node.getAnimations({subtree: true}).every(animation => animation.playState !== 'running')"
                ), "Reduced motion must leave the lifecycle readable without running animations"
                print("PASS reduced-motion local lifecycle tasks")
            else:
                scene = reduced_page.get_by_label("Illustrative product scene")
                scene.get_by_role("button", name="Code review", exact=True).click()
                assert scene.locator(".scene-alternative").is_visible()
                document = scene.get_by_role("article").bounding_box()
                frame = scene.locator(".scene-viewport").bounding_box()
                assert document and frame
                assert document["y"] >= frame["y"]
                assert document["y"] + document["height"] <= frame["y"] + frame["height"], (
                    "The static document must remain readable without canvas clipping"
                )
                print("PASS reduced-motion React scene controls and static alternative")
            reduced.close()
            browser.close()
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=4)


if __name__ == "__main__":
    run()
