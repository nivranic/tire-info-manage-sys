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


def runtime_permission_checks(administrator, runtime_engine, role, database_name, owner):
    """Exercise effective ACL drift and the exact generated provisioning plan."""
    global STEP
    from tire_api.postgres_runtime_roles import UPDATE_COLUMNS, check_runtime_role, runtime_role_sql
    from tire_api.external_fact_sql import LOCK_ROUTINES

    peer = 'runtime_peer_' + uuid4().hex[:12]
    administrator.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOINHERIT').format(sql.Identifier(peer)))
    identifiers = {'role': sql.Identifier(role), 'peer': sql.Identifier(peer),
                   'database': sql.Identifier(database_name), 'owner': sql.Identifier(owner),
                   'body': sql.Literal(LOCK_ROUTINES['tire_lock_external_owner']),
                   'user_updates': sql.SQL(',').join(sql.Identifier(column) for column in UPDATE_COLUMNS['users'])}
    cases = (
        ('missing_update_column', 'REVOKE UPDATE (display_name) ON public.users FROM {role}',
         'GRANT UPDATE (display_name) ON public.users TO {role}', 'actor_lock_grant'),
        ('missing_table_read', 'REVOKE SELECT ON public.snapshots FROM {role}',
         'GRANT SELECT ON public.snapshots TO {role}', 'required_table_grants'),
        ('missing_append', 'REVOKE INSERT ON public.raw_captures FROM {role}',
         'GRANT INSERT ON public.raw_captures TO {role}', 'required_table_grants'),
        ('missing_delete', 'REVOKE DELETE ON public.knowledge_facets FROM {role}',
         'GRANT DELETE ON public.knowledge_facets TO {role}', 'required_table_grants'),
        ('missing_lock_execute', 'REVOKE EXECUTE ON FUNCTION public.tire_lock_external_owner() FROM {role}',
         'GRANT EXECUTE ON FUNCTION public.tire_lock_external_owner() TO {role}', 'required_routines'),
        ('extra_column_update', 'GRANT UPDATE (id) ON public.snapshots TO {role}',
         'REVOKE UPDATE (id) ON public.snapshots FROM {role}', 'column_privileges'),
        ('extra_table_update', 'GRANT UPDATE ON public.users TO {role}',
         'REVOKE UPDATE ON public.users FROM {role}; '
         'GRANT UPDATE ({user_updates}) ON public.users TO {role}', 'table_privileges'),
        ('governance_append', 'GRANT INSERT ON public.external_fact_grant_revisions TO {role}',
         'REVOKE INSERT ON public.external_fact_grant_revisions FROM {role}', 'table_privileges'),
        ('table_grant_option', 'GRANT SELECT ON public.snapshots TO {role} WITH GRANT OPTION',
         'REVOKE GRANT OPTION FOR SELECT ON public.snapshots FROM {role}', 'table_grant_options'),
        ('column_grant_option', 'GRANT UPDATE (display_name) ON public.users TO {role} WITH GRANT OPTION',
         'REVOKE GRANT OPTION FOR UPDATE (display_name) ON public.users FROM {role}', 'column_grant_options'),
        ('routine_grant_option', 'GRANT EXECUTE ON FUNCTION public.tire_lock_external_owner() TO {role} WITH GRANT OPTION',
         'REVOKE GRANT OPTION FOR EXECUTE ON FUNCTION public.tire_lock_external_owner() FROM {role}', 'routine_grant_options'),
        ('public_schema_create', 'GRANT CREATE ON SCHEMA public TO PUBLIC',
         'REVOKE CREATE ON SCHEMA public FROM PUBLIC', 'schema_ddl'),
        ('public_temporary', 'GRANT TEMPORARY ON DATABASE {database} TO PUBLIC',
         'REVOKE TEMPORARY ON DATABASE {database} FROM PUBLIC', 'database_ddl'),
        ('role_parent', 'GRANT {peer} TO {role}', 'REVOKE {peer} FROM {role}', 'role_memberships'),
        ('role_member', 'GRANT {role} TO {peer}', 'REVOKE {role} FROM {peer}', 'role_memberships'),
        ('role_inherit', 'ALTER ROLE {role} INHERIT', 'ALTER ROLE {role} NOINHERIT', 'role_attributes'),
        ('row_security', 'ALTER TABLE public.snapshots ENABLE ROW LEVEL SECURITY',
         'ALTER TABLE public.snapshots DISABLE ROW LEVEL SECURITY', 'row_security_unsupported'),
        ('default_acl', 'ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT SELECT ON TABLES TO {role}',
         'ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public REVOKE SELECT ON TABLES FROM {role}', 'default_privileges'),
        ('unknown_definer', 'CREATE FUNCTION public.synthetic_runtime_definer() RETURNS void LANGUAGE plpgsql '
         'SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN RETURN; END $$',
         'DROP FUNCTION public.synthetic_runtime_definer()', 'security_definer_access'),
        ('lock_body', 'CREATE OR REPLACE FUNCTION public.tire_lock_external_owner() RETURNS void LANGUAGE plpgsql '
         'VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN RETURN; END $$',
         'CREATE OR REPLACE FUNCTION public.tire_lock_external_owner() RETURNS void LANGUAGE plpgsql '
         'VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS {body}', 'required_routines'),
        ('lock_search_path', 'ALTER FUNCTION public.tire_lock_external_owner() SET search_path=public,pg_catalog',
         'ALTER FUNCTION public.tire_lock_external_owner() SET search_path=pg_catalog', 'required_routines'),
        ('lock_invoker', 'ALTER FUNCTION public.tire_lock_external_owner() SECURITY INVOKER',
         'ALTER FUNCTION public.tire_lock_external_owner() SECURITY DEFINER', 'required_routines'),
        ('lock_overload', 'CREATE FUNCTION public.tire_lock_external_owner(integer) RETURNS void LANGUAGE plpgsql '
         'SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN RETURN; END $$',
         'DROP FUNCTION public.tire_lock_external_owner(integer)', 'security_definer_access'),
    )
    assert check_runtime_role(runtime_engine)['ok']
    for name, mutation, restore, code in cases:
        STEP = 'runtime_policy_rejects_' + name
        administrator.execute(sql.SQL(mutation).format(**identifiers))
        observed = []
        def observe(_c, _cu, statement, _p, _ctx, _many):
            observed.append(statement.lstrip().split(None, 1)[0].upper())
        try:
            event.listen(runtime_engine, 'before_cursor_execute', observe)
            try:
                result = check_runtime_role(runtime_engine)
            finally:
                event.remove(runtime_engine, 'before_cursor_execute', observe)
            REPORT.setdefault('runtime_policy_rejections', []).append({
                'case': name, 'violations': result['violations'], 'statement_types': sorted(set(observed))})
            assert not result['ok'] and code in result['violations'], result['violations']
            assert observed and set(observed) <= {'SELECT', 'SET', 'SHOW', 'WITH'}, observed
            # Missing privileges are repairable by the plan. Unsafe privileges
            # and altered routines must be refused before any grants persist.
            if not name.startswith('missing_'):
                try:
                    administrator.execute(runtime_role_sql(role, database_name)).close()
                except psycopg.Error as error:
                    assert error.sqlstate == 'P0001', error.sqlstate
                else:
                    raise AssertionError('unsafe_runtime_plan_accepted')
                finally:
                    administrator.execute('ROLLBACK').close()
        finally:
            administrator.execute(sql.SQL(restore).format(**identifiers))
        restored = check_runtime_role(runtime_engine)
        REPORT['runtime_policy_rejections'][-1]['restored_violations'] = restored['violations']
        assert restored['ok'], restored['violations']
        record(STEP)

    STEP = 'runtime_policy_partial_grants_postcheck_rollback_and_reapply'
    candidate, candidate_secret = 'runtime_candidate_' + uuid4().hex[:12], secrets.token_hex(32)
    grantor, grantor_secret = 'runtime_grantor_' + uuid4().hex[:12], secrets.token_hex(32)
    for name, password in ((candidate, candidate_secret), (grantor, grantor_secret)):
        administrator.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT PASSWORD {} '
            'NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS').format(sql.Identifier(name), sql.Literal(password)))
    administrator.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {} WITH GRANT OPTION').format(
        sql.Identifier(database_name), sql.Identifier(grantor)))
    administrator.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {} WITH GRANT OPTION').format(sql.Identifier(grantor)))
    administrator.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(grantor)))
    for routine in LOCK_ROUTINES:
        administrator.execute(sql.SQL('GRANT EXECUTE ON FUNCTION public.{}() TO {}').format(
            sql.Identifier(routine), sql.Identifier(grantor)))

    def candidate_acl():
        return administrator.execute("""
            SELECT entries.kind, entries.object_id, entries.column_id,
                   a.grantor, a.grantee, a.privilege_type, a.is_grantable
            FROM (
                SELECT 'database' AS kind, oid AS object_id, 0 AS column_id, datacl AS acl
                FROM pg_database WHERE datname=current_database()
                UNION ALL SELECT 'schema', oid, 0, nspacl FROM pg_namespace
                UNION ALL SELECT 'relation', oid, 0, relacl FROM pg_class
                UNION ALL SELECT 'column', attrelid, attnum, attacl FROM pg_attribute
                UNION ALL SELECT 'routine', oid, 0, proacl FROM pg_proc
            ) entries CROSS JOIN LATERAL aclexplode(entries.acl) a
            WHERE a.grantee=(SELECT oid FROM pg_roles WHERE rolname=%s)
            ORDER BY 1,2,3,4,5,6,7
        """, (candidate,)).fetchall()

    before = candidate_acl()
    assert not before
    notices = []
    with psycopg.connect(host=runtime_engine.url.host, port=runtime_engine.url.port, user=grantor,
            password=grantor_secret, dbname=database_name, autocommit=True, connect_timeout=5,
            **dict(runtime_engine.url.query)) as partial:
        partial.add_notice_handler(lambda notice: notices.append(notice.sqlstate))
        try:
            cursor = partial.execute(runtime_role_sql(candidate, database_name))
            while cursor.nextset():
                pass
            cursor.close()
        except psycopg.Error as error:
            REPORT['runtime_partial_grant_sqlstate'] = error.sqlstate
            REPORT['runtime_partial_grant_notice_sqlstates'] = notices
            assert error.sqlstate == 'P0001', error.sqlstate
            assert partial.info.transaction_status == psycopg.pq.TransactionStatus.INERROR
            assert notices, 'no_grant_stage_observed'
        else:
            raise AssertionError('incomplete_runtime_grants_accepted')
        finally:
            partial.execute('ROLLBACK').close()
    assert candidate_acl() == before
    administrator.execute(runtime_role_sql(candidate, database_name)).close()
    installed = candidate_acl()
    assert installed
    administrator.execute(runtime_role_sql(candidate, database_name)).close()
    assert candidate_acl() == installed
    candidate_engine = create_engine(runtime_engine.url.set(username=candidate, password=candidate_secret))
    try:
        assert check_runtime_role(candidate_engine)['ok']
    finally:
        candidate_engine.dispose()
    record(STEP)


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
            from tire_api.postgres_runtime_roles import runtime_role_sql, check_runtime_role
            with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
                connection.exec_driver_sql('REVOKE CREATE, TEMPORARY ON DATABASE "' + name + '" FROM PUBLIC')
                connection.exec_driver_sql('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
                connection.exec_driver_sql(runtime_role_sql(runtime, name))
            checked = create_engine(url(name, limited=True))
            try:
                result = check_runtime_role(checked)
                assert result['ok'], result['violations']
            finally:
                checked.dispose()

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

        STEP = 'runtime_cannot_rewrite_evidence_or_approve_licenses'
        statements = (
            'UPDATE public.snapshots SET raw_hash=raw_hash WHERE false',
            'DELETE FROM public.snapshots WHERE false',
            'TRUNCATE public.raw_captures CASCADE',
            'DELETE FROM public.audit_events WHERE false',
            'UPDATE public.users SET id=id WHERE false',
            'INSERT INTO public.tire_schema_versions SELECT * FROM public.tire_schema_versions WHERE false',
            'INSERT INTO public.external_fact_grant_revisions SELECT * FROM public.external_fact_grant_revisions WHERE false',
            'INSERT INTO public.external_fact_license_evidence SELECT * FROM public.external_fact_license_evidence WHERE false',
        )
        checked = create_engine(url(target_name, limited=True))
        try:
            for statement in statements:
                with checked.connect() as connection:
                    try:
                        connection.exec_driver_sql(statement)
                    except Exception as error:
                        assert getattr(getattr(error, 'orig', None), 'sqlstate', None) == '42501'
                    else:
                        raise AssertionError('runtime_forbidden_dml_present')
                    finally:
                        connection.rollback()
        finally:
            checked.dispose()
        REPORT['runtime_forbidden_dml_count'] = len(statements)
        record(STEP)

        checked = create_engine(url(target_name, limited=True))
        try:
            with admin_for(target_name) as administrator:
                runtime_permission_checks(administrator, checked, runtime, target_name, owner)
            verify_schema(checked, contract_path, digest)
        finally:
            checked.dispose()

        changes = {
            'missing_table': 'DROP TABLE public.knowledge_index_state',
            'missing_column': 'ALTER TABLE public.users DROP COLUMN display_name',
            'column_type': 'ALTER TABLE public.users ALTER COLUMN display_name TYPE text',
            'column_default': "ALTER TABLE public.users ALTER COLUMN display_name SET DEFAULT 'unreviewed'",
            'column_nullable': 'ALTER TABLE public.users ALTER COLUMN display_name DROP NOT NULL',
            'renamed_column': 'ALTER TABLE public.users RENAME COLUMN display_name TO renamed_display_name',
            'extra_column': 'ALTER TABLE public.users ADD COLUMN unexpected text',
            'changed_enum': "ALTER TABLE public.ai_stream_events DROP CONSTRAINT ai_stream_events_type_check; "
                "ALTER TABLE public.ai_stream_events ADD CONSTRAINT ai_stream_events_type_check CHECK (type IN ('accepted','failed'))",
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
        vector_indexes = ({'model_space': 'a' * 64, 'dimensions': 3},
                          {'model_space': 'b' * 64, 'dimensions': 4})
        try:
            vector_contract = build_reference(vector_engine, vector_path, vector_indexes=vector_indexes)
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

        STEP = 'vector_owner_maintenance_postcheck_rolls_back_partial_ddl'
        from tire_api.db import apply_schema
        from tire_api.dense import ensure_hnsw
        from tire_api import postgres_vector_indexes as vector_cli
        index_target = database()
        with admin_for(index_target) as administrator:
            administrator.execute('CREATE EXTENSION vector')
        index_owner = postgres_engine(postgres_connect_args(profile(index_target)), owner_secret)
        index_profile, index_manifest = slot / 'index-profile.json', slot / 'index-manifest.json'
        index_profile.write_text(json.dumps(profile(index_target)), encoding='utf-8')
        index_args = ['--postgres-profile', str(index_profile), '--vector-indexes-file', str(index_manifest),
                      '--schema-contract', str(vector_path), '--schema-sha256', vector_contract['sha256']]
        def apply_index_cli(specs, *, approved_path=vector_path, approved_sha256=vector_contract['sha256']):
            index_manifest.write_text(json.dumps({'schema': 'postgres-vector-indexes@1', 'indexes': specs}), encoding='utf-8')
            output = io.StringIO()
            with patch.object(vector_cli.sys, 'stdin', SimpleNamespace(isatty=lambda: True)), \
                 patch.object(vector_cli, '_password', return_value=owner_secret), redirect_stdout(output):
                code = vector_cli.main([*index_args[:-4], '--schema-contract', str(approved_path),
                                        '--schema-sha256', approved_sha256])
            return code, json.loads(output.getvalue())
        def hnsw_count():
            with index_owner.connect() as connection:
                return connection.exec_driver_sql("SELECT count(*) FROM pg_indexes WHERE schemaname='public' "
                    "AND tablename='embedding_vectors' AND indexdef LIKE '%%USING hnsw%%'").scalar()
        try:
            with index_owner.begin() as connection:
                connection.exec_driver_sql('SET LOCAL search_path=public,pg_catalog')
                apply_schema(connection)
            assert hnsw_count() == 0
            wrong = [vector_indexes[0], {**vector_indexes[1], 'dimensions': 5}]
            code, outcome = apply_index_cli(wrong)
            assert code == 1 and outcome['code'] == 'vector_index_not_declared'
            assert hnsw_count() == 0
            altered = load_contract(vector_path, vector_contract['sha256'])
            for row in altered['catalog']['indexes']:
                if row[1] == vector_cli.index_name('b' * 64):
                    row[-1] = row[-1].replace('vector_cosine_ops', 'vector_l2_ops')
            altered_path = slot / 'wrong-index-definition.json'
            altered_path.write_text(json.dumps(altered), encoding='utf-8')
            attempted = []
            def observe_creation(_c, _cu, statement, _p, _ctx, _many):
                if statement.startswith('CREATE INDEX ix_embedding_hnsw_'):
                    attempted.append(statement.split()[2])
            event.listen(Engine, 'before_cursor_execute', observe_creation)
            try:
                code, outcome = apply_index_cli(vector_indexes, approved_path=altered_path,
                    approved_sha256=hashlib.sha256(altered_path.read_bytes()).hexdigest())
            finally:
                event.remove(Engine, 'before_cursor_execute', observe_creation)
            assert code == 1 and outcome['code'] == 'schema_contract_mismatch'
            assert len(attempted) == 2
            assert hnsw_count() == 0
            record(STEP)

            STEP = 'vector_owner_cli_declared_indexes_and_idempotency'
            code, outcome = apply_index_cli(vector_indexes)
            assert code == 0 and outcome['created'] == 2 and outcome['existing'] == 0
            code, outcome = apply_index_cli(vector_indexes)
            assert code == 0 and outcome['created'] == 0 and outcome['existing'] == 2
            verify_schema(index_owner, vector_path, vector_contract['sha256'])
            grants(index_owner, index_target)
            record(STEP)

            STEP = 'vector_runtime_approved_index_check_is_select_only'
            runtime_index_db = Database(url(index_target, limited=True).render_as_string(hide_password=False),
                schema_contract=vector_path, schema_sha256=vector_contract['sha256'])
            try:
                runtime_index_db.initialize()
                statements = []
                def observe_index(_c, _cu, statement, _p, _ctx, _many):
                    statements.append(statement.lstrip().split(None, 1)[0].upper())
                event.listen(runtime_index_db.engine, 'before_cursor_execute', observe_index)
                with runtime_index_db.sessions() as session:
                    ensure_hnsw(session, SimpleNamespace(model_space='a' * 64, dimensions=3))
                event.remove(runtime_index_db.engine, 'before_cursor_execute', observe_index)
                assert statements and set(statements) == {'SELECT'}
                record(STEP)

                STEP = 'vector_runtime_maintenance_and_index_ddl_are_rejected'
                refused('vector_index_owner_required', lambda: vector_cli.maintain_indexes(
                    runtime_index_db.engine, vector_path, vector_contract['sha256'], vector_indexes))
                with runtime_index_db.engine.connect() as connection:
                    try:
                        connection.exec_driver_sql('CREATE INDEX forbidden_vector_index ON public.embedding_vectors(dimensions)')
                    except Exception as error:
                        assert getattr(getattr(error, 'orig', None), 'sqlstate', None) == '42501'
                    else:
                        raise AssertionError('runtime_index_ddl_present')
                    finally:
                        connection.rollback()
                record(STEP)

                STEP = 'vector_changed_index_rejected_by_runtime_and_owner_preflight'
                name = vector_cli.index_name('a' * 64)
                with index_owner.begin() as connection:
                    connection.exec_driver_sql('DROP INDEX public.' + name)
                    connection.exec_driver_sql('CREATE INDEX ' + name + ' ON public.embedding_vectors(dimensions)')
                with runtime_index_db.sessions() as session:
                    from fastapi import HTTPException
                    try:
                        ensure_hnsw(session, SimpleNamespace(model_space='a' * 64, dimensions=3))
                    except HTTPException as error:
                        assert error.status_code == 503 and error.detail['code'] == 'pgvector_index_maintenance_required'
                    else:
                        raise AssertionError('runtime_changed_index_accepted')
                code, outcome = apply_index_cli(vector_indexes)
                assert code == 1 and outcome['code'] == 'schema_contract_mismatch'
                refused('schema_contract_mismatch', runtime_index_db.initialize)
                with index_owner.begin() as connection:
                    connection.exec_driver_sql('DROP INDEX public.' + name)
                code, outcome = apply_index_cli(vector_indexes)
                assert code == 0 and outcome['created'] == 1
                runtime_index_db.initialize()
                record(STEP)
            finally:
                runtime_index_db.close()
        finally:
            index_owner.dispose()

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
