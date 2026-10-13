"""Browser smoke for Oryveta's preserved legacy local UI.

Tests guest sign-in, explicit preview access, mobile navigation and an
authenticated workspace lifecycle with a deterministic mocked Auth adapter.
No real OAuth secrets or external identity calls run in CI.
"""
from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "apps" / "web"


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
        # Match FastAPI's local /static mount, not the separate hosted React build.
        if path.startswith("/static/"):
            path = path[len("/static"):]
        return super().translate_path(path)


FAKE_AUTH = """
'use strict';
(() => {
 const owner='11111111-1111-4111-8111-111111111111';
 let spaces=[];
 window.OryvetaCloudAuth={
  configured:()=>true,
  identity:async()=>({id:owner,email:'founder@example.com',user_metadata:{full_name:'Test Founder'}}),
  signIn:async()=>{},signOut:async()=>{},
  workspaces:async()=>spaces.slice(),
  createWorkspace:async(input)=>{
   const w={...input,id:'22222222-2222-4222-8222-222222222222',created_by:owner,created_at:new Date().toISOString()};
   spaces=[w,...spaces];return w;
  },
  updateWorkspace:async(id,input)=>{
   spaces=spaces.map(w=>w.id===id?{...w,...input}:w);
   return spaces.find(w=>w.id===id);
  }
 };
})();
"""


def run() -> None:
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
                for name in ("app.js", "styles.css", "cloud-auth.js", "cloud-config.js", "experience.js"):
                    asset = page.request.get(f"http://127.0.0.1:{server.server_port}/static/{name}")
                    assert asset.status == 200
                    mime = asset.headers.get("content-type", "").split(";", 1)[0]
                    expected = {"text/css"} if name.endswith(".css") else {
                        "text/javascript", "application/javascript"
                    }
                    assert mime in expected, (name, mime)
                assert page.locator("#login").is_visible()
                assert not page.locator("#app").is_visible()
                assert page.locator("#github-login").is_hidden()
                assert page.locator("#preview-login").is_visible()
                assert page.locator("#email-login-form").is_visible()
                assert page.locator("#story-tab-build").is_visible()
                page.locator("#story-tab-build").focus()
                page.keyboard.press("ArrowRight")
                assert page.locator("#story-tab-evolve").get_attribute("aria-selected") == "true"
                assert page.locator("#story-panel-build").is_hidden()
                assert page.locator("#story-panel-evolve").is_visible()
                page.locator("#story-tab-proof").click()
                assert page.locator("#story-panel-proof").is_visible()
                page.locator("#story-explore").click()
                assert page.locator("#app").is_visible()
                if label == "mobile":
                    page.locator("#mobile-menu").click()  # Exit action lives in the collapsible sidebar.
                assert page.locator("#logout").is_visible()
                assert page.locator("#logout").get_attribute("aria-label") == "Exit preview"
                page.locator("#logout").click()
                page.locator("#login").wait_for(state="visible")
                assert page.locator("#app").is_hidden()
                page.locator("#preview-login").click()
                assert page.locator("#app").is_visible()
                if not page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"):
                    print("MOBILE OVERFLOW:", page.evaluate("""() => ({
                        viewport: innerWidth, content: document.documentElement.scrollWidth,
                        nodes: [...document.querySelectorAll('body *')].filter(e => {
                          const r=e.getBoundingClientRect();
                          return r.width && (r.right > innerWidth + 2 || r.left < -2) &&
                            getComputedStyle(e).display !== 'none'
                        }).slice(0,25).map(e => ({tag:e.tagName,cls:e.className?.baseVal || e.className,
                          id:e.id, rect:e.getBoundingClientRect().toJSON()}))
                    })"""), flush=True)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), label
                if label == "mobile":
                    page.locator("#mobile-menu").click()
                    assert page.locator("#nav").is_visible()
                page.locator('#nav [data-page="new"]').click()
                assert page.locator("#new-form").is_visible()
                page.locator("#project-name").fill("Preview project")
                assert page.locator("#project-name").input_value() == "Preview project"
                if label == "mobile":
                    page.locator("#mobile-menu").click()
                page.locator('#nav [data-page="evolve"]').click()
                assert page.locator("#github-import").is_visible()
                assert page.locator("#new-form").count() == 0
                assert not errors, (label, errors)
                print(f"PASS {label}: sign-in gate, explicit preview, Start New/Evolve, no JS errors")
                page.close()

            # Auth adapter mock checks onboarding behavior, not provider correctness.
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.route("**/static/cloud-auth.js", lambda route: route.fulfill(
                status=200, content_type="application/javascript", body=FAKE_AUTH
            ))
            page.goto(url, wait_until="networkidle", timeout=30000)
            assert page.locator("#app").is_visible()
            assert page.locator("#login").is_hidden()
            assert page.locator("#profile-name").inner_text() == "Test Founder"
            page.locator("#workspace-name").fill("Acme Engineering")
            page.locator("#workspace-slug").fill("acme-engineering")
            page.locator("#workspace-description").fill("Private product workspace")
            page.locator("#workspace-create-button").click()
            assert page.locator("#workspace-switch-name").inner_text() == "Acme Engineering"
            assert page.locator(".workspace-card.selected").count() == 1
            page.locator("#workspace-edit-name").fill("Acme Product Studio")
            page.locator("#workspace-save-button").click()
            assert page.locator("#workspace-switch-name").inner_text() == "Acme Product Studio"
            assert not errors, errors
            print("PASS mocked auth: first-workspace onboarding, owner update, account chrome")
            page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    run()
     server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    run()
