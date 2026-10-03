"""Synthetic identity reads keep bounded SQL costs and current binding semantics."""
from contextlib import contextmanager
from copy import deepcopy

import pytest
from sqlalchemy import event

from tire_api.identity_models import IdentityRevision
from tire_api.identity_resolution import annotate_identities, review
from test_core import VARIANT, count, live, setup, success
from test_identity_resolution import decision, post, preview, seed_pair


@contextmanager
def selected_statements(database):
    statements = []

    def record(_connection, _cursor, sql, *_):
        if sql.lstrip().lower().startswith('select'):
            statements.append(sql.lower())

    event.listen(database.engine, 'before_cursor_execute', record)
    try:
        yield statements
    finally:
        event.remove(database.engine, 'before_cursor_execute', record)


def seed_many(client, registry, count):
    rows = [{**deepcopy(VARIANT), 'manufacturer_product_code': f'BATCH-{index:03}',
             'facts': {'product_code_type': 'MSPN', 'utqg_treadwear': 100 + index}} for index in range(count)]
    registry.result = success('synthetic identity batch', rows)
    response = live(client)
    assert response.status_code == 200 and response.json()['data_state'] == 'live'
    data = response.json()
    return [row['id'] for row in data['variants']], data['provenance'][0]['snapshot_id']


def annotations(database, ids):
    with database.sessions() as db:
        return annotate_identities(db, [{'id': value} for value in ids])


@pytest.mark.parametrize('shared_target', [True, False], ids=['shared-target', 'different-targets'])
def test_one_hundred_decisions_use_bounded_annotation_and_incoming_queries(setup, shared_target):
    client, registry, database = setup
    ids, snapshot = seed_many(client, registry, 101 if shared_target else 200)
    origins = ids[:100]
    targets = [ids[-1]] * 100 if shared_target else ids[100:]
    for origin, target in zip(origins, targets):
        response = post(client, origin, decision(client, origin, target, [snapshot]))
        assert response.status_code == 201, response.text

    with selected_statements(database) as statements:
        result = annotations(database, origins)
    assert len(statements) <= 8, len(statements)
    assert len(result) == 100
    assert [row['identity_resolution']['target_id'] for row in result] == targets
    assert {row['identity_resolution']['state'] for row in result} == {'redirected'}
    print(f'annotation shared_target={shared_target}: {len(statements)} SELECTs for 100 decisions')

    if shared_target:
        with selected_statements(database) as statements, database.sessions() as db:
            incoming = review(db, targets[0])
        assert len(statements) <= 15, len(statements)
        assert len(incoming['incoming']) == 100 and not incoming['incoming_truncated']
        assert {row['variant_id'] for row in incoming['incoming']} == set(origins)
        assert {row['state'] for row in incoming['incoming']} == {'redirected'}
        print(f'incoming review: {len(statements)} SELECTs for 100 decisions')


def test_no_decisions_have_bounded_contract_reads_and_failed_query_has_none(setup):
    client, registry, database = setup
    ids, _ = seed_many(client, registry, 100)
    with selected_statements(database) as statements:
        result = annotations(database, ids)
        assert [row['id'] for row in result] == ids
        assert all(row['identity_contract']['state'] == 'current' for row in result)
        assert all('identity_resolution' not in row for row in result)
    assert len(statements) == 4 and 'identity_revisions' in statements[0]
    with selected_statements(database) as statements:
        result = live(client).json()
    assert result['data_state'] == 'live'
    assert sum('identity_revisions' in sql for sql in statements) == 1
    registry.result = {'status': 'unavailable', 'reason': 'synthetic_outage'}
    with selected_statements(database) as statements:
        assert live(client).json()['variants'] == []
        assert annotations(database, []) == []
    assert all('identity_revisions' not in sql for sql in statements)


def test_batch_bindings_track_each_source_latest_fact_lifecycle_and_target_revision(setup):
    client, registry, database = setup
    (a, b, c), snapshot, rows = seed_pair(client, registry, three=True)
    rows[1]['facts']['utqg_treadwear'] = 250
    registry.result = success('synthetic second source v1', rows)
    second = live(client, source='fixture-two').json()
    assert second['data_state'] == 'live'
    snapshots = [snapshot, second['provenance'][0]['snapshot_id']]
    for origin in (a, c):
        assert post(client, origin, decision(client, origin, b, snapshots)).status_code == 201
    assert post(client, c, decision(client, c, None, [snapshot], 'clear')).status_code == 201
    initial = annotations(database, [a, b, c])
    assert initial[0]['identity_resolution']['state'] == 'redirected'
    assert 'identity_resolution' not in initial[1]
    assert initial[2]['identity_resolution']['state'] == 'cleared'

    # Only one source advances its target facts; both per-source bindings matter.
    rows[1]['facts']['utqg_treadwear'] = 300
    registry.result = success('synthetic second source v2', rows)
    assert live(client, source='fixture-two').json()['data_state'] == 'live'
    assert annotations(database, [a])[0]['identity_resolution']['state'] == 'needs_review'
    assert post(client, a, decision(client, a, None, [snapshot], 'clear')).status_code == 201
    with selected_statements(database) as statements:
        assert {row['identity_resolution']['state'] for row in annotations(database, [a, c])} == {'cleared'}
    assert len(statements) == 4
    assert post(client, a, decision(client, a, b, snapshots)).status_code == 201
    assert annotations(database, [a])[0]['identity_resolution']['state'] == 'redirected'

    # Restoring active state still advances lifecycle revision and invalidates the binding.
    for index, action in enumerate(('revoke', 'restore')):
        response = client.post(f'/v1/tire-variants/{b}/lifecycle-events', json={
            'action': action, 'expected_revision': index, 'operator': '合成生命周期审核者',
            'reason': '仅合成批量身份读取回归验证。',
            'evidence': [{'snapshot_id': snapshot, 'locator': '合成精确产品代码所在行'}]})
        assert response.status_code == 201, response.text
        assert annotations(database, [a])[0]['identity_resolution']['state'] == 'needs_review'
    assert post(client, a, decision(client, a, b, snapshots)).status_code == 201
    assert annotations(database, [a])[0]['identity_resolution']['state'] == 'redirected'

    # A target decision, including its later clear, never changes A transitively to C.
    assert post(client, b, decision(client, b, c, snapshots)).status_code == 201
    result = annotations(database, [a])[0]['identity_resolution']
    assert result['state'] == 'needs_review' and result['target_id'] == b
    assert post(client, b, decision(client, b, None, [snapshot], 'clear')).status_code == 201
    result = annotations(database, [a, b])
    assert result[0]['identity_resolution']['state'] == 'needs_review'
    assert result[1]['identity_resolution']['state'] == 'cleared'


@pytest.mark.parametrize('field,left,right', [
    ('gtin', True, 1),
    ('gtin', False, 0),
    ('technology_features', [{'feature': {'enabled': True}}], [{'feature': {'enabled': 1}}]),
    ('technology_features', [{'feature': {'levels': [False]}}], [{'feature': {'levels': [0]}}]),
])
def test_json_type_contradictions_block_merge_even_with_a_valid_shared_code(setup, field, left, right):
    client, registry, database = setup
    results = []
    for source, value in [('fixture', left), ('fixture-two', right)]:
        registry.result = success('synthetic strict JSON identity ' + source, [{
            **deepcopy(VARIANT), 'manufacturer_product_code': 'FIX-001', 'hl': None,
            'facts': {'product_code_type': 'MSPN', field: value}}])
        response = live(client, source=source)
        assert response.status_code == 200 and response.json()['data_state'] == 'live'
        results.append(response.json())
    a, b = [result['variants'][0]['id'] for result in results]
    assert a != b
    state = preview(client, a, b)
    assert state['stable_anchors'] == ['manufacturer_product_code']
    assert state['known_contradictions'] == [field]
    assert [row['field'] for row in state['differences']] == [field]
    assert state['can_correct'] and not state['can_merge']
    payload = decision(client, a, b, [result['provenance'][0]['snapshot_id'] for result in results], 'merge')
    rejected = post(client, a, payload)
    assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'identity_gate_failed'
    assert count(database, IdentityRevision) == 0


def test_equal_valid_json_identity_still_allows_explicit_merge(setup):
    client, registry, database = setup
    registry.result = success('synthetic equal valid identity', [{
        **deepcopy(VARIANT), 'manufacturer_product_code': 'FIX-001', 'hl': None,
        'facts': {'product_code_type': 'MSPN', 'gtin': '4006381333931', 'technology_features': ['Acoustic', 'XL']}}])
    first, second = live(client).json(), live(client, source='fixture-two').json()
    a, b = first['variants'][0]['id'], second['variants'][0]['id']
    assert a != b
    state = preview(client, a, b)
    assert state['can_merge'] and state['differences'] == state['known_contradictions'] == []
    assert set(state['stable_anchors']) == {'gtin', 'manufacturer_product_code'}
    response = post(client, a, decision(client, a, b,
        [first['provenance'][0]['snapshot_id'], second['provenance'][0]['snapshot_id']], 'merge'))
    assert response.status_code == 201, response.text
    assert count(database, IdentityRevision) == 1
