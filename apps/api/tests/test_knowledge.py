"""Actual lexical SQL over synthetic accepted records; no model/network acceptance."""
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select, text

from tire_api.db import (FactVersion, QueryRun, Snapshot, TireVariant, UserSession,
                         VariantLifecycleEvent, Verification, Database, uid, utcnow)
from tire_api.domain import digest
from tire_api.knowledge import KnowledgeSearch, attach_identity_contracts, search_history
from tire_api.knowledge_models import KnowledgeDocument, KnowledgeIndexState
from tire_api.main import create_app
from test_core import FixtureRegistry, VARIANT, live, success
from test_test_events import PAYLOAD, create


class Sources(FixtureRegistry):
    def sources(self):
        return [{**item, 'source_class': 'manufacturer_official' if item['id'] == 'fixture' else 'regulatory'}
                for item in super().sources()]


@pytest.fixture
def setup():
    registry = Sources()
    app = create_app('sqlite://', registry)
    with TestClient(app) as client:
        yield client, registry, app.state.database


def search(client, text='', filters=None, **kwargs):
    return client.post('/v1/knowledge/search', json={'mode': 'history', 'text': text, 'filters': filters or {}, **kwargs})


def seed(database, rows, *, source='fixture', query='catalog', at=None, snapshot=None):
    """Create accepted-head fixtures directly, including removals impossible to fake
    with FactVersion-only tests. No source parser/quality policy is being claimed.
    """
    at = at or utcnow()
    with database.sessions() as db:
        actor = UserSession(expires_at=at + timedelta(days=7))
        db.add(actor)
        db.flush()
        run = QueryRun(session_id=actor.id, source_id=source, query_key=query, query={'model': 'synthetic'}, fallback_policy='never')
        db.add(run)
        db.flush()
        if snapshot is None:
            snapshot = uid()
            values = []
            for input_row in rows:
                row = deepcopy(input_row)
                row.setdefault('id', uid())
                row['snapshot_id'] = snapshot
                row['source_id'] = source
                if db.get(TireVariant, row['id']) is None:
                    db.add(TireVariant(id=row['id'], identity_key=digest(row['id']), identity={}, identity_status='complete'))
                values.append(row)
            db.add(Snapshot(id=snapshot, source_id=source, query_key=query,
                source_url='https://fixture.example/knowledge', raw_hash=digest(snapshot), body='RAW_BODY_MUST_NOT_BE_INDEXED',
                content_type='text/html', parser_version='knowledge-fixture@1', observed_at=at, parsed_variants=values))
            db.flush()
            for row in values:
                prior = db.scalar(select(func.max(FactVersion.version)).where(
                    FactVersion.variant_id == row['id'], FactVersion.source_id == source)) or 0
                db.add(FactVersion(variant_id=row['id'], source_id=source, snapshot_id=snapshot,
                    facts=row['facts'], facts_hash=digest(row['facts']), version=prior + 1, observed_at=at))
        db.add(Verification(snapshot_id=snapshot, query_id=run.id, source_id=source, query_key=query,
                            status='not_modified' if rows is None else 'ok', verified_at=at))
        db.commit()
        return snapshot, actor.id


def test_fts_chinese_english_literals_and_hard_filters(setup):
    client, _, database = setup
    row = {**VARIANT, 'facts': {'utqg_treadwear': 300, 'description': '静音湿地制动 literal token'}}
    seed(database, [row])
    for query in ('湿地制动', 'LITERAL token', 'ＬＩＴＥＲＡＬ', '"literal" + (token)*'):
        response = search(client, query)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['total'] == 1 and result['items'][0]['match']['method'] == 'fts'
        assert result['stages'][1]['state'] == 'succeeded'
        assert result['index']['engine'] == 'sqlite_fts5'
    assert search(client, 'literal', {'region': 'CN'}).json()['total'] == 0
    assert search(client, 'literal', {'product_code': 'FIX'}).json()['total'] == 0
    assert search(client, 'OR').json()['total'] == 0
    assert search(client, "'; DROP TABLE knowledge_documents;--").json()['total'] == 0


def test_identity_contract_is_retrieval_metadata_without_rewriting_indexed_history(setup):
    client, _, database = setup
    seed(database, [{**VARIANT, 'facts': {'description': 'namespace history evidence'}}])
    response = search(client, 'namespace history').json()
    item, = response['items']
    assert item['identity_contract']['schema'] == 'variant-identity@2'
    assert item['identity_contract']['state'] == 'legacy_unbound'
    assert item['identity_contract']['current_identity'] is None
    with database.sessions() as db:
        document = db.get(KnowledgeDocument, item['id'])
        preserved = deepcopy(document.payload)
        assert 'identity_contract' not in preserved
        input_items = [{**item, 'identity_contract': {'state': 'untrusted-index-metadata'}} for _ in range(12)]
        before = deepcopy(input_items)
        statements = []
        def observe(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        event.listen(database.engine, 'before_cursor_execute', observe)
        try:
            rendered = attach_identity_contracts(db, input_items)
        finally:
            event.remove(database.engine, 'before_cursor_execute', observe)
        assert all(row['identity_contract']['state'] == 'legacy_unbound' for row in rendered)
        assert input_items == before and document.payload == preserved
        assert len(statements) <= 4  # Batch by identity, independent of result count.
    assert search(client, '***').json()['total'] == 0
    assert search(client, 'RAW_BODY_MUST_NOT_BE_INDEXED').json()['total'] == 0
    assert search(client, filters={'size': '265/40R20', 'product_code': 'FIX-001'}).json()['total'] == 1


@pytest.mark.parametrize('body,status', [
    ({'mode': 'current', 'text': 'tire'}, 422),
    ({'mode': 'history'}, 422),
    ({'mode': 'history', 'filters': {'brand': ' '}}, 422),
    ({'mode': 'history', 'filters': {'brand': None}}, 422),
    ({'mode': 'history', 'text': '最新参数'}, 409),
    ({'mode': 'history', 'text': 'latest specs'}, 409),
    ({'mode': 'history', 'text': 'x', 'filters': {'invented': 'x'}}, 422),
    ({'mode': 'history', 'text': 'x', 'filters': {'field': 'invented'}}, 422),
    ({'mode': 'history', 'text': 'x', 'unknown': True}, 422),
    ({'mode': 'history', 'text': 'x', 'limit': True}, 422),
    ({'mode': 'history', 'text': 'x', 'limit': 31}, 422),
])
def test_strict_history_request(setup, body, status):
    client, _, _ = setup
    assert client.post('/v1/knowledge/search', json=body).status_code == status


def test_aliases_r_zr_entities_and_filter_before_limit(setup):
    client, _, database = setup
    values = [{**VARIANT, 'model': 'Pilot Sport 4 S', 'manufacturer_product_code': f'CODE-{i}',
               'size': '265/40R20' if i % 2 else '265/40ZR20'} for i in range(35)]
    values[-1] = {**values[-1], 'region': 'CN'}
    seed(database, values)
    result = search(client, 'PS4S 265/40R20 Acoustic', limit=30).json()
    assert result['total'] == 35 and result['has_more']
    assert result['stages'][1]['state'] == 'not_needed'
    assert result['inferred_filters'] == {'model': 'Pilot Sport 4 S', 'size': '265/40R20', 'technology': 'Acoustic'}
    assert len({item['reference']['variant_id'] for item in result['items']}) == 30
    assert any('R/ZR' in reason for reason in result['items'][0]['match']['explanation'])
    result = search(client, 'PS4S', {'region': 'CN'}, limit=1).json()
    assert result['total'] == 1 and result['items'][0]['region'] == 'CN'
    assert 'CODE-34' in result['items'][0]['label']
    # Residual terms must actually reach FTS, not be dropped after alias parsing.
    assert search(client, 'PS4S absentterm').json()['total'] == 0
    assert search(client, 'PS4S', {'model': 'Different Tire'}).json()['total'] == 0


def test_formal_head_membership_304_and_no_payload_reread(setup):
    client, _, database = setup
    at = utcnow()
    identity = uid()
    first = {**VARIANT, 'id': identity, 'facts': {'description': 'headalpha'}}
    old, _ = seed(database, [first], query='one', at=at)
    new, _ = seed(database, [{**first, 'facts': {'description': 'headbeta'}}], query='two', at=at + timedelta(seconds=1))
    assert search(client, 'headbeta').json()['items'][0]['reference']['snapshot_id'] == new
    assert search(client, 'headalpha').json()['total'] == 1
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())
    event.listen(database.engine, 'before_cursor_execute', capture)
    try:
        assert search(client, 'headbeta').json()['total'] == 1
    finally:
        event.remove(database.engine, 'before_cursor_execute', capture)
    assert not any('snapshots.parsed_variants' in s or 'snapshots.body' in s or 'fact_versions' in s for s in statements)
    # A 304 reuses its snapshot; the other query's accepted head stays visible.
    seed(database, None, query='one', snapshot=old, at=at + timedelta(seconds=2))
    assert search(client, 'headalpha').json()['items'][0]['reference']['snapshot_id'] == old
    assert search(client, 'headbeta').json()['total'] == 1
    # Remove from both query heads. FactVersion history survives but must not revive it.
    seed(database, [], query='one', at=at + timedelta(seconds=3))
    seed(database, [], query='two', at=at + timedelta(seconds=3))
    assert search(client, filters={'variant_id': identity}).json()['total'] == 0
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(FactVersion)) == 2


def test_latest_before_region_filter_and_lifecycle_revocation(setup):
    client, _, database = setup
    identity = uid()
    at = utcnow()
    seed(database, [{**VARIANT, 'id': identity, 'region': 'CN'}], at=at)
    _, actor_id = seed(database, [{**VARIANT, 'id': identity, 'region': 'US'}], at=at + timedelta(seconds=1))
    assert search(client, filters={'region': 'CN'}).json()['total'] == 0
    assert search(client, filters={'variant_id': identity}).json()['total'] == 1
    with database.sessions() as db:
        db.add(VariantLifecycleEvent(variant_id=identity, revision=1, action='revoke', before_state='active', after_state='revoked',
            operator_session_id=actor_id, operator='Synthetic operator', reason='synthetic removal', evidence=[]))
        db.commit()
    assert search(client, filters={'variant_id': identity}).json()['total'] == 0
    with database.sessions() as db:
        db.add(VariantLifecycleEvent(variant_id=identity, revision=2, action='restore', before_state='revoked', after_state='active',
            operator_session_id=actor_id, operator='Synthetic operator', reason='synthetic restoration', evidence=[]))
        db.commit()
    assert search(client, filters={'variant_id': identity}).json()['total'] == 1


def test_event_latest_revision_before_matching_revoke_and_participant_pair(setup):
    client, _, _ = setup
    data = deepcopy(PAYLOAD)
    data['event']['title'] = '合成旧标题'
    data['event']['participants'][1]['model'] = 'Other model'
    record = create(client, data)
    assert search(client, '旧标题').json()['total'] == 1
    assert search(client, filters={'kind': 'test_event', 'brand': 'Fixture A', 'model': 'Other model'}).json()['total'] == 0
    data['event']['title'] = '合成新标题'
    revised = client.put(f'/v1/test-events/{record["id"]}', json={**data, 'expected_revision': 1})
    assert revised.status_code == 200, revised.text
    assert search(client, '旧标题').json()['total'] == 0
    result = search(client, '新标题').json()['items'][0]
    assert result['reference'] == {'kind': 'test_event', 'event_id': record['id'], 'event_revision': 2}
    assert result['privacy_class'] == 'private' and result['verified_at'] is None
    assert 'rights_basis' not in result['excerpt'] and 'Fixture reviewer' not in result['excerpt']
    response = client.post(f'/v1/test-events/{record["id"]}/state', json={'expected_revision': 2, 'action': 'revoke',
                           'operator': 'Tester', 'reason': 'Synthetic revision withdrawal'})
    assert response.status_code == 200, response.text
    assert search(client, '新标题').json()['total'] == 0


def test_field_authority_is_specific_conflicts_survive_and_no_model_or_network(setup):
    client, registry, database = setup
    identity = uid()
    at = utcnow()
    first = {**VARIANT, 'id': identity, 'facts': {'eu_wet_grip': 'A', 'utqg_treadwear': 300,
        'source_updated_at': '2026-01-01', 'other_source_metadata': 'first',
        'evidence_spans': {'acoustic_technology': '$.sku[FIX-001].technology'}}}
    seed(database, [first], source='fixture', at=at)
    second = {**first, 'facts': {'eu_wet_grip': 'B', 'utqg_treadwear': 500,
                               'source_updated_at': '2026-02-01', 'other_source_metadata': 'second'}}
    seed(database, [second], source='fixture-two', at=at + timedelta(seconds=1))
    class ForbiddenModel:
        async def generate(self, *_args):
            raise AssertionError('Search must never call a model')
    client.app.state.ai_adapter = ForbiddenModel()
    baseline = len(registry.calls)
    normal = search(client, filters={'variant_id': identity}).json()
    assert normal['total'] == 2
    assert normal['items'][0]['source_id'] == 'fixture-two'  # time only without field boost
    assert all(item['match']['authority_tier'] is None for item in normal['items'])
    assert all(item['conflicts'] for item in normal['items'])
    assert {c['field'] for item in normal['items'] for c in item['conflicts']} == {'eu_wet_grip', 'utqg_treadwear'}
    eu = search(client, filters={'variant_id': identity, 'field': 'eu_wet_grip'}).json()
    assert [i['match']['authority_tier'] for i in eu['items']] == [1, 2]
    assert eu['items'][0]['source_id'] == 'fixture-two'
    for field in ('EU_WET_GRIP', 'ＥＵ＿ＷＥＴ＿ＧＲＩＰ'):
        equivalent = search(client, filters={'variant_id': identity, 'field': field}).json()
        assert equivalent['applied_filters']['field'] == 'eu_wet_grip'
        assert [i['match']['authority_tier'] for i in equivalent['items']] == [1, 2]
    utqg = search(client, filters={'variant_id': identity, 'field': 'utqg_treadwear'}).json()
    assert utqg['items'][0]['source_id'] == 'fixture' and utqg['items'][0]['match']['authority_tier'] == 1
    acoustic = search(client, filters={'variant_id': identity, 'field': 'acoustic_technology'}).json()
    from tire_api.field_authority import source_authority
    assert acoustic['items'][0]['match']['authority_rule'] == source_authority(
        'acoustic_technology', 'manufacturer_official', sku_specific=True)['rule']
    assert acoustic['items'][1]['match']['authority_tier'] is None
    assert len(registry.calls) == baseline
    assert all(stage['state'] == 'not_needed' for stage in eu['stages'][2:4])
    assert eu['stages'][4]['state'] == 'succeeded'


def test_unverified_snapshots_and_unaccepted_private_tables_are_not_read(setup):
    client, _, database = setup
    at = utcnow()
    with database.sessions() as db:
        db.add(Snapshot(source_id='fixture', query_key='never-verified', source_url='https://fixture.example',
            raw_hash=digest('unverified'), body='private raw', content_type='text/html', parser_version='fixture@1',
            observed_at=at, parsed_variants=[{**VARIANT, 'id': uid(), 'facts': {'description': 'unverifiedcanary'}}]))
        db.commit()
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())
    event.listen(database.engine, 'before_cursor_execute', capture)
    try:
        assert search(client, 'unverifiedcanary').json()['total'] == 0
    finally:
        event.remove(database.engine, 'before_cursor_execute', capture)
    forbidden = ('raw_captures', 'source_quarantines', 'vehicle_quarantines', 'rejected_observations', 'evidence_documents',
                 'ai_evidence_packs', 'ai_requests', 'garage_revisions', 'saved_comparisons', 'manual_fact_revisions')
    assert not any(name in statement for name in forbidden for statement in statements)


def test_projection_rebuild_is_atomic_on_failure(setup):
    client, registry, database = setup
    seed(database, [{**VARIANT, 'facts': {'description': 'firstdocument'}}])
    assert search(client, 'firstdocument').json()['total'] == 1
    seed(database, [{**VARIANT, 'facts': {'description': 'seconddocument'}}], query='new')
    # Fail only after the explicit delete starts, so the transaction rollback
    # demonstrates old documents and their FTS rows survive together.
    def stop_insert(_conn, _cursor, statement, _params, _context, _many):
        if statement.startswith('DELETE FROM knowledge_documents'):
            raise RuntimeError('synthetic interrupted rebuild')
    event.listen(database.engine, 'before_cursor_execute', stop_insert)
    try:
        with database.sessions() as db:
            with pytest.raises(RuntimeError):
                search_history(db, registry, KnowledgeSearch(mode='history', text='seconddocument'))
    finally:
        event.remove(database.engine, 'before_cursor_execute', stop_insert)
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeDocument)) == 1
        assert db.execute(text('SELECT count(*) FROM knowledge_fts')).scalar() == 1
    assert search(client, 'seconddocument').json()['total'] == 1


def test_vehicle_formal_verification_head_and_size_filter(setup):
    from test_vehicles import FixtureVehicleAdapter, live as vehicle_live, source_document, success as vehicle_success
    client, _, database = setup
    adapter = FixtureVehicleAdapter()
    client.app.state.vehicle_adapter = adapter
    first = vehicle_live(client).json()
    assert first['data_state'] == 'live'
    historical = search(client, filters={'kind': 'vehicle', 'size': '265/35R21'}).json()
    assert historical['total'] == 1
    assert historical['items'][0]['reference']['snapshot_id'] == first['provenance'][0]['snapshot_id']
    doc = source_document()
    for column in doc['data']['paramComparisonTableVOList'][0]['groups'][0]['paramComparisonCols']:
        for cell in column['paramComparisonCells']:
            cell['paramDesc'] = cell['paramDesc'].replace('265/35 R21', '275/35 R21')
    adapter.result = vehicle_success(doc)
    second = vehicle_live(client).json()
    assert second['data_state'] == 'live'
    assert search(client, filters={'kind': 'vehicle', 'size': '265/35R21'}).json()['total'] == 0
    assert search(client, filters={'kind': 'vehicle', 'size': '275/35R21'}).json()['total'] == 1
    calls = len(adapter.calls)
    assert search(client, '测试轮毂').json()['total'] == 1
    assert len(adapter.calls) == calls
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeDocument)) == 1


def test_same_timestamp_independent_query_heads_preserve_both_snapshots(setup):
    client, _, database = setup
    identity = uid()
    at = utcnow()
    one, _ = seed(database, [{**VARIANT, 'id': identity, 'facts': {'description': 'firsttie'}}], query='one', at=at)
    two, _ = seed(database, [{**VARIANT, 'id': identity, 'facts': {'description': 'secondtie'}}], query='two', at=at)
    result = search(client, filters={'variant_id': identity}).json()
    assert result['total'] == 2
    assert {item['reference']['snapshot_id'] for item in result['items']} == {one, two}


def test_unknown_acoustic_authority_without_sku_locator(setup):
    client, _, database = setup
    seed(database, [VARIANT])
    result = search(client, filters={'field': 'acoustic_technology'}).json()
    assert result['total'] == 1 and result['items'][0]['match']['authority_tier'] is None
    from tire_api.field_authority import source_authority
    assert result['items'][0]['match']['authority_rule'] == source_authority(
        'acoustic_technology', 'manufacturer_official', sku_specific=False)['rule']


def test_concurrent_searches_share_one_atomic_projection(tmp_path):
    registry = FixtureRegistry()
    database = Database('sqlite:///' + (tmp_path / 'parallel-search.db').as_posix())
    database.initialize()
    seed(database, [{**VARIANT, 'facts': {'description': '共享索引 parallelsearch'}}])
    gate = Barrier(4)
    def run(_):
        with database.sessions() as db:
            gate.wait(timeout=10)
            return search_history(db, registry, KnowledgeSearch(mode='history', text='共享索引 parallelsearch'))
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, range(4)))
        assert all(row['total'] == row['index']['documents'] == 1 for row in results)
        assert len({row['items'][0]['id'] for row in results}) == 1
        with database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(KnowledgeIndexState)) == 1
            assert db.execute(text('SELECT count(*) FROM knowledge_fts')).scalar() == 1
    finally:
        database.close()


def test_schema_reinitialization_and_fts_creation_are_transactional(tmp_path, monkeypatch):
    from tire_api import knowledge_models
    database = Database('sqlite:///' + (tmp_path / 'fts-startup.db').as_posix())
    original = knowledge_models.initialize_search
    def fail(connection):
        original(connection)
        raise RuntimeError('synthetic FTS schema failure')
    monkeypatch.setattr(knowledge_models, 'initialize_search', fail)
    with pytest.raises(RuntimeError):
        database.initialize()
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name LIKE 'knowledge_%'")).scalar() == 0
    monkeypatch.setattr(knowledge_models, 'initialize_search', original)
    database.initialize()
    database.initialize()
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_fts'")).scalar() == 1
    database.close()


def verify_knowledge_persistence(url):
    """Real SQL fixture for the isolated PostgreSQL backup/restore acceptance run.

    Works alongside existing acceptance fixtures; the returned request is safe to
    repeat after restore and its exact references should remain discoverable.
    """
    registry = FixtureRegistry()
    marker = 'knowledgepersistence' + uuid4().hex
    registry.result = success(variants=[{**VARIANT, 'model': marker, 'manufacturer_product_code': marker,
                                       'facts': {'description': '知识持久化 ' + marker}}])
    app = create_app(url, registry)
    with TestClient(app) as client:
        observed = live(client, {'query': {'model': marker}, 'fallback_policy': 'never'})
        assert observed.status_code == 200 and observed.json()['data_state'] == 'live', observed.text
        request = {'mode': 'history', 'text': '知识持久化 ' + marker, 'filters': {'source_id': 'fixture'}}
        response = client.post('/v1/knowledge/search', json=request)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['index']['engine'] == 'postgresql_fts' and result['stages'][1]['state'] == 'succeeded'
        assert result['total'] == 1 and result['items'][0]['match']['method'] == 'fts'
        references = [item['reference'] for item in result['items']]
        assert references[0]['snapshot_id'] == observed.json()['provenance'][0]['snapshot_id']
        with app.state.database.sessions() as db:
            assert db.execute(text("SELECT count(*) FROM pg_indexes WHERE tablename = 'knowledge_documents' "
                                   "AND indexname = 'ix_knowledge_search_vector' AND indexdef LIKE '%USING gin%'")).scalar() == 1
    return {'request': request, 'references': references}
