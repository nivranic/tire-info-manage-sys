"""Private synthetic provider/API checks; no real keys, model or source calls."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import threading
import time
from uuid import uuid4
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select

from tire_api import ai_analysis, ai_stream_store as store
from tire_api.ai_gateway import GatewayError, OpenAIConfig
from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.ai_stream_models import AIStreamEvent, AIStreamExecution
from tire_api.db import uid, utc, utcnow
from tire_api.domain import digest
from tire_api.embedding_budget import budget_usage
from tire_api.main import SESSION_COOKIE, create_app
from tire_api.service import QueryService
from test_ai import historical_pack
from test_core import FixtureRegistry


class HeldModel:
    def __init__(self):
        self.calls = 0
        self.release = threading.Event()
        self.failure = None

    async def stream(self, config, body, on_text):
        assert body['stream'] is True and body['store'] is False and body['background'] is False and body['tools'] == []
        self.calls += 1
        pack = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
        fact = pack['facts'][0]
        claim = {'type': 'fact', 'text': '', 'fact_ids': [fact['id']], 'evidence_ids': [fact['evidence_id']]}
        text = '{"claims":[' + json.dumps(claim) + '],"uncertainty":"synthetic stream"}'
        await on_text('{"claims":[' + json.dumps(claim) + ']')
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        if self.failure:
            raise GatewayError(self.failure)
        await on_text(',"uncertainty":"synthetic stream"}')
        return {'text': text, 'error': None, 'usage': {'input_tokens': 400, 'output_tokens': 60, 'total_tokens': 460},
                'provider_response_id': 'resp_synthetic_stream'}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    monkeypatch.setenv('TI_OBSERVABILITY_ENABLED', '0')
    monkeypatch.setattr(ai_analysis, 'configured_model', lambda: OpenAIConfig(
        model='synthetic-stream', api_key='synthetic-never-live', allow_private=True))
    app = create_app('sqlite:///' + (tmp_path / 'private-stream.sqlite').as_posix(), FixtureRegistry())
    model = HeldModel()
    app.state.ai_adapter = model
    @app.get('/fixture-loop')
    async def loop_probe():
        await asyncio.sleep(0)
        return {'responsive': True}
    with TestClient(app) as client:
        pack = historical_pack(client)
        yield client, model, app.state.database, app, pack
        model.release.set()


def payload(pack, **changes):
    return {'pack_id': pack['id'], 'question': '解释所选历史证据', 'allow_external_processing': True, **changes}


def accept(client, pack, key=None, **changes):
    return client.post('/v1/ai/analysis-streams', json=payload(pack, **changes),
                       headers={'Idempotency-Key': key or str(uuid4())})


def read(client, request_id):
    response = client.get('/v1/ai/analysis-streams/' + request_id + '?mode=history')
    assert response.status_code == 200, response.text
    return response.json()


def until(client, request_id, predicate):
    deadline = time.monotonic() + 5
    while True:
        data = read(client, request_id)
        if predicate(data):
            return data
        assert time.monotonic() < deadline, data['execution']
        time.sleep(0.01)


def seed_accepted(database, session_id, pack_id, *, expired=False):
    token = uid()
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        row = AIRequest(actor_session_id=session_id, idempotency_key=uid(), request_hash='a' * 64,
            pack_id=pack_id, question='synthetic crash boundary', provider='openai_responses', model='synthetic',
            request_contract={'delivery_mode': 'stream', 'purpose': 'analysis'}, reserved_tokens=1000)
        db.add(row)
        db.flush()
        store.create_execution_locked(db, row, token, utcnow() + timedelta(seconds=-1 if expired else 90))
        db.commit()
        return row.id, token


def test_accepted_drafts_final_and_replay_have_one_provider_and_completion(setup):
    client, model, database, _, pack = setup
    key = str(uuid4())
    response = accept(client, pack, key)
    assert response.status_code == 202
    request_id = response.json()['analysis']['id']
    draft = until(client, request_id, lambda value: bool(value['draft_claims']))
    assert draft['execution']['state'] == 'running' and draft['analysis']['answer'] is None
    assert draft['draft_claims'][0]['claim']['text'] == pack['facts'][0]['text']
    replay = accept(client, pack, key)
    assert replay.status_code == 202 and replay.json()['replayed'] and replay.json()['analysis']['id'] == request_id
    lookup = client.get('/v1/ai/analysis-streams/lookup', params={'mode': 'history', 'idempotency_key': key})
    assert lookup.status_code == 200 and lookup.json()['analysis']['id'] == request_id
    assert accept(client, pack, key, question='another intent').status_code == 409
    model.release.set()
    done = until(client, request_id, lambda value: value['execution']['terminal'])
    assert done['analysis']['state'] == done['execution']['state'] == 'completed'
    assert done['draft_claims'] == [] and done['draft_uncertainty'] is None
    assert done['analysis']['answer']['claims'][0]['text'] == pack['facts'][0]['text']
    assert accept(client, pack, key).status_code == 200
    assert model.calls == 1
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AIRequest)) == 1
        assert db.scalar(select(func.count()).select_from(AICompletion)) == 1
    events = client.get('/v1/ai/analysis-streams/' + request_id + '/events').json()
    assert [row['type'] for row in events['items']] == ['accepted', 'started', 'claim_draft', 'uncertainty_draft', 'completed']
    assert all('answer' not in row['payload'] for row in events['items'])
    assert client.get('/v1/ai/analyses/' + request_id + '?mode=history').json()['answer'] == done['analysis']['answer']


def test_unknown_keeps_reservation_hides_draft_and_rejects_report_analysis(setup):
    client, model, database, _, pack = setup
    model.failure = 'ai_stream_interrupted'
    request_id = accept(client, pack).json()['analysis']['id']
    until(client, request_id, lambda value: bool(value['draft_claims']))
    model.release.set()
    done = until(client, request_id, lambda value: value['execution']['terminal'])
    assert done['analysis']['state'] == 'outcome_unknown' and done['analysis']['answer'] is None
    assert not done['execution']['projection_only'] and done['draft_claims'] == []
    with database.sessions() as db:
        assert db.get(AICompletion, request_id).usage is None
        budget = budget_usage(db)
        assert budget['accounted_tokens'] == db.get(AIRequest, request_id).reserved_tokens
        assert not budget['has_pending_request']
    response = client.post('/v1/reports', json={'mode': 'history', 'pack_id': pack['id'], 'analysis_id': request_id,
        'title': 'synthetic unfinished analysis'}, headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 409


def test_scope_cursor_paging_and_unknown_post_lookup_are_read_only(setup):
    client, model, database, app, pack = setup
    key = str(uuid4())
    request_id = accept(client, pack, key).json()['analysis']['id']
    until(client, request_id, lambda value: bool(value['draft_claims']))
    path = '/v1/ai/analysis-streams/' + request_id
    first = client.get(path + '/events?limit=1').json()
    assert first['items'][0]['type'] == 'accepted' and first['has_more']
    next_page = client.get(path + '/events', params={'cursor': first['next_cursor']}).json()
    assert [row['type'] for row in next_page['items']] == ['started', 'claim_draft']
    for cursor in ('invalid', store.cursor(uid())):
        error = client.get(path + '/events', params={'cursor': cursor})
        assert error.status_code == 409 and error.json()['detail']['code'] == 'ai_stream_cursor_reset_required'
    assert client.get(path + '/events?limit=101').status_code == 422
    assert client.get('/v1/ai/analysis-streams/lookup', params={
        'mode': 'history', 'idempotency_key': str(uuid4())}).status_code == 404
    with TestClient(create_app(str(database.engine.url), FixtureRegistry())) as stranger:
        assert stranger.get(path + '?mode=history').status_code == 404
        for suffix in ('/events?cursor=invalid', '/events/stream?cursor=invalid'):
            assert stranger.get(path + suffix).status_code == 404
        assert stranger.get('/v1/ai/analysis-streams/lookup', params={'mode': 'history', 'idempotency_key': key}).status_code == 404
    assert model.calls == 1
    public = json.dumps(read(client, request_id)) + json.dumps(next_page)
    assert 'owner_token' not in public and client.cookies.get(SESSION_COOKIE) not in public


def test_expired_owner_is_read_only_unknown_and_cannot_start_or_finish(setup):
    client, model, database, _, pack = setup
    request_id, token = seed_accepted(database, client.cookies.get(SESSION_COOKIE), pack['id'], expired=True)
    first = read(client, request_id)
    assert first['execution']['state'] == first['analysis']['state'] == 'outcome_unknown'
    assert first['execution']['projection_only'] and first['execution']['terminal']
    assert not store.start_execution(database, request_id, token)
    assert not store.finish_execution(database, request_id, token, state='failed', error_code='ai_provider_failed')
    assert not store.finish_execution(database, request_id, uid(), state='outcome_unknown', error_code='ai_stream_interrupted')
    with database.sessions() as db:
        assert db.get(AICompletion, request_id) is None
        assert db.scalar(select(func.count()).select_from(AIStreamEvent)) == 1
        assert budget_usage(db)['has_pending_request']
    assert client.get('/v1/ai/analyses/' + request_id + '?mode=history').json()['state'] == 'outcome_unknown'
    assert model.calls == 0


def test_atomic_reservation_failure_never_creates_request_or_provider_call(setup, monkeypatch):
    client, model, database, _, pack = setup
    original = store.create_execution_locked
    def fail(db, request, owner_token):
        original(db, request, owner_token)
        raise RuntimeError('synthetic reservation failure')
    monkeypatch.setattr(store, 'create_execution_locked', fail)
    with pytest.raises(Exception):
        accept(client, pack)
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AIRequest)) == 0
        assert db.scalar(select(func.count()).select_from(AIStreamExecution)) == 0
        assert db.scalar(select(func.count()).select_from(AIStreamEvent)) == 0
    assert model.calls == 0


def test_completion_and_terminal_event_rollback_together(setup):
    client, _, database, _, pack = setup
    request_id, token = seed_accepted(database, client.cookies.get(SESSION_COOKIE), pack['id'])
    assert store.start_execution(database, request_id, token)
    def fail_terminal(_conn, _cursor, statement, parameters, _context, _many):
        if statement.startswith('INSERT INTO ai_stream_events'):
            raise RuntimeError('synthetic terminal write failure')
    event.listen(database.engine, 'before_cursor_execute', fail_terminal)
    try:
        with pytest.raises(RuntimeError, match='synthetic terminal'):
            store.finish_execution(database, request_id, token, state='outcome_unknown', error_code='ai_stream_interrupted')
    finally:
        event.remove(database.engine, 'before_cursor_execute', fail_terminal)
    with database.sessions() as db:
        assert db.get(AICompletion, request_id) is None
        assert db.scalar(select(func.count()).select_from(AIStreamEvent)) == 2
    assert store.finish_execution(database, request_id, token, state='outcome_unknown', error_code='ai_stream_interrupted')
    assert not store.finish_execution(database, request_id, token, state='failed', error_code='private secret error')


@pytest.mark.parametrize('changes,status', [({'allow_external_processing': False}, 422),
    ({'question': '当前参数如何'}, 409), ({'pack_id': 'missing'}, 404)])
def test_stream_reuses_scope_consent_and_current_question_gates(setup, changes, status):
    client, model, database, _, pack = setup
    assert accept(client, pack, **changes).status_code == status
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AIRequest)) == 0
    assert model.calls == 0


def grounded_fixture(pack):
    fact = pack['facts'][0]
    return ai_analysis.grounded_answer(json.dumps({'claims': [{'type': 'fact', 'text': '',
        'fact_ids': [fact['id']], 'evidence_ids': [fact['evidence_id']]}], 'uncertainty': 'synthetic'}),
        SimpleNamespace(payload=pack, data_state=pack['data_state']))


@pytest.mark.parametrize('operation', ['started', 'claim_draft', 'completed'])
def test_write_crossing_owner_deadline_rolls_back_before_commit(setup, monkeypatch, operation):
    client, _, database, _, pack = setup
    request_id, token = seed_accepted(database, client.cookies.get(SESSION_COOKIE), pack['id'])
    answer = grounded_fixture(pack)
    if operation != 'started':
        assert store.start_execution(database, request_id, token)
    with database.sessions() as db:
        deadline = utc(db.get(AIStreamExecution, request_id).deadline_at)
        before = db.scalar(select(func.count()).select_from(AIStreamEvent))
    original = store._append
    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(store, 'utcnow', lambda: deadline + timedelta(seconds=1))
        return result
    monkeypatch.setattr(store, '_append', delayed)
    if operation == 'started':
        result = store.start_execution(database, request_id, token)
    elif operation == 'claim_draft':
        result = store.append_event(database, request_id, token, 'claim_draft', {'index': 0, 'claim': answer['claims'][0]})
    else:
        result = store.finish_execution(database, request_id, token, state='completed', answer=answer)
    assert result is False
    with database.sessions() as db:
        assert db.get(AICompletion, request_id) is None
        assert db.scalar(select(func.count()).select_from(AIStreamEvent)) == before


def test_detail_freezes_completion_once_and_limits_drafts_to_its_cursor(setup, monkeypatch):
    client, _, database, _, pack = setup
    request_id, token = seed_accepted(database, client.cookies.get(SESSION_COOKIE), pack['id'])
    answer = grounded_fixture(pack)
    original = store.execution_view
    def concurrent_progress(*args, **kwargs):
        result = original(*args, **kwargs)
        assert store.start_execution(database, request_id, token)
        assert store.append_event(database, request_id, token, 'claim_draft', {'index': 0, 'claim': answer['claims'][0]})
        return result
    with monkeypatch.context() as scoped:
        scoped.setattr(store, 'execution_view', concurrent_progress)
        first = read(client, request_id)
    assert first['execution']['state'] == 'accepted' and first['analysis']['state'] == 'pending'
    assert first['draft_claims'] == []
    def concurrent_completion(*args, **kwargs):
        result = original(*args, **kwargs)
        assert store.finish_execution(database, request_id, token, state='completed', answer=answer)
        return result
    with monkeypatch.context() as scoped:
        scoped.setattr(store, 'execution_view', concurrent_completion)
        second = read(client, request_id)
    assert second['execution']['state'] == 'running' and second['analysis']['state'] == 'pending'
    assert second['analysis']['answer'] is None


def test_acceptance_waiting_for_database_lock_does_not_block_event_loop(setup, monkeypatch):
    client, _, database, _, pack = setup
    entered, acquired, release = threading.Event(), threading.Event(), threading.Event()
    original = QueryService.lock_ingestion
    def holder():
        with database.sessions() as locked:
            original(QueryService(locked, None))
            acquired.set()
            assert release.wait(5)
            locked.rollback()
    with ThreadPoolExecutor(max_workers=2) as pool:
        held = pool.submit(holder)
        assert acquired.wait(2)
        def observing(self):
            entered.set()
            return original(self)
        monkeypatch.setattr(QueryService, 'lock_ingestion', observing)
        waiting = pool.submit(accept, client, pack)
        assert entered.wait(2)
        timer = threading.Timer(0.7, release.set)
        timer.start()
        try:
            assert client.get('/fixture-loop').json() == {'responsive': True}
            assert not release.is_set(), 'loop was blocked until the database lock released'
        finally:
            release.set()
            timer.join()
        held.result(timeout=2)
        assert waiting.result(timeout=3).status_code == 202
