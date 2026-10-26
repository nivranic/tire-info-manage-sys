"""R96 private real HTTP fixture. Synthetic receipts; pinned historical S2 bytes; no parser child."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
API_PORT, WEB_PORT = 18966, 18967
S2 = ROOT / '.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/xiaomi-first-generation-2.pdf'
S2_SHA, S2_SIZE = '0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f', 3240150


def serve(output):
    output = output.resolve()
    assert output.parent == (ROOT / '.artifacts').resolve() and re.fullmatch(r'r96-http-[a-f0-9]{32}', output.name) and not output.exists()
    output.mkdir()
    storage = output / 'private'
    storage.mkdir()
    temporary = storage / 'tmp'
    temporary.mkdir()
    tempfile.tempdir = str(temporary)
    for key in list(os.environ):
        if key.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_OPENAI_', 'OTEL_', 'SENTRY_', 'NEXT_PUBLIC_')) or key.upper() == 'DATABASE_URL' or key.lower().endswith('_proxy'):
            del os.environ[key]
    database_path = storage / 'private.sqlite'
    database_url = 'sqlite:///' + database_path.as_posix()
    os.environ.update(TIRE_DATABASE_URL=database_url, DATABASE_URL=database_url,
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
        TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(storage / 'objects'),
        TI_PARSER_BUNDLE_ROOT=str(storage / 'bundles'), TIRE_CORS_ORIGINS=f'http://127.0.0.1:{WEB_PORT}',
        TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
    counts = {'external_network_attempts': 0, 'child_process_attempts': 0, 'normal_database_attempts': 0,
              'listener_binds': 0, 'allowed_loopback_connects': 0, 'internal_socketpair_connections': 0}
    pair_state, original_pair = threading.local(), socket.socketpair

    def guarded_pair(*args, **kwargs):
        assert getattr(pair_state, 'current', None) is None
        pair_state.current = {'listener': None, 'connected': False}
        try:
            return original_pair(*args, **kwargs)
        finally:
            pair_state.current = None

    def audit(event, arguments):
        pair = getattr(pair_state, 'current', None)
        if event == 'socket.bind':
            address = arguments[1]
            if pair is not None and pair['listener'] is None and address in (('127.0.0.1', 0), ('::1', 0)):
                pair['listener'] = arguments[0]
                return
            if address == ('127.0.0.1', API_PORT) and counts['listener_binds'] == 0:
                counts['listener_binds'] += 1
                return
            counts['external_network_attempts'] += 1
            raise RuntimeError('r96_exact_listener_required')
        if event == 'socket.connect':
            address = arguments[1]
            if pair is not None and pair['listener'] is not None and not pair['connected']:
                expected = pair['listener'].getsockname()
                if address == expected and expected[0] in ('127.0.0.1', '::1') and expected[1] != 0:
                    pair['connected'] = True
                    counts['internal_socketpair_connections'] += 1
                    return
            if address in (('127.0.0.1', API_PORT), ('127.0.0.1', WEB_PORT)):
                counts['allowed_loopback_connects'] += 1
                return
            counts['external_network_attempts'] += 1
            raise RuntimeError('r96_external_network_forbidden')
        if event in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr', 'socket.getnameinfo', 'socket.sendto', 'socket.sendmsg'):
            counts['external_network_attempts'] += 1
            raise RuntimeError('r96_name_resolution_datagram_forbidden')
        if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn'):
            counts['child_process_attempts'] += 1
            raise RuntimeError('r96_child_forbidden')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            if Path(str(arguments[0])).resolve() != database_path:
                counts['normal_database_attempts'] += 1
                raise RuntimeError('r96_exact_private_database_required')

    if sys.platform == 'win32':
        socket.socketpair = guarded_pair
        def native_win32_ver(release='', version='', csd='', ptype=''):
            value = sys.getwindowsversion()
            return str(value.major), f'{value.major}.{value.minor}.{value.build}', value.service_pack, ptype
        platform.win32_ver = native_win32_ver
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.addaudithook(audit)

    def source_hashes():
        paths = {Path(__file__).resolve()}
        for directory in ('apps/api/tire_api', 'apps/web/app', 'apps/web/components', 'packages/api-client/src', 'packages/domain-types/src'):
            paths.update(p for p in (ROOT / directory).rglob('*') if p.is_file() and p.suffix in ('.py', '.ts', '.tsx', '.css', '.json'))
        paths.update(ROOT / p for p in ('apps/api/tests/test_vehicle_raw.py', 'apps/api/tests/admin_support.py'))
        return {p.relative_to(ROOT).as_posix(): {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(paths)}

    before = source_hashes()
    state = {'schema': 'r96-private-http@1', 'synthetic_only': True, 'receipt_is_synthetic': True,
        'historical_s2_offline_replay': True, 'actual_parser_child': False, 'production_license_acceptance': False,
        'real_provider_calls': 0, 'synthetic_adapter_calls': 0, 'normal_database_used': False,
        'requests': [], 'faults_applied': [], 'sources_before': before,
        'startup_completed': False, 'lifespan_exit_returned': False, 'client_close_returned': False}
    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    save('starting.json', {**state, 'guard_counts': counts})
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    import uvicorn
    import pytest
    from fastapi import Request
    from fastapi.responses import JSONResponse, Response
    from fastapi.testclient import TestClient
    from tire_api import main
    from tire_api.db import UserSession, RawCapture, QueryRun, RejectedObservation, uid, utcnow
    from tire_api.parser_release_models import ParserBundle, ParserDeploymentRevision
    from tire_api import parser_runtime as runtime
    from tire_api.vehicles import VehicleManufacturer, VehicleModel, VehicleSnapshot, VehicleQuarantine, VehicleVerification, fitment_fact_hash
    from tire_api.vehicle_quality import assess_vehicle_quality
    from tire_api import vehicle_raw
    from tire_api.interest_events import publish
    from admin_support import register_admin
    import test_vehicle_raw as helpers

    app = main.app
    assert Path(app.state.database.engine.url.database).resolve() == database_path
    original_lifespan = app.router.lifespan_context
    owner = other = client = None
    fault = {'action': None, 'path': None, 'held': False, 'release': None}
    seeded = {}
    policy_patch = pytest.MonkeyPatch()
    original_policy = vehicle_raw._vehicle_original_policy
    original_rights = vehicle_raw._vehicle_consumer_rights
    def private_original_policy(binding):
        value = original_policy(binding)
        return {**value, 'capture_storage': 'allowed', 'local_original_read': 'allowed', 'structured_fact_use': 'allowed'}
    def private_consumer_rights(capsule):
        return {**original_rights(capsule), 'structured_fact_use': 'allowed'}

    class PrivateVehicleAdapter:
        supports_parser_deployments = False
        @staticmethod
        def candidates():
            from tire_api.adapters import xiaomi
            return [{**deepcopy(row), 'status': 'ready', 'description': 'R96 私有合成历史入口；不提供线上或许可验收'} for row in xiaomi.candidates()]
        @staticmethod
        async def fetch(vehicle_id, **kwargs):
            state['synthetic_adapter_calls'] += 1
            return {'status': 'unavailable', 'reason': 'r96_synthetic_offline_only'}
    app.state.vehicle_adapter = PrivateVehicleAdapter()

    def document(vehicle, raw_hash=None):
        return {'vehicle': {'id': vehicle, 'manufacturer': {'id': 'xiaomi', 'name': 'R96 合成厂商'},
            'model': 'R96 合成车型', 'generation': '合成历史', 'model_year': None, 'region': 'CN', 'source_vehicle_id': vehicle,
            **({'source_version': 'pdf-sha256:' + raw_hash} if raw_hash else {})},
            'trims': [{'id': 'r96-trim-' + vehicle, 'name': '合成配置', 'source_trim_id': 'r96-trim', 'model_year': None, 'wheel_option_ids': ['r96-wheel']}],
            'fitments': [{'id': 'r96-wheel', 'trim_id': 'r96-trim-' + vehicle, 'trim_name': '合成配置', 'wheel_option_name': '合成20英寸',
                'wheel_diameter_inches': 20, 'availability': 'standard', 'front': {'size': '245/40R20', 'load_index': None, 'speed_rating': None, 'oe_mark': None, 'manufacturer_product_code': None, 'matched_tire_variant_id': None},
                'rear': {'size': '245/40R20', 'load_index': None, 'speed_rating': None, 'oe_mark': None, 'manufacturer_product_code': None, 'matched_tire_variant_id': None}, 'staggered': False,
                'source_tire_description': None, 'constraints': [], 'source_description': '<script>R96纯文本</script>', 'evidence_locator': 'R96 合成定位；不是官网解析结果'}], 'footnotes': []}

    def seed():
        nonlocal owner, other, client
        client = TestClient(app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
        owner = register_admin(client, username='r96_synthetic_owner')['user']
        second = TestClient(app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
        try:
            other = register_admin(second, username='r96_synthetic_other')['user']
        finally:
            second.close()
        database = app.state.database
        context = SimpleNamespace(root=storage, database=database)
        monkeypatch = pytest.MonkeyPatch()
        with database.sessions() as db:
            db.add(UserSession(id='r86-session', user_id=owner['id'], expires_at=utcnow() + timedelta(days=1)))
            if db.get(VehicleManufacturer, 'xiaomi') is None:
                db.add(VehicleManufacturer(id='xiaomi', name='R96 合成厂商'))
            db.flush()
            for vehicle in (helpers.VEHICLE, helpers.CURRENT):
                if db.get(VehicleModel, vehicle) is None:
                    db.add(VehicleModel(id=vehicle, manufacturer_id='xiaomi', name='R96 合成车型', generation='合成历史', region='CN', source_vehicle_id=vehicle))
            db.commit()
        manifest, _ = helpers.seal(context, monkeypatch, installed_mapping=True)
        descriptor = runtime.descriptor_for_manifest(manifest, helpers.SOURCE)
        with database.sessions() as db:
            db.add(ParserBundle(id=manifest['bundle_id'], manifest=deepcopy(manifest), descriptors={helpers.SOURCE: deepcopy(descriptor)},
                operator='R96 synthetic', reason='Private archive, synthetic receipt, no parser execution', origin='r96-private'))
            db.flush()
            db.add(ParserDeploymentRevision(id='r86-storage-deployment', source_id=helpers.SOURCE, revision=1, state='active', bundle_id=manifest['bundle_id'],
                descriptor=deepcopy(descriptor), action='bootstrap', actor_session_id='r86-session', idempotency_key=uid(), request_hash='1' * 64,
                operator='R96 synthetic', reason='Private historical archive only'))
            db.commit()
        s2_bytes = S2.read_bytes()
        assert len(s2_bytes) == S2_SIZE and hashlib.sha256(s2_bytes).hexdigest() == S2_SHA
        proof = helpers.chain(context, monkeypatch, s2_bytes, installed_mapping=True)
        watched = client.post('/v1/interests', json={'name': 'R96合成车型冻结历史', 'enabled': True,
            'conditions': [{'kind': 'vehicle_fitment', 'values': [{'vehicle_id': helpers.VEHICLE}]}], 'metric_keys': [], 'changed_fields': []})
        assert watched.status_code == 201, watched.text
        watched_text = client.post('/v1/interests', json={'name': 'R96合成文本车型冻结历史', 'enabled': True,
            'conditions': [{'kind': 'vehicle_fitment', 'values': [{'vehicle_id': helpers.CURRENT}]}], 'metric_keys': [], 'changed_fields': []})
        assert watched_text.status_code == 201, watched_text.text
        with database.sessions() as db:
            cap = db.get(RawCapture, proof.capture_id)
            payload = {**document(helpers.VEHICLE, S2_SHA), 'parse_method': helpers.METHOD, 'mapping_id': helpers.MAPPING, 'parse_provenance': deepcopy(proof.expected)}
            baseline_payload = deepcopy(payload)
            for index in range(1, 4):
                baseline_payload['fitments'].append({**deepcopy(payload['fitments'][0]),
                    'id': f'r96-wheel-extra-{index}', 'wheel_option_name': f'合成20英寸额外项{index}'})
            baseline_payload['trims'][0]['wheel_option_ids'] = [row['id'] for row in baseline_payload['fitments']]
            snapshot = VehicleSnapshot(id='r96-binary-snapshot', vehicle_id=helpers.VEHICLE, source_id=helpers.SOURCE,
                source_url=cap.source_url, raw_hash=cap.raw_hash, body=None, body_encoding='binary', raw_capture_id=cap.id,
                content_type=cap.content_type, parser_version=cap.parser_version, parser_identity=deepcopy(cap.parser_identity),
                observed_at=utcnow(), payload=baseline_payload, fact_hash=fitment_fact_hash(baseline_payload), fact_version=1)
            db.add(snapshot)
            db.flush()
            db.add(VehicleVerification(id=uid(), snapshot_id=snapshot.id, query_id=proof.run_id, vehicle_id=helpers.VEHICLE,
                parser_identity=deepcopy(cap.parser_identity), verified_at=snapshot.observed_at - timedelta(microseconds=1)))
            db.flush()
            publish(db, 'vehicle', snapshot)
            quality = assess_vehicle_quality(baseline_payload, payload)
            assert quality['groups']['fitments']['baseline_rows'] == 4 and quality['groups']['fitments']['candidate_rows'] == 1
            assert 'row_loss_threshold' in quality['reason_codes']
            quarantine = VehicleQuarantine(id='r96-binary-quarantine', query_id=cap.query_id, vehicle_id=helpers.VEHICLE,
                source_id=helpers.SOURCE, previous_snapshot_id=snapshot.id, source_url=cap.source_url, raw_hash=cap.raw_hash,
                body=None, body_encoding='binary', raw_capture_id=cap.id, content_type=cap.content_type,
                parser_version=cap.parser_version, parser_identity=deepcopy(cap.parser_identity), payload=deepcopy(payload), quality=quality)
            db.add(quarantine)
            text_run = helpers.new_run(db, vehicle=helpers.CURRENT)
            text_bytes = '<script>R96纯文本不可执行</script>\n保留 Unicode 原文'.encode('utf-8')
            text_cap = helpers.capture(db, text_run, text_bytes, observed=helpers.observation(text_bytes, binary=False))
            text_payload = document(helpers.CURRENT)
            text_row = VehicleSnapshot(id='r96-text-snapshot', vehicle_id=helpers.CURRENT, source_id=helpers.SOURCE,
                source_url=text_cap.source_url, raw_hash=text_cap.raw_hash, body=text_bytes.decode('utf-8'), body_encoding='utf-8',
                raw_capture_id=text_cap.id, content_type=text_cap.content_type, parser_version=text_cap.parser_version,
                parser_identity=deepcopy(text_cap.parser_identity), observed_at=utcnow(), payload=text_payload, fact_hash=fitment_fact_hash(text_payload), fact_version=1)
            db.add(text_row)
            db.flush()
            db.add(VehicleVerification(id=uid(), snapshot_id=text_row.id, query_id=text_run.id, vehicle_id=helpers.CURRENT,
                parser_identity=None, verified_at=text_row.observed_at - timedelta(microseconds=1)))
            db.flush()
            publish(db, 'vehicle', text_row)
            text_rejected = RejectedObservation(id='r96-text-rejected', query_id=text_run.id, source_id=helpers.SOURCE,
                query_key=text_run.query_key, target_kind='vehicle', stage='parser', reason='parser_failed',
                source_url=text_cap.source_url, raw_hash=text_cap.raw_hash, raw_body=text_bytes, body_encoding='utf-8',
                content_type=text_cap.content_type, parser_version=text_cap.parser_version, parser_identity=deepcopy(text_cap.parser_identity))
            db.add(text_rejected)
            unknown_run = helpers.new_run(db)
            unknown_cap = helpers.capture(db, unknown_run)
            rejected = RejectedObservation(id='r96-binary-rejected', query_id=unknown_run.id, source_id=helpers.SOURCE, query_key=unknown_run.query_key,
                target_kind='vehicle', stage='parser', reason='vehicle_pdf_revision_unreviewed', source_url=unknown_cap.source_url,
                raw_hash=unknown_cap.raw_hash, raw_body=unknown_cap.raw_body, body_encoding='binary', content_type='application/pdf',
                parser_version=unknown_cap.parser_version, parser_identity=deepcopy(unknown_cap.parser_identity))
            db.add(rejected)
            db.commit()
            seeded.update(binary_snapshot=snapshot.id, binary_capture=cap.id, binary_quarantine=quarantine.id,
                binary_rejected=rejected.id, unknown_capture=unknown_cap.id, text_capture=text_cap.id, text_snapshot=text_row.id, text_quarantine=text_rejected.id,
                source=helpers.SOURCE, vehicle=helpers.VEHICLE, current_vehicle=helpers.CURRENT,
                s2_sha256=S2_SHA, s2_bytes=S2_SIZE, unknown_sha256=unknown_cap.raw_hash, unknown_bytes=unknown_cap.byte_count,
                text_body=text_bytes.decode('utf-8'), source_bundle=manifest['bundle_id'],
                binary_quarantine_quality=quality, quality_generator='production assess_vehicle_quality on private synthetic baseline/candidate')
        monkeypatch.undo()
        # Both the original schema checks and production V2 endpoints remain active.
        for path in (f'/v1/vehicle-evidence/{seeded["binary_snapshot"]}', f'/v1/captures/{seeded["binary_capture"]}', f'/v1/quarantines/{seeded["binary_quarantine"]}', f'/v1/quarantines/{seeded["binary_rejected"]}', f'/v1/quarantines/{seeded["text_quarantine"]}'):
            response = client.get(path + '?mode=history&format=raw-evidence-v2')
            assert response.status_code == 200, (path, response.status_code, response.text[:300])
        save('seed.json', {**seeded, 'receipt_is_synthetic': True, 'historical_s2_path': S2.relative_to(ROOT).as_posix(), 'actual_child': False})

    @asynccontextmanager
    async def lifespan(application):
        try:
            async with original_lifespan(application):
                # These process-local grants apply only to the exact private database above.
                # They preserve all structural/integrity checks and never enable provider/export.
                policy_patch.setattr(vehicle_raw, '_vehicle_original_policy', private_original_policy)
                policy_patch.setattr(vehicle_raw, '_vehicle_consumer_rights', private_consumer_rights)
                state['synthetic_policy'] = {'local_original_read': 'allowed', 'local_structured': 'allowed',
                    'provider_use': False, 'export_or_redistribution': False, 'scope': str(database_path), 'restored': False}
                seed()
                state['startup_completed'] = True
                save('started.json', {**state, 'guard_counts': counts, 'seed': seeded, 'api_port': API_PORT, 'web_port': WEB_PORT})
                print(json.dumps({'ready': True, 'port': API_PORT, 'output': str(output)}), flush=True)
                yield
            state['lifespan_exit_returned'] = True
        except BaseException as error:
            state['lifespan_error_type'] = type(error).__name__
            raise
        finally:
            if client is not None:
                client.close()
                state['client_close_returned'] = True
            policy_patch.undo()
            if 'synthetic_policy' in state:
                state['synthetic_policy']['restored'] = (vehicle_raw._vehicle_original_policy is original_policy and vehicle_raw._vehicle_consumer_rights is original_rights)
            after = source_hashes()
            save('stopped.json', {**state, 'sources_after': after, 'sources_stable': before == after, 'guard_counts': counts,
                'shutdown_complete': state['startup_completed'] and state['lifespan_exit_returned'] and state['client_close_returned'] and state.get('synthetic_policy', {}).get('restored', False),
                'private_resources_retained': True})
    app.router.lifespan_context = lifespan

    @app.middleware('http')
    async def controlled_faults(request: Request, call_next):
        path = request.url.path
        response = await call_next(request)
        record = {'method': request.method, 'path': path, 'status': response.status_code}
        state['requests'].append(record)
        if path == fault['path'] and fault['action']:
            action, fault['action'] = fault['action'], None
            state['faults_applied'].append({'path': path, 'action': action, 'original_status': response.status_code})
            if action in ('403', '404', '409', '503'):
                return JSONResponse({'detail': {'code': 'r96_synthetic_' + action}}, status_code=int(action))
            if action == 'hold':
                event = asyncio.Event()
                fault['held'], fault['release'] = True, event
                await event.wait()
                fault['held'], fault['release'] = False, None
            elif action in ('source-mismatch', 'query-state-mismatch', 'key-order'):
                body = b''.join([chunk async for chunk in response.body_iterator])
                value = json.loads(body)
                if action == 'source-mismatch':
                    value['source_url'] = value['source_url'] + '?r96=synthetic-mismatch'
                elif action == 'query-state-mismatch':
                    value['query_state'] = 'failed' if value['query_state'] == 'pending' else 'pending'
                    # This field is a decoder-enforced projection, not an independent fault.
                    value['processing_unconfirmed'] = value['query_state'] == 'pending'
                else:
                    value = dict(reversed(list(value.items())))
                return JSONResponse(value, status_code=response.status_code, headers={key: val for key, val in response.headers.items() if key.lower() not in ('content-length', 'content-type')})
        return response

    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=API_PORT, loop='asyncio', log_level='warning', access_log=False))
    @app.post('/fixture/session')
    def session(request: Request, account: str = 'owner'):
        assert account in ('owner', 'other')
        with app.state.database.sessions() as db:
            row = db.get(UserSession, request.state.session_id)
            row.user_id = (owner if account == 'owner' else other)['id']
            db.commit()
        return {'synthetic_only': True, 'authenticated': True, 'login_acceptance': False}
    @app.get('/fixture/state')
    def fixture_state():
        return {'seed': seeded, 'guard_counts': counts, 'held': fault['held'], 'request_count': len(state['requests']), 'faults_applied': state['faults_applied']}
    @app.post('/fixture/fault')
    async def set_fault(request: Request):
        value = await request.json()
        paths = {f'/v1/{kind}/{identifier}{suffix}' for kind, identifier in (
            ('captures', seeded['binary_capture']), ('captures', seeded['unknown_capture']), ('captures', seeded['text_capture']),
            ('vehicle-evidence', seeded['binary_snapshot']), ('vehicle-evidence', seeded['text_snapshot']),
            ('quarantines', seeded['binary_quarantine']), ('quarantines', seeded['binary_rejected']), ('quarantines', seeded['text_quarantine'])) for suffix in ('', '/content')}
        assert value.get('path') in paths and value.get('action') in ('403', '404', '409', '503', 'hold', 'source-mismatch', 'query-state-mismatch', 'key-order')
        assert fault['release'] is None and fault['action'] is None
        fault.update(path=value['path'], action=value['action'])
        return {'armed': True, 'synthetic_only': True}
    @app.post('/fixture/release')
    async def release():
        if fault['release'] is not None:
            fault['release'].set()
        return {'released': True}
    @app.post('/fixture/shutdown')
    async def shutdown():
        if fault['release'] is not None:
            fault['release'].set()
        server.should_exit = True
        return {'stopping': True}
    server.run()
    save('server-return.json', {'server_started': server.started, 'startup_completed': state['startup_completed'],
        'should_exit': server.should_exit, 'process_exit_code': 0 if server.started and state['startup_completed'] else 1})
    if not server.started or not state['startup_completed']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    serve(parser.parse_args().output)
