"""Conditional history refreshes use complete semantics and never refresh sources."""
from copy import deepcopy
from datetime import timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, update

from tire_api.db import EvidenceObject, QueryRun, Snapshot, Verification, WatchItem, uid, utcnow
from tire_api.domain import digest
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from tire_api.offline_packs import semantic_digest
from test_core import live
from test_garage import PROFILE
from test_offline_packs import EMPTY_SCOPE, confirm, download, fixed_receipt_scope, plan, setup


ENDPOINT = '/v1/offline-pack-updates:prepare'


def update_request(client, base, requested_scope, **changes):
    return client.post(ENDPOINT, json={'mode': 'history', 'base_pack_id': base['id'],
        'expected_base_sha256': base['sha256'], 'scope': requested_scope, **changes})


def stored_counts(database):
    with database.sessions() as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in
            (OfflinePackPlan, OfflinePack, EvidenceObject, QueryRun, Snapshot, Verification))


def forbid_external_calls(client, registry, monkeypatch):
    calls = {'source': 0, 'model': 0}
    def source(*args, **kwargs):
        calls['source'] += 1
        raise AssertionError('History-only updates cannot refresh a source')
    def model(*args, **kwargs):
        calls['model'] += 1
        raise AssertionError('History-only updates cannot configure or call an AI model')
    monkeypatch.setattr(registry, 'fetch', source)
    import tire_api.ai_gateway as gateway
    monkeypatch.setattr(gateway, 'configured_model', model)
    monkeypatch.setattr(client.app.state.ai_adapter, 'generate', model)
    monkeypatch.setattr(client.app.state.ai_adapter, 'stream', model)
    return calls


def test_no_change_ignores_export_nonces_without_writing_plan_pack_or_object(setup, monkeypatch):
    client, registry, database = setup
    live(client)
    client.post('/v1/garage', json=deepcopy(PROFILE))
    prepared = plan(client)
    base = confirm(client, prepared).json()
    raw, envelope = download(client, base)
    before = stored_counts(database)
    paths = sorted(database.object_store.root.rglob('*'))
    calls = forbid_external_calls(client, registry, monkeypatch)
    import tire_api.offline_packs as module
    def forbidden(*args, **kwargs):
        raise AssertionError('No-change cannot persist an object or a plan')
    monkeypatch.setattr(module, 'record_object', forbidden)
    monkeypatch.setattr(module, 'persist_plan', forbidden)
    response = update_request(client, base, envelope['scope'])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result == {'schema': 'offline-pack-update@1', 'state': 'no_change', 'mode': 'history',
        'base_pack_id': base['id'], 'base_semantic_digest': semantic_digest(envelope),
        'current_semantic_digest': semantic_digest(envelope), 'base_pack': base, 'plan': None,
        'source_refresh_performed': False}
    assert response.headers['cache-control'] == 'no-store'
    assert stored_counts(database) == before
    assert sorted(database.object_store.root.rglob('*')) == paths
    assert calls == {'source': 0, 'model': 0}
    assert download(client, base)[0] == raw


def test_garage_context_document_change_is_planned_when_member_diff_is_empty(setup, monkeypatch):
    client, registry, database = setup
    garage = client.post('/v1/garage', json=deepcopy(PROFILE)).json()
    prepared = plan(client)
    base = confirm(client, prepared).json()
    raw, envelope = download(client, base)
    changed_profile = {**garage['profile'], 'nickname': 'Changed private Garage nickname'}
    response = client.put('/v1/garage/' + garage['id'], json={
        'expected_revision': garage['revision'], 'profile': changed_profile})
    assert response.status_code == 200, response.text
    calls = forbid_external_calls(client, registry, monkeypatch)
    response = update_request(client, base, envelope['scope'])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['state'] == 'planned'
    assert result['base_semantic_digest'] != result['current_semantic_digest']
    changed = result['plan']
    assert changed['schema'] == 'offline-pack-plan@1' and changed['can_confirm']
    assert changed['base_pack_id'] == base['id']
    assert changed['diff'] == {'added': [], 'removed': [], 'changed': []}
    assert changed['contexts'][0]['payload']['profile'] == changed_profile
    assert changed['documents'][0]['title'] == changed_profile['nickname']
    key = uid()
    new = confirm(client, changed, key).json()
    assert confirm(client, changed, key).json() == new
    assert confirm(client, changed, key, expected_fingerprint='0' * 64).status_code == 409
    assert new['id'] != base['id'] and new['base_pack_id'] == base['id']
    _, current = download(client, new)
    assert semantic_digest(current) == result['current_semantic_digest']
    assert download(client, base)[0] == raw
    assert calls == {'source': 0, 'model': 0}
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(OfflinePack)) == 2


def test_watch_context_nested_timestamp_and_document_changes_are_not_nonces(setup):
    client, _, database = setup
    data = live(client).json()
    watch = client.post('/v1/watchlists', json={'variant_id': data['variants'][0]['id']}).json()
    scope = deepcopy(EMPTY_SCOPE)
    scope['watchlist'] = {'include': True}
    prepared = plan(client, scope)
    base = confirm(client, prepared).json()
    _, envelope = download(client, base)
    with database.sessions() as db:
        row = db.get(WatchItem, watch['id'])
        row.created_at += timedelta(seconds=1)
        db.commit()
    response = update_request(client, base, envelope['scope'])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['state'] == 'planned'
    assert result['plan']['diff'] == {'added': [], 'removed': [], 'changed': []}
    assert result['plan']['contexts'] != prepared['contexts']
    assert result['plan']['documents'] != prepared['documents']


@pytest.mark.parametrize('dimension', ['scope', 'contracts', 'documents', 'omissions'])
def test_full_scope_policy_documents_and_omissions_are_compared(setup, monkeypatch, dimension):
    client, _, _ = setup
    client.post('/v1/garage', json=deepcopy(PROFILE))
    prepared = plan(client)
    base = confirm(client, prepared).json()
    _, envelope = download(client, base)
    scope = deepcopy(envelope['scope'])
    import tire_api.offline_packs as module
    if dimension == 'scope':
        scope['recent']['limit'] = 19
    elif dimension == 'contracts':
        catalog = module.policy_catalog
        monkeypatch.setattr(module, 'policy_catalog', lambda: {**catalog(), 'synthetic_policy_revision': 2})
    elif dimension == 'documents':
        original = module.documents
        def changed(*args, **kwargs):
            docs = original(*args, **kwargs)
            docs[0]['text'] += ' synthetic search projection changed'
            return docs
        monkeypatch.setattr(module, 'documents', changed)
    else:
        original = module.resolve_scope
        def changed(*args, **kwargs):
            contexts, members, omissions, counts = original(*args, **kwargs)
            omissions.append({'selector': 'rights', 'object_id': None,
                'reason': 'synthetic_rights_policy_gap', 'blocking': False})
            return contexts, members, omissions, counts
        monkeypatch.setattr(module, 'resolve_scope', changed)
    response = update_request(client, base, scope)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['state'] == 'planned' and result['plan']['can_confirm']
    assert result['base_semantic_digest'] != result['current_semantic_digest']
    assert result['plan']['diff'] == {'added': [], 'removed': [], 'changed': []}


def test_new_verification_receipt_changes_complete_semantics_and_freezes_exact_bytes(setup, monkeypatch):
    client, registry, database = setup
    live(client)
    scope = deepcopy(EMPTY_SCOPE)
    scope['watchlist'] = {'include': True}
    with database.sessions() as db:
        variant_id = db.scalar(select(Snapshot)).parsed_variants[0]['id']
    client.post('/v1/watchlists', json={'variant_id': variant_id})
    prepared = plan(client, scope)
    base = confirm(client, prepared).json()
    raw, envelope = download(client, base)
    with database.sessions() as db:
        receipt = db.scalar(select(Verification))
        receipt_id = uid()
        db.add(Verification(id=receipt_id, snapshot_id=receipt.snapshot_id, query_id=receipt.query_id,
            source_id=receipt.source_id, query_key=receipt.query_key, status='not_modified',
            parser_identity=receipt.parser_identity, verified_at=utcnow() + timedelta(seconds=10)))
        db.commit()
    calls = forbid_external_calls(client, registry, monkeypatch)
    response = update_request(client, base, envelope['scope'])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['state'] == 'planned' and result['plan']['diff']['changed']
    assert result['plan']['resolved'][0]['reference']['verification_id'] == receipt_id
    new = confirm(client, result['plan']).json()
    _, current = download(client, new)
    assert current['members'][0]['reference']['verification_id'] == receipt_id
    assert semantic_digest(current) == result['current_semantic_digest']
    assert download(client, base)[0] == raw
    assert calls == {'source': 0, 'model': 0}


def test_owner_precedes_hash_and_corrupt_storage_checks(setup):
    client, _, database = setup
    prepared = plan(client, EMPTY_SCOPE)
    base = confirm(client, prepared).json()
    _, envelope = download(client, base)
    before = stored_counts(database)
    other = TestClient(client.app)
    assert update_request(other, base, envelope['scope'], expected_base_sha256='0' * 64).status_code == 404
    assert update_request(client, base, envelope['scope'], base_pack_id='missing').status_code == 404
    wrong = update_request(client, base, envelope['scope'], expected_base_sha256='0' * 64)
    assert wrong.status_code == 409 and wrong.json()['detail']['code'] == 'offline_base_sha256_mismatch'
    database.object_store.path(base['sha256']).write_bytes(b'private synthetic corrupted object')
    assert update_request(other, base, envelope['scope']).status_code == 404
    response = update_request(client, base, envelope['scope'])
    assert response.status_code == 503
    assert response.json()['detail'] == {'code': 'offline_frozen_object_unavailable'}
    assert str(database.object_store.root) not in response.text
    assert stored_counts(database) == before


@pytest.mark.parametrize('mutation', ['owner_scope_id', 'sha256', 'byte_count', 'content_created_at', 'plan_fingerprint'])
def test_inconsistent_base_descriptor_is_sanitized_503_before_prepare(setup, monkeypatch, mutation):
    client, _, database = setup
    prepared = plan(client, EMPTY_SCOPE)
    base = confirm(client, prepared).json()
    _, envelope = download(client, base)
    descriptor = {**base, mutation: 1 if mutation == 'byte_count' else '0' * 64}
    with database.engine.begin() as connection:
        connection.execute(update(OfflinePack).where(OfflinePack.id == base['id']).values(descriptor=descriptor))
    import tire_api.offline_packs as module
    def forbidden(*args, **kwargs):
        raise AssertionError('Invalid stored base metadata must fail before preparation')
    monkeypatch.setattr(module, 'prepare_plan', forbidden)
    response = update_request(client, base, envelope['scope'])
    assert response.status_code == 503, response.text
    assert response.json()['detail'] == {'code': 'offline_frozen_object_unavailable'}


@pytest.mark.parametrize('raw', [b'not-json', b'[]', b'{}', b'null'])
def test_valid_content_address_with_invalid_frozen_json_is_sanitized(setup, raw):
    client, _, database = setup
    prepared = plan(client, EMPTY_SCOPE)
    base = confirm(client, prepared).json()
    from tire_api.documents import record_object
    with database.sessions() as db:
        sha = record_object(db, raw)
        db.execute(update(OfflinePack).where(OfflinePack.id == base['id']).values(content_hash=sha, byte_count=len(raw)))
        db.commit()
    response = update_request(client, {**base, 'sha256': sha}, EMPTY_SCOPE)
    assert response.status_code == 503, response.text
    assert response.json()['detail'] == {'code': 'offline_frozen_object_unavailable'}


@pytest.mark.parametrize('changes', [
    {'mode': 'live'}, {'expected_base_sha256': 'invalid'}, {'expected_owner_scope_id': '0' * 64},
    {'scope': {**EMPTY_SCOPE, 'references': [{'kind': 'vehicle', 'snapshot_id': 'x'}] * 1001}},
    {'scope': {**EMPTY_SCOPE, 'garage': {'include': False, 'vehicle_ids': ['x'] * 1001}}},
    {'scope': {**EMPTY_SCOPE, 'watchlist': {'include': False, 'item_ids': ['x'] * 1001}}},
    {'scope': {**EMPTY_SCOPE, 'recent': {'include': True, 'limit': 21}}},
    {'scope': {**EMPTY_SCOPE, 'recent': {'include': 'false'}}},
])
def test_update_reuses_strict_dto_and_selector_bounds(setup, changes):
    client, _, database = setup
    base = confirm(client, plan(client, EMPTY_SCOPE)).json()
    before = stored_counts(database)
    assert update_request(client, base, EMPTY_SCOPE, **changes).status_code == 422
    assert stored_counts(database) == before


@pytest.mark.parametrize('limit_field,count_field', [('max_garage_profiles', 'garage_profiles'),
    ('max_watch_items', 'watch_items'), ('max_distinct_evidence', 'distinct_evidence'),
    ('max_searchable_documents', 'searchable_documents')])
def test_update_count_caps_stop_before_merge_and_do_not_create_partial_plan(setup, monkeypatch, limit_field, count_field):
    client, _, database = setup
    data = live(client).json()
    client.post('/v1/garage', json=deepcopy(PROFILE))
    client.post('/v1/watchlists', json={'variant_id': data['variants'][0]['id']})
    prepared = plan(client)
    base = confirm(client, prepared).json()
    _, envelope = download(client, base)
    before = stored_counts(database)
    import tire_api.offline_packs as module
    import tire_api.offline_evidence as evidence
    monkeypatch.setitem(module.CAPACITY, limit_field, 0)
    def forbidden(*args, **kwargs):
        raise AssertionError('An over-count must stop before field merging')
    monkeypatch.setattr(evidence, '_tire_resolution', forbidden)
    response = update_request(client, base, envelope['scope'])
    assert response.status_code == 413, response.text
    assert response.json()['detail']['dimension'] == count_field
    assert stored_counts(database) == before


def test_actual_201_receipts_update_stops_before_merge_and_without_partial_plan(setup, monkeypatch):
    client, _, database = setup
    base = confirm(client, plan(client, EMPTY_SCOPE)).json()
    scope = fixed_receipt_scope(setup, 201)
    before = stored_counts(database)
    import tire_api.offline_evidence as evidence
    def forbidden(*args, **kwargs):
        raise AssertionError('The 201st receipt must fail before merging')
    monkeypatch.setattr(evidence, '_tire_resolution', forbidden)
    response = update_request(client, base, scope)
    assert response.status_code == 413, response.text
    detail = response.json()['detail']
    assert detail['dimension'] == 'distinct_evidence' and detail['count'] == 201
    assert detail['limit'] == 200 and detail['count_is_lower_bound'] is True
    assert stored_counts(database) == before


def test_update_complete_preview_limit_still_rejects_no_change_without_partial_plan(setup, monkeypatch):
    client, _, database = setup
    client.post('/v1/garage', json=deepcopy(PROFILE))
    prepared = plan(client)
    base = confirm(client, prepared).json()
    _, envelope = download(client, base)
    before = stored_counts(database)
    import tire_api.offline_packs as module
    monkeypatch.setattr(module, 'MAX_PREVIEW_BYTES', 100)
    response = update_request(client, base, envelope['scope'])
    assert response.status_code == 413
    assert response.json()['detail']['code'] == 'offline_preview_transport_limit_exceeded'
    assert stored_counts(database) == before


def test_same_semantics_can_reuse_valid_base_when_only_new_nonces_overflow_bytes(setup, monkeypatch):
    client, _, database = setup
    prepared = plan(client, EMPTY_SCOPE)
    base = confirm(client, prepared).json()
    raw, envelope = download(client, base)
    before = stored_counts(database)
    import tire_api.offline_packs as module
    monkeypatch.setitem(module.CAPACITY, 'max_package_bytes', len(raw))
    measured = module.prepare_plan
    observed = []
    def capture(*args, **kwargs):
        result = measured(*args, **kwargs)
        observed.append(result.preview)
        return result
    monkeypatch.setattr(module, 'prepare_plan', capture)
    response = update_request(client, base, envelope['scope'])
    assert response.status_code == 200, response.text
    assert observed[0]['measured_bytes'] > len(raw) and not observed[0]['can_confirm']
    assert response.json()['state'] == 'no_change' and response.json()['plan'] is None
    assert stored_counts(database) == before


def test_real_semantic_change_over_byte_limit_retains_full_blocked_preview(setup, monkeypatch):
    client, _, database = setup
    prepared = plan(client, EMPTY_SCOPE)
    base = confirm(client, prepared).json()
    raw, envelope = download(client, base)
    client.post('/v1/garage', json=deepcopy(PROFILE))
    scope = deepcopy(envelope['scope'])
    scope['garage']['include'] = True
    before = stored_counts(database)
    import tire_api.offline_packs as module
    monkeypatch.setitem(module.CAPACITY, 'max_package_bytes', len(raw))
    response = update_request(client, base, scope)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['state'] == 'planned' and result['plan']['state'] == 'blocked'
    assert not result['plan']['can_confirm'] and result['plan']['content_sha256'] is None
    assert result['plan']['contexts'] and result['plan']['documents']
    assert any(row['reason'] == 'package_bytes_limit_exceeded' for row in result['plan']['omissions'])
    assert confirm(client, result['plan']).status_code == 409
    after = stored_counts(database)
    assert after[0] == before[0] + 1 and after[1:] == before[1:]
    assert download(client, base)[0] == raw


@pytest.mark.parametrize('field', ['schema', 'owner_scope_id', 'privacy_class', 'data_state',
    'source_refresh_performed', 'scope', 'contracts', 'contexts', 'members', 'documents', 'omissions'])
def test_semantic_digest_covers_every_meaningful_dimension_and_exact_canonical_namespace(field):
    envelope = {'schema': 'offline-pack@1', 'owner_scope_id': 'owner', 'privacy_class': 'private',
        'data_state': 'local_snapshot', 'source_refresh_performed': False, 'scope': {}, 'contracts': {},
        'contexts': [], 'members': [], 'documents': [], 'omissions': [],
        'package_id': 'one', 'created_at': 'now', 'plan_fingerprint': 'hash', 'base_pack_id': None}
    meaningful = {key: value for key, value in envelope.items()
        if key not in {'package_id', 'created_at', 'plan_fingerprint', 'base_pack_id'}}
    expected = digest({'namespace': 'offline-semantic@1', 'envelope': meaningful})
    assert semantic_digest(envelope) == expected
    changed = {**envelope, field: {'synthetic_change': True}}
    assert semantic_digest(changed) != expected
    nonces = {**envelope, 'package_id': 'two', 'created_at': 'later',
        'plan_fingerprint': 'another', 'base_pack_id': 'one'}
    assert semantic_digest(nonces) == expected


def test_semantic_digest_preserves_nested_nonces_list_order_and_future_fields():
    original = {'contexts': [{'created_at': 'first', 'package_id': 'nested'}],
        'members': [{'verification_id': 'old'}, {'verification_id': 'new'}]}
    for changed in ({**original, 'contexts': [{'created_at': 'later', 'package_id': 'nested'}]},
                    {**original, 'members': list(reversed(original['members']))},
                    {**original, 'future_semantic_field': True}):
        assert semantic_digest(changed) != semantic_digest(original)
