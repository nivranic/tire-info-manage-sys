"""Synthetic source evidence for field defaults; no Parser, model or network calls."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select

from tire_api.db import FactVersion, Snapshot, TireVariant, Verification
from tire_api.main import create_app
from test_core import FixtureRegistry, QUERY, VARIANT, live, success


class FieldSources(FixtureRegistry):
    def sources(self):
        return [{**row, 'source_class': 'manufacturer_official' if row['id'] == 'fixture' else 'regulatory'}
                for row in super().sources()]


@pytest.fixture
def setup():
    registry = FieldSources()
    app = create_app('sqlite://', registry)
    with TestClient(app) as client:
        yield client, registry, app.state.database


def known_variant(**facts):
    return {**deepcopy(VARIANT), 'facts': {'product_code_type': 'MSPN', 'utqg_treadwear': 300,
        'eu_wet_grip': 'A', 'evidence_spans': {'facts.utqg_treadwear': '$.sku.utqg',
            'facts.eu_wet_grip': '$.sku.label', 'acoustic_technology': '$.sku.technology'}, **facts}}


def seed_sources(client, registry):
    registry.result = success('synthetic official evidence', [known_variant()])
    first = live(client).json()
    registry.result = success('synthetic regulatory evidence', [known_variant(utqg_treadwear=500, eu_wet_grip='B')])
    second = live(client, source='fixture-two').json()
    assert first['variants'][0]['id'] == second['variants'][0]['id']
    return first, second


def fields(resolution):
    return {item['field']: item for item in resolution['fields']}


def test_history_defaults_choose_per_field_without_rewriting_source_row(setup):
    client, registry, _ = setup
    first, second = seed_sources(client, registry)
    variant_id = first['variants'][0]['id']
    response = client.get(f'/v1/tire-variants/{variant_id}/field-resolution?mode=history')
    assert response.status_code == 200
    resolved = fields(response.json())
    assert resolved['utqg_treadwear']['default_value'] == 300
    assert resolved['eu_wet_grip']['default_value'] == 'B'
    assert resolved['utqg_treadwear']['state'] == resolved['eu_wet_grip']['state'] == 'conflict_preferred'
    compared = client.post('/v1/compare', json={'variant_ids': [variant_id]}).json()
    row, = compared['variants']
    assert row['facts']['utqg_treadwear'] == 500
    assert fields(row['field_resolution'])['utqg_treadwear']['default_value'] == 300
    assert {item['field'] for item in compared['conflicts']} == {'utqg_treadwear', 'eu_wet_grip'}
    assert second['variants'][0]['facts']['utqg_treadwear'] == 500


def test_live_resolution_contains_only_the_requested_source(setup):
    client, registry, _ = setup
    _first, second = seed_sources(client, registry)
    row, = second['variants']
    assert 'field_resolution' in row
    resolved = fields(row['field_resolution'])
    assert resolved['utqg_treadwear']['default_value'] == 500
    assert {item['source_id'] for item in resolved['utqg_treadwear']['candidates']} == {'fixture-two'}
    assert second['conflicts'] == []


def test_historical_identity_contract_comes_from_recorded_snapshot(setup):
    from test_identity_migration import apply_current, seed_legacy
    from tire_api.identity_contract import schema_version
    client, registry, database = setup
    registry.result = success('synthetic v2 recorded identity contract', [known_variant()])
    current = live(client).json()['variants'][0]
    with database.sessions() as db:
        old = seed_legacy(db, namespace='CAI')
        apply_current(db)
        db.commit()
    compared = client.post('/v1/compare', json={'variant_ids': [current['id'], old['variant_id']]}).json()
    rows = {row['id']: row for row in compared['variants']}
    assert rows[current['id']]['identity_contract_version'] == schema_version()
    assert rows[old['variant_id']]['identity_contract_version'] is None
    assert rows[old['variant_id']]['snapshot_id'] == old['snapshot_id']
    with database.sessions() as db:
        assert db.get(Snapshot, old['snapshot_id']).identity_contract_version is None


def test_catalog_and_conflict_list_are_bounded_explicit_history_reads(setup):
    client, registry, database = setup
    seed_sources(client, registry)
    before = {}
    with database.sessions() as db:
        before = {model.__name__: db.scalar(select(func.count()).select_from(model))
                  for model in (TireVariant, FactVersion, Snapshot, Verification)}
    assert client.get('/v1/field-policies').status_code == 200
    assert client.get('/v1/field-conflicts').status_code == 422
    result = client.get('/v1/field-conflicts?mode=history&field=utqg_treadwear&limit=1').json()
    assert result['total'] == 1 and result['limit'] == 1 and len(result['items']) == 1
    assert client.get('/v1/field-conflicts?mode=history&offset=1&limit=1').json()['items'] == []
    assert client.get('/v1/field-conflicts?mode=history&limit=101').status_code == 422
    with database.sessions() as db:
        assert before == {model.__name__: db.scalar(select(func.count()).select_from(model))
                          for model in (TireVariant, FactVersion, Snapshot, Verification)}


def test_new_page_with_same_facts_uses_new_snapshot_and_old_fact_reference(setup):
    client, registry, database = setup
    registry.result = success('synthetic before locator change', [known_variant()])
    first = live(client).json()
    variant_id = first['variants'][0]['id']
    with database.sessions() as db:
        original_fact = db.scalar(select(FactVersion))
        fact_id, original_snapshot = original_fact.id, original_fact.snapshot_id
    registry.result = success('synthetic after locator change', [known_variant(evidence_spans={
        'facts.utqg_treadwear': '$.changedLayout.sku.utqg'})])
    second = live(client).json()
    candidate, = fields(second['variants'][0]['field_resolution'])['utqg_treadwear']['candidates']
    assert candidate['snapshot_id'] != original_snapshot
    assert candidate['fact_version_id'] == fact_id and candidate['eligible'] is True
    assert candidate['evidence_locator'] == '$.changedLayout.sku.utqg'
    assert fields(client.get(f'/v1/tire-variants/{variant_id}/field-resolution?mode=history').json())['utqg_treadwear']['has_default']
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(FactVersion)) == 1


def test_verified_304_does_not_refresh_content_time_or_default(setup, monkeypatch):
    from datetime import timedelta
    from tire_api.db import utcnow
    from tire_api import service
    client, registry, _ = setup
    registry.sources = lambda: [{**row, 'source_class': 'manufacturer_official'} for row in FixtureRegistry.sources(registry)]
    moment = utcnow()
    monkeypatch.setattr(service, 'utcnow', lambda: moment)
    registry.result = success('synthetic older official content', [known_variant(utqg_treadwear=300)])
    first = live(client).json()
    variant_id = first['variants'][0]['id']
    moment += timedelta(hours=1)
    registry.result = success('synthetic newer official content', [known_variant(utqg_treadwear=400)])
    live(client, source='fixture-two')
    moment += timedelta(hours=1)
    registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product',
        'etag': '"fixture-etag"', 'parser_version': 'fixture@1'}
    result = live(client).json()
    assert result['data_state'] == 'live_verified_304'
    resolved = fields(client.get(f'/v1/tire-variants/{variant_id}/field-resolution?mode=history').json())['utqg_treadwear']
    assert resolved['default_value'] == 400
    old = next(item for item in resolved['candidates'] if item['source_id'] == 'fixture')
    assert old['verified_at'] > old['observed_at']
    assert old['dimensions']['time']['verification_used_for_rank'] is False


def test_latest_catalog_removal_does_not_resurrect_fact_version(setup):
    import hashlib
    from tire_api.db import QueryRun, uid, utcnow
    from tire_api.domain import IDENTITY_CONTRACT_VERSION
    client, registry, database = setup
    first, _ = seed_sources(client, registry)
    variant_id = first['variants'][0]['id']
    with database.sessions() as db:
        run = db.scalar(select(QueryRun).where(QueryRun.source_id == 'fixture'))
        raw = 'synthetic accepted empty catalog'
        snapshot = Snapshot(id=uid(), source_id='fixture', query_key=run.query_key,
            source_url='https://fixture.example/tires/product', raw_hash=hashlib.sha256(raw.encode()).hexdigest(),
            body=raw, content_type='text/html', parser_version='fixture@1', parsed_variants=[],
            identity_contract_version=IDENTITY_CONTRACT_VERSION)
        db.add(snapshot); db.flush()
        db.add(Verification(snapshot_id=snapshot.id, query_id=run.id, source_id='fixture',
            query_key=run.query_key, status='ok', verified_at=utcnow()))
        db.commit()
    result = fields(client.get(f'/v1/tire-variants/{variant_id}/field-resolution?mode=history').json())['utqg_treadwear']
    assert result['state'] == 'uncontested' and result['default_value'] == 500
    assert {row['source_id'] for row in result['candidates']} == {'fixture-two'}


def test_same_source_conflict_preserves_both_values_without_default(setup):
    client, registry, _ = setup
    registry.result = success('synthetic contradictory declaration', [known_variant(utqg_traction=None,
        source_field_conflicts=[{'field': 'utqg_traction', 'values': [
            {'source_field': 'left', 'value': 'A'}, {'source_field': 'right', 'value': 'AA'}]}])])
    row, = live(client).json()['variants']
    resolved = fields(row['field_resolution'])['utqg_traction']
    assert resolved['state'] == 'conflict_tied' and resolved['has_default'] is False
    assert {item['value'] for item in resolved['candidates']} == {None, 'A', 'AA'}
    assert all(item['source_conflicted'] for item in resolved['candidates'])


def test_legacy_unbound_history_has_no_default_and_read_does_not_bind(setup):
    from test_identity_migration import seed_legacy
    from tire_api.identity_contract_models import VariantIdentityBinding
    client, _, database = setup
    with database.sessions() as db:
        old = seed_legacy(db, namespace='CAI')
    response = client.get(f"/v1/tire-variants/{old['variant_id']}/field-resolution?mode=history")
    assert response.status_code == 200
    assert all(not item['has_default'] for item in response.json()['fields'])
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(VariantIdentityBinding)) == 0


def test_valid_explicit_merge_keeps_only_selected_original_evidence(setup):
    from test_identity_resolution import decision, post
    client, registry, _ = setup
    left = {**known_variant(), 'hl': None}
    right = {**known_variant(utqg_treadwear=500), 'hl': None}
    registry.result = success('synthetic merge source left', [left])
    first = live(client).json()
    registry.result = success('synthetic merge source right', [right])
    second = live(client, source='fixture-two').json()
    a, b = first['variants'][0]['id'], second['variants'][0]['id']
    assert a != b
    snapshots = [first['provenance'][0]['snapshot_id'], second['provenance'][0]['snapshot_id']]
    accepted = post(client, a, decision(client, a, b, snapshots, 'merge'))
    assert accepted.status_code == 201
    event_id = accepted.json()['event']['id']
    result = client.post('/v1/compare', json={'variant_ids': [a, b], 'resolve_identities': True}).json()
    row, = result['variants']
    resolved = fields(row['field_resolution'])['utqg_treadwear']
    assert row['id'] == b and row['facts']['utqg_treadwear'] == 500
    assert resolved['default_value'] == 300
    assert {item['variant_id'] for item in resolved['candidates']} == {a, b}
    merged = next(item for item in resolved['candidates'] if item['variant_id'] == a)
    assert merged['identity_match'] == 'reviewed_merge' and merged['equivalence_event_id'] == event_id
    alone = client.post('/v1/compare', json={'variant_ids': [b], 'resolve_identities': True}).json()['variants'][0]
    assert {item['variant_id'] for item in fields(alone['field_resolution'])['utqg_treadwear']['candidates']} == {b}


def test_correction_does_not_collect_original_facts_and_saved_result_is_frozen(setup):
    from test_identity_resolution import seed_pair, decision, post
    client, registry, _ = setup
    (a, b), snapshot, _ = seed_pair(client, registry)
    assert post(client, a, decision(client, a, b, [snapshot], 'correct')).status_code == 201
    selection = {'variant_ids': [a, b], 'resolve_identities': True}
    result = client.post('/v1/compare', json=selection).json()
    candidate_ids = {item['variant_id'] for item in fields(result['variants'][0]['field_resolution'])['utqg_treadwear']['candidates']}
    assert candidate_ids == {b}
    saved = client.post('/v1/saved-comparisons', json={**selection, 'expected_fingerprint': result['fingerprint'],
        'title': 'synthetic frozen field policy', 'notes': ''})
    assert saved.status_code == 201
    assert post(client, a, decision(client, a, None, [snapshot], 'clear')).status_code == 201
    frozen = client.get(f"/v1/saved-comparisons/{saved.json()['id']}?mode=history").json()
    assert frozen['comparison'] == result


def test_field_history_checks_raw_once_without_writing_projection(setup):
    client, registry, database = setup
    first, _ = seed_sources(client, registry)
    statements = []
    def capture(_connection, _cursor, sql, _params, _context, _many):
        statements.append(sql.lower())
    event.listen(database.engine, 'before_cursor_execute', capture)
    try:
        response = client.get(f"/v1/tire-variants/{first['variants'][0]['id']}/field-resolution?mode=history")
        assert response.status_code == 200
    finally:
        event.remove(database.engine, 'before_cursor_execute', capture)
    assert sum('snapshots.body' in sql for sql in statements) == 1
    assert not any(sql.lstrip().startswith(('insert ', 'update ', 'delete ')) for sql in statements)


def test_missing_null_and_known_remain_distinct_without_false_conflicts(setup):
    client, registry, _ = setup
    first_value = known_variant()
    first_value['facts'].pop('utqg_treadwear')
    registry.result = success('synthetic missing wear', [first_value])
    first = live(client).json()
    registry.result = success('synthetic null wear', [known_variant(utqg_treadwear=None)])
    live(client, source='fixture-two')
    path = f"/v1/tire-variants/{first['variants'][0]['id']}/field-resolution?mode=history"
    wear = fields(client.get(path).json())['utqg_treadwear']
    assert wear['state'] == 'unknown'
    assert {(item['present'], item['value']) for item in wear['candidates']} == {(False, None), (True, None)}
    registry.result = success('synthetic known wear', [known_variant(utqg_treadwear=0)])
    live(client, source='fixture-two')
    wear = fields(client.get(path).json())['utqg_treadwear']
    assert wear['state'] == 'uncontested' and wear['default_value'] == 0
    assert any(item['present'] is False for item in wear['candidates'])


@pytest.mark.parametrize('damage', ['body', 'query'])
def test_tampered_raw_or_query_binding_cannot_win_a_default(setup, damage):
    from sqlalchemy import update
    from tire_api.db import QueryRun
    client, registry, database = setup
    first, _ = seed_sources(client, registry)
    variant_id = first['variants'][0]['id']
    with database.sessions() as db:
        if damage == 'body':
            db.execute(update(Snapshot).where(Snapshot.id == first['provenance'][0]['snapshot_id'])
                       .values(body='synthetic corrupted body'))
        else:
            db.execute(update(QueryRun).where(QueryRun.id == first['query_id']).values(query={'model': 'wrong binding'}))
        db.commit()
    wear = fields(client.get(f'/v1/tire-variants/{variant_id}/field-resolution?mode=history').json())['utqg_treadwear']
    official = next(item for item in wear['candidates'] if item['source_id'] == 'fixture')
    assert official['evidence_valid'] is False and official['eligible'] is False
    assert wear['default_value'] == 500


def test_tampered_legacy_member_key_never_defaults_after_identity_migration(setup):
    from sqlalchemy import update
    from test_identity_migration import apply_current, seed_legacy
    client, _, database = setup
    with database.sessions() as db:
        seeded = seed_legacy(db)
        apply_current(db)
        snapshot = db.get(Snapshot, seeded['snapshot_id'])
        members = deepcopy(snapshot.parsed_variants)
        members[0]['identity_key'] = '0' * 64
        db.execute(update(Snapshot).where(Snapshot.id == snapshot.id).values(parsed_variants=members))
        db.commit()
    resolution = client.get(f"/v1/tire-variants/{seeded['variant_id']}/field-resolution?mode=history").json()
    assert all(not item['has_default'] for item in resolution['fields'])
    assert all('legacy_identity_snapshot_mismatch' in item['missing_evidence']
               for field in resolution['fields'] for item in field['candidates'])


def test_selected_old_snapshot_never_uses_future_same_value_fact(setup):
    from tire_api.field_evidence import snapshot_field_candidates
    client, registry, database = setup
    results = []
    for number, value in enumerate((300, 400, 300)):
        registry.result = success(f'synthetic sequential content {number}', [known_variant(utqg_treadwear=value)])
        results.append(live(client).json())
    variant_id = results[0]['variants'][0]['id']
    with database.sessions() as db:
        facts = db.scalars(select(FactVersion).order_by(FactVersion.version)).all()
        old = snapshot_field_candidates(db, results[0]['provenance'][0]['snapshot_id'], variant_id, registry)
        new = snapshot_field_candidates(db, results[2]['provenance'][0]['snapshot_id'], variant_id, registry)
        assert {item['fact_version_id'] for item in old} == {facts[0].id}
        assert {item['fact_version_id'] for item in new} == {facts[2].id}


def test_source_alias_disagreement_cannot_be_resolved_by_locator_completeness(setup):
    client, registry, _ = setup
    registry.result = success('synthetic alias contradiction', [known_variant(utqg_treadwear=300, treadwear=400)])
    row, = live(client).json()['variants']
    wear = fields(row['field_resolution'])['utqg_treadwear']
    assert wear['state'] == 'conflict_tied' and wear['has_default'] is False
    assert {item['source_field'] for item in wear['candidates']} == {'utqg_treadwear', 'treadwear'}


def test_conflict_source_filter_keeps_the_other_source_evidence(setup):
    client, registry, _ = setup
    seed_sources(client, registry)
    result = client.get('/v1/field-conflicts?mode=history&source_id=fixture&field=utqg_treadwear').json()
    assert result['total'] == 1
    assert {item['source_id'] for item in fields(result['items'][0])['utqg_treadwear']['candidates']} == {'fixture', 'fixture-two'}


def test_variant_history_loads_raw_only_for_its_selected_members(setup):
    client, registry, database = setup
    first, second = seed_sources(client, registry)
    registry.result = success('synthetic unrelated private raw body', [{**known_variant(), 'manufacturer_product_code': 'UNRELATED'}])
    unrelated = live(client, {'query': {'size': '265/40R20'}, 'fallback_policy': 'never'}).json()
    unrelated_snapshot = unrelated['provenance'][0]['snapshot_id']
    reads = []
    def capture(_connection, _cursor, sql, params, _context, _many):
        if 'snapshots.body' in sql.lower():
            reads.append((sql, params))
    event.listen(database.engine, 'before_cursor_execute', capture)
    try:
        response = client.get(f"/v1/tire-variants/{first['variants'][0]['id']}/field-resolution?mode=history")
        assert response.status_code == 200
    finally:
        event.remove(database.engine, 'before_cursor_execute', capture)
    assert len(reads) == 1
    assert set(reads[0][1]) == {first['provenance'][0]['snapshot_id'], second['provenance'][0]['snapshot_id']}
    assert unrelated_snapshot not in reads[0][1]


def test_two_active_queries_keep_both_observations_after_older_body_304(setup, monkeypatch):
    from datetime import timedelta
    from tire_api.db import utcnow
    from tire_api import service
    client, registry, _ = setup
    moment = utcnow() - timedelta(days=3)
    monkeypatch.setattr(service, 'utcnow', lambda: moment)
    first_query = {'query': {'model': 'Fixture Tire'}, 'fallback_policy': 'never'}
    registry.result = success('synthetic older query body', [known_variant(utqg_treadwear=300)])
    first = live(client, first_query).json()
    moment += timedelta(days=1)
    registry.result = success('synthetic newer query body', [known_variant(utqg_treadwear=400)])
    second = live(client).json()
    assert first['variants'][0]['id'] == second['variants'][0]['id']
    moment += timedelta(days=1)
    registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product',
        'etag': '"fixture-etag"', 'parser_version': 'fixture@1'}
    assert live(client, first_query).json()['data_state'] == 'live_verified_304'
    value = client.get(f"/v1/tire-variants/{first['variants'][0]['id']}/field-resolution?mode=history").json()
    wear = fields(value)['utqg_treadwear']
    assert len(wear['candidates']) == 2
    assert {item['snapshot_id'] for item in wear['candidates']} == {
        first['provenance'][0]['snapshot_id'], second['provenance'][0]['snapshot_id']}
    assert wear['default_value'] == 400 and wear['state'] == 'conflict_preferred'
