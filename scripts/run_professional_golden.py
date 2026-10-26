"""Capture actual R71/R75 HTTP in new private SQLite roots, then evaluate offline."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import sys
import threading
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests'), str(ROOT / 'scripts')]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if path.parent.name == 'actuals' and len(raw) > 512_000:
        raise ValueError('professional_golden_actual_too_large')
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': path.name, 'byte_count': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def source_hashes():
    paths = sorted((ROOT / 'apps/api/tire_api').rglob('*.py'))
    paths += [ROOT / name for name in [
        'apps/api/tests/professional_golden_support.py',
        'apps/api/tests/test_fitment_relations.py', 'apps/api/tests/admin_support.py',
        'scripts/run_professional_golden.py', 'scripts/verify_professional_golden.py',
    ]]
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}


def install_private_audit(storage):
    """Allow Windows' own socketpair handshake only at its exact fresh listener."""
    counts = {'network_attempts': 0, 'child_process_attempts': 0,
        'normal_database_attempts': 0, 'internal_socketpair_connections': 0}
    pair_state = threading.local()
    original_pair = socket.socketpair

    def guarded_pair(*args, **kwargs):
        if getattr(pair_state, 'current', None) is not None:
            raise RuntimeError('professional_golden_nested_socketpair_forbidden')
        pair_state.current = {'listener': None, 'connected': False}
        try:
            return original_pair(*args, **kwargs)
        finally:
            pair_state.current = None

    def audit(event, arguments):
        pair = getattr(pair_state, 'current', None)
        if event == 'socket.bind':
            address = arguments[1]
            if (pair is not None and pair['listener'] is None and type(address) is tuple
                    and address[0] in {'127.0.0.1', '::1'} and address[1] == 0):
                pair['listener'] = arguments[0]
                return
            counts['network_attempts'] += 1
            raise RuntimeError('professional_golden_network_forbidden')
        if event == 'socket.connect':
            address = arguments[1]
            if pair is not None and pair['listener'] is not None and not pair['connected']:
                expected = pair['listener'].getsockname()
                if address == expected and expected[0] in {'127.0.0.1', '::1'} and expected[1] != 0:
                    pair['connected'] = True
                    counts['internal_socketpair_connections'] += 1
                    return
            counts['network_attempts'] += 1
            raise RuntimeError('professional_golden_network_forbidden')
        if event in {'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr',
                     'socket.getnameinfo', 'socket.sendto', 'socket.sendmsg'}:
            counts['network_attempts'] += 1
            raise RuntimeError('professional_golden_network_forbidden')
        if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn'}:
            counts['child_process_attempts'] += 1
            raise RuntimeError('professional_golden_child_process_forbidden')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            if not Path(str(arguments[0])).resolve().is_relative_to(storage.resolve()):
                counts['normal_database_attempts'] += 1
                raise RuntimeError('professional_golden_private_database_required')
    if sys.platform == 'win32':
        socket.socketpair = guarded_pair
    sys.addaudithook(audit)
    return counts


def source_review(case, execution, corpus):
    """Recheck existing R74 agent-review findings; do not manufacture a product event."""
    from tire_api.professional_golden_corpus import strict_json_loads
    verified = corpus.verify_external(ROOT)
    material = case['materials'][0]
    original = material['original']
    def bound_json(binding):
        path = ROOT / binding['path']
        with path.open('rb') as stream:
            raw = stream.read(512_001)
        if (len(raw) > 512_000 or len(raw) != binding['byte_count']
                or hashlib.sha256(raw).hexdigest() != binding['sha256']):
            raise ValueError('professional_golden_source_review_binding_invalid')
        return strict_json_loads(raw)
    capture = bound_json(material['capture_receipt'])
    review = bound_json(material['agent_review_record'])
    receipt = capture['material_request_view']['receipt']
    if (capture['http_status'] != 201 or receipt['raw_hash'] != original['sha256']
            or receipt['byte_count'] != original['byte_count']
            or review['pdf_sha256'] != original['sha256']
            or len(review['table_1']['rows_as_printed']) != 9
            or 'Size, load/speed indices, GTIN and OE identity were not established' not in review['table_1']['identity_limit']
            or 'whole tire wear rate' not in review['table_3']['not_a_measure_of']
            or 'human-reviewed professional Golden' not in review['method_and_limits']['not_accepted']):
        raise ValueError('professional_golden_r74_review_binding_invalid')
    # These are fixed findings from the independently archived R74 review, not
    # copied from this case's expected/source_review findings list.
    findings = ['exact_sku_not_established', 'tested_size_not_established',
        'study_codes_not_manufacturer_codes', 'particle_classification_not_whole_tire_performance',
        'source_review_only_no_product_event', 'agent_review_not_human_golden']
    return {
        'schema': 'professional-golden-actual@1', 'case_id': case['case_id'],
        'input_sha256': hashlib.sha256(json.dumps(case['input'], sort_keys=True,
            ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
        'execution': {**execution, 'mode': 'source_review_only', 'private_http_observed': False},
        'event_binding': None, 'event_snapshot': None, 'sku_bindings': [], 'material_bindings': [],
        'bridge_results': [], 'candidate_result': None,
        'source_review_result': {'original_verified': len(verified) == 9,
            'capture_receipt_verified': True, 'agent_review_record_verified': True,
            'exact_sku_truth': 'unknown', 'findings': findings},
    }


def run(output):
    output = output.absolute()
    if (not output.resolve().is_relative_to((ROOT / '.artifacts').resolve())
            or not output.name.startswith('r76-') or output.exists()):
        raise ValueError('professional_golden_new_private_output_required')
    output.mkdir(parents=True, exist_ok=False)
    actual_directory = output / 'actuals'
    actual_directory.mkdir()
    storage = output / 's'
    storage.mkdir()
    first_db = storage / 'bootstrap.db'
    for name in list(os.environ):
        if (name.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_OPENAI_'))
                or name == 'DATABASE_URL' or name.lower().endswith('_proxy')):
            del os.environ[name]
    private_url = 'sqlite:///' + first_db.as_posix()
    os.environ.update(TIRE_DATABASE_URL=private_url, DATABASE_URL=private_url,
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
        TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(storage / 'o'),
        TI_PARSER_BUNDLE_ROOT=str(storage / 'b'))
    counts = install_private_audit(storage)
    if sys.platform == 'win32':
        def native_win32_ver(release='', version='', csd='', ptype=''):
            native = sys.getwindowsversion()
            return str(native.major), f'{native.major}.{native.minor}.{native.build}', native.service_pack, ptype
        platform.win32_ver = native_win32_ver
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    from tire_api.professional_golden_corpus import ProfessionalGoldenCorpus
    from tire_api.professional_golden_checks import load_case, evaluate_corpus
    from verify_professional_golden import fingerprint, load_actuals
    corpus = ProfessionalGoldenCorpus()
    before = source_hashes()
    corpus_receipt = corpus.verify_all()
    cases = corpus.read_cases()
    external_receipt = corpus.verify_external(ROOT)
    # Reject an invalid oracle before application import, storage initialization or HTTP.
    for case in cases:
        load_case(case)
    run_id = uuid4().hex
    execution = {'mode': 'private_http', 'run_id': run_id,
        'runner_sha256': sha(Path(__file__)),
        'product_source_fingerprint': hashlib.sha256(json.dumps(before, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest(), 'private_http_observed': True}
    actuals, completed, actual_bindings = [], [], []
    try:
        from fastapi.testclient import TestClient
        from tire_api import main
        from test_fitment_relations import NoNetworkRegistry
        from professional_golden_support import run_private_case
        assert main.app.state.database.engine.url.get_backend_name() == 'sqlite'
        assert Path(main.app.state.database.engine.url.database).resolve() == first_db.resolve()
        for index, case in enumerate(cases):
            if case['input']['mode'] == 'source_review_only':
                actual = source_review(case, execution, corpus)
            else:
                case_root = storage / str(index)
                case_root.mkdir()
                db_path = case_root / 'p.db'
                db_url = 'sqlite:///' + db_path.as_posix()
                os.environ.update(TIRE_DATABASE_URL=db_url, DATABASE_URL=db_url,
                    TI_OBJECT_STORE_ROOT=str(case_root / 'o'), TI_PARSER_BUNDLE_ROOT=str(case_root / 'b'))
                app = main.create_app(db_url, NoNetworkRegistry())
                assert app.state.database.engine.url.get_backend_name() == 'sqlite'
                assert Path(app.state.database.engine.url.database).resolve() == db_path.resolve()
                with TestClient(app, backend_options={'loop_factory': asyncio.SelectorEventLoop}) as client:
                    actual = run_private_case(client, case, execution)
                app.state.database.engine.dispose()
            actual = actual.model_dump(mode='json', by_alias=True) if hasattr(actual, 'model_dump') else actual
            actual_bindings.append(write(actual_directory / (case['case_id'] + '.json'), actual))
            actuals.append(actual)
            completed.append(case['case_id'])
            print(json.dumps({'captured_case_id': case['case_id']}), flush=True)
        after = source_hashes()
        prohibited = [value for key, value in counts.items() if key != 'internal_socketpair_connections']
        if (before != after or corpus.verify_all() != corpus_receipt
                or corpus.verify_external(ROOT) != external_receipt or any(prohibited)):
            raise ValueError('professional_golden_execution_binding_changed')
        disk_actuals, disk_bindings = load_actuals(actual_directory)
        if sorted(actual_bindings, key=lambda row: row['path']) != disk_bindings:
            raise ValueError('professional_golden_actuals_changed')
        report = evaluate_corpus(cases, disk_actuals, corpus_receipt['manifest_sha256'], fingerprint())
        report = report.model_dump(mode='json', by_alias=True) if hasattr(report, 'model_dump') else report
        if (source_hashes() != before or load_actuals(actual_directory)[1] != disk_bindings
                or corpus.verify_all() != corpus_receipt or corpus.verify_external(ROOT) != external_receipt):
            raise ValueError('professional_golden_evaluation_binding_changed')
        write(output / 'report.json', report)
        write(output / 'execution-receipt.json', {
            'schema': 'professional-golden-private-execution@1', 'run_id': run_id,
            'execution_observation': 'in_process_private_asgi_http_at_capture_time',
            'actuals_are_not_self_authenticating': True, 'completed_case_ids': completed,
            'source_before': before, 'source_after': after, 'sources_stable': before == after,
            'corpus_receipt': corpus_receipt, 'guard_counts': counts,
            'external_evidence_bindings': external_receipt,
            'normal_database_used': False, 'provider_calls': 0,
            'human_truth_status': 'pending_external_review',
            'report_sha256': sha(output / 'report.json'),
            'actual_bindings': disk_bindings,
            'private_databases_excluded_from_public_receipt': True,
        })
        print(json.dumps({'engineering_state': report['state'], 'release_gate': report['release_gate']}))
        return 1 if report['state'] == 'failed' else 0
    except BaseException as error:
        write(output / 'failure.json', {'schema': 'professional-golden-private-failure@1',
            'completed_case_ids': completed, 'exception_type': type(error).__name__,
            'locations': [{'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
                          for frame in traceback.extract_tb(error.__traceback__)],
            'guard_counts': counts, 'source_before': before, 'source_after': source_hashes()})
        print(json.dumps({'error_code': 'professional_golden_private_execution_failed',
            'exception_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.artifacts' / ('r76-http-' + uuid4().hex))
    arguments = parser.parse_args()
    raise SystemExit(run(arguments.output))
