"""Browser smoke for Oryveta's preserved legacy local UI.

Tests guest sign-in, explicit preview access, mobile navigation, an
authenticated workspace lifecycle with a deterministic mocked Auth adapter and
navigation ordering when a superseded response arrives late.
No real OAuth secrets or external identity calls run in CI.
"""
from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

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


# The legacy shell's local mode talks to the self-hosted API. These deterministic payloads stand
# in for it exactly like FAKE_AUTH stands in for the hosted adapter: no server process, no
# credentials and no network. "p-gone" is listed but has no detail payload, which is what the
# real API returns for a project removed by another session.
LOCAL_API = {
    "/api/config": {"name": "Oryveta", "github_auth_enabled": False, "local_demo_enabled": True},
    "/api/me": {
        "id": "local-demo-user",
        "display_name": "Local Builder",
        "email": "builder@example.com",
        "csrf_token": "smoke-csrf-token",
    },
    "/api/projects": [
        {"id": "p-alpha", "name": "Alpha Service", "brief": "First project", "origin": "create",
         "status": "ready"},
        {"id": "p-beta", "name": "Beta Snapshot", "brief": "Second project", "origin": "import",
         "status": "ready"},
        {"id": "p-gone", "name": "Removed Elsewhere", "brief": "Deleted by another session",
         "origin": "create", "status": "ready"},
    ],
    "/api/overview": {"projects": 3, "active_jobs": 0, "verified_runs": 0},
    "/api/activity": [],
    "/api/ai/status": {"status": "disabled", "model": None},
    "/api/ai/budget": {"remaining_tokens": 20000},
    "/api/projects/p-alpha": {"id": "p-alpha", "name": "Alpha Service", "brief": "First project",
                              "origin": "create", "status": "ready", "files": [], "analysis": None},
    "/api/projects/p-beta": {"id": "p-beta", "name": "Beta Snapshot", "brief": "Second project",
                             "origin": "import", "status": "ready", "files": [], "analysis": None},
}

# Holds a chosen API response back inside the browser so a superseded navigation resolves after
# the user has already opened a newer page. `before` delays the request instead of the response,
# which is how a late failure is produced.
DELAYED_FETCH = """
'use strict';
window.__delayedApi={pattern:null,ms:0,before:false};
(() => {
 const realFetch=window.fetch;
 const pause=(ms)=>new Promise((resolve)=>setTimeout(resolve,ms));
 window.fetch=async(...args)=>{
  const target=String(args[0]&&args[0].url?args[0].url:args[0]);
  const plan=window.__delayedApi;
  const match=!!plan.pattern&&target.includes(plan.pattern);
  if(match&&plan.before)await pause(plan.ms);
  const response=await realFetch(...args);
  if(match&&!plan.before)await pause(plan.ms);
  return response;
 };
})();
"""


def serve_local_api(route):
    path = urlsplit(route.request.url).path
    if path in LOCAL_API:
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(LOCAL_API[path]))
        return
    route.fulfill(status=404, content_type="application/json",
                  body=json.dumps({"detail": "Project not found"}))


def hold(page, pattern: str, ms: int = 1200, before: bool = False):
    page.evaluate("plan => { window.__delayedApi = plan; }",
                  {"pattern": pattern, "ms": ms, "before": before})


def toast_text(page) -> str:
    return page.evaluate(
        "() => { const box = document.querySelector('#toast');"
        " return box.classList.contains('hidden') ? '' : box.textContent; }"
    )


def breadcrumb(page) -> str:
    return page.locator("#breadcrumb-current").inner_text()


def navigation_order(browser, origin: str) -> None:
    """Only the newest navigation may own shared state, the rendered page and its errors."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.add_init_script(DELAYED_FETCH)
    page.route("**/api/**", serve_local_api)
    page.goto(origin, wait_until="networkidle", timeout=30000)
    assert page.locator("#app").is_visible()
    assert breadcrumb(page) == "Overview"

    # A superseded list navigation must not replace a newer page or the draft typed into it.
    hold(page, "/api/projects")
    page.locator('#nav [data-page="projects"]').click()
    page.wait_for_timeout(100)
    page.locator('#nav [data-page="new"]').click()
    page.locator("#project-name").fill("Draft on the newer page")
    page.wait_for_timeout(1600)
    assert breadcrumb(page) == "Start New", breadcrumb(page)
    assert page.locator("#new-form").count() == 1
    assert page.locator("#project-name").input_value() == "Draft on the newer page"
    assert page.evaluate(
        "() => document.querySelector('#nav .nav-link.active')?.dataset.page"
    ) == "new"

    # A superseded detail navigation must not take over the project heading of a newer one.
    hold(page, "", 0)
    page.locator('#nav [data-page="projects"]').click()
    page.wait_for_selector('[data-project="p-alpha"]', timeout=15000)
    hold(page, "/api/projects/p-alpha")
    page.locator('[data-project="p-alpha"]').click()
    page.wait_for_timeout(100)
    page.locator('[data-project="p-beta"]').click()
    page.wait_for_timeout(1600)
    assert page.locator("#page h1").first.inner_text() == "Beta Snapshot", (
        page.locator("#page h1").first.inner_text()
    )

    # A superseded navigation that fails must not report its error on the newer page.
    hold(page, "", 0)
    page.locator('#nav [data-page="projects"]').click()
    page.wait_for_selector('[data-project="p-gone"]', timeout=15000)
    hold(page, "/api/projects/p-gone", before=True)
    page.locator('[data-project="p-gone"]').click()
    page.locator('#nav [data-page="new"]').click()
    page.locator("#project-name").fill("Draft kept after a failed older page")
    page.wait_for_timeout(1600)
    assert toast_text(page) == "", toast_text(page)
    assert breadcrumb(page) == "Start New"
    assert page.locator("#project-name").input_value() == "Draft kept after a failed older page"

    # Current navigations are untouched: they render, and their own failures still surface.
    hold(page, "", 0)
    page.locator('#nav [data-page="projects"]').click()
    page.wait_for_selector('[data-project="p-alpha"]', timeout=15000)
    assert breadcrumb(page) == "Projects"
    page.locator('[data-project="p-alpha"]').click()
    page.wait_for_selector("[data-run-scan]", timeout=15000)
    assert page.locator("#page h1").first.inner_text() == "Alpha Service"
    page.locator('#nav [data-page="projects"]').click()
    page.wait_for_selector('[data-project="p-gone"]', timeout=15000)
    page.locator('[data-project="p-gone"]').click()
    page.wait_for_timeout(500)
    assert toast_text(page) == "Project not found", toast_text(page)
    page.locator('#nav [data-page="activity"]').click()
    page.wait_for_timeout(300)
    assert breadcrumb(page) == "Activity"
    assert not errors, errors
    print("PASS navigation order: newest page owns state, draft and errors")
    page.close()


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

            navigation_order(browser, f"http://127.0.0.1:{server.server_port}/")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    run()
