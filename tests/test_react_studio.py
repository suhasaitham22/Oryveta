"""Static architecture checks supplement the real npm build and Chromium smoke workflow."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]/"apps"/"web"
STUDIO=ROOT/"studio"
def test_react_is_real_app_not_legacy_dom_script():
    package=json.loads((STUDIO/"package.json").read_text())
    assert "react" in package["dependencies"]
    assert "@radix-ui/react-tabs" in package["dependencies"]
    assert "vite" in package["devDependencies"]
    assert (STUDIO/"src/components/ui/button.jsx").is_file()
    assert (STUDIO/"src/pages/Workspace.jsx").is_file()
    assert "createRoot" in (STUDIO/"src/main.jsx").read_text()
def test_real_storyboard_and_vendored_snapcn():
    s=json.loads((STUDIO/"public/demo-stories.json").read_text())
    assert {x["id"] for x in s}>={"start-new","evolve","agent-evaluation"}
    for x in s:
        assert x["state"]=="storyboard"
        assert all("receipt" in f and f["receipt"] for f in x["scenes"])
    assert (STUDIO/"demo/src/components/snap-cn/text-reveal.tsx").is_file()
    assert "TextReveal" in (STUDIO/"demo/src/Root.tsx").read_text()
def test_hosted_react_build_config_and_oauth_gated():
    config=json.loads((ROOT/"vercel.json").read_text())
    assert config["outputDirectory"]=="studio/dist"
    assert "studio" in config["buildCommand"]
    assert "oauthGitHubEnabled=false" in (STUDIO/"src/lib/identity.js").read_text()
    assert "signInWithOtp" in (STUDIO/"src/lib/identity.js").read_text()
