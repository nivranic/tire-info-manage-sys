"""One real bounded Parser completes before a source pause blocks adoption.

The only source body is read from the immutable Round 41 before backup. HTTP is
a fixed local replay; Registry, bundle selection, child and QueryService are real.
This does not test cancellation of already dispatched HTTP or an existing child.
--execute requires a separately granted exclusive Parser window.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from uuid import uuid4

from field_authority_parser_acceptance import check_receipt, pid_alive, raw_expectations, require, save, sha

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / '.artifacts/runtime/round41-before.sqlite'
SNAPSHOT_ID = '169436f3-1238-4301-80b7-7be9478e0e9b'
SOURCE = 'hankook-us'
EXPECTED_CODES = {'1022631', '1022632'}


def load_saved_input():
    require(BACKUP.is_file(), 'authorized_backup_missing')
    backup_hash = sha(BACKUP.read_bytes())
    with sqlite3.connect(BACKUP.resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        row = db.execute('SELECT id, source_id, query_key, source_url, raw_hash, body, content_type, '
            'parser_version, observed_at FROM snapshots WHERE id=?', (SNAPSHOT_ID,)).fetchone()
        require(row is not None and row['source_id'] == SOURCE, 'saved_snapshot_missing')
        snapshot = dict(row)
        query_row = db.execute('SELECT query FROM query_runs WHERE source_id=? AND query_key=? '
            'ORDER BY created_at, id LIMIT 1', (SOURCE, snapshot['query_key'])).fetchone()
        require(query_row is not None, 'saved_query_missing')
        query = json.loads(query_row['query'])
    require(sha(snapshot['body'].encode('utf-8')) == snapshot['raw_hash'], 'saved_raw_hash_mismatch')
    require(query == {'size': '205/45R17', 'model': 'Ventus S1 evo3'}, 'saved_query_scope_changed')
    expected = raw_expectations(snapshot['body'])
    require(sha(BACKUP.read_bytes()) == backup_hash, 'backup_changed_during_read')
    return snapshot, query, expected, backup_hash


def file_hashes(directory):
    return {str(path.relative_to(directory)).replace('\\', '/'): sha(path.read_bytes())
            for path in sorted(directory.rglob('*')) if path.is_file()}


def empty_response(value, reason):
    require(value['data_state'] == 'source_unavailable' and value['reason'] == reason,
            'management_block_not_reported')
    require(value['variants'] == value['provenance'] == value['conflicts'] == []
            and value['consent_id'] is None and value['verified_at'] is None,
            'blocked_query_exposed_evidence_or_consent')


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
            from tire_api.parser_runtime import _command
            command, expected_command = arguments[1], _command()
            if isinstance(command, str):
                prefix = subprocess.list2cmdline(expected_command) + ' --execution-root '
                execution_root = command[len(prefix):].strip('"') if command.startswith(prefix) else None
            else:
                execution_root = (command[-1] if isinstance(command, (tuple, list))
                    and list(command[:-2]) == expected_command and command[-2] == '--execution-root' else None)
            allowed = {Path(path) / 'package' for path in report['parser_temp_directories']}
            require(execution_root is not None and Path(execution_root).resolve() in allowed,
                    'only_exact_production_parser_command_allowed')
            require(counters['parser_child_starts'] == 0, 'only_one_parser_child_allowed')
            counters['parser_child_starts'] += 1

    sys.addaudithook(audit)
    original_popen = subprocess.Popen

    class TrackedPopen(original_popen):
        # asyncio.windows_utils subclasses Popen during import. Keep its class
        # contract intact while recording the actual process returned by Windows.
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            report['launched_pids'].append(self.pid)

    subprocess.Popen = TrackedPopen
    import aiohttp
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from tire_api.adapters import registry
    from tire_api.ai_models import AIEvidencePack, AIRequest
    from tire_api.captures import checked_capture_bytes
    from tire_api.db import (AlertEvent, ChangeEvent, FactVersion, FallbackConsent, NotificationDelivery,
                            QueryRun, RawCapture, Snapshot, SourceQuarantine, TireVariant, Verification)
    from tire_api.domain import digest
    from tire_api.embedding_models import EmbeddingRequest
    from tire_api.main import create_app
    from tire_api.parser_bundles import verify_bundle
    from tire_api.parser_release_models import ParserBundle, ParserExecution, ParserSelection
    from tire_api.parser_runtime import limits
    from tire_api.source_setting_models import SourceSettingRevision
    from tire_api.source_settings import (SourceAccessBlocked, SourceSettingDecision, SourceSettingPreview,
        append_source_setting, assert_source_run_access, preview_source_setting)

    aiohttp.ClientSession = forbid_network
    require(sys.platform == 'win32', 'this_acceptance_requires_windows_job_limits')
    expected_limits = limits()
    require(expected_limits['wall_seconds'] == 8 and expected_limits['max_concurrent'] == 2
        and expected_limits['cpu_seconds'] == 5 and expected_limits['memory_bytes'] == 384 * 1024 * 1024,
        'production_parser_limits_changed')
    require(digest(query) == snapshot['query_key'], 'saved_query_hash_mismatch')
    target = registry.query_url(query, SOURCE)
    require(target == snapshot['source_url'], 'saved_registry_url_changed')
    report['limits'] = expected_limits
    transport = []

    class ReplayHTTP:
        def __init__(self, hosts):
            require(hosts == frozenset({registry.SPECS[SOURCE].host}), 'unexpected_replay_host')

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, headers=None, **_kwargs):
            require(counters['registry_fetch_calls'] == 1 and counters['parser_child_starts'] == 0,
                    'unexpected_transport_after_parser_or_second_fetch')
            counters['replayed_http_responses'] += 1
            transport.append({'url': url, 'headers': dict(headers or {}), 'status': 200})
            if url == registry.SPECS[SOURCE].origin + '/robots.txt':
                return SimpleNamespace(status=200, url=url, body='User-agent: *\nAllow: /\n',
                    content_type='text/plain', etag=None, last_modified=None)
            require(url == target and not headers, 'unexpected_replay_url_or_validators')
            return SimpleNamespace(status=200, url=url, body=snapshot['body'], content_type=snapshot['content_type'],
                etag='"round41-saved-official-replay"', last_modified=None)

    registry.SafeHttpClient = ReplayHTTP
    registry._states.clear()
    registry._robots.clear()
    registry._robots_requests.clear()
    app = create_app(os.environ['TIRE_DATABASE_URL'], registry)
    database = app.state.database

    class ForbiddenModel:
        async def generate(self, *_args, **_kwargs):
            counters['model_calls'] += 1
            raise RuntimeError('model_forbidden')

    app.state.ai_adapter = ForbiddenModel()
    original_fetch = registry.fetch
    frozen_bundles = {}

    def change_source(action):
        # Deliberately use a different Session from QueryService's request session.
        with database.sessions() as writer:
            preview = preview_source_setting(writer, SOURCE, SourceSettingPreview(action=action), registry=registry)
            payload = SourceSettingDecision(action=action, expected_revision=preview['revision'],
                expected_fingerprint=preview['fingerprint'], operator='本机真实Parser验收',
                reason='保存官方原文回放；在Parser退出后检查来源采纳门')
            return append_source_setting(writer, SOURCE, payload, 'private-parser-acceptance', str(uuid4()), registry=registry)

    async def pause_after_completed_parser(source_id, submitted_query, cached=None, **kwargs):
        counters['registry_fetch_calls'] += 1
        require(source_id == SOURCE and submitted_query == query and counters['registry_fetch_calls'] == 1,
                'unexpected_registry_fetch')
        result = await original_fetch(source_id, submitted_query, cached=cached, **kwargs)
        receipt = deepcopy(result.get('parser_receipt'))
        if isinstance(receipt, dict):
            report['receipts'].append({'phase': 'completed_before_management_pause',
                'state': result['status'], 'error_code': result.get('reason'), 'receipt': receipt})
            save(output / 'report.json', report)
        require(result['status'] == 'ok', 'production_parser_failed_before_pause')
        check_receipt(receipt, expected_limits)
        require(receipt.get('limits_backend') == 'windows_job_object', 'windows_job_limit_backend_missing')
        require(result.get('parser_version') == 'hankook-us-spec-cards@1.1.0', 'unexpected_hankook_parser_version')
        rows = result['variants']
        require(len(rows) == 2 and {row['manufacturer_product_code'] for row in rows} == EXPECTED_CODES,
                'parsed_code_scope_mismatch')
        fields = []
        for row in rows:
            code = row['manufacturer_product_code']
            require(row['facts'].get('product_code_type') == 'MATERIAL_CODE', 'parsed_namespace_missing')
            require(row['size'] == query['size'] and type(row['run_flat']) is bool
                and row['run_flat'] is expected[code]['run_flat']
                and type(row['facts'].get('utqg_treadwear')) is int
                and row['facts']['utqg_treadwear'] == expected[code]['utqg_treadwear'], 'parsed_raw_field_mismatch')
            fields.append({'code': code, 'product_code_type': 'MATERIAL_CODE', 'size': row['size'],
                'run_flat': row['run_flat'], 'utqg_treadwear': row['facts']['utqg_treadwear']})
        save(output / 'parsed-before-rejection.json', {'source_id': SOURCE, 'raw_sha256': snapshot['raw_hash'],
            'parser_version': result['parser_version'], 'parser_identity': result['parser_identity'],
            'variants': rows, 'field_checks': fields, 'accepted_as_facts': False})
        report['field_checks'] = fields
        frozen_bundles.update(file_hashes(private_root / 'bundles'))
        require(bool(frozen_bundles), 'sealed_bundle_files_missing')
        transition = change_source('pause')
        require(transition['source']['management']['state'] == 'paused'
            and transition['source']['management']['access_generation'] == 1, 'pause_generation_mismatch')
        save(output / 'pause-after-parser.json', transition)
        counters['management_pauses'] += 1
        return result

    registry.fetch = pause_after_completed_parser
    models = (Snapshot, TireVariant, FactVersion, Verification, ChangeEvent, AlertEvent, NotificationDelivery,
              SourceQuarantine, FallbackConsent, AIEvidencePack, AIRequest, EmbeddingRequest)
    try:
        with TestClient(app) as client:
            require(client.get('/health').status_code == 200, 'private_api_unavailable')
            report['stage'] = 'production_parser_running'
            save(output / 'report.json', report)
            request = {'query': query, 'fallback_policy': 'ask'}
            response = client.post(f'/v1/sources/{SOURCE}/live-query', json=request)
            require(response.status_code == 200, 'private_query_http_failed')
            blocked = response.json()
            save(output / 'inflight-blocked.json', blocked)
            empty_response(blocked, 'source_access_changed')
            with database.sessions() as db:
                run = db.get(QueryRun, blocked['query_id'])
                require(run.source_access_generation == 0, 'initial_access_generation_not_frozen')
                execution = db.get(ParserExecution, run.id)
                require(execution is not None and execution.state == 'completed'
                    and execution.receipt == report['receipts'][0]['receipt'], 'completed_receipt_not_retained')
                selection = db.get(ParserSelection, run.id)
                require(selection is not None, 'production_selection_missing')
                bundle = db.get(ParserBundle, selection.bundle_id)
                require(bundle is not None, 'production_bundle_missing')
                verify_bundle(bundle.manifest)
                report['bundle_id'] = bundle.id
                report['bundle_manifest_sha256'] = sha(json.dumps(bundle.manifest, sort_keys=True).encode())
                captures = list(db.scalars(select(RawCapture)))
                require(len(captures) == 1 and captures[0].query_id == run.id
                    and checked_capture_bytes(db, captures[0])[0] == snapshot['body'].encode('utf-8'),
                    'received_raw_not_retained')
                report['capture_id'] = captures[0].id
                report['stored_counts_after_inflight'] = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                                                         for model in models}
                require(not any(report['stored_counts_after_inflight'].values()), 'blocked_adoption_created_formal_records')
            before_paused_query = dict(counters)
            response = client.post(f'/v1/sources/{SOURCE}/live-query', json=request)
            require(response.status_code == 200, 'paused_query_http_failed')
            paused = response.json()
            save(output / 'paused-query.json', paused)
            empty_response(paused, 'source_paused')
            require(counters == before_paused_query, 'paused_query_started_fetch_child_or_model')
            denied = client.post('/v1/fallback-consents', json={'query_id': paused['query_id'], 'decision': 'allow', 'scope': 'once'})
            require(denied.status_code == 409, 'paused_query_offered_consent')
            save(output / 'paused-consent-denied.json', denied.json())
            enabled = change_source('enable')
            require(enabled['source']['management']['access_generation'] == 2, 'resume_generation_mismatch')
            save(output / 'enabled-no-refetch.json', enabled)
            with database.sessions() as db:
                old_run = db.get(QueryRun, blocked['query_id'])
                try:
                    assert_source_run_access(db, old_run, registry=registry)
                except SourceAccessBlocked as error:
                    require(error.code == 'source_access_changed', 'wrong_stale_generation_reason')
                else:
                    raise RuntimeError('resume_reauthorized_old_run')
                require(db.get(QueryRun, paused['query_id']).source_access_generation is None, 'blocked_query_got_access_pin')
                require(db.get(ParserSelection, paused['query_id']) is None
                    and db.get(ParserExecution, paused['query_id']) is None, 'paused_query_selected_or_executed_parser')
                report['stored_counts_final'] = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                    for model in (*models, RawCapture, QueryRun, ParserExecution, ParserSelection, ParserBundle, SourceSettingRevision)}
                require(all(report['stored_counts_final'][model.__tablename__] == 0 for model in models),
                        'later_control_step_created_formal_records')
                require(report['stored_counts_final']['raw_captures'] == 1
                    and report['stored_counts_final']['query_runs'] == 2
                    and report['stored_counts_final']['parser_executions'] == 1
                    and report['stored_counts_final']['parser_selections'] == 1
                    and report['stored_counts_final']['source_setting_revisions'] == 2, 'unexpected_control_counts')
            require(file_hashes(private_root / 'bundles') == frozen_bundles, 'source_control_changed_sealed_bundle_files')
            save(output / 'sealed-bundle-files.json', frozen_bundles)
            require(counters['parser_child_starts'] == len(report['launched_pids']) == len(report['receipts']) == 1,
                    'parser_child_count_not_one')
            require(counters['registry_fetch_calls'] == counters['management_pauses'] == 1
                    and counters['replayed_http_responses'] == 2, 'unexpected_replay_counts')
            require(counters['model_calls'] == counters['external_network_attempts'] == 0, 'unexpected_external_call')
            require(counters == before_paused_query, 'control_operations_triggered_execution')
            report.update(stage='passed', transport=transport, paused_query_no_new_fetch_or_child=True,
                resumed_old_run_still_stale=True, original_sealed_bundle_files_unchanged=True,
                sealed_bundle_file_count=len(frozen_bundles), parser_completed_before_pause=True,
                in_flight_cancellation_tested=False)
    finally:
        registry.fetch = original_fetch
        subprocess.Popen = original_popen
        database.engine.dispose()


def run(output):
    output = Path(output).resolve()
    require(output.is_relative_to((ROOT / '.artifacts').resolve()) and not output.exists(), 'new_workspace_output_required')
    snapshot, query, expected, backup_hash = load_saved_input()
    output.mkdir(parents=True)
    (output / 'saved-official-body.html').write_bytes(snapshot['body'].encode('utf-8'))
    save(output / 'saved-source.json', {**{key: value for key, value in snapshot.items() if key != 'body'},
        'query': query, 'expected_raw_fields': expected, 'backup_sha256': backup_hash})
    temp_root = Path(tempfile.gettempdir()).resolve()
    private_root = Path(tempfile.mkdtemp(prefix='ti41s-')).resolve()
    report = {'status': 'running', 'stage': 'starting', 'scope': 'saved_official_body_real_parser_management_fence',
        'normal_database_used': False, 'new_official_fetch': False, 'actual_human_review': False, 'release_approved': False,
        'backup_sha256_before': backup_hash, 'saved_snapshot_id': SNAPSHOT_ID, 'raw_sha256': snapshot['raw_hash'],
        'private_root': str(private_root), 'receipts': [], 'launched_pids': [], 'parser_temp_directories': [],
        'counters': {'external_network_attempts': 0, 'model_calls': 0, 'parser_child_starts': 0,
                     'replayed_http_responses': 0, 'registry_fetch_calls': 0, 'management_pauses': 0}}
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
        cleanup = {'private_root': str(private_root), 'parser_pids': [], 'parser_temp_directories': [],
                   'private_storage_removed': False}
        try:
            pids = set(report['launched_pids']) | {item['receipt']['pid'] for item in report['receipts']
                if isinstance(item.get('receipt'), dict) and item['receipt'].get('pid')}
            cleanup['parser_pids'] = [{'pid': pid, 'alive': pid_alive(pid)} for pid in sorted(pids)]
            cleanup['parser_temp_directories'] = [{'path': path, 'exists': Path(path).exists()}
                                                  for path in report['parser_temp_directories']]
            require(private_root.resolve() == private_root and private_root.parent == temp_root
                and private_root.name.startswith('ti41s-') and not private_root.is_symlink(), 'unexpected_cleanup_target')
            shutil.copytree(private_root, output / 'private-checkpoint')
            if not any(item['alive'] for item in cleanup['parser_pids']):
                shutil.rmtree(private_root)
                cleanup['private_storage_removed'] = not private_root.exists()
        finally:
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
    parser.add_argument('--check-input', action='store_true', help='Immutable backup and fixed raw fields only; no app/Parser import')
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
