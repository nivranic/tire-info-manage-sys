"""Explicitly synthetic identity decisions, including no-implicit-resolution guards."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, select

from tire_api.ai_models import AIRequest
from tire_api.db import ChangeEvent, FactVersion, Snapshot, TireVariant, Verification
from tire_api.identity_models import IdentityRevision
from tire_api.identity_resolution import IdentityDecision, append_decision
from tire_api.main import create_app
from test_core import FixtureRegistry, QUERY, VARIANT, count, grant, live, setup, success


def seed_pair(client, registry, *, three=False):
    rows = [{**deepcopy(VARIANT), 'manufacturer_product_code': f'FIX-{i}',
             'facts': {'product_code_type': 'MSPN', 'utqg_treadwear': i * 100}} for i in range(1, 4 if three else 3)]
    registry.result = success('synthetic-identity-pair', rows)
    response = live(client)
    assert response.status_code == 200 and response.json()['data_state'] == 'live'
    result = response.json()
    return [row['id'] for row in result['variants']], result['provenance'][0]['snapshot_id'], rows


def preview(client, origin, target=None):
    result = client.post(f'/v1/tire-variants/{origin}/identity-preview', json={'mode': 'history', 'target_id': target})
    assert result.status_code == 200, result.text
    return result.json()


def decision(client, origin, target, snapshots, action='correct'):
    state = preview(client, origin, target)
    return {'mode': 'history', 'target_id': target, 'action': action, 'expected_revision': state['revision'],
        'expected_fingerprint': state['fingerprint'], 'operator': '合成身份审核者',
        'reason': '仅演练身份治理，不对真实轮胎作纠错或等价结论', 'acknowledged': True,
        'acknowledge_unknowns': bool(state['unknown_fields']),
        'field_reasons': {row['field']: '已人工核对合成原文中的该项差异' for row in state['differences']},
        'evidence': [{'snapshot_id': key, 'locator': '合成精确产品代码所在行'} for key in snapshots]}


def post(client, origin, payload, key=None):
    return client.post(f'/v1/tire-variants/{origin}/identity-revisions', json=payload,
                       headers={'Idempotency-Key': key or str(uuid4())})


def read(client, origin):
    response = client.get(f'/v1/tire-variants/{origin}/identity-resolution?mode=history')
    assert response.status_code == 200, response.text
    return response.json()


def test_correct_compare_freeze_clear_and_preserve_originals(setup):
    client, registry, database = setup
    (a, b), snapshot, _ = seed_pair(client, registry)
    before = {model.__name__: count(database, model) for model in (TireVariant, FactVersion, Snapshot, Verification)}
    initial = client.post('/v1/compare', json={'variant_ids': [a, b]}).json()
    payload = decision(client, a, b, [snapshot])
    changed = post(client, a, payload)
    assert changed.status_code == 201, changed.text
    review = changed.json()['review']
    assert review['resolution']['state'] == 'redirected' and review['resolution']['target_id'] == b
    assert review['history'][0]['binding']['source']['identity']['manufacturer_product_code'] == 'FIX-1'
    assert read(client, b)['incoming'][0]['variant_id'] == a
    normal = client.post('/v1/compare', json={'variant_ids': [a, b]}).json()
    assert [v['id'] for v in normal['variants']] == [a, b] and normal['variants'][0]['facts']['utqg_treadwear'] == 100
    assert normal['fingerprint'] != initial['fingerprint']
    selection = {'variant_ids': [a, b], 'resolve_identities': True}
    resolved = client.post('/v1/compare', json=selection).json()
    assert [v['id'] for v in resolved['variants']] == [b] and resolved['variants'][0]['facts']['utqg_treadwear'] == 200
    assert resolved['identity_mappings'][0]['requested_id'] == a and resolved['identity_mappings'][0]['resolved_id'] == b
    saved = client.post('/v1/saved-comparisons', json={**selection, 'include_manual': False,
        'expected_fingerprint': resolved['fingerprint'], 'title': '合成身份比较', 'notes': ''})
    assert saved.status_code == 201, saved.text
    assert post(client, a, decision(client, a, None, [snapshot], 'clear')).status_code == 201
    restored = client.post('/v1/compare', json=selection).json()
    assert [v['id'] for v in restored['variants']] == [a, b]
    frozen = client.get('/v1/saved-comparisons/' + saved.json()['id'] + '?mode=history').json()
    assert frozen['comparison'] == resolved
    assert frozen['current_identity_resolutions'][a]['state'] == 'cleared'
    assert before == {model.__name__: count(database, model) for model in (TireVariant, FactVersion, Snapshot, Verification)}
    assert len(registry.calls) == 1
    with database.sessions() as db:
        row = db.get(TireVariant, a)
        assert row.identity['manufacturer_product_code'] == 'FIX-1'
        row = db.scalar(select(IdentityRevision))
        row.reason = 'overwrite'
        with pytest.raises(ValueError, match='只能追加'): db.commit()
        db.rollback()
        db.delete(db.scalar(select(IdentityRevision)))
        with pytest.raises(ValueError, match='只能追加'): db.commit()


def test_merge_requires_shared_stable_identifier_and_explicit_unknown_ack(setup):
    client, registry, database = setup
    (a, b), snapshot, _ = seed_pair(client, registry)
    state = preview(client, a, b)
    assert state['known_contradictions'] == ['manufacturer_product_code'] and not state['can_merge']
    assert post(client, a, decision(client, a, b, [snapshot], 'merge')).status_code == 409
    registry.result = success('incomplete identity', [{**VARIANT, 'hl': None,
        'facts': {**VARIANT['facts'], 'product_code_type': 'MSPN'}}])
    first = live(client, {'query': {'model': 'Fixture Tire'}, 'fallback_policy': 'never'}).json()
    second = live(client, source='fixture-two').json()
    x, y = first['variants'][0]['id'], second['variants'][0]['id']
    assert x != y
    evidence = [first['provenance'][0]['snapshot_id'], second['provenance'][0]['snapshot_id']]
    state = preview(client, x, y)
    assert state['can_merge'] and state['unknown_fields'] == ['hl']
    assert state['stable_anchors'] == ['manufacturer_product_code']
    payload = decision(client, x, y, evidence, 'merge')
    assert post(client, x, {**payload, 'acknowledge_unknowns': False}).status_code == 422
    assert post(client, x, {**payload, 'evidence': payload['evidence'][:1]}).status_code == 422
    assert post(client, x, payload).status_code == 201
    assert read(client, y)['incoming'][0]['action'] == 'merge'
    assert count(database, IdentityRevision) == 1


@pytest.mark.parametrize('mutate,status', [
    ({'field_reasons': {}}, 422), ({'operator': '   '}, 422), ({'acknowledged': False}, 422),
    ({'expected_revision': True}, 422), ({'expected_fingerprint': 'f'*64}, 409),
    ({'evidence': [{'snapshot_id': 'absent', 'locator': 'unrelated snapshot'}]}, 422),
    ({'evidence': [{'snapshot_id': 'absent', 'locator': '  '}]}, 422),
])
def test_invalid_decisions_never_write(setup, mutate, status):
    client, registry, database = setup
    (a, b), snapshot, _ = seed_pair(client, registry)
    assert post(client, a, {**decision(client, a, b, [snapshot]), **mutate}).status_code == status
    assert count(database, IdentityRevision) == 0


def test_self_cycle_and_changed_target_do_not_transitively_merge(setup):
    client, registry, _ = setup
    (a, b, c), snapshot, _ = seed_pair(client, registry, three=True)
    assert client.post(f'/v1/tire-variants/{a}/identity-preview', json={'mode': 'history', 'target_id': a}).status_code == 422
    assert post(client, a, decision(client, a, b, [snapshot])).status_code == 201
    assert 'target_has_identity_decision' in preview(client, b, a)['blockers']
    assert post(client, b, decision(client, b, a, [snapshot])).status_code == 409
    assert post(client, b, decision(client, b, c, [snapshot])).status_code == 201
    assert read(client, a)['resolution']['state'] == 'needs_review'
    assert read(client, a)['resolution']['target_id'] == b
    assert client.post('/v1/compare', json={'variant_ids': [a], 'resolve_identities': True}).status_code == 409
    assert post(client, a, decision(client, a, c, [snapshot])).status_code == 201
    assert read(client, a)['resolution']['target_id'] == c


def test_source_change_stales_decision_and_failure_never_reads_identity_history(setup):
    client, registry, database = setup
    (a, b), snapshot, rows = seed_pair(client, registry)
    stale = decision(client, a, b, [snapshot])
    assert post(client, a, stale).status_code == 201
    online = live(client).json()
    assert online['variants'][0]['id'] == a and online['variants'][0]['identity_resolution']['state'] == 'redirected'
    registry.result = {'status': 'not_modified', 'url': online['provenance'][0]['source_url'],
                       'parser_version': 'fixture@1', 'etag': '"fixture-etag"'}
    checked = live(client).json()
    assert checked['data_state'] == 'live_verified_304' and checked['variants'][0]['id'] == a
    registry.result = {'status': 'unavailable', 'reason': 'synthetic_outage'}
    statements = []
    def record(_conn, _cursor, sql, *_): statements.append(sql.lower())
    event.listen(database.engine, 'before_cursor_execute', record)
    try:
        failed = live(client).json()
    finally:
        event.remove(database.engine, 'before_cursor_execute', record)
    assert failed['variants'] == [] and all('identity_revisions' not in sql for sql in statements)
    consent = grant(client, failed['query_id']).json()
    fallback = live(client, {**QUERY, 'consent_id': consent['id']}).json()
    assert fallback['variants'][0]['id'] == a
    rows[1]['facts']['utqg_treadwear'] = 250
    registry.result = success('updated target facts', rows)
    assert live(client).json()['data_state'] == 'live'
    assert read(client, a)['resolution']['state'] == 'needs_review'
    assert post(client, a, stale).status_code == 409


def test_same_uuid_returns_original_event_after_clear_and_changed_payload_rejected(setup):
    client, registry, database = setup
    (a, b), snapshot, _ = seed_pair(client, registry)
    body, key = decision(client, a, b, [snapshot]), str(uuid4())
    first = post(client, a, body, key).json()
    assert post(client, a, decision(client, a, None, [snapshot], 'clear')).status_code == 201
    repeated = post(client, a, body, key).json()
    assert repeated['event'] == first['event'] and repeated['idempotent_replay']
    assert repeated['review']['resolution']['state'] == 'cleared'
    assert post(client, a, {**body, 'reason': 'different request reason'}, key).status_code == 409
    assert count(database, IdentityRevision) == 2


@pytest.mark.parametrize('same_key', [False, True])
def test_concurrent_decisions_are_serialized(tmp_path, same_key):
    app = create_app('sqlite:///' + (tmp_path / 'race.sqlite').as_posix(), FixtureRegistry())
    with TestClient(app) as client:
        (a, b), snapshot, _ = seed_pair(client, app.state.registry)
        body = IdentityDecision(**decision(client, a, b, [snapshot]))
        database = app.state.database
        barrier, key = Barrier(2), str(uuid4())
        def run(_):
            with database.sessions() as db:
                barrier.wait(timeout=10)
                try:
                    return append_decision(db, a, body, 'fixture-actor', key if same_key else str(uuid4()))['event']['revision']
                except HTTPException as error:
                    return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(run, [1, 2])) == ([1, 1] if same_key else [1, 409])
        assert count(database, IdentityRevision) == 1


def test_knowledge_and_new_or_frozen_ai_packs_require_identity_review(setup, monkeypatch):
    from test_ai import ModelFixture, analyze
    client, registry, database = setup
    model = ModelFixture()
    client.app.state.ai_adapter = model
    monkeypatch.setenv('TI_AI_ENABLED', '1')
    monkeypatch.setenv('TI_OPENAI_API_KEY', 'synthetic-key-never-live')
    monkeypatch.setenv('TI_OPENAI_MODEL', 'synthetic-model')
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '1')
    (a, b), snapshot, _ = seed_pair(client, registry)
    request = {'mode': 'history', 'references': [{'kind': 'tire', 'snapshot_id': snapshot, 'variant_id': a}]}
    pack = client.post('/v1/ai/evidence-packs', json=request).json()['pack']
    assert post(client, a, decision(client, a, b, [snapshot])).status_code == 201
    assert client.post('/v1/ai/evidence-packs', json=request).status_code == 409
    with database.sessions() as db:
        change = db.scalar(select(ChangeEvent).where(ChangeEvent.variant_id == a))
        change_id = change.id
    change_pack = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [
        {'kind': 'change_event', 'change_id': change_id}]})
    assert change_pack.status_code == 409 and change_pack.json()['detail']['code'] == 'identity_review_required'
    rejected = analyze(client, pack)
    assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'identity_review_required'
    assert model.calls == [] and count(database, AIRequest) == 0
    def search():
        r = client.post('/v1/knowledge/search', json={'mode': 'history', 'text': 'Fixture Tire'})
        assert r.status_code == 200, r.text
        return r.json()
    assert a not in str(search()) and b in str(search())
    assert post(client, a, decision(client, a, None, [snapshot], 'clear')).status_code == 201
    assert a in str(search())
    assert client.post('/v1/ai/evidence-packs', json=request).status_code == 200


def test_candidates_are_paginated_accepted_metadata_and_escape_sql_wildcards(setup):
    client, registry, _ = setup
    (a, b), _, _ = seed_pair(client, registry)
    assert client.get('/v1/identity-candidates').status_code == 422
    result = client.get('/v1/identity-candidates?mode=history&q=FIX-&offset=1').json()
    assert result['total'] == 2 and len(result['items']) == 1 and result['offset'] == 1
    assert result['items'][0]['id'] in {a, b} and 'facts' not in result['items'][0]
    assert client.get('/v1/identity-candidates?mode=history&q=%25').json()['items'] == []


@pytest.mark.parametrize('field,value,allowed', [
    ('gtin', True, False), ('gtin', ['4006381333931'], False), ('gtin', 4006381333931, False),
    ('gtin', '4006381333932', False), ('gtin', '00000000', False), ('gtin', '4006381333931', True),
    ('eprel_id', True, False), ('eprel_id', {'id': '1234'}, False), ('eprel_id', '0', False),
    ('eprel_id', '123456', True),
])
def test_merge_anchor_is_a_valid_identifier_not_an_arbitrary_json_fact(setup, field, value, allowed):
    client, registry, database = setup
    registry.result = success('synthetic anchor', [{**VARIANT, 'manufacturer_product_code': None, 'hl': None,
                                                   'facts': {field: value}}])
    first, second = live(client).json(), live(client, source='fixture-two').json()
    a, b = first['variants'][0]['id'], second['variants'][0]['id']
    assert a != b
    state = preview(client, a, b)
    assert state['can_merge'] is allowed
    assert state['stable_anchors'] == ([field] if allowed else [])
    payload = decision(client, a, b, [first['provenance'][0]['snapshot_id'], second['provenance'][0]['snapshot_id']], 'merge')
    assert post(client, a, payload).status_code == (201 if allowed else 409)
    assert count(database, IdentityRevision) == int(allowed)


@pytest.mark.parametrize('left_type,right_type,gtin,allowed,anchors', [
    (None, None, None, False, []),
    ('MSPN', 'MSPN', None, True, ['manufacturer_product_code']),
    ('MSPN', 'CAI', '4006381333931', False, ['gtin']),
    (None, None, '4006381333931', True, ['gtin']),
    (None, 'MSPN', None, False, []),
])
def test_code_anchor_requires_equal_known_namespace(setup, left_type, right_type, gtin, allowed, anchors):
    client, registry, _ = setup
    def row(namespace):
        return {**deepcopy(VARIANT), 'manufacturer_product_code': '001', 'hl': None,
                'facts': {'product_code_type': namespace, **({'gtin': gtin} if gtin else {})}}
    registry.result = success('synthetic first namespace', [row(left_type)])
    first = live(client).json()
    registry.result = success('synthetic second namespace', [row(right_type)])
    second = live(client, source='fixture-two').json()
    a, b = first['variants'][0]['id'], second['variants'][0]['id']
    assert a != b
    proposed = preview(client, a, b)
    assert proposed['can_merge'] is allowed and proposed['stable_anchors'] == anchors
    if left_type and right_type and left_type != right_type:
        assert 'product_code_type' in proposed['known_contradictions']
    if left_type is None or right_type is None:
        assert 'product_code_type' in proposed['unknown_fields']


def test_policy_change_stales_unchanged_decision_and_idempotent_replay(setup, monkeypatch):
    import tire_api.identity_resolution as resolution
    client, registry, database = setup
    (a, b), snapshot, _ = seed_pair(client, registry)
    current_policy = resolution.IDENTITY_POLICY_VERSION
    monkeypatch.setattr(resolution, 'IDENTITY_POLICY_VERSION', 'identity-resolution@1')
    payload, key = decision(client, a, b, [snapshot]), str(uuid4())
    event = post(client, a, payload, key).json()['event']
    assert read(client, a)['resolution']['state'] == 'redirected'
    monkeypatch.setattr(resolution, 'IDENTITY_POLICY_VERSION', current_policy)
    assert read(client, a)['resolution']['state'] == 'needs_review'
    replay = post(client, a, payload, key).json()
    assert replay['event'] == event and replay['idempotent_replay']
    assert replay['review']['resolution']['state'] == 'needs_review'
    assert client.post('/v1/compare', json={'variant_ids': [a], 'resolve_identities': True}).status_code == 409
    with database.sessions() as db, pytest.raises(HTTPException) as error:
        resolution.require_ai_identity(db, [a])
    assert error.value.detail['code'] == 'identity_review_required'
    assert post(client, a, decision(client, a, None, [snapshot], 'clear')).status_code == 201
    monkeypatch.setattr(resolution, 'IDENTITY_POLICY_VERSION', 'identity-resolution@next-test')
    assert read(client, a)['resolution']['state'] == 'cleared'


def test_unbound_legacy_identity_is_not_resolved_or_sent_to_ai(setup):
    from tire_api.domain import VariantInput
    from tire_api.identity_resolution import require_ai_identity, resolve_comparison_ids
    client, _registry, database = setup
    parsed = VariantInput.model_validate(VARIANT)
    key, status = parsed.legacy_identity_key('synthetic-legacy', 'synthetic-query', 0)
    variant_id = str(uuid4())
    with database.sessions() as db:
        db.add(TireVariant(id=variant_id, identity_key=key, identity=parsed.legacy_identity(), identity_status=status))
        db.commit()
        for operation in (require_ai_identity, resolve_comparison_ids):
            with pytest.raises(HTTPException) as error:
                operation(db, [variant_id])
            assert error.value.detail['code'] == 'identity_contract_review_required'
    assert client.post('/v1/compare', json={'variant_ids': [variant_id]}).status_code == 409
