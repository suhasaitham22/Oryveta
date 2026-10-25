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

Nothing is mocked: every request reaches the local PostgREST/Auth stack and
every assertion reads the resulting UI or the database. The only interference is
an in-page `fetch` wrapper that issues the real request immediately and defers
delivery of its real response, which is how an out-of-order response is produced
deterministically. No response body, status or success is invented.

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
      (error) => { rule.state = "failed"; throw error; },
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


CASES = {
    "stale_chat_details": prove_stale_chat_details,
    "chat_refresh_order": prove_chat_refresh_order,
    "chat_draft_clobber": prove_chat_draft_clobber,
    "project_draft_clobber": prove_project_draft_clobber,
    "chat_history_window": prove_chat_history_window,
    "chat_creation_draft": prove_chat_creation_draft,
    "chat_creation_after_navigation": prove_chat_creation_after_navigation,
    "invitation_draft": prove_invitation_draft,
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
        if fixtures.get("workspace"):
            requests.append(("/rest/v1/workspaces", {"id": f"eq.{fixtures['workspace']['id']}"}))
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
    print("Cleanup: fixture conversations, project, workspace and temporary identities removed",
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
