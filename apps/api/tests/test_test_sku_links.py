"""Private synthetic workflow; material declarations are never online verification."""
from copy import deepcopy
import base64
import json
from uuid import uuid4

import pytest

from test_fitment_relations import relation_setup
from test_test_events import PAYLOAD, create


@pytest.fixture
def bridge(relation_setup):
    client, database, session, selected = relation_setup
    data = deepcopy(PAYLOAD)
    data['event']['tested_size'] = '245/40R20'
    data['event']['participants'][0].update(brand='Synthetic', model='Synthetic Tire')
    event = create(client, data)
    selection = {key: selected[key] for key in ('variant_id', 'tire_snapshot_id', 'fact_version_id')}
    selection.update(event_id=event['id'], event_revision_id=event['revision_id'], participant_key='a')
    return client, database, session, {'mode': 'history', 'action': 'create', 'link_id': None,
        'selection': selection, 'materials': [], 'assertions': [], 'evidence_level': 'manual_assertion'}


def test_manual_bridge_preview_is_available_without_promoting_unverified_identity(bridge):
    client, _, _, payload = bridge
    response = client.post('/v1/test-sku-links/preview', json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['schema'] == 'test-sku-link@1'
    assert result['eligibility'] == 'none'
    assert result['boundary']['origin_verification'] == 'unverified'


def test_bridge_empty_shared_history_requires_explicit_mode(bridge):
    client, _, _, _ = bridge
    assert client.get('/v1/test-sku-links?mode=history').status_code == 200
    assert client.get('/v1/test-sku-links').status_code == 422


def test_bridge_admin_guard_precedes_malformed_preview_body(bridge):
    from fastapi.testclient import TestClient
    client, _, _, _ = bridge
    with TestClient(client.app) as anonymous:
        assert anonymous.post('/v1/test-sku-links/preview', json={'unexpected': True}).status_code == 403


def preview(client, payload):
    response = client.post('/v1/test-sku-links/preview', json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def decision(client, payload):
    proposed = preview(client, payload)
    return {**deepcopy(payload), 'expected_revision': proposed['revision'],
        'expected_fingerprint': proposed['fingerprint'], 'declaration_revision_id': proposed['declaration_revision_id'],
        'operator': 'Synthetic bridge reviewer', 'reason': 'Project-authored synthetic workflow only',
        'acknowledged': True, 'opened_materials': [{'document_id': m['document_id'], 'raw_hash': m['raw_hash'],
            'metadata_hash': m['metadata_hash']} for m in proposed['material_evidence']],
        'confirmed_event_revision_id': proposed['confirmed_event_revision_id'],
        'confirmed_participant_hash': proposed['confirmed_participant_hash']}


def post(client, payload, key=None):
    return client.post('/v1/test-sku-links/decisions', json=payload,
                       headers={'Idempotency-Key': key or str(uuid4())})


def stored(client, payload):
    response = post(client, decision(client, payload))
    assert response.status_code == 201, response.text
    return response.json()['link']


def operation(payload, link_id, action):
    return {**deepcopy(payload), 'link_id': link_id, 'action': action}


def second_admin(client):
    from admin_support import register_admin
    from fastapi.testclient import TestClient
    other = TestClient(client.app)
    user = register_admin(other, 'bridge-reviewer')['user']
    assert client.post('/v1/auth/users/' + user['id'] + '/role', json={'is_admin': True}).status_code == 200
    return other


@pytest.fixture
def explicit_bridge(bridge):
    client, database, session, payload = bridge
    metadata = {'title': 'Synthetic material', 'source_url': PAYLOAD['event']['source_url'],
        'operator': 'Synthetic author', 'rights_basis': 'Project-authored synthetic bytes for local tests'}
    response = client.post('/v1/documents', content=b'%PDF-1.4 synthetic unit fixture, not a publication', headers={
        'content-type': 'application/pdf', 'x-evidence-metadata': base64.b64encode(json.dumps(metadata).encode()).decode()})
    assert response.status_code == 201, response.text
    document_id = response.json()['id']
    listed = client.get('/v1/test-sku-links/materials?mode=history').json()['items'][0]
    identity = preview(client, payload)['frozen_evidence']['tire']['identity']
    locator = {'page': 1, 'region': 'synthetic table row a', 'quote': '  Synthetic participant a\n'}
    payload = deepcopy(payload)
    payload['materials'] = [{'document_id': document_id, 'expected_raw_hash': listed['raw_hash'],
        'expected_metadata_hash': listed['metadata_hash'], 'event_locator': locator, 'participant_locator': locator,
        'rights': {'rights_holder': 'Synthetic project', 'basis': 'Project-authored material',
                   'store_original': True, 'workspace_reopen': True, 'quote_identifiers': True}}]
    payload['assertions'] = [{'field': field, 'material_document_id': document_id, 'material_value': value,
        'page': 1, 'region': 'synthetic identity row', 'quote': ' ' + str(value) + '\n'} for field, value in identity.items()]
    payload['evidence_level'] = 'source_explicit_identifiers_in_supplied_material'
    return client, database, session, payload


def test_explicit_material_two_account_review_restore_and_exact_history(explicit_bridge):
    client, _, _, payload = explicit_bridge
    created = stored(client, payload)
    assert created['review_state'] == 'pending_review' and created['eligibility'] == 'none'
    assert 'test_sku_self_review' in preview(client, operation(payload, created['id'], 'review'))['blockers']
    reviewer = second_admin(client)
    try:
        reviewed = stored(reviewer, operation(payload, created['id'], 'review'))
        assert reviewed['eligibility'] == 'conditional_reviewed_transcription'
        assert reviewed['declared_by_user_id'] == created['declared_by_user_id']
        assert reviewed['declaration_revision_id'] == created['revision_id']
        assert reviewed['history'][0]['actor_user_id'] != created['declared_by_user_id']
        revoked = stored(reviewer, operation(payload, created['id'], 'revoke'))
        restored = stored(reviewer, operation(payload, created['id'], 'restore'))
        assert revoked['review_state'] == 'revoked'
        assert restored['review_state'] == 'pending_review' and restored['eligibility'] == 'none'
        assert restored['declaration_revision_id'] == created['revision_id']
        historical = client.get('/v1/test-sku-links/' + created['id'] + '?mode=history&revision=2')
        assert historical.status_code == 200 and historical.json()['revision_id'] == reviewed['revision_id']
    finally:
        reviewer.close()


def test_same_account_other_session_cannot_review_and_idempotent_replay_is_exact(bridge):
    from admin_support import ADMIN_PASSWORD
    from fastapi.testclient import TestClient
    client, _, _, payload = bridge
    key, request = str(uuid4()), decision(client, payload)
    response = post(client, request, key)
    assert response.status_code == 201, response.text
    created = response.json()['link']
    same = TestClient(client.app)
    try:
        assert same.post('/v1/auth/login', json={'username': 'admin', 'password': ADMIN_PASSWORD}).status_code == 200
        assert 'test_sku_self_review' in preview(same, operation(payload, created['id'], 'review'))['blockers']
        stored(client, operation(payload, created['id'], 'revoke'))
        replay = post(same, request, key)
        assert replay.status_code == 201 and replay.json()['idempotent_replay'] is True
        assert replay.json()['link']['revision_id'] == created['revision_id']
        changed = {**request, 'reason': 'A different synthetic reason'}
        assert post(same, changed, key).status_code == 409
        assert post(client, request).status_code == 409  # scope/old preview, never a second link
    finally:
        same.close()


@pytest.mark.parametrize('mutation', ['uncertain', 'false', 'source', 'size', 'brand', 'model'])
def test_explicit_gate_does_not_fill_or_normalize_mismatched_fields(explicit_bridge, mutation):
    client, _, _, payload = explicit_bridge
    altered = deepcopy(payload)
    if mutation == 'uncertain':
        altered['assertions'].pop()
    elif mutation == 'false':
        next(a for a in altered['assertions'] if a['field'] == 'run_flat')['material_value'] = 'false'
    elif mutation == 'source':
        metadata = {'title': 'Different synthetic source', 'source_url': 'https://fixture.example/other-test',
            'operator': 'Synthetic author', 'rights_basis': 'Project-authored alternative material'}
        response = client.post('/v1/documents', content=b'%PDF-1.4 different synthetic source', headers={
            'content-type': 'application/pdf', 'x-evidence-metadata': base64.b64encode(json.dumps(metadata).encode()).decode()})
        assert response.status_code == 201, response.text
        item = next(m for m in client.get('/v1/test-sku-links/materials?mode=history').json()['items'] if m['id'] == response.json()['id'])
        altered['materials'][0].update(document_id=item['id'], expected_raw_hash=item['raw_hash'], expected_metadata_hash=item['metadata_hash'])
        for assertion in altered['assertions']:
            assertion['material_document_id'] = item['id']
    else:
        # These actual event values have to be revised, never guessed from the SKU.
        event = client.get('/v1/test-events/' + payload['selection']['event_id'] + '?mode=history').json()
        value = deepcopy(event['event'])
        if mutation == 'size': value['tested_size'] = '245/40ZR20'
        else: value['participants'][0][mutation] += ' different'
        revised = client.put('/v1/test-events/' + event['id'], json={'expected_revision': event['revision'],
            'event': value, 'operator': 'Synthetic author', 'reason': 'Synthetic exact scope conflict'}).json()
        altered['selection']['event_revision_id'] = revised['revision_id']
    proposed = preview(client, altered)
    assert proposed['can_submit'] is False and proposed['blockers']


@pytest.mark.parametrize('field', ['operator', 'reason', 'quote', 'region', 'material_value', 'page'])
def test_nonblank_original_strings_and_strict_page_contract(explicit_bridge, field):
    client, _, _, payload = explicit_bridge
    request = decision(client, payload)
    if field in ('operator', 'reason'):
        request[field] = '      '
    else:
        request['assertions'][0][field] = True if field == 'page' else '   \n'
    assert post(client, request).status_code == 422


def test_event_participant_removal_and_reentry_keep_frozen_history_but_stale_review(bridge):
    client, _, _, payload = bridge
    created = stored(client, payload)
    event = client.get('/v1/test-events/' + payload['selection']['event_id'] + '?mode=history').json()
    data = deepcopy(event['event'])
    data['participants'] = [p for p in data['participants'] if p['key'] != 'a']
    data['measurements'] = [m for m in data['measurements'] if m['participant_key'] != 'a']
    used_metrics = {m['metric_key'] for m in data['measurements']}
    data['metrics'] = [m for m in data['metrics'] if m['key'] in used_metrics]
    response = client.put('/v1/test-events/' + event['id'], json={'event': data, 'expected_revision': event['revision'],
        'operator': 'Synthetic author', 'reason': 'Synthetic participant removal'})
    assert response.status_code == 200, response.text
    revised = response.json()
    response = client.get('/v1/test-sku-links/' + created['id'] + '?mode=history&revision=1')
    assert response.status_code == 200, response.text
    assert response.json()['effective_state'] == 'needs_review'
    assert response.json()['frozen_evidence']['test']['participant']['key'] == 'a'
    assert 'test_participant_missing' in response.json()['blockers']
    client.put('/v1/test-events/' + event['id'], json={'event': event['event'], 'expected_revision': revised['revision'],
        'operator': 'Synthetic author', 'reason': 'Synthetic participant reentry'})
    result = client.get('/v1/test-sku-links/' + created['id'] + '?mode=history').json()
    assert result['effective_state'] == 'needs_review' and result['eligibility'] == 'none'


def test_material_bytes_are_rechecked_on_exact_history(explicit_bridge):
    client, database, _, payload = explicit_bridge
    created = stored(client, payload)
    with database.sessions() as db:
        path = db.info['object_store'].path(payload['materials'][0]['expected_raw_hash'])
    path.write_bytes(b'%PDF-damaged synthetic material')
    response = client.get('/v1/test-sku-links/' + created['id'] + '?mode=history&revision=1')
    assert response.status_code == 422 and response.json()['detail']['code'] == 'test_sku_material_integrity_failed'


@pytest.mark.parametrize('table', ['test_sku_links', 'test_sku_link_revisions'])
@pytest.mark.parametrize('operation_sql', ['UPDATE {table} SET id=id', 'DELETE FROM {table}',
    'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'])
def test_bridge_database_ledger_rejects_rewrites(bridge, table, operation_sql):
    from sqlalchemy.exc import DBAPIError
    client, database, _, payload = bridge
    stored(client, payload)
    with pytest.raises(DBAPIError):
        with database.engine.begin() as connection:
            connection.exec_driver_sql(operation_sql.format(table=table))


def test_new_bridge_revisions_are_orm_immutable_and_previews_do_not_write(bridge):
    from sqlalchemy import func, select
    from tire_api.db import AuditEvent
    from tire_api.test_sku_link_models import TestSkuLinkRevision
    client, database, _, payload = bridge
    created = stored(client, payload)
    with database.sessions() as db:
        baseline = db.scalar(select(func.count()).select_from(AuditEvent))
    preview(client, operation(payload, created['id'], 'revise'))
    client.get('/v1/test-sku-links/' + created['id'] + '?mode=history')
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == baseline
        row = db.get(TestSkuLinkRevision, created['revision_id'])
        row.reason = 'Attempted synthetic rewrite'
        with pytest.raises(ValueError):
            db.commit()


@pytest.mark.parametrize('kind', ['catalog', 'lifecycle', 'event'])
def test_current_aba_cannot_reactivate_an_old_binding(bridge, kind):
    from test_fitment_relations import seed_tire
    from tire_api.db import VariantLifecycleEvent, uid
    client, database, session, payload = bridge
    created = stored(client, payload)
    selected = payload['selection']
    old_request = decision(client, operation(payload, created['id'], 'revise'))
    if kind == 'catalog':
        seed_tire(database, session, variant_id=selected['variant_id'], empty=True)
        seed_tire(database, session, variant_id=selected['variant_id'], metadata_only=True)
    elif kind == 'lifecycle':
        with database.sessions() as db:
            for revision, before, after in ((1, 'active', 'revoked'), (2, 'revoked', 'active')):
                db.add(VariantLifecycleEvent(id=uid(), variant_id=selected['variant_id'], revision=revision,
                    action='revoke' if after == 'revoked' else 'restore', before_state=before, after_state=after,
                    operator_session_id=session, operator='Synthetic administrator',
                    reason='Synthetic lifecycle ABA only', evidence=[]))
            db.commit()
    else:
        for revision, action in ((1, 'revoke'), (2, 'restore')):
            response = client.post('/v1/test-events/' + selected['event_id'] + '/state', json={
                'expected_revision': revision, 'action': action, 'operator': 'Synthetic author',
                'reason': 'Synthetic event state ABA only'})
            assert response.status_code == 200, response.text
    result = client.get('/v1/test-sku-links/' + created['id'] + '?mode=history').json()
    assert result['effective_state'] == 'needs_review' and result['eligibility'] == 'none'
    assert result['stale_reasons']
    assert post(client, old_request).status_code == 409


def test_fact_only_and_metadata_refresh_do_not_change_identity_review_binding(bridge):
    from test_fitment_relations import seed_tire, tire_payload
    client, database, session, payload = bridge
    created = stored(client, payload)
    selected = payload['selection']
    seed_tire(database, session, variant_id=selected['variant_id'], metadata_only=True)
    seed_tire(database, session, tire_payload(facts={'utqg_treadwear': 400}),
              variant_id=selected['variant_id'], version=2)
    result = client.get('/v1/test-sku-links/' + created['id'] + '?mode=history').json()
    assert result['effective_state'] == 'pending_review' and not result['stale_reasons']
    assert result['frozen_evidence'] == created['frozen_evidence']


@pytest.mark.parametrize('same_key', [False, True])
def test_bridge_concurrent_create_has_one_append_or_exact_replay(bridge, same_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from tire_api.test_sku_links import BridgeDecision, append_link_revision
    client, database, session, payload = bridge
    request = BridgeDecision.model_validate(decision(client, payload))
    key = str(uuid4())
    barrier = Barrier(2)

    def submit(_index):
        barrier.wait(timeout=10)
        with database.sessions() as db:
            try:
                return append_link_revision(db, request, session, key if same_key else str(uuid4()))
            except HTTPException as error:
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    if same_key:
        assert all(isinstance(result, dict) for result in results)
        assert {r['idempotent_replay'] for r in results} == {False, True}
        assert len({r['event']['revision_id'] for r in results}) == 1
    else:
        assert len([r for r in results if isinstance(r, dict)]) == 1
        assert 409 in results


# Current ORM table shapes plus a pre-019 ledger; not an exact historical DB backup.
@pytest.fixture
def pre019(tmp_path, monkeypatch):
    from sqlalchemy import text
    from tire_api.db import Base, UserSession, uid, utcnow
    from tire_api.knowledge_models import initialize_search
    from tire_api.main import create_app
    from tire_api.migrations import DEVICE_AI_LEDGER_TRIGGERS_SQLITE
    from test_fitment_relations import NoNetworkRegistry
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    database = create_app('sqlite:///' + (tmp_path / 'pre019.sqlite').as_posix(), NoNetworkRegistry()).state.database
    new_tables = {'test_sku_links', 'test_sku_link_revisions'}
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name not in new_tables])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions (version VARCHAR(80) PRIMARY KEY, '
                                   'applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in EXPECTED_SCHEMA_VERSIONS[:18]:
            connection.execute(text('INSERT INTO tire_schema_versions(version) VALUES (:version)'), {'version': version})
        for sql in DEVICE_AI_LEDGER_TRIGGERS_SQLITE:
            connection.exec_driver_sql(sql)
        initialize_search(connection)
        connection.exec_driver_sql('CREATE TABLE preserved_bridge_marker (value TEXT NOT NULL)')
        connection.exec_driver_sql("INSERT INTO preserved_bridge_marker VALUES ('synthetic predecessor')")
    try:
        yield database
    finally:
        database.close()


def test_019_additive_upgrade_preserves_all_predecessor_rows_and_repeats(pre019):
    from sqlalchemy import text
    from test_ai_stream_migration import snapshot
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    from historical_migration_support import (assert_full_chain_preserved, assert_target_delta,
        assert_trigger_contract, initialize_observing_version)
    new_tables = {'test_sku_links', 'test_sku_link_revisions'}
    before = snapshot(pre019)
    stage = initialize_observing_version(pre019, '019_test_sku_links')
    assert_target_delta(before, stage, new_tables)
    # before intentionally lacks both target tables and their six ledger triggers.
    assert_trigger_contract(stage, device=True, candidate=False)
    first = snapshot(pre019)
    pre019.initialize()
    after = snapshot(pre019)
    assert first == after
    assert after['tables'] - before['tables'] == {'test_sku_links', 'test_sku_link_revisions'}
    assert_full_chain_preserved(before, after)
    for table in before['tables'] - {'tire_schema_versions'}:
        assert after['rows'][table] == before['rows'][table]
    assert not after['rows']['test_sku_links'] and not after['rows']['test_sku_link_revisions']
    with pre019.engine.connect() as connection:
        assert set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == set(EXPECTED_SCHEMA_VERSIONS)
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar_one() == 'ok'


def test_019_new_tables_triggers_and_version_rollback_together(pre019, monkeypatch):
    from test_ai_stream_migration import snapshot
    from tire_api import migrations
    before = snapshot(pre019)
    original = migrations.upgrade
    def failed(connection):
        original(connection)
        raise RuntimeError('synthetic_r71_upgrade_failure')
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', failed)
        with pytest.raises(RuntimeError, match='synthetic_r71_upgrade_failure'):
            pre019.initialize()
    assert snapshot(pre019) == before


def test_bridge_postgresql_ddl_compiles_without_connecting():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable
    from tire_api.migrations import TEST_SKU_LINK_TRIGGERS_POSTGRESQL
    from tire_api.test_sku_link_models import TestSkuLink, TestSkuLinkRevision
    dialect = postgresql.dialect()
    for model in (TestSkuLink, TestSkuLinkRevision):
        assert 'CREATE TABLE' in str(CreateTable(model.__table__).compile(dialect=dialect))
        for index in model.__table__.indexes:
            assert 'CREATE INDEX' in str(CreateIndex(index).compile(dialect=dialect))
    assert len(TEST_SKU_LINK_TRIGGERS_POSTGRESQL) == 5
    assert all(str(ddl.compile(dialect=dialect)) for ddl in TEST_SKU_LINK_TRIGGERS_POSTGRESQL)
