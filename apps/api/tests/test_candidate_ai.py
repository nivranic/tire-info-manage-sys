"""R77 private HTTP integration; controlled provider is never real model acceptance."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text

from candidate_ai_support import (configured_environment, grant_all, grant_payload, ok, prepare,
    seed_candidate_ai, submit_payload)


@pytest.fixture
def candidate_ai_case(tmp_path, monkeypatch):
    parent = Path(os.environ.get('R77_TEST_STORAGE_ROOT', str(tmp_path)))
    url = configured_environment(monkeypatch, parent / uuid4().hex[:8])
    from tire_api.main import create_app
    from test_fitment_relations import NoNetworkRegistry
    app = create_app(url, NoNetworkRegistry())
    with TestClient(app, backend_options={'loop_factory': asyncio.SelectorEventLoop}) as client:
        yield seed_candidate_ai(client)
    app.state.database.engine.dispose()


def test_prepare_without_rights_is_local_and_complete(candidate_ai_case):
    case = candidate_ai_case
    result = prepare(case)
    assert result['schema'] == 'candidate-ai-preparation@1'
    assert result['purpose'] == 'candidate_spec_assistance@1'
    assert len(result['candidates']) == 2
    assert result['sendable'] is False and result['consent_hash'] is None
    assert result['blockers'] == ['candidate_ai_dependency_permission_missing']
    assert case.adapter.calls == []
    assert {dep['source_kind'] for dep in result['dependencies']} == {'vehicle', 'tire', 'relation'}
    assert all(dep['fields'] and dep['authorization'] is None for dep in result['dependencies'])


def test_real_prepare_grant_new_prepare_submit_and_recover(candidate_ai_case):
    case = candidate_ai_case
    first = prepare(case)
    grant_all(case, first)
    ready = prepare(case)
    assert ready['sendable'] is True and ready['consent_hash']
    assert all(dep['authorization']['revision'] == 1 for dep in ready['dependencies'])
    identifier = case.variants[0]
    reason = ready['candidates'][0]['reasons'][0]['id']
    case.adapter.text = json.dumps({'decision': 'choose', 'selections': [{'variant_id': identifier,
        'reason_ids': [reason]}], 'uncertainty_codes': []})
    key = str(uuid4())
    result = ok(case.client.post('/v1/ai/candidate-recommendations', json=submit_payload(ready),
        headers={'Idempotency-Key': key}))
    assert result['state'] == 'completed', result
    assert len(case.adapter.calls) == 1
    answer = result['answer']
    assert answer['selections'][0]['variant_id'] == identifier
    assert answer['not_selected_variant_ids'] == [case.variants[1]]
    assert answer['ranking'] == 'not_computed' and answer['performance_score'] is None
    assert result['current'] is False
    assert result['current_status']['state'] == 'unchanged'
    replay = ok(case.client.post('/v1/ai/candidate-recommendations', json=submit_payload(ready),
        headers={'Idempotency-Key': key}))
    assert replay['id'] == result['id'] and len(case.adapter.calls) == 1
    restored = ok(case.client.get('/v1/ai/candidate-recommendations?mode=history&key=' + key))
    assert restored['id'] == result['id'] and len(case.adapter.calls) == 1
    assert case.client.post('/v1/ai/candidate-recommendations', json=submit_payload(ready),
        headers={'Idempotency-Key': str(uuid4())}).status_code == 409
    outbound = json.dumps(case.adapter.calls[0], ensure_ascii=False)
    for prohibited in ('license_basis', 'rights_holder', 'source_url', 'source_variant_name', 'facts', 'reviewer', 'TestEvent'):
        assert prohibited not in outbound


@pytest.mark.parametrize('operation', ['analyses', 'analysis-streams', 'rule-drafts'])
def test_generic_submission_cannot_consume_candidate_package(candidate_ai_case, operation):
    case = candidate_ai_case
    value = prepare(case)
    data = {'pack_id': value['pack_id'], 'allow_external_processing': True}
    if operation != 'rule-drafts':
        data['question'] = 'Synthetic generic bypass attempt'
    response = case.client.post('/v1/ai/' + operation, json=data, headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'candidate_ai_dedicated_route_required'
    assert case.adapter.calls == []


def test_changed_preference_rejects_old_consent_without_call(candidate_ai_case):
    case = candidate_ai_case
    initial = prepare(case)
    grant_all(case, initial)
    ready = prepare(case)
    weights = deepcopy(case.preference['weights'])
    weights['dry'] += 1
    weights['wet'] -= 1
    ok(case.client.put('/v1/driving-preferences', json={'expected_revision': case.preference['revision'], 'weights': weights}))
    response = case.client.post('/v1/ai/candidate-recommendations', json=submit_payload(ready),
        headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 409
    assert case.adapter.calls == []


def test_authorization_aba_does_not_restore_preparation(candidate_ai_case):
    case = candidate_ai_case
    initial = prepare(case)
    grant_all(case, initial)
    ready = prepare(case)
    dep = ready['dependencies'][0]
    path = '/v1/ai/candidate-preparations/' + ready['preparation_id'] + '/authorizations'
    ok(case.client.post(path, json=grant_payload(dep, revision=1, action='revoke')))
    ok(case.client.post(path, json=grant_payload(dep, revision=2, action='grant')))
    response = case.client.post('/v1/ai/candidate-recommendations', json=submit_payload(ready),
        headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 409 and case.adapter.calls == []


def test_append_only_sql_guards_are_installed(candidate_ai_case):
    case = candidate_ai_case
    initial = prepare(case)
    grant_all(case, initial)
    for table in ('candidate_ai_preparations', 'candidate_ai_authorizations'):
        with pytest.raises(Exception, match='candidate_ai_history_immutable'):
            with case.database.engine.begin() as connection:
                connection.execute(text('DELETE FROM ' + table))


def test_append_only_sql_replace_cannot_destroy_any_unique_history(candidate_ai_case):
    case = candidate_ai_case
    initial = prepare(case)
    grant_all(case, initial)
    ready = prepare(case)
    ok(case.client.post('/v1/ai/candidate-recommendations', json=submit_payload(ready),
        headers={'Idempotency-Key': str(uuid4())}))
    from tire_api.candidate_ai_models import MODELS
    conflicts = {
        'candidate_ai_authorizations': [('scope_hash',), ('id',)],
        'candidate_ai_preparations': [('pack_id',), ('id',)],
        'candidate_ai_claims': [('preparation_id', 'request_id'), ('id', 'request_id'), ('id', 'preparation_id')]}
    for model in MODELS:
        table = model.__tablename__
        columns = [column.name for column in model.__table__.columns]
        with case.database.engine.connect() as connection:
            before = connection.execute(text('SELECT * FROM ' + table)).all()
        # Isolate each primary/secondary unique collision while replacing all
        # other unique identities, with recursive_triggers explicitly off.
        for changed_columns in conflicts[table]:
            changes = {name: uuid4().hex for name in changed_columns}
            projection = [':' + name if name in changes else name for name in columns]
            with pytest.raises(Exception, match='candidate_ai_history_immutable'):
                with case.database.engine.begin() as connection:
                    connection.exec_driver_sql('PRAGMA recursive_triggers=OFF')
                    connection.execute(text(f'INSERT OR REPLACE INTO {table} ({", ".join(columns)}) '
                        f'SELECT {", ".join(projection)} FROM {table} LIMIT 1'), changes)
        with case.database.engine.connect() as connection:
            assert connection.execute(text('SELECT * FROM ' + table)).all() == before


@pytest.fixture
def candidate_ai_predecessor(tmp_path, monkeypatch):
    """A real pre-021 file schema and synthetic business history, never normal DB."""
    parent = Path(os.environ.get('R77_TEST_STORAGE_ROOT', str(tmp_path)))
    url = configured_environment(monkeypatch, parent / uuid4().hex[:8])
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    from tire_api.main import create_app
    from tire_api.db import Base
    from tire_api.candidate_ai_models import TABLES
    from tire_api.webhook_models import MODELS as WEBHOOK_MODELS
    from tire_api.external_api_models import TABLES as EXTERNAL_TABLES
    from tire_api.knowledge_models import initialize_search
    from test_identity_migration import seed_legacy
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    database = create_app(url).state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables
            if table.name not in {*TABLES, *EXTERNAL_TABLES, *(model.__tablename__ for model in WEBHOOK_MODELS)}])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
            '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in EXPECTED_SCHEMA_VERSIONS[:20]:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        initialize_search(connection)
    with database.sessions() as db:
        seed_legacy(db, namespace='SYNTHETIC-R77', product_code='SYNTHETIC-PRE021', watch=True)
    try:
        yield database
    finally:
        database.close()


def test_021_file_migration_preserves_old_schema_and_rows_and_is_idempotent(candidate_ai_predecessor):
    from test_ai_stream_migration import snapshot
    from tire_api.candidate_ai_models import TABLES
    from tire_api.webhook_models import MODELS as WEBHOOK_MODELS
    from tire_api.external_api_models import TABLES as EXTERNAL_TABLES
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    database = candidate_ai_predecessor
    assert database.engine.url.database and Path(database.engine.url.database).is_file()
    before = snapshot(database)
    assert not set(TABLES) & before['tables']
    database.initialize()
    first = snapshot(database)
    database.initialize()
    after = snapshot(database)
    assert first == after
    assert after['tables'] - before['tables'] == {*TABLES, *EXTERNAL_TABLES, *(model.__tablename__ for model in WEBHOOK_MODELS)}
    assert not before['tables'] - after['tables']
    assert [row for row in after['schema'] if row[2] in before['tables']] == before['schema']
    for table in before['tables'] - {'tire_schema_versions'}:
        assert after['rows'][table] == before['rows'][table], table
    assert all(not after['rows'][table] for table in TABLES)
    with database.engine.connect() as connection:
        assert list(connection.execute(text('SELECT version FROM tire_schema_versions ORDER BY version')).scalars()) == EXPECTED_SCHEMA_VERSIONS
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar_one() == 'ok'
        triggers = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'trigger'").scalars().all()
        assert all(table + '_no_' + operation in triggers for table in TABLES for operation in ('update', 'delete', 'replace'))


def test_021_file_migration_failure_rolls_back_schema_and_version(candidate_ai_predecessor, monkeypatch):
    from test_ai_stream_migration import snapshot
    from tire_api import migrations
    database = candidate_ai_predecessor
    before = snapshot(database)
    upgrade = migrations.upgrade
    def fail_after_upgrade(connection):
        upgrade(connection)
        raise RuntimeError('synthetic_r77_migration_rollback')
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', fail_after_upgrade)
        with pytest.raises(RuntimeError, match='synthetic_r77_migration_rollback'):
            database.initialize()
    assert snapshot(database) == before
    database.initialize()
