"""Synthetic actual-base replacements; all storage is private to the runner."""
from copy import deepcopy

import pytest
from sqlalchemy import event, func, select

from test_core import VARIANT, success
from test_curation import edit, prepare
from test_interest_events import adopt as query_source, producer


def adopt(client):
    # The synthetic legacy namespace is query-local. Keep prepare()'s scope.
    return query_source(client, broad=True)


def watch(client):
    response = client.post('/v1/interests', json={'name': 'Synthetic manual applicability', 'enabled': True,
        'conditions': [{'kind': 'brand', 'values': ['Fixture Brand']}], 'metric_keys': [],
        'changed_fields': ['curation_applicability']})
    assert response.status_code == 201, response.text
    return response.json()


def notices(client):
    response = client.get('/v1/interest-notifications?mode=history&limit=100')
    assert response.status_code == 200, response.text
    return [row for row in response.json()['items'] if row['event']['domain'] == 'tire_curation_validity']


def test_new_fact_aggregates_manual_heads_and_keeps_exact_original_reader(producer):
    client, registry, database = producer
    variant_id, _, _, payload = prepare(client)
    assert edit(client, variant_id, {**payload, 'value': 0}).status_code == 201
    assert edit(client, variant_id, {**payload, 'field': 'tread_depth', 'value': None,
                                    'expected_revision': 1}).status_code == 201
    watch(client)
    registry.result = success('Synthetic new source base', [{**deepcopy(VARIANT),
        'facts': {'utqg_treadwear': 320, 'tread_depth': {'value': 7, 'unit': 'mm'}}}])
    adopt(client)
    found = notices(client)
    assert len(found) == 1
    frozen = found[0]['event']
    assert frozen['action'] == 'invalidate' and frozen['state'] == 'needs_review'
    assert frozen['before']['facts'] == {'utqg_treadwear': 0, 'tread_depth': None}
    assert frozen['after']['facts']['utqg_treadwear'] == 320
    reference = next(row for row in frozen['evidence'] if row['kind'] == 'tire_curation_applicability_event')
    original = client.get(f"/v1/interest-evidence/{reference['kind']}/{reference['record_id']}?mode=history")
    assert original.status_code == 200, original.text
    body = original.json()
    assert body['fingerprint'] == reference['fingerprint']
    assert {row['field'] for row in body['record']['affected']} == {'utqg_treadwear', 'tread_depth'}
    assert body['record']['manual_revision_watermark'] == 2
    assert body['record']['binding']['after']['fact_version'] == 2
    assert body['evidence'] == frozen['evidence']
    from tire_api.db import ManualFactRevision
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ManualFactRevision)) == 2


def test_metadata_and_later_stale_refresh_do_not_duplicate_invalidation(producer):
    client, registry, _ = producer
    variant_id, _, _, payload = prepare(client)
    assert edit(client, variant_id, payload).status_code == 201
    watch(client)
    registry.result = success('Synthetic changed raw body with the same actual facts')
    adopt(client)
    assert notices(client) == []
    registry.result = success('Synthetic replacement base', [{**deepcopy(VARIANT),
        'facts': {'utqg_treadwear': 420}}])
    adopt(client)
    found = notices(client)
    assert len(found) == 1
    assert found[0]['event']['changed_paths'] == ['curation_applicability', 'state']
    registry.result = success('Synthetic later replacement while old manual remains stale',
        [{**deepcopy(VARIANT), 'facts': {'utqg_treadwear': 440}}])
    adopt(client)
    assert len(notices(client)) == 1


def test_delivery_failure_rolls_back_the_entire_source_acceptance(producer):
    client, registry, database = producer
    variant_id, _, _, payload = prepare(client)
    assert edit(client, variant_id, payload).status_code == 201
    watch(client)
    from tire_api.db import ChangeEvent, FactVersion, Snapshot, Verification
    from tire_api.interest_applicability_models import TireCurationApplicabilityEvent
    from tire_api.interest_catalog_models import TireCatalogRevision
    from tire_api.interest_models import InterestEvent, InterestNotification
    models = (Snapshot, FactVersion, Verification, ChangeEvent, TireCatalogRevision,
              TireCurationApplicabilityEvent, InterestEvent, InterestNotification)
    def counts():
        with database.sessions() as db:
            return [db.scalar(select(func.count()).select_from(model)) for model in models]
    before = counts()
    registry.result = success('Synthetic rollback source', [{**deepcopy(VARIANT), 'facts': {'utqg_treadwear': 320}}])
    def fail(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith('insert into interest_notifications'):
            raise RuntimeError('synthetic_applicability_delivery_failure')
    event.listen(database.engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='synthetic_applicability_delivery_failure'):
            adopt(client)
    finally:
        event.remove(database.engine, 'before_cursor_execute', fail)
    assert counts() == before
    adopt(client)
    assert len(notices(client)) == 1
