"""Historical recall tests: recorded evidence, isolated storage, no publication."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from tire_api.adapters import nhtsa
from tire_api.captures import before_parse_recorder
from tire_api.db import QueryRun, RawCapture, uid
from tire_api.domain import digest
from tire_api.main import create_app
from tire_api.recall_models import (RecallEvent, RecallNotification, RecallRevision, RecallSnapshot,
                                    RecallVerification)
from tire_api.recall_discovery import RecallDiscoveryService, RecallSearchSnapshot, RecallSearchVerification
from tire_api.recalls import RecallService
from tire_api.reparse import compare_candidate, validate_candidate
from tire_api.source_settings import assert_source_access
from admin_support import register_admin
from test_core import FixtureRegistry

SOURCE = nhtsa.SOURCE_ID
QUERIES = {'campaign': {'campaign_number': '23T001000'},
           'search': {'search': 'XCELLENT ROADBREAKER', 'offset': '0'}}
BODIES = {kind: (Path(__file__).parent / 'fixtures/recalls' / name).read_text(encoding='utf-8')
          for kind, name in [('campaign', 'campaign-23t001000.json'), ('search', 'search-xcellent.json')]}
FORMAL = (RecallSnapshot, RecallVerification, RecallRevision, RecallEvent, RecallNotification,
          RecallSearchSnapshot, RecallSearchVerification)


def formal_counts(database):
    from tire_api.db import FactVersion, Verification, AlertEvent
    from tire_api.knowledge_models import KnowledgeDocument
    with database.sessions() as db:
        return {table.__tablename__: db.scalar(select(func.count()).select_from(table))
                for table in (*FORMAL, FactVersion, Verification, AlertEvent, KnowledgeDocument)}


def seed_recall(client, database, kind, *, accepted=True, body=None, query=None, payload=None):
    client.get('/health')
    query = query or QUERIES[kind]
    body = body or BODIES[kind]
    with database.sessions() as db:
        run = QueryRun(id=uid(), session_id=client.cookies.get('tire_local_session'), source_id=SOURCE,
                       query_key=digest(query), query=query, fallback_policy='never',
                       source_access_generation=assert_source_access(db, SOURCE))
        db.add(run)
        db.commit()
        observation = {'status': 'ok', 'body': body, 'url': nhtsa.query_url(query),
                       'content_type': 'application/json', 'parser_version': nhtsa.PARSER_VERSION}
        before_parse_recorder(db, run)(observation)
        if accepted:
            payload = payload if payload is not None else nhtsa.parse_json(body, query)
            service = RecallService(db, None) if kind == 'campaign' else RecallDiscoveryService(db, None)
            service.persist(run, observation, payload, None, None)
            run.state = 'live'
            db.commit()
        return db.scalar(select(RawCapture.id).where(RawCapture.query_id == run.id))


def create_reparse(client, capture_id, *, bundle_id=None, key=None):
    params = {'mode': 'history', **({'bundle_id': bundle_id} if bundle_id else {})}
    catalog = client.get('/v1/reparse/catalog', params=params)
    assert catalog.status_code == 200, catalog.text
    descriptor = next(row for row in catalog.json()['parsers'] if row['source_id'] == SOURCE)
    return client.post('/v1/reparse/runs', headers={'Idempotency-Key': key or str(uuid4())}, json={
        'mode': 'history', 'capture_id': capture_id, 'parser_version': descriptor['parser_version'],
        'parser_digest': descriptor['parser_digest'], **({'bundle_id': bundle_id} if bundle_id else {})})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from tire_api import parser_runtime
    calls = []
    async def simulated(source, raw, query, version, parser_digest, **_kwargs):
        calls.append(deepcopy(query))
        return {'payload': nhtsa.parse_json(raw.decode(), query), 'receipt': {'synthetic_runtime': True}}
    monkeypatch.setattr(parser_runtime, 'parse_isolated', simulated)
    app = create_app('sqlite:///' + (tmp_path / 'recall-reparse.db').as_posix(), FixtureRegistry())
    with TestClient(app) as client:
        register_admin(client)
        yield client, app.state.database, calls


@pytest.mark.parametrize('kind', QUERIES)
def test_history_review_is_not_adoption_and_freezes_latest_baseline(setup, kind, monkeypatch):
    client, database, calls = setup
    first = seed_recall(client, database, kind)
    before = formal_counts(database)
    def forbidden(*_args, **_kwargs):
        pytest.fail('history must not fetch or persist recall evidence')
    monkeypatch.setattr(nhtsa, 'fetch', forbidden)
    key = str(uuid4())
    response = create_reparse(client, first, key=key)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['state'] == 'completed' and run['accepted_as_facts'] is False
    assert run['input']['target_kind'] == 'recall' and run['input']['query'] == QUERIES[kind]
    assert run['completion']['quality']['reason_codes'] == []
    assert run['completion']['diff']['total_changed_fields'] == 0
    assert create_reparse(client, first, key=key).json()['id'] == run['id'] and len(calls) == 1
    review = client.post('/v1/reparse/runs/' + run['id'] + '/reviews', json={'mode': 'history',
        'expected_revision': 0, 'status': 'reviewed', 'operator': 'Synthetic reviewer', 'reason': 'History only'})
    assert review.status_code == 201 and formal_counts(database) == before
    seed_recall(client, database, kind)
    detail = client.get('/v1/reparse/runs/' + run['id'] + '?mode=history').json()
    assert not detail['baseline_current'] and detail['baseline'] == run['baseline']


@pytest.mark.parametrize('kind', QUERIES)
@pytest.mark.parametrize('mutation', ['url', 'mime', 'source', 'query', 'target'])
def test_capture_metadata_must_match_exact_query(setup, kind, mutation):
    client, database, calls = setup
    capture_id = seed_recall(client, database, kind)
    with database.engine.begin() as connection:
        if mutation == 'query':
            query = ({'campaign_number': '23t001000'} if kind == 'campaign'
                     else {'search': 'XCELLENT ROADBREAKER', 'offset': 0})
            connection.execute(update(QueryRun).values(query=query, query_key=digest(query)))
            connection.execute(update(RawCapture).values(query_key=digest(query)))
        else:
            field, value = {'url': ('source_url', nhtsa.query_url(QUERIES[kind]) + '&extra=1'),
                'mime': ('content_type', 'text/json'), 'source': ('source_id', 'xiaomi-cn'),
                'target': ('target_kind', 'tire')}[mutation]
            connection.execute(update(RawCapture).where(RawCapture.id == capture_id).values(**{field: value}))
    response = create_reparse(client, capture_id)
    assert response.status_code == 422 and not calls


def source_input(kind):
    return {'target_kind': 'recall', 'source_id': SOURCE, 'query': QUERIES[kind],
            'source_url': nhtsa.query_url(QUERIES[kind]), 'content_type': 'application/json'}


@pytest.mark.parametrize('mutation', ['wrong_shape', 'campaign', 'applicability', 'extra', 'duplicate', 'units'])
def test_campaign_candidate_boundary(mutation):
    rows = nhtsa.parse_json(BODIES['campaign'], QUERIES['campaign'])
    if mutation == 'wrong_shape': rows = {'records': rows}
    elif mutation == 'campaign': rows[0]['campaign_number'] = '23T002000'
    elif mutation == 'applicability': rows[0]['applicability'] = 'unaffected'
    elif mutation == 'extra': rows[0]['extra'] = 'unverified'
    elif mutation == 'duplicate': rows.append(deepcopy(rows[0]))
    elif mutation == 'units': rows[0]['potential_units'] = True
    with pytest.raises(ValueError):
        validate_candidate(rows, source_input('campaign'), BODIES['campaign'].encode())


@pytest.mark.parametrize('mutation', ['offset', 'max', 'float_max', 'count', 'next', 'applicability', 'duplicate_document',
                                    'extra_associated', 'nested_associated', 'foreign_document'])
def test_search_candidate_boundary(mutation):
    payload = nhtsa.parse_json(BODIES['search'], QUERIES['search'])
    campaign = payload['products'][0]['campaigns'][0]
    if mutation == 'offset': payload['pagination'].update(offset=10, count=0, total=10, has_previous=True); payload['products'] = []
    elif mutation == 'max': payload['pagination']['max'] = True
    elif mutation == 'float_max': payload['pagination']['max'] = 10.0
    elif mutation == 'count': payload['pagination']['count'] = 2
    elif mutation == 'next': payload['pagination']['has_next'] = True
    elif mutation == 'applicability': payload['products'][0]['applicability'] = 'not_affected'
    elif mutation == 'duplicate_document': campaign['documents'].append(deepcopy(campaign['documents'][0]))
    elif mutation == 'extra_associated': campaign['associated_products'][0]['is_safe'] = True
    elif mutation == 'nested_associated': campaign['associated_products'][0]['productionDates'] = {'opaque': 'claim'}
    elif mutation == 'foreign_document': campaign['documents'][0]['url'] = 'https://example.org/recall.pdf'
    with pytest.raises(ValueError):
        validate_candidate(payload, source_input('search'), BODIES['search'].encode())


@pytest.mark.parametrize('kind', QUERIES)
def test_value_correction_can_pass_but_missing_safety_fields_cannot(kind):
    baseline = nhtsa.parse_json(BODIES[kind], QUERIES[kind])
    candidate = deepcopy(baseline)
    row = candidate[0] if kind == 'campaign' else candidate['products'][0]['campaigns'][0]
    row['remedy'] = 'Corrected official remedy text'
    quality, difference = compare_candidate({'payload': baseline}, candidate, 'recall')
    assert not quality['blocked'] and difference['total_changed_fields'] == 1
    row['remedy'] = ' '
    quality, difference = compare_candidate({'payload': baseline}, candidate, 'recall')
    assert 'recall_safety_field_loss' in quality['reason_codes']
    assert quality['lost_field_count'] == 1


@pytest.mark.parametrize('group', ['campaigns', 'documents', 'associated_products'])
def test_nested_member_loss_never_hides_behind_new_members(group):
    baseline = nhtsa.parse_json(BODIES['search'], QUERIES['search'])
    candidate = deepcopy(baseline)
    campaign = candidate['products'][0]['campaigns'][0]
    if group == 'campaigns':
        campaign['campaign_number'] = '26T777777'
    elif group == 'documents':
        campaign['documents'][0]['url'] = 'https://static.nhtsa.gov/odi/rcl/2026/NEW.pdf'
    else:
        campaign['associated_products'][0]['productModel'] = 'NEW MODEL'
    quality, difference = compare_candidate({'payload': baseline}, candidate, 'recall')
    assert 'recall_member_loss' in quality['reason_codes'] and quality['groups'][group]['lost_rows']
    assert difference['added_row_keys'] and difference['removed_row_keys']


def test_search_identity_pagination_and_order_are_explainable():
    baseline = nhtsa.parse_json(BODIES['search'], QUERIES['search'])
    second = deepcopy(baseline['products'][0]); second['id'] += 1; second['artemis_id'] += 1
    baseline['products'].append(second); baseline['pagination'].update(count=2, total=2)
    candidate = deepcopy(baseline)
    candidate['products'].reverse()
    quality, difference = compare_candidate({'payload': baseline}, candidate, 'recall')
    assert not quality['blocked'] and difference['changed_rows'][0]['row_key'] == 'order'
    candidate['products'][0]['artemis_id'] += 99
    candidate['pagination']['total'] = 11; candidate['pagination']['has_next'] = True
    quality, _ = compare_candidate({'payload': baseline}, candidate, 'recall')
    assert {'recall_identity_changed', 'recall_pagination_changed'} <= set(quality['reason_codes'])


def test_campaign_ambiguity_preserves_all_records_and_empty_is_not_clearance():
    baseline = nhtsa.parse_json(BODIES['campaign'], QUERIES['campaign'])
    extra = deepcopy(baseline[0]); extra['summary'] = 'Another record with the same product label'
    candidate = [baseline[0], extra]
    validated = validate_candidate(candidate, source_input('campaign'), BODIES['campaign'].encode())
    quality, difference = compare_candidate(None, validated, 'recall')
    assert len(validated) == 2 and len(difference['added_row_keys']) == 2
    assert 'ambiguous_alignment' in quality['reason_codes']
    quality, _ = compare_candidate({'payload': baseline}, [], 'recall')
    assert 'recall_member_loss' in quality['reason_codes']


@pytest.mark.parametrize('mutation', ['empty', 'product_loss', 'kind'])
def test_search_empty_or_replacement_never_becomes_clearance(mutation):
    baseline = nhtsa.parse_json(BODIES['search'], QUERIES['search'])
    candidate = deepcopy(baseline)
    if mutation == 'empty':
        candidate['products'] = []
        candidate['pagination'].update(count=0, total=0)
    elif mutation == 'product_loss':
        candidate['products'][0]['id'] += 1
    else:
        candidate = nhtsa.parse_json(BODIES['campaign'], QUERIES['campaign'])
    quality, _ = compare_candidate({'payload': baseline}, candidate, 'recall')
    assert 'recall_member_loss' in quality['reason_codes']
    if mutation == 'kind':
        assert 'recall_payload_kind_changed' in quality['reason_codes']


def test_baseline_select_is_bounded_and_does_not_materialize_raw_body(setup):
    from sqlalchemy import event
    from tire_api.reparse import latest_baseline
    client, database, _ = setup
    for _ in range(3):
        seed_recall(client, database, 'campaign')
    statements = []
    def trace(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(database.engine, 'before_cursor_execute', trace)
    try:
        with database.sessions() as db:
            baseline = latest_baseline(db, SOURCE, 'recall', digest(QUERIES['campaign']), QUERIES['campaign'])
            assert baseline is not None
    finally:
        event.remove(database.engine, 'before_cursor_execute', trace)
    queries = [statement for statement in statements if 'recall_snapshots' in statement]
    assert len(queries) == 1 and 'LIMIT' in queries[0].upper()
    assert 'recall_snapshots.body' not in queries[0]
