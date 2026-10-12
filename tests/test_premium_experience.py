"""Static regression for passwordless auth and accessible product story."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def file(path): return (ROOT/path).read_text()

def test_public_email_auth_with_github_off():
    auth=file("apps/web/cloud-auth.js")
    cfg=file("apps/web/cloud-config.js")
    assert "signInWithOtp" in auth and "signInWithEmail" in auth
    assert "emailRedirectTo:window.location.origin+'/'" in auth
    assert "githubConfigured()" in auth and "emailEnabled: true" in cfg
    assert "githubEnabled: false" in cfg
    assert "sb_secret_" not in cfg and "service_role:" not in cfg
def test_accessible_progressive_design():
    html=file("apps/web/index.html")
    motion=file("apps/web/experience.js")
    css=file("apps/web/styles.css")
    assert 'id="email-login-form"' in html and 'type="email"' in html
    assert 'role="tablist"' in html and 'role="tabpanel"' in html
    assert "IntersectionObserver" in motion and "requestAnimationFrame" in motion
    assert "aria-selected" in motion and "prefers-reduced-motion" in motion
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert '"/static/experience.js"' in file("apps/web/vercel.json")
