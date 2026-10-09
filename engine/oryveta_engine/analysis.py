"""Evidence-backed static review. Potential issues are explicitly not automatic fixes."""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".sql"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", "target", ".next"}
MAX_FILES = 1600
MAX_BYTES_PER_FILE = 300_000


def analyze_repository(root: Path) -> dict[str, Any]:
    root = root.resolve()
    findings: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    analyzed = 0
    skipped = 0
    indexed: list[tuple[Path, str, str]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_symlink() or path.suffix not in SOURCE_EXTENSIONS:
            continue
        if analyzed >= MAX_FILES:
            skipped += 1
            continue
        if path.stat().st_size > MAX_BYTES_PER_FILE:
            skipped += 1
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            skipped += 1
            continue
        name = path.relative_to(root).as_posix()
        counts[path.suffix] = counts.get(path.suffix, 0) + 1
        indexed.append((path, name, content))
        analyzed += 1
        for number, line in enumerate(content.splitlines(), 1):
            if re.search(r"\b(FIXME|TODO|HACK)\b", line):
                _add(findings, name, number, "maintenance", "low", "Maintenance marker", "Review unresolved TODO/FIXME with owner context.", "high")
            if re.search(r"\b(eval|exec)\s*\(", line) and path.suffix == ".py":
                _add(findings, name, number, "security", "medium", "Dynamic code execution", "Audit input origin and replace with explicit parsing where practical.", "medium")
            if "shell=True" in line and path.suffix == ".py":
                _add(findings, name, number, "security", "high", "Shell invocation", "Check for untrusted input and replace with argument-array subprocess calls.", "high")
            if re.search(r"\b(console\.log|debugger)\b", line) and path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
                _add(findings, name, number, "quality", "low", "Debugging statement", "Consider structured logging or removing debug-only behavior.", "high")
        if path.suffix == ".py":
            _inspect_python(name, content, findings)

    if not (root / "README.md").is_file():
        _add(findings, "README.md", 0, "maintainability", "medium", "Missing README", "Document how to run, test and maintain the repository.", "high")
    if not any((root / t).exists() for t in ["tests", "test", "__tests__"]):
        _add(findings, "", 0, "testing", "medium", "No conventional test directory", "Confirm test coverage and add regression tests before larger refactors.", "medium")
    if (root / "requirements.txt").is_file():
        for number, line in enumerate((root / "requirements.txt").read_text(errors="replace").splitlines(), 1):
            line = line.strip()
            if line and not line.startswith("#") and not any(x in line for x in ["==", "@", ">=", "~="]):
                _add(findings, "requirements.txt", number, "dependencies", "low", "Unconstrained dependency", "Pin or constrain this dependency to improve reproducibility.", "high")
    kind = "Mixed" if len(counts) > 1 else ({".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".rs": "Rust"}.get(next(iter(counts), ""), "Unknown"))
    counts_by_type = {k: len([x for x in findings if x["category"] == k]) for k in {x["category"] for x in findings}}
    summary = {
        "language": kind, "language_files": counts, "source_files_analyzed": analyzed,
        "files_skipped": skipped, "findings_count": len(findings),
        "by_category": counts_by_type,
        "modernization_options": [
            {"title": "Behavior-preserving cleanup", "note": "Prioritize verified bugs, unused candidates and regression tests."},
            {"title": "Dependency and tooling modernization", "note": "Upgrade with CI and behavioral comparisons."},
            {"title": "Rust migration assessment", "note": "Optional: benchmark bottlenecks first; rewrite only if justified by evidence."},
        ],
        "disclaimer": "Static heuristics, not a security audit or proof of unused code; human/CI review needed.",
    }
    evidence = repr([(p, content[:1000]) for _, p, content in indexed]).encode()
    summary["input_fingerprint_sha256"] = hashlib.sha256(evidence).hexdigest()
    return {"summary": summary, "findings": findings[:400]}


def _add(items: list, path: str, line: int, category: str, severity: str,
         title: str, recommendation: str, confidence: str) -> None:
    items.append({"path": path, "line": line, "category": category, "severity": severity,
                  "title": title, "recommendation": recommendation, "confidence": confidence})


def _inspect_python(path: str, content: str, findings: list) -> None:
    try:
        tree = ast.parse(content)
    except SyntaxError as err:
        _add(findings, path, err.lineno or 0, "correctness", "high", "Python syntax error", str(err.msg), "high")
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            _add(findings, path, node.lineno, "correctness", "medium", "Bare except", "Catch explicit exception types and handle failure deliberately.", "high")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_") and not node.name.startswith("__"):
            occurrences = len(re.findall(r"\b" + re.escape(node.name) + r"\b", content))
            if occurrences == 1:
                _add(findings, path, node.lineno, "dead-code-candidate", "low", "Possibly unused private function", "Check dynamic references and external imports before removing.", "low")
        if isinstance(node, ast.Import):
            for name in node.names:
                bound = name.asname or name.name.split(".")[0]
                if len(re.findall(r"\b" + re.escape(bound) + r"\b", content)) == 1:
                    _add(findings, path, node.lineno, "dead-code-candidate", "low", "Possibly unused import", "Confirm via Ruff F401 before removing.", "medium")
