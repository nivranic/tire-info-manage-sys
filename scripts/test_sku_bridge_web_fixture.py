"""R71 private production HTTP routes with project-authored synthetic evidence only.

No normal database, external sources, model providers or parser children are allowed.
Credentials are created by the browser via production account routes, never persisted here.
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


def serve(port, web_port, output):
    output = output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts').resolve())
    assert 1024 <= port <= 65535 and port not in {3000, 8000}
    assert 1024 <= web_port <= 65535 and web_port not in {3000, 8000, port}
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output.mkdir(parents=True, exist_ok=False)
    storage = ROOT / '.artifacts' / ('r71-web-' + uuid4().hex)
    storage.mkdir()
    database_path = storage / 'synthetic.sqlite'
    for name in list(os.environ):
        if name.startswith('TI_') or name in {'TIRE_DATABASE_URL', 'DATABASE_URL', 'TIRE_CORS_ORIGINS'}:
            del os.environ[name]
    os.environ.update(
        TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
        TI_OBJECT_STORE_ROOT=str(storage / 'objects'), TI_OBJECT_STORE_BACKEND='filesystem',
        TI_PARSER_BUNDLE_ROOT=str(storage / 'bundles'),
        TIRE_CORS_ORIGINS=f'http://127.0.0.1:{web_port},http://localhost:{web_port}',
    )
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    bound_sources = ['apps/api/tire_api/' + name + '.py' for name in (
        'test_sku_links', 'test_sku_link_models', 'db', 'migrations', 'main', 'auth',
        'domain', 'test_events', 'documents', 'object_store', 'interest_events', 'identity_contract')]
    bound_sources += ['apps/api/tests/test_fitment_relations.py', 'apps/api/tests/test_test_events.py',
                      'scripts/test_sku_bridge_web_fixture.py']
    source_hashes = lambda: {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in bound_sources}
    sources_before = source_hashes()
    platform.uname()  # Prewarm Windows lazy platform subprocess before the child fence.
    counters = {'external_network_attempts': 0, 'child_process_attempts': 0,
                'normal_database_attempts': 0}

    def audit(event, arguments):
        if event == 'subprocess.Popen':
            counters['child_process_attempts'] += 1
            raise RuntimeError('Children forbidden in private R71 QA')
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
            if address not in {'127.0.0.1', '::1', 'localhost'}:
                counters['external_network_attempts'] += 1
                raise RuntimeError('External networking forbidden in private R71 QA')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            if not Path(str(arguments[0])).resolve().is_relative_to(storage):
                counters['normal_database_attempts'] += 1
                raise RuntimeError('R71 private database required')
    sys.addaudithook(audit)

    import uvicorn
    from fastapi import Response
    from reportlab.pdfgen.canvas import Canvas
    from sqlalchemy import func, select
    from tire_api.db import FactVersion, Snapshot, UserSession, uid, utcnow
    from tire_api.domain import VariantInput
    from tire_api.main import create_app
    from tire_api.test_events import EventPayload, TireTestEvent, TireTestRevision, append
    from test_fitment_relations import NoNetworkRegistry, seed_tire, tire_payload
    from test_test_events import PAYLOAD

    app = create_app('sqlite:///' + database_path.as_posix(), NoNetworkRegistry())
    original_lifespan = app.router.lifespan_context
    state = {'synthetic_only': True, 'normal_database_used': False, 'provider_calls': 0}
    pdf_buffer = BytesIO()
    identity = VariantInput.model_validate(tire_payload()).identity()
    canvas = Canvas(pdf_buffer, pagesize=(612, 792), invariant=True)
    y = 755
    lines = ['PROJECT-AUTHORED SYNTHETIC QA; NOT A REAL TEST PUBLICATION',
             'Event: R71 Synthetic same-event test. Participant a: Synthetic Tire.',
             'Source reference is a fixture.invalid placeholder. No source authenticity is claimed.']
    lines += [f'{field}: {json.dumps(value, ensure_ascii=True)}' for field, value in identity.items()]
    lines += ['Tested size: 245/40R20; synthetic wet braking: 38.00 m; source rank: 3.',
              'Rights: Project-authored synthetic material for local QA, not professional test evidence.']
    for line in lines:
        canvas.setFont('Helvetica', 8)
        canvas.drawString(22, y, line)
        y -= 21
    canvas.save()
    pdf = pdf_buffer.getvalue()
    (output / 'synthetic-source.pdf').write_bytes(pdf)

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            with application.state.database.sessions() as db:
                seed = UserSession(id=uid(), expires_at=utcnow() + timedelta(hours=3))
                db.add(seed)
                db.commit()
                seed_id = seed.id
            variant, snapshot, fact = seed_tire(application.state.database, seed_id)
            with application.state.database.sessions() as db:
                event = TireTestEvent(id=uid())
                db.add(event)
                db.flush()
                data = deepcopy(PAYLOAD['event'])
                data.update(title='R71 合成验收 · 测试对象与精确 SKU', organization='Project-authored synthetic QA',
                            tested_size='245/40R20', source_url='https://fixture.invalid/test',
                            rights_basis='Project-authored synthetic fixture for local verification only.')
                data['participants'][0].update(brand='Synthetic', model='Synthetic Tire',
                                               source_designation='Synthetic participant a; see material page 1')
                recorded = append(db, event.id, EventPayload.model_validate(data).model_dump(mode='json'),
                                  'create', 'active', 'Synthetic QA fixture', 'Project-authored synthetic evidence',
                                  seed_id, 1)
                state.update(event_id=recorded['id'], event_revision_id=recorded['revision_id'],
                             event_revision=recorded['revision'], variant_id=variant,
                             tire_snapshot_id=snapshot, fact_version_id=fact, identity=identity)
            (output / 'started.json').write_text(json.dumps({
                'schema': 'test-sku-bridge-private-runtime@1', 'state': state,
                'private_storage': storage.relative_to(ROOT).as_posix(),
                'scope': 'production HTTP and React UI; synthetic material only',
                'sources_before': sources_before,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'ready': True, 'port': port, 'event_id': state['event_id']}), flush=True)
            yield
        (output / 'stopped.json').write_text(json.dumps({
            'shutdown_complete': True, 'counters': counters,
            'sources_before': sources_before, 'sources_after': source_hashes(),
            'sources_stable': sources_before == source_hashes(),
        }, indent=2), encoding='utf-8')

    app.router.lifespan_context = lifespan
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
                                         log_level='warning', access_log=False))

    @app.get('/fixture/state')
    def fixture_state():
        from tire_api.test_sku_link_models import TestSkuLinkRevision
        with app.state.database.sessions() as db:
            counts = {name: db.scalar(select(func.count()).select_from(model))
                      for name, model in [('event_revisions', TireTestRevision), ('snapshots', Snapshot),
                                          ('facts', FactVersion), ('link_revisions', TestSkuLinkRevision)]}
        return {**state, 'counts': counts, 'counters': dict(counters)}

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
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--web-port', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    serve(args.port, args.web_port, args.output)
