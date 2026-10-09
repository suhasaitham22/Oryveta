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
