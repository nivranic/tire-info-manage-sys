"""Synthetic query projection tests: no manufacturer or AI calls."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select, text

from tire_api.db import (ChangeEvent, FactVersion, FallbackConsent, QueryRun, RawCapture, Snapshot,
                         SourceQuarantine, Verification)
from tire_api.domain import LiveQueryRequest, digest
from tire_api.main import create_app
from tire_api.query_filters import TireFilter, canonical_filters, select_variants
from test_core import FixtureRegistry, QUERY, VARIANT, count, grant, live, setup, success


def condition(field, value=None, op='eq'):
    return {'field': field, 'op': op, **({'value': value} if op not in ('is_known', 'is_unknown') else {})}


def filters(*values):
    return canonical_filters([TireFilter.model_validate(value) for value in values])


def row(code, **changes):
    value = deepcopy(VARIANT)
    value['manufacturer_product_code'] = code
    value.update(changes)
    return value


def selection(rows, *conditions):
    return select_variants(rows, filters(*conditions))


def assert_counts(result, source, matched, excluded, undetermined):
    data = result['selection'] if 'selection' in result else result
    assert [data[key] for key in ('source_count', 'matched_count', 'excluded_count', 'undetermined_count')] == [source, matched, excluded, undetermined]
    if source is not None:
        assert source == matched + excluded + undetermined


def test_catalog_is_complete_typed_and_detached_from_source_io(setup):
    client, registry, _ = setup
    response = client.get('/v1/tire-query-filters')
    assert response.status_code == 200
    body = response.json()
    assert body['version'] == 'tire-query-filters@1' and body['max_conditions'] == 16
    fields = {item['key']: item for item in body['fields']}
    assert len(fields) == 28
    assert {key for key, item in fields.items() if item['type'] == 'number'} == {'utqg_treadwear', 'eu_external_noise_db'}
    assert fields['eu_external_noise_db']['unit'] == 'dB'
    assert fields['ev_marketing_mark']['type'] == 'boolean'
    assert fields['load_index']['operators'] == fields['speed_rating']['operators'] == ['eq', 'is_known', 'is_unknown']
    assert fields['technology_features']['description'] and body['notice']
    assert registry.calls == []


def test_and_projection_counts_unknown_separately_from_explicit_false():
    rows = [row('TRUE', xl=True), row('FALSE', xl=False), row('UNKNOWN', xl=None),
            row('LOW', xl=False, facts={'utqg_treadwear': 200})]
    selected, stats = selection(rows, condition('xl', False), condition('utqg_treadwear', 300, 'gte'))
    assert [value['manufacturer_product_code'] for value in selected] == ['FALSE']
    assert_counts(stats, 4, 1, 2, 1)
    selected, stats = selection(rows, condition('xl', op='is_unknown'))
    assert [value['manufacturer_product_code'] for value in selected] == ['UNKNOWN']
    assert_counts(stats, 4, 1, 3, 0)
    assert selection(rows, condition('xl', op='is_known'))[1]['matched_count'] == 3


@pytest.mark.parametrize('op,value', [('eq', False), ('eq', True), ('is_known', None), ('is_unknown', None)])
def test_conflicting_selected_field_is_undetermined_even_when_one_value_is_present(op, value):
    conflict = row('CONFLICT', xl=False, facts={'source_field_conflicts': [
        {'field': 'xl', 'values': [{'value': False}, {'value': True}], 'resolution': 'unresolved'}]})
    selected, stats = selection([conflict], condition('xl', value, op))
    assert selected == []
    assert_counts(stats, 1, 0, 0, 1)


@pytest.mark.parametrize('raw', [True, '70', '70 dB', {'value': 70, 'unit': 'dB'}, [70]])
@pytest.mark.parametrize('op', ['eq', 'is_known', 'is_unknown'])
def test_numeric_invalid_type_and_unit_objects_are_undetermined(raw, op):
    selected, stats = selection([row('INVALID', facts={'eu_external_noise_db': raw})],
                                condition('eu_external_noise_db', 70, op))
    assert selected == []
    assert_counts(stats, 1, 0, 0, 1)


def test_numbers_use_numeric_order_with_explicit_units_only():
    rows = [row('LOW', facts={'eu_external_noise_db': 68}), row('MID', facts={'eu_external_noise_db': 70.5}),
            row('HIGH', facts={'eu_external_noise_db': 74}), row('UNKNOWN', facts={})]
    selected, stats = selection(rows, condition('eu_external_noise_db', 70, 'gte'), condition('eu_external_noise_db', 72, 'lte'))
    assert [value['manufacturer_product_code'] for value in selected] == ['MID']
    assert_counts(stats, 4, 1, 2, 1)
    assert selection([row('ZERO', facts={'utqg_treadwear': 0})], condition('utqg_treadwear', op='is_known'))[1]['matched_count'] == 1


def test_exact_normalization_does_not_erase_codes_or_order_dual_load_and_speed():
    exact = row('000123', load_index='104/102', speed_rating='(Y)', facts={'gtin': '00012345678905', 'eprel_id': '00042'})
    conditions = [condition('manufacturer_product_code', '０００１２３'), condition('gtin', '00012345678905'),
                  condition('eprel_id', '00042'), condition('load_index', '104/102'), condition('speed_rating', '(y)')]
    assert selection([exact], *conditions)[1]['matched_count'] == 1
    for field, value in [('manufacturer_product_code', '123'), ('gtin', '12345678905'), ('eprel_id', '42'),
                         ('load_index', '104'), ('speed_rating', 'Y')]:
        assert selection([exact], condition(field, value))[1]['excluded_count'] == 1
    assert selection([exact], condition('size', '265/40R20'))[1]['excluded_count'] == 1
    assert selection([exact], condition('size', ' 265 /40 zr20 '))[1]['matched_count'] == 1


def test_technology_is_exact_whole_text_or_whole_list_member_without_aliases():
    rows = [row('TEXT', acoustic_technology=' Acoustic '), row('MEMBER', acoustic_technology=None,
            facts={'technology_features': ['XL', 'ＡＣＯＵＳＴＩＣ']}), row('PREFIX', acoustic_technology='Acoustic Plus'),
            row('PNCS', acoustic_technology='PNCS'), row('MARKETING', acoustic_technology=None,
            facts={'description': 'Acoustic', 'technology_features': [{'name': 'Acoustic'}]})]
    assert [v['manufacturer_product_code'] for v in selection(rows, condition('acoustic_technology', 'ACOUSTIC'))[0]] == ['TEXT']
    selected, stats = selection(rows, condition('technology_features', 'acoustic'))
    assert [v['manufacturer_product_code'] for v in selected] == ['MEMBER']
    assert_counts(stats, 5, 1, 0, 4)
    assert selection([row('EMPTY', facts={'technology_features': []})], condition('technology_features', op='is_unknown'))[1]['matched_count'] == 1


def test_undeclared_family_ev_and_construction_are_not_inferred_from_model_or_size():
    source = row('EV', model='Family Pilot EV XL Acoustic', facts={})
    for field, expected in [('family', 'Family'), ('ev_marketing_mark', True), ('construction', 'ZR'), ('acoustic_foam', True)]:
        assert_counts(selection([source], condition(field, expected))[1], 1, 0, 0, 1)
        assert selection([source], condition(field, op='is_unknown'))[1]['matched_count'] == 1
    explicit = row('EV', facts={'family': 'Family', 'ev_marketing_mark': False})
    assert selection([explicit], condition('family', 'family'), condition('ev_marketing_mark', False))[1]['matched_count'] == 1
    assert selection([row('BAD', facts={'ev_marketing_mark': 0})], condition('ev_marketing_mark', False))[1]['undetermined_count'] == 1


@pytest.mark.parametrize('bad', [
    {}, {'field': 'brand'}, condition('arbitrary_field', 'x'), condition('facts.gtin', 'x'),
    condition('brand', ''), condition('brand', '   '), condition('brand', '\u200b'), condition('brand', 'x' * 513),
    condition('brand', []), condition('brand', {}), condition('brand', 123), condition('xl', 0), condition('xl', 1),
    condition('xl', 'false'), condition('xl', None), condition('utqg_treadwear', '300'), condition('utqg_treadwear', True),
    condition('utqg_treadwear', {'value': 300}), condition('load_index', 104), condition('load_index', '104', 'gte'),
    condition('speed_rating', 'Y', 'lte'), condition('speed_rating', 'YY'), condition('load_index', '104Y'),
    condition('size', '265/40R20 XL'), condition('brand', 'x', 'contains'),
    {'field': 'brand', 'op': 'is_known', 'value': None}, {'field': 'brand', 'op': 'eq', 'value': 'x', 'extra': True},
])
def test_invalid_conditions_fail_422_before_source_io(setup, bad):
    client, registry, _ = setup
    assert live(client, {**QUERY, 'filters': [bad]}).status_code == 422
    assert registry.calls == []


@pytest.mark.parametrize('bad', [None, {}, 'brand', [None]])
def test_invalid_filter_container_is_rejected(setup, bad):
    client, registry, _ = setup
    assert live(client, {**QUERY, 'filters': bad}).status_code == 422
    assert registry.calls == []


@pytest.mark.parametrize('number', [float('nan'), float('inf'), float('-inf')])
def test_nonfinite_filter_is_rejected(number):
    with pytest.raises(ValidationError):
        LiveQueryRequest.model_validate({**QUERY, 'filters': [condition('utqg_treadwear', number)]})


def test_sixteen_limit_precedes_deduplication_and_equivalent_order_is_canonical(setup):
    client, _, _ = setup
    duplicate = condition('brand', ' ＦＩＸＴＵＲＥ   BRAND ')
    valid = live(client, {**QUERY, 'filters': [duplicate] * 16})
    assert valid.status_code == 200
    assert valid.json()['selection']['filters'] == [condition('brand', 'fixture brand')]
    assert live(client, {**QUERY, 'filters': [duplicate] * 17}).status_code == 422
    left = LiveQueryRequest.model_validate({**QUERY, 'filters': [condition('utqg_treadwear', 300.0, 'gte'), duplicate]})
    right = LiveQueryRequest.model_validate({**QUERY, 'filters': [condition('brand', 'fixture brand'), condition('utqg_treadwear', 300, 'gte')]})
    assert canonical_filters(left.filters) == canonical_filters(right.filters)
    assert isinstance(canonical_filters(left.filters)[1]['value'], int)


def test_live_projection_freezes_filters_and_preserves_all_snapshots_facts_and_events(setup):
    client, registry, database = setup
    rows = [row('A', xl=False), row('B', xl=True), row('C', xl=None)]
    registry.result = success('all-source-rows', rows)
    payload = {**QUERY, 'filters': [condition('xl', False)]}
    response = live(client, payload)
    assert response.status_code == 200
    result = response.json()
    assert result['data_state'] == 'live'
    assert [value['manufacturer_product_code'] for value in result['variants']] == ['A']
    assert_counts(result, 3, 1, 1, 1)
    with database.sessions() as db:
        run = db.get(QueryRun, result['query_id'])
        assert run.selection_filters == result['selection']['filters'] == filters(condition('xl', False))
        assert run.query == QUERY['query'] and run.query_key == digest(QUERY['query'])
        snapshot = db.get(Snapshot, result['provenance'][0]['snapshot_id'])
        assert len(snapshot.parsed_variants) == 3
        assert snapshot.body == 'all-source-rows' and snapshot.query_key == run.query_key
    assert count(database, FactVersion) == count(database, ChangeEvent) == 3
    assert registry.calls[-1][1] == QUERY['query']
    unfiltered = live(client).json()
    assert_counts(unfiltered, 3, 3, 0, 0)
    assert len(unfiltered['variants']) == 3 and count(database, Snapshot) == 1
    by_id = live(client, {**QUERY, 'filters': [condition('variant_id', result['variants'][0]['id'])]}).json()
    assert len(by_id['variants']) == 1


def test_304_reuses_resource_cache_and_reprojects_different_filters_including_zero(setup):
    client, registry, database = setup
    registry.result = success('multiple variants', [row('A', xl=False), row('B', xl=True)])
    first = live(client, {**QUERY, 'filters': [condition('xl', False)]}).json()
    registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product', 'parser_version': 'fixture@1'}
    second = live(client, {**QUERY, 'filters': [condition('xl', True)]}).json()
    assert second['data_state'] == 'live_verified_304'
    assert second['variants'][0]['manufacturer_product_code'] == 'B'
    assert_counts(second, 2, 1, 1, 0)
    assert second['provenance'] == first['provenance']
    assert registry.calls[-1][2]['snapshot_id'] == first['provenance'][0]['snapshot_id']
    third = live(client, {**QUERY, 'filters': [condition('manufacturer_product_code', 'NONE')]}).json()
    assert third['data_state'] == 'live_verified_304' and third['variants'] == [] and third['reason'] is None
    assert_counts(third, 2, 0, 2, 0)
    assert count(database, Snapshot) == 1 and count(database, Verification) == 3


def test_zero_live_matches_keep_success_and_current_source_conflicts_only_from_returned_rows(setup):
    client, registry, _ = setup
    conflict = {'source_field_conflicts': [{'field': 'xl', 'values': [True, False]}]}
    registry.result = success('mixed conflict', [row('A'), row('B', facts=conflict)])
    selected = live(client, {**QUERY, 'filters': [condition('manufacturer_product_code', 'A')]}).json()
    assert selected['conflicts'] == []
    selected = live(client, {**QUERY, 'filters': [condition('manufacturer_product_code', 'B')]}).json()
    assert len(selected['conflicts']) == 1 and selected['conflicts'][0]['variant_id'] == selected['variants'][0]['id']
    empty = live(client, {**QUERY, 'filters': [condition('brand', 'Different')]}).json()
    assert empty['data_state'] == 'live' and empty['reason'] is None
    assert empty['variants'] == empty['conflicts'] == [] and len(empty['provenance']) == 1
    assert_counts(empty, 2, 0, 2, 0)


def test_failed_ask_unanswered_never_and_denied_do_not_read_local_parameters(setup):
    client, registry, database = setup
    live(client)
    payload = {**QUERY, 'filters': [condition('utqg_treadwear', 300)]}
    registry.result = {'status': 'unavailable', 'reason': 'timeout'}
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(database.engine, 'before_cursor_execute', capture)
    try:
        ask = live(client, payload).json()
        never = live(client, {**payload, 'fallback_policy': 'never'}).json()
        assert ask['data_state'] == 'consent_required' and never['data_state'] == 'source_unavailable'
        for result in (ask, never):
            assert_counts(result, None, None, None, None)
            assert result['selection']['filters'] == filters(condition('utqg_treadwear', 300))
            assert result['variants'] == result['provenance'] == result['conflicts'] == []
        denied = grant(client, ask['query_id'], 'deny').json()
        assert live(client, {**payload, 'consent_id': denied['id']}).status_code == 403
        selects = [statement.lower() for statement in statements if statement.lstrip().upper().startswith('SELECT')]
        assert not any('fact_versions' in statement or 'snapshots.parsed_variants' in statement for statement in selects)
    finally:
        event.remove(database.engine, 'before_cursor_execute', capture)


def test_changed_filters_cannot_consume_grant_and_equivalent_filters_can_use_it_once(setup):
    client, registry, database = setup
    live(client)
    original = [condition('brand', 'ＦＩＸＴＵＲＥ   Brand'), condition('utqg_treadwear', 300.0, 'gte')]
    payload = {**QUERY, 'filters': original}
    registry.result = {'status': 'unavailable', 'reason': 'timeout'}
    failed = live(client, payload).json()
    cid = grant(client, failed['query_id']).json()['id']
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(database.engine, 'before_cursor_execute', capture)
    try:
        for changed in ([], [condition('brand', 'Other')], original + [condition('xl', True)]):
            assert live(client, {**payload, 'filters': changed, 'consent_id': cid}).status_code == 403
        assert not any('snapshots.parsed_variants' in statement.lower() or 'fact_versions' in statement.lower()
                       for statement in statements if statement.lstrip().upper().startswith('SELECT'))
        assert not any(statement.lstrip().upper().startswith('UPDATE FALLBACK_CONSENTS') for statement in statements)
    finally:
        event.remove(database.engine, 'before_cursor_execute', capture)
    with database.sessions() as db:
        assert db.get(FallbackConsent, cid).used_at is None
    equivalent = [condition('utqg_treadwear', 300, 'gte'), condition('brand', 'fixture brand'), condition('brand', 'fixture brand')]
    result = live(client, {**payload, 'filters': equivalent, 'consent_id': cid}).json()
    assert result['data_state'] == 'local_snapshot'
    assert_counts(result, 1, 1, 0, 0)
    assert live(client, {**payload, 'filters': equivalent, 'consent_id': cid}).status_code == 409


def test_zero_local_matches_keep_local_state_and_missing_snapshot_has_null_counts(setup):
    client, registry, _ = setup
    payload = {**QUERY, 'filters': [condition('brand', 'absent')]}
    registry.result = {'status': 'unavailable', 'reason': 'timeout'}
    failed = live(client, payload).json()
    cid = grant(client, failed['query_id']).json()['id']
    missing = live(client, {**payload, 'consent_id': cid}).json()
    assert missing['data_state'] == 'local_snapshot' and missing['reason'] == 'no_matching_local_snapshot'
    assert_counts(missing, None, None, None, None)
    registry.result = success()
    live(client)
    registry.result = {'status': 'unavailable', 'reason': 'timeout'}
    failed = live(client, payload).json()
    cid = grant(client, failed['query_id']).json()['id']
    empty = live(client, {**payload, 'consent_id': cid}).json()
    assert empty['data_state'] == 'local_snapshot' and empty['reason'] != 'no_matching_local_snapshot'
    assert empty['variants'] == [] and len(empty['provenance']) == 1
    assert_counts(empty, 1, 0, 1, 0)


def test_projection_does_not_suppress_quality_gate_on_excluded_rows(setup):
    client, registry, database = setup
    rows = [row(f'CODE-{index}') for index in range(10)]
    registry.result = success('baseline full source', rows)
    payload = {**QUERY, 'filters': [condition('manufacturer_product_code', 'CODE-0')]}
    assert_counts(live(client, payload).json(), 10, 1, 9, 0)
    registry.result = success('loses only excluded rows', rows[:7])
    result = live(client, payload).json()
    assert result['data_state'] == 'consent_required' and result['reason'] == 'source_quality_quarantined'
    assert_counts(result, None, None, None, None)
    assert count(database, Snapshot) == count(database, Verification) == count(database, SourceQuarantine) == 1
    assert count(database, FactVersion) == count(database, ChangeEvent) == 10
    with database.sessions() as db:
        quarantine = db.scalar(select(SourceQuarantine))
        assert len(quarantine.candidates) == 7
        assert quarantine.quality['baseline_rows'] == 10 and quarantine.quality['lost_rows'] == 3


def test_additive_upgrade_keeps_legacy_queries_and_evidence_unchanged_and_is_idempotent(tmp_path):
    url = 'sqlite:///' + (tmp_path / 'legacy-selection.db').as_posix()
    registry = FixtureRegistry()
    app = create_app(url, registry)
    with TestClient(app) as client:
        result = live(client).json()
        registry.result = {'status': 'unavailable', 'reason': 'timeout'}
        failed = live(client).json()
        cid = grant(client, failed['query_id']).json()['id']
        cookies = dict(client.cookies)
        with app.state.database.engine.begin() as connection:
            connection.exec_driver_sql('ALTER TABLE query_runs DROP COLUMN selection_filters')
            connection.execute(text('DELETE FROM tire_schema_versions WHERE version = :version'), {'version': '004_query_selection_filters'})
            before_queries = [dict(row) for row in connection.execute(text('SELECT * FROM query_runs')).mappings()]
            before_snapshots = [dict(row) for row in connection.execute(text('SELECT * FROM snapshots')).mappings()]
    upgraded = create_app(url, registry)
    with TestClient(upgraded, cookies=cookies) as client:
        database = upgraded.state.database
        database.initialize()
        with database.engine.connect() as connection:
            after = [dict(row) for row in connection.execute(text('SELECT * FROM query_runs')).mappings()]
            assert all(row.pop('selection_filters') is None for row in after)
            assert after == before_queries
            assert [dict(row) for row in connection.execute(text('SELECT * FROM snapshots')).mappings()] == before_snapshots
            assert connection.execute(text("SELECT COUNT(*) FROM tire_schema_versions WHERE version='004_query_selection_filters'")).scalar() == 1
        local = live(client, {**QUERY, 'consent_id': cid}).json()
        assert local['selection']['filters'] == []
        assert_counts(local, 1, 1, 0, 0)
        with database.sessions() as db:
            assert db.get(QueryRun, result['query_id']).selection_filters is None
            assert db.get(QueryRun, failed['query_id']).selection_filters is None


@pytest.mark.parametrize('sentinel', ['unknown', ' unspecified ', 'ＵＮＫＮＯＷＮ'])
def test_technical_text_missing_sentinels_do_not_turn_into_known_values(sentinel):
    value = row('unknown', facts={'season': sentinel})
    assert_counts(selection([value], condition('season', op='is_unknown'))[1], 1, 1, 0, 0)
    assert_counts(selection([value], condition('season', op='is_known'))[1], 1, 0, 1, 0)
    assert_counts(selection([value], condition('season', 'summer'))[1], 1, 0, 0, 1)
    # Identifiers remain exact text even if a legitimate product code spells unknown.
    assert selection([value], condition('manufacturer_product_code', 'unknown'))[1]['matched_count'] == 1


def test_raw_capture_and_parser_input_keep_the_unfiltered_resource_query():
    class CapturingRegistry(FixtureRegistry):
        async def fetch(self, source_id, query, cached=None, *, on_observation=None):
            assert query == QUERY['query']
            assert on_observation is not None
            on_observation({key: value for key, value in self.result.items() if key != 'variants'})
            return await super().fetch(source_id, query, cached, on_observation=on_observation)

    registry = CapturingRegistry()
    registry.result = success('full original body with three source variants', [row('A'), row('B'), row('C')])
    app = create_app('sqlite://', registry)
    with TestClient(app) as client:
        result = live(client, {**QUERY, 'filters': [condition('manufacturer_product_code', 'A')]}).json()
        assert result['data_state'] == 'live'
        assert_counts(result, 3, 1, 2, 0)
        with app.state.database.sessions() as db:
            capture = db.scalar(select(RawCapture))
            run = db.get(QueryRun, capture.query_id)
            assert capture.query_key == digest(QUERY['query']) == run.query_key
            assert run.query == QUERY['query']
            assert capture.target_kind == 'tire'
            assert capture.raw_body.decode() == registry.result['body']
            assert len(db.scalar(select(Snapshot)).parsed_variants) == 3


def test_simultaneous_filtered_consent_requests_have_one_winner(tmp_path):
    registry = FixtureRegistry()
    app = create_app('sqlite:///' + (tmp_path / 'consent-race.db').as_posix(), registry)
    payload = {**QUERY, 'filters': [condition('xl', True)]}
    with TestClient(app) as client:
        live(client)
        registry.result = {'status': 'unavailable', 'reason': 'timeout'}
        failed = live(client, payload).json()
        cid = grant(client, failed['query_id']).json()['id']
        cookies = dict(client.cookies)
        barrier = Barrier(2)

        def consume(_):
            requester = TestClient(app, cookies=cookies)
            try:
                barrier.wait(timeout=10)
                return live(requester, {**payload, 'consent_id': cid})
            finally:
                requester.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, range(2)))
        assert sorted(result.status_code for result in results) == [200, 409]
        winner = next(result.json() for result in results if result.status_code == 200)
        assert winner['data_state'] == 'local_snapshot'
        assert_counts(winner, 1, 1, 0, 0)
