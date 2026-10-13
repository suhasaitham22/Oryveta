import io
import zipfile

import pytest
from oryveta_engine.repositories import InvalidRepository, create_archive, parse_github_url, snapshot_zip


def zipped(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for path, data in files.items():
            z.writestr(path, data)
    return buffer.getvalue()


@pytest.mark.parametrize('url', [
    'http://github.com/a/b', 'https://evil.com/a/b',
    'https://github.com/a/b/extra', 'https://github.com/a/..',
    'https://user:pass@github.com/a/b',
])
def test_reject_unsafe_github_urls(url):
    with pytest.raises(InvalidRepository):
        parse_github_url(url)


def test_parse_github():
    assert parse_github_url('https://github.com/org/repo.git') == ('org','repo')


def test_snapshot_and_export(tmp_path):
    root = tmp_path / 'import'
    assert snapshot_zip(root, zipped({'repo-main/README.md':'hello','repo-main/src/a.py':'print(1)'})) == 2
    assert (root/'README.md').read_text() == 'hello'
    with zipfile.ZipFile(io.BytesIO(create_archive(root))) as z:
        assert sorted(z.namelist()) == ['README.md','src/a.py']


def test_traversal_rejected(tmp_path):
    with pytest.raises(InvalidRepository):
        snapshot_zip(tmp_path/'bad', zipped({'../escape.py':'bad'}))
    assert not (tmp_path/'escape.py').exists()


def test_archive_limits(tmp_path):
    with pytest.raises(InvalidRepository):
        snapshot_zip(tmp_path/'bad', b'x' * (12*1024*1024+1))


def test_zip_preserves_source_only_top_level_folder(tmp_path):
    root = tmp_path / "import"
    assert snapshot_zip(root, zipped({"src/main.py": "print(1)"})) == 1
    assert (root / "src" / "main.py").read_text() == "print(1)"
    assert not (root / "main.py").exists()


def test_zip_cleanup_if_second_file_extraction_fails(tmp_path, monkeypatch):
    archive = zipped({"repo-main/first.py": "x=1", "repo-main/second.py": "x=2"})
    original_open = zipfile.ZipFile.open
    seen = {"count": 0}

    def interrupted(self, name, *args, **kwargs):
        seen["count"] += 1
        if seen["count"] == 2:
            raise zipfile.BadZipFile("simulated checksum error")
        return original_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", interrupted)
    root = tmp_path / "import"
    with pytest.raises(InvalidRepository, match="Corrupt"):
        snapshot_zip(root, archive)
    assert not root.exists()


@pytest.mark.parametrize("url", [
    "https://github.com/org/repo?tab=readme",
    "https://github.com/org/repo#frag",
])
def test_rejects_ambiguous_github_urls(url):
    with pytest.raises(InvalidRepository):
        parse_github_url(url)
