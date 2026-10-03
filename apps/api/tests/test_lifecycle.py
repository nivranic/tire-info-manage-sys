"""Whole-entity withdrawals preserve official observations and require explicit recovery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from tire_api.db import Database, FactVersion, Snapshot, TireVariant, UserSession, VariantLifecycleEvent, utcnow
from tire_api.lifecycle import LifecycleRequest, append_lifecycle_event
from tire_api.main import create_app
from test_core import FixtureRegistry, QUERY, VARIANT, count, grant, live, setup, success


def request_for(result, **extra):
    return {'action': 'revoke', 'expected_revision': 0, 'operator': '合成验收',
            'reason': '仅测试整实体撤销流程，不对真实产品作判断',
            'evidence': [{'snapshot_id': result['provenance'][0]['snapshot_id'], 'locator': '产品代码 FIX-001 所在测试规格'}], **extra}


def test_withdraw_restore_append_history_preserve_raw_and_exclude_comparison(setup):
    client, registry, database = setup
    original = live(client).json()
    variant = original['variants'][0]
    vid = variant['id']
    path = f'/v1/tire-variants/{vid}'
    assert client.get(path + '/lifecycle').status_code == 422
    before = client.get(path + '/lifecycle?mode=history').json()
    assert before['lifecycle']['state'] == 'active' and before['history'] == []
    body = request_for(original)
    withdrawn = client.post(path + '/lifecycle-events', json=body)
    assert withdrawn.status_code == 201
    state = withdrawn.json()
    assert state['lifecycle']['state'] == 'revoked' and state['history'][0]['before_state'] == 'active'
    assert state['history'][0]['after_state'] == 'revoked'
    raw = client.get('/v1/evidence/' + original['provenance'][0]['snapshot_id']).json()
    assert raw['body'] == 'fixture-body-v1' and raw['raw_hash'] == original['provenance'][0]['raw_hash']
    compared = client.post('/v1/compare', json={'variant_ids': [vid]}).json()
    assert compared['variants'] == [] and compared['conflicts'] == [] and compared['provenance'] == []
    assert compared['excluded_variants'][0]['lifecycle']['state'] == 'revoked'
    assert 'facts' not in compared['excluded_variants'][0]
    history = client.get(path + '?mode=history').json()
    assert history['facts'] == variant['facts'] and history['lifecycle']['state'] == 'revoked'
    client.post('/v1/watchlists', json={'variant_id': vid})
    assert client.get('/v1/watchlists').json()['items'][0]['variant']['lifecycle']['state'] == 'revoked'
    assert client.post(path + '/lifecycle-events', json=body).status_code == 409
    assert client.post(path + '/lifecycle-events', json={**body, 'expected_revision': 1}).status_code == 409
    restored = client.post(path + '/lifecycle-events', json={**body, 'action': 'restore', 'expected_revision': 1}).json()
    assert restored['lifecycle']['state'] == 'active' and restored['lifecycle']['revision'] == 2
    assert len(restored['history']) == 2 and restored['history'][1]['after_state'] == 'revoked'
    assert len(client.post('/v1/compare', json={'variant_ids': [vid]}).json()['variants']) == 1
    assert count(database, TireVariant) == count(database, FactVersion) == count(database, Snapshot) == 1
    assert count(database, VariantLifecycleEvent) == 2
    with database.sessions() as db:
        row = db.scalar(select(VariantLifecycleEvent))
        row.reason = 'overwrite'
        with pytest.raises(ValueError, match='只能追加'): db.commit()
        db.rollback()
        db.delete(db.scalar(select(VariantLifecycleEvent)))
        with pytest.raises(ValueError, match='只能追加'): db.commit()


def test_live_304_and_fallback_cannot_revive_a_withdrawn_entity(setup):
    client, registry, database = setup
    first = live(client).json()
    vid = first['variants'][0]['id']
    assert client.post(f'/v1/tire-variants/{vid}/lifecycle-events', json=request_for(first)).status_code == 201
    second = live(client).json()
    assert second['data_state'] == 'live' and second['variants'][0]['lifecycle']['state'] == 'revoked'
    registry.result = {'status': 'not_modified', 'url': first['provenance'][0]['source_url'],
                       'parser_version': 'fixture@1', 'etag': '"fixture-etag"'}
    verified = live(client).json()
    assert verified['data_state'] == 'live_verified_304' and verified['variants'][0]['lifecycle']['state'] == 'revoked'
    registry.result = {'status': 'unavailable', 'reason': 'synthetic_outage'}
    statements = []
    def record(_conn, _cursor, sql, *_): statements.append(sql.lower())
    event.listen(database.engine, 'before_cursor_execute', record)
    try:
        failure = live(client).json()
    finally:
        event.remove(database.engine, 'before_cursor_execute', record)
    assert failure['variants'] == []
    assert all('variant_lifecycle_events' not in sql for sql in statements)
    consent = grant(client, failure['query_id']).json()
    offline = live(client, {**QUERY, 'consent_id': consent['id']}).json()
    assert offline['variants'][0]['lifecycle']['state'] == 'revoked'
    registry.result = success('new official body', variants=[{**VARIANT, 'facts': {'utqg_treadwear': 400}}])
    updated = live(client).json()
    assert updated['variants'][0]['facts']['utqg_treadwear'] == 400
    assert updated['variants'][0]['lifecycle']['state'] == 'revoked'
    assert count(database, VariantLifecycleEvent) == 1


def test_withdrawal_is_exact_identity_scoped_and_cannot_cite_another_sku(setup):
    client, registry, database = setup
    first = live(client).json()
    original = first['variants'][0]['id']
    registry.result = success('another sku', variants=[{**VARIANT, 'manufacturer_product_code': 'FIX-002'}])
    other = live(client, source='fixture-two').json()
    vid = other['variants'][0]['id']
    assert vid != original
    assert client.post(f'/v1/tire-variants/{vid}/lifecycle-events', json=request_for(first)).status_code == 422
    assert client.post(f'/v1/tire-variants/{original}/lifecycle-events', json=request_for(first)).status_code == 201
    compared = client.post('/v1/compare', json={'variant_ids': [original, vid], 'include_manual': True}).json()
    assert [row['id'] for row in compared['variants']] == [vid]
    assert compared['excluded_variants'][0]['id'] == original


@pytest.mark.parametrize('change', [
    {'action': 'delete'}, {'operator': '  '}, {'reason': '    x    '}, {'expected_revision': True},
    {'evidence': []}, {'evidence': [{'snapshot_id': 'missing', 'locator': 'absent evidence'}]},
    {'evidence': [{'snapshot_id': 'missing', 'locator': '   '}]},
])
def test_invalid_state_change_creates_no_event(setup, change):
    client, _, database = setup
    first = live(client).json()
    vid = first['variants'][0]['id']
    result = client.post(f'/v1/tire-variants/{vid}/lifecycle-events', json=request_for(first, **change))
    assert result.status_code == 422
    assert count(database, VariantLifecycleEvent) == 0


def test_concurrent_state_changes_have_one_winner(tmp_path):
    url = f"sqlite:///{(tmp_path/'lifecycle-race.db').as_posix()}"
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        first = live(client).json()
    database = Database(url)
    with database.sessions() as db:
        db.add(UserSession(id='curator', expires_at=utcnow() + timedelta(hours=1)))
        db.commit()
    barrier = Barrier(2)
    def change(_):
        with database.sessions() as db:
            barrier.wait(timeout=5)
            try:
                return append_lifecycle_event(db, first['variants'][0]['id'], LifecycleRequest(**request_for(first)), 'curator')['lifecycle']['revision']
            except HTTPException as error:
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, [1, 2])) == [1, 409]
    assert count(database, VariantLifecycleEvent) == 1
    database.close()
