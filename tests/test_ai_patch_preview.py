"""AI can suggest a diff, but cannot mutate, run or publish repository code."""

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from oryveta_api.config import Settings
from oryveta_api.main import create_app
from oryveta_engine.model_runtime import ModelCompletion


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class ReplacementModel:
    def __init__(self, replacement):
        self.replacement = replacement
        self.prompts = []

    async def complete(self, prompt, *, max_output_tokens, temperature):
        self.prompts.append(prompt)
        assert max_output_tokens == 512
        return ModelCompletion(self.replacement, 90, 50, "mock")


def setup(tmp_path, replacement='def value():\n    return 2\n'):
    settings = Settings(database_path=str(tmp_path / "db"),
                        workspace_root=str(tmp_path / "work"),
                        local_demo=True, ollama_model="llama3.2:latest")
    app = create_app(settings)
    fake = ReplacementModel(replacement)
    app.state.model_provider = fake
    client = TestClient(app)
    assert client.post('/auth/local-demo').status_code == 204
    headers = {'X-Oryveta-CSRF': client.get('/api/me').json()['csrf_token']}
    created = client.post('/api/projects', json={
        'name': 'Patch demo', 'brief': 'A safe read-only AI patch proposal',
        'blueprint': 'python-api',
    }, headers=headers)
    assert created.status_code == 201
    project_id = created.json()['id']
    path = Path(settings.workspace_root) / 'local-demo-user' / project_id / 'fix.py'
    original = 'def value():\n    return 1\n'
    path.write_text(original)
    payload = {'path': 'fix.py', 'expected_sha256': sha(original),
               'source': original, 'instruction': 'Change return value to two'}
    url = f'/api/projects/{project_id}/ai-patch-preview'
    return client, headers, fake, path, payload, url


def test_generated_patch_is_read_only_and_review_required(tmp_path):
    client, headers, fake, path, payload, url = setup(tmp_path)
    response = client.post(url, json=payload, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'review_required'
    assert result['applied'] is False and result['behavior_verified'] is False
    assert '+    return 2' in result['diff']
    assert result['checks'][-1] == {'name': 'python_syntax', 'status': 'passed'}
    assert path.read_text() == payload['source']
    assert len(fake.prompts) == 1 and 'BEGIN_UNTRUSTED_SOURCE' in fake.prompts[0]
    assert result['budget']['allocated_tokens'] == 140
    assert 'Human review required' in result['note']


def test_ai_patch_requires_csrf_and_project_ownership(tmp_path):
    client, headers, fake, path, payload, url = setup(tmp_path)
    assert client.post(url, json=payload).status_code == 403
    assert client.post('/api/projects/not-owned/ai-patch-preview', json=payload,
                       headers=headers).status_code == 404
    assert fake.prompts == []
    assert client.get('/api/ai/budget').json()['allocated_tokens'] == 0


def test_stale_or_incorrect_source_rejected_before_inference(tmp_path):
    client, headers, fake, path, payload, url = setup(tmp_path)
    wrong = client.post(url, json={**payload, 'source': 'x = 1\n'}, headers=headers)
    assert wrong.status_code == 409
    path.write_text('x = 2\n')
    stale = client.post(url, json=payload, headers=headers)
    assert stale.status_code == 409
    assert fake.prompts == []
    assert client.get('/api/ai/budget').json()['allocated_tokens'] == 0


def test_unsafe_path_and_symlink_rejected_before_inference(tmp_path):
    client, headers, fake, path, payload, url = setup(tmp_path)
    bad = client.post(url, json={**payload, 'path': '../fix.py'}, headers=headers)
    assert bad.status_code == 422
    alias = path.parent / 'alias.py'
    alias.symlink_to(path)
    bad_link = client.post(url, json={**payload, 'path': 'alias.py'}, headers=headers)
    assert bad_link.status_code == 422
    assert fake.prompts == []


def test_invalid_model_generated_python_is_rejected(tmp_path):
    client, headers, fake, path, payload, url = setup(tmp_path, 'def broken(:\n')
    result = client.post(url, json=payload, headers=headers)
    assert result.status_code == 422
    assert path.read_text() == payload['source']
    assert len(fake.prompts) == 1
    assert client.get('/api/ai/budget').json()['allocated_tokens'] == 140


def test_no_model_does_not_spend_tokens(tmp_path):
    client, headers, fake, path, payload, url = setup(tmp_path)
    client.app.state.model_provider = None
    response = client.post(url, json=payload, headers=headers)
    assert response.status_code == 503
    assert client.get('/api/ai/budget').json()['allocated_tokens'] == 0


def test_ai_patch_preview_allows_broken_original_python(tmp_path):
    client, headers, fake, path, payload, url = setup(tmp_path, 'def value():\n    return 2\n')
    broken = 'def value(:\n'
    path.write_text(broken)
    result = client.post(url, json={**payload, 'source': broken,
                                    'expected_sha256': sha(broken)}, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['applied'] is False
    assert path.read_text() == broken


def test_late_source_change_after_model_call_is_rejected(tmp_path):
    client, headers, fake, path, payload, url = setup(tmp_path)
    class MutatingModel:
        async def complete(self, prompt, *, max_output_tokens, temperature):
            path.write_text('changed concurrently\n')
            return ModelCompletion('def value():\n    return 2\n', 90, 50, 'mock')
    client.app.state.model_provider = MutatingModel()
    result = client.post(url, json=payload, headers=headers)
    assert result.status_code == 409
    assert path.read_text() == 'changed concurrently\n'
