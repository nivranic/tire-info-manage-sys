"""Normal API evidence, query ownership and Chinese recall fallback permissions."""
from copy import deepcopy
from hashlib import sha256

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, text

from admin_support import register_admin
from tire_api.adapters import samr as source
from tire_api.db import RawCapture, RejectedObservation
from tire_api.main import create_app
from tire_api.query_owner_models import QueryRunOwnerReceipt
from tire_api.query_fallback_policies import QueryFallbackUse
from tire_api.samr_recalls import SamrRecallSnapshot, SamrRecallVerification
from test_query_fallback_policies49 import allow, scope
from test_samr import IDENTITY, NOTICE, SEARCH, notice_body, search_body


class FixtureRegistry:
    def sources(self):
        return [source.source_metadata()]


class FixtureAdapter:
    def __init__(self):
        self.offline, self.not_modified, self.mutate = False, False, None
        self.reason = 'upstream_timeout'
        self.calls = []

    async def fetch(self, query, cached=None, *, on_observation=None):
        self.calls.append(deepcopy(query))
        if self.offline:
            return {'status': 'unavailable', 'reason': self.reason}
        value = {'status': 'not_modified' if self.not_modified else 'ok', 'url': source.query_url(query),
            'content_type': 'application/json' if query['operation'] == 'search' else 'text/html',
            'parser_version': source.PARSER_VERSION, 'parser_identity': deepcopy(IDENTITY), 'etag': '"synthetic"'}
        if not self.not_modified:
            body = search_body(page=int(query['page'])) if query['operation'] == 'search' else notice_body(query['reference'])
            value.update(body=body, document=source.parse_document(body, query))
            if on_observation:
                on_observation(value)
        if self.mutate:
            self.mutate(value)
        return value


@pytest.fixture
def context(tmp_path):
    app = create_app('sqlite:///' + (tmp_path / 'samr.sqlite').as_posix(), FixtureRegistry())
    adapter = FixtureAdapter()
    app.state.samr_recall_adapter = adapter
    with TestClient(app) as client:
        client.get('/v1/source-settings')
        yield client, adapter, app.state.database


def run(client, query=NOTICE, **options):
    response = client.post('/v1/samr-recalls/query', json={'query': query, **options})
    assert response.status_code == 200, response.text
    return response.json()


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_online_api_captures_search_notice_and_stable_repeated_evidence(context):
    client, adapter, database = context
    search = run(client, SEARCH)
    first = run(client)
    repeated = run(client)
    assert search['document']['declared_total'] == 1
    assert first['data_state'] == repeated['data_state'] == 'live'
    notice = first['document']['notice']
    assert notice['published_date'] == '2021-07-23' and notice['pub_date_raw'].startswith('2026-')
    assert notice['applicability'] == 'not_assessed'
    assert repeated['provenance'] == first['provenance']
    assert repeated['snapshot_observed_at'] == first['snapshot_observed_at']
    evidence = client.get(first['provenance'][0]['evidence_path'])
    assert evidence.status_code == 200
    assert sha256(evidence.json()['body'].encode()).hexdigest() == first['provenance'][0]['raw_hash']
    assert evidence.json()['access_basis']['redistribution_license'] == 'unverified'
    assert count(database, SamrRecallSnapshot) == 2 and count(database, SamrRecallVerification) == 3
    assert count(database, RawCapture) == 3
    with database.sessions() as db:
        assert {row.target_kind for row in db.scalars(select(RawCapture))} == {'recall'}


def test_single_use_consent_and_explicit_history_are_independent(context):
    client, adapter, database = context
    first = run(client)
    adapter.offline = True
    failed = run(client)
    assert failed['data_state'] == 'consent_required' and failed['document'] is None
    response = client.post('/v1/fallback-consents', json={'query_id': failed['query_id'], 'decision': 'allow', 'scope': 'once'})
    assert response.status_code == 201
    token = response.json()['id']
    wrong = client.post('/v1/samr-recalls/query', json={'query': SEARCH, 'consent_id': token})
    assert wrong.status_code == 403
    assert run(client, consent_id=token)['document'] == first['document']
    assert client.post('/v1/samr-recalls/query', json={'query': NOTICE, 'consent_id': token}).status_code in {403, 409}
    assert run(client, fallback_policy='never')['data_state'] == 'source_unavailable'
    calls = len(adapter.calls)
    history = client.get('/v1/samr-recalls/history', params={**NOTICE, 'mode': 'history'})
    assert history.status_code == 200 and history.json()['document'] == first['document']
    assert len(adapter.calls) == calls and count(database, SamrRecallVerification) == 1
    assert client.get('/v1/samr-recalls/history', params=NOTICE).status_code == 422


def test_consent_is_session_bound(context):
    client, adapter, _ = context
    adapter.offline = True
    failed = run(client)
    token = client.post('/v1/fallback-consents', json={'query_id': failed['query_id'], 'decision': 'allow', 'scope': 'once'}).json()['id']
    client.cookies.clear()
    response = client.post('/v1/samr-recalls/query', json={'query': NOTICE, 'consent_id': token})
    assert response.status_code == 403


@pytest.mark.parametrize('query,kind', [(SEARCH, 'samr_recall_search'), (NOTICE, 'samr_recall_notice')])
def test_programmatic_policy_records_permission_and_preserves_online_first(context, query, kind):
    client, adapter, database = context
    client.get('/v1/source-settings')
    first = run(client, query)
    allow(client, selected=scope(source.SOURCE_ID, kind))
    assert run(client, query)['data_state'] == 'live'
    assert count(database, QueryFallbackUse) == 0
    adapter.offline = True
    restored = run(client, query)
    assert restored['data_state'] == 'local_snapshot' and restored['document'] == first['document']
    assert restored['fallback_authorization']['use']['query_kind'] == kind
    assert count(database, QueryFallbackUse) == 1
    other = NOTICE if query == SEARCH else SEARCH
    assert run(client, other)['data_state'] == 'consent_required'


def test_other_regulatory_query_kinds_cannot_authorize_chinese_history(context):
    client, _, _ = context
    for kind in ['recall_campaign', 'safety_gate_report']:
        response = client.post('/v1/query-fallback-policies:preview', json={
            'mode': 'query_allow', 'scope': scope(source.SOURCE_ID, kind)})
        assert response.status_code == 422
        assert response.json()['detail']['code'] == 'query_fallback_source_kind_mismatch'


def test_non_network_failure_keeps_continuous_fallback_closed(context):
    client, adapter, database = context
    run(client)
    allow(client, selected=scope(source.SOURCE_ID, 'samr_recall_notice'))
    adapter.offline, adapter.reason = True, 'samr_recall_schema_changed'
    assert run(client)['document'] is None
    assert count(database, QueryFallbackUse) == 0


def test_304_keeps_snapshot_and_rejects_changed_parser_identity(context):
    client, adapter, database = context
    first = run(client)
    adapter.not_modified = True
    verified = run(client)
    assert verified['data_state'] == 'live_verified_304'
    assert verified['provenance'] == first['provenance']
    adapter.mutate = lambda value: value['parser_identity'].update(deployment_revision=2)
    assert run(client)['data_state'] == 'consent_required'
    assert count(database, SamrRecallVerification) == 2


def test_invalid_parent_document_is_retained_and_not_adopted(context):
    client, adapter, database = context
    adapter.mutate = lambda value: value['document']['notice'].update(article_id='b' * 32)
    failed = run(client)
    assert failed['data_state'] == 'consent_required' and failed['document'] is None
    assert count(database, SamrRecallSnapshot) == 0 and count(database, RejectedObservation) == 1


def test_owner_receipt_and_source_pause_apply_to_normal_entry(context):
    from test_source_settings import decision, revise
    client, adapter, database = context
    register_admin(client)
    first = run(client)
    assert count(database, QueryRunOwnerReceipt) == 1
    changed = revise(client, decision(client, 'pause', source=source.SOURCE_ID), source=source.SOURCE_ID)
    assert changed.status_code == 201
    calls = len(adapter.calls)
    blocked = run(client)
    assert blocked['reason'] == 'source_paused' and blocked['document'] is None
    assert len(adapter.calls) == calls
    assert client.get(first['provenance'][0]['evidence_path']).status_code == 200


def test_snapshot_is_append_only_and_raw_tampering_is_detected(context):
    client, _, database = context
    first = run(client)
    with database.sessions() as db:
        row = db.scalar(select(SamrRecallSnapshot))
        row.body = 'changed'
        with pytest.raises(ValueError):
            db.commit()
        db.rollback()
    with database.engine.begin() as connection:
        connection.execute(text("UPDATE samr_recall_snapshots SET body = 'changed'"))
    assert client.get(first['provenance'][0]['evidence_path']).status_code == 503
