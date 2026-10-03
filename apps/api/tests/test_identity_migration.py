"""Namespace migration contracts; seed_legacy creates synthetic v1 history only."""
from copy import deepcopy
from datetime import timedelta
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from tire_api.db import (ChangeEvent, Database, FactVersion, QueryRun, Snapshot,
    TireVariant, UserSession, Verification, WatchItem, uid, utcnow)
from tire_api.domain import TireQuery, VariantInput, digest
from tire_api.identity_contract import (IdentityContractError, MigrationApply, apply_migration,
    cli_engine, contract_metadata, migration_preview, resolve_variant, schema_version)
from tire_api.identity_contract_models import VariantIdentityBinding, VariantIdentityMigrationApplication
from tire_api.service import QueryService, business_facts
from tire_api.source_settings import assert_source_access


def seed_legacy(db, *, namespace='CAI', source_id='fixture', query=None, product_code='LEGACY-1',
                variant_id=None, watch=False, body=None, extra_namespaces=(), session_id=None):
    """Create synthetic v1 evidence; None namespace is unknown, extra_namespaces adds history."""
    query = TireQuery.model_validate(query or {'size': '265/40R20', 'model': 'Fixture Tire'}).canonical()
    query_key = digest(query)
    base = {'brand': 'Fixture Brand', 'model': 'Fixture Tire', 'manufacturer_product_code': product_code,
        'region': 'US', 'size': '265/40ZR20', 'load_index': '104', 'speed_rating': 'Y',
        'xl': True, 'hl': False, 'oe_mark': 'LUC', 'acoustic_technology': 'Fixture Acoustic',
        'run_flat': False, 'source_variant_name': 'synthetic-v1', 'facts': {'utqg_treadwear': 300}}
    if session_id is None:
        session_id = uid()
        db.add(UserSession(id=session_id, expires_at=utcnow() + timedelta(days=1)))
        db.flush()
    snapshots, facts, runs, variants = [], [], [], []
    stored = None
    for index, current_namespace in enumerate((namespace, *extra_namespaces)):
        value = deepcopy(base)
        if current_namespace is not None:
            value['facts']['product_code_type'] = current_namespace
        parsed = VariantInput.model_validate(value)
        key, status = parsed.legacy_identity_key(source_id, query_key, 0)
        if stored is None:
            stored = TireVariant(id=variant_id or uid(), identity_key=key,
                identity=parsed.legacy_identity(), identity_status=status)
            db.add(stored); db.flush()
        raw = body if body is not None else f'synthetic-v1-body:{product_code}:{index}'
        run = QueryRun(id=uid(), session_id=session_id, source_id=source_id, query_key=query_key,
            query=query, fallback_policy='never', state='live')
        db.add(run); db.flush()
        snapshot = Snapshot(id=uid(), source_id=source_id, query_key=query_key,
            source_url='https://fixture.example/tires/product', raw_hash=hashlib.sha256(raw.encode()).hexdigest(),
            body=raw, content_type='text/html', parser_version='fixture@1', etag='"fixture-etag"',
            parsed_variants=[{**parsed.model_dump(), 'id': stored.id, 'identity_key': key,
                'identity_status': status, 'fact_version': index + 1}])
        db.add(snapshot); db.flush()
        fact = FactVersion(id=uid(), variant_id=stored.id, source_id=source_id, snapshot_id=snapshot.id,
            facts=business_facts(parsed.facts), facts_hash=digest(business_facts(parsed.facts)), version=index + 1)
        db.add(fact)
        db.add(Verification(id=uid(), snapshot_id=snapshot.id, query_id=run.id, source_id=source_id,
            query_key=query_key, status='ok', etag='"fixture-etag"'))
        snapshots.append(snapshot.id); facts.append(fact.id); runs.append(run.id); variants.append(parsed.model_dump())
    watch_id = None
    if watch:
        watch_id = uid()
        db.add(WatchItem(id=watch_id, session_id=session_id, variant_id=stored.id))
    db.commit()
    return {'variant_id': stored.id, 'snapshot_ids': snapshots, 'fact_ids': facts, 'query_ids': runs,
        'snapshot_id': snapshots[-1], 'fact_id': facts[-1], 'query_id': runs[-1], 'variant': variants[-1],
        'variants': variants, 'query': query, 'query_key': query_key, 'source_id': source_id,
        'session_id': session_id, 'watch_id': watch_id}


def migration_payload(preview, **changes):
    return MigrationApply.model_validate({'mode': 'history', 'schema': preview['schema'],
        'expected_revision': preview['revision'], 'expected_preview_fingerprint': preview['preview_fingerprint'],
        'acknowledged': True, 'operator': 'synthetic operator', 'reason': 'synthetic migration verification', **changes})


def apply_current(db):
    return apply_migration(db, migration_payload(migration_preview(db)), 'synthetic-cli', str(uuid4()))


@pytest.fixture
def database():
    database = Database('sqlite://')
    database.initialize()
    try:
        yield database
    finally:
        database.close()


def test_preview_and_signed_application_preserve_legacy_rows(database):
    with database.sessions() as db:
        safe = seed_legacy(db, watch=True)
        unknown = seed_legacy(db, namespace=None, product_code='UNKNOWN', watch=True)
        mixed = seed_legacy(db, namespace='MSPN', extra_namespaces=(None,), product_code='MIXED')
        before = [(row.id, deepcopy(row.identity), row.identity_key) for row in db.scalars(select(TireVariant))]
        preview = migration_preview(db)
        assert preview['summary'] == {'legacy_total': 3, 'eligible': 1, 'needs_review': 2,
            'already_bound': 0, 'watch_risk_count': 1, 'rule_risk_count': 0}
        assert preview['can_apply'] is True
        assert db.scalar(select(func.count()).select_from(VariantIdentityBinding)) == 0
        payload, key = migration_payload(preview), str(uuid4())
        receipt = apply_migration(db, payload, 'synthetic-cli', key)
        assert len(receipt['binding_ids']) == 1
        replay = apply_migration(db, payload, 'synthetic-cli', key)
        assert replay['id'] == receipt['id'] and replay['idempotent_replay'] is True
        assert [(row.id, row.identity, row.identity_key) for row in db.scalars(select(TireVariant))] == before
        assert contract_metadata(db, safe['variant_id'])['state'] == 'current'
        assert contract_metadata(db, unknown['variant_id'])['state'] == 'legacy_needs_review'
        assert contract_metadata(db, mixed['variant_id'])['state'] == 'legacy_needs_review'
        assert migration_preview(db)['summary']['already_bound'] == 1
        assert migration_preview(db)['can_apply'] is False
        with pytest.raises(IdentityContractError, match='idempotency_payload_mismatch'):
            apply_migration(db, migration_payload(preview, reason='changed'), 'synthetic-cli', key)
        db.rollback()
        with pytest.raises(IdentityContractError, match='identity_migration_no_changes'):
            apply_current(db)


@pytest.mark.parametrize('damage,reason', [
    ('duplicate', 'legacy_duplicate_snapshot_member'), ('raw', 'legacy_raw_integrity_failed'),
    ('fact_source', 'legacy_fact_evidence_mismatch'), ('fact_version', 'legacy_fact_evidence_mismatch'),
    ('verification', 'legacy_verification_missing'), ('member_key', 'legacy_identity_evidence_mismatch')])
def test_corrupt_legacy_evidence_never_binds(database, damage, reason):
    with database.sessions() as db:
        seeded = seed_legacy(db)
        snapshot = db.get(Snapshot, seeded['snapshot_id'])
        if damage == 'duplicate':
            db.execute(update(Snapshot).where(Snapshot.id == snapshot.id).values(parsed_variants=snapshot.parsed_variants * 2))
        elif damage == 'raw':
            db.execute(update(Snapshot).where(Snapshot.id == snapshot.id).values(body='synthetic corruption'))
        elif damage == 'fact_source':
            db.execute(update(FactVersion).values(source_id='other-fixture'))
        elif damage == 'fact_version':
            db.execute(update(FactVersion).values(version=42))
        elif damage == 'verification':
            db.execute(update(Verification).values(query_key='f' * 64))
        else:
            members = deepcopy(snapshot.parsed_variants); members[0]['identity_key'] = 'e' * 64
            db.execute(update(Snapshot).where(Snapshot.id == snapshot.id).values(parsed_variants=members))
        db.commit(); db.expire_all()
        preview = migration_preview(db)
        assert preview['summary']['eligible'] == 0
        assert reason in preview['items'][0]['reason_codes']
        apply_current(db)
        assert db.scalar(select(func.count()).select_from(VariantIdentityBinding)) == 0
        assert migration_preview(db)['can_apply'] is False


def test_apply_guards_no_writes(database):
    with database.sessions() as db:
        seed_legacy(db)
        preview = migration_preview(db)
        for changes, code in [({'schema': 'old'}, 'version_conflict'), ({'expected_revision': 2}, 'revision_conflict'),
            ({'expected_preview_fingerprint': '0' * 64}, 'preview_stale'), ({'acknowledged': False}, 'acknowledgement_required')]:
            with pytest.raises(IdentityContractError, match=code):
                apply_migration(db, migration_payload(preview, **changes), 'synthetic-cli', str(uuid4()))
            db.rollback()
        assert db.scalar(select(func.count()).select_from(VariantIdentityMigrationApplication)) == 0
        assert db.scalar(select(func.count()).select_from(VariantIdentityBinding)) == 0


def test_migrated_uuid_reused_same_facts_new_contract_snapshot(database):
    with database.sessions() as db:
        seeded = seed_legacy(db)
        old_snapshot = db.get(Snapshot, seeded['snapshot_id'])
        service = QueryService(db, None)
        assert service.transport_cache(seeded['source_id'], seeded['query_key']) is None
        apply_current(db)
        run = QueryRun(id=uid(), session_id=seeded['session_id'], source_id=seeded['source_id'],
            query_key=seeded['query_key'], query=seeded['query'], fallback_policy='never',
            source_access_generation=assert_source_access(db, seeded['source_id']))
        db.add(run); db.commit()
        result = {'body': old_snapshot.body, 'url': old_snapshot.source_url, 'content_type': old_snapshot.content_type,
            'parser_version': old_snapshot.parser_version, 'etag': old_snapshot.etag}
        current, _, rows = service.record_success(run, result, [VariantInput.model_validate(seeded['variant'])])
        db.commit()
        assert current.id != old_snapshot.id and current.identity_contract_version == schema_version()
        assert rows[0]['id'] == seeded['variant_id'] and rows[0]['fact_version'] == 1
        assert db.scalar(select(func.count()).select_from(FactVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ChangeEvent)) == 0
        cache = service.transport_cache(seeded['source_id'], seeded['query_key'])
        assert QueryService.valid_304(cache, {'url': old_snapshot.source_url, 'parser_version': old_snapshot.parser_version})
        assert migration_preview(db)['items'][0]['reason_codes'] == []


def test_migrated_namespace_does_not_absorb_another_namespace(database):
    with database.sessions() as db:
        seeded = seed_legacy(db, watch=True)
        apply_current(db)
        cai = VariantInput.model_validate(seeded['variant'])
        value = deepcopy(seeded['variant']); value['facts']['product_code_type'] = 'MSPN'
        mspn = VariantInput.model_validate(value)
        service = QueryService(db, None)
        ids = None
        for index, verification_status in enumerate(('ok', 'ok', 'not_modified')):
            run = QueryRun(id=uid(), session_id=seeded['session_id'], source_id='fixture',
                query_key=seeded['query_key'], query=seeded['query'], fallback_policy='never',
                source_access_generation=assert_source_access(db, 'fixture'))
            db.add(run); db.commit()
            snapshot, _, rows = service.record_success(run, {'body': 'synthetic-two-code-namespaces',
                'url': 'https://fixture.example/tires/product', 'content_type': 'text/html',
                'parser_version': 'fixture@1', 'etag': '"v2"'}, [cai, mspn], verification_status)
            db.commit()
            assert rows[0]['id'] == seeded['variant_id'] and rows[1]['id'] != seeded['variant_id']
            assert ids is None or ids == [row['id'] for row in rows]
            ids = [row['id'] for row in rows]
        assert db.get(WatchItem, seeded['watch_id']).variant_id == seeded['variant_id']
        assert db.scalar(select(func.count()).select_from(TireVariant)) == 2
        assert db.scalar(select(func.count()).select_from(FactVersion)) == 2
        assert migration_preview(db)['items'][0]['reason_codes'] == []


def test_unknown_assessment_creates_independent_entity_and_preserves_watch(database):
    with database.sessions() as db:
        seeded = seed_legacy(db, namespace=None, watch=True)
        value = deepcopy(seeded['variant']); value['facts']['product_code_type'] = 'MSPN'
        parsed = VariantInput.model_validate(value)
        with pytest.raises(IdentityContractError, match='identity_migration_required'):
            resolve_variant(db, parsed, seeded['source_id'], seeded['query_key'], 0, uid())
        db.rollback(); apply_current(db)
        current, _, _ = resolve_variant(db, parsed, seeded['source_id'], seeded['query_key'], 0, uid())
        db.commit()
        assert current.id != seeded['variant_id']
        assert db.get(WatchItem, seeded['watch_id']).variant_id == seeded['variant_id']
        old_contract = contract_metadata(db, seeded['variant_id'])
        assert old_contract['tracking_state'] == 'identity_review_required'
        assert old_contract['related_candidates'][0]['variant_id'] == current.id
        assert contract_metadata(db, current.id)['related_candidates'][0]['variant_id'] == seeded['variant_id']


def test_occupied_canonical_key_never_reassigns_a_legacy_uuid(database):
    with database.sessions() as db:
        # A preexisting current entity may coexist with an independently imported
        # v1 archive. Migration must retain both rather than choose a survivor.
        template = seed_legacy(db)
        parsed = VariantInput.model_validate(template['variant'])
        key, status = parsed.identity_key('fixture', template['query_key'], 0)
        current = TireVariant(id=uid(), identity_key=key, identity=parsed.identity(), identity_status=status)
        db.add(current); db.flush()
        from tire_api.identity_contract import _new_binding
        db.add(_new_binding(variant_id=current.id, key=key, identity=parsed.identity(), status=status,
            origin='source_observation', proof={'synthetic_independent_archive': True}))
        db.commit()
        preview = migration_preview(db)
        assert preview['summary']['legacy_total'] == 1 and preview['summary']['eligible'] == 0
        assert 'canonical_key_collision' in preview['items'][0]['reason_codes']
        apply_current(db)
        assert db.scalar(select(func.count()).select_from(TireVariant)) == 2
        assert contract_metadata(db, template['variant_id'])['state'] == 'legacy_needs_review'
        assert contract_metadata(db, current.id)['state'] == 'current'


def test_unknown_namespace_rows_are_separate_even_with_same_code(database):
    import asyncio
    from tire_api.domain import LiveQueryRequest
    from test_core import FixtureRegistry, VARIANT, success
    with database.sessions() as db:
        actor = uid()
        db.add(UserSession(id=actor, expires_at=utcnow() + timedelta(days=1))); db.commit()
        registry = FixtureRegistry()
        registry.result = success(variants=[VARIANT, {**VARIANT, 'facts': {'utqg_treadwear': 420}}])
        result = asyncio.run(QueryService(db, registry).execute('fixture',
            LiveQueryRequest.model_validate({'query': {'size': '265/40R20'}, 'fallback_policy': 'never'}), actor))
        assert result['data_state'] == 'live' and len(result['variants']) == 2
        assert len({row['id'] for row in result['variants']}) == 2
        assert all(row['identity_contract']['identity_status'] == 'source_scoped' for row in result['variants'])


def test_changed_legacy_evidence_invalidates_assessment(database):
    with database.sessions() as db:
        seeded = seed_legacy(db, namespace=None)
        apply_current(db)
        db.execute(update(Snapshot).where(Snapshot.id == seeded['snapshot_id']).values(body='synthetic changed body'))
        db.commit()
        with pytest.raises(IdentityContractError, match='identity_migration_stale'):
            resolve_variant(db, VariantInput.model_validate(seeded['variant']), seeded['source_id'], seeded['query_key'], 0, uid())


def test_adoption_barrier_rolls_back_whole_batch_but_keeps_raw(database):
    import asyncio
    from tire_api.db import RawCapture
    from tire_api.domain import LiveQueryRequest
    with database.sessions() as db:
        seeded = seed_legacy(db, namespace=None)
        existing = deepcopy(seeded['variant']); existing['facts']['product_code_type'] = 'CAI'
        new = {**deepcopy(existing), 'manufacturer_product_code': 'NEW-FIRST'}

        class Registry:
            def sources(self):
                return [{'id': 'fixture', 'status': 'ready'}]

            async def fetch(self, source_id, query, cached=None, *, on_observation=None):
                assert cached is None
                result = {'status': 'ok', 'body': 'synthetic batch before identity barrier',
                    'url': 'https://fixture.example/tires/product', 'content_type': 'text/html',
                    'parser_version': 'fixture@1', 'variants': [new, existing]}
                on_observation(result)
                return result

        result = asyncio.run(QueryService(db, Registry()).execute('fixture',
            LiveQueryRequest.model_validate({'query': seeded['query'], 'fallback_policy': 'never'}), seeded['session_id']))
        assert result['data_state'] == 'source_unavailable' and result['reason'] == 'identity_migration_required'
        assert db.scalar(select(func.count()).select_from(TireVariant)) == 1
        assert db.scalar(select(func.count()).select_from(Snapshot)) == 1
        assert db.scalar(select(func.count()).select_from(FactVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ChangeEvent)) == 0
        assert db.scalar(select(func.count()).select_from(VariantIdentityBinding)) == 0
        assert db.scalar(select(func.count()).select_from(RawCapture)) == 1


def test_old_watch_and_precise_rule_are_visible_but_cannot_track_or_reenable(tmp_path):
    from fastapi.testclient import TestClient
    from tire_api.db import AlertRule, AlertRuleRevision, MonitorJob
    from tire_api.main import create_app
    from tire_api.monitoring import claim_job, interval_for
    from test_core import FixtureRegistry
    database_url = f"sqlite:///{(tmp_path / 'watch-rule.sqlite').as_posix()}"
    app = create_app(database_url, FixtureRegistry())
    with TestClient(app) as client:
        client.get('/health')
        with app.state.database.sessions() as db:
            session_id = db.scalar(select(UserSession.id))
            seeded = seed_legacy(db, namespace=None, watch=True, session_id=session_id)
            job = MonitorJob(id=uid(), source_id='fixture', query=seeded['query'], next_due_at=utcnow())
            db.add(job); db.flush()
            rule = AlertRule(id=uid(), job_id=job.id, variant_id=seeded['variant_id'])
            db.add(rule); db.flush()
            db.add(AlertRuleRevision(rule_id=rule.id, revision=1, name='synthetic old precise rule',
                enabled=True, archived=False, interval_seconds=14400, kinds=['facts_changed'], fields=[],
                conditions={}, actor_session_id=session_id))
            db.commit(); apply_current(db)
            rule_id = rule.id
            assert interval_for(db, job.id) is None
        assert claim_job(app.state.database) is None
        watch = client.get('/v1/watchlists').json()['items'][0]
        assert watch['variant_id'] == seeded['variant_id']
        assert watch['identity_contract']['tracking_state'] == 'identity_review_required'
        assert client.post('/v1/watchlists', json={'variant_id': seeded['variant_id']}).status_code == 409
        assert client.post('/v1/compare', json={'variant_ids': [seeded['variant_id']]}).status_code == 409
        detail = client.get(f'/v1/alert-rules/{rule_id}?mode=history').json()
        assert detail['tracking_state'] == 'identity_review_required' and detail['job']['next_due_at'] is None
        payload = {'expected_revision': 1, 'name': detail['name'], 'enabled': True,
            'interval_seconds': 14400, 'kinds': ['facts_changed'], 'fields': [], 'conditions': {}}
        assert client.put(f'/v1/alert-rules/{rule_id}', json=payload).status_code == 409
        paused = client.put(f'/v1/alert-rules/{rule_id}', json={**payload, 'enabled': False})
        assert paused.status_code == 200 and paused.json()['enabled'] is False


def test_cli_readonly_requires_existing_schema_and_cannot_write(tmp_path):
    import sqlite3
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    missing = tmp_path / 'missing' / 'db.sqlite'
    with pytest.raises(IdentityContractError, match='schema_required'):
        cli_engine(f'sqlite:///{missing.as_posix()}', readonly=True)
    assert not missing.parent.exists()
    empty = tmp_path / 'empty.sqlite'
    with sqlite3.connect(empty):
        pass
    before = empty.read_bytes()
    with pytest.raises(IdentityContractError, match='schema_required'):
        cli_engine(f'sqlite:///{empty.as_posix()}', readonly=True)
    assert empty.read_bytes() == before
    path = tmp_path / 'initialized.sqlite'
    database = Database(f'sqlite:///{path.as_posix()}'); database.initialize()
    with database.sessions() as db:
        seed_legacy(db)
    database.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    engine = cli_engine(f'sqlite:///{path.as_posix()}', readonly=True)
    try:
        with Session(engine) as db:
            assert migration_preview(db)['summary']['eligible'] == 1
            with pytest.raises(Exception, match='readonly'):
                db.execute(text('DELETE FROM tire_variants'))
            db.rollback()
    finally:
        engine.dispose()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_cli_process_preview_has_no_startup_side_effects(tmp_path):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[3]
    missing = tmp_path / 'missing-directory' / 'missing.sqlite'
    object_root = tmp_path / 'must-not-create-objects'
    env = {**os.environ, 'TIRE_DATABASE_URL': f'sqlite:///{missing.as_posix()}',
        'TI_OBJECT_STORE_ROOT': str(object_root), 'PYTHONPATH': str(root / 'apps/api')}
    command = [sys.executable, str(root / 'scripts/identity_contract.py'), 'preview']
    result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 2 and json.loads(result.stdout)['error_code'] == 'identity_contract_schema_required'
    assert not missing.parent.exists() and not object_root.exists()
    path = tmp_path / 'existing.sqlite'
    database = Database(f'sqlite:///{path.as_posix()}'); database.initialize()
    with database.sessions() as db:
        seed_legacy(db)
    database.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    env['TIRE_DATABASE_URL'] = f'sqlite:///{path.as_posix()}'
    result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0 and json.loads(result.stdout)['summary']['eligible'] == 1
    assert not object_root.exists()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_concurrent_identical_migration_request_has_one_receipt(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    database = Database(f"sqlite:///{(tmp_path / 'migration-race.sqlite').as_posix()}")
    database.initialize()
    try:
        with database.sessions() as db:
            seed_legacy(db)
            payload = migration_payload(migration_preview(db))
        key, barrier = str(uuid4()), Barrier(2)

        def apply(_):
            with database.sessions() as db:
                barrier.wait(timeout=10)
                return apply_migration(db, payload, 'synthetic-cli', key)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(apply, range(2)))
        assert results[0]['id'] == results[1]['id']
        assert sorted(row['idempotent_replay'] for row in results) == [False, True]
        with database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(VariantIdentityMigrationApplication)) == 1
            assert db.scalar(select(func.count()).select_from(VariantIdentityBinding)) == 1
    finally:
        database.close()


@pytest.mark.parametrize('model', [VariantIdentityBinding, VariantIdentityMigrationApplication])
def test_migration_receipts_and_bindings_are_append_only(database, model):
    with database.sessions() as db:
        seed_legacy(db)
        apply_current(db)
        row = db.scalar(select(model))
        row.fingerprint = '0' * 64
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()
        db.rollback()
        row = db.scalar(select(model))
        db.delete(row)
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()


def test_backup_replay_keeps_every_original_column_and_row(tmp_path):
    """Only the explicit immutable Round 38 backup is read; all writes use tmp_path."""
    import json
    import sqlite3
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    backup = root / '.artifacts/runtime/round38-before.sqlite'
    if not backup.is_file():
        pytest.skip('explicit read-only Round 38 backup not available')
    original_sha = hashlib.sha256(backup.read_bytes()).hexdigest()
    private = tmp_path / 'backup-replay.sqlite'

    def table_state(connection, table, columns):
        quoted = ','.join('"' + name.replace('"', '""') + '"' for name in columns)
        hashes = sorted(hashlib.sha256(repr(tuple(row)).encode()).hexdigest()
                        for row in connection.execute(f'SELECT {quoted} FROM "{table}"'))
        return {'count': len(hashes), 'hash': digest(hashes), 'row_hashes': hashes}

    with sqlite3.connect(backup.as_uri() + '?mode=ro&immutable=1', uri=True) as source:
        before_versions = {row[0] for row in source.execute('SELECT version FROM tire_schema_versions')}
        tables = [row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        columns = {name: [row[1] for row in source.execute(f'PRAGMA table_info("{name}")')] for name in tables}
        before = {name: table_state(source, name, columns[name]) for name in tables}
        with sqlite3.connect(private) as target:
            source.backup(target)
    database = Database(f'sqlite:///{private.as_posix()}')
    database.initialize()
    with database.sessions() as db:
        preview = migration_preview(db)
        assert preview['summary'] == {'legacy_total': 92, 'eligible': 83, 'needs_review': 9,
            'already_bound': 0, 'watch_risk_count': 1, 'rule_risk_count': 0}
        receipt = apply_current(db)
        assert len(receipt['binding_ids']) == 83
        after_summary = migration_preview(db)['summary']
        assert after_summary['already_bound'] == 83 and after_summary['needs_review'] == 9
    database.close()
    with sqlite3.connect(private.as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        after = {name: table_state(connection, name, columns[name]) for name in tables}
        for name in tables:
            assert set(before[name]['row_hashes']) <= set(after[name]['row_hashes']), name
            if name != 'tire_schema_versions':
                assert before[name] == after[name], name
        assert {row[0] for row in connection.execute('SELECT version FROM tire_schema_versions')} == (
            before_versions | {'005_variant_identity_contract', '006_source_settings', '007_monitor_tasks', '008_recall_discovery_monitoring', '009_ai_streaming', '010_offline_packs', '011_query_fallback_policies', '012_device_ai_preparations', '013_device_ai_ledger_triggers'})
        assert connection.execute('SELECT COUNT(*) FROM snapshots WHERE identity_contract_version IS NOT NULL').fetchone()[0] == 0
    final_sha = hashlib.sha256(backup.read_bytes()).hexdigest()
    assert final_sha == original_sha
    report = {'backup_sha256_before': original_sha, 'backup_sha256_after': final_sha,
        'original_tables': len(tables), 'preview': preview['summary'], 'after': after_summary,
        'bindings_added': len(receipt['binding_ids']), 'applications_added': 1,
        'original_columns_unchanged': True, 'old_snapshot_contracts_remain_null': True,
        'tables': {name: {'columns': columns[name], 'before_count': before[name]['count'],
            'after_count': after[name]['count'], 'before_hash': before[name]['hash'],
            'after_hash': after[name]['hash']} for name in tables}}
    output = root / '.artifacts/runtime/round38-migration-tests/backup-replay.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
