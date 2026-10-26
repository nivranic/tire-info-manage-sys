"""R122 synthetic query sources through real business routes and a new private DB.

No upstream requests or parser execution receipts are claimed. Root alone launches
this bounded fixture, never a default/normal application or retained database.
"""
import argparse
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import hashlib
from itertools import count
import json
import os
from pathlib import Path
import platform
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]


def serve(port, web_port, output):
    output = output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts').resolve()) and not output.exists()
    assert 1024 <= port <= 65535 and port not in {3000, 8000}
    assert 1024 <= web_port <= 65535 and web_port not in {3000, 8000, port}
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output.mkdir()
    storage = output / 'storage'
    storage.mkdir()
    database_path = storage / 'synthetic.sqlite'
    for name in list(os.environ):
        if name.startswith('TI_') or name in {'TIRE_DATABASE_URL', 'DATABASE_URL', 'TIRE_CORS_ORIGINS'}:
            del os.environ[name]
    os.environ.update(TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
        TI_OBJECT_STORE_ROOT=str(storage / 'objects'), TI_OBJECT_STORE_BACKEND='filesystem',
        TI_PARSER_BUNDLE_ROOT=str(storage / 'bundles'),
        TIRE_CORS_ORIGINS=f'http://127.0.0.1:{web_port},http://localhost:{web_port}')
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'scripts')]
    platform.uname()  # Prewarm Windows' lazy platform child before the child fence.
    counters = {'external_network_attempts': 0, 'child_process_attempts': 0,
                'normal_database_attempts': 0}

    def audit(event, arguments):
        if event == 'subprocess.Popen':
            counters['child_process_attempts'] += 1
            raise RuntimeError('No children in private R122 query fixture')
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
            if address not in {'127.0.0.1', '::1', 'localhost'}:
                counters['external_network_attempts'] += 1
                raise RuntimeError('No external networking in private R122 query fixture')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            if not Path(str(arguments[0])).resolve().is_relative_to(storage):
                counters['normal_database_attempts'] += 1
                raise RuntimeError('R122 new private database required')
    sys.addaudithook(audit)

    import uvicorn
    from sqlalchemy import func, select
    from tire_api.ai_models import AIRequest
    from tire_api.embedding_models import EmbeddingRequest
    from tire_api.main import create_app
    # Reuse the existing synthetic row schema and registry interface; no old
    # fixture_application / self_test / default listener is invoked.
    from query_filter_browser_qa import FilterRegistry, fixture_rows

    model = 'R122 Synthetic Tire'
    source_ids = ('r122-selection-a', 'r122-selection-b')
    diagnostic_request = ContextVar('r122_diagnostic_request', default=None)
    diagnostic_sequence = count(1)
    request_sequence = count(1)
    diagnostic_routes = {
        ('GET', '/v1/auth/me'), ('GET', '/v1/source-settings'),
        ('POST', '/fixture/shutdown'),
        *(('POST', '/v1/sources/' + source_id + '/live-query') for source_id in source_ids),
    }

    def diagnostic(event, **fields):
        # All callers supply fixed stage/method/path labels and numeric metadata.
        # No request payload, headers, identity, SQL or exception text is read.
        row = {'sequence': next(diagnostic_sequence), 'event': event, **fields}
        request_id = diagnostic_request.get()
        if request_id is not None:
            row['request'] = request_id
        with (output / 'diagnostics.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, separators=(',', ':')) + '\n')
            stream.flush()

    def diagnostic_error(event, error, **fields):
        code = getattr(getattr(error, 'orig', error), 'sqlite_errorcode', None)
        context = error.__context__
        contexts = []
        for _ in range(3):
            if context is None:
                break
            item = {'error_class': type(context).__name__}
            original = getattr(context, 'orig', context)
            for name in ('sqlite_errorcode', 'winerror', 'errno'):
                number = getattr(original, name, None)
                if type(number) is int:
                    item[name] = number
            contexts.append(item)
            context = context.__context__
        diagnostic(event, error_class=type(error).__name__,
                   **({'sqlite_errorcode': code} if type(code) is int else {}),
                   **({'contexts': contexts} if contexts else {}), **fields)

    # Private-process instrumentation only; forward arguments/results and preserve
    # the original callable metadata and exception behavior.
    from tire_api.service import QueryService

    def instrument_sync(method):
        original = getattr(QueryService, method)

        @wraps(original)
        def observed(*args, **kwargs):
            diagnostic('service_enter', method=method)
            try:
                value = original(*args, **kwargs)
            except BaseException as error:
                diagnostic_error('service_error', error, method=method)
                raise
            diagnostic('service_exit', method=method)
            return value

        setattr(QueryService, method, observed)

    original_execute = QueryService._execute

    @wraps(original_execute)
    async def observed_execute(*args, **kwargs):
        diagnostic('service_enter', method='_execute')
        try:
            value = await original_execute(*args, **kwargs)
        except BaseException as error:
            diagnostic_error('service_error', error, method='_execute')
            raise
        diagnostic('service_exit', method='_execute')
        return value

    QueryService._execute = observed_execute
    for method in ('pin_source_access', 'transport_cache', 'record_success', '_lock_ingestion', 'result'):
        instrument_sync(method)

    template = fixture_rows(model)[0]
    # Explicit synthetic namespace plus complete identity fields lets one exact
    # record repeat across sources. This is no claim of a real manufacturer SKU.
    template['facts']['product_code_type'] = 'MSPN'
    rows_a = []
    for index in range(26):
        row = deepcopy(template)
        row['manufacturer_product_code'] = 'R122-A-' + str(index + 1).zfill(3)
        row['source_variant_name'] = 'Project-owned synthetic result ' + str(index + 1)
        row['size'] = '265/40R20'
        row['facts']['gtin'] = None
        row['facts']['fixture_notice'] = 'Project-authored synthetic source; not a real supplier SKU.'
        rows_a.append(row)
    rows_b = [deepcopy(rows_a[0])]
    for index in range(2):
        row = deepcopy(template)
        row['manufacturer_product_code'] = 'R122-B-' + str(index + 1).zfill(3)
        row['source_variant_name'] = 'Project-owned synthetic source B result ' + str(index + 1)
        row['size'] = '265/40R20'
        row['facts']['gtin'] = None
        row['facts']['fixture_notice'] = 'Project-authored synthetic source; not a real supplier SKU.'
        rows_b.append(row)

    class SelectionRegistry(FilterRegistry):
        supports_parser_deployments = False

        def __init__(self):
            super().__init__(model=model)

        def sources(self):
            return [{'id': source_id, 'name': 'R122 合成来源 ' + label,
                     'region': 'US', 'source_class': 'test_fixture', 'status': 'ready',
                     'homepage': 'https://fixture.invalid/r122/' + label,
                     'description': 'Project-authored synthetic source for local verification only.',
                     'supported_models': [model], 'default_model': model, 'target_kind': 'tire'}
                    for source_id, label in zip(source_ids, ('A', 'B'), strict=True)]

        async def fetch(self, source_id, query, cached=None, *, on_observation=None):
            assert source_id in source_ids and query.get('model') == model
            self.calls.append({'source_id': source_id})
            rows = deepcopy(rows_a if source_id == source_ids[0] else rows_b)
            result = {'status': 'ok', 'url': 'https://fixture.invalid/r122/' + source_id,
                'content_type': 'application/json', 'parser_version': 'r122-synthetic@1',
                'body': json.dumps({'synthetic_only': True, 'rows': rows}, ensure_ascii=False),
                'etag': '"r122-synthetic-v1"', 'variants': rows}
            if on_observation:
                diagnostic('registry_observation_enter')
                try:
                    on_observation(result)
                except BaseException as error:
                    diagnostic_error('registry_observation_error', error)
                    raise
                diagnostic('registry_observation_exit')
            return result

    def source_hashes():
        names = [p for p in (ROOT / 'apps/api/tire_api').rglob('*.py')]
        names += [ROOT / 'scripts/query_filter_browser_qa.py', Path(__file__).resolve()]
        return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(names)}

    before = source_hashes()
    registry = SelectionRegistry()
    app = create_app('sqlite:///' + database_path.as_posix(), registry)
    original_lifespan = app.router.lifespan_context
    state = {'synthetic_only': True, 'normal_database_used': False,
             'real_source_calls': 0, 'provider_calls': 0, 'model': model,
             'source_ids': list(source_ids), 'source_row_counts': [26, 3],
             'parser_execution': 'synthetic_output_no_subprocess_receipt'}

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            (output / 'started.json').write_text(json.dumps({**state, 'sources_before': before},
                ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'ready': True, 'port': port, 'synthetic_only': True}), flush=True)
            yield
        (output / 'stopped.json').write_text(json.dumps({'shutdown_complete': True,
            'counters': counters, 'source_calls': len(registry.calls),
            'sources_before': before, 'sources_after': source_hashes(),
            'sources_stable': before == source_hashes()}, indent=2), encoding='utf-8')

    app.router.lifespan_context = lifespan

    class DiagnosticApplication:
        """Observe fixed routes outside every unchanged application middleware."""

        async def __call__(self, scope, receive, send):
            route = (scope.get('method'), scope.get('path'))
            if scope['type'] != 'http' or route not in diagnostic_routes:
                return await app(scope, receive, send)
            token = diagnostic_request.set(next(request_sequence))
            status = None

            async def observed_send(message):
                nonlocal status
                if message['type'] == 'http.response.start':
                    status = message['status']
                await send(message)

            diagnostic('http_enter', method=route[0], path=route[1])
            try:
                await app(scope, receive, observed_send)
            except BaseException as error:
                diagnostic_error('http_error', error, method=route[0], path=route[1], status=status)
                raise
            else:
                diagnostic('http_end', method=route[0], path=route[1], status=status)
            finally:
                diagnostic_request.reset(token)

    server = uvicorn.Server(uvicorn.Config(DiagnosticApplication(), host='127.0.0.1', port=port,
                                         log_level='warning', access_log=False))

    @app.get('/fixture/state')
    def fixture_state():
        with app.state.database.sessions() as db:
            model_requests = db.scalar(select(func.count()).select_from(AIRequest))
            embedding_requests = db.scalar(select(func.count()).select_from(EmbeddingRequest))
        return {**state, 'counters': dict(counters), 'source_calls': len(registry.calls),
                'model_requests': model_requests, 'embedding_requests': embedding_requests}

    @app.post('/fixture/shutdown')
    def shutdown():
        server.should_exit = True
        return {'shutdown_requested': True}

    server.run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--web-port', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    serve(args.port, args.web_port, args.output)
