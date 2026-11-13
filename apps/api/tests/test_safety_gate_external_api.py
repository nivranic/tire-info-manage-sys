"""Owned, licensed weekly alerts over the actual external HTTP boundary."""
from uuid import uuid4
import base64
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from admin_support import ADMIN_PASSWORD, register_admin
from test_safety_gate import FixtureAdapter, FixtureRegistry, QUERY, report, run
from test_safety_gate_external_governance import approve, proposal
from tire_api.external_fact_governance import GovernanceStore
from tire_api.main import create_app
from tire_api.adapters import safety_gate as source


class MultiAdapter(FixtureAdapter):
    count = 3
    long_fields = False

    async def fetch(self, query, cached=None, *, on_observation=None):
        value = await super().fetch(query, cached, on_observation=None)
        if value['status'] == 'ok' and query['operation'] == 'report':
            value.update(body=report(self.count))
            if self.long_fields:
                value['body'] = value['body'].replace('<brand>SYNTHETIC</brand>', '<brand>'+'b'*60000+'</brand>')
                value['body'] = value['body'].replace('<name>Synthetic tyre</name>', '<name>'+'n'*60000+'</name>')
            value['document'] = source.parse_xml(value['body'], query)
        if on_observation and 'body' in value:
            on_observation(value)
        return value


@pytest.fixture
def external_case(tmp_path):
    app = create_app('sqlite:///' + (tmp_path / 'external.db').as_posix(), FixtureRegistry(),
        external_safety_gate_grant='synthetic-safety-grant')
    adapter = MultiAdapter()
    app.state.safety_gate_adapter = adapter
    with TestClient(app) as client:
        register_admin(client)
        yield client, adapter, app.state.database


def key(client, scopes=None):
    response = client.post('/v1/api-keys', headers={'Idempotency-Key': str(uuid4())}, json={
        'name': 'Synthetic weekly reader', 'scopes': scopes or ['safety-gate:read'],
        'expires_in_days': 7, 'acknowledged': True})
    assert response.status_code == 201
    return response.json()


def licensed(client, database):
    from tire_api.external_safety_gate import REQUIRED_FIELDS
    result = run(client)
    store = GovernanceStore(database.engine)
    approve(store, store.authenticate('admin', ADMIN_PASSWORD),
        proposal(result, fields=sorted(REQUIRED_FIELDS | {'facts.brand'})))
    return result, store


def read(client, token, query_id, **params):
    return client.get('/external/v1/safety-gate-reports/' + QUERY['report_id'] + '/alerts',
        headers={'Authorization': 'Bearer ' + token}, params={'query_id': query_id, 'mode': 'history', **params})


def test_licensed_owned_report_is_projected_without_fetch(external_case):
    client, adapter, database = external_case
    result, _store = licensed(client, database)
    token = key(client)['token']
    calls = len(adapter.calls)
    response = read(client, token, result['query_id'])
    assert response.status_code == 200
    value = response.json()
    assert value['schema'] == 'external-safety-gate-alert-page@1'
    assert value['data_state'] == 'local_snapshot' and value['source_refresh_performed'] is False
    assert value['items'][0]['facts'] == {'brand': 'SYNTHETIC'}
    assert value['items'][0]['applicability'] == 'not_assessed'
    assert value['observation']['raw_hash'] == result['provenance'][0]['raw_hash']
    assert value['query_id'] == result['query_id']
    assert value['next_cursor'] is None and len(adapter.calls) == calls
    assert response.headers['cache-control'] == 'no-store'
    assert 'set-cookie' not in response.headers


def cursor_body(value):
    encoded = value.split('.')[0]
    return json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))


def test_three_pages_are_fixed_to_one_owned_report_and_expiry(external_case):
    client, adapter, database = external_case
    result, _ = licensed(client, database)
    token = key(client)['token']
    first = read(client, token, result['query_id'], limit=1).json()
    second = read(client, token, result['query_id'], limit=1, cursor=first['next_cursor']).json()
    third = read(client, token, result['query_id'], limit=1, cursor=second['next_cursor']).json()
    assert [page['items'][0]['alert_id'] for page in (first, second, third)] == ['900001', '900002', '900003']
    assert third['next_cursor'] is None
    assert cursor_body(first['next_cursor'])['expires'] == cursor_body(second['next_cursor'])['expires']
    assert read(client, token, result['query_id'], limit=1, cursor=first['next_cursor']).json() == second
    assert len(adapter.calls) == 1


@pytest.mark.parametrize('params', [{'mode':'live'}, {'mode':''}, {'limit':'0'}, {'limit':'21'},
    {'limit':'01'}, {'limit':'1.0'}, {'cursor':''}, {'cursor':'x'*2049}, {'unexpected':'1'}, {'query_id':'../other'}])
def test_closed_query_contract(external_case, params):
    client, _, database = external_case
    result, _ = licensed(client, database)
    token = key(client)['token']
    response = client.get('/external/v1/safety-gate-reports/900001/alerts', headers={'Authorization':'Bearer '+token},
        params={'query_id':result['query_id'], 'mode':'history', **params})
    assert response.status_code == 422


def test_duplicate_query_and_cookie_only_do_not_authorize(external_case):
    client, _, database = external_case
    result, _ = licensed(client, database)
    token = key(client)['token']
    path = '/external/v1/safety-gate-reports/900001/alerts'
    params = [('query_id',result['query_id']), ('mode','history'), ('mode','history')]
    assert client.get(path, headers={'Authorization':'Bearer '+token}, params=params).status_code == 422
    assert client.get(path, params={'query_id':result['query_id'], 'mode':'history'}).status_code == 401
    assert client.post(path, headers={'Authorization':'Bearer '+token}).status_code == 405


@pytest.mark.parametrize('scopes', [['sources:read'], ['facts:read']])
def test_other_scopes_do_not_grant_alerts(external_case, scopes):
    client, _, database = external_case
    result, _ = licensed(client, database)
    assert read(client, key(client, scopes)['token'], result['query_id']).status_code == 403


def test_four_scopes_work_without_breaking_old_routes(external_case):
    client, _, database = external_case
    result, _ = licensed(client, database)
    token = key(client, ['facts:read','safety-gate:read','sources:read','webhooks:read'])['token']
    assert read(client, token, result['query_id']).status_code == 200
    assert client.get('/external/v1/sources', headers={'Authorization':'Bearer '+token}).status_code == 200
    response = client.get('/external/v1/tire-facts', headers={'Authorization':'Bearer '+token},
        params={'source_id':source.SOURCE_ID, 'query_id':result['query_id'], 'verification_id':'missing'})
    assert response.status_code == 404


def test_cross_owner_and_anonymous_queries_stay_private(external_case):
    client, _, database = external_case
    result, _ = licensed(client, database)
    assert client.post('/v1/auth/logout').status_code == 200
    anonymous = run(client)
    register_admin(client, username='other_synthetic_owner')
    token = key(client)['token']
    assert read(client, token, result['query_id']).status_code == 404
    assert read(client, token, anonymous['query_id']).status_code == 404
    own = run(client)
    assert read(client, token, own['query_id']).status_code == 200


def test_missing_license_and_required_fields_fail_closed(external_case):
    from tire_api.external_safety_gate import REQUIRED_FIELDS
    client, _, database = external_case
    result = run(client)
    token = key(client)['token']
    assert read(client, token, result['query_id']).status_code == 404
    store = GovernanceStore(database.engine)
    approve(store, store.authenticate('admin', ADMIN_PASSWORD), proposal(result, fields=sorted(REQUIRED_FIELDS - {'identity.alert_id'})))
    assert read(client, token, result['query_id']).status_code == 404


def test_revoked_license_and_key_are_rechecked_each_page(external_case):
    client, _, database = external_case
    result, store = licensed(client, database)
    created = key(client)
    page = read(client, created['token'], result['query_id'], limit=1).json()
    actor = store.authenticate('admin', ADMIN_PASSWORD)
    request = {'schema':'external-fact-governance-request@1', 'action':'withdraw',
        'grant_id':'synthetic-safety-grant', 'reason':'Synthetic withdrawal'}
    prepared = store.preview(actor, request)
    store.append(actor, request, expected_revision=prepared['expected_revision'], expected_head=prepared['expected_head'],
        expected_preview_fingerprint=prepared['fingerprint'], idempotency_key=str(uuid4()))
    assert read(client, created['token'], result['query_id'], limit=1, cursor=page['next_cursor']).status_code == 404
    response = client.post('/v1/api-keys/'+created['key']['id']+'/revoke',
        headers={'Idempotency-Key':str(uuid4())}, json={'acknowledged':True})
    assert response.status_code == 200
    assert read(client, created['token'], result['query_id']).status_code == 401


def test_policy_reapproval_invalidates_old_window(external_case):
    from tire_api.external_safety_gate import REQUIRED_FIELDS
    client, _, database = external_case
    result, store = licensed(client, database)
    token = key(client)['token']
    first = read(client, token, result['query_id'], limit=1).json()
    approve(store, store.authenticate('admin', ADMIN_PASSWORD),
        proposal(result, fields=sorted(REQUIRED_FIELDS | {'facts.brand','facts.barcode'})))
    assert read(client, token, result['query_id'], limit=1, cursor=first['next_cursor']).status_code == 409
    fresh = read(client, token, result['query_id']).json()
    assert fresh['items'][0]['facts'] == {'brand':'SYNTHETIC', 'barcode':None}


def test_cursor_cannot_cross_key_query_limit_or_expiry(external_case, monkeypatch):
    from datetime import timedelta
    from tire_api import external_api
    client, _, database = external_case
    result, _ = licensed(client, database)
    first_key, second_key = key(client)['token'], key(client)['token']
    page = read(client, first_key, result['query_id'], limit=1).json()
    cursor = page['next_cursor']
    assert read(client, second_key, result['query_id'], limit=1, cursor=cursor).status_code == 422
    assert read(client, first_key, result['query_id'], limit=2, cursor=cursor).status_code == 422
    another = run(client)
    assert read(client, first_key, another['query_id'], limit=1, cursor=cursor).status_code == 422
    now = external_api.utcnow()
    monkeypatch.setattr(external_api, 'utcnow', lambda: now + timedelta(seconds=901))
    assert read(client, first_key, result['query_id'], limit=1, cursor=cursor).status_code == 422


@pytest.mark.parametrize('sql,value', [
    ('UPDATE safety_gate_snapshots SET body=:value', 'tampered'),
    ('UPDATE safety_gate_snapshots SET document_hash=:value', '0'*64),
    ('UPDATE safety_gate_verifications SET status=:value', 'unavailable'),
    ('UPDATE query_runs SET state=:value', 'consent_required'),
    ('UPDATE safety_gate_verifications SET parser_identity=:value', '{"bad":true}'),
])
def test_evidence_corruption_is_rejected_on_continuation(external_case, sql, value):
    client, _, database = external_case
    result, _ = licensed(client, database)
    token = key(client)['token']
    first = read(client, token, result['query_id'], limit=1).json()
    with database.engine.begin() as connection:
        connection.execute(text(sql), {'value':value})
    assert read(client, token, result['query_id'], limit=1, cursor=first['next_cursor']).status_code == 404


def test_index_failed_and_wrong_report_are_not_successful_report_queries(external_case):
    client, adapter, database = external_case
    result, _ = licensed(client, database)
    token = key(client)['token']
    index = run(client, {'operation':'reports'})
    assert read(client, token, index['query_id']).status_code == 404
    adapter.offline = True
    failed = run(client)
    assert read(client, token, failed['query_id']).status_code == 404
    assert client.get('/external/v1/safety-gate-reports/900002/alerts', headers={'Authorization':'Bearer '+token},
        params={'query_id':result['query_id'], 'mode':'history'}).status_code == 404


def test_capacity_is_checked_before_snapshot_materialization(external_case, monkeypatch):
    from tire_api.external_safety_gate import SafetyGateReadBudget
    from tire_api.safety_gate import SafetyGateSnapshot
    client, _, database = external_case
    result, _ = licensed(client, database)
    token = key(client)['token']
    with database.engine.begin() as connection:
        connection.execute(text('UPDATE safety_gate_snapshots SET body=:body'), {'body':'x'*(8*1024*1024+1)})
    original = SafetyGateReadBudget.load
    loaded = []
    def track(self, db, model, *args, **kwargs):
        value = original(self, db, model, *args, **kwargs)
        if model is SafetyGateSnapshot:
            loaded.append(True)
        return value
    monkeypatch.setattr(SafetyGateReadBudget, 'load', track)
    assert read(client, token, result['query_id']).status_code == 404
    assert loaded == []


def test_bearer_is_reauthenticated_after_middleware(external_case, monkeypatch):
    from tire_api.external_safety_gate import SafetyGateReader
    from tire_api.external_api_models import ApiKeyRevocation
    from tire_api.db import utcnow
    from tire_api.webhook_delivery import seal
    client, _, database = external_case
    result, _ = licensed(client, database)
    created = key(client)
    original = SafetyGateReader.capture_credential
    def revoke(self, headers):
        captured = original(self, headers)
        with database.sessions() as db:
            db.add(seal(ApiKeyRevocation(key_id=created['key']['id'], revoked_at=utcnow(), reason='user')))
            db.commit()
        return captured
    monkeypatch.setattr(SafetyGateReader, 'capture_credential', revoke)
    assert read(client, created['token'], result['query_id']).status_code == 401


def test_large_permitted_report_requires_smaller_response_pages(external_case):
    from tire_api.external_safety_gate import REQUIRED_FIELDS
    client, adapter, database = external_case
    adapter.count, adapter.long_fields = 20, True
    result = run(client)
    store = GovernanceStore(database.engine)
    approve(store, store.authenticate('admin', ADMIN_PASSWORD), proposal(result, fields=sorted(REQUIRED_FIELDS | {'facts.brand','facts.name'})))
    token = key(client)['token']
    assert read(client, token, result['query_id'], limit=20).status_code == 404
    assert read(client, token, result['query_id'], limit=1).status_code == 200


def test_304_query_reuses_approved_snapshot_but_preserves_new_owner_receipt(external_case):
    client, adapter, database = external_case
    first, _ = licensed(client, database)
    adapter.not_modified = True
    second = run(client)
    assert second['data_state'] == 'live_verified_304'
    value = read(client, key(client)['token'], second['query_id'])
    assert value.status_code == 200
    assert value.json()['observation']['snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert value.json()['query_id'] == second['query_id']


def test_unknown_reader_backend_fails_before_connection():
    from types import SimpleNamespace
    from tire_api.external_safety_gate import SafetyGateReader
    from tire_api.external_fact_reader import ReaderError
    class UnopenedEngine:
        dialect = SimpleNamespace(name='unsupported')
        def connect(self):
            pytest.fail('unsupported_reader_must_not_connect')
    reader = SafetyGateReader(UnopenedEngine())
    with pytest.raises(ReaderError, match='reader_backend_unsupported'):
        reader.read_page(None, report_id='900001', query_pairs=(('query_id','synthetic'),('mode','history')))
