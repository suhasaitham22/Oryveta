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
    """Validate the entire ZIP before creating files, then extract within limits.

    We never execute imported content. Non-regular files, duplicate destinations,
    path traversal and file/directory collisions are rejected up front.
    """
    if len(payload) > MAX_ARCHIVE:
        raise InvalidRepository("Archive exceeds 12 MB")
    try:
        handle = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise InvalidRepository("Invalid ZIP archive") from exc

    with handle:
        members = handle.infolist()
        if len(members) > MAX_ENTRIES:
            raise InvalidRepository("Archive contains too many files")

        file_paths = [PurePosixPath(m.filename) for m in members if m.filename and not m.is_dir()]
        first = {p.parts[0] for p in file_paths if p.parts}
        strip_root = len(first) == 1 and any(len(p.parts) > 1 for p in file_paths)
        planned: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
        seen: set[str] = set()
        total = 0

        for member in members:
            raw = member.filename
            components = raw.rstrip("/").split("/")
            if (not raw or raw.startswith("/") or "\\" in raw
                    or any(part in {"", ".", ".."} or ":" in part for part in components)):
                raise InvalidRepository("Unsafe archive path")
            mode = stat.S_IFMT(member.external_attr >> 16)
            if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise InvalidRepository("Special file entries are not allowed")
            if member.is_dir():
                continue
            if mode == stat.S_IFDIR:
                raise InvalidRepository("Invalid directory entry")
            parts = tuple(components[1:] if strip_root else components)
            if not parts or any(part in {".git", "node_modules", ".venv", "__pycache__"} for part in parts):
                continue
            key = "/".join(parts).casefold()
            if key in seen:
                raise InvalidRepository("Archive contains duplicate destination paths")
            seen.add(key)
            total += member.file_size
            if member.file_size > 3 * 1024 * 1024 or total > MAX_UNPACKED:
                raise InvalidRepository("Expanded archive exceeds limits")
            planned.append((member, parts))

        if not planned:
            raise InvalidRepository("No project files found in the archive")
        # A file must not also be an ancestor of another file, case-insensitively.
        for key in seen:
            prefix = key.split("/")
            if any("/".join(prefix[:i]) in seen for i in range(1, len(prefix))):
                raise InvalidRepository("Archive has file/directory path collisions")

        root = root.resolve()
        root.mkdir(parents=True, exist_ok=False)
        try:
            for member, parts in planned:
                dest = root.joinpath(*parts)
                if not dest.resolve().is_relative_to(root):
                    raise InvalidRepository("Archive escapes project workspace")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with handle.open(member) as source, dest.open("xb") as target:
                    copied = 0
                    while part := source.read(64 * 1024):
                        copied += len(part)
                        if copied > member.file_size or copied > 3 * 1024 * 1024:
                            raise InvalidRepository("Archive file exceeds limits")
                        target.write(part)
                    if copied != member.file_size:
                        raise InvalidRepository("Archive file length mismatch")
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise InvalidRepository("Corrupt or encrypted ZIP archive") from exc
        return len(planned)


def create_archive(root: Path) -> bytes:
    """Export a workspace ZIP, refusing oversized exports before buffering files."""
    root = root.resolve()
    planned: list[Path] = []
    total = 0
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root)
        if any(part in {".git", "node_modules", ".venv"} for part in relative.parts):
            continue
        if item.is_symlink() or not item.is_file():
            continue
        if not item.resolve().is_relative_to(root):
            raise InvalidRepository("Project export contains an unsafe path")
        total += item.stat().st_size
        if total > MAX_UNPACKED or len(planned) >= MAX_ENTRIES:
            raise InvalidRepository("Project export exceeds 32 MB or 1800 files")
        planned.append(item)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in planned:
            archive.write(item, item.relative_to(root).as_posix())
    if output.tell() > MAX_UNPACKED:
        raise InvalidRepository("Project export exceeds 32 MB")
    return output.getvalue()
