"""Original-bound text through normal AI, stream and report entry points."""
import json
import asyncio
import time
from datetime import timedelta
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select, func, text

from fastapi.testclient import TestClient
from test_ai import ModelFixture, analyze
from test_core import FixtureRegistry
from test_text_embeddings import selection
from tire_api.ai_models import AIRequest
from tire_api.db import utcnow
from tire_api.main import create_app

AI_PURPOSE = 'original_text_ai@1'
EXPORT_PURPOSE = 'original_text_report_export@1'


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = {'TI_AI_ENABLED': '1', 'TI_AI_PROVIDER': 'openai_responses',
        'TI_OPENAI_MODEL': 'synthetic-model', 'TI_OPENAI_API_KEY': 'synthetic-never-live',
        'TI_AI_ALLOW_PRIVATE': '1', 'TI_AI_DAILY_TOKEN_LIMIT': '100000', 'TI_AI_DAILY_REQUEST_LIMIT': '20'}
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    registry = FixtureRegistry()
    app = create_app('sqlite:///' + (tmp_path / 'original-ai.sqlite').as_posix(), registry)
    model = ModelFixture()
    app.state.ai_adapter = model
    with TestClient(app) as client:
        from admin_support import register_admin
        register_admin(client)
        yield client, registry, model, app.state.database


def authorize(client, selected, *, purpose=AI_PURPOSE, **changes):
    payload = {'selection': selected, 'purpose': purpose, 'action': 'grant', 'expected_revision': 0,
        'rights_basis': 'Synthetic original authored for this contract test',
        'privacy_class': 'public', 'expires_at': None, 'acknowledged': True, **changes}
    return client.post('/v1/ai/text-authorizations', json=payload)


def prepared(client, selected):
    granted = authorize(client, selected)
    assert granted.status_code == 200, granted.text
    response = prepare(client, selected)
    assert response.status_code == 200, response.text
    return response.json()['pack']


def prepare(client, selected):
    return client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [selected]})


def prepared_test_pdf(setup, *, granted=False):
    from test_test_events import create, pdf_measurement_payload
    client, _registry, model, _database = setup
    model.mutation = lambda answer: answer.update(uncertainty='')
    payload, document = pdf_measurement_payload(client)
    event = create(client, payload)
    selected = {'kind': 'document_text', 'reference': event['event']['measurements'][0]['pdf_reference']}
    if granted:
        response = authorize(client, selected)
        assert response.status_code == 200, response.text
    response = prepare(client, {'kind': 'test_event', 'event_id': event['id'], 'event_revision': 1})
    assert response.status_code == 200, response.text
    pack = response.json()['pack']
    assert pack['test_pdf_policy'] == 'test-pdf-original@1'
    return pack, selected, event, document


def test_selected_nonfirst_measurement_keeps_pdf_binding_analysis_and_report_exports(setup):
    from test_test_events import create, pdf_measurement_payload
    client, _registry, model, _database = setup
    payload, _document = pdf_measurement_payload(client)
    values = payload['event']['measurements']
    values[0], values[1] = values[1], values[0]
    event = create(client, payload)
    reference = {'kind': 'test_event', 'event_id': event['id'], 'event_revision': 1, 'measurement_numbers': [2]}
    response = prepare(client, reference)
    assert response.status_code == 200, response.text
    pack = response.json()['pack']
    facts = [fact for fact in pack['facts'] if fact['field'].startswith('本场成绩 ')]
    assert len(facts) == 1 and facts[0]['field'] == '本场成绩 2'
    assert facts[0]['field_code'] == 'manual_test_independent.field_9'
    assert facts[0]['value']['pdf_reference'] == event['event']['measurements'][1]['pdf_reference']
    assert analyze(client, pack).status_code == 403 and not model.calls
    selected = {'kind': 'document_text', 'reference': facts[0]['value']['pdf_reference']}
    assert authorize(client, selected).status_code == 200
    model.mutation = lambda answer: answer.update(claims=[{'type': 'fact', 'text': '',
        'fact_ids': [facts[0]['id']], 'evidence_ids': [facts[0]['evidence_id']]}], uncertainty='')
    result = analyze(client, pack)
    assert result.status_code == 200, result.text
    assert result.json()['state'] == 'completed' and len(model.calls) == 1
    saved = client.post('/v1/reports', headers={'Idempotency-Key': str(uuid4())}, json={
        'mode': 'history', 'pack_id': pack['id'], 'analysis_id': result.json()['id'],
        'title': 'Synthetic explicitly selected measurement', 'notes': ''})
    assert saved.status_code == 201, saved.text
    report = saved.json()
    assert report['body']['facts'] == pack['facts']
    assert authorize(client, selected, purpose=EXPORT_PURPOSE).status_code == 200
    for format in ('markdown', 'html', 'pdf'):
        exported = client.post('/v1/reports/' + report['id'] + '/exports', json={'revision': 1, 'format': format})
        assert exported.status_code == 201, exported.text
        assert client.get(exported.json()['content_url']).status_code == 200
    reopened = client.get('/v1/reports/' + report['id'], params={'mode': 'history'})
    assert reopened.status_code == 200 and reopened.json()['body'] == report['body']
    changed = client.post('/v1/test-events/' + event['id'] + '/state', json={
        'action': 'revoke', 'expected_revision': 1, 'operator': 'Synthetic reviewer', 'reason': 'Synthetic revocation'})
    assert changed.status_code == 200, changed.text
    assert analyze(client, pack).status_code == 409 and len(model.calls) == 1


def test_test_pdf_original_needs_its_purpose_grant_before_any_model_reservation(setup):
    client, _registry, model, database = setup
    pack, _selected, _event, _document = prepared_test_pdf(setup)
    response = analyze(client, pack)
    assert response.status_code == 403, response.text
    assert response.json()['detail']['code'] == 'ai_original_text_use_not_allowed'
    assert not model.calls
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AIRequest)) == 0


def test_test_pdf_original_grant_binds_analysis_and_three_export_formats(setup):
    client, _registry, model, _database = setup
    pack, selected, event, _document = prepared_test_pdf(setup, granted=True)
    response = analyze(client, pack)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run['state'] == 'completed' and run['answer']['test_pdf_policy'] == 'test-pdf-original@1'
    assert run['request_contract']['test_pdf_policy'] == 'test-pdf-original@1'
    assert len(model.calls) == 1
    report = client.post('/v1/reports', json={'mode': 'history', 'pack_id': pack['id'],
        'analysis_id': run['id'], 'title': 'Synthetic PDF-bound measurement', 'notes': ''},
        headers={'Idempotency-Key': str(uuid4())})
    assert report.status_code == 201, report.text
    report = report.json()
    assert report['body']['test_pdf_policy'] == 'test-pdf-original@1'
    rejected = client.post('/v1/reports/' + report['id'] + '/exports', json={'revision': 1, 'format': 'markdown'})
    assert rejected.status_code == 403, rejected.text
    grant = authorize(client, selected, purpose=EXPORT_PURPOSE)
    assert grant.status_code == 200, grant.text
    import hashlib
    for format in ('markdown', 'html', 'pdf'):
        exported = client.post('/v1/reports/' + report['id'] + '/exports', json={'revision': 1, 'format': format})
        assert exported.status_code == 201, exported.text
        raw = client.get(exported.json()['content_url'])
        assert raw.status_code == 200 and hashlib.sha256(raw.content).hexdigest() == exported.json()['sha256']
    revoked = authorize(client, selected, purpose=EXPORT_PURPOSE, action='revoke', expected_revision=1)
    assert revoked.status_code == 200
    assert client.get(exported.json()['content_url']).status_code == 403
    assert client.get('/v1/reports/' + report['id'], params={'mode': 'history'}).json()['body'] == report['body']
    fact = next(item for item in report['body']['facts'] if isinstance(item['value'], dict)
        and item['value'].get('pdf_reference'))
    assert fact['value']['pdf_reference'] == event['event']['measurements'][0]['pdf_reference']


def test_test_pdf_original_revocation_between_reservation_and_dispatch_blocks_provider(setup, monkeypatch):
    from tire_api import ai_execution
    client, _registry, model, _database = setup
    pack, selected, _event, _document = prepared_test_pdf(setup, granted=True)
    original = ai_execution.require_evidence_dispatch
    def changed(*args, **kwargs):
        revoked = authorize(client, selected, action='revoke', expected_revision=1)
        assert revoked.status_code == 200, revoked.text
        return original(*args, **kwargs)
    monkeypatch.setattr(ai_execution, 'require_evidence_dispatch', changed)
    response = analyze(client, pack)
    assert response.status_code == 200, response.text
    assert response.json()['state'] == 'failed' and response.json()['error_code'] == 'ai_original_text_use_not_allowed'
    assert not model.calls


@pytest.mark.parametrize('revoke', [False, True])
def test_test_pdf_stream_freezes_original_and_rechecks_permission_at_terminal(setup, revoke):
    from test_ai_stream_api import accept, read
    client, _registry, model, _database = setup
    pack, selected, _event, _document = prepared_test_pdf(setup, granted=True)
    async def stream(config, body, on_text):
        receipt = await model.generate(config, body)
        await on_text(receipt['text'])
        if revoke:
            revoked = await asyncio.to_thread(authorize, client, selected, action='revoke', expected_revision=1)
            assert revoked.status_code == 200
        return receipt
    model.stream = stream
    key = str(uuid4())
    accepted = accept(client, pack, key)
    assert accepted.status_code == 202, accepted.text
    identity = accepted.json()['analysis']['id']
    # PDF restoration runs again before dispatch and terminal adoption. Keep the
    # production owner deadline unchanged while allowing this fixture to finish.
    deadline = time.monotonic() + 90
    while True:
        detail = read(client, identity)
        if detail['execution']['terminal']:
            break
        assert time.monotonic() < deadline, detail['execution']
        time.sleep(0.05)
    run = detail['analysis']
    assert len(model.calls) == 1 and run['usage']['total_tokens'] == 600
    if revoke:
        assert run['state'] == 'failed' and run['answer'] is None
        assert run['error_code'] == 'ai_original_text_use_not_allowed'
    else:
        assert run['state'] == 'completed' and run['answer']['test_pdf_policy'] == 'test-pdf-original@1'
    assert accept(client, pack, key).json()['analysis']['id'] == identity and len(model.calls) == 1


@pytest.mark.parametrize('change', ['revoke', 'revision', 'original', 'marker'])
def test_test_pdf_changes_after_dispatch_reject_answer_and_retain_actual_usage(setup, change):
    from tire_api.ai_models import AIEvidencePack
    from tire_api.domain import digest
    client, _registry, model, database = setup
    pack, selected, event, document = prepared_test_pdf(setup, granted=True)
    generate = model.generate
    async def changed(config, body):
        receipt = await generate(config, body)
        if change == 'revoke':
            assert authorize(client, selected, action='revoke', expected_revision=1).status_code == 200
        elif change == 'revision':
            payload = {**event['event'], 'conditions': 'Synthetic changed conditions after dispatch'}
            revised = client.put('/v1/test-events/' + event['id'], json={'event': payload, 'expected_revision': 1,
                'operator': 'Synthetic reviewer', 'reason': 'Exercise post-dispatch revision'})
            assert revised.status_code == 200, revised.text
        elif change == 'original':
            with database.sessions() as db:
                path = db.info['object_store'].path(document['raw_hash'])
            path.write_bytes(b'synthetic corrupted original')
        else:
            with database.sessions() as db:
                row = db.get(AIEvidencePack, pack['id'])
                damaged = deepcopy(row.payload)
                del damaged['test_pdf_policy']
                db.execute(text('UPDATE ai_evidence_packs SET payload=:payload, fingerprint=:fingerprint WHERE id=:id'),
                    {'payload': json.dumps(damaged), 'fingerprint': digest(damaged), 'id': row.id})
                db.commit()
        return receipt
    model.generate = changed
    run = analyze(client, pack).json()
    assert run['state'] == 'failed' and run['answer'] is None
    assert run['usage']['total_tokens'] == 600 and len(model.calls) == 1


@pytest.mark.parametrize('damage', ['marker', 'reference', 'quote', 'participant', 'field'])
def test_test_pdf_frozen_contract_rejects_rehashed_structural_damage(setup, damage):
    from types import SimpleNamespace
    from tire_api.ai_analysis import grounded_answer
    client, _registry, _model, _database = setup
    pack, _selected, _event, _document = prepared_test_pdf(setup)
    payload = deepcopy(pack)
    fact = next(item for item in payload['facts'] if isinstance(item['value'], dict)
        and item['value'].get('pdf_reference'))
    if damage == 'marker':
        del payload['test_pdf_policy']
    elif damage == 'reference':
        fact['value']['pdf_reference']['raw_hash'] = True
    elif damage == 'quote':
        fact['value']['evidence_span'] = None
    elif damage == 'participant':
        fact['value']['unexpected_participant'] = 'unbound'
    else:
        fact['field_code'] = 'unbound.field'
    output = {'claims': [], 'uncertainty': ''}
    with pytest.raises((ValueError, TypeError)):
        grounded_answer(json.dumps(output), SimpleNamespace(payload=payload, data_state='local_snapshot'))


def test_selected_source_text_prepares_locally_without_model_call(setup):
    client, _registry, model, database = setup
    selected = selection(client, database)
    response = prepare(client, selected)
    assert response.status_code == 200, response.text
    pack = response.json()['pack']
    assert pack['evidence'][0]['original_text']['selection'] == selected
    assert pack['facts'][0]['value'] == '原件正文 acoustic comfort 🛞'
    assert pack['original_text_policy'] == 'original-text-grounding@1'
    assert not model.calls
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AIRequest)) == 0


def test_missing_generation_purpose_refuses_before_reserving_or_dispatching(setup):
    client, _registry, model, database = setup
    selected = selection(client, database)
    response = prepare(client, selected)
    assert response.status_code == 200, response.text
    value = analyze(client, response.json()['pack'])
    assert value.status_code == 403 and value.json()['detail']['code'] == 'ai_original_text_use_not_allowed'
    assert not model.calls


def test_preview_grant_analysis_and_history_use_exact_original(setup):
    client, _registry, model, database = setup
    selected = selection(client, database)
    preview = client.post('/v1/ai/text-authorizations/preview', json={'selection': selected})
    assert preview.status_code == 200 and preview.json()['authorization']['state'] == 'missing'
    assert preview.json()['recipient']['provider'] == 'openai_responses' and not model.calls
    pack = prepared(client, selected)
    key = str(uuid4())
    response = analyze(client, pack, key)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run['state'] == 'completed' and run['usage']['total_tokens'] == 600
    assert run['answer']['claims'][0]['text'] == pack['facts'][0]['text']
    assert '🛞' in run['answer']['claims'][0]['text']
    body = model.calls[0][1]
    dispatched = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
    assert dispatched['evidence'][0]['original_text']['selection'] == selected
    assert body['tools'] == [] and body['store'] is False and '原文摘录' in body['input'][0]['content']
    assert analyze(client, pack, key).json()['id'] == run['id'] and len(model.calls) == 1
    assert client.get('/v1/ai/analyses/' + run['id'] + '?mode=history').json()['answer'] == run['answer']


def test_pdf_freezes_page_and_retention_time_without_publication_guess(setup):
    from test_document_text import indexed_document, search
    client, _registry, model, _database = setup
    document, _ = indexed_document(client, pages=('originalpdf 原文🛞', 'originalpdf second page'))
    result = search(client, 'originalpdf', document_id=document['id']).json()['items']
    selected = {'kind': 'document_text', 'reference': result[1]['reference']}
    pack = prepared(client, selected)
    evidence = pack['evidence'][0]
    assert evidence['original_text']['selection'] == selected and evidence['content_scope'] == 'document_page'
    assert evidence['observed_at'] is None and evidence['retained_at'] == document['created_at']
    run = analyze(client, pack).json()
    assert run['state'] == 'completed' and len(model.calls) == 1
    assert pack['facts'][0]['value'] == result[1]['text']


@pytest.mark.parametrize('change', ['revoke', 'expire', 'private', 'receiver', 'original'])
def test_current_use_changes_refuse_before_reservation(setup, monkeypatch, change):
    client, _registry, model, database = setup
    selected = selection(client, database)
    pack = prepared(client, selected)
    if change == 'revoke':
        assert authorize(client, selected, action='revoke', expected_revision=1).status_code == 200
    elif change == 'expire':
        expiration = utcnow() + timedelta(minutes=1)
        assert authorize(client, selected, expected_revision=1, expires_at=expiration.isoformat()).status_code == 200
        from tire_api import text_embeddings
        monkeypatch.setattr(text_embeddings, 'utcnow', lambda: expiration + timedelta(seconds=1))
    elif change == 'private':
        assert authorize(client, selected, expected_revision=1, privacy_class='private').status_code == 200
        monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '0')
    elif change == 'receiver':
        from dataclasses import replace
        from tire_api import ai_analysis
        config = ai_analysis.configured_model()
        monkeypatch.setattr(ai_analysis, 'configured_model', lambda: replace(config, endpoint='https://fixture.invalid/changed'))
    else:
        with database.sessions() as db:
            db.execute(text('UPDATE snapshots SET body = :body WHERE id = :id'),
                {'body': 'damaged original', 'id': selected['reference']['snapshot_id']})
            db.commit()
    response = analyze(client, pack)
    assert response.status_code in {403, 409}, response.text
    assert not model.calls
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AIRequest)) == 0


def test_final_dispatch_revocation_records_zero_actual_usage(setup, monkeypatch):
    from tire_api import ai_execution
    client, _registry, model, database = setup
    selected = selection(client, database)
    pack = prepared(client, selected)
    original = ai_execution.require_evidence_dispatch
    def changed(*args, **kwargs):
        assert authorize(client, selected, action='revoke', expected_revision=1).status_code == 200
        return original(*args, **kwargs)
    monkeypatch.setattr(ai_execution, 'require_evidence_dispatch', changed)
    run = analyze(client, pack).json()
    assert run['state'] == 'failed' and run['error_code'] == 'ai_original_text_use_not_allowed'
    assert run['usage']['total_tokens'] == 0 and not model.calls


def test_revocation_during_call_keeps_actual_usage_and_rejects_answer(setup):
    client, _registry, model, database = setup
    selected = selection(client, database)
    pack = prepared(client, selected)
    original = model.generate
    async def changed(config, body):
        receipt = await original(config, body)
        assert authorize(client, selected, action='revoke', expected_revision=1).status_code == 200
        return receipt
    model.generate = changed
    run = analyze(client, pack).json()
    assert run['state'] == 'failed' and run['answer'] is None
    assert run['error_code'] == 'ai_original_text_use_not_allowed' and run['usage']['total_tokens'] == 600
    assert len(model.calls) == 1


@pytest.mark.parametrize('revoke', [False, True])
def test_stream_uses_same_original_contract_and_call_accounting(setup, revoke):
    from test_ai_stream_api import accept, until
    client, _registry, model, database = setup
    selected = selection(client, database)
    pack = prepared(client, selected)
    async def stream(config, body, on_text):
        receipt = await model.generate(config, body)
        await on_text(receipt['text'])
        if revoke:
            revoked = await asyncio.to_thread(authorize, client, selected, action='revoke', expected_revision=1)
            assert revoked.status_code == 200
        return receipt
    model.stream = stream
    key = str(uuid4())
    accepted = accept(client, pack, key)
    assert accepted.status_code == 202, accepted.text
    identity = accepted.json()['analysis']['id']
    detail = until(client, identity, lambda value: value['execution']['terminal'])
    run = detail['analysis']
    assert run['usage']['total_tokens'] == 600 and len(model.calls) == 1
    if revoke:
        assert run['state'] == 'failed' and run['answer'] is None
        assert run['error_code'] == 'ai_original_text_use_not_allowed'
    else:
        assert run['state'] == 'completed' and run['answer']['claims'][0]['text'] == pack['facts'][0]['text']
    assert accept(client, pack, key).json()['analysis']['id'] == identity and len(model.calls) == 1


def test_export_purpose_and_download_revocation_preserve_saved_report(setup):
    client, _registry, model, database = setup
    selected = selection(client, database)
    pack = prepared(client, selected)
    run = analyze(client, pack).json()
    saved = client.post('/v1/reports', json={'mode': 'history', 'pack_id': pack['id'],
        'analysis_id': run['id'], 'title': 'Original excerpt report', 'notes': ''}, headers={'Idempotency-Key': str(uuid4())})
    assert saved.status_code == 201, saved.text
    report = saved.json()
    identity = report['id']
    request = {'revision': 1, 'format': 'html'}
    assert client.post(f'/v1/reports/{identity}/exports', json=request).status_code == 403
    assert authorize(client, selected, purpose=EXPORT_PURPOSE).status_code == 200
    exported = client.post(f'/v1/reports/{identity}/exports', json=request)
    assert exported.status_code == 201, exported.text
    url = f"/v1/reports/{identity}/exports/{exported.json()['id']}/content?mode=history&revision=1"
    content = client.get(url)
    assert content.status_code == 200 and '原件正文 acoustic comfort 🛞' in content.text
    assert authorize(client, selected, purpose=EXPORT_PURPOSE, action='revoke', expected_revision=1).status_code == 200
    assert client.get(url).status_code == 403
    frozen = client.get(f'/v1/reports/{identity}?mode=history')
    assert frozen.status_code == 200 and frozen.json()['body'] == report['body']
    assert len(model.calls) == 1


def test_permission_scope_cannot_cross_generation_export_or_embedding(setup):
    client, _registry, _model, database = setup
    selected = selection(client, database)
    exported = authorize(client, selected, purpose=EXPORT_PURPOSE)
    assert exported.status_code == 200
    scope = exported.json()['scope_hash']
    assert authorize(client, selected, action='revoke', expected_revision=1, scope_hash=scope).status_code == 409
    from test_text_embeddings import authorize as embedding_authorize
    assert embedding_authorize(client, selected, action='revoke', expected_revision=1, scope_hash=scope).status_code == 409
    preview = client.post('/v1/ai/text-authorizations/preview', json={'selection': selected})
    assert preview.json()['authorization']['state'] == 'missing'
    assert authorize(client, selected, purpose=EXPORT_PURPOSE, action='revoke', expected_revision=1, scope_hash=scope).status_code == 200


def test_saved_scope_revocation_works_after_model_disabled_and_original_corrupt(setup, monkeypatch):
    client, _registry, _model, database = setup
    selected = selection(client, database)
    granted = authorize(client, selected).json()
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    with database.sessions() as db:
        db.execute(text('UPDATE snapshots SET body = :body WHERE id = :id'),
            {'body': 'damaged', 'id': selected['reference']['snapshot_id']})
        db.commit()
    response = authorize(client, selected, scope_hash=granted['scope_hash'], action='revoke', expected_revision=1)
    assert response.status_code == 200 and response.json()['authorization']['state'] == 'revoked'


def test_invalid_or_duplicate_reference_refuses_during_preparation(setup):
    client, _registry, model, database = setup
    selected = selection(client, database)
    duplicate = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [selected, selected]})
    assert duplicate.status_code == 422
    changed = deepcopy(selected)
    changed['reference']['raw_hash'] = 'f' * 64
    assert prepare(client, changed).status_code == 409 and not model.calls


def test_original_and_structured_references_share_the_six_evidence_limit(setup):
    from test_ai import historical_pack
    client, _registry, model, database = setup
    selected = selection(client, database)
    assert authorize(client, selected).status_code == 200
    tire = historical_pack(client)['evidence'][0]
    reference = {'kind': 'tire', 'snapshot_id': tire['snapshot_id'], 'variant_id': tire['variant_id']}
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [selected, reference]})
    assert response.status_code == 200, response.text
    pack = response.json()['pack']
    assert len(pack['evidence']) == 2 and pack['field_resolutions']
    assert analyze(client, pack).json()['state'] == 'completed' and len(model.calls) == 1
    assert client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [selected] * 7}).status_code == 422


def test_changed_outbound_body_cannot_pass_final_dispatch_binding(setup, monkeypatch):
    from tire_api import ai_execution
    client, _registry, model, database = setup
    pack = prepared(client, selection(client, database))
    check = ai_execution.require_evidence_dispatch
    def changed(database, request_id, config, body, frozen=None):
        body['input'][1]['content'] = body['input'][1]['content'].replace('acoustic', 'invented')
        return check(database, request_id, config, body, frozen)
    monkeypatch.setattr(ai_execution, 'require_evidence_dispatch', changed)
    value = analyze(client, pack).json()
    assert value['state'] == 'failed' and value['error_code'] == 'ai_original_text_binding_failed'
    assert value['usage']['total_tokens'] == 0 and not model.calls


def verify_original_text_ai(url, *, authenticate):
    with pytest.MonkeyPatch.context() as monkeypatch:
        for key, value in {'TI_AI_ENABLED': '1', 'TI_AI_PROVIDER': 'openai_responses',
            'TI_OPENAI_MODEL': 'synthetic-original-ai', 'TI_OPENAI_API_KEY': 'synthetic-never-live',
            'TI_AI_ALLOW_PRIVATE': '1', 'TI_AI_DAILY_TOKEN_LIMIT': '1000000', 'TI_AI_DAILY_REQUEST_LIMIT': '100'}.items():
            monkeypatch.setenv(key, value)
        app = create_app(url, FixtureRegistry())
        model = ModelFixture()
        app.state.ai_adapter = model
        with TestClient(app) as client:
            authenticate(client)
            selected = selection(client, app.state.database)
            pack = prepared(client, selected)
            run = analyze(client, pack).json()
            assert run['state'] == 'completed' and run['usage']['total_tokens'] == 600
            saved = client.post('/v1/reports', headers={'Idempotency-Key': str(uuid4())}, json={
                'mode': 'history', 'pack_id': pack['id'], 'analysis_id': run['id'], 'title': 'PG original text', 'notes': ''})
            assert saved.status_code == 201, saved.text
            report = saved.json()
            assert authorize(client, selected, purpose=EXPORT_PURPOSE).status_code == 200
            exported = client.post(f"/v1/reports/{report['id']}/exports", json={'revision': 1, 'format': 'html'})
            assert exported.status_code == 201, exported.text
            download = exported.json()['content_url']
            assert client.get(download).status_code == 200 and len(model.calls) == 1
            checkpoint = {'pack_id': pack['id'], 'analysis_id': run['id'], 'report_id': report['id'],
                'body': report['body'], 'download': download, 'reference': selected}
        app.state.database.close()
    return {'checks': ['original_text_purpose_and_frozen_pack', 'grounded_responses_receipt',
        'report_export_bound_to_independent_current_purpose'], 'checkpoint': checkpoint}


def assert_original_text_ai_checkpoint(url, checkpoint, *, authenticate):
    from tire_api.ai_original_text import EXPORT_PURPOSE, require_originals
    from tire_api.report_models import ResearchReport
    app = create_app(url, FixtureRegistry())
    model = ModelFixture()
    app.state.ai_adapter = model
    with TestClient(app) as client:
        authenticate(client)
        report = client.get(f"/v1/reports/{checkpoint['report_id']}?mode=history")
        assert report.status_code == 200 and report.json()['body'] == checkpoint['body']
        run = client.get(f"/v1/ai/analyses/{checkpoint['analysis_id']}?mode=history")
        assert run.status_code == 200 and run.json()['state'] == 'completed'
        assert client.get(checkpoint['download']).status_code == 200
        with app.state.database.sessions() as db:
            stored = db.get(ResearchReport, checkpoint['report_id'])
            require_originals(db, stored.body, purpose=EXPORT_PURPOSE)
        assert not model.calls
    app.state.database.close()
