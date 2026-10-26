"""Governance producers use synthetic accepted observations in private databases."""
from copy import deepcopy

from test_interest_events import producer, adopt
from test_core import VARIANT, success
from test_curation import prepare, edit
from test_lifecycle import request_for


def follow(client, fields):
    response = client.post('/v1/interests', json={'name': 'Synthetic governance following', 'enabled': True,
        'conditions': [{'kind': 'brand', 'values': ['Fixture Brand']}], 'metric_keys': [], 'changed_fields': fields})
    assert response.status_code == 201, response.text
    return response.json()


def notices(client, domain):
    response = client.get('/v1/interest-notifications?mode=history')
    assert response.status_code == 200, response.text
    return [row for row in response.json()['items'] if row['event']['domain'] == domain]


def test_manual_values_and_exact_original_record_remain_frozen(producer):
    client, _, _ = producer
    variant_id, _, _, payload = prepare(client)
    follow(client, ['facts.utqg_treadwear'])
    response = edit(client, variant_id, {**payload, 'value': 0})
    assert response.status_code == 201, response.text
    found = notices(client, 'tire_curation')
    assert len(found) == 1
    event = found[0]['event']
    assert event['before']['facts']['utqg_treadwear'] == 300
    assert event['after']['facts']['utqg_treadwear'] == 0
    ref = next(ref for ref in event['evidence'] if ref['kind'] == 'tire_curation_revision')
    original = client.get(f"/v1/interest-evidence/{ref['kind']}/{ref['record_id']}?mode=history")
    assert original.status_code == 200, original.text
    body = original.json()
    assert body['fingerprint'] == ref['fingerprint'] and body['record']['after'] == {'present': True, 'value': 0}
    assert 'operator_session_id' not in body['record'] and 'valid_to' not in body['record']
    assert body['evidence'] == event['evidence']


def test_lifecycle_changes_state_without_fabricating_fact_changes(producer):
    client, _, _ = producer
    initial = adopt(client)
    variant = initial['variants'][0]['id']
    follow(client, ['state'])
    for revision, action in enumerate(('revoke', 'restore')):
        response = client.post(f'/v1/tire-variants/{variant}/lifecycle-events',
            json=request_for(initial, action=action, expected_revision=revision))
        assert response.status_code == 201, response.text
    found = notices(client, 'tire_lifecycle')
    assert len(found) == 2 and {item['event']['action'] for item in found} == {'revoke', 'restore'}
    assert all(item['event']['changed_paths'] == ['state'] for item in found)


def test_catalog_reentry_is_new_even_when_fact_and_snapshot_pair_repeat(producer):
    client, registry, _ = producer
    rows = [{**deepcopy(VARIANT), 'manufacturer_product_code': f'SYNTHETIC-{index}',
             'facts': {**VARIANT['facts'], 'product_code_type': 'MSPN'}} for index in range(4)]
    registry.result = success('Synthetic full catalog', rows)
    adopt(client)
    follow(client, ['catalog_membership'])
    for _ in range(2):
        registry.result = success('Synthetic partial catalog', rows[1:])
        adopt(client)
        registry.result = success('Synthetic full catalog', rows)
        adopt(client)
    found = notices(client, 'tire_catalog')
    assert len(found) == 4
    assert [item['event']['revision'] for item in sorted(found, key=lambda item: item['event']['revision'])] == [2, 3, 4, 5]
    assert {item['event']['action'] for item in found} == {'added', 'removed'}
    assert all(item['event']['changed_paths'] == ['catalog_membership', 'state'] for item in found)
    registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product', 'etag': '"fixture-etag"'}
    adopt(client)
    assert len(notices(client, 'tire_catalog')) == 4
