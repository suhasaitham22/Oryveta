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
