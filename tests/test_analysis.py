from oryveta_engine.analysis import analyze_repository


def test_analysis_evidence(tmp_path):
    (tmp_path / 'main.py').write_text('import math\n\ndef _unused():\n    return 1\n\ntry:\n    pass\nexcept:\n    pass\n',encoding='utf-8')
    summary = analyze_repository(tmp_path)
    titles = {finding['title'] for finding in summary['findings']}
    assert 'Bare except' in titles
    assert 'Possibly unused private function' in titles
    assert 'Possibly unused import' in titles
    assert 'Missing README' in titles
    assert summary['summary']['source_files_analyzed'] == 1
    assert len(summary['summary']['input_fingerprint_sha256']) == 64


def test_analysis_does_not_call_repo_code(tmp_path):
    (tmp_path/'crash.py').write_text('raise RuntimeError("should not execute")',encoding='utf8')
    assert analyze_repository(tmp_path)['summary']['source_files_analyzed']==1


def test_fingerprint_detects_changes_beyond_first_thousand_bytes(tmp_path):
    source = tmp_path / "main.py"
    source.write_text("#" * 1200 + "\nx = 1\n", encoding="utf-8")
    before = analyze_repository(tmp_path)["summary"]["input_fingerprint_sha256"]
    source.write_text("#" * 1200 + "\nx = 2\n", encoding="utf-8")
    after = analyze_repository(tmp_path)["summary"]["input_fingerprint_sha256"]
    assert before != after


def test_python_security_findings_are_ast_aware(tmp_path):
    (tmp_path / "code.py").write_text(
        '# shell=True and eval("evil") are comments\n'
        'doc = "eval(1); shell=True"\n'
        'import subprocess\n'
        'subprocess.run(["echo", "ok"], shell=True)\n'
        'value = eval("1+1")\n',
        encoding="utf-8",
    )
    result = analyze_repository(tmp_path)
    title_lines = [(f["title"], f["line"]) for f in result["findings"]
                   if f["title"] in {"Dynamic code execution", "Shell invocation"}]
    assert sorted(title_lines) == [("Dynamic code execution", 5), ("Shell invocation", 4)]


def test_detects_react_typescript_and_python_frameworks_without_execution(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"react":"^19","next":"^15"},'
        '"devDependencies":{"typescript":"5","vitest":"2"},'
        '"scripts":{"test":"vitest run"}}',
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="service"\nversion="0.1"\n'
        'dependencies=["fastapi>=0.100","pytest>=8"]\n',
        encoding="utf-8",
    )
    (tmp_path / "app.tsx").write_text("export const App = () => null;", encoding="utf-8")
    (tmp_path / "service.py").write_text("def run(): return True\n", encoding="utf-8")
    output = analyze_repository(tmp_path)["summary"]
    assert output["language"] == "Mixed"
    assert set(output["technology"]["frameworks_and_tools"]) >= {
        "React", "Next.js", "TypeScript", "Vitest", "FastAPI", "pytest"
    }
    assert "package.json" in output["technology"]["manifests"]
    assert "pyproject.toml" in output["technology"]["manifests"]
    assert len(output["input_fingerprint_sha256"]) == 64
    before = output["input_fingerprint_sha256"]
    (tmp_path / "package.json").write_text('{"dependencies":{}}', encoding="utf-8")
    assert analyze_repository(tmp_path)["summary"]["input_fingerprint_sha256"] != before


def test_truncation_is_reported_not_silently_hidden(tmp_path):
    (tmp_path / "large.py").write_text("# TODO\n" * 450, encoding="utf-8")
    result = analyze_repository(tmp_path)
    assert result["summary"]["findings_count"] > len(result["findings"])
    assert result["summary"]["findings_truncated"] is True
    assert result["summary"]["findings_returned"] == 400
