"""Saved comparisons freeze what was reviewed; preferences never rewrite evidence."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from tire_api.db import DrivingPreferenceRevision, FactVersion, SavedComparison, SavedComparisonRevision, Snapshot
from tire_api.main import create_app
from test_core import FixtureRegistry, QUERY, VARIANT, count, live, setup, success
from test_lifecycle import request_for

WEIGHTS = {'dry': 20, 'wet': 25, 'quiet': 20, 'comfort': 10, 'wear': 15, 'energy': 5, 'appearance': 5}


def preview(client, vid, manual=False):
    response = client.post('/v1/compare', json={'variant_ids': [vid], 'include_manual': manual})
    assert response.status_code == 200, response.text
    return response.json()


def save(client, compared, **changes):
    return client.post('/v1/saved-comparisons', json={
        'variant_ids': compared['variant_ids'], 'include_manual': compared['include_manual'],
        'expected_fingerprint': compared['fingerprint'], 'title': '合成证据对照', 'notes': '仅流程测试', **changes})


@pytest.mark.parametrize('state', ['legacy_unbound', 'legacy_needs_review'])
def test_direct_save_cannot_bypass_identity_gate_and_old_saved_content_remains_readable(setup, state):
    from tire_api.domain import digest
    from tire_api.service import provenance
    from test_identity_migration import apply_current, seed_legacy
    client, _registry, database = setup
    client.get('/health')
    actor = client.cookies['tire_local_session']
    with database.sessions() as db:
        seeded = seed_legacy(db, namespace=None, session_id=actor)
        if state == 'legacy_needs_review':
            apply_current(db)
        source = provenance(db.get(Snapshot, seeded['snapshot_id']))
    variant_id = seeded['variant_id']
    history = client.get(f'/v1/tire-variants/{variant_id}?mode=history').json()
    assert history['identity_contract']['state'] == state
    # The public history and provenance are sufficient to reproduce the stable
    # content fingerprint. It must not act as authorization to bypass a gate.
    compared = {'data_state': 'local_snapshot', 'variant_ids': [variant_id], 'include_manual': False,
        'variants': [history], 'excluded_variants': [], 'provenance': [source], 'conflicts': [],
        'notice': '历史精确 SKU 比较；不计算跨测试事件性能排名。'}
    compared['fingerprint'] = digest(compared)
    frozen = deepcopy(compared)
    frozen.pop('fingerprint')
    frozen['variants'][0].pop('identity_contract')
    frozen['fingerprint'] = digest(frozen)
    with database.sessions() as db:
        old = SavedComparison(payload=frozen, fingerprint=frozen['fingerprint'], variant_count=1,
                              include_manual=False, actor_session_id=actor)
        db.add(old)
        db.flush()
        db.add(SavedComparisonRevision(comparison_id=old.id, revision=1, title='Synthetic pre-v2 saved history',
            notes='Frozen legacy reference; not new namespace approval', archived=False, operation='save', actor_session_id=actor))
        db.commit()
        old_id = old.id
    detail = client.get(f'/v1/saved-comparisons/{old_id}?mode=history')
    assert detail.status_code == 200 and detail.json()['comparison'] == frozen
    denied = client.post('/v1/compare', json={'variant_ids': [variant_id]})
    assert denied.status_code == 409 and denied.json()['detail']['code'] == 'identity_contract_review_required'
    response = save(client, compared)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'identity_contract_review_required'
    assert count(database, SavedComparison) == count(database, SavedComparisonRevision) == 1
    assert client.get(f'/v1/saved-comparisons/{old_id}?mode=history').json()['comparison'] == frozen


def test_saved_comparison_does_not_drift_after_source_or_lifecycle_changes(setup):
    client, registry, database = setup
    initial = live(client).json()
    vid = initial['variants'][0]['id']
    compared = preview(client, vid)
    assert preview(client, vid)['fingerprint'] == compared['fingerprint']
    response = save(client, compared)
    assert response.status_code == 201
    record = response.json()
    registry.result = success('new source content', [{**VARIANT, 'facts': {'utqg_treadwear': 420}}])
    live(client)
    assert preview(client, vid)['variants'][0]['facts']['utqg_treadwear'] == 420
    assert save(client, compared).status_code == 409
    assert count(database, SavedComparison) == 1
    assert client.post(f'/v1/tire-variants/{vid}/lifecycle-events', json=request_for(initial)).status_code == 201
    assert client.get('/v1/saved-comparisons/' + record['id']).status_code == 422
    detail = client.get(f"/v1/saved-comparisons/{record['id']}?mode=history").json()
    assert detail['comparison'] == compared
    assert detail['comparison']['variants'][0]['facts']['utqg_treadwear'] == 300
    assert detail['comparison']['variants'][0]['lifecycle']['state'] == 'active'
    assert detail['current_lifecycle'][vid]['state'] == 'revoked'
    assert preview(client, vid)['variants'] == []
    assert count(database, Snapshot) == count(database, FactVersion) == 2
    with database.sessions() as db:
        saved = db.get(SavedComparison, record['id'])
        saved.payload = {'replaced': True}
        with pytest.raises(ValueError, match='只能追加'): db.commit()
        db.rollback()
        db.delete(db.get(SavedComparison, record['id']))
        with pytest.raises(ValueError, match='只能追加'): db.commit()


def test_manual_revisions_are_frozen_only_when_explicitly_included(setup):
    client, registry, database = setup
    initial = live(client).json()
    vid = initial['variants'][0]['id']
    view = client.get(f'/v1/tire-variants/{vid}/fact-review?source_id=fixture&mode=history').json()
    request = {'source_id': 'fixture', 'base_fact_id': view['base_fact_id'], 'expected_revision': 0,
               'field': 'utqg_treadwear', 'action': 'manual_override', 'value': 400, 'operator': '合成核验',
               'reason': '只测试人工修订，不改官方参数', 'evidence': request_for(initial)['evidence']}
    assert client.post(f'/v1/tire-variants/{vid}/fact-revisions', json=request).status_code == 201
    included = preview(client, vid, True)
    record = save(client, included).json()
    assert included['variants'][0]['effective_facts']['utqg_treadwear'] == 400
    assert 'effective_facts' not in preview(client, vid)['variants'][0]
    assert client.post(f'/v1/tire-variants/{vid}/fact-revisions', json={**request, 'expected_revision': 1, 'value': 500}).status_code == 201
    assert save(client, included).status_code == 409
    frozen = client.get(f"/v1/saved-comparisons/{record['id']}?mode=history").json()['comparison']
    assert frozen['variants'][0]['effective_facts']['utqg_treadwear'] == 400
    assert frozen['variants'][0]['curation']['fields']['utqg_treadwear']['revision'] == 1


def test_saved_metadata_and_archive_history_cannot_replace_comparison(setup):
    client, _, database = setup
    compared = preview(client, live(client).json()['variants'][0]['id'])
    record = save(client, compared).json()
    path = '/v1/saved-comparisons/' + record['id']
    edit = {'expected_revision': 1, 'title': '新标题 <script>ignored</script>', 'notes': '新备注'}
    assert client.put(path, json={**edit, 'comparison': {'fake': True}}).status_code == 422
    assert client.put(path, json=edit).json()['revision'] == 2
    assert client.put(path, json=edit).status_code == 409
    assert client.post(path + '/state', json={'expected_revision': 2, 'action': 'archive'}).status_code == 200
    assert client.get('/v1/saved-comparisons').json()['items'] == []
    assert client.get('/v1/saved-comparisons?archived=true').json()['items'][0]['id'] == record['id']
    assert client.post(path + '/state', json={'expected_revision': 3, 'action': 'restore'}).json()['revision'] == 4
    detail = client.get(path + '?mode=history').json()
    assert detail['comparison'] == compared and len(detail['history']) == 4
    assert detail['history'][-1]['title'] == '合成证据对照'
    assert count(database, SavedComparisonRevision) == 4


def test_listing_reads_metadata_only_and_no_automatic_fetch(setup):
    client, registry, database = setup
    compared = preview(client, live(client).json()['variants'][0]['id'])
    save(client, compared)
    calls = len(registry.calls)
    statements = []
    def record(_conn, _cursor, sql, *_):
        if sql.lstrip().upper().startswith('SELECT'): statements.append(sql.lower())
    event.listen(database.engine, 'before_cursor_execute', record)
    try:
        rows = client.get('/v1/saved-comparisons').json()
    finally:
        event.remove(database.engine, 'before_cursor_execute', record)
    assert rows['total'] == 1 and 'comparison' not in rows['items'][0]
    assert client.get('/v1/saved-comparisons?offset=1').json()['items'] == []
    assert any('saved_comparisons' in sql for sql in statements)
    assert all('payload' not in sql and 'fact_versions' not in sql and 'snapshots' not in sql for sql in statements)
    assert len(registry.calls) == calls


def test_all_withdrawn_cannot_be_saved_and_arbitrary_payload_is_rejected(setup):
    client, _, database = setup
    initial = live(client).json()
    vid = initial['variants'][0]['id']
    compared = preview(client, vid)
    assert save(client, compared, payload={'facts': 'forged'}).status_code == 422
    client.post(f'/v1/tire-variants/{vid}/lifecycle-events', json=request_for(initial))
    assert save(client, preview(client, vid)).status_code == 422
    assert count(database, SavedComparison) == 0


@pytest.mark.parametrize('text', ['bad\x00description', '\ud800', 'bad\x07description'])
def test_invalid_description_text_never_reaches_database(setup, text):
    client, _, database = setup
    compared = preview(client, live(client).json()['variants'][0]['id'])
    payload = {'variant_ids': compared['variant_ids'], 'expected_fingerprint': compared['fingerprint'], 'title': '合成测试', 'notes': text}
    response = client.post('/v1/saved-comparisons', content=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    assert response.status_code == 422 and count(database, SavedComparison) == 0


def test_preferences_are_explicit_append_only_and_do_not_change_comparison(setup):
    client, registry, database = setup
    before = client.get('/v1/driving-preferences').json()
    assert before['revision'] == 0 and before['weights'] is None and before['history'] == []
    initial = live(client).json()
    compared = preview(client, initial['variants'][0]['id'])
    result = client.put('/v1/driving-preferences', json={'expected_revision': 0, 'weights': WEIGHTS}).json()
    assert result['revision'] == 1 and result['weights'] == WEIGHTS
    assert preview(client, initial['variants'][0]['id']) == compared
    assert client.put('/v1/driving-preferences', json={'expected_revision': 0, 'weights': WEIGHTS}).status_code == 409
    assert client.put('/v1/driving-preferences', json={'expected_revision': 1, 'weights': WEIGHTS}).json()['revision'] == 1
    cleared = client.post('/v1/driving-preferences/clear', json={'expected_revision': 1}).json()
    assert cleared['revision'] == 2 and cleared['weights'] is None
    assert cleared['history'][1]['weights'] == WEIGHTS
    assert len(registry.calls) == 1 and count(database, DrivingPreferenceRevision) == 2
    with database.sessions() as db:
        row = db.scalar(select(DrivingPreferenceRevision))
        row.weights = {'dry': 100}
        with pytest.raises(ValueError, match='只能追加'): db.commit()


@pytest.mark.parametrize('weights', [
    {**WEIGHTS, 'dry': True}, {**WEIGHTS, 'dry': 20.0}, {**WEIGHTS, 'dry': '20'},
    {**WEIGHTS, 'dry': -1}, {**WEIGHTS, 'dry': 101}, {**WEIGHTS, 'wet': 24},
    {**WEIGHTS, 'unknown_metric': 0}, {'dry': 100},
])
def test_invalid_weights_are_not_silently_normalized(setup, weights):
    client, _, database = setup
    assert client.put('/v1/driving-preferences', json={'expected_revision': 0, 'weights': weights}).status_code == 422
    assert count(database, DrivingPreferenceRevision) == 0


def test_workspace_research_persists_across_sessions_and_restart(tmp_path):
    url = f"sqlite:///{(tmp_path/'research.db').as_posix()}"
    with TestClient(create_app(url, FixtureRegistry())) as client:
        compared = preview(client, live(client).json()['variants'][0]['id'])
        saved = save(client, compared).json()
        assert client.put('/v1/driving-preferences', json={'expected_revision': 0, 'weights': WEIGHTS}).status_code == 200
    with TestClient(create_app(url, FixtureRegistry())) as restarted:
        assert restarted.get('/v1/saved-comparisons').json()['items'][0]['id'] == saved['id']
        assert restarted.get('/v1/driving-preferences').json()['weights'] == WEIGHTS


def test_concurrent_preference_updates_have_one_winner(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path/'pref-race.db').as_posix()}", FixtureRegistry())
    with TestClient(app) as client:
        client.get('/health')
        cookies = dict(client.cookies)
        barrier = Barrier(2)
        def update(weights):
            with TestClient(app, cookies=cookies) as actor:
                barrier.wait(timeout=5)
                return actor.put('/v1/driving-preferences', json={'expected_revision': 0, 'weights': weights}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(update, [WEIGHTS, {**WEIGHTS, 'dry': 25, 'wet': 20}])) == [200, 409]
