"""Bounded file tools; the model never receives a host shell or arbitrary path access."""
from __future__ import annotations

import difflib
import os
import stat
import tempfile
from hashlib import sha256
from pathlib import Path

from .coding_config import relative_path
from .coding_contract import CodingError

MAX_EDIT_FILE_BYTES = 128 * 1024
MAX_OBSERVATION_BYTES = 8192
MAX_REPLACEMENT_BYTES = 8192

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "list_files", "description": "List the source files you are allowed to inspect.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a bounded line window and the current whole-file SHA-256.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start_line": {"type": "integer"},
            "line_count": {"type": "integer"}}, "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "replace_text", "description": "Replace one unique exact text occurrence in an editable file. Every call must include all four arguments: path, expected_sha256 from read_file, old text, and new text. Preserve unrelated behavior.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "expected_sha256": {"type": "string"},
            "old": {"type": "string"}, "new": {"type": "string"}},
            "required": ["path", "expected_sha256", "old", "new"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "search", "description": "Find a literal single-line string in allowed files; output is bounded.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "run_checks", "description": "Run the operator-defined development checks in isolated containers. You cannot choose commands or expected results.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
]


def _arguments(arguments, allowed, required=()):
    if not isinstance(arguments, dict):
        raise CodingError("invalid_tool_arguments", "tool arguments must be a JSON object")
    missing = set(required) - arguments.keys()
    unexpected = arguments.keys() - set(allowed)
    if missing or unexpected:
        raise CodingError(
            "invalid_tool_arguments", "supply every required field and only allowed fields",
            details={"missing_fields": sorted(missing), "allowed_fields": sorted(allowed),
                     "unexpected_field_count": len(unexpected)},
        )


class SourceTools:
    def __init__(self, root: Path, read_paths: tuple[str, ...], write_paths: tuple[str, ...]):
        if root.is_symlink() or not root.is_dir():
            raise CodingError("invalid_source", "source workspace must be a real directory")
        self.root = root.resolve()
        self.read_paths = frozenset(read_paths)
        self.write_paths = frozenset(write_paths)
        self.edits = 0
        for path in self.read_paths:
            self._read(path)

    def _path(self, value, *, write=False):
        path = relative_path(value)
        allowed = self.write_paths if write else self.read_paths
        if path not in allowed:
            raise CodingError("path_denied", "file is not in the operator's tool allowlist")
        target = self.root
        for part in path.split("/"):
            target = target / part
            if target.is_symlink():
                raise CodingError("path_denied", "symlinked source paths are not supported")
        return target

    def _read(self, path):
        target = self._path(path)
        try:
            descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_EDIT_FILE_BYTES:
                    raise CodingError("source_limit", "tool files must be regular and at most 128 KiB")
                content = handle.read(MAX_EDIT_FILE_BYTES + 1)
            if len(content) > MAX_EDIT_FILE_BYTES:
                raise CodingError("source_limit", "source file grew beyond the tool limit")
            return content, content.decode("utf-8")
        except CodingError:
            raise
        except (OSError, UnicodeError):
            raise CodingError("invalid_source", "allowed source file is missing or not readable UTF-8") from None

    def call(self, name: str, arguments: dict) -> dict:
        if name == "list_files":
            _arguments(arguments, ())
            return {"files": [{"path": path, "editable": path in self.write_paths}
                              for path in sorted(self.read_paths)]}
        if name == "read_file":
            _arguments(arguments, {"path", "start_line", "line_count"}, {"path"})
            start, count = arguments.get("start_line", 1), arguments.get("line_count", 80)
            if type(start) is not int or start < 1 or type(count) is not int or not 1 <= count <= 200:
                raise CodingError("invalid_tool_arguments", "use a positive start line and 1 to 200 lines")
            raw, text = self._read(arguments["path"])
            lines = text.splitlines(keepends=True)
            if start > max(1, len(lines)):
                raise CodingError("invalid_tool_arguments", "start line is beyond the file")
            selected = "".join(lines[start - 1:start - 1 + count])
            if len(selected.encode("utf-8")) > MAX_OBSERVATION_BYTES:
                raise CodingError("observation_limit", "requested window is too large; read fewer lines")
            return {"path": arguments["path"], "sha256": sha256(raw).hexdigest(),
                    "start_line": start, "total_lines": len(lines), "content": selected,
                    "more_lines": start - 1 + count < len(lines)}
        if name == "replace_text":
            _arguments(arguments, {"path", "expected_sha256", "old", "new"},
                       {"path", "expected_sha256", "old", "new"})
            target = self._path(arguments["path"], write=True)
            old, new = arguments["old"], arguments["new"]
            if (not isinstance(old, str) or not old or not isinstance(new, str)
                    or max(len(old.encode("utf-8")), len(new.encode("utf-8"))) > MAX_REPLACEMENT_BYTES):
                raise CodingError("invalid_tool_arguments", "replacement text must fit within 8192 bytes")
            raw, text = self._read(arguments["path"])
            if arguments["expected_sha256"] != sha256(raw).hexdigest():
                raise CodingError("stale_source", "file changed; read it again before editing")
            if old == new or text.count(old) != 1:
                raise CodingError("ambiguous_edit", "old text must occur exactly once and change the file")
            updated = text.replace(old, new, 1).encode("utf-8")
            if len(updated) > MAX_EDIT_FILE_BYTES:
                raise CodingError("source_limit", "edited file exceeds 128 KiB")
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".repair-edit-", delete=False) as handle:
                    temporary = Path(handle.name)
                    os.fchmod(handle.fileno(), 0o644)
                    handle.write(updated)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            self.edits += 1
            return {"path": arguments["path"], "sha256": sha256(updated).hexdigest(),
                    "bytes": len(updated), "changed": True}
        if name == "search":
            _arguments(arguments, {"query"}, {"query"})
            query = arguments["query"]
            if not isinstance(query, str) or not 1 <= len(query) <= 200 or "\n" in query:
                raise CodingError("invalid_tool_arguments", "search requires a bounded single-line literal")
            hits = []
            for path in sorted(self.read_paths):
                _, text = self._read(path)
                for number, line in enumerate(text.splitlines(), 1):
                    if query in line:
                        if len(hits) == 20:
                            return {"hits": hits, "truncated": True}
                        hits.append({"path": path, "line": number, "text": line[:160]})
            return {"hits": hits, "truncated": False}
        raise CodingError("tool_denied", "tool is not available in this fixed execution policy")


def _quoted_patch_path(prefix: str, path: str) -> str:
    value = f"{prefix}/{path}"
    if all(33 <= byte < 127 and byte not in {34, 92} for byte in value.encode("utf-8")):
        return value
    escaped = []
    for byte in value.encode("utf-8"):
        if byte in {34, 92}:
            escaped.append("\\" + chr(byte))
        elif 32 <= byte < 127:
            escaped.append(chr(byte))
        else:
            escaped.append(f"\\{byte:03o}")
    return '"' + "".join(escaped) + '"'


def source_patch(base: Path, tools: SourceTools) -> str:
    """Git-applicable text diff, including absent final newlines and quoted paths."""
    output = []
    for path in sorted(tools.write_paths):
        before = (base / path).read_bytes().decode("utf-8")
        _, after = tools._read(path)
        for line in difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                         fromfile=_quoted_patch_path("a", path),
                                         tofile=_quoted_patch_path("b", path)):
            output.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(output)
