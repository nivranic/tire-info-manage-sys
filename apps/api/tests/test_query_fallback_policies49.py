"""Fresh synthetic owned-policy, audience and durable-consumption boundaries."""
import asyncio
from copy import deepcopy
from datetime import timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select, update

from tire_api.db import FallbackConsent, QueryRun, UserSession, uid, utcnow
from tire_api.domain import LiveQueryRequest
from tire_api.main import create_app
from tire_api.query_fallback_policies import QueryFallbackPolicyRevision, QueryFallbackPreview, QueryFallbackUse
from tire_api.service import QueryService
from admin_support import register_admin
from test_core import FixtureRegistry, QUERY, grant, live


class FourDomainRegistry(FixtureRegistry):
    def sources(self):
        return super().sources() + [{'id': 'nhtsa-us-recalls', 'name': 'Synthetic regulator',
                                    'status': 'ready', 'target_kind': 'recall', 'region': 'US'}]


class NormalizedVehicleFixture:
    """Already normalized synthetic data; no Parser implementation is called."""
    def __init__(self):
        self.offline = False
        self.calls = []
        self.payload = {'vehicle': {'id': 'synthetic-vehicle', 'manufacturer': {'id': 'synthetic-maker', 'name': 'Synthetic'},
            'model': 'Synthetic', 'generation': 'Synthetic', 'region': 'CN', 'model_year': 2026,
            'source_vehicle_id': 'synthetic'},
            'trims': [{'id': 'synthetic-trim', 'name': 'Synthetic', 'source_trim_id': 'synthetic',
                       'wheel_option_ids': ['synthetic-wheel']}],
            'fitments': [{'id': 'synthetic-wheel', 'trim_id': 'synthetic-trim', 'trim_name': 'Synthetic',
                'wheel_option_name': 'Synthetic', 'availability': 'standard', 'wheel_diameter_inches': 20,
                'front': {'size': '245/40R20'}, 'rear': {'size': '265/40R20'}, 'staggered': True,
                'constraints': [], 'source_description': 'Synthetic; no SKU/OE assertion',
                'evidence_locator': 'synthetic/wheel'}], 'footnotes': ['Synthetic only'], 'documents': []}

    def candidates(self):
        return [{'id': 'synthetic-vehicle', 'status': 'ready'}]

    async def fetch(self, vehicle_id, *, on_observation=None):
        from tire_api.adapters import xiaomi
        self.calls.append(vehicle_id)
        if self.offline:
            return {'status': 'unavailable', 'reason': 'upstream_timeout'}
        return {'status': 'ok', 'url': xiaomi.API_URL, 'body': 'synthetic vehicle raw',
                'content_type': 'application/json', 'parser_version': 'synthetic-vehicle@1',
                'payload': deepcopy(self.payload)}


class NetworkRecallFixtures:
    def __init__(self):
        from test_recalls import RecallFixture
        from test_recall_discovery import SearchFixture
        self.campaign, self.search = RecallFixture(), SearchFixture()
        self.offline = False

    async def fetch(self, query, cached=None, *, on_observation=None):
        if self.offline:
            return {'status': 'unavailable', 'reason': 'upstream_network_error'}
        adapter = self.campaign if 'campaign_number' in query else self.search
        return await adapter.fetch(query, cached, on_observation=on_observation)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for name in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(name, '0')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    registry = FixtureRegistry()
    app = create_app('sqlite:///' + (tmp_path / 'policy.sqlite').as_posix(), registry)
    with TestClient(app) as client:
        client.get('/v1/source-settings')  # Explicit normal bootstrap before owned policy API.
        register_admin(client)
        yield client, registry, app.state.database


def scope(source='fixture', kind='tire', generation=0):
    return {'kind': 'query', 'query_kind': kind,
            'sources': [{'source_id': source, 'access_generation': generation}]}


def preview(client, mode='query_allow', selected=None, **changes):
    return client.post('/v1/query-fallback-policies:preview', json={
        'mode': mode, 'scope': selected or scope(), **changes})


def apply(client, prepared, key=None, **changes):
    return client.post('/v1/query-fallback-policies:apply', headers={'Idempotency-Key': key or uid()}, json={
        'preview_id': prepared['preview_id'], 'expected_fingerprint': prepared['fingerprint'],
        'expected_revision': prepared['expected_revision'], 'allow_continuous_history_fallback': True, **changes})


def allow(client, mode='query_allow', selected=None, **changes):
    response = preview(client, mode, selected, **changes)
    assert response.status_code == 200, response.text
    response = apply(client, response.json())
    assert response.status_code == 200, response.text
    return response.json()


def outage(registry, reason='upstream_timeout'):
    registry.result = {'status': 'unavailable', 'reason': reason}


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def trace(database):
    statements = []
    def sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())
    def commit(_conn):
        statements.append('COMMIT')
    event.listen(database.engine, 'before_cursor_execute', sql)
    event.listen(database.engine, 'commit', commit)
    return statements


def business_reads(statements):
    return [text for text in statements if text.startswith('select') and 'snapshots.parsed_variants' in text]


def test_metadata_preview_denial_and_owner_header_read_no_answer_material(setup):
    client, registry, database = setup
    live(client)
    statements = trace(database)
    prepared = preview(client).json()
    assert not business_reads(statements)
    assert prepared['proposed_policy']['scope'] == scope()
    assert apply(client, prepared, allow_continuous_history_fallback=False).status_code == 422
    assert not business_reads(statements) and count(database, QueryFallbackPolicyRevision) == 0
    metadata = client.get('/v1/source-settings')
    owner = metadata.headers['X-Tire-Offline-Owner-Scope']
    assert len(owner) == 64 and owner == prepared['owner_scope_id']
    assert 'X-Tire-Offline-Owner-Scope' not in client.get('/v1/tire-query-filters').headers
    outage(registry)
    pending = live(client).json()
    assert pending['data_state'] == 'consent_required' and pending['variants'] == []


def test_apply_once_idempotency_cas_owner_and_append_only(setup):
    client, _, database = setup
    prepared = preview(client).json()
    key = uid()
    first = apply(client, prepared, key).json()
    assert apply(client, prepared, key).json() == first
    assert apply(client, prepared).status_code == 409
    assert apply(client, prepared, key, expected_revision=1).status_code == 409
    with TestClient(client.app) as other:
        assert other.get('/v1/query-fallback-policies').status_code == 401
        other.get('/v1/source-settings')
        assert apply(other, prepared).status_code == 404
        assert other.get('/v1/query-fallback-policies').json()['items'] == []
    changed = preview(client, 'ask', policy_id=first['id'], expected_revision=first['revision']).json()
    second = apply(client, changed).json()
    assert second['revision'] == 2 and second['mode'] == 'ask'
    with database.sessions() as db:
        row = db.scalar(select(QueryFallbackPolicyRevision))
        row.state = 'revoked'
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()


def test_policy_receipt_is_durable_before_business_read_and_each_attempt_unique(setup):
    client, registry, database = setup
    original = live(client).json()
    policy = allow(client)
    statements = trace(database)
    outage(registry)
    first = live(client).json()
    assert first['data_state'] == 'local_snapshot' and first['variants'][0]['id'] == original['variants'][0]['id']
    use = first['fallback_authorization']['use']
    assert first['consent_id'] is None and first['fallback_authorization']['type'] == 'policy_once'
    assert use['policy_id'] == policy['id'] and use['policy_revision'] == policy['revision']
    assert use['query_kind'] == 'tire' and use['audience'] == 'programmatic'
    claimed = next(index for index, text in enumerate(statements) if text.startswith('insert into query_fallback_uses'))
    read = next(index for index, text in enumerate(statements) if index > claimed and text in business_reads(statements))
    assert 'COMMIT' in statements[claimed + 1:read]
    second = live(client).json()
    assert second['fallback_authorization']['use']['id'] != use['id']
    assert count(database, QueryFallbackUse) == 2


def test_all_tire_filters_are_kept_in_policy_authorized_selection(setup):
    client, registry, _ = setup
    live(client)
    allow(client)
    outage(registry)
    filters = [{'field': 'utqg_treadwear', 'op': 'gte', 'value': 301}]
    result = live(client, {**QUERY, 'filters': filters}).json()
    assert result['data_state'] == 'local_snapshot' and result['variants'] == []
    assert result['selection']['filters'] == filters and result['selection']['excluded_count'] == 1
    assert result['fallback_authorization']['use']['query_kind'] == 'tire'


def test_never_wins_over_allow_and_blocks_stale_explicit_once_not_manual_history(setup):
    client, registry, database = setup
    original = live(client).json()
    outage(registry)
    failed = live(client).json()
    token = grant(client, failed['query_id']).json()['id']
    allow(client)
    never = allow(client, 'never')
    statements = trace(database)
    result = live(client).json()
    assert result['data_state'] == 'source_unavailable' and result['variants'] == []
    assert live(client, {**QUERY, 'consent_id': token}).status_code == 403
    assert not business_reads(statements) and count(database, QueryFallbackUse) == 0
    variant = original['variants'][0]['id']
    assert client.get('/v1/tire-variants/' + variant + '?mode=history').status_code == 200
    revoked = client.post('/v1/query-fallback-policies/' + never['id'] + ':revoke',
        headers={'Idempotency-Key': uid()}, json={'expected_revision': never['revision']})
    assert revoked.status_code == 200
    assert live(client, {**QUERY, 'consent_id': token}).status_code == 200


@pytest.mark.parametrize('reason', ['parser_schema_changed', 'upstream_http_403', 'generic_5xx', 'synthetic_outage'])
def test_non_network_failure_does_not_automatically_read_but_old_once_stays_compatible(setup, reason):
    client, registry, database = setup
    live(client)
    allow(client)
    outage(registry, reason)
    statements = trace(database)
    failed = live(client).json()
    assert failed['data_state'] == 'consent_required' and failed['variants'] == []
    assert not business_reads(statements) and count(database, QueryFallbackUse) == 0
    token = grant(client, failed['query_id']).json()['id']
    explicit = live(client, {**QUERY, 'consent_id': token}).json()
    assert explicit['data_state'] == 'local_snapshot' and explicit['variants']


@pytest.mark.parametrize('audience', ['internal', 'background_monitor', 'ai_current'])
def test_non_programmatic_audiences_do_not_use_continuous_permission(setup, audience):
    client, registry, database = setup
    original = live(client).json()
    allow(client)
    outage(registry)
    with database.sessions() as db:
        session_id = db.get(QueryRun, original['query_id']).session_id
        result = asyncio.run(QueryService(db, registry).execute('fixture', LiveQueryRequest.model_validate(QUERY),
                                                                  session_id, audience=audience))
    assert result['data_state'] == 'consent_required' and result['variants'] == []
    assert count(database, QueryFallbackUse) == 0
    assert live(client, {**QUERY, 'audience': 'programmatic'}).status_code == 422


def test_pause_expiry_clock_regression_and_source_generation_cannot_extend_allow(setup, monkeypatch):
    client, registry, database = setup
    live(client)
    policy = allow(client, expires_in_seconds=900)
    outage(registry)
    import tire_api.query_fallback_policies as module
    real_now = module.utcnow
    monkeypatch.setattr(module, 'utcnow', lambda: real_now() + timedelta(seconds=901))
    assert live(client).json()['data_state'] == 'consent_required'
    monkeypatch.setattr(module, 'utcnow', lambda: real_now() - timedelta(seconds=60))
    assert live(client).json()['data_state'] == 'consent_required'
    monkeypatch.setattr(module, 'utcnow', real_now)
    listed = client.get('/v1/query-fallback-policies').json()['items']
    assert listed[0]['state'] == 'paused' and listed[0]['reason'] == 'clock_regression'
    assert live(client).json()['data_state'] == 'consent_required'
    paused = client.post('/v1/query-fallback-policies/' + policy['id'] + ':pause',
        headers={'Idempotency-Key': uid()}, json={'expected_revision': listed[0]['revision']})
    assert paused.status_code == 200


def test_revocation_after_durable_claim_returns_no_result_and_consumption_survives(setup, monkeypatch):
    client, registry, database = setup
    live(client)
    policy = allow(client)
    outage(registry)
    import tire_api.query_fallback_policies as module
    original = module.revalidate_use
    calls = 0
    def revoke_after_claim(db, selected_registry, run, use):
        nonlocal calls
        calls += 1
        if calls == 1:
            current = module.latest(db, run.session_id, policy['id'])
            payload = deepcopy(current.payload)
            payload.update(revision=current.revision + 1, state='revoked', reason='revoked', updated_at=module.stamp(module.utcnow()))
            module.append_revision(db, run.session_id, payload, uid(), 'f' * 64)
            db.commit()
        return original(db, selected_registry, run, use)
    monkeypatch.setattr(module, 'revalidate_use', revoke_after_claim)
    response = live(client)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'query_fallback_policy_changed'
    assert count(database, QueryFallbackUse) == 1


def test_missing_or_expired_owner_never_bootstraps_policy_session(setup):
    client, _, database = setup
    before = count(database, UserSession)
    with TestClient(client.app) as other:
        assert other.get('/v1/query-fallback-policies').status_code == 401
        assert 'set-cookie' not in other.get('/v1/query-fallback-policies').headers
    assert count(database, UserSession) == before
    with database.sessions() as db:
        db.execute(update(UserSession).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert client.get('/v1/query-fallback-policies').status_code == 401
    assert count(database, UserSession) == before


def test_scope_source_kind_revision_and_preview_fingerprint_are_strict(setup):
    client, _, _ = setup
    assert preview(client, 'source_allow').status_code == 422
    assert preview(client, selected=scope(generation=1)).status_code == 409
    assert preview(client, selected=scope(kind='recall_campaign')).status_code == 422
    prepared = preview(client).json()
    assert apply(client, prepared, expected_fingerprint='0' * 64).status_code == 409
    assert apply(client, prepared, expected_revision=1).status_code == 409
    assert preview(client, selected={'kind': 'query', 'query_kind': 'tire',
                                   'sources': scope()['sources'] * 2}).status_code == 422


@pytest.mark.parametrize('kind', ['tire', 'vehicle_fitments', 'recall_campaign', 'recall_search'])
def test_four_public_query_kinds_use_their_own_exact_policy_and_historic_response(tmp_path, monkeypatch, kind):
    for name in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(name, '0')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    registry = FourDomainRegistry()
    app = create_app('sqlite:///' + (tmp_path / 'four.sqlite').as_posix(), registry)
    app.state.vehicle_adapter = NormalizedVehicleFixture()
    app.state.recall_adapter = NetworkRecallFixtures()
    with TestClient(app) as client:
        endpoint, body, source, content = {
            'tire': ('/v1/sources/fixture/live-query', deepcopy(QUERY), 'fixture', 'variants'),
            'vehicle_fitments': ('/v1/vehicles/synthetic-vehicle/live-fitments', {}, 'xiaomi-cn-vehicles', 'fitments'),
            'recall_campaign': ('/v1/recalls/live-query', {'query': {'campaign_number': '23T001000'}}, 'nhtsa-us-recalls', 'records'),
            'recall_search': ('/v1/recalls/search', {'query': {'search': 'SYNTHETIC DEMO', 'offset': 0}}, 'nhtsa-us-recalls', 'products'),
        }[kind]
        original = client.post(endpoint, json=body)
        assert original.status_code == 200, original.text
        assert original.json()['data_state'] == 'live' and original.json()[content], original.text
        allowed = allow(client, selected=scope(source=source, kind=kind))
        outage(registry)
        app.state.vehicle_adapter.offline = True
        app.state.recall_adapter.offline = True
        statements = trace(app.state.database)
        response = client.post(endpoint, json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['data_state'] == 'local_snapshot'
        # Field authority records the requested data_state; facts and identity stay exact.
        fact_rows = lambda rows: [{key: value for key, value in row.items() if key != 'field_resolution'} for row in rows]
        assert fact_rows(result[content]) == fact_rows(original.json()[content])
        use = result['fallback_authorization']['use']
        assert use['query_kind'] == kind and use['policy_id'] == allowed['id']
        material_column = {'tire': 'snapshots.parsed_variants', 'vehicle_fitments': 'vehicle_snapshots.payload',
                           'recall_campaign': 'recall_snapshots.records', 'recall_search': 'recall_search_snapshots.discovery'}[kind]
        claimed = next(index for index, sql in enumerate(statements) if sql.startswith('insert into query_fallback_uses'))
        read = next(index for index, sql in enumerate(statements) if sql.startswith('select') and material_column in sql)
        assert read > claimed and 'COMMIT' in statements[claimed + 1:read]
        if kind == 'recall_search':
            assert result['query'] == original.json()['query'] and result['pagination'] == original.json()['pagination']
            wrong_page = client.post(endpoint, json={'query': {'search': 'SYNTHETIC DEMO', 'offset': 10}}).json()
            assert wrong_page['products'] == []  # That new authorized attempt cannot borrow offset 0 data.
        never = allow(client, 'never', selected=scope(source=source, kind=kind))
        blocked = client.post(endpoint, json=body).json()
        assert blocked['data_state'] == 'source_unavailable' and blocked[content] == []
        assert never['mode'] == 'never'


@pytest.mark.parametrize('kind', ['tire', 'recall_campaign'])
def test_http_current_ai_evidence_never_inherits_continuous_programmatic_policy(tmp_path, monkeypatch, kind):
    from tire_api.ai_models import AIEvidencePack
    for name in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(name, '0')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    registry = FourDomainRegistry()
    app = create_app('sqlite:///' + (tmp_path / 'ai-evidence-only.sqlite').as_posix(), registry)
    app.state.recall_adapter = NetworkRecallFixtures()
    with TestClient(app) as client:
        if kind == 'tire':
            observed = live(client).json()
            request = {'mode': 'current', 'source_id': 'fixture', 'query': QUERY['query'],
                       'variant_ids': [observed['variants'][0]['id']]}
            selected = scope()
        else:
            client.post('/v1/recalls/live-query', json={'query': {'campaign_number': '23T001000'}})
            request = {'mode': 'current', 'source_id': 'nhtsa-us-recalls', 'query_kind': 'recall_by_campaign',
                       'query': {'campaign_number': '23T001000'}}
            selected = scope(source='nhtsa-us-recalls', kind=kind)
        allow(client, selected=selected)
        outage(registry)
        app.state.recall_adapter.offline = True
        response = client.post('/v1/ai/evidence-packs', json=request)
        assert response.status_code == 200, response.text
        failed = response.json()
        assert failed['pack'] is None and failed['query_result']['data_state'] == 'consent_required'
        assert count(app.state.database, QueryFallbackUse) == count(app.state.database, AIEvidencePack) == 0
        token = grant(client, failed['query_result']['query_id']).json()['id']
        explicit = client.post('/v1/ai/evidence-packs', json={**request, 'consent_id': token})
        assert explicit.status_code == 200, explicit.text
        assert explicit.json()['pack']['data_state'] == 'local_snapshot'
        assert count(app.state.database, QueryFallbackUse) == 0
