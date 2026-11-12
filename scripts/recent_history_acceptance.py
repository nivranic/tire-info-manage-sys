"""029-032 business acceptance in the disposable PostgreSQL verification database."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import make_url

from tire_api.db import EvidenceDocument, EvidenceObject, FactVersion, Snapshot, SourceQuarantine, Verification
from tire_api.interest_models import InterestEvent, InterestNotification
from tire_api.main import create_app
from tire_api.material_source_policy import PolicyCatalog, canonical_policy
from tire_api.service import QueryService
from tire_api.source_material_models import SourceMaterialOutcome, SourceMaterialStop
from tire_api.source_page_models import SourcePageChange, SourcePageNotification
from tire_api.source_page_monitoring import append_page_change
from tire_api.source_page_url_models import SourcePageUrlMove, SourcePageUrlMoveNotification
from tire_api.source_page_url_monitoring import append_url_move
from test_core import FixtureRegistry, VARIANT, success
from test_source_materials import POLICY, obtained, payload as material_payload, stop_payload
from test_source_quality_interests import accepted_state, model_count

QUERY = {'model': 'PG Recent History', 'size': '265/40R20'}
OLD_URL = 'https://fixture.example/tires/recent-history'
NEW_URL = 'https://fixture.example/tires/recent-history-moved'
PAGE_PATH = '/v1/source-page-notifications'
URL_PATH = '/v1/source-page-url-move-notifications'
STATE_MODELS = (Snapshot, Verification, FactVersion, SourceQuarantine, SourcePageChange,
    SourcePageNotification, SourcePageUrlMove, SourcePageUrlMoveNotification, InterestEvent, InterestNotification)


def accepted(response, expected=200):
    if response.status_code != expected:
        detail = response.json().get('detail')
        raise AssertionError({'state': 'http_failure', 'completion': {
            'error_code': detail.get('code') if isinstance(detail, dict) else None}})
    return response.json()


def online(client):
    return client.post('/v1/sources/fixture/live-query', json={'query': QUERY, 'fallback_policy': 'never'})


def counts(database, models=STATE_MODELS):
    return {model.__tablename__: model_count(database, model) for model in models}


def own_notices(client, path, rule_ids):
    rows = accepted(client.get(path, params={'mode': 'history', 'limit': 50}))['items']
    return [row for row in rows if row['rule_id'] in rule_ids]


def rule(client, kind, name):
    return accepted(client.post('/v1/alert-rules', json={'name': name, 'source_id': 'fixture',
        'query': QUERY, 'enabled': True, 'kinds': [kind], 'fields': [], 'conditions': {},
        'variant_id': None}), 201)


def failed_delivery_rolls_back(client, database, table):
    before = counts(database)
    marker = 'synthetic-recent-history-delivery-failure'

    def reject(_connection, _cursor, statement, *_args):
        if statement.lstrip().lower().startswith('insert into ' + table):
            raise RuntimeError(marker)

    event.listen(database.engine, 'before_cursor_execute', reject)
    try:
        try:
            online(client)
        except RuntimeError as error:
            assert str(error) == marker
        else:
            raise AssertionError('The synthetic delivery failure did not reach its insertion')
    finally:
        event.remove(database.engine, 'before_cursor_execute', reject)
    assert counts(database) == before


def replay_page_event(database, model, event_id, append):
    before = counts(database)
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        row = db.get(model, event_id)
        assert append(db, db.get(Verification, row.verification_id),
            db.get(Verification, row.previous_verification_id)).id == row.id
        db.commit()
    assert counts(database) == before


def page_and_url_history(client, registry, database, variant):
    page = rule(client, 'page_changed', 'PG original text history')
    moved = rule(client, 'url_moved', 'PG source address history')
    registry.result = success('PG original A', [variant], url=OLD_URL)
    first = accepted(online(client))
    assert first['data_state'] == 'live'
    registry.result = success('PG original B', [variant], url=OLD_URL)
    failed_delivery_rolls_back(client, database, 'source_page_notifications')
    second = accepted(online(client))
    assert second['data_state'] == 'live'
    notices = own_notices(client, PAGE_PATH, {page['id']})
    assert len(notices) == 1
    assert notices[0]['event']['before']['snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert notices[0]['event']['after']['snapshot_id'] == second['provenance'][0]['snapshot_id']
    assert not own_notices(client, URL_PATH, {moved['id']})
    late_page = rule(client, 'page_changed', 'PG late original subscription')
    replay_page_event(database, SourcePageChange, notices[0]['event']['id'], append_page_change)
    assert not own_notices(client, PAGE_PATH, {late_page['id']})

    registry.result = success('PG original B', [variant], url=NEW_URL)
    failed_delivery_rolls_back(client, database, 'source_page_url_move_notifications')
    moved_result = accepted(online(client))
    assert moved_result['data_state'] == 'live'
    registry.result = success('PG original B', [variant], url=OLD_URL)
    returned = accepted(online(client))
    assert returned['data_state'] == 'live'
    moves = own_notices(client, URL_PATH, {moved['id']})
    assert len(moves) == 2
    assert {(row['event']['previous_source_url'], row['event']['source_url']) for row in moves} == {
        (OLD_URL, NEW_URL), (NEW_URL, OLD_URL)}
    assert len(own_notices(client, PAGE_PATH, {page['id'], late_page['id']})) == 1
    late_url = rule(client, 'url_moved', 'PG late address subscription')
    replay_page_event(database, SourcePageUrlMove, moves[0]['event']['id'], append_url_move)
    assert not own_notices(client, URL_PATH, {late_url['id']})
    for path, notice in ((PAGE_PATH, notices[0]), (URL_PATH, moves[0])):
        marked = accepted(client.put(path + '/' + notice['id'] + '/read', json={'read': True}))
        assert marked['read_at']
        assert accepted(client.put(path + '/' + notice['id'] + '/read', json={'read': True})) == marked
    frozen = []
    for path, notice in [(PAGE_PATH, notices[0]), *((URL_PATH, item) for item in moves)]:
        frozen.append({'path': path + '/' + notice['id'],
            'value': accepted(client.get(path + '/' + notice['id'], params={'mode': 'history'}))})
    return {'notices': frozen, 'baseline': returned}


def quality_history(client, registry, database, interest, unsubscribed, baseline):
    before = accepted_state(database)
    previous_events = counts(database, (SourcePageChange, SourcePageUrlMove))
    registry.result = success('PG rejected quality update', [], url=OLD_URL)
    failed_delivery_rolls_back(client, database, 'interest_notifications')
    rejected = accepted(online(client))
    assert rejected['data_state'] == 'source_unavailable'
    assert rejected['reason'] == 'source_quality_quarantined' and not rejected['variants']
    assert accepted_state(database) == before
    assert counts(database, (SourcePageChange, SourcePageUrlMove)) == previous_events
    rows = accepted(client.get('/v1/interest-notifications', params={'mode': 'history', 'limit': 50}))['items']
    quality = [row for row in rows if row['event']['domain'] == 'tire_source_quality'
        and row['interest_id'] in {interest['id'], unsubscribed['id']}]
    assert len(quality) == 1 and quality[0]['interest_id'] == interest['id']
    notice = accepted(client.get('/v1/interest-notifications/' + quality[0]['id'], params={'mode': 'history'}))
    assert notice['event']['after']['accepted'] is False
    assert notice['event']['after']['baseline']['snapshot_id'] == baseline['provenance'][0]['snapshot_id']
    assert notice['match']['criteria']['source_quality_notifications'] is True
    settings = {key: interest[key] for key in ('name', 'enabled', 'conditions', 'metric_keys', 'changed_fields')}
    changed = accepted(client.put('/v1/interests/' + interest['id'], json={**settings,
        'expected_revision': interest['revision'], 'source_quality_notifications': False}))
    assert changed['revision'] == 2 and changed['source_quality_notifications'] is False
    assert accepted(client.get('/v1/interest-notifications/' + notice['id'], params={'mode': 'history'})) == notice
    current = accepted(client.get('/v1/interests/' + interest['id'], params={'mode': 'history'}))
    return {'path': '/v1/interest-notifications/' + notice['id'], 'value': notice,
        'interest_path': '/v1/interests/' + interest['id'], 'interest': current}


def stopped_material(client, app, url):
    entered, release = Event(), Event()
    calls, physical_puts = [], []
    app.state.material_policies = PolicyCatalog([canonical_policy(POLICY)])
    body = material_payload(client)
    original_put = app.state.database.object_store.put
    before = counts(app.state.database, (SourceMaterialOutcome, EvidenceDocument, EvidenceObject))

    async def fetch(policy):
        calls.append(policy['policy_id'])
        return obtained(policy)

    def held_put(raw):
        digest = original_put(raw)
        physical_puts.append(digest)
        entered.set()
        assert release.wait(20), 'Held synthetic put was not released'
        return digest

    with patch.object(app.state.material_transport, 'fetch', fetch), patch.object(
            app.state.database.object_store, 'put', held_put), ThreadPoolExecutor(max_workers=3) as pool:
        pending = pool.submit(client.post, '/v1/source-materials/captures', json=body)
        try:
            assert entered.wait(10), 'Synthetic put did not start'
            path = '/v1/source-materials/requests/' + body['idempotency_key']
            original = accepted(client.get(path, params={'mode': 'history'}))
            assert original['state'] == 'processing_unconfirmed'
            gate = Barrier(2)

            def stop(_index):
                other_app = create_app(url, FixtureRegistry())
                with TestClient(other_app, cookies=dict(client.cookies)) as other:
                    with other_app.state.database.engine.connect() as connection:
                        backend = connection.execute(text('SELECT pg_backend_pid()')).scalar_one()
                    gate.wait(timeout=10)
                    result = accepted(other.post(path + '/stop', json=stop_payload(original)))
                    return backend, result

            responses = list(pool.map(stop, range(2)))
            assert len({backend for backend, _result in responses}) == 2
            outcomes = [result for _backend, result in responses]
            assert sorted(result['effect'] for result in outcomes) == ['already_stopped', 'stopped']
            assert outcomes[0]['request'] == outcomes[1]['request']
            stopped = outcomes[0]['request']
            assert stopped['state'] == 'stopped_unconfirmed'
            assert all(stopped[key] is None for key in ('completed_at', 'failure_code', 'document', 'receipt'))
        finally:
            release.set()
        late = accepted(pending.result(timeout=10), 201)
        assert late['state'] == 'stopped_unconfirmed'
    app.state.material_policies = PolicyCatalog([])
    assert accepted(client.get(path, params={'mode': 'history'})) == stopped
    assert accepted(client.post('/v1/source-materials/captures', json=body), 201) == {**stopped, 'replayed': True}
    assert calls == [POLICY['policy_id']] and len(physical_puts) == 1
    assert counts(app.state.database, (SourceMaterialOutcome, EvidenceDocument, EvidenceObject)) == before
    return {'path': path, 'value': stopped, 'payload': body, 'stop_payload': stop_payload(original)}


def reject_statement(database, statement, values, sqlstate):
    with database.engine.connect() as connection:
        transaction = connection.begin()
        try:
            try:
                connection.execute(statement, values)
            except DBAPIError as error:
                assert error.orig.sqlstate == sqlstate
            else:
                raise AssertionError('PostgreSQL accepted a protected history mutation')
        finally:
            transaction.rollback()


def native_history_guards(database, page, quality, material):
    assert database.engine.url.get_backend_name() == 'postgresql'
    assert database.engine.url.host == '127.0.0.1'
    assert database.engine.url.database.startswith(('tire_verify_', 'tire_restore_'))
    page_notice = page['notices'][0]['value']['item']
    url_notice = page['notices'][1]['value']['item']
    rows = ((SourcePageChange, page_notice['event']['id']), (SourcePageNotification, page_notice['id']),
        (SourcePageUrlMove, url_notice['event']['id']), (SourcePageUrlMoveNotification, url_notice['id']),
        (SourceMaterialStop, material['value']['request_id']))
    for model, identity in rows:
        table = model.__table__
        key = next(iter(table.primary_key)).name
        values = {'identity': identity, 'fingerprint': 'f' * 64}
        reject_statement(database, text(f'UPDATE {table.name} SET fingerprint=:fingerprint WHERE {key}=:identity'), values, 'P0001')
        reject_statement(database, text(f'DELETE FROM {table.name} WHERE {key}=:identity'), values, 'P0001')
        reject_statement(database, text(f'TRUNCATE TABLE {table.name} CASCADE'), {}, 'P0001')
        with database.engine.connect() as connection:
            row = dict(connection.execute(select(table).where(table.c[key] == identity)).mappings().one())
        if key == 'id':
            row['id'] = str(uuid4())
        reject_statement(database, insert(table).values(**row), {}, '23505')
    with database.engine.connect() as connection:
        row = dict(connection.execute(select(InterestNotification.__table__).where(
            InterestNotification.id == quality['value']['id'])).mappings().one())
    row['id'] = str(uuid4())
    reject_statement(database, insert(InterestNotification).values(**row), {}, '23505')


def assert_recent_history_checkpoint(url, checkpoint):
    registry = FixtureRegistry()
    app = create_app(url, registry)

    async def forbidden(_policy):
        raise AssertionError('Historical material reads must not acquire a source')

    app.state.material_transport.fetch = forbidden
    with TestClient(app, cookies=checkpoint['cookies']) as client:
        for item in [*checkpoint['page']['notices'], checkpoint['quality']]:
            assert accepted(client.get(item['path'], params={'mode': 'history'})) == item['value']
        quality = checkpoint['quality']
        current = accepted(client.get(quality['interest_path'], params={'mode': 'history'}))
        assert current == quality['interest']
        material = checkpoint['material']
        assert accepted(client.get(material['path'], params={'mode': 'history'})) == material['value']
        assert accepted(client.post(material['path'] + '/stop', json=material['stop_payload'])) == {
            'effect': 'already_stopped', 'request': material['value']}
        assert accepted(client.post('/v1/source-materials/captures', json=material['payload']), 201) == {
            **material['value'], 'replayed': True}
        assert not registry.calls
        native_history_guards(app.state.database, checkpoint['page'], quality, material)


def verify_recent_history_persistence(url, *, authenticate):
    target = make_url(url)
    assert target.get_backend_name() == 'postgresql' and target.host == '127.0.0.1'
    assert target.database.startswith('tire_verify_')
    registry = FixtureRegistry()
    app = create_app(url, registry)
    variant = {**deepcopy(VARIANT), 'brand': 'PG History Brand', 'model': QUERY['model'],
        'manufacturer_product_code': 'PG-HISTORY-ONE',
        'facts': {**{f'field_{index}': index for index in range(8)}, 'utqg_treadwear': 300}}
    with TestClient(app) as client:
        authenticate(client)
        settings = {'name': 'PG quality history', 'enabled': True,
            'conditions': [{'kind': 'brand', 'values': [variant['brand']]}],
            'metric_keys': [], 'changed_fields': []}
        opted = accepted(client.post('/v1/interests', json={**settings, 'source_quality_notifications': True}), 201)
        legacy = accepted(client.post('/v1/interests', json={**settings, 'name': 'PG legacy quality disabled'}), 201)
        assert legacy['source_quality_notifications'] is False
        page = page_and_url_history(client, registry, app.state.database, variant)
        quality = quality_history(client, registry, app.state.database, opted, legacy, page['baseline'])
        material = stopped_material(client, app, url)
        checkpoint = {'cookies': dict(client.cookies), 'page': page, 'quality': quality, 'material': material}
    assert_recent_history_checkpoint(url, checkpoint)
    return checkpoint
