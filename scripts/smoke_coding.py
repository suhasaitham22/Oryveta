"""Exercise the real local repair CLI on a deliberately defective two-file program.

Requires an explicitly provisioned local Ollama tool model and Docker image.
This is an integration smoke, not a coding-quality benchmark or a fake model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

GOAL = (
    "Fix numeric version ordering. The CLI reads a JSON list of dotted ASCII numeric version "
    "strings and returns the same strings sorted by the integer value of each component. "
    "For example, 1.2 sorts before 1.10, and 2.0 before 10.0. A proper prefix sorts first. "
    "Keep duplicates stable, preserve original spelling, and preserve the existing JSON "
    "error behavior for invalid input. Change only versions.py."
)
VERSIONS = '''import re


def sort_versions(values):
    if not isinstance(values, list) or any(
        not isinstance(value, str) or re.fullmatch(r"[0-9]+(?:\\.[0-9]+)*", value) is None
        for value in values
    ):
        raise ValueError("invalid versions")
    return sorted(values)
'''
ENTRY = '''import json
import sys
from versions import sort_versions

try:
    result = sort_versions(json.load(sys.stdin))
except (ValueError, TypeError):
    result = {"error": "invalid versions"}
print(json.dumps(result))
'''


def case(name, value, expected, kind):
    return {"name": name, "argv": ["python", "main.py"], "stdin": json.dumps(value),
            "expected_json": expected, "kind": kind}


def specification(model: str, digest: str, image: str, context: str) -> dict:
    """The operator contract both the repair smoke and the re-verification smoke use."""
    return {
        "schema_version": 1,
        "model": {"name": model, "digest": digest},
        "runner": {"image": image, "docker_context": context},
        "read_paths": ["main.py", "versions.py"], "write_paths": ["versions.py"],
        "development_checks": [
            case("numeric-order", ["1.10", "2.0", "1.2"], ["1.2", "1.10", "2.0"], "regression"),
            case("empty-list", [], [], "preserve"),
            case("invalid-input", ["1.x"], {"error": "invalid versions"}, "preserve"),
        ],
        "acceptance_checks": [
            case("major-order", ["10.0", "2.9", "2.10"], ["2.9", "2.10", "10.0"], "regression"),
            case("prefix-order", ["1.0.1", "1.0", "1", "0.9"], ["0.9", "1", "1.0", "1.0.1"], "preserve"),
            case("stable-duplicates", ["1.02", "1.2", "1.02", "1.10"], ["1.02", "1.2", "1.02", "1.10"], "regression"),
            case("original-spelling", ["01.2", "1.02", "1.10"], ["01.2", "1.02", "1.10"], "preserve"),
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--image", required=True, help="preloaded local sha256 image ID")
    parser.add_argument("--docker-context", default="default")
    parser.add_argument("--run-root", default=str(Path.home() / ".oryveta/repair-runs"))
    parser.add_argument("--output", required=True, help="new directory for retained evidence")
    args = parser.parse_args()
    contract = specification(args.model, args.model_digest, args.image, args.docker_context)
    with tempfile.TemporaryDirectory(prefix="oryveta-live-repair-") as directory:
        fixture = Path(directory)
        config = fixture / "operator.json"
        config.write_text(json.dumps(contract), encoding="utf-8")
        config.chmod(0o600)
        archive = fixture / "source.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("project/main.py", ENTRY)
            bundle.writestr("project/versions.py", VERSIONS)
        original = hashlib.sha256(archive.read_bytes()).hexdigest()
        command = [sys.executable, "-m", "oryveta_engine.coding_runtime", "--config", str(config),
                   "--source-zip", str(archive), "--goal", GOAL, "--run-root", args.run_root,
                   "--output", args.output]
        result = subprocess.run(command, env=os.environ.copy(), check=False)
        if result.returncode:
            raise SystemExit(result.returncode)
        receipt = json.loads((Path(args.output) / "receipt.json").read_text())
        if receipt["status"] != "needs_review" or receipt["verification"] != "passed":
            raise RuntimeError("the real repair did not pass its independent contracts")
        if hashlib.sha256(archive.read_bytes()).hexdigest() != original:
            raise RuntimeError("the input archive was modified")
        candidate = Path(args.output) / "candidate.zip"
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != receipt["candidate_archive_sha256"]:
            raise RuntimeError("the exported candidate does not match its recorded digest")
        print(json.dumps({"smoke": "real_local_model_and_containers", "checks_passed": receipt["checks_passed"],
                          "model_turns": receipt["turns"], "tool_calls": receipt["tool_calls"],
                          "tokens_observed": receipt["tokens_observed"], "publication": receipt["publication"]}))


if __name__ == "__main__":
    main()
