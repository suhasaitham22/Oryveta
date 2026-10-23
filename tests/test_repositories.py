"""Bounded import regressions, including the pinned-commit fetch (DR-004)."""

import io
import zipfile

import httpx
import pytest
from oryveta_engine import repositories
from oryveta_engine.repositories import (
    InvalidRepository,
    create_archive,
    fetch_public_github_repo,
    parse_github_url,
    snapshot_zip,
)


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


# DR-004: a retry must fetch the work item's pinned commit through this same
# safeguarded path, never the mutable default branch.
PINNED_COMMIT = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


def github_zipball(commit: str) -> bytes:
    """A GitHub-shaped zipball: abbreviated commit in the root folder, full
    commit in the ZIP archive comment, exactly as the real endpoint returns."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"org-repo-{commit[:7]}/README.md", "hello")
        archive.comment = commit.encode("ascii")
    return buffer.getvalue()


def github_transport(requested: list[str], *, default_branch: str = "main",
                     size: int = 10, private: bool = False):
    archive = github_zipball(PINNED_COMMIT)

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/repos/org/repo":
            return httpx.Response(200, json={"private": private, "size": size,
                                             "default_branch": default_branch})
        if request.url.path.startswith("/repos/org/repo/zipball/"):
            return httpx.Response(200, content=archive)
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.MockTransport(handle)


def serve_github(monkeypatch, requested: list[str], **options) -> None:
    """Point the importer's client at a local transport; no network access.

    The real constructor is captured before the module attribute is replaced,
    because `repositories.httpx` is the httpx module itself: building the stand
    in client from the patched name would call this factory again.
    """
    real_client = httpx.Client
    monkeypatch.setattr(repositories.httpx, "Client", lambda **kwargs: real_client(
        transport=github_transport(requested, **options), **kwargs))


@pytest.fixture
def github(monkeypatch):
    """Serve the fixed GitHub endpoints locally; no network access."""
    requested: list[str] = []
    serve_github(monkeypatch, requested)
    return requested


def test_default_branch_is_fetched_when_no_commit_is_pinned(github, tmp_path):
    slug, payload = fetch_public_github_repo("https://github.com/org/repo")
    assert slug == "org/repo"
    assert github[-1].endswith("/repos/org/repo/zipball/main")
    # The bytes are a whole archive the importer can still snapshot.
    assert snapshot_zip(tmp_path / "import", payload) == 1
    assert (tmp_path / "import" / "README.md").read_text() == "hello"


def test_pinned_commit_is_fetched_instead_of_the_default_branch(github, tmp_path):
    slug, payload = fetch_public_github_repo("https://github.com/org/repo",
                                             ref=PINNED_COMMIT)
    assert slug == "org/repo"
    assert github[-1].endswith(f"/repos/org/repo/zipball/{PINNED_COMMIT}")
    assert not any(url.endswith("/zipball/main") for url in github)
    assert snapshot_zip(tmp_path / "import", payload) == 1
    assert (tmp_path / "import" / "README.md").read_text() == "hello"


@pytest.mark.parametrize("ref", [
    "main", "A" * 40, "a" * 39, "a" * 41, "../../etc/passwd", "a" * 39 + "g", "",
    "a" * 40 + "/..",
])
def test_only_an_exact_lowercase_commit_may_be_pinned(github, ref):
    with pytest.raises(InvalidRepository, match="exact 40-character commit"):
        fetch_public_github_repo("https://github.com/org/repo", ref=ref)
    # Nothing was requested at all: a rejected pin never reaches the network.
    assert github == []


def test_a_pinned_commit_does_not_bypass_the_repository_guards(monkeypatch):
    requested: list[str] = []
    serve_github(monkeypatch, requested, private=True)

    with pytest.raises(InvalidRepository, match="smaller public repositories"):
        fetch_public_github_repo("https://github.com/org/repo", ref=PINNED_COMMIT)

    # The metadata guard ran and the archive was never fetched.
    assert requested == ["https://api.github.com/repos/org/repo"]
