"""R98 private HTTP candidate; genuine review routes, historical S2, synthetic grants/receipts.

This is a new entry point, not an extension of R96/R97 authorization. Root must
review/freeze this source and the literal launch argv before it is executed.
It starts no parser child, Provider, normal database, web server, or browser.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import ctypes
from ctypes import wintypes
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
API_PYTHON = Path('D:/.PYENV/pyenv-win/versions/3.12.10/python.exe')
VENV_SITE = ROOT / 'apps/api/.venv/Lib/site-packages'
API_PORT, WEB_PORT = 18986, 18987
S2 = ROOT / '.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/xiaomi-first-generation-2.pdf'
S2_SHA, S2_SIZE = '0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f', 3240150
V2 = '?mode=history&format=raw-evidence-v2'
CASE_NAMES = ('row', 'field', 'combo', 'restricted', 'permission', 'expiry', 'stale',
              'applied', 'conflict', 'drop', 'post403', 'close', 'selection', 'account', 'refresh')


def serve(output):
    output = output.absolute()
    for part in (output, *output.parents):
        if part.exists() and (part.is_symlink() or getattr(part.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400):
            raise ValueError('fresh output and ancestors must not be reparse points')
    output = output.resolve()
    if (output.parent != (ROOT / '.artifacts').resolve()
            or re.fullmatch(r'r98w-[a-f0-9]{16}', output.name) is None or output.exists()):
        raise ValueError('fresh exact .artifacts/r98w-16hex output required')
    if Path.cwd().resolve() != ROOT:
        raise ValueError('fixed repository working directory required')
    counts = {'external_network_attempts': 0, 'child_process_attempts': 0,
              'normal_database_attempts': 0, 'filesystem_denied_attempts': 0,
              'filesystem_denied_operations': {}, 'listener_binds': 0,
              'allowed_loopback_connects': 0, 'internal_socketpair_connections': 0}
    original_open, original_close, owned_fds = os.open, os.close, {}
    fd_lock = threading.RLock()

    def fs_deny(operation):
        counts['filesystem_denied_attempts'] += 1
        operations = counts['filesystem_denied_operations']
        operations[operation] = operations.get(operation, 0) + 1
        raise RuntimeError('r98_private_filesystem_required:' + operation)

    def canonical_path(value, operation):
        if not isinstance(value, (str, bytes, os.PathLike)):
            fs_deny(operation + '_path_type')
        text = os.fsdecode(value)
        if os.name == 'nt':
            if text.startswith('\\\\?\\UNC\\'):
                text = '\\\\' + text[8:]
            elif text.startswith('\\\\?\\'):
                text = text[4:]
            # No device paths or alternate data streams in the private tree.
            if text.startswith('\\\\.\\') or ':' in text[2:]:
                fs_deny(operation + '_device_or_ads')
        path = Path(text)
        if not path.is_absolute():
            path = ROOT / path
        path = Path(os.path.abspath(path))
        for part in (path, *path.parents):
            if part.exists():
                metadata = part.stat(follow_symlinks=False)
                if part.is_symlink() or getattr(metadata, 'st_file_attributes', 0) & 0x400:
                    fs_deny(operation + '_reparse')
        return path.resolve()

    def writable_path(value, operation):
        path = canonical_path(value, operation)
        if not path.is_relative_to(output):
            fs_deny(operation + '_outside_output')
        return path

    def fd_path(fd, operation):
        # stdio and inherited/native-created descriptors are never admitted.
        # FileIO may close without os.close; therefore recheck the live identity
        # and Windows final handle path rather than trusting a stale FD number.
        with fd_lock:
            expected = owned_fds.get(fd)
            if expected is None or fd in (0, 1, 2):
                fs_deny(operation + '_unowned_fd')
            try:
                metadata = os.fstat(fd)
                if (metadata.st_dev, metadata.st_ino) != expected['identity']:
                    fs_deny(operation + '_fd_reused')
                import msvcrt
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
                kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
                buffer = ctypes.create_unicode_buffer(32768)
                size = kernel.GetFinalPathNameByHandleW(wintypes.HANDLE(msvcrt.get_osfhandle(fd)), buffer, len(buffer), 0)
                if not 0 < size < len(buffer):
                    fs_deny(operation + '_fd_path_unavailable')
                path = writable_path(buffer.value, operation)
                if path != expected['path']:
                    fs_deny(operation + '_fd_path_changed')
                return path
            except OSError:
                fs_deny(operation + '_fd_closed')

    def write_target(value, operation):
        return fd_path(value, operation) if type(value) is int else writable_path(value, operation)

    def default_dirfd(value, operation):
        if value not in (None, -1):
            fs_deny(operation + '_dir_fd')

    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def filesystem_audit(event, arguments):
        if event == 'open':
            value, mode, flags = arguments
            if not isinstance(flags, int) or mode is not None and not isinstance(mode, str):
                fs_deny('open_unknown_flags_or_mode')
            if any(character in (mode or '') for character in 'wax+') or flags & write_flags:
                write_target(value, 'open_write')
        elif event in ('os.chdir', 'os.fchdir', 'os.symlink'):
            fs_deny(event)
        elif event in ('os.mkdir', 'os.chmod'):
            default_dirfd(arguments[2], event)
            write_target(arguments[0], event)
        elif event in ('os.remove', 'os.rmdir'):
            default_dirfd(arguments[1], event)
            write_target(arguments[0], event)
        elif event in ('os.rename', 'os.replace'):
            default_dirfd(arguments[2], event)
            default_dirfd(arguments[3], event)
            writable_path(arguments[0], event + '_source')
            writable_path(arguments[1], event + '_target')
        elif event == 'os.link':
            default_dirfd(arguments[2], event)
            default_dirfd(arguments[3], event)
            source = writable_path(arguments[0], event + '_source')
            target = writable_path(arguments[1], event + '_target')
            objects = output / 'p/o/sha256'
            if (not source.is_relative_to(objects) or source.parent != target.parent
                    or re.fullmatch(r'\.receiving-[a-z0-9_]{8}', source.name) is None
                    or re.fullmatch(r'[a-f0-9]{64}', target.name) is None
                    or target.parent != objects / target.name[:2] or not source.is_file()
                    or source.stat().st_nlink != 1):
                fs_deny('os.link_not_private_object_publication')
        elif event == 'os.utime':
            default_dirfd(arguments[3], event)
            write_target(arguments[0], event)
        elif event == 'os.chown':
            default_dirfd(arguments[3], event)
            write_target(arguments[0], event)
        elif event == 'os.truncate':
            write_target(arguments[0], event)
        elif event in ('os.setxattr', 'os.removexattr'):
            write_target(arguments[0], event)

    def private_os_open(path, flags, mode=0o777, *, dir_fd=None):
        default_dirfd(dir_fd, 'os.open')
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        absolute = canonical_path(path, 'os.open_tracking')
        if absolute.is_relative_to(output):
            metadata = os.fstat(descriptor)
            with fd_lock:
                owned_fds[descriptor] = {'path': absolute, 'identity': (metadata.st_dev, metadata.st_ino)}
        return descriptor

    def private_os_close(descriptor):
        with fd_lock:
            owned_fds.pop(descriptor, None)
        return original_close(descriptor)

    # Before the first mkdir and all third-party/product imports. Writes through
    # existing stdio/native C are not Python-open audited; launcher passes only
    # private stdout/stderr, no inherited non-stdio handles (close_fds=True).
    sys.addaudithook(filesystem_audit)
    os.open, os.close = private_os_open, private_os_close
    output.mkdir()
    storage = output / 'p'
    storage.mkdir()
    temporary = storage / 't'
    temporary.mkdir()
    tempfile.tempdir = str(temporary)
    private_home = storage / 'h'
    private_home.mkdir()
    for name in ('roam', 'local'):
        (private_home / name).mkdir()
    windows = Path(os.environ.get('SYSTEMROOT', 'C:/Windows')).resolve()
    python_directory = Path(sys.executable).resolve().parent
    # Preserve only OS executable/runtime lookup. No inherited application,
    # credentials, proxy, telemetry, npm, cloud, or Python startup settings.
    keep = {'SYSTEMROOT', 'WINDIR', 'PATHEXT', 'COMSPEC', 'SYSTEMDRIVE',
            'OS', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS'}
    for key in list(os.environ):
        if key.upper() not in keep:
            del os.environ[key]
    database_path = storage / 'd.sqlite'
    database_url = 'sqlite:///' + database_path.as_posix()
    os.environ.update(TIRE_DATABASE_URL=database_url, DATABASE_URL=database_url,
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
        TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(storage / 'o'),
        TI_PARSER_BUNDLE_ROOT=str(storage / 'b'), TIRE_CORS_ORIGINS=f'http://127.0.0.1:{WEB_PORT}',
        TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary),
        HOME=str(private_home), USERPROFILE=str(private_home),
        APPDATA=str(private_home / 'roam'), LOCALAPPDATA=str(private_home / 'local'),
        PATH=os.pathsep.join(str(path) for path in (python_directory, python_directory / 'Scripts', windows / 'System32')),
        PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    sys.dont_write_bytecode = True
    pair_state, original_pair = threading.local(), socket.socketpair

    def guarded_pair(*args, **kwargs):
        if getattr(pair_state, 'current', None) is not None:
            raise RuntimeError('nested socketpair forbidden')
        pair_state.current = {'listener': None, 'connected': False}
        try:
            return original_pair(*args, **kwargs)
        finally:
            pair_state.current = None

    def audit(event, arguments):
        pair = getattr(pair_state, 'current', None)
        if event == 'socket.__new__':
            _, family, kind, protocol = arguments
            allowed_family = family in (socket.AF_INET, socket.AF_INET6)
            if hasattr(socket, 'AF_UNIX') and family == socket.AF_UNIX:
                allowed_family = pair is not None
            if not allowed_family or kind != socket.SOCK_STREAM or protocol not in (0, socket.IPPROTO_TCP):
                counts['external_network_attempts'] += 1
                raise RuntimeError('r98_stream_socket_only')
            return
        if event == 'socket.bind':
            address = arguments[1]
            if pair is not None and pair['listener'] is None and address in (('127.0.0.1', 0), ('::1', 0)):
                pair['listener'] = arguments[0]
                return
            if address == ('127.0.0.1', API_PORT) and counts['listener_binds'] == 0:
                counts['listener_binds'] += 1
                return
            counts['external_network_attempts'] += 1
            raise RuntimeError('r98_exact_listener_required')
        if event == 'socket.connect':
            address = arguments[1]
            if pair is not None and pair['listener'] is not None and not pair['connected']:
                expected = pair['listener'].getsockname()
                if address == expected and expected[0] in ('127.0.0.1', '::1') and expected[1]:
                    pair['connected'] = True
                    counts['internal_socketpair_connections'] += 1
                    return
            if address in (('127.0.0.1', API_PORT), ('127.0.0.1', WEB_PORT)):
                counts['allowed_loopback_connects'] += 1
                return
            counts['external_network_attempts'] += 1
            raise RuntimeError('r98_external_network_forbidden')
        if event in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr',
                     'socket.getnameinfo', 'socket.sendto', 'socket.sendmsg'):
            counts['external_network_attempts'] += 1
            raise RuntimeError('r98_resolution_datagram_forbidden')
        if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.startfile'):
            counts['child_process_attempts'] += 1
            raise RuntimeError('r98_child_or_os_launch_forbidden')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            if Path(str(arguments[0])).resolve() != database_path:
                counts['normal_database_attempts'] += 1
                raise RuntimeError('r98_exact_private_database_required')

    if sys.platform == 'win32':
        socket.socketpair = guarded_pair

        def native_win32_ver(release='', version='', csd='', ptype=''):
            value = sys.getwindowsversion()
            return str(value.major), f'{value.major}.{value.minor}.{value.build}', value.service_pack, ptype

        platform.win32_ver = native_win32_ver
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # Guard and private environment precede all third-party/product imports.
    sys.addaudithook(audit)

    def source_hashes():
        paths = {Path(__file__).resolve(), ROOT / 'scripts/binary_quarantine_review_web_ui_qa.mjs'}
        for directory in ('apps/api/tire_api', 'apps/web/app', 'apps/web/components',
                          'packages/api-client/src', 'packages/domain-types/src'):
            paths.update(p for p in (ROOT / directory).rglob('*')
                         if p.is_file() and p.suffix in ('.py', '.ts', '.tsx', '.css', '.json'))
        paths.update(ROOT / p for p in ('apps/api/tests/test_vehicle_raw.py', 'apps/api/tests/admin_support.py'))
        return {p.relative_to(ROOT).as_posix(): {'bytes': p.stat().st_size,
                'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(paths)}

    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    before = source_hashes()
    state = {'schema': 'r98-private-review-http@1', 'synthetic_only': True,
        'historical_s2_offline_replay': True, 'receipt_is_synthetic': True,
        'actual_parser_child': False, 'formal_license_acceptance': False,
        'golden_acceptance': False, 'new_official_capture': False,
        'actual_online_adoption': False, 'normal_database_used': False,
        'real_provider_calls': 0, 'requests': [], 'faults_applied': [],
        'sources_before': before, 'startup_completed': False,
        'original_lifespan_entered': False, 'original_lifespan_exit_returned': False,
        'own_testclients_closed': False, 'engine_dispose_returned': False,
        'policy_restored': False, 'own_listener_closed': False}
    save('starting.json', {**state, 'guard_counts': counts})
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    # Direct base -S startup skips site and .pth code; add only the reviewed venv package root.
    sys.path.append(str(VENV_SITE))
    import uvicorn
    import pytest
    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse, StreamingResponse
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from tire_api import main, parser_runtime as runtime, vehicle_raw
    from tire_api.db import (AuditEvent, QueryRun, QuarantineApprovalUse, QuarantineReview,
                             RawCapture, User, UserSession, uid, utcnow)
    from tire_api.parser_release_models import ParserBundle, ParserDeploymentRevision, ParserExecution
    from tire_api.quarantine_review import binary_review_state
    from tire_api.vehicle_quality import assess_vehicle_quality
    from tire_api.vehicles import (VehicleManufacturer, VehicleModel, VehicleQuarantine,
                                  VehicleSnapshot, VehicleVerification, fitment_fact_hash)
    from admin_support import register_admin
    import test_vehicle_raw as helpers

    app = main.app
    if Path(app.state.database.engine.url.database).resolve() != database_path:
        raise RuntimeError('wrong private engine')
    original_lifespan = app.router.lifespan_context
    policy_patch = pytest.MonkeyPatch()
    original_policy = vehicle_raw._vehicle_original_policy
    clients, accounts, seeded, scopes = [], {}, {}, {}
    fault = {'path': None, 'method': None, 'action': None, 'held': False, 'release': None}
    active_records = []
    server = None

    def private_original_policy(binding):
        result = original_policy(binding)
        # Every grant binds the exact current run's row/capture/query/source/hash.
        # A permission-negative Q retains production structured pending.
        if scopes.get((binding.get('kind'), binding.get('id'))) == binding:
            return {**result, 'capture_storage': 'allowed', 'local_original_read': 'allowed',
                    'structured_fact_use': ('pending_review' if binding['id'] == 'r98-permission' else 'allowed')}
        return result

    def ledger():
        with app.state.database.sessions() as db:
            model_counts = {model.__name__: db.scalar(select(func.count()).select_from(model))
                            for model in (QuarantineReview, QuarantineApprovalUse, AuditEvent,
                                          VehicleSnapshot, VehicleVerification, VehicleQuarantine,
                                          RawCapture, ParserExecution)}
            reviews = db.scalars(select(QuarantineReview).order_by(QuarantineReview.created_at, QuarantineReview.id)).all()
            audit_rows = db.scalars(select(AuditEvent).where(AuditEvent.action.in_(
                ('quarantine_review_recorded', 'quarantine_approval_applied')))).all()
            return {'counts': model_counts, 'reviews': [{'id': row.id, 'quarantine_id': row.quarantine_id,
                'binding_hash': row.binding_hash, 'revision': row.revision, 'action': row.action,
                'operator': row.operator, 'operator_is_self_reported': True,
                'actor_session_present': bool(row.actor_session_id)} for row in reviews],
                'review_audits': [{'id': row.id, 'action': row.action, 'detail': row.detail} for row in audit_rows]}

    def document():
        axle = {'size': '245/40R20', 'load_index': '98', 'speed_rating': 'W', 'oe_mark': 'R98',
                'manufacturer_product_code': 'r98-synthetic', 'matched_tire_variant_id': 'r98-synthetic'}
        fits = [{'id': f'r98-wheel-{index}', 'trim_id': 'r98-trim', 'trim_name': '合成配置',
                 'wheel_option_name': f'合成20英寸-{index}', 'wheel_diameter_inches': 20,
                 'availability': 'standard', 'front': deepcopy(axle), 'rear': deepcopy(axle), 'staggered': False,
                 'source_tire_description': 'R98 合成轮胎说明', 'constraints': ['R98 合成约束'],
                 'source_description': 'R98 合成对照；不代表官网解析事实', 'evidence_locator': 'R98 私有合成定位'}
                for index in range(4)]
        return {'vehicle': {'id': helpers.VEHICLE, 'manufacturer': {'id': 'xiaomi', 'name': 'R98 合成厂商'},
                    'model': 'R98 合成车型', 'generation': '合成历史', 'model_year': None, 'region': 'CN',
                    'source_vehicle_id': helpers.VEHICLE, 'source_version': 'pdf-sha256:' + S2_SHA},
                'trims': [{'id': 'r98-trim', 'name': '合成配置', 'source_trim_id': 'r98-trim',
                           'model_year': None, 'wheel_option_ids': [row['id'] for row in fits]}],
                'fitments': fits, 'footnotes': []}

    def seed():
        client = TestClient(app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
        clients.append(client)
        accounts['owner'] = register_admin(client, username='r98_owner')['user']
        for name in ('other', 'reader'):
            secondary = TestClient(app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
            clients.append(secondary)
            accounts[name] = register_admin(secondary, username='r98_' + name)['user']
        database = app.state.database
        with database.sessions() as db:
            db.get(User, accounts['other']['id']).is_admin = True
            db.add(UserSession(id='r86-session', user_id=accounts['owner']['id'], expires_at=utcnow() + timedelta(days=1)))
            if db.get(VehicleManufacturer, 'xiaomi') is None:
                db.add(VehicleManufacturer(id='xiaomi', name='R98 合成厂商'))
            db.flush()
            if db.get(VehicleModel, helpers.VEHICLE) is None:
                db.add(VehicleModel(id=helpers.VEHICLE, manufacturer_id='xiaomi', name='R98 合成车型',
                    generation='合成历史', region='CN', source_vehicle_id=helpers.VEHICLE))
            db.commit()
        context, patch = SimpleNamespace(root=storage, database=database), pytest.MonkeyPatch()
        try:
            manifest, _ = helpers.seal(context, patch, installed_mapping=True)
            descriptor = runtime.descriptor_for_manifest(manifest, helpers.SOURCE)
            with database.sessions() as db:
                db.add(ParserBundle(id=manifest['bundle_id'], manifest=deepcopy(manifest),
                    descriptors={helpers.SOURCE: deepcopy(descriptor)}, operator='R98 synthetic',
                    reason='Private mapping archive and synthetic receipt; no parser child', origin='r98-private'))
                db.flush()
                db.add(ParserDeploymentRevision(id='r86-storage-deployment', source_id=helpers.SOURCE, revision=1,
                    state='active', bundle_id=manifest['bundle_id'], descriptor=deepcopy(descriptor),
                    action='bootstrap', actor_session_id='r86-session', idempotency_key=uid(), request_hash='1' * 64,
                    operator='R98 synthetic', reason='Private historical archive only'))
                db.commit()
            data = S2.read_bytes()
            if len(data) != S2_SIZE or hashlib.sha256(data).hexdigest() != S2_SHA:
                raise RuntimeError('historical S2 pin mismatch')
            proof = helpers.chain(context, patch, data, installed_mapping=True)
            proofs = {name: helpers.chain(context, patch, data, installed_mapping=True) for name in CASE_NAMES}
            with database.sessions() as db:
                cap = db.get(RawCapture, proof.capture_id)
                base = {**document(), 'parse_method': helpers.METHOD, 'mapping_id': helpers.MAPPING,
                        'parse_provenance': deepcopy(proof.expected)}
                now = utcnow()
                snapshots = {}
                for index, name in enumerate(('old', 'common')):
                    row = VehicleSnapshot(id='r98-baseline-' + name, vehicle_id=helpers.VEHICLE,
                        source_id=helpers.SOURCE, source_url=cap.source_url, raw_hash=cap.raw_hash,
                        body=None, body_encoding='binary', raw_capture_id=cap.id, content_type=cap.content_type,
                        parser_version=cap.parser_version, parser_identity=deepcopy(cap.parser_identity),
                        observed_at=now + timedelta(microseconds=index), payload=deepcopy(base),
                        fact_hash=fitment_fact_hash(base), fact_version=index + 1)
                    db.add(row)
                    db.flush()
                    db.add(VehicleVerification(id=uid(), snapshot_id=row.id, query_id=proof.run_id,
                        vehicle_id=helpers.VEHICLE, parser_identity=deepcopy(cap.parser_identity),
                        verified_at=now + timedelta(microseconds=index)))
                    snapshots[name] = row
                for name in CASE_NAMES:
                    # Each Q has a distinct real capture/run and binding; all positive
                    # loss cases share the same current verified baseline.
                    capture = db.get(RawCapture, proofs[name].capture_id)
                    candidate = deepcopy(base)
                    if name != 'field':
                        candidate['fitments'] = candidate['fitments'][:1]
                        candidate['trims'][0]['wheel_option_ids'] = [candidate['fitments'][0]['id']]
                    if name in ('field', 'combo', 'restricted'):
                        for fit in candidate['fitments']:
                            for axle in ('front', 'rear'):
                                for key in ('load_index', 'speed_rating', 'oe_mark',
                                            'manufacturer_product_code', 'matched_tire_variant_id'):
                                    fit[axle][key] = None
                            fit['source_tire_description'], fit['constraints'] = None, []
                    if name == 'restricted':
                        candidate['vehicle']['generation'] = 'R98 合成身份改变'
                    # Non-fact descriptive text makes every case binding distinct.
                    candidate['fitments'][0]['source_description'] += ' / ' + name
                    quality = assess_vehicle_quality(base, candidate)
                    expected = ({'field_loss_threshold'} if name == 'field' else
                        {'row_loss_threshold', 'field_loss_threshold', 'vehicle_identity_changed'}
                        if name == 'restricted' else {'row_loss_threshold', 'field_loss_threshold'}
                        if name == 'combo' else {'row_loss_threshold'})
                    if set(quality['reason_codes']) != expected:
                        raise RuntimeError('unexpected production quality classification: ' + name)
                    row = VehicleQuarantine(id='r98-' + name, query_id=capture.query_id,
                        vehicle_id=helpers.VEHICLE, source_id=helpers.SOURCE,
                        previous_snapshot_id=snapshots['old' if name == 'stale' else 'common'].id,
                        source_url=capture.source_url, raw_hash=capture.raw_hash, body=None,
                        body_encoding='binary', raw_capture_id=capture.id, content_type=capture.content_type,
                        parser_version=capture.parser_version, parser_identity=deepcopy(capture.parser_identity),
                        payload=candidate, quality=quality, observed_at=now + timedelta(seconds=CASE_NAMES.index(name)))
                    db.add(row)
                    db.flush()
                    seeded[name] = {'id': row.id, 'capture_id': capture.id, 'query_id': capture.query_id,
                                    'reason_codes': quality['reason_codes'], 'baseline_id': row.previous_snapshot_id}
                # Grants are limited to exactly these immutable private rows.
                for model in (VehicleSnapshot, VehicleQuarantine, RawCapture):
                    for row in db.scalars(select(model)):
                        _, binding = vehicle_raw._checked_vehicle_original_data(db, row)
                        if binding is not None:
                            scopes[(binding['kind'], binding['id'])] = deepcopy(binding)
                db.commit()
            with database.sessions() as db:
                for name in ('expiry', 'applied'):
                    row = db.get(VehicleQuarantine, seeded[name]['id'])
                    current = binary_review_state(db, row)
                    event = QuarantineReview(id=uid(), quarantine_id=row.id, binding_hash=current['binding_hash'],
                        revision=1, action='approve', operator='R98 explicitly synthetic history seed',
                        reason='Synthetic display-only seed; no actual online adoption or user approval',
                        actor_session_id='r86-session', created_at=utcnow() - timedelta(hours=26 if name == 'expiry' else 1),
                        expires_at=utcnow() + timedelta(hours=-2 if name == 'expiry' else 23))
                    db.add(event)
                    db.flush()
                    if name == 'applied':
                        synthetic_run = helpers.new_run(db)
                        db.add(QuarantineApprovalUse(review_id=event.id, query_id=synthetic_run.id))
                    seeded[name]['synthetic_history_seed'] = True
                    seeded[name]['synthetic_applied_use_seed'] = name == 'applied'
                    seeded[name]['synthetic_review_id'] = event.id
                db.commit()
            projections = {}
            for name in CASE_NAMES:
                response = client.get(f'/v1/quarantines/{seeded[name]["id"]}/review{V2}')
                if name == 'permission':
                    if response.status_code != 403:
                        raise RuntimeError('production structured permission negative did not deny')
                    projections[name] = {'status': 403, 'detail': response.json()['detail']}
                else:
                    if response.status_code != 200:
                        raise RuntimeError('production review projection failed: ' + name + ' ' + response.text[:300])
                    value = response.json()
                    projections[name] = {key: value[key] for key in ('state', 'revision', 'can_approve',
                        'restriction', 'baseline_snapshot_id', 'current_snapshot_id', 'applied_query_id', 'binding_hash')}
            if any(projections[name]['state'] != 'pending' or not projections[name]['can_approve']
                   for name in ('row', 'field', 'combo')):
                raise RuntimeError('three independent loss cases must share a current real baseline')
            seeded.update(source=helpers.SOURCE, vehicle=helpers.VEHICLE, s2_sha256=S2_SHA,
                s2_bytes=S2_SIZE, source_bundle=manifest['bundle_id'], cases=list(CASE_NAMES),
                projections=projections, classification={
                    'historical_input': 'pinned S2 bytes, offline replay; not a new official capture',
                    'private_bundle_mapping': 'private installed-source archive; not formal release/Golden',
                    'parser_execution_rows': 'synthetic completed receipts; actual parser children = 0',
                    'source_policy': 'exact private scope local-only grants; provider/export remain false',
                    'expiry_applied': 'explicit append-only synthetic history seeds; no online adoption'})
            state['seed_ledger'] = ledger()
            expected_counts = {'VehicleQuarantine': 15, 'RawCapture': 16, 'ParserExecution': 16,
                'VehicleSnapshot': 2, 'VehicleVerification': 2, 'QuarantineReview': 2, 'QuarantineApprovalUse': 1}
            if (any(state['seed_ledger']['counts'][name] != count for name, count in expected_counts.items())
                    or state['seed_ledger']['review_audits']
                    or {row['id'] for row in state['seed_ledger']['reviews']} != {
                        seeded['expiry']['synthetic_review_id'], seeded['applied']['synthetic_review_id']}):
                raise RuntimeError('exact private seed ledger mismatch')
            state['seed_counts_checked'] = expected_counts
            save('seed.json', {**seeded, 'ledger': state['seed_ledger']})
        finally:
            patch.undo()

    def competing_review(identifier):
        """Create the actual revision race through the unchanged production POST."""
        client = clients[0]
        response = client.get(f'/v1/quarantines/{identifier}/review{V2}')
        if response.status_code != 200:
            raise RuntimeError('competing reader failed')
        value = response.json()
        response = client.post(f'/v1/quarantines/{identifier}/reviews{V2}', headers={
            'X-Tire-Expected-Account': accounts['owner']['id']}, json={
            'action': 'keep_quarantined', 'expected_revision': value['revision'],
            'operator': 'R98 controlled competing administrator', 'reason': 'Actual production competing review for HTTP 409',
            'confirmed_loss': True, 'expected_binding_hash': value['binding_hash']})
        if response.status_code != 201:
            raise RuntimeError('competing production POST failed')
        return response.json()['revision']

    @asynccontextmanager
    async def lifespan(application):
        try:
            async with original_lifespan(application):
                state['original_lifespan_entered'] = True
                policy_patch.setattr(vehicle_raw, '_vehicle_original_policy', private_original_policy)
                seed()
                state['startup_completed'] = True
                save('started.json', {**state, 'seed': seeded, 'guard_counts': counts,
                                     'api_port': API_PORT, 'web_port': WEB_PORT})
                print(json.dumps({'ready': True, 'port': API_PORT, 'output': str(output)}), flush=True)
                yield
                state['final_ledger'] = ledger()
            state['original_lifespan_exit_returned'] = True
        except BaseException as error:
            state['lifespan_error_type'] = type(error).__name__
            raise
        finally:
            # Each resource has an independent close result; one error cannot
            # suppress closing the other resources. No foreign process is killed.
            errors = []
            for index, client in enumerate(clients):
                try:
                    client.close()
                except BaseException as error:
                    errors.append({'resource': 'own_testclient_' + str(index), 'type': type(error).__name__})
            state['own_testclients_closed'] = not any(row['resource'].startswith('own_testclient') for row in errors)
            try:
                app.state.database.close()
                state['engine_dispose_returned'] = True
            except BaseException as error:
                errors.append({'resource': 'private_engine', 'type': type(error).__name__})
            try:
                policy_patch.undo()
                state['policy_restored'] = vehicle_raw._vehicle_original_policy is original_policy
            except BaseException as error:
                errors.append({'resource': 'private_policy', 'type': type(error).__name__})
            app.router.lifespan_context = original_lifespan
            state['cleanup_errors'] = errors
            try:
                end_s2 = S2.read_bytes()
                state['s2_end_pin'] = {'bytes': len(end_s2), 'sha256': hashlib.sha256(end_s2).hexdigest()}
                state['s2_unchanged'] = state['s2_end_pin'] == {'bytes': S2_SIZE, 'sha256': S2_SHA}
            except BaseException as error:
                state['s2_unchanged'] = False
                errors.append({'resource': 'historical_s2_end_sample', 'type': type(error).__name__})
            state['filesystem_clean'] = counts['filesystem_denied_attempts'] == 0
            after = source_hashes()
            save('stopped.json', {**state, 'sources_after': after, 'sources_stable': before == after,
                                  'guard_counts': counts, 'private_resources_retained': True})

    app.router.lifespan_context = lifespan

    @app.middleware('http')
    async def controlled_faults(request: Request, call_next):
        path = request.url.path
        production = path.startswith('/v1/')
        item = {'method': request.method, 'path': path, 'query': request.url.query,
                'status': None, 'delivered_status': None, 'origin': 'actual-http'}
        if production:
            active_records.append(item)
            state['requests'].append(item)
        try:
            response = await call_next(request)
            item.update(status=response.status_code, delivered_status=response.status_code)
            if path == fault['path'] and request.method == fault['method'] and fault['action']:
                action, fault['action'] = fault['action'], None
                entry = {'path': path, 'method': request.method, 'action': action,
                         'original_status': response.status_code, 'production_route_completed': True,
                         'ledger_after_route': ledger()}
                state['faults_applied'].append(entry)
                if action == 'competing-review':
                    entry['competing_revision'] = await asyncio.to_thread(competing_review, 'r98-conflict')
                elif action == 'hold':
                    event = asyncio.Event()
                    fault.update(held=True, release=event)
                    try:
                        await event.wait()
                    finally:
                        fault.update(held=False, release=None)
                elif action == 'postcommit403':
                    if request.method != 'POST' or response.status_code != 201:
                        raise RuntimeError('postcommit fault requires actual production 201')
                    item['delivered_status'] = 403
                    return JSONResponse({'detail': {'code': 'r98_controlled_response_403_after_commit'}}, status_code=403)
                elif action == 'drop-after-commit':
                    if request.method != 'POST' or response.status_code != 201:
                        raise RuntimeError('drop fault requires actual production 201')
                    # Preserve the production 201 status; only truncate the real HTTP body
                    # after the unchanged production route has durably committed its audit.
                    # Depending on header delivery, fetch or the JSON body read can reject.
                    async def broken_body():
                        yield b'{'
                        raise ConnectionResetError('r98_controlled_drop_after_production_commit')
                    item['delivered_status'] = 'truncated-http-201'
                    return StreamingResponse(broken_body(), status_code=201, media_type='application/json')
            return response
        finally:
            if production:
                active_records.remove(item)

    @app.post('/fixture/session')
    def session(request: Request, account: str = 'owner'):
        if account not in ('owner', 'other', 'reader'):
            raise HTTPException(422, 'fixed synthetic account required')
        with app.state.database.sessions() as db:
            row = db.get(UserSession, request.state.session_id)
            row.user_id = accounts[account]['id']
            db.commit()
        return {'synthetic_only': True, 'account': account, 'user_id': accounts[account]['id'],
                'is_admin': account != 'reader', 'login_acceptance': False}

    @app.get('/fixture/state')
    def fixture_state():
        return {'seed': seeded, 'guard_counts': counts, 'held': fault['held'],
                'fault_armed': fault['action'] is not None, 'active_requests': len(active_records),
                'requests': state['requests'], 'faults_applied': state['faults_applied'],
                'ledger': ledger(), 'seed_ledger': state.get('seed_ledger')}

    @app.post('/fixture/fault')
    async def set_fault(request: Request):
        value = await request.json()
        allowed = {(f'/v1/quarantines/r98-{name}/reviews', 'POST', 'hold')
                   for name in ('close', 'selection', 'account', 'refresh')}
        allowed |= {('/v1/quarantines/r98-drop/reviews', 'POST', 'drop-after-commit'),
                    ('/v1/quarantines/r98-post403/reviews', 'POST', 'postcommit403')}
        allowed |= {(f'/v1/quarantines/r98-{name}/review', 'GET', 'hold')
                    for name in ('close', 'selection', 'account', 'refresh')}
        allowed.add((f'/v1/captures/{seeded["conflict"]["capture_id"]}', 'GET', 'competing-review'))
        if (set(value) != {'path', 'method', 'action'} or
                (value['path'], value['method'], value['action']) not in allowed
                or fault['release'] is not None or fault['action'] is not None):
            raise HTTPException(422, 'one fixed private fault at a time')
        fault.update(path=value['path'], method=value['method'], action=value['action'])
        return {'armed': True, 'synthetic_only': True, 'production_route_remains_active': True}

    @app.post('/fixture/release')
    async def release():
        fault['action'] = None
        if fault['release'] is not None:
            fault['release'].set()
        return {'released': True}

    @app.post('/fixture/receipt')
    async def receipt(request: Request):
        value = await request.json()
        width = value.get('viewport', {}).get('width')
        if value.get('schema') != 'r98-private-review-react@1' or width not in (1440, 390, 320):
            raise HTTPException(422, 'fixed private browser receipt required')
        # Reports contain observations, never passwords, cookies or PDF bytes.
        save('ui-' + str(width) + '.json', value)
        return {'retained': True, 'actual_browser_receipt': True}

    @app.post('/fixture/shutdown')
    async def shutdown():
        if fault['release'] is not None:
            fault['release'].set()
        server.should_exit = True
        return {'stopping_own_server': True}

    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=API_PORT,
        loop='asyncio', log_level='warning', access_log=False))
    try:
        server.run()
    finally:
        sockets = [sock for listener in getattr(server, 'servers', []) for sock in (listener.sockets or [])]
        state['own_listener_closed'] = not sockets or all(sock.fileno() == -1 for sock in sockets)
        save('server-return.json', {'server_started': server.started, **{key: state[key] for key in (
            'startup_completed', 'original_lifespan_exit_returned', 'own_testclients_closed',
            'engine_dispose_returned', 'policy_restored', 'own_listener_closed')},
            'guard_counts': counts, 'own_child_count': 0, 'foreign_processes_closed': 0,
            's2_end_pin': state.get('s2_end_pin'), 's2_unchanged': state.get('s2_unchanged'),
            'filesystem_clean': counts['filesystem_denied_attempts'] == 0,
            'private_resources_retained': True})
    if (not server.started or not state['startup_completed'] or not state.get('s2_unchanged')
            or counts['filesystem_denied_attempts'] or counts['external_network_attempts']
            or counts['child_process_attempts'] or counts['normal_database_attempts']):
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    if (Path(sys.executable).resolve() != API_PYTHON.resolve()
            or not sys.flags.isolated or not sys.flags.no_site
            or not sys.flags.utf8_mode or not sys.dont_write_bytecode):
        raise RuntimeError('exact private base API Python -I -S -X utf8 -B required')
    serve(arguments.output)
