"""Synthetic exact pre-012 additive migration; no normal databases are read."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from tire_api.ai_models import AIEvidencePack, AIRequest
from tire_api.db import Base, Database, EvidenceObject, FallbackConsent, QueryRun, UserSession, uid, utcnow
from tire_api.device_ai_models import DeviceAIConsentClaim, DeviceAIPreparation
from tire_api.knowledge_models import initialize_search
from tire_api.main import create_app
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from version_registry import EXPECTED_SCHEMA_VERSIONS, PRE_009_VERSIONS
from test_ai_stream_migration import OLD_VERSIONS, snapshot

NEW_TABLES = {'device_ai_preparations', 'device_ai_consent_claims'}
VERSIONS = [*OLD_VERSIONS, '009_ai_streaming', '010_offline_packs', '011_query_fallback_policies']
ALL_VERSIONS = set(EXPECTED_SCHEMA_VERSIONS)
ACTOR = 'synthetic-device-migration-actor'
OTHER_ACTOR = 'synthetic-device-migration-other'
ARCHIVE_HASH = 'a' * 64
PROJECTION_HASH = 'b' * 64
CONTRACT_HASH = 'c' * 64


@pytest.fixture
def predecessor(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    for key in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(key, '0')
    database = create_app('sqlite:///' + (tmp_path / 'private-pre012.sqlite').as_posix()).state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name not in NEW_TABLES])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
            '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in VERSIONS:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        initialize_search(connection)
    with database.sessions() as db:
        db.add(UserSession(id=ACTOR, expires_at=utcnow() + timedelta(hours=1)))
        db.flush()
        run = QueryRun(id=uid(), session_id=ACTOR, source_id='fixture', source_access_generation=0,
                       query_key='synthetic-pre012-key', query={'size': '265/40R20'}, selection_filters=[],
                       fallback_policy='ask', state='consent_required', reason='synthetic_pre012_failure')
        db.add(run)
        db.flush()
        db.add(FallbackConsent(id=uid(), query_id=run.id, session_id=ACTOR, decision='allow', scope='once',
                               expires_at=utcnow() + timedelta(minutes=5)))
        db.commit()
    yield database
    database.close()


def preparation(db, *, actor=ACTOR, **overrides):
    pack_id = uid()
    now = utcnow()
    db.add(AIEvidencePack(id=pack_id, actor_session_id=actor, mode='history', data_state='local_snapshot',
                          privacy_class='private', payload={}, fingerprint=CONTRACT_HASH,
                          created_at=now, expires_at=now + timedelta(minutes=30)))
    db.flush()
    values = dict(id=uid(), actor_session_id=actor, idempotency_key=uid(), request_hash=CONTRACT_HASH,
                  offline_pack_id='migration-offline-pack', offline_content_hash=ARCHIVE_HASH,
                  host_receipt_id=uid(), intent_id=uid(), selection_hash=CONTRACT_HASH,
                  projection_hash=PROJECTION_HASH, projection_byte_count=20,
                  device_context_fingerprint=CONTRACT_HASH, question_sha256=CONTRACT_HASH,
                  ai_pack_id=pack_id, contract={'schema': 'device-ai-prepare@1'},
                  created_at=now, expires_at=now + timedelta(minutes=30))
    values.update(overrides)
    row = DeviceAIPreparation(**values)
    db.add(row)
    db.flush()
    return row


def analysis_request(db, *, actor=ACTOR, **overrides):
    pack_id = uid()
    now = utcnow()
    db.add(AIEvidencePack(id=pack_id, actor_session_id=actor, mode='history', data_state='local_snapshot',
                          privacy_class='private', payload={}, fingerprint=CONTRACT_HASH,
                          created_at=now, expires_at=now + timedelta(minutes=30)))
    db.flush()
    values = dict(id=uid(), actor_session_id=actor, idempotency_key=uid(), request_hash=CONTRACT_HASH,
                  pack_id=pack_id, question='合成迁移后问题', provider='openai_responses',
                  model='synthetic-model', request_contract={}, reserved_tokens=100)
    values.update(overrides)
    row = AIRequest(**values)
    db.add(row)
    db.flush()
    return row


def claim(db, prepared, requested, *, actor=ACTOR, **overrides):
    values = dict(id=uid(), actor_session_id=actor, preparation_id=prepared.id, ai_request_id=requested.id,
                  analysis_key=requested.idempotency_key, request_hash=CONTRACT_HASH,
                  provider_consent_hash=CONTRACT_HASH, provider='openai_responses',
                  model='synthetic-model', provider_policy_fingerprint=CONTRACT_HASH)
    values.update(overrides)
    row = DeviceAIConsentClaim(**values)
    db.add(row)
    db.flush()
    return row


def test_two_additive_tables_and_012_preserve_every_predecessor_schema_and_row(predecessor):
    before = snapshot(predecessor)
    predecessor.initialize()
    predecessor.initialize()
    after = snapshot(predecessor)
    assert after['tables'] - before['tables'] == NEW_TABLES and not before['tables'] - after['tables']
    assert [row for row in after['schema'] if row[2] in before['tables']] == before['schema']
    assert all(before['rows'][table] == after['rows'][table] for table in before['tables'] - {'tire_schema_versions'})
    assert len(after['rows']['tire_schema_versions']) == len(EXPECTED_SCHEMA_VERSIONS)
    assert all(not after['rows'][table] for table in NEW_TABLES)
    with predecessor.engine.connect() as connection:
        assert set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == ALL_VERSIONS
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        inspector = inspect(connection)

        def unique_column_sets(table):
            # sqlite auto-indexes are constraint truth; SQLAlchemy's get_indexes hides them.
            sets = set()
            for row in connection.exec_driver_sql(f"PRAGMA index_list('{table}')").all():
                if row[2]:
                    columns = frozenset(info[2] for info in connection.exec_driver_sql(f"PRAGMA index_info('{row[1]}')").all())
                    sets.add(columns)
            return sets

        assert {frozenset(pair) for pair in (('actor_session_id', 'idempotency_key'), ('actor_session_id', 'host_receipt_id'),
                                             ('actor_session_id', 'intent_id'), ('id', 'actor_session_id'))} <= unique_column_sets('device_ai_preparations')
        assert {frozenset(('actor_session_id', 'analysis_key')), frozenset(('preparation_id',)), frozenset(('ai_request_id',))} <= unique_column_sets('device_ai_consent_claims')
        foreign_keys = inspector.get_foreign_keys('device_ai_consent_claims')
        assert any(fk['referred_table'] == 'device_ai_preparations'
                   and set(fk['constrained_columns']) == {'preparation_id', 'actor_session_id'}
                   and set(fk['referred_columns']) == {'id', 'actor_session_id'} for fk in foreign_keys)
        assert any(fk['referred_table'] == 'ai_requests' and set(fk['constrained_columns']) == {'ai_request_id'} for fk in foreign_keys)


def test_012_ddl_and_version_rollback_together(predecessor, monkeypatch):
    from tire_api import migrations
    before = snapshot(predecessor)
    original = migrations.upgrade
    def failed(connection):
        original(connection)
        raise RuntimeError('synthetic_012_failure')
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', failed)
        with pytest.raises(RuntimeError, match='synthetic_012_failure'):
            predecessor.initialize()
    assert snapshot(predecessor) == before
    predecessor.initialize()
    assert snapshot(predecessor)['tables'] - before['tables'] == NEW_TABLES
    with predecessor.engine.connect() as connection:
        assert set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == ALL_VERSIONS


def test_migrated_tables_round_trip_and_enforce_the_device_contract(predecessor):
    predecessor.initialize()
    with predecessor.sessions() as db:
        db.add_all([EvidenceObject(raw_hash=ARCHIVE_HASH, byte_count=100),
                    EvidenceObject(raw_hash=PROJECTION_HASH, byte_count=20)])
        db.flush()
        now = utcnow()
        db.add(OfflinePackPlan(id='migration-plan', package_id='migration-offline-pack', actor_session_id=ACTOR,
                               fingerprint=CONTRACT_HASH, preview={}, content_hash=ARCHIVE_HASH, byte_count=100,
                               created_at=now, expires_at=now + timedelta(minutes=10)))
        db.flush()
        db.add(OfflinePack(id='migration-offline-pack', plan_id='migration-plan', actor_session_id=ACTOR,
                           idempotency_key=uid(), request_hash=CONTRACT_HASH, content_hash=ARCHIVE_HASH,
                           byte_count=100, descriptor={}, created_at=now))
        db.flush()
        first = preparation(db)
        db.commit()
        frozen_key, first_id = first.idempotency_key, first.id
        with pytest.raises(IntegrityError):
            preparation(db, idempotency_key=frozen_key)
        db.rollback()
        requested = analysis_request(db)
        granted = claim(db, first, requested)
        db.commit()
        request_id, claim_id = requested.id, granted.id
        foreign = preparation(db)
        foreign_request = analysis_request(db, actor=OTHER_ACTOR)
        db.commit()
        with pytest.raises(IntegrityError):
            claim(db, foreign, foreign_request, actor=OTHER_ACTOR, preparation_id=first_id)
        db.rollback()
        second = preparation(db)
        second_request = analysis_request(db)
        db.commit()
        with pytest.raises(IntegrityError):
            claim(db, second, second_request, ai_request_id=request_id)
        db.rollback()
    with predecessor.sessions() as fresh:
        stored = fresh.get(DeviceAIPreparation, first_id)
        assert stored.actor_session_id == ACTOR and stored.idempotency_key == frozen_key
        assert stored.contract == {'schema': 'device-ai-prepare@1'}
        assert fresh.get(DeviceAIConsentClaim, claim_id).ai_request_id == request_id
        assert fresh.scalar(select(func.count()).select_from(DeviceAIPreparation)) == 3


def test_two_engines_initialize_the_same_pre012_file_concurrently_without_duplicate_versions(predecessor, tmp_path):
    url = 'sqlite:///' + (tmp_path / 'private-pre012.sqlite').as_posix()
    gate = Barrier(2)

    def racer():
        database = Database(url)
        try:
            gate.wait(timeout=5)
            database.initialize()
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(racer) for _ in range(2)]:
            future.result()

    with predecessor.engine.connect() as connection:
        versions = connection.execute(text('SELECT version FROM tire_schema_versions')).scalars().all()
        assert len(versions) == len(EXPECTED_SCHEMA_VERSIONS) and set(versions) == ALL_VERSIONS
        assert NEW_TABLES <= set(inspect(connection).get_table_names())
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.execute(text('SELECT COUNT(*) FROM local_sessions')).scalar() == 1


def test_legacy_orm_writes_still_work_after_012_without_touching_device_ledgers(predecessor):
    predecessor.initialize()
    with predecessor.sessions() as db:
        run = QueryRun(id=uid(), session_id=ACTOR, source_id='fixture', source_access_generation=0,
                       query_key='synthetic-post-012-key', query={'size': '265/40R20'}, selection_filters=[],
                       fallback_policy='ask', state='consent_required', reason='synthetic_after_012_path')
        db.add(run)
        db.flush()
        db.add(FallbackConsent(id=uid(), query_id=run.id, session_id=ACTOR, decision='allow', scope='once',
                               expires_at=utcnow() + timedelta(minutes=5)))
        db.commit()
    after = snapshot(predecessor)
    assert len(after['rows']['query_runs']) == 2 and len(after['rows']['fallback_consents']) == 2
    assert not after['rows']['device_ai_preparations'] and not after['rows']['device_ai_consent_claims']
    with predecessor.engine.connect() as connection:
        assert set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == ALL_VERSIONS


def test_012_models_compile_for_postgresql():
    for model in (DeviceAIPreparation, DeviceAIConsentClaim):
        sql = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert 'CREATE TABLE ' + model.__tablename__ in sql and 'FOREIGN KEY' in sql
