"""Pre-parser durability, including a real child process exiting inside the parser."""
import asyncio
from datetime import timedelta
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from tire_api.adapters import registry, xiaomi
from tire_api.adapters.robots import RobotsPolicy
from tire_api.adapters.transport import FetchResult, SourceAccessError
from tire_api.db import (AuditEvent, Database, FactVersion, QueryRun, RawCapture,
                         RejectedObservation, Snapshot, UserSession, Verification, utcnow)
from tire_api.domain import LiveQueryRequest
from tire_api.main import create_app
from tire_api.service import QueryService
from tire_api import parser_runtime
from tire_api.vehicles import VehicleSnapshot
from query_evidence_assertions import assert_frozen_query_evidence
from test_core import VARIANT, count

BODY = 'synthetic receipt\x00<script>window.__receiptExecuted=true</script>'
QUERY = {"query": {"model": "PSEV", "size": "265/40R20"}, "fallback_policy": "ask"}
URL = '/v1/sources/michelin-us/live-query'


@pytest.fixture(autouse=True)
def isolated_parser_bundles(tmp_path_factory, monkeypatch):
    # Sealed SHA/package paths must also fit Windows native path limits when the
    # caller keeps its pytest base directory inside the workspace artifacts.
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path_factory.mktemp('pb')))


class Transport:
    status = 200
    body = BODY
    error = False

    def __init__(self, *_): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def get(self, url, **_):
        if self.error:
            raise SourceAccessError('upstream_http_503')
        return FetchResult(self.status, url, self.body, 'text/html', '"receipt"', None)


async def robots(*_):
    return RobotsPolicy('', 'TireEvidenceResearch')


def failed_parser(*_):
    raise ValueError('synthetic-parser-error')


def configure(monkeypatch, parser=failed_parser):
    monkeypatch.setenv('TI_DISABLED_SOURCES', '')
    async def run(_source, body, query, _version, _digest, **_deployment):
        # Instrument the process boundary for transaction assertions, never a
        # production callable selector. Real children are covered separately.
        try:
            descriptor = parser_runtime.descriptor_for_manifest(_deployment['bundle_manifest'], _source)
            receipt = {
                **{key: descriptor[key] for key in ('source_id', 'parser_version', 'parser_digest', 'bundle_id', 'execution_digest')},
                'run_id': '0' * 32, 'exit_code': 0, 'reaped': True,
                'deployment_revision': _deployment['deployment_revision']}
            receipt['input_hash'] = parser_runtime.input_hash({**receipt, 'query': query}, body.encode())
            return {'payload': parser(body, query), 'receipt': receipt}
        except Exception:
            raise parser_runtime.ParserRunError('parser_schema_changed') from None
    monkeypatch.setattr(registry, 'parse_isolated', run)
    monkeypatch.setattr(registry, '_states', {})
    monkeypatch.setattr(registry, '_robots_policy', robots)
    monkeypatch.setattr(registry, 'SafeHttpClient', Transport)


def test_committed_receipt_is_visible_inside_parser_and_failure_has_no_facts(tmp_path, monkeypatch):
    app = create_app(f"sqlite:///{(tmp_path / 'receipt.db').as_posix()}")
    database = app.state.database
    observed = []

    def parser(*_):
        # Independent connection reads a committed row before parsing can return.
        with database.sessions() as db:
            capture = db.scalar(select(RawCapture))
            assert capture.raw_body == BODY.encode()
            assert db.get(QueryRun, capture.query_id).state == 'pending'
            assert db.scalar(select(AuditEvent).where(AuditEvent.action == 'raw_response_received'))
            assert db.scalar(select(Snapshot)) is None
            observed.append(capture.id)
        raise RuntimeError('synthetic parser failure')

    configure(monkeypatch, parser)
    with TestClient(app) as client:
        result = client.post(URL, json=QUERY).json()
        assert result['reason'] == 'parser_schema_changed'
        assert observed and count(database, RawCapture) == count(database, RejectedObservation) == 1
        assert all(count(database, model) == 0 for model in (Snapshot, FactVersion, Verification))
        assert client.get('/v1/captures').status_code == 422
        listing = client.get('/v1/captures?mode=history').json()
        row = listing['items'][0]
        assert row['query_state'] == 'consent_required' and not row['processing_unconfirmed']
        assert row['query'] == {'model': 'Pilot Sport EV', 'size': '265/40R20'}
        assert 'body' not in row and 'raw_body' not in row
        assert row['byte_count'] == len(BODY.encode())
        assert client.get('/v1/captures/' + row['id']).status_code == 422
        detail = client.get(row['evidence_path']).json()
        assert detail['query'] == row['query']
        assert detail['receipt_only'] and detail['body'] == BODY
        assert detail['raw_hash'] == hashlib.sha256(BODY.encode()).hexdigest()
        assert client.get('/v1/captures?mode=history&pending_only=true').json()['items'] == []
        assert client.get('/v1/captures?mode=history&source_id=other').json()['items'] == []
        with database.sessions() as db:
            saved = db.get(RawCapture, row['id'])
            saved.raw_body = b'overwrite'
            with pytest.raises(ValueError, match='只能追加'): db.commit()
            db.rollback()
            db.delete(db.get(RawCapture, row['id']))
            with pytest.raises(ValueError, match='只能追加'): db.commit()


@pytest.mark.parametrize('failure', ['insert', 'metadata'])
def test_failed_capture_prevents_parser_and_does_not_blame_source(tmp_path, monkeypatch, failure):
    parsed = []
    configure(monkeypatch, lambda *_: parsed.append(True))
    app = create_app(f"sqlite:///{(tmp_path / 'capture-fail.db').as_posix()}")
    database = app.state.database
    if failure == 'metadata':
        monkeypatch.setattr(Transport, 'body', '\ud800')

    def reject_insert(_conn, _cursor, sql, *_):
        if failure == 'insert' and sql.startswith('INSERT INTO raw_captures'):
            raise RuntimeError('private database details')

    with TestClient(app) as client:
        event.listen(database.engine, 'before_cursor_execute', reject_insert)
        try:
            response = client.post(URL, json=QUERY)
        finally:
            event.remove(database.engine, 'before_cursor_execute', reject_insert)
        assert response.status_code == 200
        assert response.json()['reason'] == 'evidence_capture_failed'
        assert 'private database details' not in response.text
        assert parsed == []
        assert all(count(database, model) == 0 for model in (RawCapture, RejectedObservation, Snapshot))
        assert registry._states[registry.SPECS['michelin-us'].origin]['failures'] == 0


def test_downstream_rollback_keeps_receipt_and_does_not_create_accepted_cache(tmp_path, monkeypatch):
    configure(monkeypatch, lambda *_: [{**VARIANT, 'model': 'Pilot Sport EV'}])
    monkeypatch.setattr(Transport, 'body', 'valid synthetic response')
    app = create_app(f"sqlite:///{(tmp_path / 'rollback.db').as_posix()}")
    original = QueryService.record_success

    def failing_ingest(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError('synthetic downstream transaction failure')

    monkeypatch.setattr(QueryService, 'record_success', failing_ingest)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post(URL, json=QUERY).status_code == 500
        assert count(app.state.database, RawCapture) == 1
        assert count(app.state.database, Snapshot) == count(app.state.database, FactVersion) == 0
        item = client.get('/v1/captures?mode=history&pending_only=true').json()['items'][0]
        assert item['processing_unconfirmed']


def test_304_keeps_original_receipt_and_does_not_journal_a_nonexistent_body(tmp_path, monkeypatch):
    configure(monkeypatch, lambda *_: [{**VARIANT, 'model': 'Pilot Sport EV'}])
    monkeypatch.setattr(Transport, 'body', 'valid synthetic response')
    app = create_app(f"sqlite:///{(tmp_path / '304.db').as_posix()}")
    with TestClient(app) as client:
        first = client.post(URL, json=QUERY).json()
        assert first['data_state'] == 'live'
        registry._states.clear()
        monkeypatch.setattr(Transport, 'status', 304)
        second = client.post(URL, json=QUERY).json()
        assert second['data_state'] == 'live_verified_304'
        assert count(app.state.database, RawCapture) == 1
        assert_frozen_query_evidence(first, second, expected_state='live_verified_304', reverified=True)


def test_capture_listing_never_selects_bodies_or_fact_tables(tmp_path, monkeypatch):
    configure(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'list.db').as_posix()}")
    statements = []

    def capture_sql(_conn, _cursor, sql, *_):
        if sql.lstrip().upper().startswith('SELECT'): statements.append(sql.lower())

    with TestClient(app) as client:
        client.post(URL, json=QUERY)
        event.listen(app.state.database.engine, 'before_cursor_execute', capture_sql)
        try:
            assert len(client.get('/v1/captures?mode=history&limit=1').json()['items']) == 1
        finally:
            event.remove(app.state.database.engine, 'before_cursor_execute', capture_sql)
    assert any('raw_captures' in sql for sql in statements)
    assert all('raw_body' not in sql and 'fact_versions' not in sql and 'snapshots' not in sql for sql in statements)


def test_receipt_alone_is_never_an_authorized_fallback(tmp_path, monkeypatch):
    configure(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'no-fallback.db').as_posix()}")
    with TestClient(app) as client:
        failed = client.post(URL, json=QUERY).json()
        assert count(app.state.database, RawCapture) == 1
        assert failed['variants'] == []
        consent = client.post('/v1/fallback-consents', json={
            'query_id': failed['query_id'], 'decision': 'allow', 'scope': 'once'}).json()
        permitted = client.post(URL, json={**QUERY, 'consent_id': consent['id']}).json()
        assert permitted['variants'] == [] and permitted['reason'] == 'no_matching_local_snapshot'
        assert count(app.state.database, RawCapture) == 1


def test_network_failure_cannot_create_a_received_body(tmp_path, monkeypatch):
    configure(monkeypatch)
    # No actual HTTP response obtained, including robots failures.
    async def denied(*_): raise SourceAccessError('robots_disallowed')
    monkeypatch.setattr(registry, '_robots_policy', denied)
    app = create_app(f"sqlite:///{(tmp_path / 'no-body.db').as_posix()}")
    with TestClient(app) as client:
        assert client.post(URL, json=QUERY).json()['reason'] == 'robots_disallowed'
        assert count(app.state.database, RawCapture) == 0


def test_cancelled_parser_leaves_unconfirmed_receipt(tmp_path, monkeypatch):
    def cancelled(*_): raise asyncio.CancelledError()
    configure(monkeypatch, cancelled)
    database = Database(f"sqlite:///{(tmp_path / 'cancel.db').as_posix()}")
    database.initialize()
    with database.sessions() as db:
        db.add(UserSession(id='cancel-test', expires_at=utcnow() + timedelta(hours=1)))
        db.commit()
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(QueryService(db, registry).execute('michelin-us', LiveQueryRequest.model_validate(QUERY), 'cancel-test'))
    with database.sessions() as db:
        capture = db.scalar(select(RawCapture))
        assert capture.raw_body == BODY.encode()
        assert db.get(QueryRun, capture.query_id).state == 'pending'
        assert db.scalar(select(Verification)) is None
    database.close()


def crash_inside_parser(url):
    """Simulate whole-service death after capture; distinct from parser death."""
    database = Database(url)
    database.initialize()
    with database.sessions() as db:
        db.add(UserSession(id='crash-test', expires_at=utcnow() + timedelta(hours=1)))
        db.commit()
        registry.SafeHttpClient = Transport
        registry._robots_policy = robots
        async def crash(*_, **_deployment): os._exit(73)
        registry.parse_isolated = crash
        asyncio.run(QueryService(db, registry).execute('michelin-us', LiveQueryRequest.model_validate(QUERY), 'crash-test'))
    raise AssertionError('parser did not terminate the process')


def test_actual_process_exit_preserves_pending_receipt_after_restart(tmp_path):
    url = f"sqlite:///{(tmp_path / 'crash.db').as_posix()}"
    environment = {**os.environ, 'TI_DISABLED_SOURCES': '',
                   'PYTHONPATH': os.pathsep.join([str(Path(__file__).parent), str(Path(__file__).parents[1])])}
    child = subprocess.run([sys.executable, '-c',
        'from test_raw_captures import crash_inside_parser; import sys; crash_inside_parser(sys.argv[1])', url],
        env=environment, capture_output=True, timeout=30)
    assert child.returncode == 73, child.stderr.decode(errors='replace')
    app = create_app(url)
    with TestClient(app) as client:
        rows = client.get('/v1/captures?mode=history&pending_only=true').json()['items']
        assert len(rows) == 1 and rows[0]['processing_unconfirmed']
        detail = client.get(rows[0]['evidence_path']).json()
        assert detail['body'] == BODY and detail['query_state'] == 'pending'
        assert all(count(app.state.database, model) == 0 for model in (Snapshot, FactVersion, Verification, RejectedObservation))


@pytest.mark.parametrize('capture_fails', [False, True])
def test_vehicle_parser_runs_only_after_durable_receipt(tmp_path, monkeypatch, capture_fails):
    class VehicleTransport(Transport):
        async def get(self, url, **_): return FetchResult(200, url, '', 'text/plain', None, None)
        async def post(self, url, **_): return FetchResult(200, url, BODY, 'application/json', None, None)

    app = create_app(f"sqlite:///{(tmp_path / 'vehicle.db').as_posix()}")
    parsed = []

    async def parse(*_, **_deployment):
        assert count(app.state.database, RawCapture) == 1
        parsed.append(True)
        raise parser_runtime.ParserRunError('parser_schema_changed')

    monkeypatch.setattr(xiaomi, 'SafeHttpClient', VehicleTransport)
    monkeypatch.setattr(xiaomi, 'parse_isolated', parse)
    monkeypatch.setattr(xiaomi, '_busy', False)
    monkeypatch.setattr(xiaomi, '_last_fetch', -float('inf'))
    monkeypatch.setattr(xiaomi, '_robots', {})
    monkeypatch.setattr(xiaomi, '_robots_requests', {})

    def fail(_conn, _cursor, sql, *_):
        if capture_fails and sql.startswith('INSERT INTO raw_captures'): raise RuntimeError('disk unavailable')

    with TestClient(app) as client:
        event.listen(app.state.database.engine, 'before_cursor_execute', fail)
        try:
            result = client.post(f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments', json={'fallback_policy': 'ask'}).json()
        finally:
            event.remove(app.state.database.engine, 'before_cursor_execute', fail)
        assert result['reason'] == ('evidence_capture_failed' if capture_fails else 'parser_schema_changed')
        assert parsed == ([] if capture_fails else [True])
        assert count(app.state.database, VehicleSnapshot) == 0
        rows = client.get('/v1/captures?mode=history').json()['items']
        assert len(rows) == (0 if capture_fails else 1)
        if rows: assert rows[0]['target_kind'] == 'vehicle'


def test_real_parser_child_crash_keeps_api_and_durable_evidence(tmp_path, monkeypatch):
    from test_parser_runtime import probe_child
    configure(monkeypatch)
    monkeypatch.setattr(registry, 'parse_isolated', parser_runtime.parse_isolated)
    probe_child(monkeypatch, tmp_path, 'crash')
    app = create_app(f"sqlite:///{(tmp_path / 'child-crash.db').as_posix()}")
    with TestClient(app) as client:
        result = client.post(URL, json=QUERY)
        assert result.status_code == 200 and result.json()['reason'] == 'parser_crashed'
        rows = client.get('/v1/captures?mode=history').json()['items']
        assert len(rows) == 1 and client.get(rows[0]['evidence_path']).json()['body'] == BODY
        assert count(app.state.database, RejectedObservation) == 1
        assert all(count(app.state.database, model) == 0 for model in (Snapshot, FactVersion, Verification))


def test_runtime_failures_still_open_origin_circuit(monkeypatch):
    configure(monkeypatch)
    calls = []
    async def failed(*_):
        calls.append(True)
        raise parser_runtime.ParserRunError('parser_crashed', {'reaped': True})
    monkeypatch.setattr(registry, 'parse_isolated', failed)
    for _ in range(3):
        result = asyncio.run(registry.fetch('michelin-us', QUERY['query']))
        assert result['parser_error'] == 'parser_crashed' and result['parser_receipt']['reaped']
        registry._states[registry.SPECS['michelin-us'].origin]['last'] = -float('inf')
    result = asyncio.run(registry.fetch('michelin-us', QUERY['query']))
    assert result['reason'] == 'circuit_open' and len(calls) == 3


def test_capture_pagination_preserves_source_and_pending_filters_without_reading_body():
    from tire_api.db import uid
    from tire_api.domain import digest
    app = create_app('sqlite://')
    with TestClient(app) as client:
        client.get('/health')
        base = utcnow()
        with app.state.database.sessions() as db:
            for index in range(23):
                source = 'hankook-us' if index < 21 else 'michelin-us'
                query = {'model': 'synthetic pagination'}
                run = QueryRun(id=uid(), session_id=client.cookies.get('tire_local_session'), source_id=source,
                    query=query, query_key=digest(query), state='pending' if index % 2 == 0 else 'source_unavailable',
                    fallback_policy='never')
                db.add(run); db.flush()
                db.add(RawCapture(id=f'capture-{index:02}', query_id=run.id, source_id=source,
                    query_key=run.query_key, target_kind='tire', source_url='https://example.com/fixture',
                    raw_body=b'fixture', raw_hash=hashlib.sha256(b'fixture').hexdigest(), byte_count=7,
                    content_type='text/html', parser_version='fixture@pagination',
                    observed_at=base + timedelta(seconds=index)))
            db.commit()
        statements = []
        def record(_conn, _cursor, sql, *_): statements.append(sql)
        event.listen(app.state.database.engine, 'before_cursor_execute', record)
        try:
            pages = [client.get(f'/v1/captures?mode=history&source_id=hankook-us&limit=10&offset={offset}').json()
                     for offset in (0, 10, 20)]
            pending = client.get('/v1/captures?mode=history&source_id=hankook-us&pending_only=true&limit=10&offset=10').json()
        finally:
            event.remove(app.state.database.engine, 'before_cursor_execute', record)
        assert [page['total'] for page in pages] == [21, 21, 21]
        ids = [row['id'] for page in pages for row in page['items']]
        assert ids == [f'capture-{index:02}' for index in reversed(range(21))]
        assert pending['total'] == 11 and [row['id'] for row in pending['items']] == ['capture-00']
        assert not any('raw_captures.raw_body' in sql or 'parsed_variants' in sql for sql in statements)
        assert client.get('/v1/captures?mode=history&offset=-1').status_code == 422
