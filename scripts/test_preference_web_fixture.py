"""Private real API for preference interpretation browser QA; never use the normal DB.

Run with apps/api/.venv/Scripts/python.exe and explicit --port/--output.
All data is synthetic. AI, external networking and parser children are disabled.
"""
import argparse
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import platform
import socket
import sys


ROOT = Path(__file__).resolve().parents[1]


def serve(port, web_port, output):
    output = output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts').resolve())
    assert 1024 <= port <= 65535 and port not in {3000, 8000}
    assert 1024 <= web_port <= 65535 and web_port not in {3000, 8000}
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output.mkdir(parents=True, exist_ok=False)
    storage = output / 'storage'
    storage.mkdir()
    database_path = storage / 'synthetic.sqlite'
    for name in list(os.environ):
        if name.startswith('TI_') or name in {'TIRE_DATABASE_URL', 'DATABASE_URL', 'TIRE_CORS_ORIGINS'}:
            del os.environ[name]
    os.environ.update(
        TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_LOGS='0',
        TI_OBJECT_STORE_ROOT=str(storage / 'objects'), TI_OBJECT_STORE_BACKEND='filesystem',
        TI_PARSER_BUNDLE_ROOT=str(storage / 'bundles'),
        TIRE_CORS_ORIGINS=f'http://127.0.0.1:{web_port},http://localhost:{web_port}',
    )
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    platform.uname()  # Prewarm Windows' lazy version subprocess before fencing children.
    counters = {'external_network_attempts': 0, 'parser_children': 0}

    def audit(event, arguments):
        if event == 'subprocess.Popen':
            counters['parser_children'] += 1
            raise RuntimeError('Parser children forbidden in private preference QA')
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
            if address not in {'127.0.0.1', '::1', 'localhost'}:
                counters['external_network_attempts'] += 1
                raise RuntimeError('External networking forbidden in private preference QA')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            assert Path(str(arguments[0])).resolve().is_relative_to(storage), 'private_database_required'
    sys.addaudithook(audit)

    import uvicorn
    from sqlalchemy import func, select
    from tire_api.db import DrivingPreferenceRevision, UserSession, uid, utcnow
    from tire_api.main import create_app
    from tire_api.test_events import TireTestEvent, TireTestRevision, EventPayload, append
    from test_test_events import PAYLOAD
    from copy import deepcopy
    from datetime import timedelta

    class NoSources:
        supports_parser_deployments = False

        def sources(self):
            return []

    app = create_app('sqlite:///' + database_path.as_posix(), NoSources())
    original_lifespan = app.router.lifespan_context
    state = {'normal_database_used': False, 'provider_calls': 0, 'synthetic_only': True}

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            payload = deepcopy(PAYLOAD['event'])
            payload['title'] = '合成验收 · 同场驾驶偏好'
            payload['metrics'][1]['label'] = '<script>window.preferenceCanary=1</script>噪声'
            payload['metrics'].append({'key': 'wet_second', 'label': '第二项湿地观察', 'unit': 'points',
                                      'protocol': 'Synthetic second wet method', 'direction': 'higher'})
            for person, raw in [('a', '-0'), ('b', '0')]:
                payload['measurements'].append({'participant_key': person, 'metric_key': 'wet_second',
                                               'raw_value': raw, 'source_rank': None,
                                               'evidence_span': f'Synthetic {person}: {raw}',
                                               'evidence_locator': f'Synthetic row {person}'})
            payload = EventPayload.model_validate(payload).model_dump(mode='json')
            with application.state.database.sessions() as db:
                seed = UserSession(id=uid(), expires_at=utcnow() + timedelta(hours=2))
                db.add(seed)
                item = TireTestEvent(id=uid())
                db.add(item)
                db.flush()
                row = append(db, item.id, payload, 'create', 'active', 'Synthetic QA',
                             'Project-authored synthetic browser fixture', seed.id, 1)
                state['event_id'] = row['id']
            (output / 'fixture-start.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
            print(json.dumps({'ready': True, 'port': port, 'event_id': state['event_id']}), flush=True)
            yield
            with application.state.database.sessions() as db:
                state.update(event_revisions=db.scalar(select(func.count()).select_from(TireTestRevision)),
                             preference_revisions=db.scalar(select(func.count()).select_from(DrivingPreferenceRevision)))
            (output / 'fixture-final.json').write_text(json.dumps({**state, **counters}, indent=2), encoding='utf-8')

    app.router.lifespan_context = lifespan
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', access_log=False))

    @app.get('/fixture/state')
    def current_state():
        with app.state.database.sessions() as db:
            return {**state, **counters,
                    'event_revisions': db.scalar(select(func.count()).select_from(TireTestRevision)),
                    'preference_revisions': db.scalar(select(func.count()).select_from(DrivingPreferenceRevision))}

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
    options = parser.parse_args()
    serve(options.port, options.web_port, options.output)
