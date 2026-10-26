"""Private R72 production HTTP/React workflow with a synthetic upstream session.

The real source transport executes against in-memory responses. No public DNS,
TLS/source authentication, normal database, provider or parser child is exercised.
"""
import argparse
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def serve(port, web_port, output, *, empty_policies=False):
    output = output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts').resolve())
    assert 1024 <= port <= 65535 and port not in {3000, 8000, web_port}
    assert 1024 <= web_port <= 65535 and web_port not in {3000, 8000}
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output.mkdir(parents=True, exist_ok=False)
    storage = ROOT / '.artifacts' / ('r72-web-' + uuid4().hex)
    storage.mkdir()
    database_path = storage / 'synthetic.sqlite'
    for name in list(os.environ):
        if name.startswith('TI_') or name in {'TIRE_DATABASE_URL', 'DATABASE_URL', 'TIRE_CORS_ORIGINS'}:
            del os.environ[name]
    policy_path = storage / 'policies.json'
    rights = {'rights_holder': 'Project fixture author',
              'basis': 'Project-authored synthetic PDF; local QA only, not professional test evidence.',
              'license_url': None, 'store_original': True, 'workspace_reopen': True,
              'quote_identifiers': True, 'provider_use': False, 'export': False}
    policies = [{'policy_id': 'qa-source', 'title': 'R72 项目合成 PDF · 受控来源响应',
                 'publisher': 'Project-authored synthetic QA', 'edition': 'fixture@1', 'published_at': None,
                 'source_reference_url': 'https://fixture.invalid/test',
                 'download_url': 'https://source-fixture.invalid/begin',
                 'redirect_urls': ['https://source-fixture.invalid/material.pdf'], 'rights': rights},
                {'policy_id': 'qa-failure', 'title': 'R72 合成失败来源 · 503',
                 'publisher': 'Project-authored synthetic QA', 'edition': None, 'published_at': None,
                 'source_reference_url': 'https://fixture.invalid/test',
                 'download_url': 'https://failure-fixture.invalid/material.pdf',
                 'redirect_urls': [], 'rights': rights},
                {'policy_id': 'qa-robots-denied', 'title': 'R72 合成 robots 禁止来源',
                 'publisher': 'Project-authored synthetic QA', 'edition': None, 'published_at': None,
                 'source_reference_url': 'https://fixture.invalid/test',
                 'download_url': 'https://denied-fixture.invalid/material.pdf',
                 'redirect_urls': [], 'rights': rights}]
    if empty_policies:
        policies = []
    policy_path.write_text(json.dumps({'schema': 'source-material-policies@1', 'policies': policies}), encoding='utf-8')
    os.environ.update(
        TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
        TI_OBJECT_STORE_ROOT=str(storage / 'objects'), TI_OBJECT_STORE_BACKEND='filesystem',
        TI_PARSER_BUNDLE_ROOT=str(storage / 'bundles'), TI_SOURCE_MATERIAL_POLICIES_FILE=str(policy_path),
        TIRE_CORS_ORIGINS=f'http://127.0.0.1:{web_port},http://localhost:{web_port}',
    )
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    sources = ['apps/api/tire_api/' + name + '.py' for name in (
        'material_source_policy', 'material_source_transport', 'source_material_models', 'source_materials',
        'documents', 'object_store', 'main', 'db', 'migrations', 'auth', 'domain',
        'test_sku_links', 'test_sku_link_models', 'test_events')]
    sources += ['apps/api/tire_api/adapters/transport.py', 'apps/api/tire_api/adapters/robots.py',
                'apps/api/tests/test_fitment_relations.py', 'apps/api/tests/test_test_events.py',
                'scripts/source_material_web_fixture.py']
    hashes = lambda: {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in sources}
    before = hashes()
    platform.uname()
    counters = {'external_network_attempts': 0, 'child_process_attempts': 0, 'normal_database_attempts': 0}

    def audit(event, arguments):
        if event == 'subprocess.Popen':
            counters['child_process_attempts'] += 1
            raise RuntimeError('Children forbidden in private R72 QA')
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
            if address not in {'127.0.0.1', '::1', 'localhost'}:
                counters['external_network_attempts'] += 1
                raise RuntimeError('External networking forbidden in private R72 QA')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            if not Path(str(arguments[0])).resolve().is_relative_to(storage):
                counters['normal_database_attempts'] += 1
                raise RuntimeError('R72 private database required')
    sys.addaudithook(audit)

    import uvicorn
    from fastapi import Response
    from reportlab.pdfgen.canvas import Canvas
    from sqlalchemy import func, select
    from tire_api.db import Base, EvidenceDocument, FactVersion, Snapshot, UserSession, uid, utcnow
    from tire_api.domain import VariantInput
    from tire_api.main import create_app
    from tire_api import material_source_transport
    from tire_api.test_events import EventPayload, TireTestEvent, TireTestRevision, append
    from test_fitment_relations import NoNetworkRegistry, seed_tire, tire_payload
    from test_test_events import PAYLOAD

    identity = VariantInput.model_validate(tire_payload()).identity()
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(612, 792), invariant=True)
    lines = ['PROJECT-AUTHORED SYNTHETIC QA; NOT A REAL TEST PUBLICATION',
             'Event: R72 Synthetic same-event test. Participant a: Synthetic Tire.',
             'Actual upstream session is a fixture, not public HTTPS or publisher authentication.']
    lines += [f'{k}: {json.dumps(v, ensure_ascii=True)}' for k, v in identity.items()]
    for index, line in enumerate(lines):
        canvas.setFont('Helvetica', 8)
        canvas.drawString(22, 755 - index * 21, line)
    canvas.save()
    pdf = buffer.getvalue()
    (output / 'synthetic-source.pdf').write_bytes(pdf)
    upstream = []

    class Body:
        def __init__(self, body):
            self.body = body

        async def iter_chunked(self, size):
            for start in range(0, len(self.body), min(size, 503)):
                yield self.body[start:start + min(size, 503)]

    class UpstreamResponse:
        def __init__(self, url):
            self.url, self.status = url, 200
            self.headers = {'Content-Type': 'application/pdf', 'Content-Encoding': 'identity'}
            body = pdf
            if url.endswith('/robots.txt'):
                self.headers['Content-Type'] = 'text/plain; charset=utf-8'
                body = b'User-agent: *\nDisallow: /\n' if 'denied-fixture' in url else b'User-agent: *\nAllow: /\n'
            elif url == 'https://source-fixture.invalid/begin':
                self.status, body = 302, b''
                self.headers['Location'] = 'https://source-fixture.invalid/material.pdf'
            elif url == 'https://failure-fixture.invalid/material.pdf':
                self.status, body = 503, b''
            elif url != 'https://source-fixture.invalid/material.pdf':
                raise RuntimeError('Unexpected synthetic upstream URL')
            self.content_length = len(body)
            self.headers['Content-Length'] = str(len(body))
            self.content = Body(body)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    class FixtureSession:
        def __init__(self, *args, **kwargs):
            assert not args and kwargs.get('trust_env') is False
            assert kwargs.get('auto_decompress') is False
            self.connector = kwargs.get('connector')

        def get(self, url, **kwargs):
            assert kwargs.get('allow_redirects') is False
            upstream.append({'method': 'GET', 'url': str(url)})
            return UpstreamResponse(str(url))

        def request(self, method, url, **kwargs):
            assert method == 'GET'
            return self.get(url, **kwargs)

        async def close(self):
            if self.connector:
                await self.connector.close()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            await self.close()

    # Process-local fixture substitution; no test injection option in the product.
    material_source_transport.aiohttp.ClientSession = FixtureSession
    app = create_app('sqlite:///' + database_path.as_posix(), NoNetworkRegistry())
    original_lifespan = app.router.lifespan_context
    state = {'synthetic_only': True, 'normal_database_used': False, 'provider_calls': 0,
             'public_source_dns_tls_exercised': False, 'upstream_layer': 'in-memory aiohttp session',
             'production_source_transport_executed': True, 'material_sha256': hashlib.sha256(pdf).hexdigest(),
             'material_byte_count': len(pdf), 'configured_policy_count': len(policies)}

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            with application.state.database.sessions() as db:
                actor = UserSession(id=uid(), expires_at=utcnow() + timedelta(hours=3))
                db.add(actor)
                db.commit()
                seed_id = actor.id
            variant, snapshot, fact = seed_tire(application.state.database, seed_id)
            with application.state.database.sessions() as db:
                event = TireTestEvent(id=uid())
                db.add(event)
                db.flush()
                payload = deepcopy(PAYLOAD['event'])
                payload.update(title='R72 合成来源原件与既有人工桥', organization='Project-authored synthetic QA',
                               tested_size='245/40R20', source_url='https://fixture.invalid/test',
                               rights_basis=rights['basis'])
                payload['participants'][0].update(brand='Synthetic', model='Synthetic Tire',
                                                  source_designation='Synthetic participant a; page 1')
                recorded = append(db, event.id, EventPayload.model_validate(payload).model_dump(mode='json'),
                                  'create', 'active', 'Synthetic QA fixture', rights['basis'], seed_id, 1)
                state.update(event_id=recorded['id'], event_revision_id=recorded['revision_id'],
                             event_revision=recorded['revision'], variant_id=variant,
                             tire_snapshot_id=snapshot, fact_version_id=fact, identity=identity)
            (output / 'started.json').write_text(json.dumps({
                'schema': 'r72-private-runtime@1', 'state': state, 'sources_before': before,
                'private_storage': storage.relative_to(ROOT).as_posix(),
                'scope': 'production HTTP/React and real source transport with synthetic upstream session',
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'ready': True, 'port': port}), flush=True)
            yield
        (output / 'stopped.json').write_text(json.dumps({
            'shutdown_complete': True, 'counters': counters, 'upstream_requests': upstream,
            'sources_before': before, 'sources_after': hashes(), 'sources_stable': before == hashes(),
        }, indent=2), encoding='utf-8')

    app.router.lifespan_context = lifespan
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
                                         log_level='warning', access_log=False))

    @app.get('/fixture/state')
    def fixture_state():
        with app.state.database.sessions() as db:
            counts = {n: db.scalar(select(func.count()).select_from(m)) for n, m in (
                ('documents', EvidenceDocument), ('facts', FactVersion), ('snapshots', Snapshot),
                ('test_event_revisions', TireTestRevision))}
            counts.update({table.name: db.scalar(select(func.count()).select_from(table))
                           for table in Base.metadata.tables.values() if table.name.startswith('source_material')})
        return {**state, 'counts': counts, 'counters': dict(counters), 'upstream_requests': list(upstream)}

    @app.get('/fixture/material')
    def fixture_material():
        return Response(pdf, media_type='application/pdf', headers={'Cache-Control': 'no-store'})

    @app.post('/fixture/shutdown')
    def shutdown():
        server.should_exit = True
        return {'shutdown_requested': True}

    server.run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--web-port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--empty-policies', action='store_true')
    args = parser.parse_args()
    serve(args.port, args.web_port, args.output, empty_policies=args.empty_policies)
