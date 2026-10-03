"""Opt-in private PG41 acceptance; synthetic sources and real independent writers."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from unittest.mock import patch
from uuid import uuid4

from identity_contract_postgres_acceptance import file_hashes, fingerprints, public_fingerprints

ROOT = Path(__file__).resolve().parents[1]
REPORT = {'status': 'running', 'scope': 'synthetic_source_settings_private_postgresql', 'checks': []}
STEP = 'isolation'


def record(name):
    REPORT['checks'].append(name)
    print(json.dumps({'check': name, 'status': 'passed'}), flush=True)


def guards():
    run_root = Path(os.environ['TIRE_PG_RUN_ROOT']).resolve()
    assert run_root.parent == (ROOT / '.artifacts/runtime').resolve()
    assert run_root.name.startswith('round41-source-settings-PG-')
    assert Path(os.environ['TIRE_PG_TEST_DATA']).resolve() == run_root / 'data'
    assert int(os.environ['TIRE_PG_TEST_PORT']) == 55441
    assert Path(os.environ['TIRE_PG_TEST_REPORT']).resolve() == run_root / 'report.json'
    assert os.environ['TI_AI_ENABLED'] == os.environ['TI_EMBEDDINGS_ENABLED'] == '0'
    assert os.environ.get('TI_DISABLED_SOURCES', '') == ''
    assert os.environ['TI_OBJECT_STORE_BACKEND'] == 'filesystem'
    assert Path(os.environ['TI_OBJECT_STORE_ROOT']).resolve() == run_root / 'objects'
    assert Path(os.environ['TI_PARSER_BUNDLE_ROOT']).resolve() == run_root / 'bundles'
    guard = 'sqlite:///' + (run_root / 'import-guard.sqlite').as_posix()
    assert os.environ['TIRE_DATABASE_URL'] == os.environ['DATABASE_URL'] == guard
    assert Path(os.environ['TIRE_PG_BIN']).resolve() == Path('E:/PostgreSQL/18/bin').resolve()
    sys.path.insert(0, str(ROOT / 'apps/api'))
    sys.path.insert(0, str(ROOT / 'apps/api/tests'))
    return run_root


def safe_failure(error):
    import traceback
    return {'error_type': type(error).__name__, 'frames': [
        {'file': Path(frame.filename).name, 'line': frame.lineno}
        for frame in traceback.extract_tb(error.__traceback__)
        if Path(frame.filename).resolve().is_relative_to(ROOT)]}


def writer(name):
    """A new Python process owns a new DB engine and its own transaction."""
    run_root = guards()
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,79}', name)
    request = json.loads((run_root / f'{name}.request.json').read_text(encoding='utf-8'))
    group = request['group']
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,79}', group)
    from sqlalchemy.engine import make_url
    from tire_api.db import Database
    from tire_api.source_settings import SourceSettingDecision, SourceSettingError, append_source_setting
    url = os.environ['TIRE_PG_APP_URL']
    parsed = make_url(url)
    assert parsed.get_backend_name() == 'postgresql' and parsed.host == '127.0.0.1' and parsed.port == 55441
    assert parsed.database.startswith('source_settings_')
    database = Database(url)
    outcome = {'pid': os.getpid(), 'parent_pid': os.getppid(), 'status': 'running'}
    code = 0
    try:
        with database.sessions() as db:
            # Establish an independent backend connection before the common gate.
            backend_pid = db.connection().exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
            db.commit()
            ready = run_root / f'{name}.ready.tmp'
            ready.write_text(json.dumps({'pid': os.getpid(), 'backend_pid': backend_pid}), encoding='utf-8')
            ready.replace(run_root / f'{name}.ready.json')
            deadline = time.monotonic() + 30
            while not (run_root / f'{group}.go').is_file():
                assert time.monotonic() < deadline, 'writer_start_gate_timeout'
                time.sleep(0.01)
            try:
                value = append_source_setting(db, request['source_id'],
                    SourceSettingDecision.model_validate(request['payload']), request['actor'], request['key'])
                outcome.update(status='accepted', status_code=201, result=value, backend_pid=backend_pid)
            except SourceSettingError as error:
                db.rollback()
                outcome.update(status='rejected', status_code=error.status_code, code=error.code, backend_pid=backend_pid)
    except Exception as error:
        code = 1
        outcome.update(status='failed', **safe_failure(error))
    finally:
        database.close()
        (run_root / f'{name}.result.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding='utf-8')
    return code


def run():
    global STEP
    run_root = guards()
    import psycopg
    from psycopg import sql
    from sqlalchemy import func, inspect, select, text, update
    from sqlalchemy.engine import URL
    from fastapi.testclient import TestClient
    from tire_api.adapters import registry as official_registry
    from tire_api.captures import checked_capture_bytes
    from tire_api.db import Base, Database, FallbackConsent, QueryRun, RawCapture, UserSession, utcnow
    from tire_api.ai_models import AIRequest
    from tire_api.embedding_models import EmbeddingRequest
    from tire_api.main import create_app
    from tire_api.service import QueryService
    from tire_api.source_setting_models import SourceSettingRevision
    from tire_api.source_settings import (SourceAccessBlocked, SourceSettingDecision, SourceSettingPreview,
        append_source_setting, assert_source_run_access, current_setting, preview_source_setting, source_setting)
    from test_core import grant
    from test_source_access import (RecordingRegistry, RecordingVehicle, RecallFixture, SearchFixture,
        accepted_counts, assert_blocked, change_source, request_lane, source_id, set_offline)

    class Registry(RecordingRegistry):
        def sources(self):
            synthetic = [row for row in super().sources() if row['id'] not in
                         {item['id'] for item in official_registry.sources()}]
            return synthetic + official_registry.sources()

    admin = psycopg.connect(host='127.0.0.1', port=55441, user='tire_source_settings_admin',
        password=os.environ['TIRE_PG_TEST_PASSWORD'], dbname='postgres', autocommit=True, connect_timeout=5)
    database = restored = None
    try:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == run_root / 'data'
        REPORT['postgres_version'] = admin.execute('SHOW server_version').fetchone()[0]
        assert REPORT['postgres_version'].split('.')[0] == '18'
        role, password = 'source_settings_app_' + uuid4().hex[:10], secrets.token_hex(32)
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION').format(
            sql.Identifier(role), sql.Literal(password)))

        def new_database(name):
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(role)))
            return URL.create('postgresql+psycopg', username=role, password=password,
                host='127.0.0.1', port=55441, database=name).render_as_string(hide_password=False)

        name = 'source_settings_' + uuid4().hex[:10]
        url = new_database(name)
        database = Database(url)
        database.initialize()
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT current_user').scalar_one() == role
            assert connection.execute(text('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication '
                'FROM pg_roles WHERE rolname = current_user')).scalar_one() is False
        record('private_pg18_non_superuser_application_role')

        STEP = 'synthetic_legacy_migration'
        with database.sessions() as db:
            db.add(UserSession(id='synthetic-legacy-session', expires_at=utcnow() + timedelta(days=1)))
            db.flush()
            db.add(QueryRun(id='synthetic-legacy-query', session_id='synthetic-legacy-session', source_id='michelin-fr',
                query_key='a' * 64, query={'model': 'Synthetic prior query'}, fallback_policy='ask', state='consent_required'))
            db.commit()
        with database.engine.begin() as connection:
            # Reconstruct pre-006 structure only in this fresh private fixture DB.
            connection.exec_driver_sql('DROP TABLE source_setting_revisions')
            connection.exec_driver_sql('ALTER TABLE query_runs DROP COLUMN source_access_generation')
            connection.execute(text("DELETE FROM tire_schema_versions WHERE version = '006_source_settings'"))
            old_versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
            old_columns = [item['name'] for item in inspect(connection).get_columns('query_runs')]
            old_queries = [dict(row) for row in connection.execute(text('SELECT * FROM query_runs')).mappings()]
            old_tables = set(inspect(connection).get_table_names())
        database.initialize()
        database.initialize()
        with database.engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == old_tables | {'source_setting_revisions'}
            quoted = ','.join('"' + column + '"' for column in old_columns)
            assert [dict(row) for row in connection.execute(text('SELECT ' + quoted + ' FROM query_runs')).mappings()] == old_queries
            versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
            assert versions == old_versions | {'006_source_settings'}
        with database.sessions() as db:
            legacy = db.get(QueryRun, 'synthetic-legacy-query')
            assert legacy.source_access_generation is None
            assert db.scalar(select(func.count()).select_from(SourceSettingRevision)) == 0
            try:
                assert_source_run_access(db, legacy)
                raise AssertionError('legacy_null_pin_was_accepted')
            except SourceAccessBlocked as error:
                assert error.code == 'source_access_pin_missing'
        record('migration_006_adds_one_table_one_nullable_column_preserves_old_values_and_null')

        def decision(source, action='pause', *, notes=None):
            values = {'action': action, **({'notes': notes} if notes is not None else {})}
            with database.sessions() as db:
                preview = preview_source_setting(db, source, SourceSettingPreview(**values))
            return {**values, 'expected_revision': preview['revision'], 'expected_fingerprint': preview['fingerprint'],
                    'operator': 'Synthetic PG operator', 'reason': 'Synthetic private PG source settings check'}

        def apply(source, action, *, notes=None):
            payload = SourceSettingDecision.model_validate(decision(source, action, notes=notes))
            with database.sessions() as db:
                return append_source_setting(db, source, payload, 'synthetic-pg-parent', str(uuid4()))

        processes_observed = []

        def two_writers(group, requests):
            child_env = {**os.environ, 'TIRE_PG_APP_URL': url}
            children, logs, names = [], [], []
            try:
                for suffix, request in zip(('a', 'b'), requests, strict=True):
                    task = group + '-' + suffix
                    names.append(task)
                    (run_root / f'{task}.request.json').write_text(json.dumps({**request, 'group': group}), encoding='utf-8')
                    log = (run_root / f'{task}.log').open('wb')
                    logs.append(log)
                    children.append(subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--writer', task],
                        env=child_env, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT))
                deadline = time.monotonic() + 30
                while not all((run_root / f'{task}.ready.json').is_file() for task in names):
                    assert all(child.poll() is None for child in children), 'writer_died_before_common_gate'
                    assert time.monotonic() < deadline, 'writers_not_ready'
                    time.sleep(0.02)
                readiness = [json.loads((run_root / f'{task}.ready.json').read_text()) for task in names]
                assert len({row['pid'] for row in readiness}) == len({row['backend_pid'] for row in readiness}) == 2
                assert all(row['pid'] != os.getpid() for row in readiness)
                (run_root / f'{group}.go').write_text('begin', encoding='utf-8')
                for child in children:
                    assert child.wait(timeout=35) == 0, 'writer_process_failed'
                results = [json.loads((run_root / f'{task}.result.json').read_text(encoding='utf-8')) for task in names]
                processes_observed.extend({'scenario': group, **row} for row in readiness)
                return results
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.wait(timeout=10)
                for log in logs:
                    log.close()

        STEP = 'independent_revision_writers'
        payload = decision('michelin-us')
        results = two_writers('revision-race', [{'source_id': 'michelin-us', 'payload': payload,
            'actor': 'synthetic-writer-' + suffix, 'key': str(uuid4())} for suffix in ('a', 'b')])
        assert sorted(row['status_code'] for row in results) == [201, 409]
        assert next(row for row in results if row['status_code'] == 409)['code'] == 'source_setting_revision_conflict'
        with database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(SourceSettingRevision).where(
                SourceSettingRevision.source_id == 'michelin-us')) == 1
        record('two_independent_processes_same_revision_one_event_other_409')

        STEP = 'independent_idempotent_writers'
        payload, key = decision('michelin-uk'), str(uuid4())
        request = {'source_id': 'michelin-uk', 'payload': payload, 'actor': 'synthetic-idempotent-actor', 'key': key}
        repeated = two_writers('uuid-race', [request, request])
        assert all(row['status_code'] == 201 for row in repeated)
        assert sorted(row['result']['replayed'] for row in repeated) == [False, True]
        original_event = repeated[0]['result']['event']
        assert original_event == repeated[1]['result']['event']
        apply('michelin-uk', 'enable')
        replayed = two_writers('uuid-later-replay', [request, request])
        assert all(row['result']['replayed'] and row['result']['event'] == original_event for row in replayed)
        assert all(row['result']['source']['management']['revision'] == 2 for row in replayed)
        with database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(SourceSettingRevision).where(
                SourceSettingRevision.source_id == 'michelin-uk')) == 2
        record('same_uuid_actor_across_processes_replays_original_event_without_duplicates')

        STEP = 'stale_session_cache'
        cached_event = apply('michelin-de', 'edit_notes', notes='Synthetic cached management row')['event']
        with database.sessions() as db:
            db.add(QueryRun(id='synthetic-cached-query', session_id='synthetic-legacy-session', source_id='michelin-de',
                query_key='b' * 64, query={'model': 'Synthetic cached request'}, fallback_policy='ask', source_access_generation=0))
            db.commit()
        with database.sessions() as stale:
            stale_row = stale.get(SourceSettingRevision, cached_event['id'])
            stale_run = stale.get(QueryRun, 'synthetic-cached-query')
            assert stale_row.access_generation == stale_run.source_access_generation == 0
            stale.commit()  # expire_on_commit=False deliberately preserves the old identity-map objects.
            apply('michelin-de', 'pause')
            QueryService(stale, None).lock_ingestion()
            assert current_setting(stale, 'michelin-de')['access_generation'] == 1
            try:
                assert_source_run_access(stale, stale_run)
                raise AssertionError('stale_session_accepted_old_generation')
            except SourceAccessBlocked as error:
                assert error.code == 'source_access_changed'
            stale.rollback()
        record('second_session_with_cached_old_objects_sees_new_generation_under_common_lock')

        registry = Registry()
        app = create_app(url, registry)
        adapters = {'tire': registry, 'vehicle': RecordingVehicle(), 'recall': RecallFixture(), 'search': SearchFixture()}
        app.state.vehicle_adapter = adapters['vehicle']
        database.close()
        database = None
        lane_reports = []
        with TestClient(app) as client:
            database = app.state.database
            env = (client, app, adapters)
            client.get('/v1/source-settings')
            # A distinct HTTP client has a distinct local session, observing the same DB workspace.
            with TestClient(create_app(url, Registry())) as other_client:
                visible = other_client.get('/v1/source-settings/michelin-us')
                assert visible.status_code == 200 and visible.json()['management']['state'] == 'paused'
                visible = other_client.get('/v1/source-settings/michelin-uk')
                assert visible.json()['management']['revision'] == 2 and visible.json()['management']['state'] == 'enabled'
            record('independent_http_session_reads_committed_workspace_settings')

            def count(model):
                with database.sessions() as db:
                    return db.scalar(select(func.count()).select_from(model))

            def enable(lane):
                with database.sessions() as db:
                    state = current_setting(db, source_id(lane))['state']
                if state == 'archived':
                    change_source(env, lane, 'restore')
                    state = 'paused'
                if state == 'paused':
                    change_source(env, lane, 'enable')

            for lane in ('tire', 'vehicle', 'recall', 'search'):
                STEP = 'management_lane_' + lane
                enable(lane)
                before, captures = accepted_counts(database), count(RawCapture)
                calls = len(adapters[lane].calls)
                change_source(env, lane, 'pause')
                blocked = assert_blocked(request_lane(env, lane), 'source_paused')
                assert len(adapters[lane].calls) == calls and accepted_counts(database) == before
                assert count(RawCapture) == captures
                assert grant(client, blocked['query_id']).status_code == 409
                enable(lane)
                original_fetch = adapters[lane].fetch

                async def aba_fetch(*args, **kwargs):
                    result = await original_fetch(*args, **kwargs)
                    change_source(env, lane, 'pause')
                    change_source(env, lane, 'enable')
                    return result

                with patch.object(adapters[lane], 'fetch', aba_fetch):
                    assert_blocked(request_lane(env, lane), 'source_access_changed')
                assert accepted_counts(database) == before and count(RawCapture) == captures + 1

                async def notes_fetch(*args, **kwargs):
                    result = await original_fetch(*args, **kwargs)
                    change_source(env, lane, 'edit_notes', 'Synthetic PG notes for ' + lane)
                    return result

                with patch.object(adapters[lane], 'fetch', notes_fetch):
                    live = request_lane(env, lane)
                assert live.status_code == 200 and live.json()['data_state'] == 'live'
                assert accepted_counts(database) != before and count(RawCapture) == captures + 2
                accepted = accepted_counts(database)
                saved_result = deepcopy(adapters[lane].result) if lane in {'tire', 'vehicle'} else None
                set_offline(env, lane)
                pending = request_lane(env, lane).json()
                assert pending['data_state'] == 'consent_required'
                granted = grant(client, pending['query_id'])
                assert granted.status_code == 201
                consent_id = granted.json()['id']
                change_source(env, lane, 'pause')
                change_source(env, lane, 'enable')
                assert_blocked(request_lane(env, lane, consent_id=consent_id), 'source_access_changed')
                with database.sessions() as db:
                    assert db.get(FallbackConsent, consent_id).used_at is None
                assert accepted_counts(database) == accepted
                if saved_result is not None:
                    adapters[lane].result = saved_result
                else:
                    adapters[lane].offline = False
                lane_reports.append({'lane': lane, 'preflight_fetches': 0, 'aba_accepted_rows_added': 0,
                    'aba_raw_captures_added': 1, 'notes_allowed_live': True, 'stale_consent_unused': True})
                record(lane + '_preflight_block_aba_raw_retention_notes_and_consent_fence')

            STEP = 'legacy_null_consent_and_read_only_projection'
            set_offline(env, 'tire')
            pending = request_lane(env, 'tire').json()
            with database.sessions() as db:
                db.execute(update(QueryRun).where(QueryRun.id == pending['query_id']).values(source_access_generation=None))
                db.commit()
            rejected = grant(client, pending['query_id'])
            assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'source_access_pin_missing'
            before_reads = fingerprints(database, Base.metadata)
            expected_sources = {source: client.get('/v1/source-settings/' + source).json() for source in
                ('michelin-us', 'michelin-uk', 'michelin-de', 'fixture', source_id('vehicle'), source_id('recall'), 'eprel')}
            expected_history = {source: client.get('/v1/source-settings/' + source + '/history?limit=100').json()
                                for source in expected_sources}
            assert client.post('/v1/source-settings/fixture/preview', json={'action': 'pause'}).status_code == 200
            assert fingerprints(database, Base.metadata) == before_reads
            assert expected_sources['eprel']['effective_status'] == 'configuration_required'
            with database.sessions() as db:
                captures = [(row.id, row.raw_hash) for row in db.scalars(select(RawCapture))]
                for capture_id, raw_hash in captures:
                    body, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                    assert location == 'object_store' and hashlib.sha256(body).hexdigest() == raw_hash
                assert db.scalar(select(func.count()).select_from(AIRequest)) == 0
                assert db.scalar(select(func.count()).select_from(EmbeddingRequest)) == 0
                null_pins = db.scalar(select(func.count()).select_from(QueryRun).where(QueryRun.source_access_generation.is_(None)))
                revision_count = db.scalar(select(func.count()).select_from(SourceSettingRevision))
            frozen_rows = fingerprints(database, Base.metadata)
            record('legacy_null_consent_rejected_and_setting_reads_do_not_mutate_registered_rows')

        database = None
        STEP = 'dump_restore'
        restore_name = 'restored_source_settings_' + uuid4().hex[:10]
        restored_url = new_database(restore_name)
        pg_bin = Path(os.environ['TIRE_PG_BIN'])
        archive = run_root / 'source-settings.dump'
        child_env = {**os.environ, 'PGHOST': '127.0.0.1', 'PGPORT': '55441', 'PGUSER': role, 'PGPASSWORD': password}
        for command in (
            [str(pg_bin / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-acl', '--no-password',
                '--dbname', name, '--file', str(archive)],
            [str(pg_bin / 'pg_restore.exe'), '--exit-on-error', '--no-owner', '--no-acl', '--no-password',
                '--dbname', restore_name, str(archive)],
        ):
            assert subprocess.run(command, env=child_env, capture_output=True, timeout=60).returncode == 0, 'dump_restore_failed'
        object_root, destination = run_root / 'objects', run_root / 'restored-objects'
        assert not destination.exists()
        object_hashes = file_hashes(object_root)
        assert object_hashes
        shutil.copytree(object_root, destination)
        assert file_hashes(destination) == object_hashes
        os.environ['TI_OBJECT_STORE_ROOT'] = str(destination)
        restored = Database(restored_url)
        restored.initialize()
        restored_rows = fingerprints(restored, Base.metadata)
        assert restored_rows == frozen_rows
        with restored.sessions() as db:
            assert set(db.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == versions
            for capture_id, raw_hash in captures:
                body, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                assert location == 'object_store' and hashlib.sha256(body).hexdigest() == raw_hash
            assert db.get(QueryRun, 'synthetic-legacy-query').source_access_generation is None
        restored.close()
        restored = None
        record('dump_restore_all_base_columns_values_schema_versions_and_object_hashes')

        STEP = 'restored_management_semantics'
        with TestClient(create_app(restored_url, Registry())) as restored_client:
            for source, expected in expected_sources.items():
                assert restored_client.get('/v1/source-settings/' + source).json() == expected
                assert restored_client.get('/v1/source-settings/' + source + '/history?limit=100').json() == expected_history[source]
            with restored_client.app.state.database.sessions() as db:
                value = append_source_setting(db, request['source_id'], SourceSettingDecision.model_validate(request['payload']),
                    request['actor'], request['key'])
                assert value['replayed'] and value['event'] == original_event
        record('restored_settings_history_null_pins_and_original_idempotent_event_are_identical')
        assert not (run_root / 'import-guard.sqlite').exists()
        REPORT.update(status='passed', process_evidence=processes_observed, independent_writer_processes=len(processes_observed),
            lane_checks=lane_reports, tables_checked=len(frozen_rows),
            columns_checked=sum(len(value['columns']) for value in frozen_rows.values()),
            schema_versions=sorted(versions), schema_migrations_added=1, migration='006_source_settings',
            source_setting_revisions=revision_count, null_query_pin_count=null_pins, legacy_null_query_preserved=True,
            table_fingerprints=public_fingerprints(frozen_rows), restore_table_fingerprints=public_fingerprints(restored_rows),
            capture_count=len(captures), object_file_count=len(object_hashes), object_hashes=object_hashes,
            copied_object_hashes=file_hashes(destination), archive_bytes=archive.stat().st_size,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            synthetic_source_calls=sum(len(adapter.calls) for adapter in adapters.values()),
            real_source_calls=0, real_parser_children=0, real_ai_calls=0, real_embedding_calls=0, normal_database_used=False,
            fingerprint_scope='All Base.metadata registered columns and values, schema versions and copied object files; '
                'not database roles, ACL or cross-host recovery')
    finally:
        if database is not None:
            database.close()
        if restored is not None:
            restored.close()
        admin.close()


def guarded_run():
    # Enforce the advertised acceptance boundary; only PostgreSQL uses sockets.
    # Imports happen after the same private environment guard as the main run.
    guards()
    from tire_api.adapters.transport import SafeHttpClient
    from tire_api import parser_runtime
    with patch.object(SafeHttpClient, '_request', side_effect=AssertionError('real_source_transport_forbidden')) as transport, \
            patch.object(parser_runtime, '_run_sync', side_effect=AssertionError('real_parser_execution_forbidden')) as parser:
        run()
        assert transport.call_count == parser.call_count == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run-private-postgres', action='store_true')
    mode.add_argument('--writer')
    arguments = parser.parse_args()
    if arguments.writer:
        try:
            return writer(arguments.writer)
        except Exception as error:
            # Even setup failures must not expose connection strings or raw SQL.
            print(json.dumps({'status': 'failed', **safe_failure(error)}), flush=True)
            return 1
    code = 0
    try:
        guarded_run()
    except Exception as error:
        code = 1
        REPORT.update(status='failed', failure_step=STEP, **safe_failure(error))
    report = Path(os.environ['TIRE_PG_TEST_REPORT']).resolve()
    assert report.name == 'report.json' and report.parent.parent == (ROOT / '.artifacts/runtime').resolve()
    assert report.parent.name.startswith('round41-source-settings-PG-')
    report.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: REPORT[key] for key in ('status', 'scope', 'checks')}), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
