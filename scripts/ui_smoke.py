"""Browser smoke for the deployable Oryveta web UI.

Runs a local static server with the same /static/* rewrites as apps/web/vercel.json.
Checks desktop/mobile rendering, navigation, assets, and read-only fallback.
"""

from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1] / "apps" / "web"
CONFIG = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
REWRITES = {item["source"]: item["destination"] for item in CONFIG["rewrites"]}


class StaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.send_error(404, "API intentionally unavailable in static preview")
            return
        super().do_GET()

    def translate_path(self, path):
        return super().translate_path(REWRITES.get(path, path))


def run() -> None:
    assert REWRITES["/static/app.js"] == "/app.js"
    assert REWRITES["/static/styles.css"] == "/styles.css"
    server = ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/?preview=1"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for label, viewport in (
                ("desktop", {"width": 1440, "height": 900}),
                ("mobile", {"width": 390, "height": 844}),
            ):
                page = browser.new_page(viewport=viewport)
                errors: list[str] = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                response = page.goto(url, wait_until="networkidle", timeout=30000)
                assert response is not None and response.status == 200
                assert page.locator("#app").is_visible(), (label, errors)
                assert page.locator("#page h1").inner_text() == "Good software gets better."
                assert "public UI preview" in page.locator("#page").inner_text()
                assert page.evaluate("document.styleSheets.length") >= 1
                assert page.locator("#app").bounding_box()["width"] > 300
                if label == "mobile":
                    page.locator("#mobile-menu").click()
                    assert page.locator("#nav").is_visible()
                page.locator('#nav [data-page="new"]').click()
                assert page.locator("#page h1").inner_text() == "From idea to repository."
                if label == "mobile":
                    # Navigation intentionally closes the mobile drawer after selection.
                    page.locator("#mobile-menu").click()
                    assert page.locator("#nav").is_visible()
                page.locator('#nav [data-page="evolve"]').click()
                assert page.locator("#page h1").inner_text() == "Great software never stands still."
                assert not errors, (label, errors)
                print(f"PASS {label}: app visible, CSS loaded, Start New/Evolve navigate, no JS errors")
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    run()
