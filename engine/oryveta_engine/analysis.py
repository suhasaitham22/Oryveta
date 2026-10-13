"""Evidence-backed static review. Potential issues are explicitly not automatic fixes."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".sql"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", "target", ".next"}
MAX_FILES = 1600
MAX_BYTES_PER_FILE = 300_000
MAX_MANIFESTS = 48
MAX_MANIFEST_BYTES = 256_000
MANIFEST_FILES = frozenset({
    "package.json", "pyproject.toml", "requirements.txt", "Cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
})
JS_DEPENDENCY_HINTS = {
    "react": "React", "next": "Next.js", "vite": "Vite", "vue": "Vue",
    "svelte": "Svelte", "express": "Express", "@nestjs/core": "NestJS",
    "typescript": "TypeScript", "vitest": "Vitest", "jest": "Jest",
    "@playwright/test": "Playwright", "fastify": "Fastify",
    "@remix-run/react": "Remix",
}
PY_DEPENDENCY_HINTS = {
    "fastapi": "FastAPI", "django": "Django", "flask": "Flask",
    "pytest": "pytest", "ruff": "Ruff", "streamlit": "Streamlit",
    "torch": "PyTorch", "tensorflow": "TensorFlow",
    "langchain": "LangChain", "langgraph": "LangGraph",
}


def analyze_repository(root: Path) -> dict[str, Any]:
    root = root.resolve()
    findings: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    analyzed = 0
    skipped = 0
    fingerprint = hashlib.sha256(b'oryveta-analysis-v2\0')
    manifest_paths: list[Path] = []

    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.name in MANIFEST_FILES and len(manifest_paths) < MAX_MANIFESTS:
            manifest_paths.append(path)
        if path.suffix not in SOURCE_EXTENSIONS:
            continue
        if analyzed >= MAX_FILES:
            skipped += 1
            continue
        if path.stat().st_size > MAX_BYTES_PER_FILE:
            skipped += 1
            continue
        try:
            raw = path.read_bytes()
            if len(raw) > MAX_BYTES_PER_FILE:
                skipped += 1
                continue
            content = raw.decode("utf-8")
        except (UnicodeError, OSError):
            skipped += 1
            continue
        name = relative.as_posix()
        counts[path.suffix] = counts.get(path.suffix, 0) + 1
        _fingerprint_file(fingerprint, name, raw)
        analyzed += 1
        for number, line in enumerate(content.splitlines(), 1):
            if re.search(r"\b(FIXME|TODO|HACK)\b", line):
                _add(findings, name, number, "maintenance", "low", "Maintenance marker", "Review unresolved TODO/FIXME with owner context.", "high")
            # Python executable constructs are inspected from AST below,
            # avoiding false security findings for comments and docstrings.
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
    technologies = _profile_repository(root, manifest_paths, fingerprint, counts)
    kind = _language_label(counts)
    counts_by_type = {k: len([x for x in findings if x["category"] == k]) for k in {x["category"] for x in findings}}
    summary = {
        "language": kind, "language_files": counts, "source_files_analyzed": analyzed,
        "files_skipped": skipped, "findings_count": len(findings),
        "findings_returned": min(len(findings), 400),
        "findings_truncated": len(findings) > 400,
        "technology": technologies,
        "analysis_scope": "bounded static source and recognized manifests; no imported code executed",
        "by_category": counts_by_type,
        "modernization_options": [
            {"title": "Behavior-preserving cleanup", "note": "Prioritize verified bugs, unused candidates and regression tests."},
            {"title": "Dependency and tooling modernization", "note": "Upgrade with CI and behavioral comparisons."},
            {"title": "Rust migration assessment", "note": "Optional: benchmark bottlenecks first; rewrite only if justified by evidence."},
        ],
        "disclaimer": "Static heuristics, not a security audit or proof of unused code; human/CI review needed.",
    }
    summary["input_fingerprint_sha256"] = fingerprint.hexdigest()
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
        if isinstance(node, ast.Call):
            # AST checks deliberately don't treat comments and strings as executable code.
            if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                _add(findings, path, node.lineno, "security", "medium",
                     "Dynamic code execution",
                     "Audit the input origin and prefer explicit parsing.", "medium")
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"run", "Popen", "call", "check_call", "check_output"}
                    and any(kw.arg == "shell" and isinstance(kw.value, ast.Constant)
                            and kw.value.value is True for kw in node.keywords)):
                _add(findings, path, node.lineno, "security", "high",
                     "Shell invocation",
                     "Check for untrusted input and prefer argument-array subprocess calls.", "high")
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


def _fingerprint_file(digest: Any, relative_path: str, payload: bytes) -> None:
    """Hash complete bounded content with unambiguous path and length framing."""
    path_bytes = relative_path.encode("utf-8")
    digest.update(len(path_bytes).to_bytes(4, "big"))
    digest.update(path_bytes)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(hashlib.sha256(payload).digest())


def _language_label(counts: dict[str, int]) -> str:
    suffixes = set(counts)
    if not suffixes:
        return "Unknown"
    if suffixes <= {".js", ".jsx", ".ts", ".tsx"}:
        return "TypeScript/JavaScript" if suffixes & {".ts", ".tsx"} else "JavaScript"
    if suffixes <= {".py"}:
        return "Python"
    if suffixes <= {".rs"}:
        return "Rust"
    if suffixes <= {".go"}:
        return "Go"
    if suffixes <= {".java"}:
        return "Java"
    if suffixes <= {".sql"}:
        return "SQL"
    return "Mixed"


def _profile_repository(root: Path, paths: list[Path], fingerprint: Any,
                        counts: dict[str, int]) -> dict[str, Any]:
    """Best-effort, bounded manifest detection; never run install scripts or code."""
    frameworks: set[str] = set()
    package_managers: set[str] = set()
    detected_manifests: list[str] = []
    unreadable: list[str] = []

    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        try:
            if path.is_symlink() or path.stat().st_size > MAX_MANIFEST_BYTES:
                unreadable.append(relative)
                continue
            raw = path.read_bytes()
            if len(raw) > MAX_MANIFEST_BYTES:
                unreadable.append(relative)
                continue
            text = raw.decode("utf-8")
        except (OSError, UnicodeError):
            unreadable.append(relative)
            continue
        _fingerprint_file(fingerprint, relative, raw)
        detected_manifests.append(relative)
        try:
            if path.name == "package.json":
                manifest = json.loads(text)
                if not isinstance(manifest, dict):
                    unreadable.append(relative)
                    continue
                dependencies = set()
                for key in ("dependencies", "devDependencies", "peerDependencies"):
                    value = manifest.get(key, {})
                    if isinstance(value, dict):
                        dependencies.update(str(k).lower() for k in value)
                frameworks.update(name for key, name in JS_DEPENDENCY_HINTS.items()
                                  if key in dependencies)
                package_managers.add("npm-compatible")
                scripts = manifest.get("scripts", {})
                if isinstance(scripts, dict) and any("test" in str(key).lower() for key in scripts):
                    frameworks.add("test script configured")
            elif path.name == "pyproject.toml":
                manifest = tomllib.loads(text)
                project = manifest.get("project", {})
                tool = manifest.get("tool", {})
                dependencies = []
                if isinstance(project, dict):
                    dependencies += project.get("dependencies", []) if isinstance(project.get("dependencies", []), list) else []
                if isinstance(tool, dict):
                    poetry = tool.get("poetry", {})
                    if isinstance(poetry, dict):
                        dependencies += list(poetry.get("dependencies", {}))
                    if "pytest" in tool:
                        frameworks.add("pytest")
                _detect_python_dependencies(dependencies, frameworks)
                package_managers.add("Python packaging")
            elif path.name == "requirements.txt":
                _detect_python_dependencies(text.splitlines(), frameworks)
                package_managers.add("pip-compatible")
            elif path.name == "Cargo.toml":
                tomllib.loads(text)
                frameworks.add("Rust/Cargo")
                package_managers.add("Cargo")
            elif path.name == "go.mod":
                if text.lstrip().startswith("module "):
                    frameworks.add("Go modules")
                    package_managers.add("Go")
            elif path.name in {"pom.xml", "build.gradle", "build.gradle.kts"}:
                frameworks.add("Java/JVM build")
        except (ValueError, TypeError, AttributeError):
            # An invalid manifest is reported as unreadable, never executed.
            unreadable.append(relative)

    has_tests = any((root / directory).is_dir()
                    for directory in ("tests", "test", "__tests__"))
    has_ci = ((root / ".github" / "workflows").is_dir()
              or (root / ".gitlab-ci.yml").is_file()
              or (root / "azure-pipelines.yml").is_file())
    ecosystems = sorted({
        "Python" if ".py" in counts else "",
        "JavaScript/TypeScript" if set(counts) & {".js", ".jsx", ".ts", ".tsx"} else "",
        "Rust" if ".rs" in counts else "",
        "Go" if ".go" in counts else "",
        "Java" if ".java" in counts else "",
    } - {""})
    return {
        "ecosystems": ecosystems,
        "frameworks_and_tools": sorted(frameworks),
        "package_managers": sorted(package_managers),
        "manifests": detected_manifests,
        "unreadable_manifests": sorted(set(unreadable)),
        "test_directory_present": has_tests,
        "ci_config_present": has_ci,
        "confidence": "manifest-derived hints, not runtime verification",
    }


def _detect_python_dependencies(lines: list[str], frameworks: set[str]) -> None:
    for line in lines:
        if not isinstance(line, str):
            continue
        name = re.split(r"[\s=<>!~;\[\]]", line.strip().lower(), maxsplit=1)[0]
        if name in PY_DEPENDENCY_HINTS:
            frameworks.add(PY_DEPENDENCY_HINTS[name])
