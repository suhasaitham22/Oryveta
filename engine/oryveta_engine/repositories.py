"""Bounded repository snapshots; no shell execution of imported code."""
from __future__ import annotations

import io
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

import httpx

MAX_ARCHIVE = 12 * 1024 * 1024
MAX_UNPACKED = 32 * 1024 * 1024
MAX_ENTRIES = 1800
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class InvalidRepository(ValueError):
    pass


def parse_github_url(url: str) -> tuple[str, str]:
    from urllib.parse import urlsplit
    value = urlsplit(url.strip())
    if value.scheme != "https" or value.hostname != "github.com" or value.port is not None or value.username:
        raise InvalidRepository("Only public https://github.com/owner/repo URLs are supported")
    parts = [p for p in value.path.strip("/").split("/") if p]
    if len(parts) != 2:
        raise InvalidRepository("Use a repository URL such as https://github.com/owner/repo")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not REPO_PATTERN.fullmatch(owner) or not REPO_PATTERN.fullmatch(repo) or owner in {".", ".."} or repo in {".", ".."}:
        raise InvalidRepository("Invalid GitHub repository name")
    return owner, repo


def fetch_public_github_repo(url: str) -> tuple[str, bytes]:
    """Fetch fixed GitHub API endpoints; follow only allowlisted archive hosts."""
    owner, repo = parse_github_url(url)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "oryveta/0.1"}
    with httpx.Client(timeout=25, follow_redirects=False, headers=headers) as client:
        meta = client.get(f"https://api.github.com/repos/{owner}/{repo}")
        if meta.status_code == 404:
            raise InvalidRepository("Repository not found, or it is private. Private GitHub App imports are not configured yet.")
        meta.raise_for_status()
        info = meta.json()
        if info.get("private") or info.get("size", 0) > 15000:
            raise InvalidRepository("Only smaller public repositories can be imported for now")
        branch = info.get("default_branch")
        if not branch or len(branch) > 150:
            raise InvalidRepository("Repository default branch is invalid")
        # Never buffer an unbounded response body, including the non-redirect case.
        archive_url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{branch}"
        with client.stream("GET", archive_url) as archive:
            if archive.status_code in {301, 302, 303, 307, 308}:
                location = archive.headers.get("location", "")
                from urllib.parse import urlsplit
                redirect = urlsplit(location)
                if (redirect.scheme != "https" or redirect.hostname not in {
                    "codeload.github.com", "objects.githubusercontent.com"
                } or redirect.username or redirect.password or redirect.port not in {None, 443}):
                    raise InvalidRepository("GitHub returned an untrusted archive destination")
                return f"{owner}/{repo}", _bounded_download(client, location)
            archive.raise_for_status()
            data = _read_bounded(archive)
        return f"{owner}/{repo}", data


def _read_bounded(response: httpx.Response) -> bytes:
    parts: list[bytes] = []
    count = 0
    for chunk in response.iter_bytes(chunk_size=64 * 1024):
        count += len(chunk)
        if count > MAX_ARCHIVE:
            raise InvalidRepository("Archive exceeds the 12 MB import limit")
        parts.append(chunk)
    return b"".join(parts)


def _bounded_download(client: httpx.Client, url: str) -> bytes:
    with client.stream("GET", url) as response:
        response.raise_for_status()
        return _read_bounded(response)


def snapshot_zip(root: Path, payload: bytes) -> int:
    if len(payload) > MAX_ARCHIVE:
        raise InvalidRepository("Archive exceeds 12 MB")
    try:
        handle = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, ValueError) as e:
        raise InvalidRepository("Invalid ZIP archive") from e
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    members = handle.infolist()
    if len(members) > MAX_ENTRIES:
        raise InvalidRepository("Archive contains too many files")
    total = 0
    saved = 0
    # A GitHub ZIP has an enclosing root directory; detect only when all entries share it.
    paths = [PurePosixPath(m.filename) for m in members if m.filename and not m.is_dir()]
    first = {p.parts[0] for p in paths if p.parts}
    strip_root = len(first) == 1 and any(len(p.parts) > 1 for p in paths)
    seen: set[str] = set()
    for member in members:
        if member.is_dir():
            continue
        if (member.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
            raise InvalidRepository("Symlink entries are not allowed")
        parts = PurePosixPath(member.filename).parts
        if not parts or any(part in {".", ".."} for part in parts) or member.filename.startswith("/") or "\\" in member.filename:
            raise InvalidRepository("Unsafe archive path")
        if strip_root:
            parts = parts[1:]
        if not parts or any(part in {".git", "node_modules", ".venv", "__pycache__"} for part in parts):
            continue
        normalized = "/".join(parts).casefold()
        if normalized in seen:
            raise InvalidRepository("Archive contains duplicate destination paths")
        seen.add(normalized)
        total += member.file_size
        if total > MAX_UNPACKED or member.file_size > 3 * 1024 * 1024:
            raise InvalidRepository("Expanded archive exceeds limits")
        dest = root.joinpath(*parts).resolve()
        if not dest.is_relative_to(root):
            raise InvalidRepository("Archive escapes project workspace")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with handle.open(member) as source, dest.open("wb") as target:
            copied = 0
            while part := source.read(64 * 1024):
                copied += len(part)
                if copied > member.file_size or copied > 3 * 1024 * 1024:
                    raise InvalidRepository("Archive file exceeds limits")
                target.write(part)
            if copied != member.file_size:
                raise InvalidRepository("Archive file length mismatch")
        saved += 1
    if not saved:
        raise InvalidRepository("No project files found in the archive")
    return saved


def create_archive(root: Path) -> bytes:
    """Export user workspace as a portable source ZIP."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(root.rglob("*")):
            if item.is_file() and not item.is_symlink() and not any(p in {".git", "node_modules", ".venv"} for p in item.relative_to(root).parts):
                archive.write(item, item.relative_to(root).as_posix())
    return output.getvalue()
