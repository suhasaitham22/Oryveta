"""Read-only, content-addressed change previews for the Evolve verification loop.

A preview is evidence for human review, not a proof of behavioral correctness.
No imported repository code is executed and no source file is modified.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
from pathlib import Path, PurePosixPath

MAX_SOURCE_BYTES = 128 * 1024
MAX_DIFF_CHARS = 24_000
ALLOWED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".sql", ".md", ".toml", ".json", ".yaml", ".yml"}
BLOCKED_PARTS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build", "target"}


class InvalidPatch(ValueError):
    """A proposal is invalid or cannot be independently reviewed."""


class StalePatch(InvalidPatch):
    """The source has changed since the proposed baseline."""


def preview_patch(root: Path, relative_path: str, expected_sha256: str, replacement: str) -> dict:
    """Validate a bounded single-file replacement and return a non-mutating diff.

    No commands, imports, test suites, or repository hooks run here. Future
    sandboxed verification must be independent and separately authorized.
    """
    if not relative_path or "\\" in relative_path or "\x00" in relative_path:
        raise InvalidPatch("Invalid relative path")
    relative = PurePosixPath(relative_path)
    if (relative.is_absolute() or any(part in {".", ".."} or part in BLOCKED_PARTS for part in relative.parts)
            or relative.as_posix() != relative_path or len(relative.parts) > 16):
        raise InvalidPatch("Unsafe repository path")
    if relative.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise InvalidPatch("Unsupported source file type")
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256):
        raise InvalidPatch("Expected SHA-256 must be lowercase hexadecimal")
    try:
        updated = replacement.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise InvalidPatch("Replacement must be UTF-8") from exc
    if len(updated) > MAX_SOURCE_BYTES or b"\x00" in updated:
        raise InvalidPatch("Replacement exceeds text limits")

    base = root.resolve(strict=True)
    target = base.joinpath(*relative.parts)
    if any(p.is_symlink() for p in (target, *target.parents) if p != base and base in p.parents):
        raise InvalidPatch("Symlinks are not supported in patch previews")
    if not target.is_file() or not target.resolve().is_relative_to(base):
        raise InvalidPatch("Source file is not available")
    if target.stat().st_size > MAX_SOURCE_BYTES:
        raise InvalidPatch("Source file exceeds text limits")
    source = target.read_bytes()
    if len(source) > MAX_SOURCE_BYTES or b"\x00" in source:
        raise InvalidPatch("Source file exceeds text limits")
    actual_sha256 = hashlib.sha256(source).hexdigest()
    if actual_sha256 != expected_sha256:
        raise StalePatch("Source changed since proposal was prepared")
    try:
        original = source.decode("utf-8")
    except UnicodeError as exc:
        raise InvalidPatch("Source file is not UTF-8") from exc

    checks = [{"name": "baseline_sha256", "status": "passed"}]
    if relative.suffix.lower() == ".py":
        try:
            ast.parse(replacement, filename=relative_path)
        except SyntaxError as exc:
            raise InvalidPatch(f"Replacement has Python syntax error at line {exc.lineno}") from exc
        checks.append({"name": "python_syntax", "status": "passed"})
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True), replacement.splitlines(keepends=True),
        fromfile=f"a/{relative_path}", tofile=f"b/{relative_path}", n=3,
    ))
    if len(diff) > MAX_DIFF_CHARS:
        raise InvalidPatch("Diff exceeds preview limits; split the proposal")
    return {
        "path": relative_path,
        "baseline_sha256": actual_sha256,
        "proposed_sha256": hashlib.sha256(updated).hexdigest(),
        "diff": diff,
        "changed": source != updated,
        "checks": checks,
        "status": "review_required",
        "applied": False,
        "behavior_verified": False,
        "note": "Read-only preview. Syntax and hash checks do not establish behavioral correctness.",
    }
