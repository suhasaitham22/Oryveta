"""Exercise the real CLI re-verification path with no model of any kind.

The operator model name and digest are deliberately absent values: a correct
run never contacts an inference endpoint, so this smoke passes with Ollama
stopped or uninstalled. It still requires a preloaded local Docker image,
because every declared case really executes in a fresh container.

It checks two outcomes: an accepted candidate produces independent fresh
evidence, and a candidate that edits a file outside the operator's write
allowlist is refused before anything of it runs.
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

from smoke_coding import ENTRY, GOAL, VERSIONS, specification

# The repaired implementation a reviewer would submit for re-verification.
FIXED = '''import re


def sort_versions(values):
    if not isinstance(values, list) or any(
        not isinstance(value, str) or re.fullmatch(r"[0-9]+(?:\\.[0-9]+)*", value) is None
        for value in values
    ):
        raise ValueError("invalid versions")
    return sorted(values, key=lambda value: [int(part) for part in value.split(".")])
'''
# A candidate ZIP carries the same stable outer wrapper the CLI exports.
WRAPPER = "candidate"


def archive(path: Path, files: dict[str, str], wrapper: str) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(f"{wrapper}/{name}", data)
    return path


def run_cli(config: Path, source: Path, candidate: Path, output: Path, run_root: str) -> dict:
    command = [sys.executable, "-m", "oryveta_engine.coding_runtime", "--config", str(config),
               "--source-zip", str(source), "--candidate-zip", str(candidate),
               "--goal", GOAL, "--run-root", run_root, "--output", str(output)]
    result = subprocess.run(command, env=os.environ.copy(), check=False,
                            capture_output=True, text=True)
    for stream in (result.stdout, result.stderr):
        try:
            return {"exit_code": result.returncode, **json.loads(stream)}
        except ValueError:
            continue
    raise RuntimeError(f"the CLI did not report a JSON verdict (exit {result.returncode})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="preloaded local sha256 image ID")
    parser.add_argument("--docker-context", default="default")
    parser.add_argument("--model", default="absent-model",
                        help="syntactically valid model that intentionally does not exist")
    parser.add_argument("--model-digest", default="0" * 64)
    parser.add_argument("--run-root", default=str(Path.home() / ".oryveta/repair-runs"))
    parser.add_argument("--output", required=True, help="new directory for retained evidence")
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    contract = specification(args.model, args.model_digest, args.image, args.docker_context)
    with tempfile.TemporaryDirectory(prefix="oryveta-reverify-") as directory:
        fixture = Path(directory)
        config = fixture / "operator.json"
        config.write_text(json.dumps(contract), encoding="utf-8")
        config.chmod(0o600)
        source = archive(fixture / "source.zip",
                         {"main.py": ENTRY, "versions.py": VERSIONS}, "project")
        candidate = archive(fixture / "candidate.zip",
                            {"main.py": ENTRY, "versions.py": FIXED}, WRAPPER)
        tampered = archive(fixture / "tampered.zip",
                           {"main.py": ENTRY + 'print("extra")\n', "versions.py": FIXED}, WRAPPER)
        original = hashlib.sha256(source.read_bytes()).hexdigest()

        accepted = run_cli(config, source, candidate, root / "accepted", args.run_root)
        if accepted["exit_code"] or accepted["status"] != "needs_review":
            raise RuntimeError("the model-free re-verification did not pass its declared cases")
        receipt = json.loads((root / "accepted" / "receipt.json").read_text())
        if receipt["mode"] != "verification" or accepted["mode"] != "verification":
            raise RuntimeError("the run did not record itself as a re-verification")
        if receipt["model_calls"] or receipt["tokens_observed"] or receipt["turns"]:
            raise RuntimeError("re-verification must not spend any inference")
        if receipt["changed_paths"] != ["versions.py"]:
            raise RuntimeError("the recorded change scope does not match the candidate")
        if receipt["candidate_archive_sha256"] != hashlib.sha256(candidate.read_bytes()).hexdigest():
            raise RuntimeError("the receipt does not identify the submitted candidate archive")
        if (root / "accepted" / "candidate.zip").read_bytes() != candidate.read_bytes():
            raise RuntimeError("the retained candidate evidence is not the submitted archive")
        if receipt["checks_passed"] != 7 or not (root / "accepted" / "verified.patch").is_file():
            raise RuntimeError("the re-verification evidence is incomplete")

        refused = run_cli(config, source, tampered, root / "refused-scope", args.run_root)
        if refused["exit_code"] != 1 or refused["error_code"] != "candidate_scope":
            raise RuntimeError("a candidate editing a read-only file was not refused")
        if (root / "refused-scope" / "verification.json").exists():
            raise RuntimeError("a refused candidate must never be executed")
        if hashlib.sha256(source.read_bytes()).hexdigest() != original:
            raise RuntimeError("the input archive was modified")
        print(json.dumps({"smoke": "model_free_reverification_real_containers",
                          "checks_passed": receipt["checks_passed"],
                          "model_calls": receipt["model_calls"],
                          "tokens_observed": receipt["tokens_observed"],
                          "run_id": receipt["run_id"], "status": receipt["status"],
                          "verification": receipt["verification"],
                          "publication": receipt["publication"],
                          "refused_error_code": refused["error_code"]}))


if __name__ == "__main__":
    main()
