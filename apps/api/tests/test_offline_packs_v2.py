"""Negotiated immutable discovery pages; fresh synthetic databases and adapters only."""
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, update

from tire_api.db import EvidenceObject
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from tire_api.recall_discovery import RecallSearchSnapshot, RecallSearchVerification
from test_core import live
from test_offline_packs import EMPTY_SCOPE, confirm, download, plan, setup
from test_recall_discovery import SearchFixture, product, search


V2 = ['offline-pack@1', 'offline-pack@2']


def adapter_for(client, count=1):
    adapter = SearchFixture()
    adapter.products = [product(identifier=index + 1) for index in range(count)]
    client.app.state.recall_adapter = adapter
    return adapter


def reference(database, query_id):
    with database.sessions() as db:
        receipt = db.scalar(select(RecallSearchVerification).where(RecallSearchVerification.query_id == query_id))
        return {'kind': 'recall_search', 'snapshot_id': receipt.snapshot_id, 'verification_id': receipt.id}


def explicit(ref):
    return {**deepcopy(EMPTY_SCOPE), 'references': [ref]}


def counts(database):
    with database.sessions() as db:
        return [db.scalar(select(func.count()).select_from(model)) for model in
                (OfflinePackPlan, OfflinePack, EvidenceObject)]


def test_negotiation_preserves_legacy_recent_closure_and_explicit_v2_page(setup):
    client, _, database = setup
    adapter = adapter_for(client, 2)
    current = search(client).json()
    old = plan(client)
    assert old['schema'] == 'offline-pack-plan@1' and old['counts']['distinct_evidence'] == 0
    assert any(row['reason'] == 'query_has_no_formal_receipt' for row in old['omissions'])
    prepared = plan(client, supported_pack_schemas=V2)
    assert prepared['schema'] == 'offline-pack-plan@2' and prepared['counts']['distinct_evidence'] == 1
    assert prepared['counts']['searchable_documents'] == 2
    calls = len(adapter.calls)
    descriptor = confirm(client, prepared).json()
    raw, envelope = download(client, descriptor)
    assert descriptor['schema'] == 'offline-pack-descriptor@2' and envelope['schema'] == 'offline-pack@2'
    member = envelope['members'][0]
    assert member['reference'] == reference(database, current['query_id'])
    assert member['payload']['discovery']['products'] == current['products']
    assert member['payload']['discovery']['pagination'] == current['pagination']
    assert member['payload']['boundary']['formal_campaign_revision'] is False
    assert member['payload']['boundary']['applicability'] == 'not_assessed'
    assert member['payload']['query'] == current['query'] and b'synthetic_search' not in raw
    assert [doc['record_index'] for doc in envelope['documents']] == [0, 1]
    assert len(adapter.calls) == calls


@pytest.mark.parametrize('supported', [[], None, ['offline-pack@3'], ['offline-pack@1', 'offline-pack@3']])
def test_unknown_or_empty_negotiation_rejected_without_plan(setup, supported):
    client, _, database = setup
    before = counts(database)
    response = client.post('/v1/offline-pack-plans', json={'mode': 'history', 'supported_pack_schemas': supported})
    assert response.status_code == 422 and counts(database) == before


def test_explicit_search_reference_requires_v2_and_exact_frozen_page_receipt(setup):
    client, _, database = setup
    adapter = adapter_for(client, 11)
    first = search(client).json()
    second = search(client, offset=10).json()
    first_ref, second_ref = reference(database, first['query_id']), reference(database, second['query_id'])
    assert client.post('/v1/offline-pack-plans', json={'mode': 'history', 'scope': explicit(second_ref)}).status_code == 422
    prepared = plan(client, explicit(second_ref), supported_pack_schemas=V2)
    adapter.not_modified = True
    search(client, offset=10)
    _, envelope = download(client, confirm(client, prepared).json())
    member = envelope['members'][0]
    assert member['reference'] == second_ref and member['payload']['query']['offset'] == '10'
    assert member['payload']['discovery']['pagination'] == second['pagination']
    assert member['payload']['discovery']['products'] == [product(11)]
    bad = {**second_ref, 'verification_id': first_ref['verification_id']}
    blocked = plan(client, explicit(bad), supported_pack_schemas=V2)
    assert not blocked['can_confirm']
    assert any('formal_receipt_mismatch' in row['reason'] for row in blocked['omissions'])


def test_other_owner_cannot_export_discovery_query_receipt(setup):
    client, _, database = setup
    adapter_for(client)
    current = search(client).json()
    with TestClient(client.app) as other:
        blocked = plan(other, explicit(reference(database, current['query_id'])), supported_pack_schemas=V2)
        assert not blocked['can_confirm']
        assert any('owner_mismatch' in row['reason'] for row in blocked['omissions'])


def test_empty_page_retains_exact_observation_and_has_one_search_document(setup):
    client, _, database = setup
    adapter_for(client, 0)
    current = search(client).json()
    prepared = plan(client, explicit(reference(database, current['query_id'])), supported_pack_schemas=V2)
    _, envelope = download(client, confirm(client, prepared).json())
    payload = envelope['members'][0]['payload']
    assert payload['empty_observation'] is True
    assert payload['discovery'] == {'products': [], 'pagination': current['pagination']}
    assert len(envelope['documents']) == 1 and envelope['documents'][0]['record_index'] is None


@pytest.mark.parametrize('field,value,reason', [('discovery_hash', '0' * 64, 'page_integrity'),
                                              ('raw_hash', '0' * 64, 'raw_integrity')])
def test_corrupt_page_does_not_change_already_frozen_original_bytes(setup, field, value, reason):
    client, _, database = setup
    adapter_for(client)
    current = search(client).json()
    ref = reference(database, current['query_id'])
    prepared = plan(client, explicit(ref), supported_pack_schemas=V2)
    with database.sessions() as db:
        db.execute(update(RecallSearchSnapshot).where(RecallSearchSnapshot.id == ref['snapshot_id']).values({field: value}))
        db.commit()
    blocked = plan(client, explicit(ref), supported_pack_schemas=V2)
    assert not blocked['can_confirm'] and any(reason in row['reason'] for row in blocked['omissions'])
    descriptor = confirm(client, prepared).json()
    raw, _ = download(client, descriptor)
    assert descriptor['sha256'] == prepared['content_sha256'] and len(raw) == prepared['measured_bytes']


def test_v2_updates_require_capability_and_keep_no_change_write_free(setup):
    client, _, database = setup
    adapter_for(client)
    current = search(client).json()
    scope = explicit(reference(database, current['query_id']))
    prepared = plan(client, scope, supported_pack_schemas=V2)
    base = confirm(client, prepared).json()
    request = {'mode': 'history', 'base_pack_id': base['id'], 'expected_base_sha256': base['sha256'], 'scope': scope}
    # New reference syntax is rejected before base lookup when @2 is omitted.
    assert client.post('/v1/offline-pack-updates:prepare', json=request).status_code == 422
    assert client.post('/v1/offline-pack-updates:prepare', json={**request, 'scope': EMPTY_SCOPE}).status_code == 409
    before = counts(database)
    response = client.post('/v1/offline-pack-updates:prepare', json={**request, 'supported_pack_schemas': V2})
    assert response.status_code == 200, response.text
    assert response.json()['schema'] == 'offline-pack-update@2' and response.json()['state'] == 'no_change'
    assert response.json()['plan'] is None and counts(database) == before
    _, envelope = download(client, base)
    assert envelope['schema'] == 'offline-pack@2'


def test_search_documents_capacity_and_failed_recent_do_not_borrow_pages(setup, monkeypatch):
    client, _, database = setup
    adapter = adapter_for(client, 10)
    search(client)
    import tire_api.offline_packs as module
    monkeypatch.setitem(module.CAPACITY, 'max_searchable_documents', 5)
    before = counts(database)
    response = client.post('/v1/offline-pack-plans', json={'mode': 'history', 'supported_pack_schemas': V2})
    assert response.status_code == 413 and counts(database) == before
    monkeypatch.setitem(module.CAPACITY, 'max_searchable_documents', 4000)
    adapter.offline = True
    failed = search(client).json()
    scope = {**deepcopy(EMPTY_SCOPE), 'recent': {'include': True, 'limit': 1}}
    prepared = plan(client, scope, supported_pack_schemas=V2)
    assert prepared['counts']['distinct_evidence'] == 0
    assert any(row['object_id'] == failed['query_id'] and row['reason'] == 'query_has_no_formal_receipt'
               for row in prepared['omissions'])


def test_v2_original_numeric_tokens_use_existing_python_canonical_writer(setup):
    client, registry, _ = setup
    registry.result['variants'][0]['facts'].update(reference_float=1.0, reference_int=9007199254740993,
                                                reference_tiny=5e-324)
    live(client)
    prepared = plan(client, supported_pack_schemas=V2)
    raw, envelope = download(client, confirm(client, prepared).json())
    assert b'"reference_float":1.0' in raw and b'"reference_int":9007199254740993' in raw
    assert b'"reference_tiny":5e-324' in raw
    assert raw == json.dumps(envelope, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
