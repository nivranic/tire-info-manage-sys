"""Loopback HTTP and independent Worker acceptance on a fresh private PG cluster.

Stored source inputs use the existing recorded transport fixture. Service processes
use their normal entry points. Worker sources are explicitly disabled, so queue
checks exercise unavailable outcomes without requesting an external website.
Explicit --live-source uses the registered Hankook adapter for real HTTP queries
and successful Worker consumption, including after independent asset restoration.
"""
import argparse
import asyncio
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import traceback
from unittest.mock import patch
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / path) for path in ('apps/api', 'apps/api/tests', 'apps/worker')]
import run_api_worker_regression as regression
from postgres_acceptance import database_fingerprint
from test_parser_releases import RecordedRegistry, SOURCE, QUERY
from tire_api.db import Database, MonitorJob, utc, utcnow
from tire_api.domain import LiveQueryRequest
from tire_api.main import SESSION_COOKIE
from tire_api.postgres_runtime_roles import check_runtime_role, runtime_role_sql
from tire_api.postgres_schema import build_reference, verify_schema
from tire_api.service import QueryService

REPORT = {'scope': 'isolated loopback PG/TLS, actual HTTP and Worker processes, recorded source fixture',
          'checks': [], 'processes': [], 'ports': [], 'model_gateways_enabled': False}
STEP = 'setup'


def record(name):
    REPORT['checks'].append({'name': name, 'passed': True})
    print(json.dumps(REPORT['checks'][-1]), flush=True)


def accepted(response, expected=200):
    if response.status_code != expected:
        REPORT['http_failure'] = {'path': response.request.url.path,
                                  'expected': expected, 'actual': response.status_code}
    assert response.status_code == expected, 'unexpected_http_status'
    return response.json()


def wait_for(check, *, timeout=30, interval=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(interval)
    raise AssertionError('process_observation_deadline')


def interrupt_console(process):
    """Signal only this run's newly created console, retaining actual process handles."""
    import ctypes
    from ctypes import wintypes as w
    assert sys.platform == 'win32' and process.poll() is None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.FreeConsole.argtypes, kernel.FreeConsole.restype = [], w.BOOL
    kernel.AttachConsole.argtypes, kernel.AttachConsole.restype = [w.DWORD], w.BOOL
    kernel.SetConsoleCtrlHandler.argtypes, kernel.SetConsoleCtrlHandler.restype = [ctypes.c_void_p, w.BOOL], w.BOOL
    kernel.GenerateConsoleCtrlEvent.argtypes, kernel.GenerateConsoleCtrlEvent.restype = [w.DWORD, w.DWORD], w.BOOL
    kernel.GetConsoleProcessList.argtypes = [ctypes.POINTER(w.DWORD), w.DWORD]
    kernel.GetConsoleProcessList.restype = w.DWORD
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.WaitForSingleObject.argtypes, kernel.WaitForSingleObject.restype = [w.HANDLE, w.DWORD], w.DWORD
    kernel.GetExitCodeProcess.argtypes, kernel.GetExitCodeProcess.restype = [w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL
    kernel.TerminateProcess.argtypes, kernel.TerminateProcess.restype = [w.HANDLE, w.UINT], w.BOOL
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    handles, exits = [], []
    completed = False
    # The tool host can have a console without a visible window. Detach only
    # this verifier before attaching the console created for its own child.
    assert kernel.FreeConsole(), 'verifier_console_detach_failed'
    assert kernel.AttachConsole(process.pid), 'service_console_attach_failed'
    try:
        assert kernel.SetConsoleCtrlHandler(None, True), 'verifier_console_ignore_failed'
        pids = (w.DWORD * 16)()
        count = kernel.GetConsoleProcessList(pids, len(pids))
        assert 1 < count <= len(pids) and process.pid in pids[:count] and os.getpid() in pids[:count]
        for pid in pids[:count]:
            if pid == os.getpid():
                continue
            handle = kernel.OpenProcess(0x00100000 | 0x1000 | 0x1, False, pid)
            assert handle, 'service_process_handle_unavailable'
            handles.append((pid, handle))
        started = time.monotonic()
        assert kernel.GenerateConsoleCtrlEvent(0, 0), 'service_console_interrupt_failed'
        for pid, handle in handles:
            assert kernel.WaitForSingleObject(handle, 30_000) == 0, 'service_graceful_exit_deadline'
            code = w.DWORD()
            assert kernel.GetExitCodeProcess(handle, ctypes.byref(code)), 'service_exit_code_unavailable'
            exits.append({'pid': pid, 'code': code.value})
        process.wait(timeout=5)
        completed = True
        return {'signal': 'CTRL_C_EVENT', 'process_exit_codes': exits,
                'elapsed_seconds': time.monotonic() - started}
    finally:
        for _pid, handle in handles:
            if not completed and kernel.WaitForSingleObject(handle, 0) == 258:
                kernel.TerminateProcess(handle, 1)
                kernel.WaitForSingleObject(handle, 10_000)
            kernel.CloseHandle(handle)
        kernel.FreeConsole()
        kernel.SetConsoleCtrlHandler(None, False)


@contextmanager
def child(slot, label, arguments, environment, *, console=False):
    startup = None
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    if console:
        assert sys.platform == 'win32', 'console_acceptance_requires_windows'
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        flags = subprocess.CREATE_NEW_CONSOLE
    with (slot / (label + '.stdout.log')).open('wb') as stdout, \
            (slot / (label + '.stderr.log')).open('wb') as stderr:
        process = subprocess.Popen([sys.executable, '-X', 'utf8', '-B', *arguments], cwd=ROOT,
            env=environment, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            creationflags=flags, startupinfo=startup)
        receipt = {'label': label, 'pid': process.pid, 'reaped': False}
        REPORT['processes'].append(receipt)
        try:
            yield process
            if console:
                receipt['graceful_exit'] = interrupt_console(process)
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            receipt.update(reaped=True, returncode=process.returncode)


@contextmanager
def http_service(slot, label, environment, *, cookies=None, graceful=False):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    REPORT['ports'].append(port)
    arguments = ['-m', 'uvicorn', 'tire_api.main:app', '--host', '127.0.0.1',
                 '--port', str(port), '--workers', '1', '--no-access-log', '--log-level', 'info' if graceful else 'warning']
    with child(slot, label, arguments, environment, console=graceful) as process, \
            httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False,
                         timeout=45, cookies=cookies) as client:
        def ready():
            assert process.poll() is None, 'api_exited_before_ready'
            try:
                return accepted(client.get('/health'))
            except (httpx.ConnectError, httpx.TimeoutException):
                return None
        health = wait_for(ready)
        assert health['database'] == 'postgresql'
        yield client


def graceful_worker(slot, environment):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    REPORT['ports'].append(port)
    label = 'worker-graceful'
    arguments = [str(ROOT / 'apps/worker/monitor.py'), '--interval', '10', '--metrics-port', str(port)]
    with child(slot, label, arguments, environment, console=True) as process, \
            httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=2) as client:
        def ready():
            assert process.poll() is None, 'worker_exited_before_ready'
            try:
                response = client.get('/v1/observability/metrics')
            except (httpx.ConnectError, httpx.TimeoutException):
                return False
            lines = (slot / (label + '.stdout.log')).read_text(encoding='utf-8').splitlines()
            return response.status_code == 200 and len(lines) >= 2
        wait_for(ready)
        lines = (slot / (label + '.stdout.log')).read_text(encoding='utf-8').splitlines()
        endpoint, cycle = json.loads(lines[0]), json.loads(lines[1])
        assert endpoint == {'address': '127.0.0.1', 'port': port, 'metrics_path': '/v1/observability/metrics'}
        assert cycle['jobs'] == 0 and cycle['results'] == []
    receipt = REPORT['processes'][-1]
    assert receipt['returncode'] == 0xC000013A
    assert all(item['code'] == 0xC000013A for item in receipt['graceful_exit']['process_exit_codes'])
    errors = (slot / (label + '.stderr.log')).read_text(encoding='utf-8')
    assert 'asyncio.exceptions.CancelledError' in errors and 'KeyboardInterrupt' in errors


def run_worker(slot, label, environment, *, live_source=False):
    if not live_source:
        environment = {**environment, 'TI_DISABLED_SOURCES': SOURCE}
    with child(slot, label, [str(ROOT / 'apps/worker/monitor.py'), '--once'], environment) as process:
        assert process.wait(timeout=45) == 0, 'worker_once_failed'
    lines = (slot / (label + '.stdout.log')).read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1, 'unexpected_worker_output'
    return json.loads(lines[0])


def files(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file()}


def evaluate(client, capture_id, bundle_id):
    value = accepted(client.post('/v1/parser-evaluations', headers={'Idempotency-Key': str(uuid4())}, json={
        'mode': 'history', 'source_id': SOURCE, 'target_bundle_id': bundle_id,
        'capture_ids': [capture_id], 'expected_deployment_revision': 1}), 201)
    assert value['state'] == 'completed', 'http_parser_evaluation_failed'
    item = value['completion']['results'][0]
    assert item['candidate_error'] is None and item['control_error'] is None
    assert item['diff']['total_changed_fields'] == 0
    for kind in ('control', 'candidate'):
        receipt = item[kind + '_receipt']
        assert receipt['reaped'] and receipt['bundle_id'] == bundle_id
        assert receipt['exit_code'] == 0
    return value


def live_execution(client, query_id):
    value = accepted(client.get('/v1/parser-executions/' + query_id, params={'mode': 'history'}))
    completion = value['completion']
    receipt = completion['receipt']
    assert completion['error_code'] is None
    if completion['state'] == 'completed':
        assert receipt['reaped'] and receipt['exit_code'] == 0
        assert receipt['bundle_id'] == value['selection']['bundle_id']
    else:
        assert completion['state'] == 'not_modified' and value['query_state'] == 'live_verified_304'
        assert not receipt
    REPORT.setdefault('live_executions', []).append({'query_id': query_id,
        'selection': value['selection'], 'completion': completion})


def run(*, live_source=False, natural_lease=False):
    global STEP
    expected = Path(os.environ['TIRE_PG_TEST_DATA']).resolve()
    assert expected.is_relative_to((ROOT / '.artifacts/postgres').resolve())
    assert expected.name == 'data' and expected.parent.name.startswith('pgverify-')
    slot = expected.parent
    port = int(os.environ['TIRE_PG_TEST_PORT'])
    ca = os.environ.get('TIRE_PG_TEST_TLS_ROOT')
    assert ca, 'process_suite_requires_tls'
    owner, runtime = 'process_owner_' + uuid4().hex[:12], 'process_runtime_' + uuid4().hex[:12]
    owner_secret, runtime_secret = secrets.token_hex(32), secrets.token_hex(32)
    transport = {'sslmode': 'verify-full', 'sslrootcert': ca}
    success_states = ('live', 'live_verified_304') if live_source else ('source_unavailable',)
    task_state = 'succeeded' if live_source else 'failed'
    REPORT['live_source'] = live_source
    REPORT['natural_lease'] = natural_lease
    if live_source:
        REPORT['scope'] = 'isolated loopback PG/TLS, actual HTTP and Worker processes, live official Hankook source'

    with psycopg.connect(host='127.0.0.1', port=port, user='tire_verify_admin',
            password=os.environ['TIRE_PG_TEST_PASSWORD'], dbname='postgres', autocommit=True,
            connect_timeout=5, **transport) as admin:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == expected
        REPORT['postgres_version'] = admin.execute('SHOW server_version').fetchone()[0]
        for role, secret in ((owner, owner_secret), (runtime, runtime_secret)):
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB '
                'NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(role), sql.Literal(secret)))

        def database_name():
            name = 'process_' + uuid4().hex[:12]
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(owner)))
            return name

        def wait_for_runtime_disconnect():
            statement = 'SELECT count(*) FROM pg_stat_activity WHERE usename=%s'
            initial = admin.execute(statement, (runtime,)).fetchone()[0]
            receipt = {'stage': STEP, 'initial_backends': initial, 'closed': False}
            REPORT.setdefault('backend_closure', []).append(receipt)
            wait_for(lambda: admin.execute(statement, (runtime,)).fetchone()[0] == 0, timeout=10)
            receipt['closed'] = True

        def url(name, *, limited=False, label='process-acceptance'):
            return URL.create('postgresql+psycopg', username=runtime if limited else owner,
                password=runtime_secret if limited else owner_secret, host='127.0.0.1', port=port,
                database=name, query={**transport, 'application_name': label}).render_as_string(hide_password=False)

        def grants(name):
            engine = create_engine(url(name))
            try:
                with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
                    connection.exec_driver_sql('REVOKE CREATE,TEMPORARY ON DATABASE "' + name + '" FROM PUBLIC')
                    connection.exec_driver_sql('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
                    connection.exec_driver_sql(runtime_role_sql(runtime, name))
            finally:
                engine.dispose()
            limited = create_engine(url(name, limited=True))
            try:
                assert check_runtime_role(limited)['ok']
                verify_schema(limited, contract_path, contract['sha256'])
            finally:
                limited.dispose()

        STEP = 'empty_reference_and_independent_runtime_database'
        reference, target = database_name(), database_name()
        contract_path = slot / 'process-schema.json'
        reference_engine = create_engine(url(reference))
        try:
            contract = build_reference(reference_engine, contract_path)
        finally:
            reference_engine.dispose()
        REPORT['contract'] = contract
        owned = Database(url(target), schema_mode='migrate')
        try:
            owned.initialize()
        finally:
            owned.close()
        grants(target)
        record(STEP)

        # Service processes receive only runtime credentials and explicit paths.
        environment = {key: value for key, value in os.environ.items() if key.upper() in
            {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'TMPDIR', 'LANG'}}
        environment.update(PYTHONPATH=str(ROOT / 'apps/api'), PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
            TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_LOGS='0',
            TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(slot / 'objects'),
            TI_PARSER_BUNDLE_ROOT=str(slot / 'bundles'), TI_DATABASE_SCHEMA_MODE='verify',
            TI_DATABASE_SCHEMA_CONTRACT=str(contract_path), TI_DATABASE_SCHEMA_SHA256=contract['sha256'],
            TIRE_DATABASE_URL=url(target, limited=True))
        assert 'TIRE_PG_TEST_PASSWORD' not in environment and owner_secret not in ''.join(environment.values())
        assert 'PROCESSOR_ARCHITECTURE' not in environment and 'PROCESSOR_ARCHITEW6432' not in environment

        STEP = 'http_admin_session_and_source_evidence'
        with patch.dict(os.environ, environment), http_service(slot, 'api-first', environment) as client:
            password = secrets.token_urlsafe(24)
            account = accepted(client.post('/v1/auth/register', json={'username': 'admin', 'password': password}))
            assert account['user']['is_admin']
            sessions = admin.execute('SELECT count(*), bool_and(s.ssl) FROM pg_stat_activity a '
                'JOIN pg_stat_ssl s USING (pid) WHERE a.usename=%s', (runtime,)).fetchone()
            assert sessions[0] > 0 and sessions[1] is True
            REPORT['http_runtime_tls_sessions'] = sessions[0]
            cookies = dict(client.cookies)
            if live_source:
                seeded = accepted(client.post('/v1/sources/' + SOURCE + '/live-query',
                    json={'query': QUERY, 'fallback_policy': 'never'}))
                REPORT['live_query_outcome'] = {'state': seeded['data_state'], 'reason': seeded.get('reason')}
                assert seeded['data_state'] == 'live' and seeded['variants'], 'live_source_query_failed'
                live_execution(client, seeded['query_id'])
            else:
                runtime_db = Database(url(target, limited=True))
                try:
                    runtime_db.initialize()
                    with runtime_db.sessions() as db:
                        seeded = asyncio.run(QueryService(db, RecordedRegistry()).execute(SOURCE,
                            LiveQueryRequest(query=QUERY, fallback_policy='never'), cookies[SESSION_COOKIE]))
                    assert seeded['data_state'] == 'live'
                finally:
                    runtime_db.close()
            captures = accepted(client.get('/v1/captures', params={'mode': 'history', 'source_id': SOURCE}))
            capture = captures['items'][0]
            raw = accepted(client.get(capture['evidence_path']))
            assert hashlib.sha256(raw['body'].encode()).hexdigest() == capture['raw_hash']
            bundle_id = capture['parser_identity']['bundle_id']
            REPORT['source_evidence'] = {'raw_hash': capture['raw_hash'], 'bundle_id': bundle_id,
                'source_url': capture['source_url'], 'byte_count': capture['byte_count'],
                'product_codes': sorted(item['manufacturer_product_code'] for item in seeded['variants']),
                'transport': 'registered live adapter via HTTP' if live_source else 'recorded excerpt via QueryService'}
            record(STEP)

            STEP = 'http_parser_children_in_inherited_architecture_environment'
            evaluation = evaluate(client, capture['id'], bundle_id)
            REPORT['initial_parser_evaluation'] = evaluation['id']
            record(STEP)

            STEP = 'independent_worker_consumes_persisted_http_rule'
            rule = accepted(client.post('/v1/alert-rules', json={
                'name': 'Synthetic process deployment rule', 'source_id': SOURCE, 'query': QUERY, 'enabled': True}), 201)
            job_id = rule['job']['id']
            result = run_worker(slot, 'worker-once', environment, live_source=live_source)
            assert result['jobs'] == 1 and result['results'][0]['job_id'] == job_id
            REPORT['first_worker_outcome'] = result['results'][0]
            assert result['results'][0]['state'] in success_states and result['results'][0]['finalized']
            path = '/v1/monitor-tasks/tire/' + job_id
            detail = accepted(client.get(path))
            assert detail['attempts_total'] == 1 and detail['attempts'][0]['terminal']
            assert detail['attempts'][0]['state'] == task_state
            if live_source:
                live_execution(client, detail['attempts'][0]['query_id'])
            record(STEP)

            STEP = 'terminate_observed_blocked_worker_and_recover_expired_lease'
            owner_engine = create_engine(url(target))
            try:
                with owner_engine.begin() as connection:
                    connection.execute(MonitorJob.__table__.update().where(MonitorJob.id == job_id)
                        .values(next_due_at=utcnow() - timedelta(seconds=1)))
                time.sleep(2.2)  # Preserve the normal per-source minimum interval.
                with owner_engine.begin() as lock:
                    # SHARE permits the startup catalog's relation reads and
                    # blocks the subsequent query INSERT after the attempt starts.
                    lock.exec_driver_sql('LOCK TABLE public.query_runs IN SHARE MODE')
                    blocked_environment = {**environment, 'TI_DISABLED_SOURCES': SOURCE,
                        'TIRE_DATABASE_URL': url(target, limited=True, label='process-cancel-worker')}
                    with child(slot, 'worker-interrupted', [str(ROOT / 'apps/worker/monitor.py'), '--once'],
                               blocked_environment) as process:
                        def blocked():
                            assert process.poll() is None, 'worker_exited_before_lock_observation'
                            return admin.execute("SELECT pid, wait_event, left(query, 300) FROM pg_stat_activity WHERE application_name=%s "
                                "AND wait_event_type='Lock' AND state='active'", ('process-cancel-worker',)).fetchone()
                        backend = wait_for(blocked)
                        detail = accepted(client.get(path))
                        REPORT['interrupt_observation'] = {'wait_event': backend[1], 'statement_prefix': backend[2],
                            'attempts_total': detail['attempts_total'], 'task_state': detail['task']['state'],
                            'latest_phase': detail['attempts'][0]['phase']}
                        assert detail['attempts_total'] == 2 and detail['attempts'][0]['phase'] == 'running'
                        REPORT['interrupted_backend_observed'] = bool(backend)
                        process.terminate()
                        process.wait(timeout=15)
                if natural_lease:
                    from tire_api.monitoring import LEASE_SECONDS
                    with owner_engine.connect() as connection:
                        expires = utc(connection.execute(select(MonitorJob.lease_until)
                            .where(MonitorJob.id == job_id)).scalar_one())
                    remaining = (expires - utcnow()).total_seconds()
                    assert 0 < remaining <= LEASE_SECONDS
                    started = time.monotonic()
                    observations = 0
                    print(json.dumps({'waiting_for_natural_lease': True, 'seconds_remaining': round(remaining, 3)}), flush=True)

                    def expired():
                        nonlocal observations
                        current = accepted(client.get(path))
                        assert current['attempts_total'] == 2
                        observation = {'checked_at': utcnow().isoformat(), 'state': current['task']['state'],
                            'elapsed_seconds': round(time.monotonic() - started, 3),
                            'lease_until': current['task']['lease_until']}
                        assert current['task']['lease_until'] == expires.isoformat()
                        with (slot / 'lease-observations.jsonl').open('a', encoding='utf-8') as output:
                            output.write(json.dumps(observation) + '\n')
                        observations += 1
                        return current['task']['state'] == 'result_unknown'

                    wait_for(expired, timeout=remaining + 20, interval=10)
                    elapsed = time.monotonic() - started
                    assert elapsed + 1 >= remaining
                    REPORT['natural_lease_observation'] = {'lease_seconds': LEASE_SECONDS,
                        'expires_at': expires.isoformat(), 'initial_remaining_seconds': remaining,
                        'elapsed_seconds': elapsed, 'observations': observations}
                else:
                    with owner_engine.begin() as connection:
                        connection.execute(MonitorJob.__table__.update().where(MonitorJob.id == job_id)
                            .values(lease_until=utcnow() - timedelta(seconds=1)))
                detail = accepted(client.get(path))
                assert detail['task']['state'] == 'result_unknown' and not detail['attempts'][0]['terminal']
                recovered = run_worker(slot, 'worker-recovered', environment, live_source=live_source)
                assert recovered['jobs'] == 1 and recovered['results'][0]['finalized']
                REPORT['recovered_worker_outcome'] = recovered['results'][0]
                assert recovered['results'][0]['state'] in success_states
                detail = accepted(client.get(path))
                assert detail['attempts_total'] == 3
                assert sorted(item['state'] for item in detail['attempts']) == sorted([task_state, task_state, 'interrupted'])
                assert all(item['terminal'] for item in detail['attempts'])
                if live_source:
                    live_execution(client, detail['attempts'][0]['query_id'])
                events = accepted(client.get(path + '/events'))
                REPORT['recovered_attempts'] = detail['attempts_total']
                REPORT['lease_expiry_fixture'] = ('natural persisted lease expiry after observed process termination'
                    if natural_lease else 'own isolated job timestamp advanced after observed process termination')
            finally:
                owner_engine.dispose()
            record(STEP)

        STEP = 'http_restart_keeps_cookie_evidence_and_event_cursor'
        with http_service(slot, 'api-restarted', environment, cookies=cookies) as client:
            restarted_events = accepted(client.get(path + '/events'))
            assert restarted_events['items'] == events['items']
            assert restarted_events['next_cursor'] == events['next_cursor']
            assert accepted(client.get(capture['evidence_path']))['raw_hash'] == raw['raw_hash']
        record(STEP)

        STEP = 'invalid_contract_rejects_real_api_and_worker_startup'
        invalid = {**environment, 'TI_DATABASE_SCHEMA_SHA256': '0' * 64}
        for label, arguments in (
                ('api-invalid-contract', ['-m', 'uvicorn', 'tire_api.main:app', '--host', '127.0.0.1', '--port', '0', '--no-access-log']),
                ('worker-invalid-contract', [str(ROOT / 'apps/worker/monitor.py'), '--once'])):
            with child(slot, label, arguments, invalid) as process:
                assert process.wait(timeout=30) != 0, 'invalid_contract_process_started'
            assert 'schema_contract_hash_mismatch' in (slot / (label + '.stderr.log')).read_text(encoding='utf-8')
        record(STEP)

        STEP = 'database_and_all_filesystem_assets_independent_restore'
        wait_for_runtime_disconnect()
        frozen = Database(url(target), schema_mode='migrate')
        try:
            before = database_fingerprint(frozen)
        finally:
            frozen.close()
        backup_objects, backup_bundles = slot / 'restored-objects', slot / 'restored-bundles'
        shutil.copytree(slot / 'objects', backup_objects)
        shutil.copytree(slot / 'bundles', backup_bundles)
        assert files(slot / 'objects') == files(backup_objects)
        assert files(slot / 'bundles') == files(backup_bundles)
        REPORT['restored_object_files'] = len(files(backup_objects))
        REPORT['restored_bundle_files'] = len(files(backup_bundles))
        restored = database_name()
        pg_environment = {key: value for key, value in environment.items() if key.upper() in
                          {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'TMPDIR'}}
        pg_environment.update(PGHOST='127.0.0.1', PGPORT=str(port), PGUSER=owner,
                              PGPASSWORD=owner_secret, PGSSLMODE='verify-full', PGSSLROOTCERT=ca)
        pg_bin = Path(os.environ['TIRE_PG_BIN'])
        archive = slot / 'process.backup'
        commands = (
            [str(pg_bin / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-acl', '--no-password',
             '--dbname', target, '--file', str(archive)],
            [str(pg_bin / 'pg_restore.exe'), '--exit-on-error', '--no-owner', '--no-acl', '--no-password',
             '--dbname', restored, str(archive)])
        for index, command in enumerate(commands):
            completed = subprocess.run(command, env=pg_environment, capture_output=True, timeout=60)
            (slot / f'backup-{index}.stderr.log').write_bytes(completed.stderr)
            assert completed.returncode == 0, 'dump_restore_failed'
        grants(restored)
        recovered_db = Database(url(restored, limited=True), schema_mode='verify',
            schema_contract=contract_path, schema_sha256=contract['sha256'])
        try:
            recovered_db.initialize()
            assert database_fingerprint(recovered_db) == before
        finally:
            recovered_db.close()
        REPORT['restored_tables'] = len(before) - 1
        # Move only these newly created run assets, making original-root fallback fail.
        for name in ('objects', 'bundles'):
            source, destination = (slot / name).resolve(), (slot / (name + '.offline')).resolve()
            assert source.is_relative_to(slot) and destination.is_relative_to(slot) and not destination.exists()
            source.rename(destination)
        record(STEP)

        STEP = 'restored_http_parser_reads_backup_assets_and_worker_restarts'
        restored_environment = {**environment, 'TIRE_DATABASE_URL': url(restored, limited=True),
            'TI_OBJECT_STORE_ROOT': str(backup_objects), 'TI_PARSER_BUNDLE_ROOT': str(backup_bundles)}
        with http_service(slot, 'api-restored', restored_environment, cookies=cookies) as client:
            restored_events = accepted(client.get(path + '/events'))
            assert restored_events['items'] == events['items']
            assert restored_events['next_cursor'] == events['next_cursor']
            assert accepted(client.get(capture['evidence_path']))['raw_hash'] == capture['raw_hash']
            evaluate(client, capture['id'], bundle_id)
            restored_owner = create_engine(url(restored))
            try:
                with restored_owner.begin() as connection:
                    connection.execute(MonitorJob.__table__.update().where(MonitorJob.id == job_id)
                        .values(next_due_at=utcnow() - timedelta(seconds=1)))
            finally:
                restored_owner.dispose()
            result = run_worker(slot, 'worker-restored', restored_environment, live_source=live_source)
            assert result['jobs'] == 1 and result['results'][0]['finalized']
            REPORT['restored_worker_outcome'] = result['results'][0]
            assert result['results'][0]['state'] in success_states
            detail = accepted(client.get(path))
            assert detail['attempts_total'] == 4 and all(item['terminal'] for item in detail['attempts'])
            if live_source:
                live_execution(client, detail['attempts'][0]['query_id'])
        wait_for_runtime_disconnect()
        record(STEP)

        STEP = 'normal_http_ctrl_c_completes_lifespan_and_closes_runtime_sessions'
        with http_service(slot, 'api-graceful', restored_environment, cookies=cookies, graceful=True) as client:
            assert accepted(client.get(path))['attempts_total'] == 4
        receipt = REPORT['processes'][-1]
        assert receipt['returncode'] == 0
        assert all(item['code'] == 0 for item in receipt['graceful_exit']['process_exit_codes'])
        assert 'Application shutdown complete.' in (slot / 'api-graceful.stderr.log').read_text(encoding='utf-8')
        wait_for_runtime_disconnect()
        record(STEP)

        STEP = 'normal_worker_ctrl_c_cancels_idle_loop_and_closes_metrics_and_sessions'
        graceful_worker(slot, restored_environment)
        wait_for_runtime_disconnect()
        record(STEP)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-source', action='store_true',
                        help='Use the registered Hankook official source for HTTP and Worker consumption.')
    parser.add_argument('--natural-lease', action='store_true',
                        help='Observe the normal 600-second lease expiry without changing its timestamp.')
    options = parser.parse_args()
    before = regression.bindings()
    try:
        run(live_source=options.live_source, natural_lease=options.natural_lease)
    except Exception as error:
        REPORT.update(failure_step=STEP, error_type=type(error).__name__, code=getattr(error, 'code', None),
            sqlstate=getattr(getattr(error, 'orig', error), 'sqlstate', None),
            frames=[{'file': Path(frame.filename).name, 'function': frame.name, 'line': frame.lineno}
                    for frame in traceback.extract_tb(error.__traceback__)])
    REPORT['inputs_stable'] = before == regression.bindings()
    REPORT['input_count'] = len(before)
    REPORT['children_reaped'] = all(item['reaped'] for item in REPORT['processes'])
    REPORT['ports_closed'] = True
    for port in REPORT['ports']:
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                REPORT['ports_closed'] = False
    REPORT['passed'] = (bool(REPORT['checks']) and REPORT['inputs_stable'] and REPORT['children_reaped']
                        and REPORT['ports_closed'] and 'failure_step' not in REPORT)
    Path(os.environ['TIRE_PG_TEST_REPORT']).write_text(json.dumps(REPORT, indent=2), encoding='utf-8')
    print(json.dumps({'passed': REPORT['passed'], 'checks': len(REPORT['checks']),
                      'failure_step': REPORT.get('failure_step')}), flush=True)
    raise SystemExit(0 if REPORT['passed'] else 1)
