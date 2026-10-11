"""Published Oryveta hosted configuration must remain safe until OAuth is enabled."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONFIG=(ROOT / "apps" / "web" / "cloud-config.js").read_text()
AUTH=(ROOT / "apps" / "web" / "cloud-auth.js").read_text()


def test_provisioned_cloud_identity_defaults_off():
    assert "nydtmiseclkwauiepqxn.supabase.co" in CONFIG
    assert "githubEnabled: false" in CONFIG
    assert "config.githubEnabled === true" in AUTH


def test_public_key_only_and_no_secrets():
    assert "sb_publishable_" in CONFIG
    assert "sb_secret_" not in CONFIG
    assert "service_role:" not in CONFIG
    assert "github_client_secret" not in CONFIG
    assert "githubEnabled" not in AUTH.split("function configured()", 1)[0]
