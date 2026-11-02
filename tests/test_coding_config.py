import copy
import json
import os

import pytest

from oryveta_engine.coding_config import load_spec, parse_spec
from oryveta_engine.coding_contract import CodingError, strict_json


def test_resolved_configuration_identity_does_not_depend_on_omitted_defaults(coding_spec_data):
    initial = parse_spec(coding_spec_data)
    explicit = copy.deepcopy(coding_spec_data)
    explicit["model"]["endpoint"] = "http://127.0.0.1:11434/"
    explicit["limits"] = {"turns": 20, "tool_calls": 60, "total_tokens": 64000, "wall_seconds": 600}
    assert parse_spec(explicit).digest == initial.digest
    explicit["acceptance_checks"][0]["expected_json"] = 8
    assert parse_spec(explicit).digest != initial.digest


@pytest.mark.parametrize("section,key,value", [
    ("model", "endpoint", "https://paid-provider.example/api"),
    ("model", "endpoint", "http://127.0.0.1:11434/path"),
    ("model", "digest", "latest"),
    ("model", "context_tokens", True),
    ("model", "output_tokens", 99999),
    ("runner", "image", "python:latest"),
    ("runner", "cpus", float("nan")),
    ("runner", "cpus", True),
    ("runner", "docker_context", "--host=ssh://example"),
    ("runner", "memory_mb", 0),
    ("limits", "turns", 0),
    ("limits", "wall_seconds", -1),
])
def test_unsafe_or_unbounded_operator_settings_are_refused(coding_spec_data, section, key, value):
    coding_spec_data.setdefault(section, {})[key] = value
    with pytest.raises(CodingError):
        parse_spec(coding_spec_data)


@pytest.mark.parametrize("path", ["../secret", "/tmp/secret", "a/../b", ".git/config", "a\\b", "a\nb", "./a"])
def test_path_scope_cannot_escape_the_snapshot(coding_spec_data, path):
    coding_spec_data["read_paths"] = [path]
    coding_spec_data["write_paths"] = [path]
    with pytest.raises(CodingError):
        parse_spec(coding_spec_data)


def test_write_authority_requires_read_authority(coding_spec_data):
    coding_spec_data["write_paths"] = ["other.py"]
    with pytest.raises(CodingError, match="readable"):
        parse_spec(coding_spec_data)


def test_unknown_scope_fields_are_not_silently_ignored(coding_spec_data):
    coding_spec_data["runner"]["privileged"] = True
    with pytest.raises(CodingError):
        parse_spec(coding_spec_data)


@pytest.mark.parametrize("change", ["version", "duplicate_case", "no_reproducer", "no_preservation", "empty_suite"])
def test_verification_contract_must_be_well_defined(coding_spec_data, change):
    if change == "version":
        coding_spec_data["schema_version"] = True
    elif change == "duplicate_case":
        coding_spec_data["acceptance_checks"][0]["name"] = "increment"
    elif change == "no_reproducer":
        coding_spec_data["development_checks"][0]["kind"] = "preserve"
    elif change == "no_preservation":
        coding_spec_data["development_checks"][1]["kind"] = "regression"
    else:
        coding_spec_data["acceptance_checks"] = []
    with pytest.raises(CodingError):
        parse_spec(coding_spec_data)


@pytest.mark.parametrize("payload", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_ambiguous_json_is_not_a_verifier_value(payload):
    with pytest.raises(ValueError):
        strict_json(payload)


@pytest.mark.parametrize("kind", ["symlink", "fifo", "oversized", "invalid_json"])
def test_config_load_rejects_unsafe_file_types_and_payloads(tmp_path, coding_spec_data, kind):
    path = tmp_path / "factory.json"
    if kind == "symlink":
        actual = tmp_path / "real.json"
        actual.write_text(json.dumps(coding_spec_data))
        path.symlink_to(actual)
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "oversized":
        path.write_bytes(b" " * (129 * 1024))
    else:
        path.write_text("not JSON")
    with pytest.raises(CodingError, match="configuration"):
        load_spec(path)
