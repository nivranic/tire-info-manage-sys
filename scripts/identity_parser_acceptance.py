"""Private v1-to-v2 identity acceptance with three real, bounded Parser children.

The only substituted component is the HTTP transport supplying explicitly
synthetic HTML/robots/304 responses. Parser code, receipts, captures, quality,
reparse, migration and adoption all use their production implementations.
No output is an independent human Golden truth or a release approval.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'hankook-us'
OLD_BUNDLE = (ROOT / '.artifacts/golden/round37-fixture-1790781358210/bundles-checkpoint/sha256'
              / '8ea5140ca7223221cd0ab003bdc83f8354f610dff56f6933b36af5cc8f2d6cb7')
QUERY = {'model': 'Ventus S1 evo3', 'size': '205/45R17'}
SIGNED = {'operator': 'Synthetic namespace acceptance',
          'reason': 'Automated synthetic fixture only; not independent human-reviewed tire truth'}


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def inventory(directory):
    result = {}
    for path in sorted(Path(directory).rglob('*')):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('A sealed fixture may not contain links or reparse points')
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def pid_alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if sys.platform != 'win32':
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return False
        raise RuntimeError('Parser PID liveness could not be verified')
    try:
        value = ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(value)):
            raise RuntimeError('Parser exit status could not be verified')
        return value.value == 259
    finally:
        kernel.CloseHandle(handle)


def check_receipt(receipt, expected_limits):
    assert receipt.get('pid') and receipt.get('exit_code') == 0 and receipt.get('reaped') is True, receipt
    assert receipt['limits'] == expected_limits
    assert receipt['network_enforced'] is False and receipt['python_network_guard'] is True
    assert not pid_alive(receipt['pid'])


def private_run(output, private_root, report):
    os.environ.update(TIRE_DATABASE_URL='sqlite:///' + (private_root / 'private.sqlite').as_posix(),
        DATABASE_URL='sqlite:///' + (private_root / 'private.sqlite').as_posix(),
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBJECT_STORE_BACKEND='filesystem',
        TI_OBJECT_STORE_ROOT=str(private_root / 'objects'), TI_PARSER_BUNDLE_ROOT=str(private_root / 'bundles'),
        TI_OBSERVABILITY_ENABLED='0', TI_OBSERVABILITY_LOGS='0', PYTHONDONTWRITEBYTECODE='1')
    sys.path.insert(0, str(ROOT / 'apps/api'))
    counters = report['counters']

    def forbid_network(*_args, **_kwargs):
        counters['external_network_attempts'] += 1
        raise RuntimeError('External transport is disabled in namespace acceptance')

    def audit(event, arguments):
        if event == 'sqlite3.connect':
            target = str(arguments[0])
            if target != ':memory:' and not Path(target).resolve().is_relative_to(private_root):
                raise RuntimeError('Only owned private SQLite may be opened')
        elif event in {'socket.connect', 'socket.getaddrinfo'}:
            target = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
            if target not in {'127.0.0.1', '::1', 'localhost'}:
                forbid_network()
        elif event == 'subprocess.Popen':
            import subprocess
            from tire_api.parser_runtime import _command
            command = arguments[1]
            expected = _command()
            if isinstance(command, str):
                # Windows emits the already converted command line, whereas
                # POSIX emits argv. Match the actual production command exactly.
                prefix = subprocess.list2cmdline(expected) + ' --execution-root '
                execution_root = command[len(prefix):].strip('"') if command.startswith(prefix) else None
            else:
                execution_root = (command[-1] if isinstance(command, (tuple, list))
                    and list(command[:-2]) == expected and command[-2] == '--execution-root' else None)
            roots = {Path(path).resolve() / 'package' for path in report['parser_temp_directories']}
            if execution_root is None or Path(execution_root).resolve() not in roots:
                report.setdefault('audit_rejections', []).append('unrecognized_parser_child_command')
                raise RuntimeError('Only the production Parser supervisor may launch a child')
            counters['parser_child_starts'] += 1
        elif event == 'tempfile.mkdtemp':
            directory = Path(arguments[0])
            if directory.name.startswith('tire-parser-'):
                report['parser_temp_directories'].append(str(directory))

    sys.addaudithook(audit)
    import aiohttp
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from tire_api.adapters import registry
    from tire_api.captures import before_parse_recorder, checked_capture_bytes
    from tire_api.db import (FactVersion, QueryRun, RawCapture, Snapshot, SourceQuarantine,
                             TireVariant, Verification, WatchItem, uid)
    from tire_api.domain import IDENTITY_CONTRACT_VERSION, VariantInput, digest
    from tire_api.main import create_app
    from tire_api.parser_bundles import bundle_descriptor, verify_bundle
    from tire_api.parser_release_models import ParserExecution
    from tire_api.parser_releases import ParserDeploymentError, _golden_gate, bootstrap_source
    from tire_api.parser_runtime import ParserRunError, limits, parse_isolated
    from tire_api.service import business_facts

    aiohttp.ClientSession = forbid_network
    expected_limits = limits()
    assert expected_limits['wall_seconds'] == 8 and expected_limits['max_concurrent'] == 2
    assert expected_limits['cpu_seconds'] == 5 and expected_limits['memory_bytes'] == 384 * 1024 * 1024
    report['limits'] = expected_limits
    manifest_bytes = (OLD_BUNDLE / 'manifest.json').read_bytes()
    old_manifest = json.loads(manifest_bytes)
    assert old_manifest['parsers'][SOURCE]['parser_version'] == 'hankook-us-spec-cards@1.0.0'
    assert old_manifest['limits'] == expected_limits
    copied_bundle = private_root / 'bundles/sha256' / old_manifest['bundle_id']
    copied_bundle.parent.mkdir(parents=True)
    shutil.copytree(OLD_BUNDLE, copied_bundle)
    assert (copied_bundle / 'manifest.json').read_bytes() == manifest_bytes
    # This includes the original environment contract. Incompatibility is a
    # retained failure, never fixed by editing or resealing the old manifest.
    verify_bundle(old_manifest)
    old_descriptor = bundle_descriptor(old_manifest, SOURCE)
    report['old_parser'] = old_descriptor
    report['stage'] = 'old_bundle_verified'
    save(output / 'report.json', report)

    original = (ROOT / 'apps/api/tests/fixtures/brand_sources/hankook-runflat-pair-excerpt.html').read_text(encoding='utf-8')
    assert '1022631' in original and '1022632' in original, 'Synthetic code substitution must cover both fixture rows'
    body = '<!-- SYNTHETIC NAMESPACE ACCEPTANCE ONLY -->\n' + original.replace('1022631', '9380001').replace('1022632', '9380002')
    raw_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
    (output / 'synthetic-body.html').write_text(body, encoding='utf-8')
    url = registry.query_url(QUERY, SOURCE)
    transport = {'mode': '200', 'requests': []}

    class SyntheticHTTP:
        def __init__(self, hosts):
            assert hosts == frozenset({registry.SPECS[SOURCE].host})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, target, *, headers=None, **_kwargs):
            counters['synthetic_http_responses'] += 1
            if target == registry.SPECS[SOURCE].origin + '/robots.txt':
                return SimpleNamespace(status=200, url=target, body='User-agent: *\nAllow: /\n',
                    content_type='text/plain', etag=None, last_modified=None)
            assert target == url
            transport['requests'].append({'mode': transport['mode'], 'headers': dict(headers or {})})
            if transport['mode'] == '304':
                assert headers == {'If-None-Match': '"synthetic-namespace-v2"'}
                return SimpleNamespace(status=304, url=url, body='', content_type='text/html',
                    etag='"synthetic-namespace-v2"', last_modified=None)
            assert not headers, 'A v1 snapshot cannot supply v2 transport validators'
            return SimpleNamespace(status=200, url=url, body=body, content_type='text/html',
                etag='"synthetic-namespace-v2"', last_modified=None)

    registry.SafeHttpClient = SyntheticHTTP
    registry._states.clear()
    registry._robots.clear()
    app = create_app(os.environ['TIRE_DATABASE_URL'], registry)

    class ForbiddenModel:
        async def generate(self, *_args, **_kwargs):
            counters['model_calls'] += 1
            raise RuntimeError('Models are forbidden in namespace acceptance')

    app.state.ai_adapter = ForbiddenModel()
    database = app.state.database
    with TestClient(app) as client:
        client.get('/health')
        actor = client.cookies['tire_local_session']
        with database.sessions() as db:
            run = QueryRun(id=uid(), session_id=actor, source_id=SOURCE, query_key=digest(QUERY),
                           query=QUERY, fallback_policy='never')
            db.add(run)
            db.commit()
            old_parser_identity = {key: old_descriptor[key] for key in ('bundle_id', 'parser_digest', 'execution_digest')}
            old_parser_identity['deployment_revision'] = None
            before_parse_recorder(db, run)({'url': url, 'body': body, 'content_type': 'text/html',
                'parser_version': old_descriptor['parser_version'], 'parser_identity': old_parser_identity})
            old_capture_id = db.scalar(select(RawCapture.id).where(RawCapture.query_id == run.id))
            db.commit()
            report['stage'] = 'old_parser_running'
            save(output / 'report.json', report)
            try:
                parsed = asyncio.run(parse_isolated(SOURCE, body, QUERY, old_descriptor['parser_version'],
                    old_descriptor['parser_digest'], bundle_manifest=old_manifest))
            except ParserRunError as error:
                report['receipts'].append({'phase': 'old_sealed_parser', 'error_code': error.code, 'receipt': error.receipt})
                raise
            report['receipts'].append({'phase': 'old_sealed_parser', 'receipt': parsed['receipt']})
            check_receipt(parsed['receipt'], expected_limits)
            assert len(parsed['payload']) == 2
            assert {row['manufacturer_product_code'] for row in parsed['payload']} == {'9380001', '9380002'}
            assert all('product_code_type' not in row['facts'] for row in parsed['payload'])
            save(output / 'old-parser-payload.json', parsed['payload'])
            snapshot_id, legacy_rows = uid(), []
            for index, raw in enumerate(parsed['payload']):
                variant = VariantInput.model_validate(raw)
                key, status = variant.legacy_identity_key(SOURCE, run.query_key, index)
                entity_id = uid()
                db.add(TireVariant(id=entity_id, identity_key=key, identity=variant.legacy_identity(), identity_status=status))
                legacy_rows.append({**variant.model_dump(), 'id': entity_id, 'identity_key': key,
                                    'identity_status': status, 'fact_version': 1})
            db.flush()
            snapshot = Snapshot(id=snapshot_id, source_id=SOURCE, query_key=run.query_key, source_url=url,
                raw_hash=raw_hash, body=body, content_type='text/html', parser_version=old_descriptor['parser_version'],
                parser_identity=old_parser_identity, identity_contract_version=None, etag='"legacy-synthetic"',
                parsed_variants=legacy_rows)
            db.add(snapshot)
            db.flush()
            for item in legacy_rows:
                facts = business_facts(item['facts'])
                db.add(FactVersion(variant_id=item['id'], source_id=SOURCE, snapshot_id=snapshot.id,
                                  facts=facts, facts_hash=digest(facts), version=1))
            db.add(Verification(snapshot_id=snapshot.id, query_id=run.id, source_id=SOURCE, query_key=run.query_key,
                                status='ok', parser_identity=old_parser_identity, etag='"legacy-synthetic"'))
            watch = WatchItem(session_id=actor, variant_id=legacy_rows[0]['id'])
            db.add(watch)
            run.state = 'live'
            db.commit()
            watch_id = watch.id
            original_identity = {row['id']: deepcopy(db.get(TireVariant, row['id']).identity) for row in legacy_rows}
            original_facts = {row.id: {'variant_id': row.variant_id, 'facts': deepcopy(row.facts), 'snapshot_id': row.snapshot_id}
                              for row in db.scalars(select(FactVersion))}
        report.update(stage='legacy_snapshot_seeded_from_real_parser', old_capture_id=old_capture_id,
                      legacy_snapshot_id=snapshot_id, legacy_ids=[row['id'] for row in legacy_rows], raw_sha256=raw_hash)
        save(output / 'report.json', report)
        preview = client.get('/v1/identity-contract/migration-preview?mode=history').json()
        save(output / 'migration-preview.json', preview)
        assert len(preview['items']) == 2 and all(row['state'] == 'needs_review' for row in preview['items'])
        assert all('legacy_namespace_unknown' in row['reason_codes'] for row in preview['items'])
        application = client.post('/v1/identity-contract/migration-applications', headers={'Idempotency-Key': str(uuid4())},
            json={**SIGNED, 'mode': 'history', 'schema': preview['schema'], 'expected_revision': preview['revision'],
                  'expected_preview_fingerprint': preview['preview_fingerprint'], 'acknowledged': True})
        assert application.status_code == 201, application.text
        save(output / 'migration-application.json', application.json())
        with database.sessions() as db:
            deployment = bootstrap_source(db, SOURCE, **SIGNED)
            current_bundle, current_revision = deployment.bundle_id, deployment.revision
        report['current_bundle_id'] = current_bundle
        catalog = client.get('/v1/reparse/catalog', params={'mode': 'history', 'bundle_id': current_bundle}).json()
        descriptor = next(row for row in catalog['parsers'] if row['source_id'] == SOURCE)
        assert descriptor['parser_version'] == 'hankook-us-spec-cards@1.1.0'
        reparsed = client.post('/v1/reparse/runs', headers={'Idempotency-Key': str(uuid4())}, json={
            'mode': 'history', 'capture_id': old_capture_id, 'parser_version': descriptor['parser_version'],
            'parser_digest': descriptor['parser_digest'], 'bundle_id': current_bundle})
        assert reparsed.status_code == 201, reparsed.text
        historical = reparsed.json()
        save(output / 'historical-reparse.json', historical)
        completion = historical['completion']
        report['receipts'].append({'phase': 'current_historical_reparse', 'error_code': completion['error_code'],
                                   'receipt': completion['receipt']})
        assert historical['state'] == 'completed' and completion['error_code'] is None
        check_receipt(completion['receipt'], expected_limits)
        assert completion['quality']['blocked'] is False
        assert len(completion['quality']['namespace_reference_alignments']) == 2
        assert all(item['entity_equivalence'] is False for item in completion['quality']['namespace_reference_alignments'])
        assert completion['diff']['added_row_keys'] and completion['diff']['removed_row_keys']
        assert historical['accepted_as_facts'] is False
        gate_input = SimpleNamespace(source_id=SOURCE, bindings=[{'input': {'target_kind': 'tire', 'capture_id': old_capture_id}}])
        with database.sessions() as db:
            gate = _golden_gate(db, gate_input, None)
            assert gate['state'] == 'unverified' and gate['blockers'] == ['golden_set_required']
            try:
                _golden_gate(db, gate_input, None, required=True)
            except ParserDeploymentError as error:
                assert error.code == 'golden_set_required'
            else:
                raise AssertionError('Missing Golden must not authorize release')
        report['golden_boundary'] = {**gate, 'verification': 'production_gate_missing_set_check',
                                    'release_evaluation_executed': False, 'release_approved': False}
        report['stage'] = 'historical_reparse_preserves_identity_boundary'
        save(output / 'report.json', report)
        response = client.post(f'/v1/sources/{SOURCE}/live-query', json={'query': QUERY, 'fallback_policy': 'never'})
        assert response.status_code == 200, response.text
        live = response.json()
        save(output / 'current-query.json', live)
        with database.sessions() as db:
            execution = db.get(ParserExecution, live['query_id'])
            assert execution is not None
            report['receipts'].append({'phase': 'current_registry_query', 'error_code': execution.error_code,
                                       'receipt': deepcopy(execution.receipt)})
            assert execution.state == 'completed', execution.error_code
            check_receipt(execution.receipt, expected_limits)
        assert live['data_state'] == 'live' and len(live['variants']) == 2, live.get('reason')
        current_ids = {row['id'] for row in live['variants']}
        assert not current_ids & set(report['legacy_ids'])
        for row in live['variants']:
            contract = row['identity_contract']
            assert contract['state'] == 'current' and contract['current_identity']['product_code_type'] == 'MATERIAL_CODE'
            assert any(item['variant_id'] in report['legacy_ids'] and item['relationship'] == 'unconfirmed_legacy'
                       for item in contract['related_candidates'])
        assert live['provenance'][0]['snapshot_id'] != snapshot_id
        transport['mode'] = '304'
        throttle = registry._states[registry.SPECS[SOURCE].origin]
        remaining = throttle['last'] + throttle['interval'] - time.monotonic()
        if remaining > 0:
            time.sleep(remaining + .02)
        confirmed = client.post(f'/v1/sources/{SOURCE}/live-query', json={'query': QUERY, 'fallback_policy': 'never'})
        assert confirmed.status_code == 200, confirmed.text
        confirmed = confirmed.json()
        save(output / 'confirmed-304.json', confirmed)
        assert confirmed['data_state'] == 'live_verified_304', confirmed.get('reason')
        assert {row['id'] for row in confirmed['variants']} == current_ids
        assert confirmed['provenance'][0]['snapshot_id'] == live['provenance'][0]['snapshot_id']
        with database.sessions() as db:
            assert db.get(Snapshot, snapshot_id).parsed_variants == legacy_rows
            assert db.get(Snapshot, snapshot_id).identity_contract_version is None
            assert all(db.get(TireVariant, key).identity == value for key, value in original_identity.items())
            assert db.get(WatchItem, watch_id).variant_id == legacy_rows[0]['id']
            assert db.scalar(select(func.count()).select_from(WatchItem)) == 1
            assert all({'variant_id': db.get(FactVersion, key).variant_id, 'facts': db.get(FactVersion, key).facts,
                        'snapshot_id': db.get(FactVersion, key).snapshot_id} == value for key, value in original_facts.items())
            assert db.scalar(select(func.count()).select_from(SourceQuarantine)) == 0
            assert db.get(Snapshot, live['provenance'][0]['snapshot_id']).identity_contract_version == IDENTITY_CONTRACT_VERSION
            captures = db.scalars(select(RawCapture)).all()
            assert len(captures) == 2
            assert all(checked_capture_bytes(db, capture)[0] == body.encode('utf-8') for capture in captures)
            assert db.get(ParserExecution, confirmed['query_id']).state == 'not_modified'
            report['stored_counts'] = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                for model in (Snapshot, TireVariant, FactVersion, Verification, RawCapture, SourceQuarantine, WatchItem)}
        left = VariantInput.model_validate(parsed['payload'][0])
        right = left.model_copy(deep=True)
        left.facts['product_code_type'], right.facts['product_code_type'] = 'MSPN', 'CAI'
        assert left.legacy_identity_key(SOURCE, digest(QUERY), 0) == right.legacy_identity_key(SOURCE, digest(QUERY), 0)
        assert left.identity_key(SOURCE, digest(QUERY), 0) != right.identity_key(SOURCE, digest(QUERY), 0)
        report['namespace_pair_check'] = {'scope': 'derived_domain_counterexample_only', 'same_digits': True,
                                        'legacy_collision': True, 'v2_distinct': True, 'independent_truth': False}
        report.update(stage='passed', transport=transport, deployment_revision=current_revision,
                      current_ids=sorted(current_ids), old_watch_retained=True)
        assert counters['parser_child_starts'] == len(report['receipts']) == 3
        assert counters['external_network_attempts'] == counters['model_calls'] == 0


def run(output):
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / '.artifacts').resolve()) or output.exists():
        raise ValueError('Use a new directory under this workspace .artifacts; never overwrite prior evidence')
    output.mkdir(parents=True)
    original = inventory(OLD_BUNDLE)
    private_root = Path(tempfile.mkdtemp(prefix='ti38i-')).resolve()
    report = {'status': 'running', 'stage': 'starting', 'scope': 'synthetic_v1_to_v2_real_parser_private_sqlite',
        'normal_database_used': False, 'actual_human_review': False, 'release_approved': False,
        'old_bundle_source': str(OLD_BUNDLE), 'private_root': str(private_root), 'receipts': [],
        'parser_temp_directories': [], 'counters': {'external_network_attempts': 0, 'synthetic_http_responses': 0,
                                                  'model_calls': 0, 'parser_child_starts': 0}}
    save(output / 'original-bundle-inventory.json', original)
    save(output / 'report.json', report)
    try:
        private_run(output, private_root, report)
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error_code=getattr(error, 'code', None),
                      error=str(error)[:4000])
        raise
    finally:
        report['original_bundle_unchanged'] = inventory(OLD_BUNDLE) == original
        cleanup = {'private_root': str(private_root), 'parser_pids': [], 'parser_temp_directories': []}
        try:
            for row in report['receipts']:
                pid = row['receipt'].get('pid')
                if pid:
                    cleanup['parser_pids'].append({'pid': pid, 'alive': pid_alive(pid)})
            cleanup['parser_temp_directories'] = [
                {'path': path, 'exists': Path(path).exists()} for path in report['parser_temp_directories']]
            # The owned TestClient has closed SQLite before this checkpoint.
            shutil.copytree(private_root, output / 'private-checkpoint')
        finally:
            if private_root.parent != Path(tempfile.gettempdir()).resolve() or not private_root.name.startswith('ti38i-'):
                raise RuntimeError('Refusing unexpected cleanup target')
            shutil.rmtree(private_root)
            cleanup['private_storage_removed'] = not private_root.exists()
            report['cleanup'] = cleanup
            clean = (cleanup['private_storage_removed'] and not any(row['alive'] for row in cleanup['parser_pids'])
                     and not any(row['exists'] for row in cleanup['parser_temp_directories']))
            if not clean or not report['original_bundle_unchanged']:
                report['status'] = 'failed'
            save(output / 'cleanup.json', cleanup)
            save(output / 'report.json', report)
        print(json.dumps({'status': report['status'], 'report': str(output / 'report.json'),
                          'parser_children': report['counters']['parser_child_starts']}), flush=True)
    if report['status'] != 'passed':
        raise RuntimeError('Acceptance failed its immutable-input or cleanup boundary')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Execute only after the exclusive Parser window is granted')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        parser.error('--execute is required; script creation/static checks never start a Parser')
    run(args.output)


if __name__ == '__main__':
    main()
