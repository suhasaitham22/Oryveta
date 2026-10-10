"""Guardrails for the hosted auth and workspace security foundation.

These are static checks. Live RLS cross-account tests are mandatory before
the hosted provider is enabled for real customers.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase" / "schema.sql").read_text()
HTML = (ROOT / "apps" / "web" / "index.html").read_text()
JS = (ROOT / "apps" / "web" / "app.js").read_text()
AUTH = (ROOT / "apps" / "web" / "cloud-auth.js").read_text()


def test_workspace_schema_has_owner_scope_and_rls():
    assert "alter table public.workspaces enable row level security" in SQL
    assert "alter table public.workspace_memberships enable row level security" in SQL
    assert "with check (created_by = (select auth.uid()))" in SQL
    assert "private.is_workspace_member(id)" in SQL
    assert "revoke insert,update,delete on public.workspace_memberships from authenticated" in SQL
    assert "set search_path = ''" in SQL


def test_identity_not_equal_repository_access():
    assert "scopes:'read:user user:email'" in AUTH
    assert "repo" not in AUTH.split("scopes:'", 1)[1].split("'", 1)[0]
    assert "Github" not in AUTH  # provider key uses lowercase 'github'
    assert "GitHub repository permissions" in HTML


def test_no_service_role_or_demo_auth_in_hosted_client():
    assert "service_role" not in AUTH.lower()
    assert "secret" not in (ROOT / "apps" / "web" / "cloud-config.js").read_text().lower().split("window.ORYVETA_CLOUD", 1)[-1]
    assert "Explore product preview" in HTML
    assert "workspace-create" in JS
    assert "workspace-update" in JS


def test_auth_scripts_are_first_party_and_pkce_is_used():
    assert "/static/cloud-auth.js" in HTML
    assert "/static/cloud-config.js" in HTML
    assert "flowType:'pkce'" in AUTH
    assert "storage:window.sessionStorage" in AUTH
    assert "getUser()" in AUTH
