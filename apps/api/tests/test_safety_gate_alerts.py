"""Synthetic changes through the normal Safety Gate adoption and history routes."""
from copy import deepcopy
import xml.etree.ElementTree as ET

import pytest
from sqlalchemy import select, text

from test_safety_gate import context, count, report, run, QUERY, IDENTITY
from tire_api.adapters import safety_gate as source
from tire_api.safety_gate import SafetyGateSnapshot
from tire_api.safety_gate_alerts import AlertRevision, AlertObservation, AlertChange


def weekly(adapter, *, identity='900001', week='19', published='15/05/2026', name='Original', alerts=1):
    query = {'operation': 'report', 'report_id': identity, 'reference': 'Report-2026-' + week}
    root = ET.fromstring(report(alerts))
    root.find('report_week').text = str(int(week))
    root.find('report_date').text = published
    for row in root.findall('notifications'):
        row.find('name').text = name
    body = ET.tostring(root, encoding='unicode')

    async def fetch(selected, cached=None, *, on_observation=None):
        adapter.calls.append(deepcopy(selected))
        value = {'status': 'ok', 'url': source.query_url(selected), 'body': body,
            'content_type': 'application/xml', 'parser_version': source.PARSER_VERSION,
            'parser_identity': deepcopy(IDENTITY), 'document': source.parse_xml(body, selected)}
        if on_observation:
            on_observation(value)
        return value

    adapter.fetch = fetch
    return query


def history(client, identity='900001', **params):
    result = client.get('/v1/safety-gate/alerts/' + identity + '/history', params={'mode': 'history', **params})
    assert result.status_code == 200, result.text
    return result.json()


def test_repeated_and_serializer_observations_reuse_content(context):
    client, adapter, database = context
    first = run(client)
    run(client)
    adapter.mutate = lambda value: value.update(body='\n' + value['body'])
    run(client)
    value = history(client)
    assert value['data_state'] == 'local_snapshot' and value['state'] == 'observed'
    assert value['total'] == 2 and value['through_sequence'] == 2
    assert count(database, AlertRevision) == 1 and count(database, AlertChange) == 1
    assert value['observations'][0]['revision']['id'] == value['observations'][1]['revision']['id']
    assert 'order' not in value['heads'][0]['revision']['alert']['fields']
    assert client.get(first['provenance'][0]['evidence_path']).json()['body'] == report()


def test_cross_week_change_and_unchanged_content(context):
    client, adapter, database = context
    run(client, weekly(adapter))
    run(client, weekly(adapter, identity='900002', week='20', published='22/05/2026', name='Revised'))
    run(client, weekly(adapter, identity='900003', week='21', published='29/05/2026', name='Revised'))
    value = history(client)
    assert count(database, AlertRevision) == 2 and count(database, AlertChange) == 2
    assert value['heads'][0]['report']['reference'] == 'Report-2026-21'
    changes = [row['event'] for row in value['observations'] if row['event']]
    assert changes[0]['kind'] == 'content_changed'
    assert changes[0]['changes'] == {'fields.name': {'before': 'Original', 'after': 'Revised'}}
    assert value['heads'][0]['revision']['alert']['applicability'] == 'not_assessed'


def test_older_report_does_not_replace_later_source_observation(context):
    client, adapter, database = context
    run(client, weekly(adapter, identity='900002', week='20', published='22/05/2026', name='Newer'))
    run(client, weekly(adapter, name='Older'))
    value = history(client)
    assert value['heads'][0]['revision']['alert']['fields']['name'] == 'Newer'
    assert value['observations'][0]['event'] is None
    assert value['observations'][0]['report']['reference'] == 'Report-2026-19'
    assert count(database, AlertRevision) == 2 and count(database, AlertChange) == 1


def test_latest_report_observation_keeps_corrected_publication_date(context):
    client, adapter, _database = context
    run(client, weekly(adapter, published='22/05/2026', name='Before correction'))
    run(client, weekly(adapter, published='15/05/2026', name='After correction'))
    value = history(client)
    assert value['heads'][0]['report']['published_date'] == '2026-05-15'
    assert value['heads'][0]['revision']['alert']['fields']['name'] == 'After correction'
    assert value['observations'][0]['event']['kind'] == 'content_changed'


def test_reappearing_content_reuses_version_and_records_new_transition(context):
    client, adapter, database = context
    for name in ['A', 'B', 'A']:
        run(client, weekly(adapter, name=name))
    value = history(client)
    assert value['heads'][0]['revision']['revision'] == 1
    assert value['observations'][0]['event']['changes']['fields.name'] == {'before': 'B', 'after': 'A'}
    assert count(database, AlertRevision) == 2 and count(database, AlertChange) == 3


def test_same_date_conflict_and_resolution_are_explicit(context):
    client, adapter, database = context
    run(client, weekly(adapter, identity='900002', week='20', published='22/05/2026', name='A'))
    other = weekly(adapter, identity='900003', week='21', published='22/05/2026', name='B')
    run(client, other)
    value = history(client)
    assert value['state'] == 'conflicting' and len(value['heads']) == 2
    assert value['observations'][0]['event']['kind'] == 'conflict_observed'
    run(client, weekly(adapter, identity='900003', week='21', published='22/05/2026', name='A'))
    value = history(client)
    assert value['state'] == 'observed' and len(value['heads']) == 2
    assert value['observations'][0]['event']['kind'] == 'conflict_resolved'
    assert count(database, AlertRevision) == 2 and count(database, AlertChange) == 3


def test_report_order_does_not_change_content_revision(context):
    client, adapter, database = context
    run(client, weekly(adapter, alerts=2))
    original = adapter.fetch

    async def reordered(query, cached=None, *, on_observation=None):
        value = await original(query, cached=cached)
        root = ET.fromstring(value['body'])
        rows = root.findall('notifications')
        for row in rows:
            root.remove(row)
        for index, row in enumerate(reversed(rows), 1):
            row.find('order').text = str(index)
            root.append(row)
        value['body'] = ET.tostring(root, encoding='unicode')
        value['document'] = source.parse_xml(value['body'], query)
        on_observation(value)
        return value

    adapter.fetch = reordered
    run(client)
    assert history(client)['total'] == 2
    assert count(database, AlertRevision) == 2 and count(database, AlertChange) == 2


def test_absence_and_failed_online_query_preserve_known_evidence(context):
    client, adapter, database = context
    run(client, weekly(adapter))
    run(client, weekly(adapter, alerts=0))
    assert history(client)['total'] == 1
    assert count(database, AlertChange) == 1
    adapter.fetch = lambda *_args, **_kwargs: failing()

    async def failing():
        return {'status': 'unavailable', 'reason': 'synthetic_outage'}

    result = run(client)
    assert result['data_state'] == 'consent_required' and result['document'] is None
    assert count(database, AlertObservation) == 1


def test_explicit_history_rebuilds_legacy_snapshots_once(context, monkeypatch):
    import tire_api.safety_gate_alerts as alerts
    client, adapter, database = context
    with monkeypatch.context() as patch:
        patch.setattr(alerts, 'backfill_alert_history', lambda _db: 0)
        run(client, weekly(adapter))
        run(client, weekly(adapter, identity='900002', week='20', published='22/05/2026', name='Revised'))
    assert count(database, AlertObservation) == 0
    calls = len(adapter.calls)
    first = history(client)
    second = history(client)
    assert first == second and first['total'] == 2
    assert len(adapter.calls) == calls and count(database, AlertChange) == 2


def test_history_pages_use_fixed_observation_range(context):
    client, adapter, _database = context
    for name in ['A', 'B', 'C']:
        run(client, weekly(adapter, name=name))
    first = history(client, limit=1)
    assert first['total'] == 3 and first['observations'][0]['sequence'] == 3
    run(client, weekly(adapter, name='D'))
    second = history(client, limit=1, offset=1, through_sequence=first['through_sequence'])
    assert second['total'] == 3 and second['observations'][0]['sequence'] == 2
    assert second['heads'] == first['heads']
    assert history(client)['through_sequence'] == 4


@pytest.mark.parametrize('identity', ['-1782', '900002'])
def test_native_ids_stay_distinct_when_case_number_is_shared(context, identity):
    client, adapter, database = context
    run(client, weekly(adapter))
    query = weekly(adapter, identity='900002', week='20', published='22/05/2026')
    original = adapter.fetch

    async def renamed(selected, cached=None, *, on_observation=None):
        value = await original(selected, cached=cached)
        value['body'] = value['body'].replace('alertDetail/900001', 'alertDetail/' + identity)
        value['document'] = source.parse_xml(value['body'], selected)
        on_observation(value)
        return value

    adapter.fetch = renamed
    run(client, query)
    first, second = history(client), history(client, identity)
    assert first['alert_id'] != second['alert_id']
    assert first['heads'][0]['revision']['alert']['case_number'] == second['heads'][0]['revision']['alert']['case_number']
    assert count(database, AlertRevision) == 2


def test_corrupt_legacy_snapshot_rolls_back_entire_projection(context, monkeypatch):
    import tire_api.safety_gate_alerts as alerts
    client, adapter, database = context
    with monkeypatch.context() as patch:
        patch.setattr(alerts, 'backfill_alert_history', lambda _db: 0)
        run(client, weekly(adapter))
        second = run(client, weekly(adapter, name='B'))
    with database.engine.begin() as connection:
        connection.execute(text('UPDATE safety_gate_snapshots SET body=:body WHERE id=:id'),
            {'body': 'corrupt', 'id': second['provenance'][0]['snapshot_id']})
    response = client.get('/v1/safety-gate/alerts/900001/history', params={'mode': 'history'})
    assert response.status_code == 503
    assert count(database, AlertRevision) == count(database, AlertObservation) == count(database, AlertChange) == 0


@pytest.mark.parametrize('identity', ['0', '0900001', '＋1', '900001x', '1' * 13])
def test_history_rejects_invalid_native_identity(context, identity):
    client, _adapter, _database = context
    assert client.get('/v1/safety-gate/alerts/' + identity + '/history', params={'mode': 'history'}).status_code == 422


def test_history_requires_mode_and_valid_range(context):
    client, _adapter, _database = context
    run(client)
    path = '/v1/safety-gate/alerts/900001/history'
    assert client.get(path).status_code == 422
    for params in [{'limit': 0}, {'limit': 51}, {'offset': -1}, {'through_sequence': 0}, {'through_sequence': 100}]:
        assert client.get(path, params={'mode': 'history', **params}).status_code == 422
    assert client.get('/v1/safety-gate/alerts/-1782/history', params={'mode': 'history'}).status_code == 404


@pytest.mark.parametrize('model', [AlertRevision, AlertObservation, AlertChange])
def test_alert_history_is_append_only(context, model):
    client, _adapter, database = context
    run(client)
    with database.sessions() as db:
        db.delete(db.scalar(select(model)))
        with pytest.raises(ValueError):
            db.flush()


@pytest.mark.parametrize('mutation', [
    "UPDATE safety_gate_snapshots SET body='corrupt'",
    "UPDATE safety_gate_alert_revisions SET content_hash='corrupt'",
    "UPDATE safety_gate_alert_observations SET position=999",
])
def test_history_integrity_failure_is_visible(context, mutation):
    client, _adapter, database = context
    run(client)
    with database.engine.begin() as db:
        db.execute(text(mutation))
    response = client.get('/v1/safety-gate/alerts/900001/history', params={'mode': 'history'})
    assert response.status_code == 503
