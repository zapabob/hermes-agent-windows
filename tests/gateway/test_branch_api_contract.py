"""API fork persistence and failure order at the actual authenticated HTTP route."""

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from hermes_state import SessionDB


@pytest.fixture
def surface(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'home'))
    db = SessionDB(tmp_path / 'state.db')
    db.create_session('parent', source='api_server', system_prompt='EXACT PREFIX\n日本語')
    db.append_message('parent', role='user', content='Retained original')
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={'key': 'fixture-only-key'}))
    adapter._session_db = db
    app = web.Application()
    app.router.add_post('/api/sessions/{session_id}/fork', adapter._handle_fork_session)
    yield db, app
    db.close()


@pytest.mark.asyncio
async def test_authenticated_fork_persists_child_prompt_lineage_and_transcript(surface):
    db, app = surface
    async with TestClient(TestServer(app)) as client:
        response = await client.post('/api/sessions/parent/fork', json={'id': 'child', 'title': 'KeepCase 日本語'},
                                     headers={'Authorization': 'Bearer fixture-only-key'})
        assert response.status == 201
        result = await response.json()
    assert result['session']['id'] == 'child'
    child = db.get_session('child')
    assert child['parent_session_id'] == 'parent'
    assert child['system_prompt'] == 'EXACT PREFIX\n日本語'
    assert child['title'] == 'KeepCase 日本語'
    assert db.get_messages_as_conversation('child') == db.get_messages_as_conversation('parent')
    assert db.get_session('parent')['end_reason'] == 'branched'


@pytest.mark.asyncio
async def test_failed_authenticated_child_create_never_ends_the_parent(surface, monkeypatch):
    db, app = surface
    def fail(*args, **kwargs):
        raise RuntimeError('owned child-create failure')
    monkeypatch.setattr(db, 'create_session', fail)
    async with TestClient(TestServer(app)) as client:
        response = await client.post('/api/sessions/parent/fork', json={'id': 'child'},
                                     headers={'Authorization': 'Bearer fixture-only-key'})
        assert response.status == 500
        await response.read()
    assert db.get_session('parent')['ended_at'] is None
    assert db.get_session('child') is None
    assert db.get_messages_as_conversation('parent')[0]['content'] == 'Retained original'


@pytest.mark.asyncio
async def test_unauthenticated_fork_has_no_persistence_effect(surface):
    db, app = surface
    async with TestClient(TestServer(app)) as client:
        response = await client.post('/api/sessions/parent/fork', json={'id': 'child'})
        assert response.status == 401
        await response.read()
    assert db.get_session('parent')['ended_at'] is None
    assert db.get_session('child') is None


@pytest.mark.parametrize('failure,status', [('replace_messages', 500), ('set_session_title', 400)])
@pytest.mark.asyncio
async def test_authenticated_fork_preserves_actual_post_create_failure_state(surface, monkeypatch, failure, status):
    db, app = surface
    def fail(*args, **kwargs):
        raise ValueError('owned title rejection') if failure == 'set_session_title' else RuntimeError('owned copy failure')
    monkeypatch.setattr(db, failure, fail)
    async with TestClient(TestServer(app)) as client:
        response = await client.post('/api/sessions/parent/fork', json={'id': 'child', 'title': 'Child'},
                                     headers={'Authorization': 'Bearer fixture-only-key'})
        assert response.status == status
        await response.read()
    assert db.get_session('parent')['end_reason'] == 'branched'
    assert db.get_session('child')['parent_session_id'] == 'parent'
    assert db.get_session('child')['system_prompt'] == 'EXACT PREFIX\n日本語'
    if failure == 'replace_messages':
        assert db.get_messages('child') == []
    else:
        assert db.get_messages_as_conversation('child') == db.get_messages_as_conversation('parent')
        assert db.get_session_title('child') is None
