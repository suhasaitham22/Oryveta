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
import threading
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "apps" / "web" / "studio" / "dist"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_args):
        pass

    def translate_path(self, path):
        if "?" in path:
            path = path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        return super().translate_path(path)


def _archive() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("snapshot/app.py", "def run():\n    return 'ok'\n")
    return stream.getvalue()


def _assert_no_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def _open_nav(page, label, width):
    if width <= 680:
        page.get_by_role("button", name="Open workspace menu").click()
    page.get_by_role("button", name=label, exact=True).first.click()




def _check_chapters(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    controls = page.get_by_label("Product story chapters").get_by_role("button")
    artifact = page.locator(".story-artifact")
    expected = ("start-new", "evolve", "work", "handoff")

    def select_all():
        for index, chapter in enumerate(expected):
            controls.nth(index).focus()
            controls.nth(index).press("Enter")
            page.wait_for_function(
                "chapter => document.querySelector('.story-artifact').dataset.activeChapter === chapter",
                arg=chapter,
            )
            # Wait for native smooth scrolling to settle, not an invented run clock.
            page.wait_for_timeout(900)
            assert artifact.get_attribute("data-active-chapter") == chapter
            active = artifact.locator(".artifact-content[aria-hidden=false]")
            assert active.count() == 1 and active.is_visible()
            assert active.evaluate("(node) => node.scrollHeight <= node.clientHeight + 1")

    select_all()
    first = page.locator(".scroll-chapter").first
    start, height = first.evaluate(
        "(node) => [node.getBoundingClientRect().top + scrollY, node.getBoundingClientRect().height]"
    )
    transforms = []
    for position in (start, start + height * 0.8):
        page.evaluate("(top) => scrollTo({top, behavior: 'instant'})", position)
        page.wait_for_timeout(120)
        transforms.append(artifact.locator(".artifact-content").evaluate_all(
            "(nodes) => nodes.map(node => getComputedStyle(node).transform)"
        ))
    assert transforms[0] != transforms[1], "Native scroll must transform the product composition"

    # Changing the preference in an already-open page must stop motion.
    page.emulate_media(reduced_motion="reduce")
    select_all()
    assert artifact.locator(".artifact-content[aria-hidden=false]").evaluate(
        "(node) => getComputedStyle(node).transform"
    ) == "none"
    page.evaluate("document.body.style.zoom = '1.5'")
    select_all()
    page.evaluate("document.body.style.zoom = ''")
    page.emulate_media(reduced_motion="no-preference")
    _assert_no_overflow(page)


def _check_hosted(page, base_url, width):
    page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
    page.get_by_role("button", name="Start New", exact=True).first.click()
    page.get_by_role("heading", name="Start New").wait_for()
    start_tabs = page.get_by_label("Start New workflow")
    start_tabs.get_by_role("tab", name="Local run").click()
    assert page.get_by_text("Cloud execution is not connected.").count() == 1
    assert page.get_by_text("Illustration · not running").count() == 1
    nav = page.get_by_role("navigation", name="Workspace navigation")
    assert nav.get_by_role("button", name="Demo Studio", exact=True).count() == 0
    start_tabs.get_by_role("tab", name="Brief").click()
    page.get_by_label("Project name").fill("Browser draft")
    page.get_by_label("Describe the product").fill("A small product brief for browser smoke coverage.")
    start_tabs.get_by_role("tab", name="Demo Studio").click()
    page.get_by_role("button", name="Edit script").click()
    page.get_by_label("Headline").fill("Edited start headline")
    _open_nav(page, "Evolve", width)
    evolve_tabs = page.get_by_label("Evolve workflow")
    evolve_tabs.get_by_role("tab", name="Brief").click()
    page.get_by_label("Repository URL or name").fill("Billing service")
    page.get_by_label("What should be improved?").fill("Review a bounded change in the billing service.")
    evolve_tabs.get_by_role("tab", name="Demo Studio").click()
    assert page.locator('[aria-label="Evolve story"]').count() == 1
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
    _open_nav(page, "Start New", width)
    page.get_by_role("tab", name="Demo Studio").click()
    assert page.get_by_label("Headline").input_value() == "Edited start headline"
    assert page.locator('[aria-label="Evolve story"]').count() == 0
    _assert_no_overflow(page)


def _check_local(page, api_url, width):
    page.goto(f"{api_url}/studio", wait_until="domcontentloaded", timeout=30000)
    assert page.url.endswith("/studio/")
    page.get_by_role("heading", name="What are you working on?").wait_for(timeout=20000)
    if width <= 680:
        page.get_by_role("button", name="Open workspace menu").click()
    page.get_by_role("button", name="Evolve", exact=True).first.click()
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
    page.get_by_role("button", name="Cancel analysis").click()
    page.get_by_role("heading", name="Canceled").wait_for(timeout=20000)
    page.get_by_text("recorded events").wait_for()
    _assert_no_overflow(page)


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
            for label, width in (("desktop", 1440), ("mobile", 390)):
                context = browser.new_context(viewport={"width": width, "height": 880})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                if os.environ.get("ORYVETA_SMOKE_API_URL"):
                    _check_local(page, api_url, width)
                else:
                    # Static mode proves the hosted boundary and draft/story UX.
                    _check_chapters(page, api_url)
                    _check_hosted(page, api_url, width)
                assert not errors, (label, errors)
                scenario = "local API lifecycle" if os.environ.get("ORYVETA_SMOKE_API_URL") else "hosted boundary and contextual story"
                print("PASS", label, scenario, "overflow")
                context.close()
            reduced = browser.new_context(reduced_motion="reduce", viewport={"width": 390, "height": 844})
            reduced_page = reduced.new_page()
            reduced_page.goto(f"{api_url}/studio/" if os.environ.get("ORYVETA_SMOKE_API_URL") else api_url, wait_until="domcontentloaded")
            if os.environ.get("ORYVETA_SMOKE_API_URL"):
                _check_local(reduced_page, api_url, 390)
                assert reduced_page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
                completed_icon = reduced_page.locator(".lifecycle-tasks .task-complete svg")
                assert completed_icon.count() >= 1
                assert completed_icon.first.evaluate("(node) => getComputedStyle(node).animationName") == "none"
                assert reduced_page.locator(".lifecycle-tasks .task-complete").first.evaluate(
                    "(node) => getComputedStyle(node).transitionDuration"
                ) == "0s"
                print("PASS reduced-motion local lifecycle tasks")
            else:
                story_chapter = reduced_page.get_by_label("Product story chapters").get_by_role("button").nth(1)
                story_chapter.focus()
                reduced_page.keyboard.press("Enter")
                reduced_page.wait_for_function(
                    "document.querySelector('.story-artifact').dataset.activeChapter === 'evolve'"
                )
                scene = reduced_page.locator(".artifact-content[aria-hidden=false]")
                assert scene.is_visible()
                assert scene.evaluate("(node) => getComputedStyle(node).transform") == "none"
                assert scene.evaluate("(node) => getComputedStyle(node).transitionDuration") == "0s"
                print("PASS reduced-motion React chapter keyboard and visible static scene")
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
