"""Source-bound PG reference/runtime acceptance, only on a fresh local cluster."""
import asyncio
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import sys
import traceback
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, URL

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests'), str(ROOT / 'apps/worker')]
from tire_api.db import Base, Database, register_schema_models
from tire_api import postgres_schema_cli as cli
from tire_api.postgres_schema import SchemaContractError, build_reference, capture_schema, load_contract, verify_schema
from tire_api.external_fact_governance_postgres import postgres_connect_args, postgres_engine
import run_api_worker_regression as regression

REPORT = {'checks': [], 'scope': 'synthetic isolated PostgreSQL; reference and runtime roles; no external provider'}
STEP = 'setup'


def record(name):
    REPORT['checks'].append({'name': name, 'passed': True})
    print(json.dumps(REPORT['checks'][-1]), flush=True)


def refused(code, call):
    try:
        call()
    except SchemaContractError as error:
        assert error.code == code
    else:
        raise AssertionError('schema_refusal_missing')


def run():
    global STEP
    expected = Path(os.environ['TIRE_PG_TEST_DATA']).resolve()
    assert expected.is_relative_to((ROOT / '.artifacts/postgres').resolve())
    assert expected.name == 'data' and expected.parent.name.startswith('pgverify-')
    port = int(os.environ['TIRE_PG_TEST_PORT'])
    os.environ['TI_OBSERVABILITY_LOGS'] = '0'
    for key in ('TI_DATABASE_SCHEMA_MODE', 'TI_DATABASE_SCHEMA_CONTRACT', 'TI_DATABASE_SCHEMA_SHA256'):
        os.environ.pop(key, None)
    slot = expected.parent
    with psycopg.connect(host='127.0.0.1', port=port, user='tire_verify_admin',
            password=os.environ['TIRE_PG_TEST_PASSWORD'], dbname='postgres', autocommit=True, connect_timeout=5) as admin:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == expected
        owner, owner_secret = 'schema_owner_' + uuid4().hex[:12], secrets.token_hex(32)
        runtime, runtime_secret = 'schema_runtime_' + uuid4().hex[:12], secrets.token_hex(32)
        for name, password in ((owner, owner_secret), (runtime, runtime_secret)):
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS').format(
                sql.Identifier(name), sql.Literal(password)))

        def database(template=None):
            name = 'schema_' + uuid4().hex[:12]
            statement = sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(owner))
            if template:
                statement += sql.SQL(' TEMPLATE {}').format(sql.Identifier(template))
            admin.execute(statement)
            return name

        def url(name, *, limited=False):
            transport = {'sslmode': 'disable'}
            if os.environ.get('TIRE_PG_TEST_TLS_ROOT'):
                transport = {'sslmode': 'verify-full', 'sslrootcert': os.environ['TIRE_PG_TEST_TLS_ROOT']}
            return URL.create('postgresql+psycopg', username=runtime if limited else owner,
                password=runtime_secret if limited else owner_secret, host='127.0.0.1', port=port, database=name, query=transport)

        def profile(name):
            value = {'schema': 'external-fact-postgres@1', 'host': '127.0.0.1', 'port': port,
                'database': name, 'user': owner, 'sslmode': 'disable', 'sslrootcert': None}
            if os.environ.get('TIRE_PG_TEST_TLS_ROOT'):
                value.update(sslmode='verify-full', sslrootcert=os.environ['TIRE_PG_TEST_TLS_ROOT'])
            return value

        def admin_for(name):
            return psycopg.connect(host='127.0.0.1', port=port, user='tire_verify_admin',
                password=os.environ['TIRE_PG_TEST_PASSWORD'], dbname=name, autocommit=True, connect_timeout=5)

        def grants(engine, name):
            # Deliberately broad DML fixture, not a production least-privilege role policy.
            with engine.begin() as connection:
                connection.exec_driver_sql('REVOKE CREATE, TEMPORARY ON DATABASE "' + name + '" FROM PUBLIC')
                connection.exec_driver_sql('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
                connection.exec_driver_sql('GRANT CONNECT ON DATABASE "' + name + '" TO "' + runtime + '"')
                connection.exec_driver_sql('GRANT USAGE ON SCHEMA public TO "' + runtime + '"')
                connection.exec_driver_sql('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "' + runtime + '"')
                connection.exec_driver_sql('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "' + runtime + '"')

        STEP = 'reference_cli'
        reference = database()
        contract_path, profile_path = slot / 'reference.json', slot / 'reference-profile.json'
        profile_path.write_text(json.dumps(profile(reference)), encoding='utf-8')
        output = io.StringIO()
        with patch.object(cli.sys, 'stdin', SimpleNamespace(isatty=lambda: True)), \
             patch.object(cli, '_password', return_value=owner_secret), redirect_stdout(output):
            result_code = cli.main(['--postgres-profile', str(profile_path), '--output-file', str(contract_path),
                                   '--empty-reference-confirmed'])
        result = json.loads(output.getvalue())
        REPORT['reference_result'] = result
        assert result_code == 0 and result['ok']
        digest = result['sha256']
        contract = load_contract(contract_path, digest)
        REPORT['reference_relations'] = result['relations']
        REPORT['reference_model_tables'] = len(Base.metadata.tables)
        record(STEP)

        STEP = 'reference_cannot_adopt_existing_database_or_overwrite_artifact'
        engine = postgres_engine(postgres_connect_args(profile(reference)), owner_secret)
        try:
            refused('schema_reference_not_empty', lambda: build_reference(engine, slot / 'second.json'))
            refused('schema_contract_output_invalid', lambda: build_reference(engine, contract_path))
            assert not (slot / 'second.json').exists()
        finally:
            engine.dispose()
        record(STEP)

        STEP = 'independent_migration_matches_reference'
        target_name = database()
        target = Database(url(target_name).render_as_string(hide_password=False), schema_mode='migrate')
        try:
            target.initialize()
            verify_schema(target.engine, contract_path, digest)
            grants(target.engine, target_name)
        finally:
            target.close()
        record(STEP)

        STEP = 'nonowner_api_readonly_startup_and_normal_query'
        from fastapi.testclient import TestClient
        from admin_support import register_admin
        from test_core import FixtureRegistry, live
        from tire_api.main import create_app
        os.environ['TI_DATABASE_SCHEMA_MODE'] = 'verify'
        os.environ['TI_DATABASE_SCHEMA_CONTRACT'] = str(contract_path)
        os.environ['TI_DATABASE_SCHEMA_SHA256'] = digest
        limited_url = url(target_name, limited=True).render_as_string(hide_password=False)
        app = create_app(limited_url, FixtureRegistry())
        REPORT['factory_added_tables'] = sorted(set(Base.metadata.tables) - {row[0] for row in contract['catalog']['relations']})
        assert not REPORT['factory_added_tables']
        startup = []
        def observe(_c, _cu, statement, _p, _ctx, _many):
            startup.append(statement.lstrip().split(None, 1)[0].upper())
        event.listen(app.state.database.engine, 'before_cursor_execute', observe)
        with TestClient(app) as client:
            event.remove(app.state.database.engine, 'before_cursor_execute', observe)
            assert startup and set(startup) <= {'SELECT', 'SHOW', 'SET'}
            register_admin(client)
            response = live(client)
            assert response.status_code == 200 and response.json()['data_state'] == 'live'
            evidence = '/v1/evidence/' + response.json()['provenance'][0]['snapshot_id']
            assert client.get(evidence).status_code == 200
            historical_cookies = dict(client.cookies)
        assert set(Base.metadata.tables) == {row[0] for row in contract['catalog']['relations'] if row[0] in Base.metadata.tables}
        REPORT['startup_statement_types'] = sorted(set(startup))
        record(STEP)

        STEP = 'nonowner_worker_normal_once_entry'
        import monitor
        os.environ['TIRE_DATABASE_URL'] = limited_url
        output = io.StringIO()
        worker_statements = []
        def observe_worker(_c, _cu, statement, _p, _ctx, _many):
            worker_statements.append(statement.lstrip().split(None, 1)[0].upper())
        event.listen(Engine, 'before_cursor_execute', observe_worker)
        try:
            with patch.object(sys, 'argv', ['monitor', '--once']), redirect_stdout(output):
                asyncio.run(monitor.main())
        finally:
            event.remove(Engine, 'before_cursor_execute', observe_worker)
        worker_result = json.loads(output.getvalue())
        assert worker_result['results'] == []
        assert worker_statements and set(worker_statements) <= {'SELECT','SET','SHOW','INSERT','UPDATE','DELETE','WITH'}
        REPORT['worker_statement_types'] = sorted(set(worker_statements))
        record(STEP)

        STEP = 'legacy_001_004_upgrade_preserves_rows_and_matches_reference'
        # Same synthetic predecessor shape as the core acceptance; this is not
        # a recovered deployment database or an archived historical release.
        removed_columns = {
            'verifications': ['etag', 'last_modified', 'parser_identity'],
            'alert_rule_revisions': ['conditions'],
            'query_runs': ['selection_filters'],
            **{name: ['parser_identity'] for name in (
                'snapshots', 'raw_captures', 'rejected_observations', 'source_quarantines',
                'vehicle_snapshots', 'vehicle_verifications', 'vehicle_quarantines')},
        }
        old_versions = ('001_verification_validators', '002_monitor_rule_conditions',
                        '003_parser_release_provenance', '004_query_selection_filters')

        def legacy_rows(connection):
            result = {}
            for table in sorted(Base.metadata.tables):
                rows = []
                for row in connection.exec_driver_sql(f'SELECT to_jsonb(t) FROM public."{table}" t').scalars():
                    for column in removed_columns.get(table, ()):
                        row.pop(column, None)
                    rows.append(json.dumps(row, sort_keys=True, separators=(',', ':')))
                result[table] = sorted(rows)
            return result

        with patch.dict(os.environ):
            for key in ('TI_DATABASE_SCHEMA_MODE', 'TI_DATABASE_SCHEMA_CONTRACT', 'TI_DATABASE_SCHEMA_SHA256'):
                os.environ.pop(key, None)
            migration_db = Database(url(target_name).render_as_string(hide_password=False))
        try:
            with migration_db.engine.begin() as connection:
                for table, columns in removed_columns.items():
                    for column in columns:
                        connection.exec_driver_sql(f'ALTER TABLE public."{table}" DROP COLUMN "{column}"')
                for version in old_versions:
                    connection.execute(text('DELETE FROM public.tire_schema_versions WHERE version=:version'), {'version': version})
                old_rows = legacy_rows(connection)
                remaining_versions = connection.exec_driver_sql('SELECT version, applied_at FROM public.tire_schema_versions ORDER BY version').all()
                assert old_rows['query_runs'] and old_rows['snapshots'] and old_rows['verifications']
            migration_db.initialize()
            with migration_db.engine.connect() as connection:
                assert legacy_rows(connection) == old_rows
                for table, columns in removed_columns.items():
                    predicate = ' OR '.join(f'"{column}" IS NOT NULL' for column in columns)
                    assert connection.exec_driver_sql(f'SELECT count(*) FROM public."{table}" WHERE {predicate}').scalar() == 0
                all_versions = connection.exec_driver_sql('SELECT version, applied_at FROM public.tire_schema_versions ORDER BY version').all()
                assert [row for row in all_versions if row.version not in old_versions] == remaining_versions
            verify_schema(migration_db.engine, contract_path, digest)
            record(STEP)
            STEP = 'legacy_001_004_repeated_migration_is_stable'
            migration_db.initialize()
            with migration_db.engine.connect() as connection:
                assert legacy_rows(connection) == old_rows
                assert connection.exec_driver_sql('SELECT version, applied_at FROM public.tire_schema_versions ORDER BY version').all() == all_versions
            verify_schema(migration_db.engine, contract_path, digest)
            record(STEP)
        finally:
            migration_db.close()
        STEP = 'legacy_001_004_nonowner_api_reads_old_evidence_and_new_query'
        upgraded_app = create_app(limited_url, FixtureRegistry())
        with TestClient(upgraded_app, cookies=historical_cookies) as client:
            assert client.get(evidence).status_code == 200
            assert live(client).status_code == 200
        record(STEP)

        STEP = 'runtime_cannot_perform_owner_ddl'
        runtime_db = Database(limited_url)
        try:
            runtime_db.initialize()
            for statement in ('CREATE TABLE public.forbidden(id integer)', 'CREATE TEMP TABLE forbidden(id integer)',
                    'ALTER TABLE public.users ADD COLUMN forbidden integer', 'DROP TABLE public.knowledge_index_state',
                    'ALTER TABLE public.external_fact_grant_revisions DISABLE TRIGGER ALL'):
                with runtime_db.engine.connect() as connection:
                    try:
                        connection.exec_driver_sql(statement)
                    except Exception as error:
                        assert getattr(getattr(error, 'orig', None), 'sqlstate', None) == '42501'
                    else:
                        raise AssertionError('runtime_ddl_permission_present')
                    finally:
                        connection.rollback()
            verify_schema(runtime_db.engine, contract_path, digest)
        finally:
            runtime_db.close()
        record(STEP)

        changes = {
            'missing_table': 'DROP TABLE public.knowledge_index_state',
            'missing_column': 'ALTER TABLE public.users DROP COLUMN display_name',
            'column_type': 'ALTER TABLE public.users ALTER COLUMN display_name TYPE text',
            'column_default': "ALTER TABLE public.users ALTER COLUMN display_name SET DEFAULT 'unreviewed'",
            'column_nullable': 'ALTER TABLE public.users ALTER COLUMN display_name DROP NOT NULL',
            'renamed_column': 'ALTER TABLE public.users RENAME COLUMN display_name TO renamed_display_name',
            'extra_column': 'ALTER TABLE public.users ADD COLUMN unexpected text',
            'missing_constraint': 'ALTER TABLE public.external_fact_license_evidence DROP CONSTRAINT ck_external_fact_evidence_size',
            'missing_index': 'DROP INDEX public.ix_knowledge_search_vector',
            'disabled_trigger': 'ALTER TABLE public.external_fact_grant_revisions DISABLE TRIGGER external_fact_grant_revisions_no_update',
            'changed_function': "CREATE OR REPLACE FUNCTION public.tire_external_fact_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN OLD; END $$",
            'missing_version': "DELETE FROM public.tire_schema_versions WHERE version='025_external_fact_governance'",
            'internal_fk_disabled': 'ALTER TABLE public.external_fact_grant_revisions DISABLE TRIGGER ALL',
            'unexpected_view': 'CREATE VIEW public.unexpected_view AS SELECT 1 AS value',
            'extension_changed': 'CREATE EXTENSION vector',
        }
        for label, statement in changes.items():
            STEP = 'reject_' + label
            changed_name = database(reference)
            owner_engine = create_engine(url(changed_name))
            try:
                grants(owner_engine, changed_name)
            finally:
                owner_engine.dispose()
            with admin_for(changed_name) as administrator:
                administrator.execute(statement)
            candidate = Database(url(changed_name, limited=True).render_as_string(hide_password=False))
            try:
                refused('schema_contract_mismatch', candidate.initialize)
            finally:
                candidate.close()
            record(STEP)

        for label, statement, code in (
                ('rls', 'ALTER TABLE public.users ENABLE ROW LEVEL SECURITY', 'schema_rls_not_supported'),
                ('custom_type', "CREATE TYPE public.extra_type AS ENUM ('synthetic')", 'schema_feature_not_supported')):
            STEP = 'reject_' + label
            changed_name = database(reference)
            owner_engine = create_engine(url(changed_name))
            try:
                grants(owner_engine, changed_name)
            finally:
                owner_engine.dispose()
            with admin_for(changed_name) as administrator:
                administrator.execute(statement)
            candidate = Database(url(changed_name, limited=True).render_as_string(hide_password=False))
            try:
                refused(code, candidate.initialize)
            finally:
                candidate.close()
            record(STEP)

        STEP = 'optional_vector_reference_and_runtime'
        vector_name = database()
        with admin_for(vector_name) as administrator:
            administrator.execute('CREATE EXTENSION vector')
        vector_engine = postgres_engine(postgres_connect_args(profile(vector_name)), owner_secret)
        vector_path = slot / 'vector-reference.json'
        try:
            vector_contract = build_reference(vector_engine, vector_path)
            grants(vector_engine, vector_name)
        finally:
            vector_engine.dispose()
        vector_runtime = Database(url(vector_name, limited=True).render_as_string(hide_password=False),
            schema_contract=vector_path, schema_sha256=vector_contract['sha256'])
        try:
            vector_runtime.initialize()
            assert vector_contract['relations'] == result['relations'] + 1
        finally:
            vector_runtime.close()
        record(STEP)

        STEP = 'contract_and_source_pin_rejection'
        runtime_db = Database(limited_url)
        try:
            refused('schema_contract_hash_mismatch', lambda: verify_schema(runtime_db.engine, contract_path, '0' * 64))
            altered = dict(contract, source_sha256='0' * 64)
            stale = slot / 'wrong-source.json'
            stale.write_text(json.dumps(altered), encoding='utf-8')
            refused('schema_contract_source_changed', lambda: verify_schema(runtime_db.engine, stale, hashlib.sha256(stale.read_bytes()).hexdigest()))
            altered = dict(contract, postgres_major=contract['postgres_major'] + 1)
            version = slot / 'wrong-version.json'
            version.write_text(json.dumps(altered), encoding='utf-8')
            refused('schema_contract_mismatch', lambda: verify_schema(runtime_db.engine, version, hashlib.sha256(version.read_bytes()).hexdigest()))
        finally:
            runtime_db.close()
        record(STEP)
        assert admin.execute('SELECT count(*) FROM pg_stat_activity WHERE usename=%s', (runtime,)).fetchone()[0] == 0
        record('runtime_connections_closed')


if __name__ == '__main__':
    before = regression.bindings()
    try:
        run()
    except Exception as error:
        REPORT.update(failure_step=STEP, error_type=type(error).__name__, code=getattr(error, 'code', None),
            sqlstate=getattr(getattr(error, 'orig', error), 'sqlstate', None),
            frames=[{'file': Path(f.filename).name, 'function': f.name, 'line': f.lineno} for f in traceback.extract_tb(error.__traceback__)])
    REPORT['inputs_stable'] = before == regression.bindings()
    REPORT['input_count'] = len(before)
    REPORT['passed'] = bool(REPORT['checks']) and REPORT['inputs_stable'] and 'failure_step' not in REPORT
    Path(os.environ['TIRE_PG_TEST_REPORT']).write_text(json.dumps(REPORT, indent=2), encoding='utf-8')
    print(json.dumps({'passed': REPORT['passed'], 'checks': len(REPORT['checks']), 'failure_step': REPORT.get('failure_step')}), flush=True)
    raise SystemExit(0 if REPORT['passed'] else 1)
