"""Synthetic Recall -> Knowledge -> exact AI material; no real source/model/Parser."""
from copy import deepcopy

import pytest
from sqlalchemy import event, select, text

from tire_api.recall_models import RecallRevision, RecallSnapshot
from test_recalls import CAMPAIGN, grant, live, recall_setup, record


@pytest.fixture
def setup(recall_setup, monkeypatch):
    from tire_api.adapters.transport import SafeHttpClient
    from tire_api.ai_gateway import OpenAIResponsesAdapter
    from tire_api import parser_runtime

    def forbidden(*_args, **_kwargs):
        raise AssertionError('real_source_model_or_parser_forbidden')

    monkeypatch.setattr(SafeHttpClient, '_request', forbidden)
    monkeypatch.setattr(OpenAIResponsesAdapter, 'generate', forbidden)
    monkeypatch.setattr(OpenAIResponsesAdapter, 'stream', forbidden)
    monkeypatch.setattr(parser_runtime, '_run_sync', forbidden)
    return recall_setup


def reference(database, result):
    snapshot_id = result['provenance'][0]['snapshot_id']
    with database.sessions() as db:
        snapshot = db.get(RecallSnapshot, snapshot_id)
        revision = db.scalar(select(RecallRevision).where(RecallRevision.campaign_number == snapshot.campaign_number,
            RecallRevision.revision == snapshot.revision)) if snapshot.revision is not None else None
        return {'kind': 'recall', 'snapshot_id': snapshot_id,
                'recall_revision_id': revision.id if revision else None}


def history_pack(client, ref):
    return client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [ref]})


def current_pack(client, **extra):
    return client.post('/v1/ai/evidence-packs', json={'mode': 'current', 'query_kind': 'recall_by_campaign',
        'source_id': 'nhtsa-us-recalls', 'query': {'campaign_number': CAMPAIGN}, **extra})


def search(client, text='', **filters):
    return client.post('/v1/knowledge/search', json={'mode': 'history', 'text': text,
        'filters': {'kind': 'recall', **filters}})


def test_history_pack_preserves_every_record_and_pure_frozen_contract(setup):
    client, adapter, database, _ = setup
    adapter.rows = [record('A'), record('B'), record('B')]
    result = live(client).json()
    ref = reference(database, result)
    response = history_pack(client, ref)
    assert response.status_code == 200, response.text
    pack = response.json()['pack']
    assert pack['purpose'] == 'recall_research' and pack['privacy_class'] == 'public'
    assert pack['recall_policy']['version'] == 'recall-fact-selection@1'
    assert pack['recall_boundary']['applicability'] == 'not_assessed'
    evidence, = pack['evidence']
    assert evidence['evidence_type'] == 'recall' and evidence['record_count'] == 3
    assert evidence['recall_revision_id'] == ref['recall_revision_id']
    assert len({item['record_key'] for item in evidence['record_scopes']}) == 3
    assert 'variant_id' not in evidence and 'event_id' not in evidence
    from tire_api.recall_evidence import validate_frozen_recall_evidence
    validate_frozen_recall_evidence(evidence, pack['facts'])
    forged = deepcopy(pack['facts'])
    forged[-1]['text'] = 'This tire is safe'
    with pytest.raises(ValueError):
        validate_frozen_recall_evidence(evidence, forged)
    assert len(adapter.calls) == 1  # Explicit history does not refetch.


def test_same_content_new_snapshot_can_bind_original_revision_only(setup):
    client, adapter, database, _ = setup
    first = live(client).json()
    first_ref = reference(database, first)
    adapter.identity['deployment_revision'] = 2
    second = live(client).json()
    second_ref = reference(database, second)
    assert first_ref['snapshot_id'] != second_ref['snapshot_id']
    assert first_ref['recall_revision_id'] == second_ref['recall_revision_id']
    response = history_pack(client, second_ref)
    assert response.status_code == 200, response.text
    evidence, = response.json()['pack']['evidence']
    assert evidence['snapshot_id'] == second_ref['snapshot_id']
    assert evidence['revision_snapshot_id'] == first_ref['snapshot_id']
    assert evidence['verified_at'] == second['verified_at']
    adapter.rows[0]['remedy'] = 'Changed official synthetic remedy'
    third_ref = reference(database, live(client).json())
    assert history_pack(client, {**second_ref, 'recall_revision_id': third_ref['recall_revision_id']}).status_code == 409
    assert history_pack(client, {**second_ref, 'recall_revision_id': None}).status_code == 409


def test_current_recall_online_first_and_one_use_consent(setup):
    client, adapter, database, _ = setup
    assert current_pack(client).status_code == 200
    adapter.offline = True
    statements = []

    def track(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    event.listen(database.engine, 'before_cursor_execute', track)
    try:
        failed = current_pack(client).json()
        assert failed['pack'] is None and failed['query_result']['data_state'] == 'consent_required'
        assert not any('recall_snapshots.records' in sql or 'from recall_revisions' in sql for sql in statements)
        consent = grant(client, failed['query_result']['query_id'])
        statements.clear()
        result = current_pack(client, consent_id=consent)
        assert result.status_code == 200, result.text
        assert result.json()['pack']['data_state'] == 'local_snapshot'
        claim = next(i for i, sql in enumerate(statements) if sql.startswith('update fallback_consents'))
        read = next(i for i, sql in enumerate(statements) if 'recall_snapshots.records' in sql)
        assert claim < read
        assert current_pack(client, consent_id=consent).status_code == 409
        assert len(adapter.calls) == 2
    finally:
        event.remove(database.engine, 'before_cursor_execute', track)


def test_knowledge_same_record_and_explicit_campaign_filters(setup):
    client, adapter, database, _ = setup
    adapter.rows = [{**record('PSEV'), 'make': 'Brand A'}, {**record('Other'), 'make': 'Brand B'}]
    result = live(client).json()
    response = search(client, campaign_number=CAMPAIGN, brand='Brand A', model='PSEV')
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['total'] == 1 and value['items'][0]['reference'] == reference(database, result)
    assert search(client, campaign_number=CAMPAIGN, brand='Brand A', model='Other').json()['total'] == 0
    assert search(client, campaign_number=CAMPAIGN, size='265/40R20').json()['total'] == 0
    assert search(client, campaign_number=CAMPAIGN, product_code='not-provided').json()['total'] == 0
    assert search(client, campaign_number='23T999999').json()['total'] == 0
    assert search(client, text=CAMPAIGN).json()['total'] == 2
    authority = search(client, campaign_number=CAMPAIGN, field='recall.remedy').json()['items'][0]['match']
    assert authority['authority_tier'] == 1 and authority['authority_rule'] == 'recall:regulatory'
    current = search(client, text='最新', campaign_number=CAMPAIGN)
    assert current.status_code == 409 and current.json()['detail']['route'] == '/v1/recalls/live-query'


def test_empty_observation_keeps_old_content_time_and_has_no_old_facts(setup):
    client, adapter, database, _ = setup
    old = live(client).json()
    old_ref = reference(database, old)
    adapter.rows = []
    empty = live(client).json()
    empty_ref = reference(database, empty)
    response = search(client, campaign_number=CAMPAIGN)
    assert response.status_code == 200, response.text
    items = response.json()['items']
    content = next(item for item in items if item['reference'] == old_ref)
    observation = next(item for item in items if item['reference'] == empty_ref)
    assert content['verified_at'] == old['verified_at']
    assert observation['verified_at'] == empty['verified_at']
    assert observation['recall']['observation_kind'] == 'empty'
    assert observation['recall']['record_count'] == 0
    prepared = history_pack(client, empty_ref)
    assert prepared.status_code == 200, prepared.text
    pack = prepared.json()['pack']
    assert len(pack['facts']) == 4 and all(item['scope'] == 'observation' for item in pack['facts'])
    assert 'Synthetic remedy' not in str(pack)
    assert empty['analysis_reference'] == empty_ref


@pytest.mark.parametrize('extra', [
    {'source_id': 'fixture'}, {'query': {'search': 'SYNTHETIC'}}, {'variant_ids': ['fake']},
    {'references': [{'kind': 'recall', 'snapshot_id': 'fake', 'recall_revision_id': None}]},
])
def test_current_recall_invalid_shape_never_fetches(setup, extra):
    client, adapter, _, _ = setup
    assert current_pack(client, **extra).status_code == 422
    assert not adapter.calls


def test_recall_pack_never_silently_truncates_records(setup):
    client, adapter, database, _ = setup
    adapter.rows = [record('Record ' + str(i)) for i in range(30)]
    ref = reference(database, live(client).json())
    assert history_pack(client, ref).status_code == 422


def test_recall_pack_byte_limit_never_truncates_one_large_record(setup):
    client, adapter, database, _ = setup
    adapter.rows[0]['summary'] = '原始公告完整正文 ' * 6000
    ref = reference(database, live(client).json())
    assert history_pack(client, ref).status_code == 422


@pytest.mark.parametrize('mutation', ['raw_hash', 'records_hash', 'source_url', 'query_key', 'verification_query'])
def test_formal_binding_integrity_failure_cannot_prepare(setup, mutation):
    client, _, database, _ = setup
    result = live(client).json()
    ref = reference(database, result)
    # Deliberately simulate corrupted private stored evidence, bypassing append-only ORM guards.
    with database.engine.begin() as connection:
        if mutation == 'verification_query':
            connection.execute(text('UPDATE query_runs SET query_key=:value WHERE id=:id'),
                               {'value': '0' * 64, 'id': result['query_id']})
        else:
            value = 'https://example.invalid/forged' if mutation == 'source_url' else '0' * 64
            connection.execute(text(f'UPDATE recall_snapshots SET {mutation}=:value WHERE id=:id'),
                               {'value': value, 'id': ref['snapshot_id']})
    assert history_pack(client, ref).status_code == 503


def test_frozen_verification_never_refreshes_to_a_later_304(setup):
    client, adapter, database, _ = setup
    first = live(client).json()
    ref = reference(database, first)
    evidence = history_pack(client, ref).json()['pack']['evidence'][0]
    adapter.not_modified = True
    later = live(client).json()
    assert later['data_state'] == 'live_verified_304'
    from tire_api.recall_evidence import load_recall_evidence
    with database.sessions() as db:
        frozen = load_recall_evidence(db, ref['snapshot_id'], ref['recall_revision_id'],
                                     verification_id=evidence['verification_id'])['evidence']
        refreshed = load_recall_evidence(db, ref['snapshot_id'], ref['recall_revision_id'])['evidence']
    assert frozen['verified_at'] == first['verified_at']
    assert refreshed['verified_at'] == later['verified_at']
    assert frozen['verification_id'] != refreshed['verification_id']


@pytest.mark.parametrize('mutation', ['pause', 'aba', 'notes'])
def test_current_recall_pack_final_source_fence_returns_recall_shape(setup, monkeypatch, mutation):
    from tire_api.adapters import nhtsa
    from tire_api.ai_evidence import PackBuilder
    from tire_api.ai_models import AIEvidencePack
    from test_core import count
    from test_source_access import mutate_source
    client, adapter, database, app = setup
    sources = app.state.registry.sources
    monkeypatch.setattr(app.state.registry, 'sources', lambda: sources() + [nhtsa.source_metadata()])
    original = PackBuilder.recall

    def recall(builder, *args, **kwargs):
        original(builder, *args, **kwargs)
        mutate_source((client, app, {'recall': adapter}), 'recall', mutation)

    monkeypatch.setattr(PackBuilder, 'recall', recall)
    response = current_pack(client)
    assert response.status_code == 200, response.text
    value = response.json()
    if mutation == 'notes':
        assert value['pack'] is not None and count(database, AIEvidencePack) == 1
    else:
        assert value['pack'] is None and value['reason'] == 'source_access_changed'
        assert value['query_result']['records'] == [] and 'variants' not in value['query_result']
        assert value['query_result']['analysis_reference'] is None
        assert count(database, AIEvidencePack) == 0
    monkeypatch.setattr(PackBuilder, 'recall', original)
    history = client.get(f'/v1/recalls/{CAMPAIGN}/history?mode=history').json()
    assert history_pack(client, history['analysis_reference']).status_code == 200


def test_recall_embedding_material_is_public_semantic_and_time_independent(setup):
    from types import SimpleNamespace
    from tire_api.embedding_text import document_chunks
    from tire_api.knowledge_models import KnowledgeDocument
    client, adapter, _, _ = setup
    live(client)
    first = search(client, campaign_number=CAMPAIGN).json()['items'][0]
    database = client.app.state.database
    config = SimpleNamespace(model='synthetic-no-provider-call', dimensions=3)
    with database.sessions() as db:
        before = document_chunks(db.get(KnowledgeDocument, first['id']), config)
    adapter.rows = []
    empty = live(client).json()
    items = search(client, campaign_number=CAMPAIGN).json()['items']
    content = next(item for item in items if item['id'] == first['id'])
    assert content['recall']['latest_observation']['verified_at'] == empty['verified_at']
    with database.sessions() as db:
        after = document_chunks(db.get(KnowledgeDocument, first['id']), config)
    assert before == after
    encoded = str(after)
    assert first['reference']['snapshot_id'] not in encoded and first['verified_at'] not in encoded
    assert all(chunk['privacy_class'] == 'public' for chunk in after)
    assert 'Synthetic remedy' in encoded and 'not_assessed' in encoded


def test_archived_recall_contract_is_independent_of_active_policy_and_source_dto(monkeypatch):
    from tire_api import recall_evidence as helper
    from test_recall_grounding import recall_pack
    payload = recall_pack(mixed=False)
    evidence, = payload['evidence']
    version = payload['recall_policy']['version']
    archived = helper.frozen_recall_contract(version)
    assert archived['policy'] == payload['recall_policy']
    # Callers cannot mutate the retained schema through its returned material.
    archived['record_fields']['summary'] = 'changed returned copy'
    assert helper.frozen_recall_contract(version)['record_fields']['summary'] == '公告摘要'
    monkeypatch.setattr(helper, 'CURRENT_RECALL_POLICY_VERSION', 'recall-fact-selection@2')
    monkeypatch.setattr(helper, 'RECALL_FIELDS', {'future_field': '新策略字段'})
    monkeypatch.setattr(helper, 'recall_policy_descriptor', lambda: {'version': 'recall-fact-selection@2', 'digest': 'f' * 64})
    monkeypatch.setattr(helper, 'recall_boundary_descriptor', lambda: {'policy': 'recall-fact-selection@2'})

    def future_source_dto(*_args, **_kwargs):
        raise AssertionError('archived_report_must_not_reparse_with_current_source_dto')

    monkeypatch.setattr(helper, 'canonical_records', future_source_dto)
    helper.validate_frozen_recall_evidence(evidence, payload['facts'], policy_version=version)
    forged = deepcopy(payload['facts'])
    forged[-1]['value'] = 'safe'
    with pytest.raises(ValueError):
        helper.validate_frozen_recall_evidence(evidence, forged, policy_version=version)
    with pytest.raises(ValueError, match='unsupported_frozen_recall_policy'):
        helper.validate_frozen_recall_evidence(evidence, payload['facts'], policy_version='recall-fact-selection@999')
