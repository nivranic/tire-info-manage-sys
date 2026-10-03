"""Isolated SQLite record invariants; no app, configured DB/store or Provider."""
from datetime import timedelta

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, delete, event, func, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from tire_api.ai_models import AIEvidencePack, AIRequest
from tire_api.db import Base, EvidenceObject, uid, utcnow
from tire_api.device_ai_models import DeviceAIConsentClaim, DeviceAIPreparation
from tire_api.offline_models import OfflinePack, OfflinePackPlan


ACTOR = 'synthetic-device-actor'
ARCHIVE_HASH = 'a' * 64
PROJECTION_HASH = 'b' * 64
CONTRACT_HASH = 'c' * 64


@pytest.fixture
def records():
    engine = create_engine('sqlite:///:memory:')

    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _record):
        connection.execute('PRAGMA foreign_keys=ON')

    # Deliberately bypass Database/configured_store/startup migrations.
    tables = [EvidenceObject.__table__, OfflinePackPlan.__table__, OfflinePack.__table__,
              AIEvidencePack.__table__, AIRequest.__table__, DeviceAIPreparation.__table__,
              DeviceAIConsentClaim.__table__]
    Base.metadata.create_all(engine, tables=tables)
    now = utcnow()
    with Session(engine) as db:
        db.add_all([EvidenceObject(raw_hash=ARCHIVE_HASH, byte_count=100),
                    EvidenceObject(raw_hash=PROJECTION_HASH, byte_count=20)])
        db.flush()
        db.add(OfflinePackPlan(id='plan', package_id='offline', actor_session_id=ACTOR,
                              fingerprint=CONTRACT_HASH, preview={}, content_hash=ARCHIVE_HASH,
                              byte_count=100, created_at=now, expires_at=now + timedelta(minutes=10)))
        db.flush()
        db.add(OfflinePack(id='offline', plan_id='plan', actor_session_id=ACTOR, idempotency_key=uid(),
                           request_hash=CONTRACT_HASH, content_hash=ARCHIVE_HASH, byte_count=100,
                           descriptor={}, created_at=now))
        db.commit()
    yield engine
    engine.dispose()


def preparation(db, *, actor=ACTOR, **overrides):
    pack_id = uid()
    now = utcnow()
    db.add(AIEvidencePack(id=pack_id, actor_session_id=actor, mode='history', data_state='local_snapshot',
                         privacy_class='private', payload={}, fingerprint=CONTRACT_HASH,
                         created_at=now, expires_at=now + timedelta(minutes=30)))
    db.flush()
    values = dict(id=uid(), actor_session_id=actor, idempotency_key=uid(), request_hash=CONTRACT_HASH,
                  offline_pack_id='offline', offline_content_hash=ARCHIVE_HASH,
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


def request(db, prepared, **overrides):
    values = dict(id=uid(), actor_session_id=prepared.actor_session_id, idempotency_key=uid(),
                  request_hash=CONTRACT_HASH, pack_id=prepared.ai_pack_id, question='合成历史问题',
                  provider='openai_responses', model='synthetic-model', request_contract={},
                  reserved_tokens=100)
    values.update(overrides)
    row = AIRequest(**values)
    db.add(row)
    db.flush()
    return row


def claim(db, prepared, requested, **overrides):
    values = dict(id=uid(), actor_session_id=prepared.actor_session_id,
                  preparation_id=prepared.id, ai_request_id=requested.id,
                  analysis_key=requested.idempotency_key, request_hash=CONTRACT_HASH,
                  provider_consent_hash=CONTRACT_HASH, provider='openai_responses',
                  model='synthetic-model', provider_policy_fingerprint=CONTRACT_HASH)
    values.update(overrides)
    row = DeviceAIConsentClaim(**values)
    db.add(row)
    db.flush()
    return row


def test_fixture_creates_only_the_explicit_related_tables_with_foreign_keys(records):
    assert set(inspect(records).get_table_names()) == {
        'evidence_objects', 'offline_pack_plans', 'offline_packs', 'ai_evidence_packs',
        'ai_requests', 'device_ai_preparations', 'device_ai_consent_claims'}
    with records.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1


@pytest.mark.parametrize('field', ['idempotency_key', 'host_receipt_id', 'intent_id'])
def test_actor_cannot_reuse_preparation_key_intent_or_host_receipt(records, field):
    with Session(records) as db:
        first = preparation(db)
        frozen = getattr(first, field)
        db.commit()
        with pytest.raises(IntegrityError):
            preparation(db, **{field: frozen})
        db.rollback()
        assert db.scalar(select(func.count()).select_from(DeviceAIPreparation)) == 1


def test_same_client_metadata_is_scoped_by_actor_not_an_installation_attestation(records):
    with Session(records) as db:
        first = preparation(db)
        metadata = {name: getattr(first, name) for name in ('idempotency_key', 'host_receipt_id', 'intent_id')}
        preparation(db, actor='another-synthetic-actor', **metadata)
        db.commit()
        assert db.scalar(select(func.count()).select_from(DeviceAIPreparation)) == 2


@pytest.mark.parametrize('size', [0, -1, 44001])
def test_projection_capacity_is_a_database_constraint(records, size):
    with Session(records) as db:
        with pytest.raises(IntegrityError):
            preparation(db, projection_byte_count=size)


@pytest.mark.parametrize('field', ['offline_pack_id', 'offline_content_hash', 'projection_hash', 'ai_pack_id'])
def test_preparation_cannot_reference_missing_server_objects(records, field):
    with Session(records) as db:
        with pytest.raises(IntegrityError):
            preparation(db, **{field: 'missing-server-record'})


def test_preparation_expiry_must_follow_creation(records):
    now = utcnow()
    with Session(records) as db:
        with pytest.raises(IntegrityError):
            preparation(db, created_at=now, expires_at=now)


def test_one_preparation_cannot_be_consumed_by_two_analysis_requests(records):
    with Session(records) as db:
        prepared = preparation(db)
        first = request(db, prepared)
        claim(db, prepared, first)
        db.commit()
        with pytest.raises(IntegrityError):
            claim(db, prepared, request(db, prepared))
        db.rollback()
        assert db.scalar(select(func.count()).select_from(DeviceAIConsentClaim)) == 1
        assert db.scalar(select(func.count()).select_from(AIRequest)) == 1


def test_claim_cannot_pin_a_preparation_belonging_to_another_actor(records):
    with Session(records) as db:
        prepared = preparation(db)
        requested = request(db, prepared)
        with pytest.raises(IntegrityError):
            claim(db, prepared, requested, actor_session_id='another-synthetic-actor')


def test_claim_cannot_reference_a_missing_analysis_request(records):
    with Session(records) as db:
        prepared = preparation(db)
        requested = request(db, prepared)
        with pytest.raises(IntegrityError):
            claim(db, prepared, requested, ai_request_id='missing-request')


@pytest.mark.parametrize('duplicate', ['analysis_key', 'ai_request_id'])
def test_request_and_analysis_key_cannot_claim_two_preparations(records, duplicate):
    with Session(records) as db:
        first = preparation(db)
        requested = request(db, first)
        claimed = claim(db, first, requested)
        second = preparation(db)
        other = request(db, second)
        frozen = getattr(claimed, duplicate)
        db.commit()
        with pytest.raises(IntegrityError):
            claim(db, second, other, **{duplicate: frozen})


def test_failed_reservation_rolls_back_request_and_consent_claim_together(records):
    with Session(records) as db:
        prepared = preparation(db)
        db.commit()
        with pytest.raises(RuntimeError, match='synthetic-before-commit-failure'):
            with db.begin():
                requested = request(db, prepared)
                claim(db, prepared, requested)
                raise RuntimeError('synthetic-before-commit-failure')
        assert db.scalar(select(func.count()).select_from(AIRequest)) == 0
        assert db.scalar(select(func.count()).select_from(DeviceAIConsentClaim)) == 0
        assert db.scalar(select(func.count()).select_from(DeviceAIPreparation)) == 1


@pytest.mark.parametrize('kind', ['preparation', 'claim'])
@pytest.mark.parametrize('mutation', ['update', 'delete'])
def test_product_session_refuses_overwriting_or_deleting_history(records, kind, mutation):
    with Session(records) as db:
        prepared = preparation(db)
        requested = request(db, prepared)
        claimed = claim(db, prepared, requested)
        row = prepared if kind == 'preparation' else claimed
        db.commit()
        if mutation == 'delete':
            db.delete(row)
        else:
            row.request_hash = 'd' * 64
        with pytest.raises(ValueError, match='只能追加'):
            db.flush()
        db.rollback()
        assert db.get(type(row), row.id).request_hash == CONTRACT_HASH


def test_explicitly_modified_json_contract_is_also_immutable(records):
    with Session(records) as db:
        prepared = preparation(db)
        identifier = prepared.id
        db.commit()
        prepared.contract['question_sha256'] = 'changed'
        flag_modified(prepared, 'contract')
        with pytest.raises(ValueError, match='只能追加'):
            db.flush()
        db.rollback()
        assert db.get(DeviceAIPreparation, identifier).contract == {'schema': 'device-ai-prepare@1'}


@pytest.mark.parametrize('kind', ['preparation', 'claim'])
@pytest.mark.parametrize('mutation', ['orm_update', 'orm_delete', 'bulk_update_mappings'])
def test_unloaded_orm_dml_cannot_rewrite_or_release_a_consumed_preparation(records, kind, mutation):
    with Session(records) as db:
        prepared = preparation(db)
        row = prepared if kind == 'preparation' else claim(db, prepared, request(db, prepared))
        model, identifier = type(row), row.id
        db.commit()
        db.expunge_all()
        assert not db.dirty and not db.deleted
        with pytest.raises(ValueError, match='只能追加'):
            if mutation == 'orm_update':
                db.execute(update(model).where(model.id == identifier).values(request_hash='d' * 64))
            elif mutation == 'orm_delete':
                db.execute(delete(model).where(model.id == identifier))
            else:
                db.bulk_update_mappings(model, [{'id': identifier, 'request_hash': 'd' * 64}])
        db.rollback()
        assert db.get(model, identifier).request_hash == CONTRACT_HASH


@pytest.mark.parametrize('kind', ['preparation', 'claim'])
def test_structured_delete_hidden_in_a_read_cte_is_also_rejected(records, kind):
    with Session(records) as db:
        prepared = preparation(db)
        row = prepared if kind == 'preparation' else claim(db, prepared, request(db, prepared))
        model, identifier = type(row), row.id
        db.commit()
        db.expunge_all()
        tombstone = delete(model).where(model.id == identifier).returning(model.id).cte('hidden_write')
        # Rejection must precede SQLite parsing; no PostgreSQL execution is claimed.
        with pytest.raises(ValueError, match='只能追加'):
            db.execute(select(tombstone.c.id))
        db.rollback()
        assert db.get(model, identifier).request_hash == CONTRACT_HASH


def test_structured_guard_does_not_block_an_unrelated_mutable_table(records):
    mutable = Table('synthetic_mutable_table', MetaData(), Column('id', Integer, primary_key=True),
                    Column('value', String))
    mutable.create(records)
    with records.begin() as connection:
        connection.execute(mutable.insert().values(id=1, value='before'))
        disguised = mutable.alias('device_ai_preparations')
        connection.execute(update(disguised).where(disguised.c.id == 1).values(value='after'))
        assert connection.execute(select(mutable.c.value)).scalar() == 'after'
        connection.execute(delete(disguised).where(disguised.c.id == 1))
        assert connection.execute(select(func.count()).select_from(mutable)).scalar() == 0


@pytest.mark.parametrize('kind', ['preparation', 'claim'])
@pytest.mark.parametrize('alias_name', ['ordinary_alias', None])
@pytest.mark.parametrize('mutation', ['update', 'delete'])
def test_table_aliases_do_not_escape_history_protection(records, kind, alias_name, mutation):
    with Session(records) as db:
        prepared = preparation(db)
        row = prepared if kind == 'preparation' else claim(db, prepared, request(db, prepared))
        model, identifier = type(row), row.id
        target = model.__table__.alias(alias_name)
        db.commit()
        db.expunge_all()
        statement = (update(target).where(target.c.id == identifier).values(request_hash='d' * 64)
                     if mutation == 'update' else delete(target).where(target.c.id == identifier))
        with pytest.raises(ValueError, match='只能追加'):
            db.execute(statement)
        db.rollback()
        assert db.get(model, identifier).request_hash == CONTRACT_HASH


@pytest.mark.parametrize('kind', ['preparation', 'claim'])
@pytest.mark.parametrize('mutation', ['upsert_update', 'insert_or_replace'])
def test_insert_variants_cannot_replace_a_previous_consent_or_preparation(records, kind, mutation):
    with Session(records) as db:
        prepared = preparation(db)
        row = prepared if kind == 'preparation' else claim(db, prepared, request(db, prepared))
        model, identifier = type(row), row.id
        values = {column.name: getattr(row, column.name) for column in model.__table__.columns}
        values['request_hash'] = 'd' * 64
        db.commit()
        db.expunge_all()
        statement = sqlite_insert(model).values(**values)
        if mutation == 'upsert_update':
            statement = statement.on_conflict_do_update(index_elements=[model.id], set_={'request_hash': 'd' * 64})
        else:
            statement = statement.prefix_with('OR REPLACE', dialect='sqlite')
        with pytest.raises(ValueError, match='只能追加'):
            db.execute(statement)
        db.rollback()
        assert db.get(model, identifier).request_hash == CONTRACT_HASH


@pytest.mark.parametrize('kind', ['preparation', 'claim'])
def test_conflict_do_nothing_can_preserve_existing_history_without_a_write(records, kind):
    with Session(records) as db:
        prepared = preparation(db)
        row = prepared if kind == 'preparation' else claim(db, prepared, request(db, prepared))
        model, identifier = type(row), row.id
        values = {column.name: getattr(row, column.name) for column in model.__table__.columns}
        values['request_hash'] = 'd' * 64
        db.commit()
        db.expunge_all()
        statement = sqlite_insert(model).values(**values).on_conflict_do_nothing(index_elements=[model.id])
        assert db.execute(statement).rowcount == 0
        db.commit()
        assert db.get(model, identifier).request_hash == CONTRACT_HASH
