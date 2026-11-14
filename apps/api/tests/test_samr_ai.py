"""Chinese recall evidence through the normal shared AI entrypoints."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from test_samr import NOTICE, SEARCH
from test_samr_recalls import FixtureAdapter, FixtureRegistry, context, run


def reference(result):
    return {'kind': 'samr_recall', 'snapshot_id': result['provenance'][0]['snapshot_id'],
        'article_id': result['document']['notice']['article_id']}


def prepare(client, result):
    return client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [reference(result)]})


def test_selected_notice_freezes_exact_article_fields_and_provenance(context):
    client, _, _ = context
    result = run(client)
    response = prepare(client, result)
    assert response.status_code == 200, response.text
    pack = response.json()['pack']
    assert pack['purpose'] == 'samr_recall_research' and pack['data_state'] == 'local_snapshot'
    assert pack['samr_boundary']['applicability'] == 'not_assessed'
    evidence = pack['evidence'][0]
    assert evidence['source_id'] == 'samr-cn-recalls'
    assert evidence['article_id'] == result['document']['notice']['article_id']
    assert evidence['raw_hash'] == result['provenance'][0]['raw_hash']
    assert evidence['access_basis']['redistribution_license'] == 'unverified'
    assert len(pack['facts']) == 11
    assert all(fact['domain'] == 'samr_recall' and fact['record_key'] == evidence['article_id'] for fact in pack['facts'])
    assert evidence['notice_values']['published_date'] == '2021-07-23'
    assert evidence['notice_values']['pub_date_raw'].startswith('2026-')


@pytest.mark.parametrize('query', [SEARCH, {**NOTICE, 'operation': 'search'}])
def test_current_analysis_requires_a_notice_native_reference(context, query):
    client, _, _ = context
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'current', 'query_kind': 'samr_recall_notice',
        'source_id': 'samr-cn-recalls', 'query': query})
    assert response.status_code == 422


def test_history_requires_the_exact_article_in_the_selected_snapshot(context):
    client, _, _ = context
    result = run(client)
    selected = reference(result)
    selected['article_id'] = 'b' * 32
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [selected]})
    assert response.status_code == 404, response.text


def test_current_analysis_performs_its_own_online_verification(context):
    client, adapter, _ = context
    run(client)
    calls = len(adapter.calls)
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'current', 'query_kind': 'samr_recall_notice',
        'source_id': 'samr-cn-recalls', 'query': NOTICE})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(adapter.calls) == calls + 1
    assert body['pack']['data_state'] == body['query_result']['data_state'] == 'live'
    assert body['pack']['evidence'][0]['verification_query_id'] == body['query_result']['query_id']


@pytest.fixture
def ai_case(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from tire_api import ai_analysis
    from tire_api.ai_gateway import OpenAIConfig
    from tire_api.main import create_app
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    monkeypatch.setattr(ai_analysis, 'configured_model', lambda: OpenAIConfig(
        model='synthetic-samr', api_key='synthetic-never-live', allow_private=True))

    class Model:
        calls = 0
        mutate = None
        bodies = None

        def answer(self, body):
            self.calls += 1
            self.bodies.append(deepcopy(body))
            payload = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
            fact = next(fact for fact in payload['facts'] if fact['field_code'] == 'samr_recall.text')
            result = {'claims': [{'type': 'fact', 'text': '', 'fact_ids': [fact['id']],
                'evidence_ids': [fact['evidence_id']]}], 'uncertainty': ''}
            if self.mutate:
                self.mutate(result, payload)
            return json.dumps(result)

        async def generate(self, config, body):
            return {'text': self.answer(body), 'error': None, 'usage': {'input_tokens': 20, 'output_tokens': 10, 'total_tokens': 30},
                'provider_response_id': 'synthetic-samr-response'}

        async def stream(self, config, body, on_text):
            output = self.answer(body)
            for part in (output[:20], output[20:]):
                await on_text(part)
            return {'text': output, 'error': None, 'usage': {'input_tokens': 20, 'output_tokens': 10, 'total_tokens': 30},
                'provider_response_id': 'synthetic-samr-stream'}

    app = create_app('sqlite:///' + (tmp_path / 'samr-ai.sqlite').as_posix(), FixtureRegistry())
    model, adapter = Model(), FixtureAdapter()
    model.bodies = []
    app.state.ai_adapter, app.state.samr_recall_adapter = model, adapter
    with TestClient(app) as client:
        yield client, adapter, app.state.database, model


def pack_for(client):
    response = prepare(client, run(client))
    assert response.status_code == 200, response.text
    return response.json()['pack']


def analyze(client, pack, *, key=None, **changes):
    return client.post('/v1/ai/analyses', headers={'Idempotency-Key': key or str(uuid4())}, json={
        'pack_id': pack['id'], 'question': '整理所选历史中国公告原文', 'allow_external_processing': True, **changes})


def test_normal_sync_stream_and_saved_exports_preserve_chinese_announcement_scope(ai_case):
    from test_ai_stream_api import accept, until
    client, _, _, model = ai_case
    pack = pack_for(client)
    value = analyze(client, pack)
    assert value.status_code == 200 and value.json()['state'] == 'completed', value.text
    answer = value.json()['answer']
    assert answer['samr_boundary'] == pack['samr_boundary']
    assert answer['claims'][0]['text'] == next(fact['text'] for fact in pack['facts'] if fact['field_code'] == 'samr_recall.text')
    accepted = accept(client, pack)
    assert accepted.status_code == 202, accepted.text
    stream = until(client, accepted.json()['analysis']['id'], lambda row: row['execution']['terminal'])
    assert stream['analysis']['state'] == 'completed', stream
    assert stream['analysis']['answer']['samr_boundary']['applicability'] == 'not_assessed'
    assert model.calls == 2
    report = client.post('/v1/reports', headers={'Idempotency-Key': str(uuid4())}, json={'mode': 'history', 'pack_id': pack['id'],
        'analysis_id': value.json()['id'], 'title': 'Synthetic Chinese announcement facts', 'notes': ''})
    assert report.status_code == 201, report.text
    detail = client.get('/v1/reports/' + report.json()['id'], params={'mode': 'history'}).json()
    assert detail['body']['schema_version'] == 'research-report@6'
    assert detail['body']['samr_boundary']['applicability'] == 'not_assessed'
    for format in ('markdown', 'html', 'pdf'):
        exported = client.post('/v1/reports/' + detail['id'] + '/exports',
            json={'format': format, 'revision': detail['revision']})
        assert exported.status_code == 201, exported.text
        assert exported.json()['renderer_version'] == 'frozen-research-export@7'
        assert client.get(exported.json()['content_url']).status_code == 200


def test_external_authorization_history_questions_and_idempotency(ai_case):
    client, _, _, model = ai_case
    pack = pack_for(client)
    assert analyze(client, pack, allow_external_processing=False).status_code == 422
    assert analyze(client, pack, question='当前最新公告是什么').status_code == 409
    assert model.calls == 0
    key = str(uuid4())
    first = analyze(client, pack, key=key)
    assert first.status_code == 200, first.text
    assert analyze(client, pack, key=key).json()['id'] == first.json()['id']
    assert model.calls == 1


def test_current_304_and_single_use_fallback_keep_exact_ai_verification(ai_case, monkeypatch):
    from tire_api.db import QueryRun
    from tire_api.samr_recalls import SamrRecallService
    client, adapter, database, model = ai_case
    audiences = []
    execute = SamrRecallService.execute

    async def observed(service, request, session_id, **kwargs):
        audiences.append(kwargs.get('audience'))
        return await execute(service, request, session_id, **kwargs)

    monkeypatch.setattr(SamrRecallService, 'execute', observed)
    payload = {'mode': 'current', 'query_kind': 'samr_recall_notice', 'source_id': 'samr-cn-recalls', 'query': NOTICE}
    first = client.post('/v1/ai/evidence-packs', json=payload)
    assert first.status_code == 200 and first.json()['pack']['data_state'] == 'live'
    adapter.not_modified = True
    unchanged = client.post('/v1/ai/evidence-packs', json=payload).json()
    assert unchanged['pack']['data_state'] == 'live_verified_304'
    assert unchanged['pack']['evidence'][0]['verification_query_id'] == unchanged['query_result']['query_id']
    adapter.offline = True
    failed = client.post('/v1/ai/evidence-packs', json=payload).json()
    assert failed['pack'] is None and failed['query_result']['data_state'] == 'consent_required'
    consent = client.post('/v1/fallback-consents', json={'query_id': failed['query_result']['query_id'],
        'decision': 'allow', 'scope': 'once'}).json()
    recovered = client.post('/v1/ai/evidence-packs', json={**payload, 'consent_id': consent['id']})
    assert recovered.status_code == 200 and recovered.json()['pack']['data_state'] == 'local_snapshot', recovered.text
    assert client.post('/v1/ai/evidence-packs', json={**payload, 'consent_id': consent['id']}).status_code in {403, 409}
    assert model.calls == 0
    assert audiences == ['ai_current'] * 5
    with database.sessions() as db:
        assert db.get(QueryRun, unchanged['query_result']['query_id']).source_id == 'samr-cn-recalls'


@pytest.mark.parametrize('mutation', [
    lambda answer, pack: answer['claims'][0].update(type='inference', text='Safe for all vehicles'),
    lambda answer, pack: answer['claims'][0].update(text='Unbound interpretation'),
    lambda answer, pack: answer['claims'][0].update(text=' '),
    lambda answer, pack: answer.update(uncertainty='Unbound uncertainty'),
    lambda answer, pack: answer.update(uncertainty=' '),
    lambda answer, pack: answer['claims'][0].update(fact_ids=['unknown']),
])
def test_unbound_model_prose_is_rejected_in_sync_and_stream(ai_case, mutation):
    from test_ai_stream_api import accept, until
    client, _, _, model = ai_case
    pack = pack_for(client)
    model.mutate = mutation
    value = analyze(client, pack)
    assert value.status_code == 200 and value.json()['state'] == 'failed', value.text
    assert value.json()['error_code'] == 'ai_grounding_validation_failed'
    assert value.json()['answer'] is None
    accepted = accept(client, pack)
    assert accepted.status_code == 202, accepted.text
    stream = until(client, accepted.json()['analysis']['id'], lambda row: row['execution']['terminal'])
    assert stream['analysis']['state'] == 'failed' and stream['analysis']['answer'] is None
    events = client.get('/v1/ai/analysis-streams/' + stream['analysis']['id'] + '/events').json()['items']
    assert all(event['payload'].get('text') in {None, ''} for event in events if event['type'] == 'uncertainty_draft')


def test_empty_fact_selection_is_accepted_with_explicit_boundary(ai_case):
    client, _, _, model = ai_case
    pack = pack_for(client)
    model.mutate = lambda answer, payload: answer.update(claims=[])
    value = analyze(client, pack).json()
    assert value['state'] == 'completed' and value['answer']['claims'] == []
    assert value['answer']['samr_boundary']['applicability'] == 'not_assessed'


@pytest.mark.parametrize('domains', [
    ('safety_gate',), ('recall',), ('test',), ('safety_gate', 'recall'),
    ('safety_gate', 'test'), ('recall', 'test'), ('safety_gate', 'recall', 'test'),
])
def test_mixed_regulatory_and_test_packs_keep_sync_stream_and_export_contracts(ai_case, domains):
    from test_ai_stream_api import accept, until
    from test_recalls import RecallFixture, live as recall_live
    from test_safety_gate import FixtureAdapter as SafetyGateFixture, run as safety_gate_run
    from test_test_events import create as create_event
    from test_reports import save, export
    client, _, _, model = ai_case
    references = [reference(run(client))]
    if 'safety_gate' in domains:
        client.app.state.safety_gate_adapter = SafetyGateFixture()
        result = safety_gate_run(client)
        references.append({'kind': 'safety_gate', 'snapshot_id': result['provenance'][0]['snapshot_id'], 'alert_id': '900001'})
    if 'recall' in domains:
        client.app.state.recall_adapter = RecallFixture()
        result = recall_live(client)
        assert result.status_code == 200, result.text
        references.append(result.json()['analysis_reference'])
    if 'test' in domains:
        event = create_event(client)
        references.append({'kind': 'test_event', 'event_id': event['id'], 'event_revision': event['revision']})
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': references})
    assert response.status_code == 200, response.text
    pack = response.json()['pack']

    def select_each(answer, payload):
        answer['claims'] = []
        for item in payload['evidence']:
            fact = next(fact for fact in payload['facts'] if fact['evidence_id'] == item['id'])
            answer['claims'].append({'type': 'fact', 'text': '', 'fact_ids': [fact['id']], 'evidence_ids': [item['id']]})

    model.mutate = select_each
    completed = analyze(client, pack).json()
    assert completed['state'] == 'completed', completed
    accepted = accept(client, pack)
    assert accepted.status_code == 202, accepted.text
    stream = until(client, accepted.json()['analysis']['id'], lambda row: row['execution']['terminal'])
    assert stream['analysis']['state'] == 'completed', stream
    report = save(client, pack, completed['id']).json()
    assert report['body']['schema_version'] == 'research-report@6'
    required = ['samr_boundary'] + [name + '_boundary' for name in domains]
    assert all(name in report['body'] and name in completed['answer'] for name in required)
    for format in ('markdown', 'html', 'pdf'):
        metadata, content = export(client, report, format)
        assert metadata['renderer_version'] == 'frozen-research-export@7' and content
    admitted = stream['analysis']['request_contract']
    assert admitted['samr_prompt_version'] == 'samr-recall-grounding@1'
    if 'safety_gate' in domains:
        assert admitted['prompt_version'] == 'safety-gate-grounding@1'


def test_programmatic_continuous_fallback_does_not_authorize_ai_current(ai_case):
    from test_query_fallback_policies49 import allow, scope
    client, adapter, _, model = ai_case
    run(client)
    allow(client, selected=scope('samr-cn-recalls', 'samr_recall_notice'))
    adapter.offline = True
    assert run(client)['data_state'] == 'local_snapshot'
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'current', 'query_kind': 'samr_recall_notice',
        'source_id': 'samr-cn-recalls', 'query': NOTICE})
    assert response.status_code == 200, response.text
    assert response.json()['pack'] is None and response.json()['query_result']['data_state'] == 'consent_required'
    assert model.calls == 0
