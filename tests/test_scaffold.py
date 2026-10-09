
import pytest
from oryveta_engine.scaffold import generate_files, project_slug, write_scaffold


def test_slugs_avoid_traversal():
    assert project_slug('../../Great App!!!') == 'great-app'
    with pytest.raises(ValueError):
        project_slug('!?.,/')


@pytest.mark.parametrize('blueprint', ['web-app', 'python-api', 'ai-service'])
def test_scaffolds_are_complete(blueprint, tmp_path):
    files = generate_files('<b>Test</b>', 'An implementation brief with enough detail.', blueprint)
    assert 'README.md' in files and 'oryveta.json' in files
    assert any(k.startswith('.github/workflows/') for k in files)
    assert any(k.startswith('tests/') for k in files)
    write_scaffold(tmp_path / 'workspace', files)
    assert (tmp_path / 'workspace' / 'README.md').exists()
    assert '<b>' not in files.get('index.html', '')
    assert 'starter repository' in files['README.md']


def test_invalid_blueprint():
    with pytest.raises(ValueError):
        generate_files('Test', 'Test brief', '../../tmp')
