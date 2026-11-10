"""Real-browser regressions for Studio collaboration response ordering.

Response-ordering and bounded-history behaviours are exercised against an
isolated local Supabase stack and a production Studio build with real Auth:

  * stale_chat_details   selecting another conversation must not keep the
                         previous conversation's messages or its actionable
                         invitations on screen
  * chat_refresh_order   a late conversation list must not hide a conversation
                         that was just created
  * chat_draft_clobber   a late send acknowledgement must not erase composer
                         text typed after the submitted message
  * project_draft_clobber a save acknowledgement that arrives after the page was
                         left and reopened must not erase the newer brief
  * chat_history_window  a message sent past the read window must stay visible
                         while the read stays bounded and deterministic
  * chat_creation_draft  creation must preserve a newer unsaved conversation title
  * chat_creation_after_navigation an old page must not clear a new page's title
  * invitation_draft    an acknowledgement must preserve the next unsent recipient
  * workspace_refresh_order a late workspace list must not hide a workspace that
                         was just created
  * workspace_save_after_leaving a settings save that outlives its page instance
                         must not cancel the newer new-workspace selection
  * workspace_initial_error a failed old mount read must not override a newer save
  * workspace_create_after_leaving a creation acknowledged after navigation must
                         not replace the newer selection or draft

Successful responses and authentication come from the real local stack; no
response body, status or success is invented. An in-page `fetch` wrapper delays
delivery of real responses to produce deterministic reordering. Transport-failure
coverage aborts an old read and delays delivery of its genuine rejection.

Pass JSON from `supabase status --output-format json` (flat, or with the values
under "env") on stdin or with --connections. Only loopback services are
accepted. The schema is applied with scripts/auth_ui_smoke.py's applier unless
--skip-sql is given. Fixture rows and the temporary Auth user are removed
afterwards. Requires httpx and Playwright.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import uuid

import httpx
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth_ui_smoke as ui  # noqa: E402  (sibling script, reused as a library)

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "apps/web/studio"
PORT = 4174
ORIGIN = f"http://127.0.0.1:{PORT}"
# Mirrors chatsApi.MESSAGE_WINDOW: the bounded message read the Studio performs.
MESSAGE_WINDOW = 200
HISTORY_BATCH = 50
# Time allowed for React to commit a released response before asserting that it
# changed nothing. The release itself is awaited in the page first.
SETTLE_MS = 900

HOLD_HARNESS = """
(() => {
  const rules = [];
  const native = window.fetch.bind(window);
  const find = (label) => rules.find((rule) => rule.label === label);
  window.__holds = {
    add(rule) {
      if (find(rule.label)) throw new Error("duplicate hold " + rule.label);
      rules.push({ ...rule, method: (rule.method || "GET").toUpperCase(), state: "waiting" });
    },
    state(label) { const rule = find(label); return rule ? rule.state : "missing"; },
    status(label) { const rule = find(label); return rule ? rule.status || 0 : 0; },
    release(label) {
      const rule = find(label);
      if (!rule) throw new Error("no hold " + label);
      rule.released = true;
      if (rule.resolve) rule.resolve();
      return rule.state;
    },
    releaseAll() {
      rules.forEach((rule) => { rule.released = true; if (rule.resolve) rule.resolve(); });
    },
    report() { return rules.map((rule) => rule.label + ":" + rule.state); },
  };
  window.fetch = function (input, init) {
    const href = typeof input === "string" ? input : (input && input.url) || "";
    let url = null;
    try { url = new URL(href, location.href); } catch (error) { url = null; }
    const method = ((init && init.method)
      || (input && typeof input === "object" && input.method) || "GET").toUpperCase();
    const rule = url && rules.find((candidate) => candidate.state === "waiting"
      && candidate.method === method
      && candidate.path === url.pathname
      && (!candidate.query || url.search.includes(candidate.query)));
    if (!rule) return native(input, init);
    rule.state = "requested";
    /* The real request goes out now. Only delivery of its real response to the
       application is deferred, so the application sees a genuine but late
       response rather than a fabricated one. */
    return native(input, init).then(
      (response) => {
        rule.status = response.status;
        rule.state = "held";
        if (rule.released) { rule.state = "delivered"; return response; }
        return new Promise((resolve) => {
          rule.resolve = () => { rule.state = "delivered"; resolve(response); };
        });
      },
      (error) => {
        if (!rule.holdError) { rule.state = "failed"; throw error; }
        rule.state = "held";
        if (rule.released) { rule.state = "delivered"; throw error; }
        return new Promise((resolve, reject) => {
          rule.resolve = () => { rule.state = "delivered"; reject(error); };
        });
      },
    );
  };
})();
"""


# ---------------------------------------------------------------------------
# Built Studio
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def studio(connection: dict, prebuilt: str | None):
    """Serve a production build of the Studio from a temporary directory."""
    env = dict(os.environ)
    env.update(
        VITE_SUPABASE_URL=connection["API_URL"],
        VITE_SUPABASE_PUBLISHABLE_KEY=connection["PUBLISHABLE_KEY"],
    )
    with contextlib.ExitStack() as resources:
        if prebuilt:
            directory = str(Path(prebuilt).resolve())
        else:
            directory = resources.enter_context(
                tempfile.TemporaryDirectory(prefix="oryveta-collab-build-"))
            subprocess.run(["npm", "run", "build", "--", "--outDir", directory],
                           cwd=STUDIO, env=env, check=True)
        logs = resources.enter_context(tempfile.TemporaryFile(mode="w+"))
        process = subprocess.Popen(
            ["node", "node_modules/vite/bin/vite.js", "preview", "--host", "127.0.0.1",
             "--port", str(PORT), "--strictPort", "--outDir", directory],
            cwd=STUDIO, env=env, stdout=logs, stderr=logs,
        )
        try:
            with httpx.Client(trust_env=False, timeout=1) as client:
                for _ in range(150):
                    if process.poll() is not None:
                        logs.seek(0)
                        raise RuntimeError(logs.read())
                    try:
                        if client.get(ORIGIN).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Built Studio did not become ready")
            yield directory
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


# ---------------------------------------------------------------------------
# Deferred delivery of real responses
# ---------------------------------------------------------------------------

def hold(page, label: str, path: str, method: str = "GET", query: str | None = None) -> None:
    page.evaluate("rule => window.__holds.add(rule)",
                  {"label": label, "path": path, "method": method, "query": query})


def hold_state(page, label: str) -> str:
    return page.evaluate("label => window.__holds.state(label)", label)


def wait_held(page, label: str, what: str, timeout: float = 30.0) -> None:
    """Block until the real response for `label` arrived and is being withheld."""
    deadline = time.monotonic() + timeout
    state = "missing"
    while time.monotonic() < deadline:
        state = hold_state(page, label)
        if state in {"held", "delivered"}:
            if state == "delivered":
                raise AssertionError(f"{what}: the {label} response was delivered before it "
                                     "could be withheld, so no ordering was exercised")
            return
        if state == "failed":
            raise AssertionError(f"{what}: the real {label} request failed in the browser")
        page.wait_for_timeout(50)
    raise AssertionError(f"{what}: the {label} request was never made (state {state}); "
                         "the page no longer performs the request this case orders")


def release(page, label: str, what: str, timeout: float = 15.0) -> int:
    """Deliver the withheld real response and let the application commit it."""
    status = page.evaluate("label => window.__holds.status(label)", label)
    page.evaluate("label => window.__holds.release(label)", label)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if hold_state(page, label) == "delivered":
            break
        page.wait_for_timeout(25)
    else:
        raise AssertionError(f"{what}: the withheld {label} response was never delivered")
    page.wait_for_timeout(SETTLE_MS)
    return status


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def sidebar_link(page, label: str):
    return page.locator("aside.workspace-sidebar").get_by_role("link", name=label, exact=True)


def open_chats(page) -> None:
    """Enter the chats page through in-application navigation, keeping the document
    (and therefore the registered holds and the shared draft provider) alive."""
    sidebar_link(page, "Private chats").click()
    expect(page.get_by_role("heading", name="Your private conversations", level=1)).to_be_visible(
        timeout=15000)


def open_projects(page) -> None:
    sidebar_link(page, "Projects").click()
    expect(page.get_by_role("heading", name="Your projects", level=1)).to_be_visible(timeout=15000)


def open_workspace_settings(page) -> None:
    sidebar_link(page, "Workspaces").click()
    expect(page.get_by_role("heading", name="Your space, your standards.", level=1)).to_be_visible(
        timeout=15000)


def site_link(page, label: str):
    return page.get_by_role("navigation", name="Primary navigation").get_by_role(
        "link", name=label, exact=True)


def leave_workspace_route(page) -> None:
    """Leave the workspace route, unmounting its page instance.

    The document stays alive, so the registered holds and the shared workspace list,
    selection and settings drafts above the route survive the departure.
    """
    site_link(page, "Home").click()
    expect(page.locator("aside.workspace-sidebar")).to_have_count(0, timeout=15000)


def enter_workspace_route(page) -> None:
    """Mount a new workspace page instance through in-application navigation."""
    site_link(page, "Workspace").click()
    expect(sidebar_link(page, "Workspaces")).to_be_visible(timeout=15000)


def count_mount_reads(page) -> int:
    """Enter the workspace route and count the workspace list reads one mount performs.

    A production build performs one read per mount; a development build mounts effects
    twice under StrictMode, where only the second read belongs to the live page
    instance. Measuring the real request count keeps the ordering cases exact on either
    build instead of assuming one.
    """
    seen: list[str] = []

    def record(request) -> None:
        if request.method == "GET" and urlsplit(request.url).path == "/rest/v1/workspaces":
            seen.append(request.url)

    page.on("request", record)
    try:
        enter_workspace_route(page)
        page.wait_for_timeout(SETTLE_MS)
    finally:
        page.remove_listener("request", record)
    return len(seen)


def space_choice(page, name: str):
    return page.locator(".choice-column").get_by_role("button", name=re.compile(re.escape(name)))


def conversation_button(page, title: str):
    return page.get_by_label("Conversations").get_by_role(
        "button", name=re.compile(re.escape(title)))


def select_conversation(page, title: str) -> None:
    conversation_button(page, title).click()
    expect(page.get_by_role("heading", name=title, level=2)).to_be_visible(timeout=15000)


def messages(page):
    return page.get_by_label("Chat messages").locator("article")


def no_alert(page, what: str) -> None:
    alerts = page.get_by_role("alert")
    if alerts.count():
        raise AssertionError(f"{what}: the page reported an error: {alerts.first.inner_text()}")


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def prove_stale_chat_details(page, fixtures, owner) -> None:
    """Details and their actions must belong to the selected conversation.

    Alpha's details load completely; Bravo is then selected while both of its
    detail responses are withheld. Alpha's message and Alpha's revocable
    invitation must leave the screen with Alpha, otherwise the owner can revoke
    Alpha's sharing from a screen that identifies Bravo.
    """
    case = "stale_chat_details"
    alpha, bravo = fixtures["alpha"], fixtures["bravo"]
    open_chats(page)
    select_conversation(page, alpha["title"])
    expect(page.get_by_text(fixtures["alpha_message"], exact=False)).to_be_visible(timeout=15000)
    expect(page.get_by_role("button", name="Revoke", exact=True)).to_have_count(1, timeout=15000)
    hold(page, "bravo-messages", "/rest/v1/chat_messages", "GET", f"chat_id=eq.{bravo['id']}")
    hold(page, "bravo-shares", "/rest/v1/chat_shares", "GET", f"chat_id=eq.{bravo['id']}")
    conversation_button(page, bravo["title"]).click()
    wait_held(page, "bravo-messages", case)
    wait_held(page, "bravo-shares", case)
    expect(page.get_by_role("heading", name=bravo["title"], level=2)).to_be_visible()
    if page.get_by_text(fixtures["alpha_message"], exact=False).count():
        raise AssertionError(
            f"{case}: while {bravo['title']} is named in the header, {alpha['title']}'s message "
            "is still rendered in the conversation log. Messages must be tied to the "
            "conversation that produced them.")
    revoke = page.get_by_role("button", name="Revoke", exact=True)
    if revoke.count():
        raise AssertionError(
            f"{case}: {alpha['title']}'s invitation for {fixtures['recipient']} is still offered "
            f"with a Revoke action while the header names {bravo['title']}. Clicking it deletes "
            f"the other conversation's share: RLS authorizes the owner, so only the page can "
            "keep the target straight.")
    if page.get_by_text(fixtures["recipient"], exact=False).count():
        raise AssertionError(
            f"{case}: {alpha['title']}'s recipient is still listed under {bravo['title']}")
    release(page, "bravo-messages", case)
    release(page, "bravo-shares", case)
    expect(page.get_by_text("No messages yet", exact=False)).to_be_visible(timeout=15000)
    if page.get_by_text(fixtures["alpha_message"], exact=False).count():
        raise AssertionError(f"{case}: {alpha['title']}'s message reappeared under "
                             f"{bravo['title']} after its own details loaded")
    expect(page.get_by_role("button", name="Revoke", exact=True)).to_have_count(0)
    shares = ui.ok(owner.get("/rest/v1/chat_shares",
                             params={"chat_id": f"eq.{alpha['id']}", "select": "id,chat_id"}))
    if len(shares) != 1:
        raise AssertionError(f"{case}: {alpha['title']} should still have exactly one invitation; "
                             f"the backend reports {shares}")
    # Revoking from the conversation that owns the invitation must still work, and must name
    # that conversation in the request rather than relying on the share id alone.
    select_conversation(page, alpha["title"])
    expect(page.get_by_role("button", name="Revoke", exact=True)).to_have_count(1, timeout=15000)
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == "/rest/v1/chat_shares"
    ) as pending:
        page.get_by_role("button", name="Revoke", exact=True).click()
    deleted = pending.value
    if not deleted.ok:
        raise AssertionError(f"{case}: revoking from its own conversation failed: HTTP "
                             f"{deleted.status}")
    if f"chat_id=eq.{alpha['id']}" not in urlsplit(deleted.url).query:
        raise AssertionError(f"{case}: the revocation identified only the share "
                             f"({urlsplit(deleted.url).query}), not the conversation it was "
                             "meant for")
    expect(page.get_by_role("status")).to_contain_text("Access revoked", timeout=15000)
    remaining = ui.ok(owner.get("/rest/v1/chat_shares",
                                params={"chat_id": f"eq.{alpha['id']}", "select": "id"}))
    if remaining:
        raise AssertionError(f"{case}: the invitation was not revoked; the backend still reports "
                             f"{remaining}")
    no_alert(page, case)
    print(f"{case}: selecting {bravo['title']} with both of its detail responses withheld left "
          f"no message, recipient or Revoke action from {alpha['title']} on screen, its "
          f"invitation stayed intact, and revoking it from {alpha['title']} itself named that "
          f"conversation and removed exactly that invitation", flush=True)


def prove_chat_refresh_order(page, fixtures, owner) -> None:
    """A conversation list from before a creation must not replace the list after it.

    The first conversation list is withheld, a conversation is created (its
    insert and the list that follows it both complete), and only then is the
    stale list delivered.
    """
    case = "chat_refresh_order"
    title = fixtures["charlie_title"]
    page.goto(f"{ORIGIN}/workspace")
    expect(sidebar_link(page, "Private chats")).to_be_visible(timeout=15000)
    hold(page, "initial-chats", "/rest/v1/chats", "GET")
    open_chats(page)
    wait_held(page, "initial-chats", case)
    page.get_by_label("New private conversation", exact=True).fill(title)
    page.get_by_role("button", name="Create conversation", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Private conversation created", timeout=30000)
    expect(conversation_button(page, title)).to_have_count(1, timeout=15000)
    release(page, "initial-chats", case)
    created = ui.ok(owner.get("/rest/v1/chats",
                              params={"title": f"eq.{title}", "select": "id,title"}))
    if len(created) != 1:
        raise AssertionError(f"{case}: the conversation was not created once: {created}")
    fixtures["charlie"] = created[0]
    if conversation_button(page, title).count() != 1:
        raise AssertionError(
            f"{case}: the conversation list captured before the creation was applied after it, so "
            f"{title} disappeared from the list although the page reports it was created and the "
            f"backend persisted {created[0]['id']}. Only the newest list may be committed.")
    if not page.get_by_role("heading", name=title, level=2).count():
        raise AssertionError(
            f"{case}: the stale list dropped the selection of the conversation that was just "
            f"created; the header no longer names {title}")
    no_alert(page, case)
    print(f"{case}: the conversation list fetched before the creation was discarded on arrival; "
          f"{title} stayed listed and selected", flush=True)


def prove_chat_draft_clobber(page, fixtures, owner) -> None:
    """A send acknowledgement may only clear the message it submitted."""
    case = "chat_draft_clobber"
    delta = fixtures["delta"]
    first = f"Submitted decision {fixtures['suffix']}"
    typed = f"Still being written {fixtures['suffix']}"
    open_chats(page)
    select_conversation(page, delta["title"])
    composer = page.get_by_label("Message", exact=True)
    expect(composer).to_be_visible(timeout=15000)
    composer.fill(first)
    hold(page, "send", "/rest/v1/chat_messages", "POST")
    page.get_by_role("button", name="Send message", exact=True).click()
    wait_held(page, "send", case)
    composer.fill(typed)
    release(page, "send", case)
    expect(page.get_by_text(first, exact=False)).to_be_visible(timeout=15000)
    value = composer.input_value()
    if value != typed:
        raise AssertionError(
            f"{case}: the acknowledgement of {first!r} cleared the composer down to {value!r} "
            f"instead of leaving the unsent {typed!r}. Only the submitted draft may be cleared.")
    stored = ui.ok(owner.get("/rest/v1/chat_messages",
                             params={"chat_id": f"eq.{delta['id']}", "select": "content"}))
    contents = [row["content"] for row in stored]
    if contents != [first]:
        raise AssertionError(f"{case}: the conversation should hold only the submitted message; "
                             f"the backend reports {contents}")
    composer.fill("")
    no_alert(page, case)
    print(f"{case}: the withheld send acknowledgement cleared only the submitted message; the "
          f"text typed while it was in flight survived and was not sent", flush=True)


def prove_project_draft_clobber(page, fixtures, owner) -> None:
    """A save acknowledgement that outlives its page must not erase a newer brief.

    The save response is withheld, the page is left and reopened (a new instance
    with no pending save of its own), the brief is edited again, and only then is
    the old acknowledgement delivered.
    """
    case = "project_draft_clobber"
    project = fixtures["project"]
    saved = f"Saved brief {fixtures['suffix']} for the held acknowledgement."
    newer = f"Newer brief {fixtures['suffix']} typed after returning to the page."
    open_projects(page)
    page.get_by_role("button", name=re.compile(re.escape(project["name"]))).first.click()
    brief = page.get_by_label("What is this project for?", exact=True)
    expect(brief).to_be_visible(timeout=15000)
    brief.fill(saved)
    hold(page, "project-save", "/rest/v1/rpc/update_project", "POST")
    page.get_by_role("button", name="Save project", exact=True).click()
    wait_held(page, "project-save", case)
    open_chats(page)
    open_projects(page)
    brief = page.get_by_label("What is this project for?", exact=True)
    expect(brief).to_have_value(saved, timeout=15000)
    brief.fill(newer)
    release(page, "project-save", case)
    stored = ui.row(ui.ok(owner.get("/rest/v1/projects",
                                    params={"id": f"eq.{project['id']}", "select": "brief"})))
    if stored["brief"] != saved:
        raise AssertionError(f"{case}: the withheld save did not persist its own brief; the "
                             f"backend holds {stored['brief']!r}")
    brief = page.get_by_label("What is this project for?", exact=True)
    value = brief.input_value()
    if value != newer:
        raise AssertionError(
            f"{case}: the save acknowledgement from the page instance that was left behind "
            f"deleted the brief typed after returning; the field now shows {value!r} instead of "
            f"{newer!r}. A completion must not write to a draft it no longer owns.")
    no_alert(page, case)
    print(f"{case}: the save acknowledgement that arrived after leaving and reopening the page "
          f"persisted its own brief and left the newer unsaved brief untouched", flush=True)


def prove_chat_creation_draft(page, fixtures, owner, *, leave_page=False) -> None:
    case = "chat_creation_after_navigation" if leave_page else "chat_creation_draft"
    submitted = f"Created {case} {fixtures['suffix']}"
    newer = f"Next conversation {case} {fixtures['suffix']}"
    open_chats(page)
    field = page.get_by_label("New private conversation", exact=True)
    field.fill(submitted)
    hold(page, case, "/rest/v1/chats", "POST")
    page.get_by_role("button", name="Create conversation", exact=True).click()
    wait_held(page, case, case)
    if leave_page:
        open_projects(page)
        open_chats(page)
        field = page.get_by_label("New private conversation", exact=True)
    field.fill(newer)
    release(page, case, case)
    expect(field).to_have_value(newer)
    stored = ui.ok(owner.get("/rest/v1/chats",
                             params={"title": f"eq.{submitted}", "select": "id"}))
    assert len(stored) == 1, "The acknowledged conversation must exist exactly once"
    field.fill("")
    print(f"{case}: an acknowledged creation preserved the newer unsaved title", flush=True)


def prove_chat_creation_after_navigation(page, fixtures, owner) -> None:
    prove_chat_creation_draft(page, fixtures, owner, leave_page=True)


def prove_invitation_draft(page, fixtures, owner) -> None:
    case = "invitation_draft"
    chat = fixtures["bravo"]
    submitted = f"submitted-{fixtures['suffix']}@example.test"
    newer = f"next-{fixtures['suffix']}@example.test"
    open_chats(page)
    select_conversation(page, chat["title"])
    field = page.get_by_label("Recipient", exact=True)
    field.fill(submitted)
    hold(page, case, "/rest/v1/chat_shares", "POST")
    page.get_by_role("button", name="Invite", exact=True).click()
    wait_held(page, case, case)
    field.fill(newer)
    release(page, case, case)
    expect(field).to_have_value(newer)
    stored = ui.ok(owner.get("/rest/v1/chat_shares", params={
        "chat_id": f"eq.{chat['id']}", "select": "recipient_email"}))
    assert [row["recipient_email"] for row in stored] == [submitted]
    field.fill("")
    print(f"{case}: an acknowledged invitation preserved the next unsent recipient", flush=True)


def prove_chat_history_window(page, fixtures, owner) -> None:
    """A message accepted past the read window must be visible, bounded and stable."""
    case = "chat_history_window"
    echo = fixtures["echo"]
    small = fixtures["delta"]
    tail = f"Message past the window {fixtures['suffix']}"
    omission = "Older messages in this conversation are not shown"

    def echo_read(response) -> bool:
        return (response.request.method == "GET"
                and urlsplit(response.url).path == "/rest/v1/chat_messages"
                and f"chat_id=eq.{echo['id']}" in urlsplit(response.url).query)

    def reopen_echo() -> list[dict]:
        """Select another conversation, then Echo, and return the window it read."""
        select_conversation(page, small["title"])
        with page.expect_response(echo_read) as pending:
            conversation_button(page, echo["title"]).click()
        response = pending.value
        if not response.ok:
            raise AssertionError(f"{case}: reading the conversation failed: HTTP "
                                 f"{response.status}")
        expect(page.get_by_role("heading", name=echo["title"], level=2)).to_be_visible(
            timeout=15000)
        page.wait_for_timeout(SETTLE_MS)
        return response.json()

    def bounded(read: list[dict], what: str) -> None:
        # The window itself, plus at most the single row that proves older history exists.
        if len(read) > MESSAGE_WINDOW + 1:
            raise AssertionError(f"{case}: {what} returned {len(read)} messages, so the read is "
                                 f"not bounded to {MESSAGE_WINDOW}")

    open_chats(page)
    window = reopen_echo()
    bounded(window, "the first conversation read")
    if len(window) != fixtures["echo_messages"]:
        raise AssertionError(f"{case}: the conversation holds {fixtures['echo_messages']} "
                             f"messages but the page read {len(window)}")
    if page.get_by_text(omission, exact=False).count():
        raise AssertionError(f"{case}: every message of this conversation fits in the window, "
                             "yet omitted older history is announced")
    composer = page.get_by_label("Message", exact=True)
    composer.fill(tail)
    with page.expect_response(echo_read) as pending:
        page.get_by_role("button", name="Send message", exact=True).click()
    if not pending.value.ok:
        raise AssertionError(f"{case}: the reload after sending failed: HTTP "
                             f"{pending.value.status}")
    page.wait_for_timeout(SETTLE_MS)
    accepted = ui.row(ui.ok(owner.get("/rest/v1/chat_messages", params={
        "chat_id": f"eq.{echo['id']}", "content": f"eq.{tail}", "select": "id"})))
    stored = ui.ok(owner.get("/rest/v1/chat_messages", params={
        "chat_id": f"eq.{echo['id']}", "select": "id", "limit": str(MESSAGE_WINDOW * 2)}))
    if len(stored) != fixtures["echo_messages"] + 1:
        raise AssertionError(f"{case}: the conversation holds {len(stored)} messages, expected "
                             f"{fixtures['echo_messages'] + 1}")
    if composer.input_value():
        raise AssertionError(f"{case}: the composer still holds "
                             f"{composer.input_value()!r} after the message was accepted")
    bounded(pending.value.json(), "the read after sending")
    rendered = messages(page).count()
    if rendered != MESSAGE_WINDOW:
        raise AssertionError(f"{case}: {rendered} messages are rendered, expected the bounded "
                             f"{MESSAGE_WINDOW}")
    if not page.get_by_text(tail, exact=False).count():
        raise AssertionError(
            f"{case}: the message the backend accepted as {accepted['id']} is not on screen "
            f"after the conversation reloaded. A conversation holding {len(stored) - 1} messages "
            "reads a window that cannot contain what was just sent.")
    last = messages(page).last.inner_text()
    if tail not in last:
        raise AssertionError(
            f"{case}: the accepted message is not the newest one on screen. The page shows "
            f"{last!r} last, so a conversation at the {MESSAGE_WINDOW}-message window hides what "
            "was just sent.")
    if not page.get_by_text(omission, exact=False).count():
        raise AssertionError(
            f"{case}: the conversation holds {len(stored)} messages but only {rendered} are "
            "readable, and nothing on screen says that older messages are omitted")
    reads = [[row["id"] for row in reopen_echo()] for _ in range(2)]
    for index, read in enumerate(reads):
        bounded(read, f"read {index + 1} of the reopened conversation")
        if read[0] != accepted["id"]:
            raise AssertionError(
                f"{case}: read {index + 1} of the reopened conversation does not include the "
                f"message that was just accepted ({accepted['id']}) as its newest row, so the "
                "window is not the newest one")
        if not page.get_by_text(tail, exact=False).count():
            raise AssertionError(f"{case}: reopening the conversation no longer shows the "
                                 "accepted message")
    if reads[0] != reads[1]:
        raise AssertionError(f"{case}: two identical reads of the same conversation returned "
                             "different windows, so the ordering is not deterministic")
    select_conversation(page, small["title"])
    if page.get_by_text(omission, exact=False).count():
        raise AssertionError(f"{case}: {small['title']} holds fewer messages than the window, so "
                             "nothing is omitted, yet omitted history is announced")
    no_alert(page, case)
    print(f"{case}: a conversation holding {len(stored)} messages showed the newly sent one "
          f"last, rendered exactly {MESSAGE_WINDOW} of them, reopened twice with an identical "
          f"bounded window led by the accepted message, announced the omitted older messages "
          f"only once some were omitted, and stayed silent in a short conversation", flush=True)


def prove_workspace_refresh_order(page, fixtures, owner) -> None:
    """A workspace list from before a creation must not replace the list after it.

    A new workspace page instance is mounted with its workspace list withheld, a
    workspace is created (its insert and the list that follows it both complete),
    and only then is the stale list delivered.
    """
    case = "workspace_refresh_order"
    name = fixtures["created_name"]
    existing = fixtures["workspace"]
    open_workspace_settings(page)
    expect(space_choice(page, existing["name"])).to_have_count(1, timeout=15000)
    leave_workspace_route(page)
    reads = count_mount_reads(page)
    if not reads:
        raise AssertionError(f"{case}: mounting the workspace route read no workspace list, so "
                             "this case no longer orders anything")
    leave_workspace_route(page)
    # Every read the mount performs is withheld, so the list that follows the creation is
    # the only one the page may commit while the initial reads are still in flight.
    labels = [f"initial-workspaces-{index + 1}" for index in range(reads)]
    for label in labels:
        hold(page, label, "/rest/v1/workspaces", "GET")
    enter_workspace_route(page)
    for label in labels:
        wait_held(page, label, case)
    open_workspace_settings(page)
    page.get_by_role("button", name="New workspace", exact=True).click()
    page.get_by_label("Workspace name", exact=True).fill(name)
    page.get_by_role("button", name="Create workspace", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Your private workspace is ready",
                                                       timeout=30000)
    rows = ui.ok(owner.get("/rest/v1/workspaces",
                           params={"name": f"eq.{name}", "select": "id,name,slug"}))
    if len(rows) != 1:
        raise AssertionError(f"{case}: the workspace was not created exactly once: {rows}")
    created = rows[0]
    fixtures["created_workspace"] = created
    expect(space_choice(page, name)).to_have_count(1, timeout=15000)
    for label in labels:
        release(page, label, case)
    if space_choice(page, name).count() != 1:
        raise AssertionError(
            f"{case}: the workspace list captured before the creation was applied after it, so "
            f"{name} disappeared from the list although the page reports it was created and the "
            f"backend persisted {created['id']}. Only the newest list may be committed.")
    if space_choice(page, name).get_attribute("aria-pressed") != "true":
        raise AssertionError(
            f"{case}: the stale list dropped the selection of the workspace that was just "
            f"created, so {name} is no longer the active workspace")
    shown = page.get_by_label("Workspace name", exact=True).input_value()
    if shown != name:
        raise AssertionError(
            f"{case}: the settings form moved to {shown!r} after the stale list arrived, so the "
            f"owner edits a workspace they did not select")
    readable = ui.ok(owner.get("/rest/v1/workspaces", params={"select": "id"}))
    listed = page.locator(".choice-column button.space-choice").count()
    if listed != len(readable):
        raise AssertionError(f"{case}: the page lists {listed} workspaces while the owner can "
                             f"read {len(readable)}")
    no_alert(page, case)
    page.get_by_role("button", name="New workspace", exact=True).click()
    expect(page.get_by_label("Workspace name", exact=True)).to_have_value("")
    print(f"{case}: the workspace list fetched before the creation was discarded on arrival; "
          f"{name} stayed listed, selected and editable", flush=True)


def prove_workspace_save_after_leaving(page, fixtures, owner) -> None:
    """A settings save that outlives its page must not cancel a newer selection.

    The save response is withheld, the workspace route is left and entered again
    (a new page instance with no pending save of its own), that instance is put on
    the deliberate new-workspace form, and only then is the old save acknowledged.
    """
    case = "workspace_save_after_leaving"
    space = fixtures["workspace"]
    saved = f"Saved description {fixtures['suffix']} from the page that was left."
    typed = f"Next workspace {fixtures['suffix']}"

    # Response delivery, not a particular follow-up read, orders the acknowledgement.

    open_workspace_settings(page)
    space_choice(page, space["name"]).click()
    # This label contains its textarea, so the label text grows with the value React
    # commits into it; matching the label loosely keeps the field addressable either way.
    description = page.get_by_label("What are you building?")
    expect(description).to_be_visible(timeout=15000)
    description.fill(saved)
    hold(page, "workspace-save", "/rest/v1/workspaces", "PATCH")
    page.get_by_role("button", name="Save settings", exact=True).click()
    wait_held(page, "workspace-save", case)
    leave_workspace_route(page)
    enter_workspace_route(page)
    open_workspace_settings(page)
    page.get_by_role("button", name="New workspace", exact=True).click()
    expect(page.get_by_role("heading", name="Your first workspace", level=2)).to_be_visible(
        timeout=15000)
    field = page.get_by_label("Workspace name", exact=True)
    field.fill(typed)
    status = release(page, "workspace-save", case)
    stored = ui.row(ui.ok(owner.get("/rest/v1/workspaces", params={
        "id": f"eq.{space['id']}", "select": "name,description"})))
    if stored["description"] != saved:
        raise AssertionError(f"{case}: the withheld save (HTTP {status}) did not persist its own "
                             f"description; the backend holds {stored['description']!r}")
    if stored["name"] != space["name"]:
        raise AssertionError(f"{case}: the save renamed the workspace to {stored['name']!r}")
    if not page.get_by_role("heading", name="Your first workspace", level=2).count():
        raise AssertionError(
            f"{case}: the save acknowledgement from the page instance that was left behind "
            f"replaced the deliberate new-workspace form with {space['name']}'s settings. A "
            "completion must not write to a selection it no longer owns.")
    shown = field.input_value()
    if shown != typed:
        raise AssertionError(
            f"{case}: the name typed on the new-workspace form was replaced by {shown!r} when "
            f"the old save was acknowledged, so the owner's next workspace name is lost")
    no_alert(page, case)
    print(f"{case}: the settings save acknowledged after the workspace route was left and "
          f"entered again persisted only its own description and left the newer "
          f"new-workspace selection and name untouched", flush=True)


def prove_workspace_initial_error(page, fixtures, owner) -> None:
    """A genuine transport failure belongs to the read that encountered it."""
    case = "workspace_initial_error"
    space = fixtures["workspace"]
    open_workspace_settings(page)
    expect(space_choice(page, space["name"])).to_have_count(1, timeout=15000)
    leave_workspace_route(page)
    reads = count_mount_reads(page)
    leave_workspace_route(page)
    assert reads, "The initial read was not observed"
    labels = [f"initial-error-{index}" for index in range(reads)]
    for label in labels:
        page.evaluate("rule => window.__holds.add(rule)", {
            "label": label, "path": "/rest/v1/workspaces", "holdError": True})
    workspace_url = str(owner.base_url).rstrip("/") + "/rest/v1/workspaces*"

    def disconnect(route):
        route.abort("connectionfailed")

    page.route(workspace_url, disconnect)
    try:
        enter_workspace_route(page)
        for label in labels:
            wait_held(page, label, case)
        page.unroute(workspace_url, disconnect)
        open_workspace_settings(page)
        space_choice(page, space["name"]).click()
        saved = f"Newer acknowledged save {fixtures['suffix']}"
        page.get_by_label("What are you building?").fill(saved)
        with page.expect_response(lambda response: response.request.method == "GET"
                                  and urlsplit(response.url).path == "/rest/v1/workspaces"):
            page.get_by_role("button", name="Save settings", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("Workspace settings saved")
        for label in labels:
            release(page, label, case)
        no_alert(page, case)
        expect(page.get_by_label("What are you building?")).to_have_value(saved)
        stored = ui.row(ui.ok(owner.get("/rest/v1/workspaces", params={
            "id": f"eq.{space['id']}", "select": "description"})))
        assert stored["description"] == saved
    finally:
        page.unroute(workspace_url, disconnect)
        for label in labels:
            page.evaluate("label => window.__holds.release(label)", label)
    print(f"{case}: failed superseded read did not replace current save feedback", flush=True)


def prove_workspace_create_after_leaving(page, fixtures, owner) -> None:
    """A completed create cannot select a record in an abandoned page instance."""
    case = "workspace_create_after_leaving"
    name = f"Abandoned create {fixtures['suffix']}"
    typed = f"Newer creation draft {fixtures['suffix']}"
    open_workspace_settings(page)
    expect(space_choice(page, fixtures["workspace"]["name"])).to_have_count(1, timeout=15000)
    page.get_by_role("button", name="New workspace", exact=True).click()
    page.get_by_label("Workspace name", exact=True).fill(name)
    hold(page, case, "/rest/v1/workspaces", "POST")
    page.get_by_role("button", name="Create workspace", exact=True).click()
    wait_held(page, case, case)
    rows = ui.ok(owner.get("/rest/v1/workspaces", params={
        "name": f"eq.{name}", "select": "id,name"}))
    assert len(rows) == 1, "The held creation did not persist exactly once"
    fixtures["abandoned_workspace"] = rows[0]
    leave_workspace_route(page)
    enter_workspace_route(page)
    open_workspace_settings(page)
    expect(space_choice(page, fixtures["workspace"]["name"])).to_have_count(1, timeout=15000)
    expect(page.get_by_role("heading", name="Your first workspace", level=2)).to_be_visible()
    page.get_by_label("Workspace name", exact=True).fill(typed)
    release(page, case, case)
    expect(page.get_by_role("heading", name="Your first workspace", level=2)).to_be_visible()
    expect(page.get_by_label("Workspace name", exact=True)).to_have_value(typed)
    no_alert(page, case)
    print(f"{case}: persisted creation did not replace the newer selection or draft", flush=True)


CASES = {
    "stale_chat_details": prove_stale_chat_details,
    "chat_refresh_order": prove_chat_refresh_order,
    "chat_draft_clobber": prove_chat_draft_clobber,
    "project_draft_clobber": prove_project_draft_clobber,
    "chat_history_window": prove_chat_history_window,
    "chat_creation_draft": prove_chat_creation_draft,
    "chat_creation_after_navigation": prove_chat_creation_after_navigation,
    "invitation_draft": prove_invitation_draft,
    "workspace_refresh_order": prove_workspace_refresh_order,
    "workspace_save_after_leaving": prove_workspace_save_after_leaving,
    "workspace_initial_error": prove_workspace_initial_error,
    "workspace_create_after_leaving": prove_workspace_create_after_leaving,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def build_fixtures(connection: dict, owner: httpx.Client, owner_id: str, suffix: str) -> dict:
    workspace = ui.row(ui.ok(owner.post("/rest/v1/workspaces", json={
        "name": f"Collaboration races {suffix}", "slug": f"races-{suffix}",
        "created_by": owner_id})))
    project = ui.row(ui.rpc(owner, "create_project", {
        "p_workspace_id": workspace["id"], "p_name": f"Race project {suffix}",
        "p_brief": f"Original brief {suffix} before any save.", "p_kind": "new",
        "p_source_url": None}))
    chats = {}
    for key, label in (("alpha", "Alpha"), ("bravo", "Bravo"), ("delta", "Delta"),
                       ("echo", "Echo")):
        chats[key] = ui.row(ui.ok(owner.post("/rest/v1/chats", json={
            "owner_id": owner_id, "workspace_id": workspace["id"],
            "title": f"{label} {suffix}"})))
    alpha_message = f"Alpha-only decision {suffix}"
    ui.ok(owner.post("/rest/v1/chat_messages", json={
        "chat_id": chats["alpha"]["id"], "author_id": owner_id, "role": "user",
        "content": alpha_message}))
    recipient = f"oryveta-{suffix}-invitee@example.test"
    ui.ok(owner.post("/rest/v1/chat_shares", json={
        "chat_id": chats["alpha"]["id"], "invited_by": owner_id,
        "recipient_email": recipient, "permission": "viewer"}))
    # One batch shares a transaction timestamp, so several batches reproduce both
    # distinct and tied creation times inside one window.
    for start in range(0, MESSAGE_WINDOW, HISTORY_BATCH):
        ui.ok(owner.post("/rest/v1/chat_messages", headers={"Prefer": "return=minimal"}, json=[
            {"chat_id": chats["echo"]["id"], "author_id": owner_id, "role": "user",
             "content": f"History {suffix} #{index + 1:03d}"}
            for index in range(start, start + HISTORY_BATCH)]))
    return {
        "suffix": suffix, "workspace": workspace, "project": project,
        "alpha": chats["alpha"], "bravo": chats["bravo"], "delta": chats["delta"],
        "echo": chats["echo"], "alpha_message": alpha_message, "recipient": recipient,
        "charlie_title": f"Charlie {suffix}", "charlie": None,
        "created_name": f"Created workspace {suffix}", "created_workspace": None,
        "echo_messages": MESSAGE_WINDOW,
    }


def remove_fixtures(connection: dict, fixtures: dict, user_ids: list[str]) -> None:
    """Delete every disposable row and Auth user this run created.

    The administrative key stays in this process: projects have no client delete
    path, and the temporary identity is removed through the Auth admin API. It is
    never handed to the browser.
    """
    key = connection.get("SERVICE_ROLE_KEY") or connection.get("SECRET_KEY")
    if not key:
        raise RuntimeError("Fixture cleanup requires the local stack's administrative key")
    chats = [fixtures[name]["id"] for name in ("alpha", "bravo", "delta", "echo")
             if fixtures.get(name)]
    if fixtures.get("charlie"):
        chats.append(fixtures["charlie"]["id"])
    failures = []
    with httpx.Client(base_url=connection["API_URL"], trust_env=False, timeout=30, headers={
            "apikey": key, "Authorization": f"Bearer {key}"}) as admin:
        requests = [("/rest/v1/chats", {"id": f"in.({','.join(chats)})"})] if chats else []
        if fixtures.get("project"):
            requests.append(("/rest/v1/projects", {"id": f"eq.{fixtures['project']['id']}"}))
        workspaces = [fixtures[name]["id"] for name in (
            "workspace", "created_workspace", "abandoned_workspace") if fixtures.get(name)]
        if workspaces:
            requests.append(("/rest/v1/workspaces", {"id": f"in.({','.join(workspaces)})"}))
        for path, params in requests:
            response = admin.delete(path, params=params)
            if response.is_error:
                failures.append(f"DELETE {path}: HTTP {response.status_code}")
        for user_id in user_ids:
            response = admin.delete(f"/auth/v1/admin/users/{user_id}")
            if response.is_error:
                failures.append(f"DELETE Auth user {user_id}: HTTP {response.status_code}")
    if failures:
        raise RuntimeError("Fixture cleanup failed: " + "; ".join(failures))
    print("Cleanup: fixture conversations, project, workspaces and temporary identities removed",
          flush=True)


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------

def exercise(connection: dict, evidence: Path, selected: list[str]) -> None:
    suffix = uuid.uuid4().hex[:12]
    address = f"oryveta-{suffix}-owner@example.test"
    failures: list[str] = []
    fixtures: dict = {}
    user_ids: list[str] = []
    browser_errors: list[str] = []
    with httpx.Client(base_url=connection["MAILPIT_URL"], trust_env=False, timeout=10) as mail, \
            sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = None
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.on("page", lambda opened: opened.on(
                "pageerror", lambda error: browser_errors.append(str(error))))
            page = context.new_page()
            page.add_init_script(HOLD_HARNESS)
            session = ui.sign_in(page, mail, connection["API_URL"], address)
            user_ids.append(session["user"]["id"])
            with ui.api_client(connection, session) as owner:
                fixtures = build_fixtures(connection, owner, session["user"]["id"], suffix)
                for name in selected:
                    page.goto(f"{ORIGIN}/workspace")
                    expect(sidebar_link(page, "Private chats")).to_be_visible(timeout=20000)
                    try:
                        CASES[name](page, fixtures, owner)
                    except Exception as problem:
                        failures.append(f"{name}: {problem}")
                        print(f"FAILED {name}: {problem}", flush=True)
                        if not page.is_closed():
                            page.screenshot(path=str(evidence / f"failed-{name}.png"),
                                            full_page=True)
                    finally:
                        if not page.is_closed():
                            page.evaluate("() => window.__holds.releaseAll()")
                if browser_errors:
                    failures.append(f"browser errors: {browser_errors}")
        finally:
            try:
                if user_ids:
                    remove_fixtures(connection, fixtures, user_ids)
            finally:
                browser.close()
    if failures:
        raise SystemExit("Collaboration ordering regressions failed:\n  "
                         + "\n  ".join(failures))
    print(f"All {len(selected)} selected collaboration cases passed: "
          + ", ".join(selected), flush=True)


def connection_values(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Connection JSON must be an object of Supabase connection values")
    values = payload.get("env") if isinstance(payload.get("env"), dict) else payload
    missing = [key for key in ("API_URL", "DB_URL", "MAILPIT_URL", "PUBLISHABLE_KEY")
               if not values.get(key)]
    if missing:
        raise ValueError("Connection JSON is missing " + ", ".join(missing)
                         + ". Pass `supabase status --output-format json`.")
    if not (values.get("SERVICE_ROLE_KEY") or values.get("SECRET_KEY")):
        raise ValueError("Local fixture creation requires an administrative key for cleanup")
    for key in ("API_URL", "DB_URL", "MAILPIT_URL"):
        values[key] = ui.loopback(values[key])
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connections", default="-",
                        help="File holding the local Supabase status JSON; '-' reads stdin")
    parser.add_argument("--evidence", default="/tmp/oryveta-collaboration-evidence")
    parser.add_argument("--skip-sql", action="store_true",
                        help="Reuse an already bootstrapped isolated stack")
    parser.add_argument("--prebuilt",
                        help="Serve this existing Studio build instead of building one")
    parser.add_argument("--only", action="append", choices=sorted(CASES),
                        help="Run only the named case; repeatable")
    arguments = parser.parse_args()
    payload = (json.load(sys.stdin) if arguments.connections == "-"
               else json.loads(Path(arguments.connections).read_text(encoding="utf-8")))
    connection = connection_values(payload)
    ui.ORIGIN = ORIGIN
    evidence = Path(arguments.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    if not arguments.skip_sql:
        ui.apply_sql(connection)
    with studio(connection, arguments.prebuilt):
        exercise(connection, evidence, arguments.only or list(CASES))


if __name__ == "__main__":
    main()
