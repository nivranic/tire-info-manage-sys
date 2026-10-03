"""Real loopback HTTP/OTel acceptance with private synthetic sources, never live AI.

Run with the API environment's Python. The parent starts one owned uvicorn child
on an available loopback port and always stops it before deleting private storage.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

WORKSPACE = Path(__file__).resolve().parents[1]
CANARY = 'synthetic-private-content-must-not-enter-observability'


def setup_paths():
    sys.path.insert(0, str(WORKSPACE / 'apps/api'))
    sys.path.insert(0, str(WORKSPACE / 'apps/api/tests'))


def serve(port: int, directory: Path, output: Path):
    root = directory.resolve()
    assert root.parent == Path(tempfile.gettempdir()).resolve() and root.name.startswith('tire-observability-')
    os.environ.update(TIRE_DATABASE_URL='sqlite:///' + (root / 'private.sqlite').as_posix(),
        DATABASE_URL='sqlite:///' + (root / 'private.sqlite').as_posix(), TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0',
        TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(root / 'objects'),
        TI_PARSER_BUNDLE_ROOT=str(root / 'bundles'), TI_OBSERVABILITY_ENABLED='1', TI_OBSERVABILITY_LOGS='1')
    setup_paths()
    import aiohttp
    import uvicorn
    from tire_api.adapters.transport import SafeHttpClient, SourceAccessError
    from tire_api.main import create_app
    from test_adapters import FakeResponse, FakeSession
    from test_core import FixtureRegistry, success

    class SyntheticRegistry(FixtureRegistry):
        def __init__(self):
            super().__init__()
            self.mode = 'live'
            self.http_calls = 0
            self.real_network_attempts = 0
            self.result = success(CANARY)

        def sources(self):
            return [{'id': 'michelin-us', 'name': 'Synthetic source, not official evidence', 'region': 'US',
                'source_class': 'test_fixture', 'status': 'ready', 'homepage': 'https://fixture.invalid',
                'supported_models': ['Fixture Tire']}]

        async def fetch(self, source_id, query, cached=None, *, on_observation=None):
            self.http_calls += 1
            status = {'live': 200, 'not_modified': 304, 'failure': 429}[self.mode]
            client = SafeHttpClient(frozenset({'www.michelinman.com'}))
            client.session = FakeSession([FakeResponse(status, chunks=[CANARY.encode()])])
            try:
                await client.get('https://www.michelinman.com/synthetic?secret=' + CANARY,
                    headers={'If-None-Match': cached.get('etag') or 'synthetic'} if cached else None)
            except SourceAccessError:
                return {'status': 'unavailable', 'reason': 'synthetic_http_failure'}
            finally:
                (output / 'fixture-counters.json').write_text(json.dumps({
                    'synthetic_http_calls': self.http_calls, 'real_network_attempts': self.real_network_attempts,
                    'real_model_calls': 0, 'real_parser_children': 0}), encoding='utf-8')
            if status == 304:
                return {'status': 'not_modified', 'url': self.result['url'], 'parser_version': 'fixture@1',
                        'etag': '"fixture-etag"'}
            return await super().fetch(source_id, query, cached, on_observation=on_observation)

    registry = SyntheticRegistry()
    def forbidden_network(*_args, **_kwargs):
        registry.real_network_attempts += 1
        raise AssertionError('External aiohttp transport forbidden in this explicit acceptance fixture')
    aiohttp.ClientSession = forbidden_network
    app = create_app(os.environ['TIRE_DATABASE_URL'], registry)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='warning'))

    @app.post('/fixture/control/{mode}')
    def control(mode: str):
        assert mode in {'live', 'not_modified', 'failure'}
        registry.mode = mode
        return {'mode': mode}

    @app.post('/fixture/shutdown')
    def shutdown():
        server.should_exit = True
        return {'shutdown_requested': True}

    server.run()


class Client:
    def __init__(self, base):
        self.base = base
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def request(self, path, body=None, headers=None):
        request = Request(self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            response = self.opener.open(request, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read().decode('utf-8')
            content = json.loads(raw) if 'application/json' in response.headers.get('Content-Type', '') else raw
            # Only expose presence, never a session/cookie value in artifacts.
            return response.status, content, bool(response.headers.get('Set-Cookie'))


def counts(path):
    with closing(sqlite3.connect('file:' + path.as_posix() + '?mode=ro', uri=True)) as db:
        tables = ('local_sessions', 'snapshots', 'fact_versions', 'verifications', 'query_runs',
                  'ai_requests', 'embedding_requests', 'parser_executions')
        return {name: db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0] for name in tables}


def main():
    output = WORKSPACE / '.artifacts/observability' / uuid4().hex
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'real_loopback_http_real_otel_sdk_synthetic_source_transport',
        'output': str(output), 'normal_database_used': False, 'checks': [],
        'model_and_worker_http_scope': 'Not exercised here; covered by separate SDK domain/worker target tests.'}
    child = None
    client = None
    private_root = None
    child_log = None
    error = None
    def checked(name):
        report['checks'].append(name)
        print(json.dumps({'check': name}, ensure_ascii=False), flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix='tire-observability-') as directory:
            private_root = Path(directory)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            client = Client(f'http://127.0.0.1:{port}')
            environment = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'PATH',
                'PATHEXT', 'USERPROFILE', 'PROCESSOR_ARCHITECTURE') if key in os.environ}
            environment.update(PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
            child_log = (output / 'server.log').open('w', encoding='utf-8')
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve', str(port),
                '--private-root', str(private_root), '--output', str(output)], env=environment,
                cwd=WORKSPACE, stdin=subprocess.DEVNULL, stdout=child_log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                deadline = time.monotonic() + 40
                while True:
                    assert child.poll() is None, 'Owned acceptance server exited during startup'
                    try:
                        status, initial, cookie = client.request('/v1/observability')
                        if status == 200:
                            break
                    except (URLError, OSError):
                        if time.monotonic() >= deadline:
                            raise
                    time.sleep(0.05)
                database = private_root / 'private.sqlite'
                assert not cookie and counts(database)['local_sessions'] == 0
                _, metrics_before, cookie = client.request('/v1/observability/metrics')
                _, initial_again, _ = client.request('/v1/observability')
                assert not cookie and initial_again['recent_spans'] == initial['recent_spans'] == []
                assert counts(database)['local_sessions'] == 0
                checked('diagnostics_before_session_are_read_only_and_not_self_counted')

                query = {'query': {'model': 'Fixture Tire', 'size': '265/40R20'}, 'fallback_policy': 'ask'}
                path = '/v1/sources/michelin-us/live-query'
                headers = {'traceparent': '00-' + '1' * 32 + '-' + '2' * 16 + '-01', 'baggage': 'private=' + CANARY,
                           'Authorization': 'Bearer ' + CANARY}
                status, first, _ = client.request(path, query, headers)
                assert status == 200 and first['data_state'] == 'live' and first['variants']
                checked('real_http_live_query_over_explicit_synthetic_transport')
                assert client.request('/fixture/control/not_modified', {})[0] == 200
                status, verified, _ = client.request(path, query)
                assert status == 200 and verified['data_state'] == 'live_verified_304'
                assert verified['provenance'][0]['snapshot_id'] == first['provenance'][0]['snapshot_id']
                checked('conditional_304_retains_original_snapshot')

                client.request('/fixture/control/failure', {})
                status, failed, _ = client.request(path, query)
                assert status == 200 and failed['data_state'] == 'consent_required' and not failed['variants'] and not failed['provenance']
                status, denied, _ = client.request('/v1/fallback-consents', {'query_id': failed['query_id'], 'decision': 'deny', 'scope': 'once'})
                assert status == 201
                assert client.request(path, {**query, 'consent_id': denied['id']})[0] == 403
                status, failed_again, _ = client.request(path, query)
                status, granted, _ = client.request('/v1/fallback-consents', {'query_id': failed_again['query_id'], 'decision': 'allow', 'scope': 'once'})
                assert status == 201
                before_fallback = json.loads((output / 'fixture-counters.json').read_text())['synthetic_http_calls']
                status, fallback, _ = client.request(path, {**query, 'consent_id': granted['id']})
                assert status == 200 and fallback['data_state'] == 'local_snapshot' and fallback['variants']
                assert json.loads((output / 'fixture-counters.json').read_text())['synthetic_http_calls'] == before_fallback
                assert client.request(path, {**query, 'consent_id': granted['id']})[0] == 409
                status, never, _ = client.request(path, {**query, 'fallback_policy': 'never'})
                assert status == 200 and never['data_state'] == 'source_unavailable' and not never['variants']
                checked('failure_denial_and_explicit_one_use_fallback_preserved')

                assert client.request(path, {'query': {'model': 'Fixture Tire', CANARY: True}})[0] == 422
                assert client.request('/not-found/' + CANARY + '?private=' + CANARY)[0] == 404
                client.request('/fixture/control/live', {})
                def concurrent(_):
                    return Client(client.base).request(path, query)[0:2]
                with ThreadPoolExecutor(max_workers=4) as pool:
                    responses = list(pool.map(concurrent, range(4)))
                assert all(status == 200 and body['data_state'] == 'live' for status, body in responses)
                checked('four_concurrent_real_http_requests_complete_without_cross_request_trace')

                before_diagnostics = counts(database)
                _, status_data, cookie = client.request('/v1/observability')
                _, metrics, cookie_metrics = client.request('/v1/observability/metrics')
                _, again, _ = client.request('/v1/observability')
                assert not cookie and not cookie_metrics and counts(database) == before_diagnostics
                assert status_data['recent_spans'] == again['recent_spans']
                _, metrics_again, _ = client.request('/v1/observability/metrics')
                assert metrics == metrics_again and metrics != metrics_before
                spans = status_data['recent_spans']
                by_id = {row['span_id']: row for row in spans}
                queries = [row for row in spans if row['name'] == 'source.query']
                assert {'live', 'live_verified_304', 'consent_required', 'source_unavailable', 'local_snapshot', 'error'} <= {
                    row['attributes']['outcome'] for row in queries}
                for row in queries:
                    parent = by_id[row['parent_span_id']]
                    assert parent['name'] == 'api.request' and parent['trace_id'] == row['trace_id']
                for name in ('source.http', 'db.ingestion_lock'):
                    nested = [row for row in spans if row['name'] == name and by_id.get(row['parent_span_id'], {}).get('name') == 'source.query']
                    assert nested and all(by_id[row['parent_span_id']]['trace_id'] == row['trace_id'] for row in nested)
                roots = [row for row in spans if row['name'] == 'api.request']
                assert len({row['trace_id'] for row in roots}) == len(roots)
                assert all(row['trace_id'] != '1' * 32 for row in roots)
                assert all(row['attributes'].get('route') not in {'/v1/observability', '/v1/observability/metrics'} for row in roots)
                exported = json.dumps(spans) + metrics
                for forbidden in (CANARY, first['query_id'], first['provenance'][0]['snapshot_id'],
                                  'www.michelinman.com', 'traceparent', 'baggage', 'Authorization'):
                    assert forbidden not in exported
                assert 'tire_operations_total' in metrics and 'tire_operation_duration' in metrics
                assert 'tire_ai_tokens' not in metrics
                assert before_diagnostics['ai_requests'] == before_diagnostics['embedding_requests'] == before_diagnostics['parser_executions'] == 0
                checked('real_sdk_parent_child_ids_safe_fields_and_prometheus_metrics')
                checked('repeated_diagnostics_create_no_sessions_or_self_spans_or_metrics')
                report['counts_before_shutdown'] = before_diagnostics
                report['span_counts'] = {name: sum(row['name'] == name for row in spans) for name in ('api.request', 'source.query', 'source.http', 'db.ingestion_lock')}
                report['fixture_counters'] = json.loads((output / 'fixture-counters.json').read_text())
                assert report['fixture_counters']['real_network_attempts'] == 0
                (output / 'observability.json').write_text(json.dumps(status_data, ensure_ascii=False, indent=2), encoding='utf-8')
                (output / 'metrics.prom').write_text(metrics, encoding='utf-8')
                report['status'] = 'passed'
            finally:
                if child.poll() is None:
                    try:
                        client.request('/fixture/shutdown', {})
                    except (URLError, OSError):
                        pass
                    try:
                        child.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait(timeout=5)
                report['child_exit_code'] = child.returncode
                child_log.close()
                child_log = None
                logs = (output / 'server.log').read_text(encoding='utf-8')
                assert CANARY not in logs, 'Private synthetic canary leaked into server log'
                report['correlated_log_records'] = sum(line.startswith('{"event":"operation_finished"') for line in logs.splitlines())
                report['owned_child_stopped'] = child.poll() is not None
        assert report['child_exit_code'] == 0 and report['owned_child_stopped'] and not private_root.exists()
        assert report['correlated_log_records'] > 0
    except Exception as cause:
        error = cause
        report.update(status='failed', error={'type': type(cause).__name__, 'message': str(cause)})
    finally:
        if child_log:
            child_log.close()
        report['private_storage_removed'] = private_root is not None and not private_root.exists()
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': report['status'], 'report': str(output / 'report.json')}, ensure_ascii=False), flush=True)
    if error:
        raise error


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--private-root', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--output', type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.serve is not None:
        serve(options.serve, options.private_root, options.output)
    else:
        main()
