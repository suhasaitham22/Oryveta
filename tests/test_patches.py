"""Regression tests for bounded, read-only Evolve patch previews."""

import hashlib

import pytest

from oryveta_engine.patches import InvalidPatch, StalePatch, preview_patch


def sha(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def test_read_only_python_preview(tmp_path):
    old = 'def value():\n    return 1\n'
    new = 'def value():\n    return 2\n'
    source = tmp_path / 'main.py'
    source.write_text(old)
    result = preview_patch(tmp_path, 'main.py', sha(old), new)
    assert result['baseline_sha256'] == sha(old)
    assert result['proposed_sha256'] == sha(new)
    assert '+    return 2' in result['diff']
    assert result['status'] == 'review_required'
    assert result['applied'] is False and result['behavior_verified'] is False
    assert result['checks'][-1] == {'name': 'python_syntax', 'status': 'passed'}
    assert source.read_text() == old


def test_stale_source_rejected(tmp_path):
    (tmp_path / 'a.py').write_text('x = 2\n')
    with pytest.raises(StalePatch, match='Source changed'):
        preview_patch(tmp_path, 'a.py', sha('x = 1\n'), 'x = 3\n')


@pytest.mark.parametrize('name', ['../outside.py', '/tmp/a.py', 'src/../../a.py', 'a\\b.py', '.git/config', 'node_modules/a.py', 'main.exe'])
def test_unsafe_paths_rejected(tmp_path, name):
    (tmp_path / 'main.exe').write_text('hello')
    with pytest.raises(InvalidPatch):
        preview_patch(tmp_path, name, sha('hello'), 'new')


def test_symlink_rejected(tmp_path):
    (tmp_path / 'real.py').write_text('x = 1\n')
    (tmp_path / 'alias.py').symlink_to(tmp_path / 'real.py')
    with pytest.raises(InvalidPatch, match='Symlinks'):
        preview_patch(tmp_path, 'alias.py', sha('x = 1\n'), 'x = 2\n')


def test_syntax_rejected_without_writing(tmp_path):
    source = tmp_path / 'main.py'
    source.write_text('x = 1\n')
    with pytest.raises(InvalidPatch, match='syntax error'):
        preview_patch(tmp_path, 'main.py', sha('x = 1\n'), 'def broken(:\n')
    assert source.read_text() == 'x = 1\n'


def test_no_change_is_explicit(tmp_path):
    (tmp_path / 'main.py').write_text('x = 1\n')
    result = preview_patch(tmp_path, 'main.py', sha('x = 1\n'), 'x = 1\n')
    assert result['diff'] == ''
    assert result['changed'] is False


def test_binary_and_oversize_rejected(tmp_path):
    (tmp_path / 'a.py').write_bytes(b'hello\x00')
    with pytest.raises(InvalidPatch):
        preview_patch(tmp_path, 'a.py', hashlib.sha256(b'hello\x00').hexdigest(), 'x = 1\n')
    (tmp_path / 'a.py').write_text('x = 1\n')
    with pytest.raises(InvalidPatch):
        preview_patch(tmp_path, 'a.py', sha('x = 1\n'), 'a' * (128 * 1024 + 1))


def test_invalid_digest_rejected(tmp_path):
    (tmp_path / 'a.py').write_text('x = 1\n')
    with pytest.raises(InvalidPatch, match='SHA-256'):
        preview_patch(tmp_path, 'a.py', 'NOT_A_SHA', 'x = 2\n')


def test_authenticated_patch_preview_api(signed_in):
    client, headers = signed_in
    created = client.post('/api/projects', json={
        'name': 'Patch demo', 'brief': 'Demonstrate a read-only patch preview',
        'blueprint': 'python-api',
    }, headers=headers)
    assert created.status_code == 201
    project_id = created.json()['id']
    root = (client.app.state.settings.workspace_root)
    from pathlib import Path
    source = Path(root) / 'local-demo-user' / project_id / 'README.md'
    old = source.read_text()
    replacement = old + '\nPatch review only.\n'
    endpoint = f'/api/projects/{project_id}/patch-preview'
    payload = {'path': 'README.md', 'expected_sha256': sha(old), 'replacement': replacement}
    assert client.post(endpoint, json=payload).status_code == 403
    response = client.post(endpoint, json=payload, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'review_required'
    assert response.json()['applied'] is False
    assert source.read_text() == old
    assert client.post(endpoint, json={**payload, 'expected_sha256': sha('stale')},
                       headers=headers).status_code == 409
    assert client.post(endpoint, json={**payload, 'path': '../secrets.py'},
                       headers=headers).status_code == 422
    assert client.post('/api/projects/not-owned/patch-preview', json=payload,
                       headers=headers).status_code == 404
