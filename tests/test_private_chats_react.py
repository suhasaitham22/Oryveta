"""RLS chat sharing and React UI must remain tied to truthful demos."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
STUDIO=ROOT/"apps/web/studio"
SQL=(ROOT/"supabase/migrations/private_chats_and_explicit_sharing.sql").read_text()
UI=(STUDIO/"src/pages/PrivateChats.jsx").read_text()
API=(STUDIO/"src/lib/privateChats.js").read_text()
WORKSPACE=(STUDIO/"src/pages/Workspace.jsx").read_text()
STORIES=json.loads((STUDIO/"public/demo-stories.json").read_text())
def test_chat_rls_contract():
    for table in ("public.chats","public.chat_messages","public.chat_shares","public.user_aliases"):
        assert "alter table "+table+" enable row level security" in SQL
    assert "email_confirmed_at is not null" in SQL
    assert "status='accepted'" in SQL
    assert "private.can_read_chat(chat_id)" in SQL
    assert "private.can_write_chat(chat_id)" in SQL
    assert "role='user'" in SQL
    assert "grant update(status,accepted_by,accepted_at)" in SQL
    assert "grant insert(chat_id,author_id,role,content)" in SQL
def test_react_ui_and_consent():
    assert '["chats",MessageSquareText,"Private chats"]' in WORKSPACE
    assert "PrivateChats" in WORKSPACE
    assert "createChat" in API and "sendMessage" in API
    assert "invite(" in API and "accept(" in API and "revoke(" in API
    assert 'role:"user"' in API
    assert "Private chats need a real account." in UI
    assert "In-app invitation created" in UI
    assert "Only the owner manages sharing" in UI
    assert "automatic email notifications" in UI
def test_matching_demo():
    story=next(s for s in STORIES if s["id"]=="private-chats")
    assert story["state"]=="storyboard"
    assert len(story["scenes"])>=3
    assert all(scene["receipt"] and scene["headline"] for scene in story["scenes"])
    assert "render:private-chats" in json.loads((STUDIO/"demo/package.json").read_text())["scripts"]
