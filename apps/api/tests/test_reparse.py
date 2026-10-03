"""Historical experiments use recorded excerpts; never a network or publication path."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from threading import Event, Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, update

from tire_api.adapters import hankook, registry, xiaomi
from tire_api.captures import before_parse_recorder
from tire_api.db import (AlertEvent, CaptureObject, ChangeEvent, EvidenceObject, FactVersion, QueryRun,
    RawCapture, Snapshot, SourceQuarantine, Verification, uid, utcnow)
from tire_api.domain import VariantInput, digest
from tire_api.knowledge_models import KnowledgeDocument
from tire_api.main import create_app
from tire_api.reparse_models import ReparseCompletion, ReparseReview, ReparseRun
from tire_api.service import QueryService
from tire_api.source_settings import assert_source_access
from test_core import FixtureRegistry
from test_vehicles import source_document

BODY = (Path(__file__).parent / 'fixtures/brand_sources/hankook-runflat-pair-excerpt.html').read_text(encoding='utf-8')
QUERY = {'model': 'Ventus S1 evo3', 'size': '205/45R17'}
FORMAL = (Snapshot, FactVersion, Verification, ChangeEvent, AlertEvent, KnowledgeDocument, SourceQuarantine)


def totals(database):
    with database.sessions() as db:
        return {table.__tablename__: db.scalar(select(func.count()).select_from(table)) for table in FORMAL}


def seed_capture(client, database, *, body=BODY, source='hankook-us', baseline=False, variants=None, legacy=False):
    client.get('/health')
    vehicle = source == xiaomi.SOURCE_ID
    query = {'vehicle_id': xiaomi.CURRENT_ID} if vehicle else QUERY
    url = xiaomi.API_URL if vehicle else registry.query_url(query, source)
    version = xiaomi.PARSER_VERSION if vehicle else registry.SPECS[source].parser_version
    mime = 'application/json' if vehicle else 'text/html'
    with database.sessions() as db:
        run = QueryRun(id=uid(), session_id=client.cookies.get('tire_local_session'), source_id=source,
                       query_key=digest(query), query=query, fallback_policy='never',
                       source_access_generation=None if legacy else assert_source_access(db, source))
        db.add(run)
        db.commit()
        observation = {'body': body, 'url': url, 'content_type': mime, 'parser_version': version}
        if legacy:
            db.add(RawCapture(id=uid(), query_id=run.id, source_id=source, query_key=run.query_key,
                target_kind='vehicle' if vehicle else 'tire', source_url=url,
                raw_hash=hashlib.sha256(body.encode()).hexdigest(), raw_body=body.encode(),
                byte_count=len(body.encode()), content_type=mime, parser_version=version))
            db.commit()
        else:
            before_parse_recorder(db, run)(observation)
        if baseline:
            if vehicle:
                from tire_api.vehicles import VehicleService
                VehicleService(db, xiaomi).persist(run, observation, xiaomi.parse_config(body))
            else:
                values = variants if variants is not None else hankook.parse_html(body, query)
                QueryService(db, None).record_success(run, observation, [VariantInput.model_validate(row) for row in values])
            run.state = 'live'
            db.commit()
        return db.scalar(select(RawCapture.id).where(RawCapture.query_id == run.id))


def request_payload(client, capture_id, source='hankook-us'):
    response = client.get('/v1/reparse/catalog?mode=history')
    assert response.status_code == 200, response.text
    parser = next(row for row in response.json()['parsers'] if row['source_id'] == source)
    return {'mode': 'history', 'capture_id': capture_id, 'parser_version': parser['parser_version'],
            'parser_digest': parser['parser_digest']}


def create(client, capture_id, *, key=None, source='hankook-us', **changes):
    return client.post('/v1/reparse/runs', headers={'Idempotency-Key': key or str(uuid4())},
                       json={**request_payload(client, capture_id, source), **changes})


def review(client, run_id, revision=0, **changes):
    return client.post(f'/v1/reparse/runs/{run_id}/reviews', json={'mode': 'history',
        'expected_revision': revision, 'status': 'reviewed', 'operator': '合成审阅者',
        'reason': '仅核对候选，不采纳为正式事实', **changes})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from tire_api import parser_runtime
    calls = []
    async def simulated_process(source_id, body, query, parser_version, parser_digest):
        calls.append((source_id, query))
        payload = xiaomi.parse_config(body.decode()) if source_id == xiaomi.SOURCE_ID else hankook.parse_html(body.decode(), query)
        return {'payload': payload, 'receipt': {'synthetic_runtime': True, 'network_enforced': False,
            'parser_version': parser_version, 'parser_digest': parser_digest}}
    monkeypatch.setattr(parser_runtime, 'parse_isolated', simulated_process)
    app = create_app('sqlite:///' + (tmp_path / 'reparse.db').as_posix(), FixtureRegistry())
    with TestClient(app) as client:
        yield client, app.state.database, calls


def test_historical_experiment_freezes_baseline_and_never_writes_formal_tables(setup, monkeypatch):
    client, database, calls = setup
    capture_id = seed_capture(client, database, baseline=True)
    before = totals(database)
    def prohibited(*args, **kwargs):
        pytest.fail('reparse must not fetch or accept source evidence')
    monkeypatch.setattr(registry, 'fetch', prohibited)
    monkeypatch.setattr(QueryService, 'record_success', prohibited)
    response = create(client, capture_id)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['state'] == 'completed' and result['accepted_as_facts'] is False
    assert result['scope'] == 'workspace' and result['data_state'] == 'local_snapshot'
    assert result['input']['raw_hash'] == hashlib.sha256(BODY.encode()).hexdigest()
    assert result['baseline']['selected_at'] and result['baseline_current']
    assert result['completion']['candidate'] and result['completion']['quality']['blocked'] is False
    assert result['completion']['diff']['total_changed_fields'] == 0
    assert len(calls) == 1 and totals(database) == before
    listing = client.get('/v1/reparse/runs?mode=history&limit=1').json()
    assert listing['total'] == 1 and listing['items'][0]['id'] == result['id']
    assert 'payload' not in listing['items'][0]['baseline']
    assert not {'candidate', 'diff', 'quality', 'receipt'} & listing['items'][0]['completion'].keys()
    assert 'body' not in result['input']


def test_deployment_catalog_bounded_and_all_routes_require_history(setup):
    client, database, _ = setup
    catalog = client.get('/v1/reparse/catalog?mode=history').json()
    assert len(catalog['parsers']) == 10 and catalog['accepted_as_facts'] is False
    assert catalog['limits']['timeout_seconds'] == 8
    assert 'eprel' not in {row['source_id'] for row in catalog['parsers']}
    for route in ('catalog', 'status', 'runs', 'runs/missing'):
        assert client.get('/v1/reparse/' + route).status_code == 422
    capture = seed_capture(client, database)
    assert create(client, capture, mode='current').status_code == 422
    assert create(client, capture, body='forbidden').status_code == 422
    assert create(client, capture, source_url='https://evil.invalid').status_code == 422
    run = create(client, capture).json()
    assert review(client, run['id'], mode='current').status_code == 422
    assert client.get('/v1/reparse/runs?mode=history&limit=26').status_code == 422


def test_unsupported_platform_catalog_does_not_claim_execution_available(setup, monkeypatch):
    from tire_api import reparse
    client, _, _ = setup
    monkeypatch.setattr(reparse, 'HOST_PLATFORM', 'darwin')
    result = client.get('/v1/reparse/catalog?mode=history').json()
    assert result['available'] is False and result['availability_reason'] == 'parser_platform_not_supported'
    assert len(result['parsers']) == 10 and client.get('/health').status_code == 200


@pytest.mark.parametrize('field,value', [('parser_version', 'old@0'), ('parser_digest', '0' * 64)])
def test_stale_parser_choice_rejected_before_execution(setup, field, value):
    client, database, calls = setup
    capture = seed_capture(client, database)
    response = create(client, capture, **{field: value})
    assert response.status_code == 409 and response.json()['detail']['code'] == 'parser_deployment_changed'
    assert not calls


@pytest.mark.parametrize('mutation', ['source', 'query', 'query_key', 'url', 'mime', 'target'])
def test_mismatched_frozen_capture_metadata_is_not_parsed(setup, mutation):
    client, database, calls = setup
    capture = seed_capture(client, database)
    with database.engine.begin() as connection:
        if mutation == 'query':
            connection.execute(update(QueryRun).values(query={'model': 'forged'}))
        else:
            key, value = {'source': ('source_id', 'toyo-us'), 'query_key': ('query_key', 'bad'),
                'url': ('source_url', 'https://evil.invalid'), 'mime': ('content_type', 'application/pdf'),
                'target': ('target_kind', 'vehicle')}[mutation]
            connection.execute(update(RawCapture).where(RawCapture.id == capture).values(**{key: value}))
    response = create(client, capture)
    assert response.status_code == 422 and not calls


@pytest.mark.parametrize('corruption', ['missing', 'mapping', 'object_size', 'capture_hash', 'capture_bytes'])
def test_object_integrity_failure_is_durable_and_never_falls_back_to_db(setup, monkeypatch, corruption):
    client, database, calls = setup
    capture = seed_capture(client, database)
    if corruption == 'missing':
        from tire_api.object_store import ObjectStoreError
        def missing(*_): raise ObjectStoreError('private storage path')
        monkeypatch.setattr(database.object_store, 'get', missing)
    else:
        with database.engine.begin() as connection:
            if corruption == 'mapping':
                other = hashlib.sha256(b'other').hexdigest()
                connection.execute(EvidenceObject.__table__.insert().values(raw_hash=other, byte_count=5, created_at=utcnow()))
                connection.execute(update(CaptureObject).where(CaptureObject.capture_id == capture).values(raw_hash=other))
            elif corruption == 'object_size':
                connection.execute(update(EvidenceObject).values(byte_count=1))
            else:
                key, value = ('raw_hash', '0' * 64) if corruption == 'capture_hash' else ('byte_count', 1)
                connection.execute(update(RawCapture).where(RawCapture.id == capture).values(**{key: value}))
    key = str(uuid4())
    response = create(client, capture, key=key)
    assert response.status_code == 503 and 'private storage path' not in response.text
    run = client.get('/v1/reparse/runs/' + response.json()['detail']['run_id'] + '?mode=history').json()
    assert run['state'] == 'failed' and run['completion']['error_code'] == 'capture_integrity_failed'
    assert not calls and run['completion']['candidate'] is None
    assert create(client, capture, key=key).json()['id'] == run['id']
    assert client.get('/v1/captures/' + capture + '?mode=history').status_code == 503


def test_legacy_bytes_are_explicitly_checked_and_damaged_bytes_rejected(setup):
    client, database, calls = setup
    good = seed_capture(client, database, legacy=True)
    assert create(client, good).json()['input']['storage_kind'] == 'database_legacy'
    bad = seed_capture(client, database, legacy=True)
    with database.engine.begin() as connection:
        connection.execute(update(RawCapture).where(RawCapture.id == bad).values(raw_body=b'damaged'))
    assert create(client, bad).status_code == 503 and len(calls) == 1


@pytest.mark.parametrize('code', ['parser_timeout', 'parser_crashed', 'parser_output_too_large'])
def test_known_parser_failures_remain_terminal_and_reviewable(setup, monkeypatch, code):
    from tire_api import parser_runtime
    client, database, _ = setup
    capture = seed_capture(client, database)
    attempts = []
    async def failed(*_):
        attempts.append(1)
        raise parser_runtime.ParserRunError(code, {'exit_code': 1, 'network_enforced': False})
    monkeypatch.setattr(parser_runtime, 'parse_isolated', failed)
    key = str(uuid4())
    result = create(client, capture, key=key).json()
    assert result['state'] == 'failed' and result['completion']['error_code'] == code
    assert create(client, capture, key=key).json()['id'] == result['id'] and len(attempts) == 1
    assert review(client, result['id'], status='needs_fix').json()['review_revision'] == 1


@pytest.mark.parametrize('bad', ['null', 'wrong_size', 'oversized', 'nonfinite'])
def test_invalid_parser_candidate_is_audited_without_accepting_facts(setup, monkeypatch, bad):
    from tire_api import parser_runtime
    client, database, _ = setup
    capture = seed_capture(client, database)
    before = totals(database)
    async def invalid(_source, body, query, *_):
        values = hankook.parse_html(body.decode(), query)
        if bad == 'null':
            values[0]['facts']['description'] = 'bad\x00value'
        elif bad == 'wrong_size':
            values[0]['size'] = '245/40R19'
        elif bad == 'oversized':
            values[0]['facts']['description'] = 'a' * (2 * 1024 * 1024)
        else:
            values[0]['facts']['value'] = float('nan')
        return {'payload': values, 'receipt': {'synthetic_runtime': True}}
    monkeypatch.setattr(parser_runtime, 'parse_isolated', invalid)
    result = create(client, capture).json()
    assert result['state'] == 'failed' and result['completion']['error_code'] == 'candidate_validation_failed'
    assert result['completion']['candidate'] is None and totals(database) == before


def test_same_session_uuid_binds_payload_and_other_session_is_not_replay(setup):
    client, database, calls = setup
    capture = seed_capture(client, database)
    key = str(uuid4())
    first = create(client, capture, key=key).json()
    assert create(client, capture, key=key).json()['id'] == first['id']
    assert create(client, capture, key=key, parser_version='other').status_code == 409
    peer = TestClient(client.app)
    peer.get('/health')
    assert create(peer, capture, key=key).json()['id'] != first['id'] and len(calls) == 2
    assert peer.get('/v1/reparse/runs/' + first['id'] + '?mode=history').status_code == 200


def test_pending_replay_has_no_second_execution_and_holds_no_ingestion_lock(setup, monkeypatch):
    from tire_api import parser_runtime
    client, database, _ = setup
    capture = seed_capture(client, database)
    entered, release = Event(), Event()
    async def waiting(source_id, body, query, version, code_hash):
        # An independent writer must be able to reserve while this parser is active.
        with database.sessions() as db:
            QueryService(db, None).lock_ingestion()
            assert db.scalar(select(ReparseRun)) is not None
            db.commit()
        entered.set()
        assert await asyncio.to_thread(release.wait, 10)
        return {'payload': hankook.parse_html(body.decode(), query), 'receipt': {'synthetic_runtime': True}}
    monkeypatch.setattr(parser_runtime, 'parse_isolated', waiting)
    payload, key = request_payload(client, capture), str(uuid4())
    def execute():
        return client.post('/v1/reparse/runs', json=payload, headers={'Idempotency-Key': key})
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(execute)
        try:
            assert entered.wait(10)
            pending = execute().json()
            assert pending['state'] == 'pending' and pending['completion'] is None
            assert review(client, pending['id']).status_code == 409
        finally:
            release.set()
        assert future.result(timeout=15).json()['state'] == 'completed'


def test_unknown_incomplete_run_never_restarts_with_same_key(setup, monkeypatch):
    client, database, calls = setup
    capture = seed_capture(client, database)
    payload, key = request_payload(client, capture), str(uuid4())
    with database.sessions() as db:
        source_input = {'capture_id': capture, 'source_id': 'hankook-us', 'target_kind': 'tire',
                        'query': QUERY, 'query_key': digest(QUERY)}
        parser = {'version': payload['parser_version'], 'digest': payload['parser_digest']}
        run = ReparseRun(id=uid(), actor_session_id=client.cookies.get('tire_local_session'), idempotency_key=key,
            request_hash=digest(payload), capture_id=capture, input=source_input, parser=parser, baseline=None,
            input_hash=digest({'input': source_input, 'parser': parser, 'baseline': None}),
            created_at=utcnow() - timedelta(minutes=3))
        db.add(run)
        db.commit()
    response = client.post('/v1/reparse/runs', json=payload, headers={'Idempotency-Key': key})
    assert response.json()['state'] == 'unknown' and not calls


def test_quality_loss_and_identity_change_are_candidates_only(setup, monkeypatch):
    from tire_api import parser_runtime
    client, database, _ = setup
    capture = seed_capture(client, database, baseline=True)
    baseline = totals(database)
    async def changed(_source, body, query, *_):
        values = hankook.parse_html(body.decode(), query)
        values[0]['load_index'] = '99'
        return {'payload': values[:1], 'receipt': {'synthetic_runtime': True}}
    monkeypatch.setattr(parser_runtime, 'parse_isolated', changed)
    result = create(client, capture).json()
    quality = result['completion']['quality']
    assert quality['baseline_rows'] == 2 and quality['lost_rows'] == 1
    assert quality['row_loss_ratio'] == .5 and quality['blocked']
    assert {'row_loss_threshold', 'tire_identity_changed'} <= set(quality['reason_codes'])
    assert result['completion']['diff']['identity_changed_row_keys']
    assert totals(database) == baseline
    assert review(client, result['id']).json()['accepted_as_facts'] is False


def test_exact_thirty_percent_field_loss_is_reported():
    from tire_api.reparse import compare_candidate
    # Ten known fields: five stable + load index + four facts.
    before = {'brand': 'Fixture', 'model': 'Fixture', 'manufacturer_product_code': 'F',
              'region': 'US', 'size': '205/45R17', 'load_index': '88',
              'facts': {'a': 1, 'b': 2, 'c': 3, 'd': 4}}
    after = {**before, 'facts': {'d': 4}}
    quality, _ = compare_candidate({'payload': [before]}, [after], 'tire')
    assert quality['known_fields'] == 10 and quality['lost_field_count'] == 3
    assert quality['field_loss_ratio'] == .3 and 'field_loss_threshold' in quality['reason_codes']


def test_vehicle_reparse_uses_existing_grouped_quality_and_source_identity(setup):
    client, database, _ = setup
    capture = seed_capture(client, database, source=xiaomi.SOURCE_ID,
                           body=json.dumps(source_document()), baseline=True)
    response = create(client, capture, source=xiaomi.SOURCE_ID)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['state'] == 'completed'
    assert set(result['completion']['quality']['groups']) == {'vehicle', 'trims', 'fitments'}
    assert result['input']['query'] == {'vehicle_id': xiaomi.CURRENT_ID}


def test_review_revision_concurrency_and_append_only_history(setup):
    client, database, _ = setup
    capture = seed_capture(client, database)
    result = create(client, capture).json()
    gate = Barrier(2)
    def apply(index):
        gate.wait(timeout=10)
        return review(client, result['id'], reason='合成并发审阅 ' + str(index))
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(apply, range(2)))
    assert sorted(reply.status_code for reply in replies) == [201, 409]
    revised = review(client, result['id'], revision=1, status='rejected').json()
    assert revised['review_revision'] == 2 and len(revised['reviews']) == 2
    assert revised['completion']['fingerprint'] == result['completion']['fingerprint']
    for model in (ReparseRun, ReparseCompletion, ReparseReview):
        with database.sessions() as db:
            db.delete(db.scalar(select(model)))
            with pytest.raises(ValueError, match='只能追加'):
                db.commit()


def test_baseline_later_changes_do_not_rewrite_candidate_or_historical_review(setup):
    client, database, _ = setup
    capture = seed_capture(client, database, baseline=True)
    first = create(client, capture).json()
    assert review(client, first['id']).status_code == 201
    values = hankook.parse_html(BODY, QUERY)
    values[0]['facts']['utqg_treadwear'] = 320
    seed_capture(client, database, baseline=True, variants=values, body=BODY + '\n')
    old = client.get('/v1/reparse/runs/' + first['id'] + '?mode=history').json()
    assert old['baseline_current'] is False and old['baseline'] == first['baseline']
    assert old['completion'] == first['completion'] and old['review_revision'] == 1


def test_catalog_failure_does_not_break_normal_api_or_existing_results(setup, monkeypatch):
    from tire_api import parser_runtime
    client, database, _ = setup
    capture, key = seed_capture(client, database), str(uuid4())
    payload = request_payload(client, capture)
    result = client.post('/v1/reparse/runs', json=payload, headers={'Idempotency-Key': key}).json()
    def broken(): raise OSError('private deployment path')
    monkeypatch.setattr(parser_runtime, 'parser_catalog', broken)
    assert client.get('/health').status_code == 200
    response = client.get('/v1/reparse/catalog?mode=history')
    assert response.status_code == 503 and 'private deployment path' not in response.text
    assert client.get('/v1/reparse/runs/' + result['id'] + '?mode=history').status_code == 200
    assert client.post('/v1/reparse/runs', json=payload, headers={'Idempotency-Key': key}).json()['id'] == result['id']


def verify_reparse_persistence(url):
    """Real child process, recorded public excerpt, no external HTTP or synthetic parser."""
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        capture_id = seed_capture(client, app.state.database, baseline=True)
        before = totals(app.state.database)
        response = create(client, capture_id)
        assert response.status_code == 201, response.text
        result = response.json()
        assert result['state'] == 'completed', result
        assert result['completion']['candidate'] and len(result['completion']['candidate']) == 2
        assert result['completion']['receipt']['isolation'] == 'process_fault_isolation'
        edited = review(client, result['id']).json()
        assert edited['review_revision'] == 1 and totals(app.state.database) == before
        checkpoint = {'session_id': client.cookies.get('tire_local_session'), 'capture_id': capture_id,
                      'run_id': result['id'], 'review_revision': 1,
                      'fingerprint': result['completion']['fingerprint'], 'raw_hash': result['input']['raw_hash']}
    assert_reparse_checkpoint(url, checkpoint)
    return checkpoint


def assert_reparse_checkpoint(url, checkpoint):
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        client.cookies.set('tire_local_session', checkpoint['session_id'])
        response = client.get('/v1/reparse/runs/' + checkpoint['run_id'] + '?mode=history')
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['completion']['fingerprint'] == checkpoint['fingerprint']
        assert result['review_revision'] == checkpoint['review_revision'] and result['accepted_as_facts'] is False
        with app.state.database.sessions() as db:
            from tire_api.captures import checked_capture_bytes
            body, _ = checked_capture_bytes(db, db.get(RawCapture, checkpoint['capture_id']))
            assert hashlib.sha256(body).hexdigest() == checkpoint['raw_hash']


def test_real_child_and_restart_preserve_frozen_experiment(tmp_path):
    verify_reparse_persistence('sqlite:///' + (tmp_path / 'real-child.db').as_posix())
