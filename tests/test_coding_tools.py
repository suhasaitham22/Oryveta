import hashlib
import os
import subprocess

import pytest

from oryveta_engine.coding_contract import CodingError
from oryveta_engine.coding_tools import MAX_EDIT_FILE_BYTES, SourceTools, source_patch


def editor(root, text="one\ntwo\n", name="main.py"):
    root.mkdir()
    (root / name).write_text(text, encoding="utf-8")
    return SourceTools(root, (name,), (name,))


def test_tools_cannot_read_or_modify_a_non_granted_file(tmp_path):
    tools = editor(tmp_path / "work")
    secret = tools.root / "private.json"
    secret.write_text("private sentinel")
    for path in ("private.json", "../private.json", str(secret)):
        with pytest.raises(CodingError):
            tools.call("read_file", {"path": path})
    assert [row["path"] for row in tools.call("list_files", {})["files"]] == ["main.py"]
    assert secret.read_text() == "private sentinel"


def test_read_only_grant_does_not_allow_writes(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    (root / "main.py").write_text("one")
    tools = SourceTools(root, ("main.py",), ())
    with pytest.raises(CodingError, match="allowlist"):
        tools.call("replace_text", {"path": "main.py", "expected_sha256": hashlib.sha256(b"one").hexdigest(),
                                    "old": "one", "new": "two"})
    assert (root / "main.py").read_text() == "one"


def test_stale_edit_preserves_an_intervening_change(tmp_path):
    tools = editor(tmp_path / "work")
    observed = tools.call("read_file", {"path": "main.py"})
    (tools.root / "main.py").write_text("operator change\n")
    with pytest.raises(CodingError, match="changed"):
        tools.call("replace_text", {"path": "main.py", "expected_sha256": observed["sha256"],
                                    "old": "one", "new": "three"})
    assert (tools.root / "main.py").read_text() == "operator change\n"


def test_ambiguous_edit_is_atomic(tmp_path):
    tools = editor(tmp_path / "work", "one\none\n")
    observed = tools.call("read_file", {"path": "main.py"})
    with pytest.raises(CodingError, match="exactly once"):
        tools.call("replace_text", {"path": "main.py", "expected_sha256": observed["sha256"],
                                    "old": "one", "new": "changed"})
    assert (tools.root / "main.py").read_text() == "one\none\n"


@pytest.mark.parametrize("kind", ["symlink", "parent_symlink", "fifo", "oversized", "binary"])
def test_special_or_unreadable_source_is_refused(tmp_path, kind):
    root = tmp_path / "work"
    root.mkdir()
    path = root / "main.py"
    name = "main.py"
    if kind == "symlink":
        path.symlink_to(tmp_path / "external")
    elif kind == "parent_symlink":
        (root / "linked").symlink_to(tmp_path, target_is_directory=True)
        name = "linked/external"
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "oversized":
        path.write_bytes(b"x" * (MAX_EDIT_FILE_BYTES + 1))
    else:
        path.write_bytes(b"\xff")
    with pytest.raises(CodingError):
        SourceTools(root, (name,), (name,))


def test_read_windows_report_omitted_lines_without_silently_cutting(tmp_path):
    tools = editor(tmp_path / "work", "alpha\nbeta\ngamma\n")
    window = tools.call("read_file", {"path": "main.py", "start_line": 2, "line_count": 1})
    assert window["content"] == "beta\n"
    assert window["more_lines"] is True
    assert window["total_lines"] == 3
    with pytest.raises(CodingError):
        tools.call("read_file", {"path": "main.py", "start_line": True})
    with pytest.raises(CodingError):
        tools.call("read_file", {"path": "main.py", "start_line": 99})


def test_search_is_literal_and_bounded(tmp_path):
    tools = editor(tmp_path / "work", "needle [x]\n" * 30)
    result = tools.call("search", {"query": "[x]"})
    assert result["truncated"] is True
    assert [hit["line"] for hit in result["hits"]] == list(range(1, 21))
    assert tools.call("search", {"query": ".*"})["hits"] == []


def test_unknown_tools_and_extra_arguments_are_refused(tmp_path):
    tools = editor(tmp_path / "work")
    with pytest.raises(CodingError):
        tools.call("shell", {"command": "echo not allowed"})
    with pytest.raises(CodingError):
        tools.call("list_files", {"host_root": "/"})


def test_missing_edit_path_is_reported_without_inferring_a_previous_read(tmp_path):
    tools = editor(tmp_path / "work")
    observed = tools.call("read_file", {"path": "main.py"})
    arguments = {"expected_sha256": observed["sha256"], "old": "one", "new": "three"}
    with pytest.raises(CodingError) as failure:
        tools.call("replace_text", arguments)
    assert failure.value.code == "invalid_tool_arguments"
    assert failure.value.details["missing_fields"] == ["path"]
    assert tools.call("read_file", {"path": "main.py"})["sha256"] == observed["sha256"]
    tools.call("replace_text", {**arguments, "path": "main.py"})
    assert (tools.root / "main.py").read_text() == "three\ntwo\n"


@pytest.mark.parametrize("name,original,updated", [
    ("main.py", b"one\ntwo\n", b"one\nthree\n"),
    ("main.py", b"one\ntwo", b"one\nthree"),
    ("caf\u00e9 file.py", b"one\ntwo\n", b"one\nthree\n"),
    ("main.py", b"one\xe2\x80\xa8context\ntwo\n", b"one\xe2\x80\xa8context\nthree\n"),
    ("main.py", b"one\fcontext\ntwo\n", b"one\fcontext\nthree\n"),
    ("main.py", b"one\rtwo", b"one\rthree"),
    ("main.py", b"one\r\ntwo\r\n", b"one\r\nthree\r\n"),
])
def test_generated_patch_applies_to_the_original_bytes(tmp_path, name, original, updated):
    base = tmp_path / "base"
    base.mkdir()
    (base / name).write_bytes(original)
    work = tmp_path / "work"
    work.mkdir()
    (work / name).write_bytes(original)
    tools = SourceTools(work, (name,), (name,))
    tools.call("replace_text", {"path": name, "expected_sha256": hashlib.sha256(original).hexdigest(),
                                "old": "two", "new": "three"})
    patch = source_patch(base, tools)
    apply_dir = tmp_path / "apply"
    apply_dir.mkdir()
    (apply_dir / name).write_bytes(original)
    result = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], input=patch.encode("utf-8"),
                            cwd=apply_dir, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (apply_dir / name).read_bytes() == updated
    assert (base / name).read_bytes() == original
