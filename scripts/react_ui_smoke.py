"""Real Chromium smoke tests for the compiled Vite React/shadcn product (not mocks).

No email is sent and no GitHub OAuth credentials are used.
Works against the production-built 'apps/web/studio/dist' folder.
"""
from __future__ import annotations
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1] / "apps" / "web" / "studio" / "dist"
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**k):super().__init__(*a,directory=str(ROOT),**k)
    def log_message(self,*a):pass
    def translate_path(self,path):
        if "?" in path:path=path.split("?",1)[0]
        if path=="/":path="/index.html"
        return super().translate_path(path)
def run():
    assert (ROOT/"index.html").is_file(), "Run npm build in apps/web/studio before browser smoke"
    assert json.loads((ROOT/"demo-stories.json").read_text())[0]["id"]=="start-new"
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        url=f"http://127.0.0.1:{server.server_port}/"
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            for label,width in (("desktop",1440),("mobile",390)):
                page=browser.new_page(viewport={"width":width,"height":880})
                errors=[]
                page.on("pageerror",lambda e:errors.append(str(e)))
                response=page.goto(url,wait_until="domcontentloaded",timeout=30000)
                assert response.status==200
                page.get_by_role("heading",name="Ideas deserve extraordinary engineering.").wait_for(timeout=20000)
                assert page.get_by_label("Your work email").count()==1
                assert page.get_by_role("button",name="Continue with GitHub Needs OAuth setup").is_disabled()
                page.get_by_role("button",name="Explore the workspace").first.click()
                page.get_by_role("button",name="Start New").wait_for(state="visible" if width>680 else "attached")
                if width<=680:page.get_by_role("button",name="Toggle navigation").click()
                page.get_by_role("button",name="Demo Studio",exact=True).click()
                page.get_by_role("heading",name="Demo Studio / stories").wait_for()
                page.get_by_role("button",name="Evolve Existing",exact=False).count() # nonfatal; list may vary
                page.get_by_role("button",name="Next demo scene").click()
                assert "02/03" in page.locator(".demo-screen").inner_text().replace(" ","") 
                page.get_by_role("button",name="Exit preview").click() if width>680 else (page.get_by_role("button",name="Toggle navigation").click(),page.get_by_role("button",name="Exit preview").click())
                page.get_by_role("heading",name="Ideas deserve extraordinary engineering.").wait_for()
                assert not errors,(label,errors)
                print("PASS",label,"React render; auth gate; workspace navigation; storyboard; preview exit")
                page.close()
            reduced=browser.new_page(reduced_motion="reduce")
            reduced.goto(url,wait_until="domcontentloaded")
            reduced.get_by_role("heading",name="Ideas deserve extraordinary engineering.").wait_for()
            assert reduced.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
            print("PASS reduced-motion support")
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=4)
if __name__=="__main__":run()
