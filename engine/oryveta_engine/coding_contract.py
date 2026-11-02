"""Shared contracts for the local, fixed-policy repair loop.

This surface does not grant access: the operator configuration, isolated runner
and controller-owned verifier enforce the boundaries independently of the model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class CodingError(RuntimeError):
    """A safe operational failure code; messages must not contain upstream bodies."""

    def __init__(self, code: str, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def strict_json(value: str | bytes) -> Any:
    """Reject ambiguous duplicate keys and non-JSON numeric constants."""
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    def constant(_value):
        raise ValueError("non-finite JSON number")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    digest: str
    endpoint: str = "http://127.0.0.1:11434"
    context_tokens: int = 16384
    output_tokens: int = 1024


@dataclass(frozen=True)
class RunnerSpec:
    image: str
    docker_context: str = "default"
    timeout_seconds: int = 15
    memory_mb: int = 256
    cpus: float = 1.0
    pids: int = 64
    tmpfs_mb: int = 64
    output_bytes: int = 16384


@dataclass(frozen=True)
class LoopLimits:
    turns: int = 20
    tool_calls: int = 60
    total_tokens: int = 64000
    wall_seconds: int = 600


@dataclass(frozen=True)
class CheckSpec:
    name: str
    argv: tuple[str, ...]
    stdin: str
    expected_json: Any
    kind: str = "regression"
    expected_exit_code: int = 0


@dataclass(frozen=True)
class FactorySpec:
    model: ModelSpec
    runner: RunnerSpec
    limits: LoopLimits
    read_paths: tuple[str, ...]
    write_paths: tuple[str, ...]
    development_checks: tuple[CheckSpec, ...]
    acceptance_checks: tuple[CheckSpec, ...]
    digest: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelReply:
    content: str
    calls: tuple[ToolCall, ...]
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    duration_seconds: float
    container_name: str
