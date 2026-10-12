"""Never permit workspace membership or a pending invitation to grant chat access."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SQL=(ROOT/"supabase/migrations/private_chats_and_explicit_sharing.sql").read_text()
JS=(ROOT/"apps/web/chats.js").read_text()
AUTH=(ROOT/"apps/web/cloud-auth.js").read_text()
HTML=(ROOT/"apps/web/index.html").read_text()

def test_rls_and_verified_recipient_gates():
    for table in ("public.chats","public.chat_messages","public.chat_shares","public.user_aliases"):
        assert "alter table "+table+" enable row level security" in SQL
    assert "email_confirmed_at is not null" in SQL
    assert "status='accepted'" in SQL
    assert "private.can_read_chat(chat_id)" in SQL
    assert "private.can_write_chat(chat_id)" in SQL
    assert "role='user'" in SQL
    assert "grant update(status,accepted_by,accepted_at)" in SQL
    assert "grant insert(chat_id,author_id,role,content)" in SQL
    assert "grant select,insert,delete on public.chats" in SQL

def test_private_chats_are_a_real_authenticated_ui():
    assert "Private chats" in HTML and "/static/chats.js" in HTML
    assert "window.OryvetaChats" in JS and "data-chat-accept" in JS
    assert "data-chat-revoke" in JS and "guest" not in JS  # uses state.cloud
    assert "No messages yet" in JS and "Sign in" in JS
    assert "inviteToChat" in AUTH and "listInvites" in AUTH
    assert "acceptChatInvite" in AUTH and "getAlias" in AUTH
    assert "role:'user'" in AUTH
