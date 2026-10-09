"""Documentation regression checks: links resolve and core decisions stay explicit."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def test_docs_index_links_exist():
    index = (DOCS / "INDEX.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)]+\.md)\)", index)
    assert len(targets) >= 15
    for relative in targets:
        assert (DOCS / relative).is_file(), relative


def test_readme_links_to_docs_hub():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "](docs/INDEX.md)" in readme


def test_documented_product_scope():
    vision = (DOCS / "VISION.md").read_text(encoding="utf-8")
    product = (DOCS / "PRODUCT.md").read_text(encoding="utf-8")
    status = (DOCS / "STATUS.md").read_text(encoding="utf-8")
    assert "Start New" in vision and "Evolve" in vision
    assert "Kaggle" in product and "internal" in product.lower()
    assert "Not implemented" in status


def test_apache_license_is_complete_and_notice_identifies_holder():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notice_text = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "Apache License" in license_text
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in license_text
    assert "APPENDIX: How to apply the Apache License to your work." in license_text
    assert "Copyright 2026 Suhas Aitham" in notice_text
    assert "Apache License" in notice_text
