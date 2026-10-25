"""Exercise the historical static prototype; no backend or auth is simulated."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "preview"


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def run():
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for width in (1440, 390):
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    errors, external_requests = [], []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("request", lambda request: external_requests.append(request.url)
                            if urlsplit(request.url).hostname not in {"127.0.0.1", None} else None)
                    page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")
                    page.locator('[data-route="start"]:visible').first.click()
                    name = "Client's <portal>"
                    brief = "Keep each client's documents private and show missing requirements."
                    page.locator("#project-name").fill(name)
                    page.locator("#project-brief").fill(brief)
                    page.locator('#brief-form button[type="submit"]').click()
                    expect(page.locator("#brief-result b")).to_have_text(name)
                    with page.expect_download() as download:
                        page.locator("#save-plan").click()
                    exported = json.loads(download.value.path().read_text())
                    assert exported["name"] == name
                    assert exported["brief"] == brief
                    assert exported["type"] == "scope-preview"
                    assert exported["actual_repository_created"] is False
                    page.locator('[data-route="evolve"]:visible').first.click()
                    repository = "https://github.com/example/repository"
                    page.locator("#repo-url").fill(repository)
                    page.locator('#import-form button[type="submit"]').click()
                    expect(page.locator("#import-result code")).to_have_text(repository)
                    page.locator('[data-route="activity"]:visible').first.click()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    assert not external_requests, external_requests
                    assert not errors, errors
                    page.close()
                    print(f"PASS historical preview {width}px: escaped draft export, local-only repository preview, navigation")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    run()
