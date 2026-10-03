"""Explicitly authorized private PG18 migration/restore acceptance; synthetic evidence only.

Launch through round38-verify-identity-postgres.ps1. No production database,
source transport, Parser child, AI or embedding provider is used.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from threading import Barrier
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
REPORT = {'status': 'running', 'scope': 'synthetic_identity_migration_private_postgresql', 'checks': []}
STEP = 'isolation'


def record(name: str) -> None:
    REPORT['checks'].append(name)
    print(json.dumps({'check': name, 'status': 'passed'}), flush=True)


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def fingerprints(database, metadata) -> dict:
    """Every registered column value; keep row hashes privately for subset proofs."""
    with database.engine.connect() as connection:
        result = {}
        for table in metadata.sorted_tables:
            rows = connection.execute(table.select()).mappings().all()
            row_hashes = sorted(hashlib.sha256(encoded(dict(row)).encode()).hexdigest() for row in rows)
            result[table.name] = {'columns': [column.name for column in table.columns], 'rows': len(rows),
                'sha256': hashlib.sha256(encoded(row_hashes).encode()).hexdigest(), 'row_hashes': row_hashes}
        return result


def retained_rows(before: dict, after: dict) -> bool:
    return all(not (Counter(value['row_hashes']) - Counter(after[name]['row_hashes']))
               for name, value in before.items())


def public_fingerprints(values: dict) -> dict:
    return {name: {key: value[key] for key in ('columns', 'rows', 'sha256')} for name, value in values.items()}


def file_hashes(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file()}


def run() -> None:
    global STEP
    runtime_root = (ROOT / '.artifacts/runtime').resolve()
    run_root = Path(os.environ['TIRE_PG_RUN_ROOT']).resolve()
    expected = Path(os.environ['TIRE_PG_TEST_DATA']).resolve()
    assert run_root.parent == runtime_root and run_root.name.startswith('round38-identity-PG-')
    assert expected == run_root / 'data'
    assert int(os.environ['TIRE_PG_TEST_PORT']) == 55438
    assert Path(os.environ['TIRE_PG_TEST_REPORT']).resolve() == run_root / 'report.json'
    assert os.environ['TI_AI_ENABLED'] == os.environ['TI_EMBEDDINGS_ENABLED'] == '0'
    assert os.environ['TI_OBJECT_STORE_BACKEND'] == 'filesystem'
    object_root = Path(os.environ['TI_OBJECT_STORE_ROOT']).resolve()
    assert object_root == run_root / 'objects'
    assert Path(os.environ['TI_PARSER_BUNDLE_ROOT']).resolve() == run_root / 'bundles'
    import_guard = 'sqlite:///' + (run_root / 'import-guard.sqlite').as_posix()
    assert os.environ['TIRE_DATABASE_URL'] == os.environ['DATABASE_URL'] == import_guard
    pg_bin = Path(os.environ['TIRE_PG_BIN']).resolve()
    assert pg_bin == Path('E:/PostgreSQL/18/bin').resolve()
    for program in ('pg_dump.exe', 'pg_restore.exe'):
        assert (pg_bin / program).is_file()

    # All environment guards precede application imports and their global app.
    sys.path.insert(0, str(ROOT / 'apps/api'))
    sys.path.insert(0, str(ROOT / 'apps/api/tests'))
    import psycopg
    from psycopg import sql
    from sqlalchemy import func, select, text
    from sqlalchemy.engine import URL
    from fastapi.testclient import TestClient
    from tire_api.db import (Base, Database, FactVersion, QueryRun, RawCapture,
        Snapshot, TireVariant, WatchItem)
    from tire_api.ai_models import AIRequest
    from tire_api.embedding_models import EmbeddingRequest
    from tire_api.captures import before_parse_recorder, checked_capture_bytes
    from tire_api.domain import LiveQueryRequest
    from tire_api.identity_contract import (IdentityContractError, apply_migration,
        application_view, contract_metadata, migration_preview)
    from tire_api.identity_contract_models import VariantIdentityBinding, VariantIdentityMigrationApplication
    from tire_api.main import create_app
    from tire_api.service import QueryService
    from test_core import FixtureRegistry
    from test_identity_migration import migration_payload, seed_legacy

    admin = psycopg.connect(host='127.0.0.1', port=55438, user='tire_identity_verify_admin',
        password=os.environ['TIRE_PG_TEST_PASSWORD'], dbname='postgres', autocommit=True, connect_timeout=5)
    database = restored = None
    try:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == expected
        REPORT['postgres_version'] = admin.execute('SHOW server_version').fetchone()[0]
        assert REPORT['postgres_version'].split('.')[0] == '18'
        role, password = 'identity_app_' + uuid4().hex[:12], secrets.token_hex(32)
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION').format(
            sql.Identifier(role), sql.Literal(password)))

        def new_database(name):
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(role)))
            return URL.create('postgresql+psycopg', username=role, password=password,
                host='127.0.0.1', port=55438, database=name).render_as_string(hide_password=False)

        name = 'identity_' + uuid4().hex[:12]
        url = new_database(name)
        database = Database(url)
        database.initialize()
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT current_user').scalar_one() == role
            assert connection.execute(text('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication '
                'FROM pg_roles WHERE rolname = current_user')).scalar_one() is False
        record('fresh_loopback_pg18_cluster_non_superuser_application_role')

        STEP = 'synthetic_legacy_seed'
        with database.sessions() as db:
            safe = seed_legacy(db, product_code='PG-SAFE', watch=True, query={'size': '265/40R20'})
            actor = safe['session_id']
            unknown = seed_legacy(db, product_code='PG-UNKNOWN', namespace=None, watch=True,
                query={'model': 'Fixture Tire'}, session_id=actor)
            mixed = seed_legacy(db, product_code='PG-MIXED', namespace='MSPN', extra_namespaces=(None,),
                session_id=actor)
            records = {'safe': safe, 'unknown': unknown, 'mixed': mixed}
            for item in records.values():
                run_row = db.get(QueryRun, item['query_id'])
                snapshot = db.get(Snapshot, item['snapshot_id'])
                recorder = before_parse_recorder(db, run_row)
                observation = {'body': snapshot.body, 'url': snapshot.source_url,
                    'content_type': snapshot.content_type, 'parser_version': snapshot.parser_version}
                db.commit()
                recorder(observation)
            assert db.scalar(select(func.count()).select_from(RawCapture)) == 3
        old_rows = fingerprints(database, Base.metadata)
        record('three_synthetic_legacy_entities_with_known_unknown_mixed_evidence_and_old_watches')

        class SyntheticRegistry(FixtureRegistry):
            def __init__(self):
                super().__init__()
                self.calls = 0

            async def fetch(self, source_id, query, cached=None, *, on_observation=None):
                self.calls += 1
                on_observation(self.result)
                return deepcopy(self.result)

        registry = SyntheticRegistry()
        observation = deepcopy(unknown['variant'])
        observation['facts']['product_code_type'] = 'CAI'
        first = {**deepcopy(observation), 'manufacturer_product_code': 'PG-NEW-BEFORE-BARRIER'}
        registry.result = {'status': 'ok', 'body': 'synthetic PG batch rollback evidence',
            'url': 'https://fixture.example/tires/product', 'content_type': 'text/html',
            'parser_version': 'fixture@1', 'variants': [first, observation]}
        STEP = 'adoption_transaction_rollback'
        with database.sessions() as db:
            result = asyncio.run(QueryService(db, registry).execute('fixture', LiveQueryRequest.model_validate(
                {'query': unknown['query'], 'fallback_policy': 'never'}), actor))
            assert result['data_state'] == 'source_unavailable' and result['reason'] == 'identity_migration_required'
            assert db.scalar(select(func.count()).select_from(RawCapture)) == 4
        after_barrier = fingerprints(database, Base.metadata)
        for table in ('tire_variants', 'snapshots', 'fact_versions', 'verifications', 'watch_items',
                      'variant_identity_bindings', 'variant_identity_migration_applications'):
            assert old_rows[table] == after_barrier[table]
        assert retained_rows(old_rows, after_barrier)
        record('postgres_entire_adoption_rolls_back_while_preparse_capture_survives')

        STEP = 'same_uuid_concurrency'
        with database.sessions() as db:
            preview = migration_preview(db)
        assert preview['summary'] == {'legacy_total': 3, 'eligible': 1, 'needs_review': 2,
            'already_bound': 0, 'watch_risk_count': 1, 'rule_risk_count': 0}
        payload = migration_payload(preview)

        def race(keys):
            barrier = Barrier(len(keys))

            def writer(key):
                with database.sessions() as db:
                    barrier.wait(timeout=10)
                    try:
                        receipt = apply_migration(db, payload, actor, key)
                        return {'status': 201, 'id': receipt['id'], 'revision': receipt['revision'],
                            'fingerprint': receipt['fingerprint'], 'replay': receipt['idempotent_replay']}
                    except IdentityContractError as error:
                        db.rollback()
                        return {'status': error.status_code, 'code': error.code}

            with ThreadPoolExecutor(max_workers=len(keys)) as executor:
                return list(executor.map(writer, keys))

        key = str(uuid4())
        outcomes = race([key, key])
        assert all(row['status'] == 201 and row['revision'] == 1 for row in outcomes)
        assert outcomes[0]['id'] == outcomes[1]['id'] and outcomes[0]['fingerprint'] == outcomes[1]['fingerprint']
        assert sorted(row['replay'] for row in outcomes) == [False, True]
        REPORT['same_uuid_outcomes'] = [{key: row[key] for key in ('status', 'revision', 'replay')} for row in outcomes]
        record('same_uuid_two_postgres_writers_one_immutable_application')
        STEP = 'different_uuid_stale_preview'
        stale = race([str(uuid4()), str(uuid4())])
        assert stale == [{'status': 409, 'code': 'identity_migration_revision_conflict'}] * 2
        REPORT['different_uuid_old_preview_outcomes'] = stale
        after_migration = fingerprints(database, Base.metadata)
        assert after_migration['variant_identity_migration_applications']['rows'] == 1
        assert after_migration['variant_identity_bindings']['rows'] == 1
        preserved = set(after_barrier) - {'variant_identity_bindings', 'variant_identity_migration_applications'}
        assert all(after_barrier[table] == after_migration[table] for table in preserved)
        record('distinct_uuids_reject_old_preview_409_without_new_rows_or_legacy_mutation')

        STEP = 'post_migration_ingestion'
        with database.sessions() as db:
            snapshot = db.get(Snapshot, safe['snapshot_id'])
            registry.result = {'status': 'ok', 'body': snapshot.body, 'url': snapshot.source_url,
                'content_type': snapshot.content_type, 'parser_version': snapshot.parser_version,
                'etag': snapshot.etag, 'variants': [safe['variant']]}
            fact_count = db.scalar(select(func.count()).select_from(FactVersion))
            result = asyncio.run(QueryService(db, registry).execute('fixture', LiveQueryRequest.model_validate(
                {'query': safe['query'], 'fallback_policy': 'never'}), actor))
            assert result['data_state'] == 'live' and result['variants'][0]['id'] == safe['variant_id']
            assert result['provenance'][0]['snapshot_id'] != safe['snapshot_id']
            assert db.scalar(select(func.count()).select_from(FactVersion)) == fact_count
            registry.result = {'status': 'ok', 'body': 'synthetic PG current CAI evidence for unknown legacy',
                'url': 'https://fixture.example/tires/product', 'content_type': 'text/html',
                'parser_version': 'fixture@1', 'variants': [observation]}
            result = asyncio.run(QueryService(db, registry).execute('fixture', LiveQueryRequest.model_validate(
                {'query': unknown['query'], 'fallback_policy': 'never'}), actor))
            assert result['data_state'] == 'live'
            new_id = result['variants'][0]['id']
            assert new_id != unknown['variant_id']
            assert db.get(WatchItem, unknown['watch_id']).variant_id == unknown['variant_id']
            assert db.get(WatchItem, safe['watch_id']).variant_id == safe['variant_id']
            ids = {key: item['variant_id'] for key, item in records.items()} | {'new_current': new_id}
            expected_contracts = {key: contract_metadata(db, variant_id) for key, variant_id in ids.items()}
            assert {key: value['state'] for key, value in expected_contracts.items()} == {
                'safe': 'current', 'unknown': 'legacy_needs_review', 'mixed': 'legacy_needs_review', 'new_current': 'current'}
            assert expected_contracts['unknown']['related_candidates'][0]['variant_id'] == new_id
            receipt = application_view(db, db.scalar(select(VariantIdentityMigrationApplication)))
            assert len(receipt['binding_ids']) == 1
            assert db.scalar(select(func.count()).select_from(VariantIdentityBinding)) == 2
            assert db.scalar(select(func.count()).select_from(TireVariant)) == 4
            for model in (AIRequest, EmbeddingRequest):
                assert db.scalar(select(func.count()).select_from(model)) == 0
            captures = [(row.id, row.raw_hash) for row in db.scalars(select(RawCapture))]
            for capture_id, raw_hash in captures:
                body, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                assert hashlib.sha256(body).hexdigest() == raw_hash and location == 'object_store'
            versions = list(db.execute(text('SELECT version FROM tire_schema_versions ORDER BY version')).scalars())
        frozen_rows = fingerprints(database, Base.metadata)
        assert retained_rows(old_rows, frozen_rows)
        record('safe_uuid_reused_without_fake_fact_unknown_forks_without_watch_redirect')
        record('all_original_rows_and_uuid_references_retained_no_ai_or_embedding_requests')
        database.close()
        database = None

        STEP = 'dump_restore'
        restore_name = 'restored_identity_' + uuid4().hex[:12]
        restored_url = new_database(restore_name)
        archive = run_root / 'identity.dump'
        child_env = {**os.environ, 'PGHOST': '127.0.0.1', 'PGPORT': '55438', 'PGUSER': role, 'PGPASSWORD': password}
        # Passwords are inherited by these two tools only; never command arguments,
        # stdout, reports, connection URLs or captured exception strings.
        commands = [
            [str(pg_bin / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-acl', '--no-password',
                '--dbname', name, '--file', str(archive)],
            [str(pg_bin / 'pg_restore.exe'), '--exit-on-error', '--no-owner', '--no-acl', '--no-password',
                '--dbname', restore_name, str(archive)],
        ]
        for command in commands:
            result = subprocess.run(command, env=child_env, capture_output=True, timeout=60)
            assert result.returncode == 0, 'private_pg_dump_or_restore_failed'
        destination = run_root / 'restored-objects'
        assert object_root.parent == destination.parent == run_root and not destination.exists()
        source_files = file_hashes(object_root)
        assert source_files
        shutil.copytree(object_root, destination)
        assert file_hashes(destination) == source_files
        os.environ['TI_OBJECT_STORE_ROOT'] = str(destination)
        restored = Database(restored_url)
        restored.initialize()
        restored_rows = fingerprints(restored, Base.metadata)
        assert frozen_rows == restored_rows
        with restored.sessions() as db:
            assert list(db.execute(text('SELECT version FROM tire_schema_versions ORDER BY version')).scalars()) == versions
            assert {key: contract_metadata(db, variant_id) for key, variant_id in ids.items()} == expected_contracts
            restored_receipt = application_view(db, db.scalar(select(VariantIdentityMigrationApplication)))
            assert restored_receipt == receipt
            assert db.get(WatchItem, safe['watch_id']).variant_id == safe['variant_id']
            assert db.get(WatchItem, unknown['watch_id']).variant_id == unknown['variant_id']
            for capture_id, raw_hash in captures:
                body, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                assert hashlib.sha256(body).hexdigest() == raw_hash and location == 'object_store'
        record('pg_dump_restore_all_registered_columns_schema_versions_and_object_copy_hashes')
        restored.close()
        restored = None

        STEP = 'restored_api_semantics'
        with TestClient(create_app(restored_url, FixtureRegistry()), cookies={'tire_local_session': actor}) as client:
            response = client.get('/v1/watchlists')
            assert response.status_code == 200
            watches = {row['variant_id']: row for row in response.json()['items']}
            assert set(watches) == {safe['variant_id'], unknown['variant_id']}
            assert watches[safe['variant_id']]['identity_contract'] == expected_contracts['safe']
            assert watches[unknown['variant_id']]['identity_contract'] == expected_contracts['unknown']
            for key, variant_id in ids.items():
                response = client.get(f'/v1/tire-variants/{variant_id}?mode=history')
                assert response.status_code == 200 and response.json()['identity_contract'] == expected_contracts[key]
            response = client.post('/v1/compare', json={'variant_ids': [unknown['variant_id']]})
            assert response.status_code == 409
            assert response.json()['detail']['code'] == 'identity_contract_review_required'
            response = client.post('/v1/compare', json={'variant_ids': [safe['variant_id']]})
            assert response.status_code == 200
        record('restored_api_current_needs_review_and_original_watch_targets_match')
        REPORT.update(status='passed', tables_checked=len(frozen_rows), columns_checked=sum(
            len(value['columns']) for value in frozen_rows.values()), initial_legacy_entities=3,
            final_entities=4, migration_application_count=1, final_binding_count=2,
            original_rows_retained=True, migration_only_preserved_table_count=len(preserved),
            restored_states={key: value['state'] for key, value in expected_contracts.items()},
            table_fingerprints=public_fingerprints(frozen_rows), restore_table_fingerprints=public_fingerprints(restored_rows),
            object_file_count=len(source_files), object_hashes=source_files, copied_object_hashes=file_hashes(destination),
            capture_count=len(captures), archive_bytes=archive.stat().st_size,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), schema_versions=versions,
            synthetic_source_observations=registry.calls, real_source_calls=0, real_parser_children=0,
            real_ai_calls=0, real_embedding_calls=0, normal_database_used=False,
            fingerprint_scope='All Base.metadata registered columns and values, schema versions and copied object files; '
                'not database roles, ACL or cross-host recovery')
    finally:
        if database is not None:
            database.close()
        if restored is not None:
            restored.close()
        admin.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-private-postgres', action='store_true', required=True)
    parser.parse_args()
    code = 0
    try:
        run()
    except Exception as error:
        import traceback
        code = 1
        REPORT.update(status='failed', failure_step=STEP, error_type=type(error).__name__)
        REPORT['frames'] = [{'file': Path(frame.filename).name, 'line': frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__) if Path(frame.filename).resolve().is_relative_to(ROOT)]
    # Do not write to an unvalidated path even when startup guards fail.
    report = Path(os.environ['TIRE_PG_TEST_REPORT']).resolve()
    runtime_root = (ROOT / '.artifacts/runtime').resolve()
    assert report.name == 'report.json' and report.parent.parent == runtime_root
    assert report.parent.name.startswith('round38-identity-PG-')
    report.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: REPORT[key] for key in ('status', 'scope', 'checks')}), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
