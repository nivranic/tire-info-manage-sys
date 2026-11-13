"""PG 024 maintenance acceptance from a pinned, genuine 015 source revision."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import zipfile

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests'), str(ROOT / 'scripts')]
from tire_api.db import Database
from tire_api import vehicle_binary_postgres_cli as cli
from tire_api.postgres_schema import build_reference, verify_schema, capture_schema
from tire_api.vehicle_binary_postgres import migrate_postgres
from tire_api.vehicle_binary_migration import VehicleBinaryMigrationError, FAILURE_STAGES
import run_api_worker_regression as regression

HISTORICAL_COMMIT = '81e18e734330c43dfa8c20545aa70b6f78e6e97b'
REPORT = {'checks': [], 'historical_commit': HISTORICAL_COMMIT, 'scope': 'isolated PG with historical code and synthetic evidence'}
STEP = 'setup'
BOOTSTRAP = '''
import sys,json,os,traceback
from pathlib import Path
request=json.load(sys.stdin)
os.environ['TIRE_DATABASE_URL']=request['url']
os.environ['TI_AI_ENABLED']='0'
os.environ['TI_OBSERVABILITY_LOGS']='0'
sys.path[:0]=[request['api'],request['tests']]
try:
 from fastapi.testclient import TestClient
 from sqlalchemy import select
 from tire_api.db import RawCapture,QueryRun
 from tire_api.main import create_app
 from tire_api.vehicles import register_vehicle_routes,VehicleSnapshot
 from test_vehicles import FixtureVehicleAdapter,OfflineTireRegistry,live
 from admin_support import register_admin
 adapter=FixtureVehicleAdapter()
 app=create_app(request['url'],OfflineTireRegistry())
 register_vehicle_routes(app,adapter)
 with TestClient(app) as client:
  register_admin(client)
  response=live(client)
  assert response.status_code==200
  with app.state.database.sessions() as db:
   snapshot=db.scalar(select(VehicleSnapshot))
   assert snapshot is not None
   query=db.scalar(select(QueryRun))
   raw=snapshot.body.encode('utf-8')
   db.add(RawCapture(query_id=query.id,source_id=query.source_id,query_key=query.query_key,target_kind='vehicle',
    source_url=snapshot.source_url,raw_hash=snapshot.raw_hash,raw_body=raw,byte_count=len(raw),
    content_type=snapshot.content_type,parser_version=snapshot.parser_version,parser_identity=snapshot.parser_identity))
   db.commit()
   result={'passed':True,'snapshot_id':snapshot.id,'body':snapshot.body,'raw_hash':snapshot.raw_hash,'cookies':dict(client.cookies),'source_calls':len(adapter.calls)}
except Exception as error:
 result={'passed':False,'error_type':type(error).__name__,'code':getattr(error,'code',None),'frames':[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(error.__traceback__)]}
print(json.dumps(result))
raise SystemExit(0 if result['passed'] else 1)
'''


def record(name):
    REPORT['checks'].append({'name': name, 'passed': True})
    print(json.dumps(REPORT['checks'][-1]), flush=True)


def refused(code, call):
    try:
        call()
    except VehicleBinaryMigrationError as error:
        assert error.code == code
    else:
        raise AssertionError('expected_refusal_missing')


def run():
    global STEP
    data = Path(os.environ['TIRE_PG_TEST_DATA']).resolve()
    assert data.is_relative_to((ROOT / '.artifacts/postgres').resolve())
    slot = data.parent
    port = int(os.environ['TIRE_PG_TEST_PORT'])
    password = os.environ['TIRE_PG_TEST_PASSWORD']
    pg_bin = Path(os.environ['TIRE_PG_BIN']).resolve()
    with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='tire_verify_admin', password=password,
                         autocommit=True) as admin:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == data
        owner, owner_password = 'migration_' + uuid4().hex[:12], uuid4().hex + uuid4().hex
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}').format(
            sql.Identifier(owner), sql.Literal(owner_password)))

        def database(template=None):
            name = 'legacy_' + uuid4().hex[:12]
            statement = sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(owner))
            if template:
                statement += sql.SQL(' TEMPLATE {}').format(sql.Identifier(template))
            admin.execute(statement)
            return name

        def profile(name):
            return {'schema': 'external-fact-postgres@1', 'host': '127.0.0.1', 'port': port, 'database': name,
                    'user': owner, 'sslmode': 'verify-full', 'sslrootcert': os.environ['TIRE_PG_TEST_TLS_ROOT']}

        def url(name):
            return URL.create('postgresql+psycopg', username=owner, password=owner_password, host='127.0.0.1',
                              port=port, database=name, query={'sslmode': 'verify-full', 'sslrootcert': os.environ['TIRE_PG_TEST_TLS_ROOT']})

        def inventory(engine):
            with engine.connect() as connection:
                connection.exec_driver_sql("SET LOCAL timezone='UTC'")
                catalog = capture_schema(connection)
                rows = {table: sorted(json.dumps(row, sort_keys=True) for row in connection.exec_driver_sql(
                    f'SELECT to_jsonb(t) FROM public."{table}" t').scalars()) for table in inspect(connection).get_table_names(schema='public')}
            return {'catalog': catalog, 'rows': rows}

        STEP = 'historical_015_source_bootstrap_with_vehicle_evidence'
        exported = slot / 'historical'
        archived = subprocess.run(['git', 'archive', '--format=zip', HISTORICAL_COMMIT, 'apps/api/tire_api',
            'apps/api/tests/test_vehicles.py', 'apps/api/tests/admin_support.py'], cwd=ROOT, capture_output=True, timeout=30, check=True).stdout
        manifest = {}
        with zipfile.ZipFile(io.BytesIO(archived)) as archive:
            for entry in archive.infolist():
                path = Path(entry.filename)
                assert not path.is_absolute() and '..' not in path.parts and entry.filename.startswith('apps/')
                assert (entry.external_attr >> 16) & 0o170000 != 0o120000
                output = exported / path
                if entry.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    value = archive.read(entry)
                    output.write_bytes(value)
                    manifest[entry.filename] = hashlib.sha256(value).hexdigest()
        legacy = database()
        child = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', BOOTSTRAP],
            input=json.dumps({'url': url(legacy).render_as_string(hide_password=False), 'api': str(exported / 'apps/api'),
                              'tests': str(exported / 'apps/api/tests')}), text=True, encoding='utf-8', capture_output=True, timeout=90)
        bootstrap = json.loads(child.stdout)
        REPORT['historical_bootstrap'] = {key: value for key, value in bootstrap.items() if key not in {'cookies', 'body', 'raw_hash'}}
        assert child.returncode == 0 and bootstrap['passed']
        original = create_engine(url(legacy), poolclass=NullPool)
        before = inventory(original)
        assert len(before['rows']['raw_captures']) == 1
        record(STEP)

        STEP = 'normal_startup_requires_explicit_migration'
        ordinary = Database(url(legacy).render_as_string(hide_password=False))
        try:
            refused('vehicle_binary_migration_required', ordinary.initialize)
        finally:
            ordinary.close()
        assert inventory(original) == before
        record(STEP)

        STEP = 'snapshot_backup_and_explicit_cli_migration'
        target_name = database(legacy)
        profile_path, backup_path = slot / 'migration-profile.json', slot / 'before.dump'
        profile_path.write_text(json.dumps(profile(target_name)), encoding='utf-8')
        output = io.StringIO()
        with patch.object(cli.sys, 'stdin', SimpleNamespace(isatty=lambda: True)), \
             patch.object(cli, '_password', return_value=owner_password), redirect_stdout(output):
            result = cli.main(['--postgres-profile', str(profile_path), '--pg-bin', str(pg_bin),
                               '--backup-file', str(backup_path), '--offline-confirmed'])
        response = json.loads(output.getvalue())
        REPORT['migration'] = response
        assert result == 0 and response['ok'] and not response['already_current']
        assert response['database_backup']['sha256'] == hashlib.sha256(backup_path.read_bytes()).hexdigest()
        target = create_engine(url(target_name), poolclass=NullPool)
        after = inventory(target)
        for table, old_rows in before['rows'].items():
            if table == 'tire_schema_versions':
                assert all(row in after['rows'][table] for row in old_rows)
            else:
                old_columns = {item[1] for item in before['catalog']['columns'] if item[0] == table}
                projected = [json.dumps({key: value for key, value in json.loads(row).items() if key in old_columns}, sort_keys=True) for row in after['rows'][table]]
                assert sorted(projected) == old_rows
        record(STEP)

        STEP = 'repeat_migration_preserves_schema_and_rows'
        repeated = migrate_postgres(target, offline_confirmed=True)
        assert repeated['already_current'] and inventory(target) == after
        record(STEP)

        STEP = 'current_upgrade_matches_empty_reference'
        current = Database(url(target_name).render_as_string(hide_password=False))
        reference_engine = create_engine(url(database()), poolclass=NullPool)
        contract_path = slot / 'reference.json'
        try:
            current.initialize()
            contract = build_reference(reference_engine, contract_path)
            verify_schema(current.engine, contract_path, contract['sha256'])
        finally:
            current.close()
            reference_engine.dispose()
        record(STEP)

        STEP = 'upgraded_api_verify_reads_original_vehicle_evidence'
        from fastapi.testclient import TestClient
        from tire_api.main import create_app
        from test_core import FixtureRegistry
        with patch.dict(os.environ, {'TI_DATABASE_SCHEMA_MODE': 'verify', 'TI_DATABASE_SCHEMA_CONTRACT': str(contract_path),
                                     'TI_DATABASE_SCHEMA_SHA256': contract['sha256']}):
            upgraded_app = create_app(url(target_name).render_as_string(hide_password=False), FixtureRegistry())
            with TestClient(upgraded_app, cookies=bootstrap['cookies']) as client:
                evidence = client.get('/v1/vehicle-evidence/' + bootstrap['snapshot_id'], params={'mode': 'history'})
                assert evidence.status_code == 200
                assert evidence.json()['body'] == bootstrap['body'] and evidence.json()['raw_hash'] == bootstrap['raw_hash']
        record(STEP)

        STEP = 'independent_restore_matches_original_015'
        restored = database()
        parameters = cli.postgres_connect_args(profile(restored))
        environment = {**os.environ, 'PGPASSWORD': owner_password, 'PGHOST': '127.0.0.1', 'PGPORT': str(port),
                       'PGUSER': owner, 'PGSSLMODE': 'verify-full', 'PGSSLROOTCERT': parameters['sslrootcert']}
        restore = subprocess.run([str(pg_bin / 'pg_restore.exe'), '--exit-on-error', '--no-owner', '--no-acl', '--no-password',
                                  '--dbname', restored, str(backup_path)], env=environment, capture_output=True, timeout=60)
        assert restore.returncode == 0
        restored_engine = create_engine(url(restored), poolclass=NullPool)
        try:
            recovered = inventory(restored_engine)
            if recovered != before:
                REPORT['restore_catalog_differences'] = [key for key in before['catalog'] if before['catalog'][key] != recovered['catalog'][key]]
                REPORT['restore_row_differences'] = [key for key in before['rows'] if before['rows'][key] != recovered['rows'].get(key)]
                (slot / 'restore-diff.json').write_text(json.dumps({'before': before, 'recovered': recovered}, indent=2))
            assert recovered == before
        finally:
            restored_engine.dispose()
        record(STEP)

        for failure_stage in FAILURE_STAGES:
            STEP = 'rollback_' + failure_stage
            candidate = create_engine(url(database(legacy)), poolclass=NullPool)
            def fail(stage):
                if stage == failure_stage:
                    raise RuntimeError('synthetic_failure')
            try:
                refused('vehicle_binary_migration_failed', lambda: migrate_postgres(candidate, offline_confirmed=True, failure_hook=fail))
                assert inventory(candidate) == before
            finally:
                candidate.dispose()
            record(STEP)

        for label, statement, code in (
                ('bad_capture_hash', "UPDATE public.raw_captures SET raw_hash=repeat('0',64)", 'vehicle_binary_invalid_legacy_evidence'),
                ('partial_structure', "ALTER TABLE public.raw_captures ADD COLUMN body_encoding VARCHAR(16)", 'vehicle_binary_schema_inconsistent'),
                ('premature_version', "INSERT INTO public.tire_schema_versions(version) VALUES ('024_vehicle_binary_raw')", 'vehicle_binary_schema_inconsistent')):
            STEP = 'reject_' + label
            candidate = create_engine(url(database(legacy)), poolclass=NullPool)
            try:
                with candidate.begin() as connection:
                    connection.exec_driver_sql(statement)
                damaged = inventory(candidate)
                refused(code, lambda: migrate_postgres(candidate, offline_confirmed=True))
                assert inventory(candidate) == damaged
            finally:
                candidate.dispose()
            record(STEP)

        STEP = 'backup_failure_preserves_legacy_database'
        failed_name = database(legacy)
        failed_engine = create_engine(url(failed_name), poolclass=NullPool)
        parameters = cli.postgres_connect_args(profile(failed_name))
        try:
            with patch.object(cli.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
                refused('vehicle_binary_backup_failed', lambda: migrate_postgres(failed_engine, offline_confirmed=True,
                    backup=lambda connection: cli.snapshot_backup(connection, parameters, owner_password,
                                                                    str(pg_bin), str(slot / 'failed.dump'))))
            assert inventory(failed_engine) == before
            refused('vehicle_binary_backup_path_invalid', lambda: migrate_postgres(failed_engine, offline_confirmed=True,
                backup=lambda connection: cli.snapshot_backup(connection, parameters, owner_password,
                                                                str(pg_bin), str(backup_path))))
            assert inventory(failed_engine) == before
        finally:
            failed_engine.dispose()
        record(STEP)

        STEP = 'schema_lock_timeout_preserves_legacy_database'
        locked_engine = create_engine(url(database(legacy)), poolclass=NullPool)
        try:
            with locked_engine.begin() as blocker:
                blocker.exec_driver_sql('SELECT pg_advisory_xact_lock(821741906)')
                refused('vehicle_binary_migration_failed', lambda: migrate_postgres(locked_engine, offline_confirmed=True))
            assert inventory(locked_engine) == before
        finally:
            locked_engine.dispose()
        record(STEP)

        STEP = 'existing_view_and_custom_index_preserved'
        custom_engine = create_engine(url(database(legacy)), poolclass=NullPool)
        try:
            with custom_engine.begin() as connection:
                connection.exec_driver_sql('CREATE VIEW public.historical_vehicle_view AS SELECT id,body FROM public.vehicle_snapshots')
                connection.exec_driver_sql('CREATE INDEX historical_vehicle_body ON public.vehicle_snapshots(body)')
            custom_before = inventory(custom_engine)
            migrate_postgres(custom_engine, offline_confirmed=True)
            custom_after = inventory(custom_engine)
            for category in ('indexes', 'relations'):
                assert all(row in custom_after['catalog'][category] for row in custom_before['catalog'][category])
        finally:
            custom_engine.dispose()
        record(STEP)

        original.dispose()
        target.dispose()
        assert all(hashlib.sha256((exported / name).read_bytes()).hexdigest() == digest for name, digest in manifest.items())
        REPORT['historical_source_files'] = len(manifest)
        REPORT['historical_sources_stable'] = True


if __name__ == '__main__':
    bindings = regression.bindings()
    try:
        run()
    except Exception as error:
        REPORT.update(failure_step=STEP, error_type=type(error).__name__, code=getattr(error, 'code', None),
            frames=[{'file': Path(frame.filename).name, 'function': frame.name, 'line': frame.lineno} for frame in traceback.extract_tb(error.__traceback__)])
    REPORT['inputs_stable'] = bindings == regression.bindings()
    REPORT['input_count'] = len(bindings)
    REPORT['passed'] = bool(REPORT['checks']) and REPORT['inputs_stable'] and 'failure_step' not in REPORT
    Path(os.environ['TIRE_PG_TEST_REPORT']).write_text(json.dumps(REPORT, indent=2), encoding='utf-8')
    print(json.dumps({'passed': REPORT['passed'], 'checks': len(REPORT['checks']), 'failure_step': REPORT.get('failure_step')}), flush=True)
    raise SystemExit(0 if REPORT['passed'] else 1)
