"""Opt-in PG46: immutable before checkpoint, additive 010, owned offline packs.

Only the private pg46 wrapper may launch this script on loopback port 55446.
The original before/after and every normal database/credential remain untouched.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

from identity_contract_postgres_acceptance import file_hashes, public_fingerprints
import monitor_tasks_postgres_acceptance as previous
from recall_knowledge_postgres_acceptance import schema_snapshot, normalized_schema, evaluate_enum_checks

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / '.artifacts/offline-pack'
BEFORE = ROOT / '.artifacts/runtime/round46-before.sqlite'
BEFORE_SHA = '716caf68d7dee70bde3d4a5465134f3f41e4620d2db1a90f99904cef8d228b94'
PORT = 55446
NEW_TABLES = {'offline_pack_plans', 'offline_packs'}
MIGRATION = '010_offline_packs'
SQLITE_ONLY = {'knowledge_fts', 'knowledge_fts_config', 'knowledge_fts_content',
               'knowledge_fts_data', 'knowledge_fts_docsize', 'knowledge_fts_idx'}
REPORT = {'status': 'running', 'scope': 'private_pg46_checkpoint_migration_offline_packs', 'checks': []}
STEP = 'isolation'
SOURCE_PATHS = ('scripts/offline_pack_postgres_acceptance.py', 'scripts/recall_knowledge_postgres_acceptance.py',
    'scripts/identity_contract_postgres_acceptance.py', 'scripts/monitor_tasks_postgres_acceptance.py',
    '.artifacts/runtime/round46-verify-offline-postgres.ps1', 'apps/api/tire_api/db.py',
    'apps/api/tire_api/main.py', 'apps/api/tire_api/migrations.py', 'apps/api/tire_api/offline_models.py',
    'apps/api/tire_api/offline_packs.py', 'apps/api/tire_api/offline_evidence.py',
    'apps/api/tests/test_offline_packs.py')
save_atomic, safe_failure, wait_gate = previous.save_atomic, previous.safe_failure, previous.wait_gate


def record(name):
    REPORT['checks'].append(name)
    print(json.dumps({'check': name, 'status': 'passed'}), flush=True)


def guards():
    root = Path(os.environ['TIRE_PG_RUN_ROOT']).resolve()
    assert root.parent == ARTIFACTS.resolve() and re.fullmatch(r'pg46-[0-9a-f]{32}', root.name)
    assert (root / '.pg46-owned').read_text(encoding='utf-8') == root.name
    assert Path(os.environ['TIRE_PG_TEST_DATA']).resolve() == root / 'data'
    assert Path(os.environ['TIRE_PG_TEST_REPORT']).resolve() == root / 'report.json'
    assert int(os.environ['TIRE_PG_TEST_PORT']) == PORT
    assert all(os.environ[name] == '0' for name in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'))
    assert os.environ['TI_OBJECT_STORE_BACKEND'] == 'filesystem'
    assert Path(os.environ['TI_OBJECT_STORE_ROOT']).resolve() in (root / 'objects', root / 'restored-objects')
    assert Path(os.environ['TI_PARSER_BUNDLE_ROOT']).resolve() == root / 'bundles'
    guard = 'sqlite:///' + (root / 'import-guard.sqlite').as_posix()
    assert os.environ['TIRE_DATABASE_URL'] == os.environ['DATABASE_URL'] == guard
    assert Path(os.environ['TIRE_PG_BIN']).resolve() == Path('E:/PostgreSQL/18/bin').resolve()
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    return root


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def normal(value):
    if isinstance(value, datetime):
        return {'utc_datetime': (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {'bytes': bytes(value).hex()}
    if isinstance(value, dict):
        return {key: normal(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normal(item) for item in value]
    return value


def row_digest(value):
    return hashlib.sha256(encoded(normal(value)).encode()).hexdigest()


def fingerprints(database, tables):
    from sqlalchemy import JSON, select
    result = {}
    with database.engine.connect() as connection:
        for table in tables:
            json_columns = [column for column in table.columns if isinstance(column.type, JSON)]
            statement = select(table, *(column.is_(None).label('_sqlnull_' + column.name) for column in json_columns))
            rows = []
            for raw in connection.execute(statement).mappings():
                value = {column.name: raw[column.name] for column in table.columns}
                for column in json_columns:
                    value[column.name] = {'sql_null': True} if raw['_sqlnull_' + column.name] else {'json': value[column.name]}
                rows.append(row_digest(value))
            rows.sort()
            result[table.name] = {'columns': [column.name for column in table.columns], 'rows': len(rows),
                                  'sha256': row_digest(rows), 'row_hashes': rows}
    return result


def sqlite_snapshot(path):
    def quoted(name):
        return '"' + name.replace('"', '""') + '"'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        rows = {}
        for name in tables:
            columns = [row[1] for row in connection.execute('PRAGMA table_info(' + quoted(name) + ')')]
            hashes = sorted(row_digest(list(row)) for row in connection.execute('SELECT * FROM ' + quoted(name)))
            rows[name] = {'columns': columns, 'rows': len(hashes), 'sha256': row_digest(hashes), 'row_hashes': hashes}
        schema = [list(row) for row in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        return rows, schema


def sqlite_checkpoint(root):
    from tire_api.db import Database
    assert hashlib.sha256(BEFORE.read_bytes()).hexdigest() == BEFORE_SHA
    old, schema = sqlite_snapshot(BEFORE)
    assert len(old) == 105 and SQLITE_ONLY <= old.keys() and not NEW_TABLES & old.keys()
    destination = root / 'before-private.sqlite'
    assert not destination.exists()
    shutil.copyfile(BEFORE, destination)
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == BEFORE_SHA
    database = Database('sqlite:///' + destination.as_posix())
    try:
        database.initialize()
        with database.engine.connect() as connection:
            connection.exec_driver_sql('PRAGMA wal_checkpoint(TRUNCATE)')
        migrated, migrated_schema = sqlite_snapshot(destination)
        assert migrated.keys() - old.keys() == NEW_TABLES
        assert all(migrated[name] == value for name, value in old.items() if name != 'tire_schema_versions')
        assert not Counter(old['tire_schema_versions']['row_hashes']) - Counter(migrated['tire_schema_versions']['row_hashes'])
        assert migrated['tire_schema_versions']['rows'] == old['tire_schema_versions']['rows'] + 1
        assert [row for row in migrated_schema if row[2] not in NEW_TABLES] == schema
        database.initialize()
        with database.engine.connect() as connection:
            connection.exec_driver_sql('PRAGMA wal_checkpoint(TRUNCATE)')
        assert sqlite_snapshot(destination) == (migrated, migrated_schema)
    finally:
        database.close()
    save_atomic(root / 'sqlite-before-fingerprints.json', public_fingerprints(old))
    save_atomic(root / 'sqlite-before-schema.json', schema)
    save_atomic(root / 'sqlite-after-010-fingerprints.json', public_fingerprints(migrated))
    save_atomic(root / 'sqlite-after-010-schema.json', migrated_schema)
    save_atomic(root / 'sqlite-fts-exact.json', {name: public_fingerprints(old)[name] for name in sorted(SQLITE_ONLY)})
    REPORT['sqlite_checkpoint'] = {'original_sha256': BEFORE_SHA, 'old_tables': 105, 'after_tables': 107,
        'added_tables': sorted(NEW_TABLES), 'old_values_retained': True, 'old_schema_exact': True,
        'sqlite_only_fts_tables': sorted(SQLITE_ONLY), 'sqlite_only_fts_values_exact': True,
        'repeat_initialize_unchanged': True, 'private_copy': destination.name}
    record('unique_before_read_only_private_sqlite_105_old_tables_exact_plus_010_two_tables')


def migrate_checkpoint_to_pg(database, tables, root):
    from sqlalchemy import JSON, create_engine, inspect, null, select
    # Read-only URI: never instantiate Database against the immutable original.
    source = create_engine('sqlite:///file:' + BEFORE.as_posix() + '?mode=ro&immutable=1&uri=true')
    try:
        old_tables = [table for table in tables if table.name not in NEW_TABLES]
        assert len(old_tables) == 99
        with source.connect() as connection, database.engine.begin() as target:
            for table in old_tables:
                source_columns = {column['name'] for column in inspect(connection).get_columns(table.name)}
                target_columns = {column.name for column in table.columns}
                if source_columns != target_columns:
                    REPORT['checkpoint_column_mismatch'] = {'table': table.name, 'sqlite_only': sorted(source_columns-target_columns), 'pg_only': sorted(target_columns-source_columns)}
                    raise AssertionError('checkpoint_registered_columns_differ')
                json_columns = [column for column in table.columns if isinstance(column.type, JSON)]
                statement = select(table, *(column.is_(None).label('_sqlnull_' + column.name) for column in json_columns))
                groups = defaultdict(list)
                for raw in connection.execute(statement).mappings():
                    sql_nulls = tuple(column.name for column in json_columns if raw['_sqlnull_' + column.name])
                    value = {column.name: raw[column.name] for column in table.columns if column.name not in sql_nulls}
                    value = {key: item.replace(tzinfo=timezone.utc)
                        if isinstance(item, datetime) and item.tzinfo is None and getattr(table.c[key].type, 'timezone', False)
                        else item for key, item in value.items()}
                    groups[sql_nulls].append(value)
                for sql_nulls, values in groups.items():
                    insert = table.insert().values(**{name: null() for name in sql_nulls})
                    target.execute(insert, values)
        # Reuse exactly the same typed columns and SQL-NULL markers on both sides.
        source_adapter = type('ReadonlyCheckpoint', (), {'engine': source})()
        expected = fingerprints(source_adapter, old_tables)
        actual = fingerprints(database, old_tables)
        save_atomic(root / 'cross-dialect-before-values.json', public_fingerprints(expected))
        save_atomic(root / 'cross-dialect-pg-imported-values.json', public_fingerprints(actual))
        if actual != expected:
            REPORT['cross_dialect_differing_tables'] = [name for name in expected if expected[name] != actual[name]]
            raise AssertionError('cross_dialect_old_values_changed')
        REPORT['cross_dialect'] = {'tables': 99, 'columns': sum(len(item['columns']) for item in expected.values()),
            'rows': sum(item['rows'] for item in expected.values()), 'all_rows_semantically_equal': True,
            'normalization': 'SQLite naive application timestamps interpreted as UTC; typed JSON semantics; SQL NULL distinct from JSON null; bytes exact',
            'sqlite_fts_not_fabricated_in_postgres': True}
        record('all_99_old_orm_and_version_tables_semantically_migrated_to_pg_with_nulls_distinct')
        return actual
    finally:
        source.dispose()


class NoFetchRegistry:
    def sources(self):
        from test_core import FixtureRegistry
        return FixtureRegistry().sources()

    async def fetch(self, *args, **kwargs):
        raise AssertionError('source_calls_forbidden_even_synthetic')


def writer(name):
    root = guards()
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,79}', name)
    request = json.loads((root / f'{name}.request.json').read_text())
    from fastapi.testclient import TestClient
    from sqlalchemy.engine import make_url
    from tire_api.main import SESSION_COOKIE, create_app
    parsed = make_url(os.environ['TIRE_PG_APP_URL'])
    assert parsed.get_backend_name() == 'postgresql' and parsed.host == '127.0.0.1' and parsed.port == PORT
    assert parsed.database.startswith('offline_pack_')
    app = create_app(os.environ['TIRE_PG_APP_URL'], NoFetchRegistry())
    outcome = {'pid': os.getpid(), 'parent_pid': os.getppid(), 'action': 'confirm_offline_package', 'status': 'running'}
    code = 0
    try:
        with TestClient(app, cookies={SESSION_COOKIE: request['synthetic_actor']}) as client:
            with app.state.database.engine.connect() as connection:
                outcome['backend_pid'] = connection.exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
            save_atomic(root / f'{name}.ready.json', {'pid': os.getpid(), 'backend_pid': outcome['backend_pid']})
            wait_gate(root / (request['group'] + '.go'))
            response = client.post('/v1/offline-packs', json=request['body'], headers={'Idempotency-Key': request['key']})
            assert response.status_code in (201, 409)
            outcome.update(status='finished', response_status=response.status_code)
            if response.status_code == 201:
                value = response.json()
                download = client.get(value['download_path'])
                assert download.status_code == 200
                assert hashlib.sha256(download.content).hexdigest() == value['sha256']
                outcome.update(package_id=value['id'], sha256=value['sha256'], byte_count=len(download.content))
            else:
                outcome['error_code'] = response.json()['detail']['code']
    except Exception as error:
        code = 1
        outcome.update(status='failed', **safe_failure(error))
    finally:
        app.state.database.close()
        save_atomic(root / f'{name}.result.json', outcome)
    return code


class Writers(previous.Writers):
    def launch(self, group, request, *, different_keys=False):
        names = [f'{group}-{index}' for index in range(2)]
        for name in names:
            body = {'group': group, **request}
            if different_keys:
                body['key'] = str(uuid4())
            save_atomic(self.root / f'{name}.request.json', body)
            env = {**os.environ, 'TIRE_PG_APP_URL': self.url}
            env.pop('TIRE_PG_TEST_PASSWORD', None)
            self.logs[name] = (self.root / f'{name}.log').open('wb')
            self.children[name] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--writer', name],
                env=env, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=self.logs[name], stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ready = self.collect(names, 'ready')
        assert len({row['pid'] for row in ready}) == len({row['backend_pid'] for row in ready}) == 2
        self.evidence.extend({'scenario': group, 'launcher_pid': self.children[name].pid, **row}
            for name, row in zip(names, ready, strict=True))
        (self.root / f'{group}.go').write_text('begin')
        for name in names:
            assert self.children[name].wait(timeout=45) == 0
        return self.collect(names, 'result')


def seed_tire(database, actor):
    from tire_api.db import QueryRun, Snapshot, FactVersion, Verification, uid
    from tire_api.domain import VariantInput, digest
    from tire_api.identity_contract import schema_version, resolve_variant
    from tire_api.service import QueryService
    from test_core import VARIANT
    value = deepcopy(VARIANT)
    value['manufacturer_product_code'] = 'PG46-' + uuid4().hex
    variant = VariantInput.model_validate(value)
    query = {'size': value['size'], 'model': value['model']}
    query_key, snapshot_id = digest(query), uid()
    raw = 'PG46 SYNTHETIC RAW NEVER INCLUDED'
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        run = QueryRun(session_id=actor, source_id='fixture', query=query, query_key=query_key, fallback_policy='never', state='live')
        db.add(run)
        db.flush()
        stored, identity_key, identity_status = resolve_variant(db, variant, 'fixture', query_key, 0, snapshot_id)
        variant_id = stored.id
        parsed = {**variant.model_dump(), 'id': variant_id, 'identity_key': identity_key,
            'identity_status': identity_status, 'identity_contract_version': schema_version(), 'fact_version': 1, 'snapshot_id': snapshot_id}
        db.add(Snapshot(id=snapshot_id, source_id='fixture', query_key=query_key, source_url='https://fixture.example/pg46',
            raw_hash=hashlib.sha256(raw.encode()).hexdigest(), body=raw, content_type='text/plain', parser_version='synthetic-pg46@1',
            parser_identity=None, identity_contract_version=schema_version(), parsed_variants=[parsed]))
        db.flush()
        db.add(FactVersion(variant_id=variant_id, source_id='fixture', snapshot_id=snapshot_id,
            facts=variant.facts, facts_hash=digest(variant.facts), version=1))
        receipt = Verification(snapshot_id=snapshot_id, query_id=run.id, source_id='fixture', query_key=query_key, status='ok', parser_identity=None)
        db.add(receipt)
        db.commit()
        return variant_id, {'kind': 'tire', 'snapshot_id': snapshot_id, 'variant_id': variant_id, 'verification_id': receipt.id}


def constraints(database):
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from tire_api.offline_models import OfflinePack, OfflinePackPlan
    evidence = []
    with database.engine.connect() as connection:
        plan = dict(connection.execute(select(OfflinePackPlan)).mappings().first())
        pack = dict(connection.execute(select(OfflinePack)).mappings().first())
        connection.rollback()
        cases = [
            ('unique_plan_package_id', OfflinePackPlan.__table__, {**plan, 'id': str(uuid4())}, '23505'),
            ('plan_content_foreign_key', OfflinePackPlan.__table__, {**plan, 'id': str(uuid4()), 'package_id': str(uuid4()), 'content_hash': 'f' * 64}, '23503'),
            ('pack_plan_foreign_key', OfflinePack.__table__, {**pack, 'id': str(uuid4()), 'plan_id': str(uuid4()), 'idempotency_key': str(uuid4())}, '23503'),
            ('pack_actor_key_unique', OfflinePack.__table__, {**pack, 'id': str(uuid4()), 'plan_id': str(uuid4())}, '23505'),
            ('pack_plan_unique', OfflinePack.__table__, {**pack, 'id': str(uuid4()), 'idempotency_key': str(uuid4())}, '23505'),
        ]
        for name, table, value, expected in cases:
            transaction = connection.begin()
            try:
                try:
                    connection.execute(table.insert().values(**value))
                except IntegrityError as error:
                    assert error.orig.sqlstate == expected
                    evidence.append({'case': name, 'sqlstate': expected, 'constraint': error.orig.diag.constraint_name, 'rolled_back': True})
                else:
                    raise AssertionError('new_offline_constraint_missing')
            finally:
                transaction.rollback()
        transaction = connection.begin()
        try:
            temporary_plan = {**plan, 'id': str(uuid4()), 'package_id': str(uuid4())}
            connection.execute(OfflinePackPlan.__table__.insert().values(**temporary_plan))
            try:
                connection.execute(OfflinePack.__table__.insert().values(**{**pack, 'id': temporary_plan['package_id'],
                    'plan_id': temporary_plan['id'], 'idempotency_key': str(uuid4()), 'content_hash': 'f' * 64}))
            except IntegrityError as error:
                assert error.orig.sqlstate == '23503'
                evidence.append({'case': 'pack_content_foreign_key', 'sqlstate': '23503', 'constraint': error.orig.diag.constraint_name, 'rolled_back': True})
            else:
                raise AssertionError('pack_content_constraint_missing')
        finally:
            transaction.rollback()
    with database.sessions() as db:
        plan_row = db.get(OfflinePackPlan, plan['id'])
        plan_row.fingerprint = '0' * 64
        try:
            db.commit()
        except ValueError:
            db.rollback()
            evidence.append({'case': 'orm_append_only_plan_update', 'rejected': True, 'rolled_back': True})
        else:
            raise AssertionError('plan_mutation_allowed')
        db.delete(db.get(OfflinePack, pack['id']))
        try:
            db.commit()
        except ValueError:
            db.rollback()
            evidence.append({'case': 'orm_append_only_pack_delete', 'rejected': True, 'rolled_back': True})
        else:
            raise AssertionError('pack_deletion_allowed')
    return evidence


def run():
    global STEP
    root = guards()
    source_manifest = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_PATHS}
    assert source_manifest['apps/api/tire_api/offline_evidence.py'] == 'cb3e84dd12ab99d69ca45b654324e193a35599965cf0f5053925950c99f9e8ad'
    save_atomic(root / 'acceptance-source-manifest.json', source_manifest)
    import psycopg
    from psycopg import sql
    from fastapi.testclient import TestClient
    from sqlalchemy import MetaData, Table, inspect, select, text
    from sqlalchemy.engine import URL
    from tire_api.db import Base, Database, EvidenceObject
    from tire_api.main import SESSION_COOKIE, create_app
    from tire_api.offline_models import OfflinePack, OfflinePackPlan
    from test_offline_packs import EMPTY_SCOPE, plan, confirm, download, seed_domains
    from test_garage import PROFILE
    sqlite_checkpoint(root)
    admin = psycopg.connect(host='127.0.0.1', port=PORT, user='tire_offline_pack_admin', password=os.environ['TIRE_PG_TEST_PASSWORD'],
        dbname='postgres', autocommit=True, connect_timeout=5)
    database = restored = writers = None
    previous.REPORT = REPORT
    try:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == root / 'data'
        assert admin.execute('SHOW listen_addresses').fetchone()[0] == '127.0.0.1'
        REPORT.update(postgres_version=admin.execute('SHOW server_version').fetchone()[0], parent_pid=os.getpid(),
            postmaster_pid=int((root / 'data/postmaster.pid').read_text().splitlines()[0]))
        assert REPORT['postgres_version'].split('.')[0] == '18'
        role, password = 'offline_pack_app_' + uuid4().hex[:10], secrets.token_hex(32)
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION').format(sql.Identifier(role), sql.Literal(password)))

        def new_database(name):
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(role)))
            return URL.create('postgresql+psycopg', username=role, password=password, host='127.0.0.1', port=PORT, database=name).render_as_string(hide_password=False)

        name = 'offline_pack_' + uuid4().hex[:10]
        url = new_database(name)
        database = Database(url)
        database.initialize()
        versions_table = Table('tire_schema_versions', MetaData(), autoload_with=database.engine)
        tables = list(Base.metadata.sorted_tables) + [versions_table]
        assert len(tables) == 101
        with database.engine.begin() as connection:
            assert connection.exec_driver_sql('SELECT current_user').scalar_one() == role
            assert not connection.exec_driver_sql('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication FROM pg_roles WHERE rolname=current_user').scalar_one()
            # Recreate the old checkpoint-era schema in this empty private PG only.
            connection.exec_driver_sql('DROP TABLE offline_packs')
            connection.exec_driver_sql('DROP TABLE offline_pack_plans')
            connection.execute(versions_table.delete())
        STEP = 'import_99_before_tables'
        old_values = migrate_checkpoint_to_pg(database, tables, root)
        old_schema = schema_snapshot(database)
        assert len(old_schema) == 99
        STEP = 'additive_010_migration'
        database.initialize()
        migrated = fingerprints(database, tables)
        migrated_schema = schema_snapshot(database)
        assert migrated_schema.keys() - old_schema.keys() == NEW_TABLES
        assert all(migrated_schema[name] == value for name, value in old_schema.items())
        assert all(migrated[name] == value for name, value in old_values.items() if name != 'tire_schema_versions')
        assert not Counter(old_values['tire_schema_versions']['row_hashes']) - Counter(migrated['tire_schema_versions']['row_hashes'])
        with database.engine.connect() as connection:
            versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
        assert len(versions) == 10 and MIGRATION in versions
        database.initialize()
        assert fingerprints(database, tables) == migrated and schema_snapshot(database) == migrated_schema
        save_atomic(root / 'pg-old-schema.json', old_schema)
        save_atomic(root / 'pg-after-010-schema.json', migrated_schema)
        save_atomic(root / 'pg-after-010-values.json', public_fingerprints(migrated))
        record('pg_010_adds_exactly_two_tables_preserves_all_99_old_values_and_schema_twice')

        STEP = 'synthetic_owned_offline_workflow'
        app = create_app(url, NoFetchRegistry())
        with TestClient(app) as client:
            client.get('/health').raise_for_status()
            actor = client.cookies[SESSION_COOKIE]
            variant_id, tire_ref = seed_tire(database, actor)
            refs, origin_id = seed_domains(client, database)
            profile = deepcopy(PROFILE)
            profile['rear']['current_variant_id'] = variant_id
            garage = client.post('/v1/garage', json=profile)
            garage.raise_for_status()
            watch = client.post('/v1/watchlists', json={'variant_id': variant_id})
            watch.raise_for_status()
            scope = deepcopy(EMPTY_SCOPE)
            scope.update(garage={'include': True}, watchlist={'include': True}, references=[tire_ref, *refs])
            prepared = plan(client, scope)
            assert prepared['can_confirm'] and prepared['counts']['distinct_evidence'] == 5
            assert prepared['counts']['searchable_documents'] == 9
            key = str(uuid4())
            descriptor = confirm(client, prepared, key).json()
            raw, envelope = download(client, descriptor)
            assert envelope['contexts'] == prepared['contexts'] and envelope['documents'] == prepared['documents']
            assert not any(canary in raw for canary in (b'actor_session_id', b'PG46 SYNTHETIC RAW', b'raw canary', b'FULL PDF'))
            assert confirm(client, prepared, key).json() == descriptor
            assert confirm(client, prepared, key, expected_fingerprint='0' * 64).status_code == 409
            assert confirm(client, prepared, allow_device_storage=False).status_code == 422
            other = TestClient(app)
            assert other.get(descriptor['download_path']).status_code == 404
            assert other.get('/v1/offline-pack-plans/' + prepared['id'] + '?mode=history').status_code == 404
            assert confirm(other, prepared).status_code == 404
            other.close()
            save_atomic(root / 'owned-package-summary.json', {'descriptor': descriptor, 'members': len(envelope['members']),
                'documents': len(envelope['documents']), 'raw_excluded': True, 'foreign_owner_denied': True})
            record('zero_source_parser_model_four_domain_plan_confirm_owned_download_idempotency_and_foreign_owner_denial')
            duplicates = deepcopy(EMPTY_SCOPE)
            duplicates.update(garage={'include': True, 'vehicle_ids': [garage.json()['id']] * 51},
                watchlist={'include': True, 'item_ids': [watch.json()['id']] * 101}, references=[tire_ref] * 201)
            duplicate_plan = plan(client, duplicates)
            assert duplicate_plan['can_confirm'] and duplicate_plan['counts']['distinct_evidence'] == 1
            duplicate_descriptor = confirm(client, duplicate_plan).json()
            duplicate_bytes, duplicate_envelope = download(client, duplicate_descriptor)
            assert len(duplicate_envelope['scope']['references']) == 201
            assert len(duplicate_envelope['scope']['garage']['vehicle_ids']) == 51
            assert len(duplicate_envelope['scope']['watchlist']['item_ids']) == 101
            assert len(duplicate_envelope['members']) == 1 and len(duplicate_envelope['contexts']) == 2
            (root / 'duplicate-scope-envelope.json').write_bytes(duplicate_bytes)
            save_atomic(root / 'duplicate-scope-descriptor.json', duplicate_descriptor)
            record('requested_duplicate_scope_201_references_51_garage_101_watch_preserved_resolved_one_evidence')
            # A second formal same-body query receipt is a normal ingestion
            # outcome. Seed it directly to keep all source/parser calls zero.
            from tire_api.db import QueryRun, Verification, uid
            with database.sessions() as db:
                receipt = db.get(Verification, tire_ref['verification_id'])
                original_query = db.get(QueryRun, receipt.query_id)
                next_query = QueryRun(id=uid(), session_id=actor, source_id=original_query.source_id,
                    query_key=original_query.query_key, query=deepcopy(original_query.query), fallback_policy='never', state='live')
                db.add(next_query)
                db.flush()
                second_receipt = Verification(id=uid(), snapshot_id=receipt.snapshot_id, query_id=next_query.id,
                    source_id=receipt.source_id, query_key=receipt.query_key, status='not_modified', parser_identity=receipt.parser_identity)
                db.add(second_receipt)
                second_receipt_id = second_receipt.id
                db.commit()
            default_plan = plan(client)
            assert default_plan['can_confirm']
            same_snapshot_members = [member for member in default_plan['resolved'] if member['reference']['kind'] == 'tire'
                and member['reference']['snapshot_id'] == tire_ref['snapshot_id']]
            assert {member['reference']['verification_id'] for member in same_snapshot_members} == {tire_ref['verification_id'], second_receipt_id}
            assert download(client, descriptor)[0] == raw
            with database.sessions() as db:
                assert db.get(Verification, tire_ref['verification_id']) and db.get(Verification, second_receipt_id)
            record('same_snapshot_two_formal_query_receipts_default_plan_201_preserves_both_and_old_package')
            writers = Writers(root, url)
            common = plan(client, scope)
            request = {'synthetic_actor': actor, 'key': str(uuid4()), 'body': {'plan_id': common['id'], 'expected_fingerprint': common['fingerprint'], 'allow_device_storage': True}}
            same = writers.launch('same-key', request)
            assert [row['response_status'] for row in same] == [201, 201]
            assert len({row['package_id'] for row in same}) == len({row['sha256'] for row in same}) == 1
            common = plan(client, scope)
            request['body'] = {'plan_id': common['id'], 'expected_fingerprint': common['fingerprint'], 'allow_device_storage': True}
            different = writers.launch('different-key', request, different_keys=True)
            assert sorted(row['response_status'] for row in different) == [201, 409]
            assert next(row for row in different if row['response_status'] == 409)['error_code'] == 'offline_plan_already_confirmed'
            REPORT['writer_outcomes'] = {'same_key': same, 'different_key': different}
            record('four_independent_writer_processes_same_key_replay_and_different_key_single_confirmation_exit_zero')
        constraints_before = constraints(database)
        save_atomic(root / 'new-table-constraints-original.json', constraints_before)
        record('postgres_unique_foreign_keys_and_orm_append_only_negative_cases_rollback')
        frozen = fingerprints(database, tables)
        frozen_objects = file_hashes(root / 'objects')
        assert all(not Counter(value['row_hashes']) - Counter(frozen[name]['row_hashes']) for name, value in old_values.items())
        final_schema = schema_snapshot(database)
        enum_before = evaluate_enum_checks(database, final_schema)
        save_atomic(root / 'enum-checks-original.json', enum_before)
        save_atomic(root / 'fingerprints-frozen.json', public_fingerprints(frozen))
        save_atomic(root / 'schema-frozen.json', final_schema)
        database.initialize()
        assert fingerprints(database, tables) == frozen and schema_snapshot(database) == final_schema

        STEP = 'four_stage_dump_restore'
        restored_name = 'restored_offline_pack_' + uuid4().hex[:10]
        restored_url = new_database(restored_name)
        archive = root / 'offline-pack.dump'
        env = {**os.environ, 'PGHOST': '127.0.0.1', 'PGPORT': str(PORT), 'PGUSER': role, 'PGPASSWORD': password}
        env.pop('TIRE_PG_TEST_PASSWORD', None)
        pg_bin = Path(os.environ['TIRE_PG_BIN'])
        pre_dump = fingerprints(database, tables)
        assert pre_dump == frozen
        pre_dump_objects = file_hashes(root / 'objects')
        assert pre_dump_objects == frozen_objects
        assert schema_snapshot(database) == final_schema
        save_atomic(root / 'fingerprints-pre-dump.json', public_fingerprints(pre_dump))
        save_atomic(root / 'schema-pre-dump.json', schema_snapshot(database))
        for command in ([str(pg_bin / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-acl', '--no-password', '--dbname', name, '--file', str(archive)],
                        [str(pg_bin / 'pg_restore.exe'), '--exit-on-error', '--no-owner', '--no-acl', '--no-password', '--dbname', restored_name, str(archive)]):
            assert subprocess.run(command, env=env, capture_output=True, timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).returncode == 0, 'private_dump_restore_failed'
        objects = file_hashes(root / 'objects')
        assert objects and objects == frozen_objects
        destination = root / 'restored-objects'
        assert not destination.exists()
        shutil.copytree(root / 'objects', destination)
        assert file_hashes(destination) == objects
        os.environ['TI_OBJECT_STORE_ROOT'] = str(destination)
        restored = Database(restored_url)
        before_initialize = fingerprints(restored, tables)
        restored_schema = schema_snapshot(restored)
        assert before_initialize == frozen
        assert normalized_schema(restored_schema) == normalized_schema(final_schema)
        enum_restored = evaluate_enum_checks(restored, restored_schema)
        assert enum_restored == enum_before
        save_atomic(root / 'enum-checks-restored.json', enum_restored)
        restored_before_objects = file_hashes(destination)
        assert restored_before_objects == frozen_objects
        save_atomic(root / 'fingerprints-restored-pre-initialize.json', public_fingerprints(before_initialize))
        save_atomic(root / 'schema-restored-pre-initialize.json', restored_schema)
        restored.initialize()
        after_initialize = fingerprints(restored, tables)
        assert after_initialize == frozen and schema_snapshot(restored) == restored_schema
        restored_after_objects = file_hashes(destination)
        assert restored_after_objects == frozen_objects
        save_atomic(root / 'objects-four-stages.json', {'frozen': frozen_objects, 'pre_dump': pre_dump_objects,
            'restored_pre_initialize': restored_before_objects, 'restored_post_initialize': restored_after_objects})
        save_atomic(root / 'fingerprints-restored-post-initialize.json', public_fingerprints(after_initialize))
        save_atomic(root / 'schema-restored-post-initialize.json', schema_snapshot(restored))
        restored_constraints = constraints(restored)
        assert restored_constraints == constraints_before
        save_atomic(root / 'new-table-constraints-restored.json', restored_constraints)
        assert fingerprints(restored, tables) == frozen
        with restored.sessions() as db:
            for row in db.scalars(select(EvidenceObject)):
                data = restored.object_store.get(row.raw_hash, row.byte_count)
                assert len(data) == row.byte_count and hashlib.sha256(data).hexdigest() == row.raw_hash
            expected_packages = [deepcopy(row.descriptor) for row in db.scalars(select(OfflinePack))]
        restored_app = create_app(restored_url, NoFetchRegistry())
        with TestClient(restored_app, cookies={SESSION_COOKIE: actor}) as client:
            for descriptor in expected_packages:
                download(client, descriptor)
        assert fingerprints(restored, tables) == frozen
        assert hashlib.sha256(BEFORE.read_bytes()).hexdigest() == BEFORE_SHA
        assert source_manifest == {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_PATHS}
        assert not (root / 'import-guard.sqlite').exists()
        record('pg_101_tables_four_stage_exact_values_schema_enum_equivalence_objects_and_owned_download_restore')
        REPORT.update(status='passed', migration=MIGRATION, added_tables=sorted(NEW_TABLES),
            tables_checked=len(frozen), columns_checked=sum(len(value['columns']) for value in frozen.values()),
            old_99_tables_rows_retained=True, schema_tables_checked=len(final_schema), schema_versions=sorted(versions),
            four_stage_exact_values=True, four_stage_schema_equivalent=True, four_stage_objects_exact=True,
            schema_normalization='Only ten explicitly enumerated PG18 enum ARRAY cast deparse equivalents; all other fields exact',
            table_fingerprints=public_fingerprints(frozen), restored_table_fingerprints=public_fingerprints(after_initialize),
            object_hashes=objects, restored_object_hashes=file_hashes(destination), archive_bytes=archive.stat().st_size,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), original_before_sha256=BEFORE_SHA,
            real_source_calls=0, synthetic_source_calls=0, real_model_calls=0, real_parser_children=0, normal_database_used=False,
            no_cross_dialect_schema_exact_claim=True, before_and_after_never_recreated=True)
    finally:
        if writers is not None:
            writers.close()
        if database is not None:
            database.close()
        if restored is not None:
            restored.close()
        admin.close()


def guarded(action):
    guards()
    from tire_api.adapters.transport import SafeHttpClient
    from tire_api import parser_runtime
    from tire_api.ai_gateway import OpenAIResponsesAdapter
    with patch.object(SafeHttpClient, '_request', side_effect=AssertionError('real_source_forbidden')) as source, \
         patch.object(parser_runtime, '_run_sync', side_effect=AssertionError('real_parser_forbidden')) as parser, \
         patch.object(OpenAIResponsesAdapter, 'stream', side_effect=AssertionError('real_model_forbidden')) as stream, \
         patch.object(OpenAIResponsesAdapter, 'generate', side_effect=AssertionError('real_model_forbidden')) as generate:
        result = action()
        assert source.call_count == parser.call_count == stream.call_count == generate.call_count == 0
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run-private-postgres', action='store_true')
    mode.add_argument('--writer')
    args = parser.parse_args()
    if args.writer:
        try:
            return guarded(lambda: writer(args.writer))
        except Exception as error:
            print(json.dumps({'status': 'failed', **safe_failure(error)}), flush=True)
            return 1
    code = 0
    try:
        guarded(run)
    except Exception as error:
        code = 1
        REPORT.update(status='failed', failure_step=STEP, **safe_failure(error))
    path = Path(os.environ['TIRE_PG_TEST_REPORT']).resolve()
    assert path.parent.parent == ARTIFACTS.resolve() and re.fullmatch(r'pg46-[0-9a-f]{32}', path.parent.name)
    save_atomic(path, REPORT)
    print(json.dumps({key: REPORT[key] for key in ('status', 'scope', 'checks')}), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
