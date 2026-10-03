"""Private Golden workflow fixture: real HTTP and Parser children, synthetic truth.

Only this fixture's temporary SQLite/object/bundle directories are written. No
signature produced here represents a person reviewing real manufacturer data.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from http.cookiejar import CookieJar
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import sys
import tempfile
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'hankook-us'
SIGNED = {'operator': 'Synthetic Golden QA',
          'reason': 'Automated synthetic workflow check; not actual human-reviewed truth'}


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


class Client:
    def __init__(self, base):
        if not re.fullmatch(r'http://127\.0\.0\.1:[0-9]+', base):
            raise ValueError('Only an explicit loopback fixture is supported')
        if int(base.rsplit(':', 1)[-1]) in {3000, 8000}:
            raise ValueError('Normal Web/API ports cannot be used as a Golden fixture')
        self.base = base
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

    def call(self, path, payload=None, *, key=None, status=200):
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Idempotency-Key'] = key
        request = Request(self.base + path, headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None)
        try:
            response = self.opener.open(request, timeout=100)
        except HTTPError as error:
            response = error
        with response:
            value = json.load(response)
            if response.status != status:
                raise AssertionError(f'{path}: expected HTTP {status}, got {response.status}: {value}')
            return value

    def post(self, path, payload, *, status=201, key=None):
        return self.call(path, payload, key=key or str(uuid4()), status=status)


def case_payload(capture, expected, title):
    return {**SIGNED, 'kind': 'tire', 'source_id': SOURCE, 'title': title,
        'capture_id': capture, 'evidence_note': 'Synthetic fixture rows, codes 9370001/9370002. Not official truth.',
        'expected': expected, 'expected_revision': 0, 'expected_fingerprint': None}


def review_payload(case, action='approve'):
    return {**SIGNED, 'case_revision': case['revision'], 'case_fingerprint': case['fingerprint'],
        'expected_revision': case['review_revision'], 'expected_fingerprint': case['review_fingerprint'],
        'action': action, 'acknowledged': True}


def freeze(client, case, title):
    case = client.post(f"/v1/golden/cases/{case['id']}/reviews", review_payload(case))
    reference = {name: case[name] for name in ('review_revision', 'review_fingerprint')}
    reference.update(case_id=case['id'], case_revision=case['revision'], case_fingerprint=case['fingerprint'])
    return client.post('/v1/golden/sets', {**SIGNED, 'title': title, 'source_id': SOURCE,
        'case_refs': [reference], 'expected_revision': 0, 'expected_fingerprint': None, 'acknowledged': True})


def evaluation_payload(state, frozen):
    return {'mode': 'history', 'source_id': SOURCE, 'target_bundle_id': state['bundle_id'],
        'capture_ids': frozen['capture_ids'], 'expected_deployment_revision': state['deployment_revision'],
        'golden_set_id': frozen['id'], 'expected_golden_set_revision': frozen['revision'],
        'golden_set_fingerprint': frozen['fingerprint']}


def approval_payload(evaluation):
    return {**SIGNED, 'mode': 'history', 'expected_revision': evaluation['review_revision'],
        'completion_fingerprint': evaluation['completion']['fingerprint'], 'action': 'approve',
        'acknowledged': True, 'acknowledge_reference_gaps': True}


def api_counterexamples(client, output):
    """Run after the browser success path; all assertions use production endpoints."""
    output = Path(output)
    report = {'status': 'running', 'scope': 'synthetic_expectations_real_http_real_parser', 'checks': [], 'evaluations': {}}
    save(output / 'api-counterexamples.json', report)
    def checked(name):
        report['checks'].append(name)
        save(output / 'api-counterexamples.json', report)
    try:
        state = client.call('/fixture/state')
        assert state['scope'] == 'synthetic_truth_real_http_real_parser_private_sqlite'
        assert state['normal_database_used'] is False and state['actual_human_review'] is False
        client.post('/v1/golden/sets', {**SIGNED, 'title': 'Rejected empty set', 'source_id': SOURCE,
            'case_refs': [], 'expected_revision': 0, 'expected_fingerprint': None,
            'acknowledged': True}, status=422)
        checked('empty_set_rejected')
        client.post('/v1/golden/cases', case_payload(state['pair_capture_id'], {'records': []}, 'Empty truth'), status=422)
        checked('empty_truth_rejected')
        for name in ('wrong_field', 'same_count_replacement', 'single_sku'):
            capture = state['single_capture_id'] if name == 'single_sku' else state['pair_capture_id']
            expected = deepcopy(state['single_expected'] if name == 'single_sku' else state['expected'])
            if name == 'wrong_field':
                expected['records'][0]['value']['facts']['utqg_treadwear'] = 999
            elif name == 'same_count_replacement':
                expected['records'][1]['value']['manufacturer_product_code'] = '9370099'
            case = client.post('/v1/golden/cases', case_payload(capture, expected, 'Synthetic ' + name))
            frozen = freeze(client, case, 'Synthetic ' + name + ' set')
            current = client.call('/fixture/state')
            evaluation = client.post('/v1/parser-evaluations', evaluation_payload(current, frozen))
            save(output / (name + '-evaluation.json'), evaluation)
            gate = evaluation['golden_gate']
            report['evaluations'][name] = {'id': evaluation['id'], 'state': gate['state']}
            assert gate['state'] == ('inconclusive' if name == 'single_sku' else 'failed'), gate
            assert not evaluation['can_approve']
            if name == 'single_sku':
                assert gate['report']['wrong_merge_count'] is None
            client.post(f"/v1/parser-evaluations/{evaluation['id']}/reviews", approval_payload(evaluation), status=409)
            checked(name + '_cannot_be_approved_even_with_reference_gap_acknowledgement')
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        save(output / 'api-counterexamples.json', report)
    return report


def _serve_owned(port, output, private_root, owned):
    if port in {3000, 8000} or not 1024 <= port <= 65535:
        raise ValueError('A separate unprivileged fixture port is required')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'fixture.json').exists():
        raise ValueError('Use a new output directory; previous evidence must be preserved')
    database_path = private_root / 'private.sqlite'
    os.environ.update(TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
        DATABASE_URL='sqlite:///' + database_path.as_posix(), TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0',
        TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(private_root / 'objects'),
        TI_PARSER_BUNDLE_ROOT=str(private_root / 'bundles'), TI_OBSERVABILITY_ENABLED='1', TI_OBSERVABILITY_LOGS='0',
        TIRE_CORS_ORIGINS='http://127.0.0.1:3000,http://localhost:3000')
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    import aiohttp
    import uvicorn
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from tire_api.adapters import hankook, registry
    from tire_api.domain import VariantInput
    from tire_api.golden_checks import validate_expected
    from tire_api.main import create_app
    from tire_api.parser_release_models import ParserEvaluation, ParserEvaluationCompletion
    from tire_api.parser_releases import bootstrap_source, current_deployment
    from test_reparse import BODY, QUERY, seed_capture, totals

    counters = {'external_network_attempts': 0, 'source_calls': 0, 'model_calls': 0, 'child_starts': 0}
    def blocked_network(*_args, **_kwargs):
        counters['external_network_attempts'] += 1
        raise RuntimeError('External transport is disabled in the private Golden fixture')
    aiohttp.ClientSession = blocked_network
    def audit(event, arguments):
        if event == 'subprocess.Popen':
            counters['child_starts'] += 1
        elif event in {'socket.connect', 'socket.getaddrinfo'}:
            target = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
            if target not in {'127.0.0.1', '::1', 'localhost'}:
                blocked_network()
        elif event == 'sqlite3.connect':
            target = str(arguments[0])
            if target != ':memory:' and not Path(target).resolve().is_relative_to(private_root):
                raise RuntimeError('The fixture may only connect to its owned SQLite directory')
    sys.addaudithook(audit)

    class OfflineRegistry:
        supports_parser_deployments = True
        @staticmethod
        def sources():
            return [row for row in registry.sources() if row['id'] == SOURCE]
        async def fetch(self, *_args, **_kwargs):
            counters['source_calls'] += 1
            raise RuntimeError('Source queries are forbidden in this fixture')

    app = create_app(os.environ['TIRE_DATABASE_URL'], OfflineRegistry())
    owned['app'] = app
    database = app.state.database
    database.initialize()
    # Explicitly mutate a stored excerpt into synthetic input. The original is unchanged.
    pair = '<!-- SYNTHETIC GOLDEN WORKFLOW ONLY -->\n' + BODY.replace('1022631', '9370001').replace('1022632', '9370002')
    sections = pair.split('<li>')
    assert len(sections) == 3, 'Fixture must retain two top-level specification rows'
    single = sections[0] + '<li>' + sections[1] + '</ul></div></section>\n'
    def scaffold(body):
        rows = [VariantInput.model_validate(row).model_dump() for row in hankook.parse_html(body, QUERY)]
        return validate_expected('tire', {'records': [{'golden_sku_id': 'synthetic-' + row['manufacturer_product_code'],
            'value': row} for row in rows]})
    expected, single_expected = scaffold(pair), scaffold(single)
    assert len(expected['records']) == 2 and len(single_expected['records']) == 1
    client = TestClient(app)
    pair_capture = seed_capture(client, database, body=pair)
    single_capture = seed_capture(client, database, body=single)
    client.close()
    with database.sessions() as db:
        deployment = bootstrap_source(db, SOURCE, **SIGNED)
        bundle_id = deployment.bundle_id
    formal_before = totals(database)
    save(output / 'synthetic-expected.json', expected)
    (output / 'synthetic-pair.html').write_text(pair, encoding='utf-8')
    metadata = {'scope': 'synthetic_truth_real_http_real_parser_private_sqlite', 'normal_database_used': False,
        'actual_human_review': False, 'base_url': f'http://127.0.0.1:{port}', 'source_id': SOURCE,
        'pair_capture_id': pair_capture, 'single_capture_id': single_capture, 'bundle_id': bundle_id,
        'expected': expected, 'single_expected': single_expected, 'raw_sha256': hashlib.sha256(pair.encode()).hexdigest(),
        'expected_origin': 'Parser-derived synthetic workflow scaffold, not independently reviewed truth'}
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='warning'))

    def state():
        with database.sessions() as db:
            current = current_deployment(db, SOURCE)
            names = ('golden_cases', 'golden_case_revisions', 'golden_case_reviews', 'golden_set_revisions',
                     'parser_evaluations', 'parser_evaluation_reviews', 'parser_deployment_revisions',
                     'ai_requests', 'embedding_requests', 'parser_executions')
            from sqlalchemy import text
            counts = {name: db.execute(text('SELECT COUNT(*) FROM ' + name)).scalar_one() for name in names}
            completions = db.scalars(select(ParserEvaluationCompletion)).all()
            receipts = [item['candidate_receipt'] for done in completions for item in done.results if item.get('candidate_receipt')]
            return {**metadata, 'counters': dict(counters), 'counts': counts, 'deployment_revision': current.revision,
                'deployment_state': current.state, 'formal_unchanged': totals(database) == formal_before,
                'candidate_receipts': receipts, 'private_db_bytes': database_path.stat().st_size}

    @app.get('/fixture/state')
    def fixture_state():
        return state()

    @app.post('/fixture/shutdown')
    def shutdown():
        save(output / 'fixture-before-shutdown.json', state())
        server.should_exit = True
        return {'shutdown_requested': True}

    save(output / 'fixture.json', metadata)
    print(json.dumps({'ready': True, 'base_url': metadata['base_url'], 'output': str(output)}), flush=True)
    final = {'status': 'running', 'normal_database_used': False, 'actual_human_review': False}
    try:
        server.run()
        final['status'] = 'stopped'
    except BaseException as error:
        final.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        database.close()
        try:
            # Copy only after the owned API has closed all SQLite handles.
            shutil.copy2(database_path, output / 'private-checkpoint.sqlite')
            final['private_checkpoint_bytes'] = (output / 'private-checkpoint.sqlite').stat().st_size
            shutil.copytree(private_root / 'bundles', output / 'bundles-checkpoint')
            shutil.copytree(private_root / 'objects', output / 'objects-checkpoint')
        finally:
            if private_root.parent != Path(tempfile.gettempdir()).resolve() or not private_root.name.startswith('tire-golden-'):
                raise RuntimeError('Refusing unexpected cleanup target')
            shutil.rmtree(private_root)
            final.update(private_storage_removed=not private_root.exists(), counters=counters)
            save(output / 'fixture-final.json', final)


def serve(port, output):
    """Also clean owned storage when import, schema initialization or seeding fails."""
    private_root = Path(tempfile.mkdtemp(prefix='tire-golden-')).resolve()
    owned = {}
    try:
        _serve_owned(port, output, private_root, owned)
    finally:
        if 'app' in owned:
            owned['app'].state.database.close()
            owned['app'].state.telemetry.shutdown()
        if private_root.exists():
            if private_root.parent != Path(tempfile.gettempdir()).resolve() or not private_root.name.startswith('tire-golden-'):
                raise RuntimeError('Refusing unexpected setup cleanup target')
            shutil.rmtree(private_root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--serve', action='store_true', help='Start an owned temporary API; POST /fixture/shutdown to finish')
    mode.add_argument('--check-api', action='store_true', help='Run negative API scenarios against an existing private fixture')
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.serve:
        serve(args.port, args.output)
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        api_counterexamples(Client(args.base), args.output)


if __name__ == '__main__':
    main()
