"""Documentation regression checks: links resolve and core decisions stay explicit."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def test_docs_index_links_exist():
    index = (DOCS / "INDEX.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)]+\.md)\)", index)
    for relative in targets:
        assert (DOCS / relative).is_file(), relative


