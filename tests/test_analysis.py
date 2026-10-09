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
