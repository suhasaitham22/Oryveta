import io
import zipfile
from fastapi.testclient import TestClient
from oryveta_api.config import Settings
from oryveta_api.main import create_app
from oryveta_engine.worker import Worker


def test_public_and_auth_endpoints(client):
    assert client.get('/').status_code == 200
    assert client.get('/static/styles.css').status_code == 200
    assert client.get('/api/health').json()['status'] == 'ok'
    assert client.get('/api/projects').status_code == 401
    assert client.get('/api/config').json()['navigation'] == ['Start New','Evolve']


def test_csrf_enforced(signed_in):
    client, headers = signed_in
    assert client.post('/api/projects',json={'name':'Demo','brief':'A test application','blueprint':'python-api'}).status_code == 403
    bad = client.post('/api/projects',json={'name':'Demo','brief':'A test application','blueprint':'python-api'},headers={'X-Oryveta-CSRF':'bogus'})
    assert bad.status_code == 403


def test_create_export_and_scoped_access(signed_in, tmp_path):
    client, headers = signed_in
    made=client.post('/api/projects',json={'name':'Good API','brief':'An API for customer records','blueprint':'python-api'},headers=headers)
    assert made.status_code==201, made.text
    project_id=made.json()['id']
    assert made.json()['note'].startswith('Runnable starter')
    detail=client.get('/api/projects/'+project_id).json()
    assert 'tests/test_api.py' in detail['files']
    export=client.get('/api/projects/'+project_id+'/export')
    assert export.status_code==200
    with zipfile.ZipFile(io.BytesIO(export.content)) as z:
        assert 'Dockerfile' in z.namelist()
        assert '.github/workflows/ci.yml' in z.namelist()
    assert client.get('/api/projects/not-my-project').status_code==404
    another=TestClient(create_app(Settings(database_path=str(tmp_path/'separate.db'),workspace_root=str(tmp_path/'other'),local_demo=True)))
    assert another.get('/api/projects/'+project_id).status_code==401


def test_import_scan_and_data_isolation(signed_in):
    client, headers=signed_in
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('demo/README.md','# Demo')
        z.writestr('demo/main.py','def broken(:\n    pass\n')
        z.writestr('demo/lib.py','import math\n# TODO fix\n')
    resp=client.post('/api/projects/import/zip',headers={**headers,'Content-Type':'application/zip','X-Project-Name':'Demo repo'},content=buf.getvalue())
    assert resp.status_code==201,resp.text
    project_id=resp.json()['id']
    assert resp.json()['status']=='analyzing'
    assert client.get('/api/projects/'+project_id).json()['analysis'] is None
    worker=Worker(client.app.state.db, client.app.state.settings.workspace_root)
    assert worker.run_once() is True
    project=client.get('/api/projects/'+project_id).json()
    assert project['status']=='analyzed'
    assert project['analysis']['summary']['findings_count']>=2
    assert any(f['title']=='Python syntax error' for f in project['analysis']['findings'])
    assert client.get('/api/activity').json()


def test_import_unsafe_archive_rejected(signed_in):
    client,headers=signed_in
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('../evil.py','print(1)')
    resp=client.post('/api/projects/import/zip',headers={**headers,'Content-Type':'application/zip'},content=b.getvalue())
    assert resp.status_code==422


def test_github_import_validation_no_fetch(signed_in):
    client,headers=signed_in
    assert client.post('/api/projects/import/github',json={'url':'https://notgithub.com/org/repo'},headers=headers).status_code==422


def test_benchmark_worker(signed_in):
    client,headers=signed_in
    r=client.post('/api/internal/evaluations/runs',json={'challenge':'iris','seed':42},headers=headers)
    assert r.status_code==202
    worker=Worker(client.app.state.db,client.app.state.settings.workspace_root)
    assert worker.run_once()
    runs=client.get('/api/internal/evaluations/runs').json()
    assert runs[0]['status']=='succeeded'
    assert runs[0]['result']['best_score']>0


def test_cross_account_project_access_is_denied(signed_in):
    from oryveta_api.auth import new_session
    client, headers = signed_in
    made = client.post('/api/projects', json={
        'name':'Private API','brief':'Confidential private API','blueprint':'python-api'
    },headers=headers).json()
    with client.app.state.db.connect() as conn:
        conn.execute("""INSERT INTO users(id,github_id,login,display_name,avatar_url,created_at)
            VALUES('second','github-other','other','Other','',0)""")
    token = new_session(client.app.state.db, 'second')
    other = TestClient(client.app)
    other.cookies.set('oryveta_session', token)
    assert other.get('/api/projects').json() == []
    assert other.get('/api/projects/'+made['id']).status_code == 404
    assert other.get('/api/projects/'+made['id']+'/export').status_code == 404
    csrf = other.get('/api/me').json()['csrf_token']
    assert other.post('/api/projects/'+made['id']+'/analyze',
                      headers={'X-Oryveta-CSRF':csrf}).status_code == 404


def test_origin_header_rejection(signed_in):
    client,headers=signed_in
    assert client.post('/api/projects',json={
        'name':'Bad origin','brief':'Do not create this','blueprint':'python-api'
    },headers={**headers,'Origin':'https://attacker.invalid'}).status_code == 403
