"""Chinese announcement contracts at admission, dispatch, stream and export boundaries."""
from copy import deepcopy
from dataclasses import replace
import json
import time

import pytest
from sqlalchemy import select, text, update

from test_ai_stream_api import accept, until
from test_samr import NOTICE, SEARCH
from test_samr_ai import ai_case, analyze, pack_for, prepare, reference
from test_samr_recalls import run
from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.domain import digest


def execute(client, pack, streamed):
    if not streamed:
        response = analyze(client, pack)
        assert response.status_code == 200, response.text
        return response.json(), None
    response = accept(client, pack)
    assert response.status_code == 202, response.text
    detail = until(client, response.json()['analysis']['id'], lambda row: row['execution']['terminal'])
    return detail['analysis'], detail


@pytest.mark.parametrize('mutation', [
    lambda pack: pack['facts'][0].update(text='Unbound prose'),
    lambda pack: pack['facts'].pop(),
    lambda pack: pack['facts'][0].update(record_key='b' * 32),
    lambda pack: pack['evidence'][0].update(source_id='nhtsa-us-recalls'),
    lambda pack: pack['evidence'][0].update(region='US'),
    lambda pack: pack['evidence'][0].update(article_id='b' * 32),
    lambda pack: pack['evidence'][0].update(parser_identity={'invalid': True}),
    lambda pack: pack['evidence'][0]['notice_values'].update(pub_date_raw='invalid'),
    lambda pack: pack['evidence'][0]['access_basis'].update(redistribution_license='claimed-open'),
    lambda pack: pack['samr_boundary'].update(applicability='safe'),
    lambda pack: pack.pop('samr_policy'),
])
def test_frozen_contract_rejects_tampered_fields_and_metadata(ai_case, mutation):
    from tire_api.ai_samr_contract import validate_payload
    pack = pack_for(ai_case[0])
    mutation(pack)
    with pytest.raises((ValueError, KeyError)):
        validate_payload(pack)


def test_admission_rejects_stale_contract_before_reservation(ai_case):
    client, _, database, model = ai_case
    pack = pack_for(client)
    with database.sessions() as db:
        stored = db.get(AIEvidencePack, pack['id'])
        value = deepcopy(stored.payload)
        value['facts'][0]['text'] = 'unapproved mutation'
        db.execute(update(AIEvidencePack).where(AIEvidencePack.id == stored.id).values(payload=value, fingerprint=digest(value)))
        db.commit()
    response = analyze(client, pack)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'ai_samr_contract_stale'
    assert model.calls == 0
    with database.sessions() as db:
        assert db.scalar(select(AIRequest.id)) is None


@pytest.mark.parametrize('streamed', [False, True])
@pytest.mark.parametrize('mutation', [
    'body', 'question', 'model', 'provider', 'owner', 'contract_policy',
    'contract_version', 'contract_removed', 'all_payload_markers_removed',
])
def test_actual_dispatch_rechecks_accepted_packet_and_recipient(ai_case, monkeypatch, streamed, mutation):
    from tire_api import ai_samr_contract as contract
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
                    stored = db.get(AIEvidencePack, request.pack_id)
                    if mutation == 'owner':
                        db.execute(update(AIEvidencePack).where(AIEvidencePack.id == stored.id).values(actor_session_id='other-synthetic-session'))
                    elif mutation.startswith('contract_'):
                        value = deepcopy(request.request_contract)
                        if mutation == 'contract_policy':
                            value['samr_policy']['digest'] = 'f' * 64
                        elif mutation == 'contract_version':
                            value['samr_prompt_version'] = 'unrecognized@9'
                        else:
                            value.pop('samr_policy')
                        db.execute(update(AIRequest).where(AIRequest.id == request_id).values(request_contract=value))
                    else:
                        value = {'purpose': 'analysis', 'evidence': [{'id': 'e1', 'kind': 'manual', 'label': 'Synthetic replacement'}],
                            'facts': [{'id': 'f1', 'evidence_id': 'e1', 'field': 'replacement', 'value': 'unapproved', 'text': 'unapproved'}],
                            'conflicts': [], 'source_state': 'snapshot'}
                        db.execute(update(AIEvidencePack).where(AIEvidencePack.id == stored.id).values(payload=value, fingerprint=digest(value)))
                        envelope = json.loads(body['input'][1]['content'])
                        envelope['untrusted_evidence_pack'] = {**value, 'data_state': stored.data_state}
                        body['input'][1]['content'] = json.dumps(envelope)
                        if running_pack is not None:
                            running_pack['payload'] = deepcopy(value)
                    db.commit()
        return actual(database, request_id, config, body, running_pack)

    monkeypatch.setattr(contract, 'require_dispatch', checked)
    if streamed and mutation == 'owner':
        accepted = accept(client, pack)
        assert accepted.status_code == 202, accepted.text
        request_id = accepted.json()['analysis']['id']
        deadline = time.monotonic() + 5
        while True:
            with database.sessions() as db:
                completion = db.get(AICompletion, request_id)
                if completion:
                    result = {name: getattr(completion, name) for name in ('state', 'error_code', 'usage', 'answer')}
                    break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert client.get('/v1/ai/analysis-streams/' + request_id + '?mode=history').status_code == 404
    else:
        result, _ = execute(client, pack, streamed)
    assert entered and model.calls == 0
    assert result['state'] == 'failed' and result['error_code'] == 'ai_grounding_validation_failed'
    assert result['answer'] is None and result['usage']['total_tokens'] == 0


@pytest.mark.parametrize('streamed', [False, True])
def test_completion_rechecks_raw_after_provider_execution(ai_case, streamed):
    client, _, database, model = ai_case
    pack = pack_for(client)

    def corrupt(_answer, _payload):
        with database.engine.begin() as connection:
            connection.execute(text('UPDATE samr_recall_snapshots SET body=:body'), {'body': 'tampered after provider entry'})

    model.mutate = corrupt
    result, detail = execute(client, pack, streamed)
    assert model.calls == 1 and result['state'] == 'failed'
    assert result['error_code'] == 'ai_grounding_validation_failed' and result['answer'] is None
    assert result['usage']['total_tokens'] == 30
    if detail:
        assert detail['draft_claims'] == [] and detail['draft_uncertainty'] is None


@pytest.mark.parametrize('mutation', ['verification_status', 'query_state', 'parser_identity', 'search_snapshot'])
def test_history_requires_successful_exact_notice_verification(ai_case, mutation):
    from tire_api.db import QueryRun
    from tire_api.samr_recalls import SamrRecallVerification
    client, _, database, model = ai_case
    result = run(client, SEARCH if mutation == 'search_snapshot' else NOTICE)
    if mutation == 'search_snapshot':
        response = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [{
            'kind': 'samr_recall', 'snapshot_id': result['provenance'][0]['snapshot_id'], 'article_id': 'a' * 32}]})
        assert response.status_code == 404
    else:
        with database.sessions() as db:
            if mutation == 'verification_status':
                db.execute(update(SamrRecallVerification).values(status='failed'))
            elif mutation == 'query_state':
                db.execute(update(QueryRun).values(state='source_unavailable'))
            else:
                db.execute(update(SamrRecallVerification).values(parser_identity={'invalid': True}))
            db.commit()
        assert prepare(client, result).status_code == 409
    assert model.calls == 0


@pytest.mark.parametrize('mode', ['current', 'history'])
def test_large_official_body_is_rejected_with_complete_source_retained(ai_case, mode):
    from test_samr_notice_history import revised
    from tire_api.samr_recalls import SamrRecallSnapshot
    client, adapter, database, model = ai_case
    revised(adapter, content='完整合成公告' * 4000)
    if mode == 'current':
        response = client.post('/v1/ai/evidence-packs', json={'mode': 'current', 'query_kind': 'samr_recall_notice',
            'source_id': 'samr-cn-recalls', 'query': NOTICE})
    else:
        response = prepare(client, run(client))
    assert response.status_code == 422, response.text
    with database.sessions() as db:
        saved = db.scalar(select(SamrRecallSnapshot))
        assert '完整合成公告' * 4000 in saved.document['notice']['text']
        assert db.scalar(select(AIEvidencePack.id)) is None
    assert model.calls == 0


def test_different_article_scopes_cannot_form_one_claim(ai_case):
    client, _, _, model = ai_case
    first = run(client)
    second = run(client, {'operation': 'notice', 'reference': NOTICE['reference'].replace('a' * 32, 'b' * 32)})
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [reference(first), reference(second)]})
    assert response.status_code == 200, response.text
    pack = response.json()['pack']

    def combine(answer, payload):
        facts = [next(fact for fact in payload['facts'] if fact['evidence_id'] == item['id']) for item in payload['evidence']]
        answer['claims'][0].update(fact_ids=[fact['id'] for fact in facts], evidence_ids=[fact['evidence_id'] for fact in facts])

    model.mutate = combine
    assert analyze(client, pack).json()['error_code'] == 'ai_grounding_validation_failed'


def test_saved_report_exports_after_original_changes(ai_case):
    from test_reports import save, export
    client, _, database, _ = ai_case
    pack = pack_for(client)
    analysis = analyze(client, pack).json()
    assert analysis['state'] == 'completed', analysis
    saved = save(client, pack, analysis['id'])
    assert saved.status_code == 201, saved.text
    report = saved.json()
    first, original = export(client, report)
    with database.engine.begin() as connection:
        connection.execute(text('UPDATE samr_recall_snapshots SET body=:body'), {'body': 'changed after frozen report'})
    second, restored = export(client, report)
    assert first['sha256'] == second['sha256'] and original == restored
    assert '中国召回公告与适用性边界' in original.decode()
