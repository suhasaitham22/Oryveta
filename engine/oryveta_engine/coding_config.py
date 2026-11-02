"""Strict operator-owned configuration for local repair; never supplied by a model."""
from __future__ import annotations

import math
import os
import re
import stat
from hashlib import sha256
from pathlib import PurePosixPath

from .coding_contract import (
    CheckSpec, CodingError, FactorySpec, LoopLimits, ModelSpec, RunnerSpec,
    canonical_json, strict_json,
)
from .model_runtime import validate_local_ollama_url

MAX_CONFIG_BYTES = 128 * 1024
RESERVED_PARTS = {".git", ".venv", "node_modules", "__pycache__"}


def relative_path(value: object) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 240
            or any(ord(char) < 32 for char in value) or "\\" in value or ":" in value):
        raise CodingError("invalid_path", "paths must be bounded relative POSIX file names")
    path = PurePosixPath(value)
    if (path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(part in RESERVED_PARTS for part in path.parts)):
        raise CodingError("invalid_path", "path is outside the allowed source namespace")
    return value


def _object(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise CodingError("invalid_config", "configuration has missing or unsupported fields")
    return value


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise CodingError("invalid_config", "configuration integer is outside its allowed range")
    return value


def _checks(value) -> tuple[CheckSpec, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 24:
        raise CodingError("invalid_config", "each check suite requires 1 to 24 cases")
    result = []
    for item in value:
        item = _object(item, {"name", "argv", "stdin", "expected_json", "kind", "expected_exit_code"},
                       {"name", "argv", "stdin", "expected_json", "kind"})
        name = item["name"]
        argv = item["argv"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,59}", name):
            raise CodingError("invalid_config", "check names must be stable lowercase identifiers")
        if (not isinstance(argv, list) or not 1 <= len(argv) <= 24
                or any(not isinstance(arg, str) or not arg or len(arg) > 4096 or "\0" in arg
                       for arg in argv) or argv[0].startswith("-")):
            raise CodingError("invalid_config", "checks require a bounded literal command argument list")
        if not isinstance(item["stdin"], str) or len(item["stdin"].encode("utf-8")) > 4096:
            raise CodingError("invalid_config", "check input must fit within 4096 UTF-8 bytes")
        if item["kind"] not in {"regression", "preserve"}:
            raise CodingError("invalid_config", "check kind must be regression or preserve")
        if len(canonical_json(item["expected_json"]).encode("utf-8")) > 8192:
            raise CodingError("invalid_config", "expected JSON exceeds the check contract limit")
        code = _integer(item.get("expected_exit_code", 0), 0, 122)
        result.append(CheckSpec(name, tuple(argv), item["stdin"], item["expected_json"],
                                item["kind"], code))
    return tuple(result)


def parse_spec(data: object) -> FactorySpec:
    data = _object(data, {"schema_version", "model", "runner", "limits", "read_paths",
                          "write_paths", "development_checks", "acceptance_checks"},
                   {"schema_version", "model", "runner", "read_paths", "write_paths",
                    "development_checks", "acceptance_checks"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise CodingError("invalid_config", "unsupported factory configuration version")
    model = _object(data["model"], {"name", "digest", "endpoint", "context_tokens", "output_tokens"},
                    {"name", "digest"})
    name = model["name"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", name):
        raise CodingError("invalid_config", "invalid local model name")
    digest = model["digest"]
    if not isinstance(digest, str):
        raise CodingError("invalid_config", "model digest is required")
    digest = digest.removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CodingError("invalid_config", "model digest must be SHA-256")
    endpoint = model.get("endpoint", "http://127.0.0.1:11434")
    try:
        endpoint = validate_local_ollama_url(endpoint)
    except (ValueError, TypeError, AttributeError):
        raise CodingError("invalid_config", "model endpoint must be an approved local Ollama origin") from None
    model_spec = ModelSpec(name, digest, endpoint,
                           _integer(model.get("context_tokens", 16384), 4096, 32768),
                           _integer(model.get("output_tokens", 1024), 128, 2048))
    runner = _object(data["runner"], {"image", "docker_context", "timeout_seconds", "memory_mb",
                                     "cpus", "pids", "tmpfs_mb", "output_bytes"}, {"image"})
    if not isinstance(runner["image"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", runner["image"]):
        raise CodingError("invalid_config", "runner image must be a preloaded immutable local image ID")
    context = runner.get("docker_context", "default")
    if not isinstance(context, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", context):
        raise CodingError("invalid_config", "invalid Docker context name")
    cpus = runner.get("cpus", 1.0)
    if type(cpus) not in {int, float} or not math.isfinite(cpus) or not .1 <= cpus <= 4:
        raise CodingError("invalid_config", "CPU limit must be between 0.1 and 4")
    runner_spec = RunnerSpec(
        runner["image"], context,
        _integer(runner.get("timeout_seconds", 15), 1, 120),
        _integer(runner.get("memory_mb", 256), 64, 2048), float(cpus),
        _integer(runner.get("pids", 64), 8, 256),
        _integer(runner.get("tmpfs_mb", 64), 64, 256),
        _integer(runner.get("output_bytes", 16384), 1024, 65536))
    if 2 * runner_spec.tmpfs_mb + 16 > runner_spec.memory_mb:
        raise CodingError("invalid_config", "memory must cover both tmpfs limits and shared memory")
    limits = _object(data.get("limits", {}), {"turns", "tool_calls", "total_tokens", "wall_seconds"})
    loop_limits = LoopLimits(
        _integer(limits.get("turns", 20), 1, 50),
        _integer(limits.get("tool_calls", 60), 1, 100),
        _integer(limits.get("total_tokens", 64000), 1024, 500000),
        _integer(limits.get("wall_seconds", 600), 30, 1800))
    paths = []
    for key in ("read_paths", "write_paths"):
        values = data[key]
        if not isinstance(values, list) or not 1 <= len(values) <= 128:
            raise CodingError("invalid_config", "read/write allowlists require 1 to 128 exact paths")
        values = tuple(relative_path(value) for value in values)
        if len(set(values)) != len(values):
            raise CodingError("invalid_config", "source allowlists contain duplicate paths")
        paths.append(values)
    if not set(paths[1]).issubset(paths[0]):
        raise CodingError("invalid_config", "editable files must also be readable")
    development, acceptance = (_checks(data[key]) for key in ("development_checks", "acceptance_checks"))
    all_checks = development + acceptance
    if len({check.name for check in all_checks}) != len(all_checks):
        raise CodingError("invalid_config", "check names must be unique across suites")
    if not any(check.kind == "regression" for check in development):
        raise CodingError("invalid_config", "development checks must contain a reproducer")
    if not any(check.kind == "preserve" for check in all_checks):
        raise CodingError("invalid_config", "at least one existing-behavior check is required")
    from dataclasses import asdict
    resolved = {"schema_version": 1, "model": asdict(model_spec), "runner": asdict(runner_spec),
                "limits": asdict(loop_limits), "read_paths": paths[0], "write_paths": paths[1],
                "development_checks": [asdict(check) for check in development],
                "acceptance_checks": [asdict(check) for check in acceptance]}
    fingerprint = sha256(canonical_json(resolved).encode("utf-8")).hexdigest()
    return FactorySpec(model_spec, runner_spec, loop_limits, paths[0], paths[1],
                       development, acceptance, fingerprint)


def load_spec(path: str | os.PathLike[str]) -> FactorySpec:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("not a regular file")
            payload = handle.read(MAX_CONFIG_BYTES + 1)
        if len(payload) > MAX_CONFIG_BYTES:
            raise ValueError("too large")
        return parse_spec(strict_json(payload))
    except CodingError:
        raise
    except (OSError, ValueError, TypeError, RecursionError, UnicodeError):
        raise CodingError("invalid_config", "configuration must be bounded, unambiguous UTF-8 JSON") from None
