import pytest
from fastapi.testclient import TestClient

from oryveta_api.config import Settings
from oryveta_api.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(database_path=str(tmp_path / 'oryveta.db'),
                              workspace_root=str(tmp_path / 'workspaces'),
                              local_demo=True))
    return TestClient(app)


@pytest.fixture
def signed_in(client):
    assert client.post('/auth/local-demo').status_code == 204
    user = client.get('/api/me').json()
    return client, {'X-Oryveta-CSRF': user['csrf_token']}


@pytest.fixture
def coding_spec_data():
    return {
        "schema_version": 1,
        "model": {"name": "qwen3:8b", "digest": "a" * 64},
        "runner": {"image": "sha256:" + "b" * 64},
        "read_paths": ["main.py"],
        "write_paths": ["main.py"],
        "development_checks": [
            {"name": "increment", "argv": ["python", "main.py"],
             "stdin": "1", "expected_json": 3, "kind": "regression"},
            {"name": "empty", "argv": ["python", "main.py"],
             "stdin": "null", "expected_json": None, "kind": "preserve"},
        ],
        "acceptance_checks": [
            {"name": "acceptance-private-marker", "argv": ["python", "main.py"],
             "stdin": "5", "expected_json": 7, "kind": "regression"},
        ],
    }
