"""Private SQLite and synthetic adapters exercise recall consumers, never live AI."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
import threading

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from tire_api import ai_analysis, ai_stream_store as store
from tire_api.ai_gateway import OpenAIConfig
from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.ai_stream_models import AIStreamEvent
from tire_api.db import utcnow
from tire_api.domain import digest
from tire_api.main import SESSION_COOKIE, create_app
from tire_api.recall_evidence import recall_boundary_descriptor
from tire_api.recall_models import RecallVerification
from test_ai import analyze
from test_ai_stream_api import accept, seed_accepted, until
from test_recalls import NoTireSource, RecallFixture, live, record
from test_reports import export, save


class RecallModel:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.release = threading.Event()
        self.release.set()

    def output(self, body):
        self.calls.append(deepcopy(body))
        payload = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
        facts = [item for item in payload['facts'] if item['scope'] == 'record' and item['field_code'] == 'recall.remedy']
        selected = facts[:1] or payload['facts'][:1]
        result = {'claims': [{'type': 'fact', 'text': '', 'fact_ids': [item['id'] for item in selected],
                              'evidence_ids': [selected[0]['evidence_id']]}], 'uncertainty': ''}
        if self.failure == 'inference': result['claims'][0].update(type='inference', text='该实物没有安全风险')
        if self.failure == 'uncertainty': result['uncertainty'] = '该轮胎未受召回影响'
        if self.failure == 'cross_record': result['claims'][0]['fact_ids'] = [item['id'] for item in facts]
        return result

    def receipt(self, text):
        return {'text': text, 'error': None, 'usage': {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120},
                'provider_response_id': 'resp_synthetic_recall'}

    async def generate(self, _config, body):
        return self.receipt(json.dumps(self.output(body)))

    async def stream(self, _config, body, on_text):
        result = self.output(body)
        prefix = '{"claims":' + json.dumps(result['claims'])
        await on_text(prefix)
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        suffix = ',"uncertainty":' + json.dumps(result['uncertainty']) + '}'
        await on_text(suffix)
        return self.receipt(prefix + suffix)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    monkeypatch.setenv('TI_OBSERVABILITY_ENABLED', '0')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setattr(ai_analysis, 'configured_model', lambda: OpenAIConfig(
        model='synthetic-recall', api_key='synthetic-never-live', allow_private=True))
    app = create_app('sqlite:///' + (tmp_path / 'private-recall-consumers.sqlite').as_posix(), NoTireSource())
    adapter, model = RecallFixture(), RecallModel()
    adapter.rows = [record('A'), record('B')]
    app.state.recall_adapter, app.state.ai_adapter = adapter, model
    with TestClient(app) as client:
        yield client, adapter, model, app.state.database
        model.release.set()


def prepare(client):
    observed = live(client)
    assert observed.status_code == 200, observed.text
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'history',
        'references': [observed.json()['analysis_reference']]})
    assert response.status_code == 200, response.text
    return response.json()['pack']


def test_synchronous_recall_contract_boundary_and_report_use_exact_frozen_receipt(setup):
    client, adapter, model, database = setup
    pack = prepare(client)
    receipt = pack['evidence'][0]['verification_id']
    analysis = analyze(client, pack).json()
    assert analysis['state'] == 'completed', analysis
    assert analysis['request_contract']['prompt_version'] == 'recall-grounding@1'
    assert analysis['request_contract']['purpose'] == 'recall_research'
    assert analysis['answer']['uncertainty'] == ''
    assert analysis['answer']['recall_boundary'] == recall_boundary_descriptor()
    adapter.not_modified = True
    assert live(client).status_code == 200
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RecallVerification)) == 2
    baseline = len(adapter.calls), len(model.calls)
    response = save(client, pack, analysis['id'])
    assert response.status_code == 201, response.text
    report = response.json()
    assert report['body']['evidence'][0]['verification_id'] == receipt
    assert report['body']['recall_boundary'] == recall_boundary_descriptor()
    assert report['body']['facts'] == pack['facts']
    assert baseline == (len(adapter.calls), len(model.calls))


@pytest.mark.parametrize('failure', ['inference', 'uncertainty', 'cross_record'])
def test_unsafe_recall_answers_cannot_complete_or_be_saved_as_analysis(setup, failure):
    client, _, model, database = setup
    pack = prepare(client)
    model.failure = failure
    analysis = analyze(client, pack).json()
    assert analysis['state'] == 'failed' and analysis['answer'] is None
    assert analysis['error_code'] == 'ai_grounding_validation_failed'
    assert save(client, pack, analysis['id']).status_code == 409
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AICompletion)) == 1


def test_stream_unsafe_late_uncertainty_invalidates_all_drafts_and_report_eligibility(setup):
    client, _, model, _ = setup
    pack = prepare(client)
    model.failure = 'uncertainty'
    model.release.clear()
    response = accept(client, pack)
    assert response.status_code == 202, response.text
    request_id = response.json()['analysis']['id']
    draft = until(client, request_id, lambda value: bool(value['draft_claims']))
    assert draft['analysis']['pack']['recall_boundary'] == recall_boundary_descriptor()
    assert draft['analysis']['request_contract']['prompt_version'] == 'recall-grounding@1'
    assert draft['analysis']['answer'] is None and draft['draft_uncertainty'] is None
    assert save(client, pack, request_id).status_code == 409
    model.release.set()
    terminal = until(client, request_id, lambda value: value['execution']['terminal'])
    assert terminal['analysis']['state'] == 'failed' and terminal['analysis']['answer'] is None
    assert terminal['draft_claims'] == [] and terminal['draft_uncertainty'] is None
    assert save(client, pack, request_id).status_code == 409


def test_stream_store_independently_rejects_injected_uncertainty_and_final_answer(setup):
    client, _, _, database = setup
    pack = prepare(client)
    request_id, token = seed_accepted(database, client.cookies.get(SESSION_COOKIE), pack['id'])
    assert store.start_execution(database, request_id, token)
    with pytest.raises(ValueError, match='recall_freeform'):
        store.append_event(database, request_id, token, 'uncertainty_draft', {'text': '安全'})
    with database.sessions() as db:
        row = db.get(AIEvidencePack, pack['id'])
        fact = row.payload['facts'][0]
        good = ai_analysis.grounded_answer(json.dumps({'claims': [{'type': 'fact', 'text': '',
            'fact_ids': [fact['id']], 'evidence_ids': [fact['evidence_id']]}], 'uncertainty': ''}), row)
    bad = {**good, 'uncertainty': '该车辆适用'}
    with pytest.raises(ValueError, match='recall_freeform'):
        store.finish_execution(database, request_id, token, state='completed', answer=bad)
    assert store.append_event(database, request_id, token, 'uncertainty_draft', {'text': ''})
    assert store.finish_execution(database, request_id, token, state='completed', answer=good)
    with database.sessions() as db:
        assert db.get(AICompletion, request_id).answer == good
        assert all(event.payload.get('text', '') != '安全' for event in db.scalars(
            select(AIStreamEvent).where(AIStreamEvent.request_id == request_id)))


def test_later_revision_and_empty_observation_never_rewrite_saved_report(setup):
    client, adapter, model, _ = setup
    pack = prepare(client)
    response = save(client, pack)
    assert response.status_code == 201, response.text
    report = response.json()
    adapter.rows[0]['remedy'] = 'New synthetic formal remedy'
    assert live(client).json()['revision'] == 2
    adapter.rows = []
    assert live(client).json()['records'] == []
    baseline = len(adapter.calls), len(model.calls)
    current = client.get(f'/v1/reports/{report["id"]}?mode=history').json()
    assert current['body'] == report['body'] and current['body_hash'] == report['body_hash']
    for format in ('markdown', 'html', 'pdf'):
        export(client, current, format)
    assert baseline == (len(adapter.calls), len(model.calls))


def test_empty_recall_observation_can_be_saved_without_restoring_old_revision(setup):
    client, adapter, _, _ = setup
    prepare(client)
    adapter.rows = []
    pack = prepare(client)
    assert len(pack['facts']) == 4 and pack['evidence'][0]['recall_revision_id'] is None
    analysis = analyze(client, pack).json()
    assert analysis['state'] == 'completed'
    report = save(client, pack, analysis['id'])
    assert report.status_code == 201, report.text
    assert report.json()['body']['evidence'][0]['observation_kind'] == 'empty'
    export(client, report.json())


def test_report_rechecks_exact_receipt_time_against_database(setup):
    client, _, _, database = setup
    pack = prepare(client)
    with database.sessions() as db:
        original = db.get(AIEvidencePack, pack['id'])
        payload = deepcopy(original.payload)
        payload['evidence'][0]['verified_at'] = '2030-01-01T00:00:00+00:00'
        forged = AIEvidencePack(actor_session_id=original.actor_session_id, mode='history', data_state='local_snapshot',
            privacy_class='public', payload=payload, fingerprint=digest(payload), expires_at=utcnow() + timedelta(minutes=1))
        db.add(forged)
        db.commit()
        forged_id = forged.id
    assert save(client, {'id': forged_id}).status_code == 409


@pytest.mark.parametrize('stream', [False, True])
def test_stale_recall_contract_stops_before_model_configuration_or_request_reservation(setup, monkeypatch, stream):
    client, _, model, database = setup
    pack = prepare(client)
    with database.sessions() as db:
        original = db.get(AIEvidencePack, pack['id'])
        payload = deepcopy(original.payload)
        payload['recall_policy']['digest'] = '0' * 64
        stale = AIEvidencePack(actor_session_id=original.actor_session_id, mode='history', data_state='local_snapshot',
            privacy_class='public', payload=payload, fingerprint=digest(payload), expires_at=utcnow() + timedelta(minutes=1))
        db.add(stale)
        db.commit()
        stale_id = stale.id
    def unexpected_configuration():
        raise AssertionError('stale recall evidence must be rejected before model configuration')
    monkeypatch.setattr(ai_analysis, 'configured_model', unexpected_configuration)
    response = (accept if stream else analyze)(client, {'id': stale_id})
    assert response.status_code == 409 and response.json()['detail']['code'] == 'ai_recall_contract_stale'
    assert not model.calls
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AIRequest)) == 0
