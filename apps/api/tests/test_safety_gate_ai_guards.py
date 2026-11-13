"""Synthetic mutations at real reservation/dispatch and completion boundaries."""
from copy import deepcopy
from dataclasses import replace
import json
import time
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from test_safety_gate_ai import ai_case, analyze, pack_for, prepare
from test_safety_gate import QUERY, run
from test_ai_stream_api import accept, until
from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.domain import digest


def execute(client, pack, streamed):
    if not streamed:
        response = analyze(client, pack)
        assert response.status_code == 200
        return response.json(), None
    response = accept(client, pack)
    assert response.status_code == 202
    detail = until(client, response.json()['analysis']['id'], lambda row: row['execution']['terminal'])
    return detail['analysis'], detail


@pytest.mark.parametrize('streamed', [False, True])
@pytest.mark.parametrize('mutation', [
    'body', 'question', 'model', 'provider', 'pack_payload', 'owner',
    'contract_policy', 'contract_version', 'contract_removed', 'all_payload_markers_removed',
])
def test_final_dispatch_rejects_binding_changes_before_any_model_call(ai_case, monkeypatch, tmp_path, streamed, mutation):
    from tire_api import ai_safety_gate_contract as contract
    client, _, database, model = ai_case
    pack = pack_for(client)
    actual, entered = contract.require_dispatch, []

    def checked(database, request_id, config, body, running_pack=None):
        if not entered:
            entered.append(True)
            if mutation == 'model':
                config = replace(config, model='different-synthetic-recipient')
            elif mutation == 'provider':
                config = replace(config, provider='openai_chat')
            elif mutation in {'body', 'question'}:
                envelope = json.loads(body['input'][1]['content'])
                if mutation == 'body':
                    envelope['untrusted_evidence_pack']['facts'][0]['text'] = 'unapproved replacement'
                else:
                    envelope['question'] = 'unapproved question'
                body['input'][1]['content'] = json.dumps(envelope)
            else:
                with database.sessions() as db:
                    request = db.get(AIRequest, request_id)
                    frozen = db.get(AIEvidencePack, request.pack_id)
                    if mutation == 'owner':
                        db.execute(update(AIEvidencePack).where(AIEvidencePack.id == frozen.id).values(actor_session_id='different-synthetic-session'))
                    elif mutation == 'pack_payload':
                        value = deepcopy(frozen.payload)
                        value['facts'][0]['text'] = 'unapproved stored replacement'
                        db.execute(update(AIEvidencePack).where(AIEvidencePack.id == frozen.id).values(payload=value))
                    elif mutation.startswith('contract_'):
                        value = deepcopy(request.request_contract)
                        if mutation == 'contract_policy':
                            value['safety_gate_policy']['digest'] = 'f' * 64
                        elif mutation == 'contract_version':
                            value['safety_gate_prompt_version'] = 'unrecognized@9'
                        else:
                            value.pop('safety_gate_policy')
                        db.execute(update(AIRequest).where(AIRequest.id == request_id).values(request_contract=value))
                    else:
                        # Retain the admitted request contract but strip all
                        # Safety Gate markers from both mutable dispatch inputs.
                        value = {'purpose': 'analysis', 'evidence': [{'id': 'e1', 'kind': 'manual', 'label': 'Synthetic replacement'}],
                            'facts': [{'id': 'f1', 'evidence_id': 'e1', 'field': 'replacement', 'value': 'unapproved', 'text': 'unapproved'}],
                            'conflicts': [], 'source_state': 'snapshot'}
                        db.execute(update(AIEvidencePack).where(AIEvidencePack.id == frozen.id).values(payload=value, fingerprint=digest(value)))
                        envelope = json.loads(body['input'][1]['content'])
                        envelope['untrusted_evidence_pack'] = {**value, 'data_state': frozen.data_state}
                        body['input'][1]['content'] = json.dumps(envelope)
                        if running_pack is not None:
                            running_pack['payload'] = deepcopy(value)
                    db.commit()
        return actual(database, request_id, config, body, running_pack)

    monkeypatch.setattr(contract, 'require_dispatch', checked)
    if streamed and mutation in {'pack_payload', 'owner'}:
        response = accept(client, pack)
        assert response.status_code == 202
        request_id = response.json()['analysis']['id']
        deadline = time.monotonic() + 5
        while True:
            with database.sessions() as db:
                completion = db.get(AICompletion, request_id)
                if completion:
                    result = {name: getattr(completion, name) for name in ('state', 'error_code', 'usage', 'answer')}
                    break
            assert time.monotonic() < deadline
            time.sleep(.01)
        denied = client.get('/v1/ai/analysis-streams/' + request_id + '?mode=history')
        assert denied.status_code == (404 if mutation == 'owner' else 409)
        detail = None
    else:
        result, detail = execute(client, pack, streamed)
    (tmp_path / 'dispatch-observation.json').write_text(json.dumps({
        'mutation': mutation, 'streamed': streamed, 'model_calls': model.calls,
        'state': result['state'], 'error_code': result['error_code'], 'usage': result['usage'],
    }), encoding='utf-8')
    assert entered and model.calls == 0
    assert result['state'] == 'failed' and result['error_code'] == 'ai_grounding_validation_failed'
    assert result['answer'] is None and result['usage']['total_tokens'] == 0
    if detail:
        assert detail['draft_claims'] == [] and detail['draft_uncertainty'] is None


@pytest.mark.parametrize('streamed', [False, True])
@pytest.mark.parametrize('mutation', ['material', 'admitted_contract'])
def test_material_changed_by_completion_is_rejected_without_zeroing_provider_usage(ai_case, streamed, mutation):
    from tire_api.safety_gate import SafetyGateSnapshot
    client, _, database, model = ai_case
    pack = pack_for(client)

    def after_call(_answer, _payload):
        with database.sessions() as db:
            if mutation == 'material':
                db.execute(update(SafetyGateSnapshot).values(body='changed while generating'))
            else:
                request = db.scalar(select(AIRequest).where(AIRequest.pack_id == pack['id']))
                value = deepcopy(request.request_contract)
                value['safety_gate_policy']['digest'] = 'f' * 64
                db.execute(update(AIRequest).where(AIRequest.id == request.id).values(request_contract=value))
            db.commit()

    model.mutate = after_call
    result, detail = execute(client, pack, streamed)
    assert model.calls == 1
    assert result['state'] == 'failed' and result['error_code'] == 'ai_grounding_validation_failed'
    assert result['answer'] is None and result['usage']['total_tokens'] == 30
    if detail:
        assert detail['draft_claims'] == [] and detail['draft_uncertainty'] is None


@pytest.mark.parametrize('domain', ['recall', 'test', 'both'])
def test_mixed_evidence_keeps_independent_scopes_and_report_boundaries(ai_case, domain):
    from test_recalls import RecallFixture, live as recall_live
    from test_test_events import create as create_event
    from test_reports import save, export
    from tire_api.ai_analysis import grounded_answer
    from types import SimpleNamespace
    client, _, _, model = ai_case
    result = run(client)
    references = [{'kind': 'safety_gate', 'snapshot_id': result['provenance'][0]['snapshot_id'], 'alert_id': '900001'}]
    if domain in {'recall', 'both'}:
        client.app.state.recall_adapter = RecallFixture()
        recalled = recall_live(client)
        assert recalled.status_code == 200 and recalled.json()['data_state'] == 'live'
        references.append(recalled.json()['analysis_reference'])
    if domain in {'test', 'both'}:
        event = create_event(client)
        references.append({'kind': 'test_event', 'event_id': event['id'], 'event_revision': event['revision']})
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': references})
    assert response.status_code == 200
    pack = response.json()['pack']

    def choose_separate(answer, payload):
        answer['claims'] = []
        for evidence in payload['evidence']:
            fact = next(f for f in payload['facts'] if f['evidence_id'] == evidence['id'])
            answer['claims'].append({'type': 'fact', 'text': '', 'fact_ids': [fact['id']], 'evidence_ids': [evidence['id']]})

    model.mutate = choose_separate
    analysis = analyze(client, pack).json()
    assert analysis['state'] == 'completed'
    assert len(analysis['answer']['claims']) == len(references)
    report = save(client, pack, analysis['id']).json()
    assert report['body']['schema_version'] == 'research-report@5'
    for format in ('markdown', 'html', 'pdf'):
        meta, data = export(client, report, format)
        assert meta['renderer_version'] == 'frozen-research-export@6' and data
    required = ['safety_gate_boundary'] + (['recall_boundary'] if domain in {'recall', 'both'} else []) + (['test_boundary'] if domain in {'test', 'both'} else [])
    assert all(name in report['body'] and name in analysis['answer'] for name in required)
    first = pack['facts'][0]
    second = next(f for f in pack['facts'] if f['evidence_id'] != first['evidence_id'])
    unsafe = {'claims': [{'type': 'fact', 'text': '', 'fact_ids': [first['id'], second['id']],
        'evidence_ids': [first['evidence_id'], second['evidence_id']]}], 'uncertainty': ''}
    with pytest.raises(ValueError):
        grounded_answer(json.dumps(unsafe), SimpleNamespace(payload=pack, data_state=pack['data_state']))


@pytest.mark.parametrize('mutation', ['verification_status', 'query_state', 'parser_identity', 'alert_absent'])
def test_history_selection_requires_exact_successful_verification(ai_case, mutation):
    from tire_api.safety_gate import SafetyGateVerification
    from tire_api.db import QueryRun
    client, _, database, model = ai_case
    result = run(client)
    if mutation == 'alert_absent':
        response = prepare(client, result, alert_id='-1782')
        assert response.status_code == 404
    else:
        with database.sessions() as db:
            if mutation == 'verification_status':
                db.execute(update(SafetyGateVerification).values(status='failed'))
            elif mutation == 'query_state':
                db.execute(update(QueryRun).values(state='source_unavailable'))
            else:
                db.execute(update(SafetyGateVerification).values(parser_identity={'unexpected': True}))
            db.commit()
        response = prepare(client, result)
        assert response.status_code == 409
    assert model.calls == 0
    with database.sessions() as db:
        assert db.scalar(select(AIEvidencePack.id)) is None


def test_more_than_six_selections_rejected_before_capture(ai_case):
    client, adapter, _, model = ai_case
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'current', 'query_kind': 'safety_gate_report',
        'source_id': 'eu-safety-gate', 'query': QUERY, 'alert_ids': [str(i) for i in range(1, 8)]})
    assert response.status_code == 422 and adapter.calls == [] and model.calls == 0


@pytest.mark.parametrize('mode', ['history', 'current'])
def test_large_official_field_rejected_without_truncating_or_persisting_pack(ai_case, monkeypatch, mode):
    import test_safety_gate
    client, _, database, model = ai_case
    original = test_safety_gate.report
    monkeypatch.setattr(test_safety_gate, 'report', lambda: original().replace('<danger>', '<danger>' + 'X' * 25000))
    if mode == 'history':
        result = run(client)
        response = prepare(client, result)
    else:
        response = client.post('/v1/ai/evidence-packs', json={'mode': 'current', 'query_kind': 'safety_gate_report',
            'source_id': 'eu-safety-gate', 'query': QUERY, 'alert_ids': ['900001']})
    assert response.status_code == 422
    assert model.calls == 0
    with database.sessions() as db:
        assert db.scalar(select(AIEvidencePack.id)) is None


def test_negative_native_alert_and_nulls_survive_prepare_analysis_and_pdf(ai_case, monkeypatch):
    import test_safety_gate
    from test_reports import save, export
    from test_report_rendering import pdf_text
    client, _, _, _ = ai_case
    original = test_safety_gate.report
    monkeypatch.setattr(test_safety_gate, 'report', lambda: original().replace('alertDetail/900001', 'alertDetail/-1782'))
    result = run(client)
    pack = prepare(client, result, alert_id='-1782').json()['pack']
    assert pack['evidence'][0]['alert_id'] == '-1782'
    assert next(f for f in pack['facts'] if f['field_code'] == 'safety_gate.barcode')['value'] is None
    analysis = analyze(client, pack).json()
    assert analysis['state'] == 'completed'
    report = save(client, pack, analysis['id']).json()
    meta, body = export(client, report, 'pdf')
    assert meta['renderer_version'] == 'frozen-research-export@6'
    text = pdf_text(body)
    assert '-1782' in text and 'not_assessed' in text and '来源未标明' in text
