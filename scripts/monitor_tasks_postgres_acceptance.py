"""Opt-in PG42 monitor journal acceptance with real independent private writers.

Run only through round42-verify-monitor-tasks-postgres.ps1 after the parent grants
the exclusive execution window. Sources are synthetic; no Parser/model/network
source transport or normal database is permitted.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import timedelta
import hashlib
import importlib.util
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
from uuid import UUID, uuid4

from identity_contract_postgres_acceptance import file_hashes, fingerprints, public_fingerprints

ROOT = Path(__file__).resolve().parents[1]
REPORT = {'status': 'running', 'scope': 'synthetic_monitor_tasks_private_postgresql', 'checks': []}
STEP = 'isolation'


def record(name):
    REPORT['checks'].append(name)
    print(json.dumps({'check': name, 'status': 'passed'}), flush=True)


def guards():
    run_root = Path(os.environ['TIRE_PG_RUN_ROOT']).resolve()
    assert run_root.parent == (ROOT / '.artifacts/runtime').resolve()
    assert run_root.name.startswith('round42-monitor-tasks-PG-')
    assert Path(os.environ['TIRE_PG_TEST_DATA']).resolve() == run_root / 'data'
    assert int(os.environ['TIRE_PG_TEST_PORT']) == 55442
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


def save_atomic(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def wait_gate(path, timeout=45):
    deadline = time.monotonic() + timeout
    while not path.is_file():
        assert time.monotonic() < deadline, 'private_writer_gate_timeout'
        time.sleep(0.01)


def writer(name):
    """Retain the claim credential only in this independent process's memory."""
    run_root = guards()
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,79}', name)
    request = json.loads((run_root / f'{name}.request.json').read_text(encoding='utf-8'))
    group, kind = request['group'], request['kind']
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,79}', group)
    assert kind in {'tire', 'recall'} and request['finish_mode'] in {'synthetic', 'stale'}
    from sqlalchemy.engine import make_url
    from tire_api import monitoring, recall_monitoring
    from tire_api.db import Database, UserSession, utcnow
    from tire_api.domain import LiveQueryRequest
    from tire_api.recall_models import RecallLiveRequest
    from tire_api.recalls import RecallService
    from tire_api.service import QueryService
    from test_source_access import RecordingRegistry, RecallFixture
    url = os.environ['TIRE_PG_APP_URL']
    parsed = make_url(url)
    assert parsed.get_backend_name() == 'postgresql' and parsed.host == '127.0.0.1' and parsed.port == 55442
    assert parsed.database.startswith('monitor_tasks_')
    spec = importlib.util.spec_from_file_location('pg42_worker', ROOT / 'apps/worker/monitor.py')
    monitor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitor)
    database = Database(url)
    queue = monitoring if kind == 'tire' else recall_monitoring
    outcome = {'pid': os.getpid(), 'parent_pid': os.getppid(), 'kind': kind, 'status': 'running'}
    code = 0
    try:
        with database.sessions() as db:
            backend_pid = db.connection().exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
            db.commit()
        outcome['backend_pid'] = backend_pid
        save_atomic(run_root / f'{name}.ready.json', {'pid': os.getpid(), 'backend_pid': backend_pid})
        wait_gate(run_root / f'{group}.go')
        claim = queue.claim_job(database)
        if claim is None:
            outcome.update(status='idle')
            save_atomic(run_root / f'{name}.claim.json', outcome)
        else:
            monitor.begin_attempt(database, claim, queue.guard_claim)
            outcome.update(status='claimed', job_id=claim['id'], attempt_id=claim['attempt_id'])
            save_atomic(run_root / f'{name}.claim.json', outcome)
            wait_gate(run_root / f'{name}.finish.go')
            query_id = None
            if request['finish_mode'] == 'synthetic':
                if kind == 'tire':
                    with database.sessions() as db:
                        QueryService(db, None).lock_ingestion()
                        if db.get(UserSession, 'synthetic-pg42-worker') is None:
                            db.add(UserSession(id='synthetic-pg42-worker', expires_at=utcnow() + timedelta(days=1)))
                        db.commit()
                        result = asyncio.run(QueryService(db, RecordingRegistry(),
                            ingestion_guard=lambda session: queue.guard_claim(session, claim)).execute('fixture',
                                LiveQueryRequest(query=claim['query'], fallback_policy='never'), 'synthetic-pg42-worker'))
                else:
                    with database.sessions() as db:
                        result = asyncio.run(RecallService(db, RecallFixture(),
                            ingestion_guard=lambda session: queue.guard_claim(session, claim)).execute(
                                RecallLiveRequest(query=claim['query'], fallback_policy='never'), claim['session_id']))
                state, reason, query_id = result['data_state'], result.get('reason'), result['query_id']
                assert state == 'live', 'synthetic_query_was_not_live'
            else:
                state, reason = 'live', None
            finalized = queue.finish_job(database, claim, state, reason, query_id=query_id)
            outcome.update(status='finished', finalized=finalized, result_state=state, query_id=query_id)
    except Exception as error:
        code = 1
        outcome.update(status='failed', **safe_failure(error))
    finally:
        database.close()
        save_atomic(run_root / f'{name}.result.json', outcome)
    return code


class Writers:
    def __init__(self, run_root, url):
        self.root, self.url, self.children, self.logs, self.evidence = run_root, url, {}, {}, []

    def start(self, group, kind, *, count=2, finish_mode='synthetic'):
        child_env = {**os.environ, 'TIRE_PG_APP_URL': self.url}
        child_env.pop('TIRE_PG_TEST_PASSWORD', None)
        names = [f'{group}-{index}' for index in range(count)]
        for name in names:
            save_atomic(self.root / f'{name}.request.json', {'group': group, 'kind': kind, 'finish_mode': finish_mode})
            log = (self.root / f'{name}.log').open('wb')
            self.logs[name] = log
            self.children[name] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--writer', name],
                env=child_env, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        ready = self.collect(names, 'ready')
        assert len({row['pid'] for row in ready}) == len({row['backend_pid'] for row in ready}) == count
        assert all(row['pid'] != os.getpid() for row in ready)
        self.evidence.extend({'scenario': group, **row} for row in ready)
        (self.root / f'{group}.go').write_text('begin', encoding='utf-8')
        outcomes = self.collect(names, 'claim')
        assert sum(row['status'] == 'claimed' for row in outcomes) == 1, 'claim_did_not_have_exactly_one_winner'
        assert sum(row['status'] == 'idle' for row in outcomes) == count - 1
        winner = next(name for name, row in zip(names, outcomes, strict=True) if row['status'] == 'claimed')
        for name, row in zip(names, outcomes, strict=True):
            if row['status'] == 'idle':
                assert self.children[name].wait(timeout=10) == 0
        return winner, next(row for row in outcomes if row['status'] == 'claimed')

    def collect(self, names, suffix):
        deadline = time.monotonic() + 40
        paths = [self.root / f'{name}.{suffix}.json' for name in names]
        while not all(path.is_file() for path in paths):
            assert all(path.is_file() or self.children[name].poll() is None
                       for name, path in zip(names, paths, strict=True)), 'writer_died_before_receipt'
            assert time.monotonic() < deadline, 'writer_receipt_timeout'
            time.sleep(0.02)
        return [json.loads(path.read_text(encoding='utf-8')) for path in paths]

    def finish(self, name):
        (self.root / f'{name}.finish.go').write_text('finish', encoding='utf-8')
        assert self.children[name].wait(timeout=45) == 0, 'writer_failed_at_completion'
        result, = self.collect([name], 'result')
        return result

    def close(self):
        for name, process in self.children.items():
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            self.logs[name].close()
        REPORT['writer_processes_reaped'] = all(process.poll() is not None for process in self.children.values())
        REPORT['writer_exit_codes'] = {name: process.returncode for name, process in self.children.items()}
        REPORT['process_evidence'] = self.evidence
        REPORT['independent_writer_processes'] = len(self.children)


def strip_clock(value):
    return {key: item for key, item in value.items() if key != 'server_time'}


def stream_rows(client, path, cursor):
    from tire_api import monitor_tasks
    with patch.object(monitor_tasks, 'STREAM_SECONDS', 0.06), patch.object(monitor_tasks, 'POLL_SECONDS', 0.005):
        response = client.get(path + '/events/stream', headers={'Last-Event-ID': cursor})
    assert response.status_code == 200
    rows = []
    for frame in response.text.split('\n\n'):
        if 'event: task_event\n' in frame:
            lines = frame.splitlines()
            data = json.loads(next(line[6:] for line in lines if line.startswith('data: ')))
            assert next(line[4:] for line in lines if line.startswith('id: ')) == data['cursor']
            rows.append(data)
    assert 'event: stream_end' in response.text
    return rows


def run():
    global STEP
    run_root = guards()
    import psycopg
    from psycopg import sql
    from fastapi.testclient import TestClient
    from sqlalchemy import func, inspect, select, text
    from sqlalchemy.engine import URL
    from tire_api.db import Base, Database, MonitorJob, MonitorRun, QueryRun, RawCapture, uid, utcnow
    from tire_api.ai_models import AIRequest
    from tire_api.embedding_models import EmbeddingRequest
    from tire_api.captures import checked_capture_bytes
    from tire_api.main import SESSION_COOKIE, create_app
    from tire_api.monitor_task_models import MonitorTaskAttempt, MonitorTaskEvent
    from tire_api.recall_models import RecallMonitorJob, RecallMonitorRun
    from test_core import QUERY
    from test_recalls import CAMPAIGN
    from test_source_access import RecordingRegistry

    admin = psycopg.connect(host='127.0.0.1', port=55442, user='tire_monitor_tasks_admin',
        password=os.environ['TIRE_PG_TEST_PASSWORD'], dbname='postgres', autocommit=True, connect_timeout=5)
    database = restored = writers = None
    try:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == run_root / 'data'
        REPORT['postgres_version'] = admin.execute('SHOW server_version').fetchone()[0]
        REPORT['parent_pid'] = os.getpid()
        REPORT['admin_backend_pid'] = admin.execute('SELECT pg_backend_pid()').fetchone()[0]
        REPORT['postmaster_pid'] = int((run_root / 'data/postmaster.pid').read_text().splitlines()[0])
        assert REPORT['postgres_version'] == '18.3'
        role, password = 'monitor_tasks_app_' + uuid4().hex[:10], secrets.token_hex(32)
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION').format(
            sql.Identifier(role), sql.Literal(password)))

        def new_database(name):
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(role)))
            return URL.create('postgresql+psycopg', username=role, password=password,
                host='127.0.0.1', port=55442, database=name).render_as_string(hide_password=False)

        name = 'monitor_tasks_' + uuid4().hex[:10]
        url = new_database(name)
        database = Database(url)
        database.initialize()
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT current_user').scalar_one() == role
            assert connection.execute(text('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication '
                'FROM pg_roles WHERE rolname = current_user')).scalar_one() is False
        record('private_pg18_3_non_superuser_role_and_owned_loopback_cluster')
        database.close()
        database = None

        app = create_app(url, RecordingRegistry())
        other_app = create_app(url, RecordingRegistry())
        lane_reports, cursors, expected_details, expected_events = [], {}, {}, {}
        with TestClient(app) as client, TestClient(other_app) as stranger:
            database = app.state.database
            client.get('/health')
            stranger.get('/health')
            owner, other = client.cookies.get(SESSION_COOKIE), stranger.cookies.get(SESSION_COOKIE)
            assert owner and other and owner != other
            rules = {}
            for label, peer in (('owner', client), ('other', stranger)):
                tire = peer.post('/v1/alert-rules', json={'name': 'Synthetic PG shared tire ' + label,
                    'source_id': 'fixture', 'query': QUERY['query'], 'enabled': True})
                recall = peer.post('/v1/recall-monitor-rules', json={'name': 'Synthetic PG private recall ' + label,
                    'query': {'campaign_number': CAMPAIGN}, 'enabled': label == 'owner'})
                assert tire.status_code == recall.status_code == 201
                rules[label] = {'tire': tire.json(), 'recall': recall.json()}
            jobs = {kind: rules['owner'][kind]['job']['id'] for kind in ('tire', 'recall')}
            assert jobs['tire'] == rules['other']['tire']['job']['id']
            assert jobs['recall'] != rules['other']['recall']['job']['id']
            old = utcnow() - timedelta(days=1)
            with database.sessions() as db:
                for kind, run_model in (('tire', MonitorRun), ('recall', RecallMonitorRun)):
                    db.add(run_model(id=uid(), job_id=jobs[kind], lease_token='synthetic-pre007-' + kind,
                        state='live', reason=None, started_at=old, finished_at=old + timedelta(seconds=1)))
                db.commit()

            STEP = 'migration_007'
            original_rows = fingerprints(database, Base.metadata)
            with database.engine.begin() as connection:
                connection.exec_driver_sql('DROP TABLE monitor_task_events')
                connection.exec_driver_sql('DROP TABLE monitor_task_attempts')
                connection.execute(text("DELETE FROM tire_schema_versions WHERE version = '007_monitor_tasks'"))
                old_tables = set(inspect(connection).get_table_names())
                old_versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
            database.initialize()
            database.initialize()
            assert fingerprints(database, Base.metadata) == original_rows
            with database.engine.connect() as connection:
                assert set(inspect(connection).get_table_names()) == old_tables | {'monitor_task_attempts', 'monitor_task_events'}
                versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
                assert versions == old_versions | {'007_monitor_tasks'}
            record('migration_007_twice_preserves_all_old_columns_and_legacy_runs_without_backfill')

            writers = Writers(run_root, url)
            for kind, job_model, run_model in (('tire', MonitorJob, MonitorRun), ('recall', RecallMonitorJob, RecallMonitorRun)):
                STEP = kind + '_independent_claim_race'
                path = f'/v1/monitor-tasks/{kind}/{jobs[kind]}'
                initial = client.get(path).json()
                assert initial['attempts_total'] == 0 and initial['legacy_runs_total'] == 1
                if kind == 'tire':
                    assert initial['task']['scope'] == 'local_workspace' and initial['task']['rule_count'] == 2
                    assert stranger.get(path).status_code == 200
                else:
                    assert initial['task']['scope'] == 'session'
                    for suffix in ('', '/events', '/events/stream'):
                        assert stranger.get(path + suffix).status_code == 404
                winner, claim = writers.start(kind + '-race', kind)
                assert claim['job_id'] == jobs[kind]
                active = client.get(path).json()
                assert active['task']['state'] == 'running' and active['task']['phase'] == 'running'
                assert active['attempts_total'] == 1
                cursors[kind] = active['cursor']
                completed = writers.finish(winner)
                assert completed['finalized'] is True and completed['query_id']
                first = client.get(path).json()
                assert first['task']['state'] == 'succeeded' and first['legacy_runs_total'] == 1
                with database.sessions() as db:
                    terminal = db.scalar(select(MonitorTaskEvent).where(MonitorTaskEvent.attempt_id == claim['attempt_id'],
                        MonitorTaskEvent.phase == 'finished'))
                    assert terminal.query_id == completed['query_id']
                    query, run = db.get(QueryRun, terminal.query_id), db.get(run_model, terminal.run_id)
                    assert query.state == run.state == 'live' and query.fallback_policy == 'never'
                record(kind + '_two_real_processes_one_claim_running_and_linked_terminal')

                STEP = kind + '_legacy_token_projection_and_stale_writer'
                time.sleep(2.2)  # Real source completion throttle, with synthetic adapters only.
                with database.sessions() as db:
                    db.get(job_model, jobs[kind]).next_due_at = utcnow() - timedelta(seconds=1)
                    db.commit()
                stale_name, stale = writers.start(kind + '-stale', kind, finish_mode='stale')
                with database.sessions() as db:
                    job = db.get(job_model, jobs[kind])
                    job.lease_token, job.lease_until = uid(), utcnow() + timedelta(seconds=600)
                    db.commit()  # Simulate an old Worker which knows no attempt table.
                before_reads = fingerprints(database, Base.metadata)
                unknown = client.get(path).json()
                assert unknown['task']['state'] == 'result_unknown' and not unknown['task']['terminal']
                for state, total in (('running', 0), ('result_unknown', 1)):
                    filtered = client.get('/v1/monitor-tasks', params={'kind': kind,
                        'rule_id': rules['owner'][kind]['id'], 'state': state}).json()
                    assert filtered['total'] == total
                    assert all(row['state'] == state for row in filtered['items'])
                assert fingerprints(database, Base.metadata) == before_reads
                with database.sessions() as db:
                    db.get(job_model, jobs[kind]).lease_until = utcnow() - timedelta(seconds=1)
                    db.commit()
                replacement_name, replacement = writers.start(kind + '-replacement', kind, count=1)
                assert replacement['attempt_id'] != stale['attempt_id']
                with database.sessions() as db:
                    replacement_token = db.get(job_model, jobs[kind]).lease_token
                    runs_before = db.scalar(select(func.count()).select_from(run_model))
                rejected = writers.finish(stale_name)
                assert rejected['finalized'] is False
                with database.sessions() as db:
                    assert db.get(job_model, jobs[kind]).lease_token == replacement_token
                    assert db.scalar(select(func.count()).select_from(run_model)) == runs_before
                    terminals = db.scalars(select(MonitorTaskEvent).where(MonitorTaskEvent.attempt_id == stale['attempt_id'],
                        MonitorTaskEvent.phase == 'finished')).all()
                    assert len(terminals) == 1 and terminals[0].state == 'interrupted'
                replacement_result = writers.finish(replacement_name)
                assert replacement_result['finalized'] is True
                detail = client.get(path).json()
                assert detail['attempts_total'] == 3 and detail['legacy_runs_total'] == 1
                assert detail['task']['state'] == 'succeeded'
                states = [row['state'] for row in detail['attempts']]
                assert states == ['succeeded', 'interrupted', 'succeeded']
                page = client.get(path + '/events', params={'cursor': initial['cursor']}).json()
                assert [row['sequence'] for row in page['items']] == list(range(1, 10))
                assert len({row['id'] for row in page['items']}) == 9
                assert all(str(UUID(row['id'])) == row['id'] for row in page['items'])
                assert len({row['attempt_id'] for row in page['items']}) == 3
                tail = client.get(path + '/events', params={'cursor': cursors[kind]}).json()
                assert [row['sequence'] for row in tail['items']] == list(range(3, 10))
                assert stream_rows(client, path, cursors[kind]) == tail['items']
                anchor = json.loads(base64.urlsafe_b64decode(cursors[kind] + '=' * (-len(cursors[kind]) % 4)))
                anchor[4] = str(uuid4())
                bad = base64.urlsafe_b64encode(json.dumps(anchor).encode()).decode().rstrip('=')
                reset = client.get(path + '/events', params={'cursor': bad})
                assert reset.status_code == 409 and reset.json()['detail']['code'] == 'task_cursor_reset_required'
                body = json.dumps(detail) + json.dumps(page)
                assert 'lease_token' not in body and 'actor_session_id' not in body and owner not in body and other not in body
                expected_details[kind], expected_events[kind] = strip_clock(detail), strip_clock(tail)
                lane_reports.append({'kind': kind, 'attempts': 3, 'events': 9, 'legacy_runs': 1,
                    'successful_attempts': 2, 'interrupted_attempts': 1, 'stale_finish_accepted': False,
                    'replay_start_sequence': 3, 'replay_end_sequence': 9, 'tampered_anchor_status': 409,
                    'legacy_token_filter_consistent': True})
                record(kind + '_old_process_cannot_overwrite_replacement_cross_attempt_cursor_and_pure_unknown')

            writers.close()
            assert REPORT['writer_processes_reaped']
            with database.sessions() as db:
                assert db.scalar(select(func.count()).select_from(AIRequest)) == 0
                assert db.scalar(select(func.count()).select_from(EmbeddingRequest)) == 0
                captures = [(row.id, row.raw_hash) for row in db.scalars(select(RawCapture))]
                assert len(captures) == 4
                for capture_id, raw_hash in captures:
                    body, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                    assert location == 'object_store' and hashlib.sha256(body).hexdigest() == raw_hash
            frozen_rows = fingerprints(database, Base.metadata)
        database = None

        STEP = 'dump_restore'
        restore_name = 'restored_monitor_tasks_' + uuid4().hex[:10]
        restored_url = new_database(restore_name)
        archive, pg_bin = run_root / 'monitor-tasks.dump', Path(os.environ['TIRE_PG_BIN'])
        child_env = {**os.environ, 'PGHOST': '127.0.0.1', 'PGPORT': '55442', 'PGUSER': role, 'PGPASSWORD': password}
        child_env.pop('TIRE_PG_TEST_PASSWORD', None)
        for command in (
            [str(pg_bin / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-acl', '--no-password',
                '--dbname', name, '--file', str(archive)],
            [str(pg_bin / 'pg_restore.exe'), '--exit-on-error', '--no-owner', '--no-acl', '--no-password',
                '--dbname', restore_name, str(archive)],
        ):
            assert subprocess.run(command, env=child_env, capture_output=True, timeout=60).returncode == 0, 'private_dump_restore_failed'
        object_root, destination = run_root / 'objects', run_root / 'restored-objects'
        object_hashes = file_hashes(object_root)
        assert object_hashes and not destination.exists()
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
        restored.close()
        restored = None
        record('dump_restore_all_registered_columns_versions_and_object_hashes_identical')

        STEP = 'restored_original_cursor'
        with TestClient(create_app(restored_url, RecordingRegistry()), cookies={SESSION_COOKIE: owner}) as client, \
                TestClient(create_app(restored_url, RecordingRegistry()), cookies={SESSION_COOKIE: other}) as stranger:
            for kind in ('tire', 'recall'):
                path = f'/v1/monitor-tasks/{kind}/{jobs[kind]}'
                assert strip_clock(client.get(path).json()) == expected_details[kind]
                replay = client.get(path + '/events', params={'cursor': cursors[kind]}).json()
                assert strip_clock(replay) == expected_events[kind]
                assert stream_rows(client, path, cursors[kind]) == expected_events[kind]['items']
                assert stranger.get(path).status_code == (200 if kind == 'tire' else 404)
        record('restored_original_seq_uuid_cursor_replays_same_events_sse_scope_and_legacy_history')
        assert not (run_root / 'import-guard.sqlite').exists()
        REPORT.update(status='passed', lane_checks=lane_reports, tables_checked=len(frozen_rows),
            columns_checked=sum(len(value['columns']) for value in frozen_rows.values()), schema_versions=sorted(versions),
            migration='007_monitor_tasks', schema_migrations_added=1, legacy_runs_preserved=2,
            table_fingerprints=public_fingerprints(frozen_rows), restore_table_fingerprints=public_fingerprints(restored_rows),
            capture_count=len(captures), object_file_count=len(object_hashes), object_hashes=object_hashes,
            copied_object_hashes=file_hashes(destination), archive_bytes=archive.stat().st_size,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), real_source_calls=0,
            real_parser_children=0, real_ai_calls=0, real_embedding_calls=0, normal_database_used=False,
            sse_test_window_seconds=0.06,
            fingerprint_scope='All Base.metadata registered columns and values, schema versions and object files; '
                'not roles, ACL or cross-host recovery')
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
    with patch.object(SafeHttpClient, '_request', side_effect=AssertionError('real_source_transport_forbidden')) as transport, \
            patch.object(parser_runtime, '_run_sync', side_effect=AssertionError('real_parser_execution_forbidden')) as parser:
        value = action()
        assert transport.call_count == parser.call_count == 0
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run-private-postgres', action='store_true')
    mode.add_argument('--writer')
    arguments = parser.parse_args()
    if arguments.writer:
        try:
            return guarded(lambda: writer(arguments.writer))
        except Exception as error:
            print(json.dumps({'status': 'failed', **safe_failure(error)}), flush=True)
            return 1
    code = 0
    try:
        guarded(run)
    except Exception as error:
        code = 1
        REPORT.update(status='failed', failure_step=STEP, **safe_failure(error))
    report = Path(os.environ['TIRE_PG_TEST_REPORT']).resolve()
    assert report.name == 'report.json' and report.parent.parent == (ROOT / '.artifacts/runtime').resolve()
    assert report.parent.name.startswith('round42-monitor-tasks-PG-')
    report.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: REPORT[key] for key in ('status', 'scope', 'checks')}), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
