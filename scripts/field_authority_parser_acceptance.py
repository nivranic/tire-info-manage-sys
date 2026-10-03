"""One bounded production Parser child over a saved official body, followed by 304.

Reads only the immutable Round 39 before backup. HTTP is a fixed local replay;
the Registry, Parser supervisor/bundle, QueryService and field policy are real.
This is historical-body replay, not a new official fetch or human Golden review.
No Parser can run without --execute and an independently granted exclusive window.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / '.artifacts/runtime/round39-before.sqlite'
SNAPSHOT_ID = '169436f3-1238-4301-80b7-7be9478e0e9b'
SOURCE = 'hankook-us'
EXPECTED_CODES = {'1022631', '1022632'}
ETAG = '"round39-saved-official-replay"'


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    Path(path).write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))


def raw_expectations(body):
    """Read only fixed code neighborhoods; never reuse the production source parser."""
    expected = {}
    for code in sorted(EXPECTED_CODES):
        matches = list(re.finditer(r'<span class="dt">Material Code</span>\s*<span class="dd">'
                                  + re.escape(code) + r'</span>', body))
        require(len(matches) == 1, 'saved_raw_code_not_unique')
        position = matches[0].start()
        start = body.rfind('<div class="accordion-top', 0, position)
        end = body.find('<div class="accordion-top', position)
        require(start >= 0 and end > position, 'saved_raw_card_boundary_missing')
        card = body[start:end]
        require('205/45R17' in card[:1500], 'saved_raw_size_mismatch')
        values = {}
        for label in ('Run Flat', 'UTQG - Tread Wear'):
            found = re.findall(r'<span class="dt">' + re.escape(label)
                               + r'</span>\s*<span class="dd">([^<]+)</span>', card)
            require(len(found) == 1, 'saved_raw_field_not_unique')
            values[label] = found[0].strip()
        require(values['Run Flat'] in {'Y', 'N'} and values['UTQG - Tread Wear'] == '260',
                'saved_raw_expected_value_changed')
        expected[code] = {'run_flat': values['Run Flat'] == 'Y', 'utqg_treadwear': 260,
                          'card_sha256': sha(card.encode('utf-8'))}
    require(expected['1022631']['run_flat'] is True and expected['1022632']['run_flat'] is False,
            'saved_raw_runflat_pair_changed')
    return expected


def load_saved_input():
    require(BACKUP.is_file(), 'authorized_backup_missing')
    original_hash = sha(BACKUP.read_bytes())
    # URI read-only and immutable prevents journals, migrations and accidental writes.
    with sqlite3.connect(BACKUP.resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        record = db.execute('SELECT id, source_id, query_key, source_url, raw_hash, body, content_type, '
            'parser_version, parsed_variants, observed_at FROM snapshots WHERE id=?', (SNAPSHOT_ID,)).fetchone()
        require(record is not None and record['source_id'] == SOURCE, 'saved_snapshot_missing')
        snapshot = dict(record)
        query_row = db.execute('SELECT query FROM query_runs WHERE source_id=? AND query_key=? '
            'ORDER BY created_at, id LIMIT 1', (SOURCE, snapshot['query_key'])).fetchone()
        require(query_row is not None, 'saved_query_missing')
        query = json.loads(query_row['query'])
    require(sha(snapshot['body'].encode('utf-8')) == snapshot['raw_hash'], 'saved_raw_hash_mismatch')
    require(query == {'size': '205/45R17', 'model': 'Ventus S1 evo3'}, 'saved_query_scope_changed')
    snapshot['parsed_variants'] = json.loads(snapshot['parsed_variants'])
    expected = raw_expectations(snapshot['body'])
    require(sha(BACKUP.read_bytes()) == original_hash, 'backup_changed_during_read')
    return snapshot, query, expected, original_hash


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
        require(ctypes.get_last_error() == 87, 'parser_pid_liveness_unverified')
        return False
    try:
        exit_code = ctypes.c_ulong()
        require(kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)), 'parser_exit_unverified')
        return exit_code.value == 259
    finally:
        kernel.CloseHandle(handle)


def check_receipt(receipt, limits):
    require(receipt.get('pid') and receipt.get('exit_code') == 0 and receipt.get('reaped') is True,
            'parser_not_successfully_reaped')
    require(receipt.get('limits') == limits, 'parser_limits_changed')
    require(receipt.get('python_network_guard') is True and receipt.get('network_enforced') is False,
            'parser_network_receipt_changed')
    require(not pid_alive(receipt['pid']), 'parser_child_still_alive')


def private_run(output, private_root, report, snapshot, query, expected):
    os.environ.update(TIRE_DATABASE_URL='sqlite:///' + (private_root / 'private.sqlite').as_posix(),
        DATABASE_URL='sqlite:///' + (private_root / 'private.sqlite').as_posix(), TI_AI_ENABLED='0',
        TI_EMBEDDINGS_ENABLED='0', TI_OBJECT_STORE_BACKEND='filesystem',
        TI_OBJECT_STORE_ROOT=str(private_root / 'objects'), TI_PARSER_BUNDLE_ROOT=str(private_root / 'bundles'),
        TI_OBSERVABILITY_ENABLED='0', TI_OBSERVABILITY_LOGS='0', PYTHONDONTWRITEBYTECODE='1')
    sys.path.insert(0, str(ROOT / 'apps/api'))
    counters = report['counters']

    def forbid_network(*_args, **_kwargs):
        counters['external_network_attempts'] += 1
        raise RuntimeError('external_network_forbidden')

    def audit(event, arguments):
        if event == 'sqlite3.connect':
            target = str(arguments[0])
            require(target == ':memory:' or Path(target).resolve().is_relative_to(private_root),
                    'only_owned_private_database_allowed')
        elif event in {'socket.connect', 'socket.getaddrinfo'}:
            target = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
            if target not in {'127.0.0.1', '::1', 'localhost'}:
                forbid_network()
        elif event == 'tempfile.mkdtemp':
            directory = Path(arguments[0]).resolve()
            if directory.name.startswith('tire-parser-'):
                require(directory.parent == Path(tempfile.gettempdir()).resolve(), 'unexpected_parser_temp_root')
                report['parser_temp_directories'].append(str(directory))
        elif event == 'subprocess.Popen':
            import subprocess
            from tire_api.parser_runtime import _command
            command, expected_command = arguments[1], _command()
            if isinstance(command, str):
                prefix = subprocess.list2cmdline(expected_command) + ' --execution-root '
                execution_root = command[len(prefix):].strip('"') if command.startswith(prefix) else None
            else:
                execution_root = (command[-1] if isinstance(command, (tuple, list))
                    and list(command[:-2]) == expected_command and command[-2] == '--execution-root' else None)
            allowed_roots = {Path(path) / 'package' for path in report['parser_temp_directories']}
            require(execution_root is not None and Path(execution_root).resolve() in allowed_roots,
                    'only_exact_production_parser_command_allowed')
            require(counters['parser_child_starts'] == 0, 'only_one_parser_child_allowed')
            counters['parser_child_starts'] += 1

    sys.addaudithook(audit)
    import aiohttp
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from tire_api.adapters import registry
    from tire_api.ai_models import AIRequest
    from tire_api.captures import checked_capture_bytes
    from tire_api.db import FactVersion, RawCapture, Snapshot, SourceQuarantine, TireVariant, Verification
    from tire_api.domain import IDENTITY_CONTRACT_VERSION, digest
    from tire_api.embedding_models import EmbeddingRequest
    from tire_api.field_authority import policy_descriptor
    from tire_api.main import create_app
    from tire_api.parser_bundles import verify_bundle
    from tire_api.parser_release_models import ParserBundle, ParserExecution, ParserSelection
    from tire_api.parser_runtime import limits

    aiohttp.ClientSession = forbid_network
    expected_limits = limits()
    require(expected_limits['wall_seconds'] == 8 and expected_limits['max_concurrent'] == 2
        and expected_limits['cpu_seconds'] == 5 and expected_limits['memory_bytes'] == 384 * 1024 * 1024,
        'production_parser_limits_changed')
    require(digest(query) == snapshot['query_key'], 'saved_query_hash_mismatch')
    target = registry.query_url(query, SOURCE)
    require(target == snapshot['source_url'], 'saved_registry_url_changed')
    report['limits'] = expected_limits
    transport = {'mode': '200', 'requests': []}

    class ReplayHTTP:
        def __init__(self, hosts):
            require(hosts == frozenset({registry.SPECS[SOURCE].host}), 'unexpected_replay_host')

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, headers=None, **_kwargs):
            counters['replayed_http_responses'] += 1
            if url == registry.SPECS[SOURCE].origin + '/robots.txt':
                return SimpleNamespace(status=200, url=url, body='User-agent: *\nAllow: /\n',
                    content_type='text/plain', etag=None, last_modified=None)
            require(url == target, 'unexpected_replay_url')
            transport['requests'].append({'mode': transport['mode'], 'headers': dict(headers or {})})
            if transport['mode'] == '304':
                require(headers == {'If-None-Match': ETAG}, 'conditional_validator_missing')
                return SimpleNamespace(status=304, url=url, body='', content_type=snapshot['content_type'],
                    etag=ETAG, last_modified=None)
            require(not headers and counters['parser_child_starts'] == 0, 'unexpected_second_200')
            return SimpleNamespace(status=200, url=url, body=snapshot['body'], content_type=snapshot['content_type'],
                etag=ETAG, last_modified=None)

    registry.SafeHttpClient = ReplayHTTP
    registry._states.clear()
    registry._robots.clear()
    registry._robots_requests.clear()
    app = create_app(os.environ['TIRE_DATABASE_URL'], registry)

    class ForbiddenModel:
        async def generate(self, *_args, **_kwargs):
            counters['model_calls'] += 1
            raise RuntimeError('model_forbidden')

    app.state.ai_adapter = ForbiddenModel()
    database = app.state.database
    try:
        with TestClient(app) as client:
            require(client.get('/health').status_code == 200, 'private_api_unavailable')
            report['stage'] = 'production_parser_running'
            save(output / 'report.json', report)
            response = client.post(f'/v1/sources/{SOURCE}/live-query', json={'query': query, 'fallback_policy': 'never'})
            require(response.status_code == 200, 'private_live_query_failed')
            live = response.json()
            save(output / 'live-200.json', live)
            with database.sessions() as db:
                execution = db.get(ParserExecution, live['query_id'])
                if execution is not None:
                    report['receipts'].append({'phase': 'current_saved_official_body',
                        'state': execution.state, 'error_code': execution.error_code, 'receipt': deepcopy(execution.receipt)})
                require(execution is not None and execution.state == 'completed', 'production_parser_execution_failed')
                check_receipt(execution.receipt, expected_limits)
                selection = db.get(ParserSelection, live['query_id'])
                require(selection is not None, 'production_selection_missing')
                bundle = db.get(ParserBundle, selection.bundle_id)
                require(bundle is not None, 'production_bundle_missing')
                verify_bundle(bundle.manifest)
                report['bundle_id'] = bundle.id
                report['bundle_manifest_sha256'] = sha(json.dumps(bundle.manifest, sort_keys=True).encode())
            require(live['data_state'] == 'live' and len(live['variants']) == 2, 'live_adoption_failed')
            require({row['manufacturer_product_code'] for row in live['variants']} == EXPECTED_CODES, 'parsed_code_scope_mismatch')
            accepted_snapshot = live['provenance'][0]['snapshot_id']
            policy = policy_descriptor()
            require(policy['version'] == 'field-authority@1', 'unexpected_field_policy')
            checks = []
            for row in live['variants']:
                code = row['manufacturer_product_code']
                contract = row['identity_contract']
                require(contract['state'] == 'current' and contract['current_identity']['product_code_type'] == 'MATERIAL_CODE',
                        'namespace_not_preserved')
                resolution = row['field_resolution']
                require(resolution['policy'] == policy and resolution['scope'] == 'current_source', 'field_policy_scope_mismatch')
                fields = {item['field']: item for item in resolution['fields']}
                with database.sessions() as db:
                    facts = list(db.scalars(select(FactVersion).where(FactVersion.variant_id == row['id'])))
                    require(len(facts) == 1 and facts[0].snapshot_id == accepted_snapshot, 'fact_reference_mismatch')
                    fact_id = facts[0].id
                for field in ('run_flat', 'utqg_treadwear'):
                    decision = fields[field]
                    require(decision['has_default'] and decision['state'] == 'uncontested'
                            and type(decision['default_value']) is type(expected[code][field])
                            and decision['default_value'] == expected[code][field], 'raw_default_value_mismatch')
                    require(len(decision['candidates']) == 1, 'unexpected_candidate_expansion')
                    candidate = decision['candidates'][0]
                    require(candidate['snapshot_id'] == accepted_snapshot and candidate['fact_version_id'] == fact_id
                        and candidate['raw_hash'] == snapshot['raw_hash'] and candidate['source_id'] == SOURCE
                        and candidate['eligible'] and candidate['authority']['tier'] == 1 and candidate['evidence_locator'],
                        'candidate_provenance_or_authority_mismatch')
                    checks.append({'code': code, 'field': field, 'default_value': decision['default_value'],
                                   'candidate_id': candidate['id'], 'fact_version_id': fact_id})
            transport['mode'] = '304'
            throttle = registry._states[registry.SPECS[SOURCE].origin]
            delay = throttle['last'] + throttle['interval'] - time.monotonic()
            if delay > 0:
                time.sleep(min(delay + .02, 5))
            response = client.post(f'/v1/sources/{SOURCE}/live-query', json={'query': query, 'fallback_policy': 'never'})
            require(response.status_code == 200, 'private_304_query_failed')
            verified = response.json()
            save(output / 'verified-304.json', verified)
            require(verified['data_state'] == 'live_verified_304'
                    and verified['provenance'][0]['snapshot_id'] == accepted_snapshot
                    and verified['snapshot_observed_at'] == live['snapshot_observed_at'], '304_changed_content_observation')
            for row in verified['variants']:
                before = next(value for value in live['variants'] if value['id'] == row['id'])
                for field in ('run_flat', 'utqg_treadwear'):
                    original = next(value for value in before['field_resolution']['fields'] if value['field'] == field)
                    current = next(value for value in row['field_resolution']['fields'] if value['field'] == field)
                    require(current['default_value'] == original['default_value']
                            and current['candidates'][0]['observed_at'] == original['candidates'][0]['observed_at']
                            and current['candidates'][0]['dimensions']['time']['verification_used_for_rank'] is False,
                            '304_changed_field_content_time')
            with database.sessions() as db:
                require(db.get(ParserExecution, verified['query_id']).state == 'not_modified', '304_started_parser')
                require(db.get(Snapshot, accepted_snapshot).identity_contract_version == IDENTITY_CONTRACT_VERSION,
                        'snapshot_identity_schema_missing')
                captures = list(db.scalars(select(RawCapture)))
                require(len(captures) == 1 and checked_capture_bytes(db, captures[0])[0] == snapshot['body'].encode('utf-8'),
                        'capture_body_changed')
                report['stored_counts'] = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                    for model in (Snapshot, TireVariant, FactVersion, Verification, RawCapture, SourceQuarantine, AIRequest, EmbeddingRequest)}
                require(report['stored_counts']['source_quarantines'] == 0 and report['stored_counts']['ai_requests'] == 0
                        and report['stored_counts']['embedding_requests'] == 0, 'unexpected_quarantine_or_model_record')
            require(counters['parser_child_starts'] == len(report['receipts']) == 1, 'parser_child_count_not_one')
            require(counters['model_calls'] == counters['external_network_attempts'] == 0, 'unexpected_external_call')
            report.update(stage='passed', field_checks=checks, transport=transport, policy=policy,
                          accepted_snapshot_id=accepted_snapshot, verified_304_no_new_child=True)
    finally:
        database.engine.dispose()


def run(output):
    output = Path(output).resolve()
    require(output.is_relative_to((ROOT / '.artifacts').resolve()) and not output.exists(), 'new_workspace_output_required')
    snapshot, query, expected, backup_hash = load_saved_input()
    output.mkdir(parents=True)
    (output / 'saved-official-body.html').write_bytes(snapshot['body'].encode('utf-8'))
    save(output / 'saved-source.json', {**{key: value for key, value in snapshot.items() if key != 'body'},
        'query': query, 'expected_raw_fields': expected, 'backup_sha256': backup_hash})
    private_root = Path(tempfile.mkdtemp(prefix='ti39f-')).resolve()
    report = {'status': 'running', 'stage': 'starting', 'scope': 'saved_official_body_real_parser_private_sqlite',
        'normal_database_used': False, 'new_official_fetch': False, 'actual_human_review': False, 'release_approved': False,
        'backup_sha256_before': backup_hash, 'saved_snapshot_id': SNAPSHOT_ID, 'raw_sha256': snapshot['raw_hash'],
        'private_root': str(private_root), 'receipts': [], 'parser_temp_directories': [],
        'counters': {'external_network_attempts': 0, 'model_calls': 0, 'parser_child_starts': 0, 'replayed_http_responses': 0}}
    save(output / 'report.json', report)
    try:
        private_run(output, private_root, report, snapshot, query, expected)
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error)[:2000])
        raise
    finally:
        report['backup_sha256_after'] = sha(BACKUP.read_bytes())
        report['original_backup_and_records_unchanged'] = report['backup_sha256_after'] == backup_hash
        cleanup = {'private_root': str(private_root), 'parser_pids': [], 'parser_temp_directories': []}
        try:
            cleanup['parser_pids'] = [{'pid': item['receipt']['pid'], 'alive': pid_alive(item['receipt']['pid'])}
                for item in report['receipts'] if isinstance(item.get('receipt'), dict) and item['receipt'].get('pid')]
            cleanup['parser_temp_directories'] = [{'path': path, 'exists': Path(path).exists()}
                                                  for path in report['parser_temp_directories']]
            shutil.copytree(private_root, output / 'private-checkpoint')
        finally:
            require(private_root.parent == Path(tempfile.gettempdir()).resolve() and private_root.name.startswith('ti39f-'),
                    'unexpected_cleanup_target')
            shutil.rmtree(private_root)
            cleanup['private_storage_removed'] = not private_root.exists()
            report['cleanup'] = cleanup
            if (not report['original_backup_and_records_unchanged'] or not cleanup['private_storage_removed']
                    or any(item['alive'] for item in cleanup['parser_pids'])
                    or any(item['exists'] for item in cleanup['parser_temp_directories'])):
                report['status'] = 'failed'
            save(output / 'cleanup.json', cleanup)
            save(output / 'report.json', report)
        print(json.dumps({'status': report['status'], 'report': str(output / 'report.json'),
                          'parser_children': report['counters']['parser_child_starts']}), flush=True)
    require(report['status'] == 'passed', 'acceptance_or_cleanup_failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Requires the separately granted exclusive Parser window')
    parser.add_argument('--check-input', action='store_true', help='Read only the backup and check fixed raw fields; no app/Parser imports')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.check_input and not args.execute:
        snapshot, query, expected, backup_hash = load_saved_input()
        print(json.dumps({'status': 'input_checked_no_parser', 'source_id': SOURCE, 'saved_snapshot_id': SNAPSHOT_ID,
            'backup_sha256': backup_hash, 'raw_sha256': snapshot['raw_hash'], 'body_bytes': len(snapshot['body'].encode('utf-8')),
            'query': query, 'expected_raw_fields': expected, 'parser_children': 0}, ensure_ascii=False))
        return
    if not args.execute or args.check_input or args.output is None:
        parser.error('Use --check-input or --execute --output NEW_ARTIFACT_DIRECTORY')
    run(args.output)


if __name__ == '__main__':
    main()
