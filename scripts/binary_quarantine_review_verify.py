#!/usr/bin/env python3
"""R97 exact private API verification; freeze does not import product or pytest.

Run only after independent review, using apps/api/.venv/Scripts/python.exe
-I -X utf8 -B. This wrapper never changes the existing regression manifest,
Guard, ChildPolicy pins, source permission policy, or normal database.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading

RESOLVE = Path.resolve
ROOT = RESOLVE(Path(__file__)).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

# These three modules are stdlib-only until bootstrap and the Guard are active.
import run_api_worker_regression as common
from regression_children import ChildPolicy
from regression_guard import RegressionGuard

SUITES = {
    'boundary': (
        'apps/api/tests/test_vehicle_binary_review_boundary.py',
    ),
    'compat': (
        'apps/api/tests/test_vehicle_binary_approval.py',
        'apps/api/tests/test_vehicle_binary_reparse.py',
        'apps/api/tests/test_vehicle_raw_v2.py',
        'apps/api/tests/test_quarantine_review.py',
        'apps/api/tests/test_auth_accounts.py::test_register_while_authenticated_preserves_identity',
        'apps/api/tests/test_auth_accounts.py::test_logout_then_login_other_user_on_same_session',
        'apps/api/tests/test_auth_accounts.py::test_admin_guard_blocks_management_writes',
        'apps/api/tests/test_auth_lifecycle.py::test_admin_guard_dependency_runs_before_body_validation',
        'apps/api/tests/test_auth_lifecycle.py::test_delete_user_unbinds_sessions_and_guards_last_admin',
        'apps/api/tests/test_auth_lifecycle.py::test_deleted_users_data_joins_next_login_on_same_session',
        'apps/api/tests/test_auth_lifecycle.py::test_login_sweep_unbinds_expired_sessions',
        'apps/api/tests/test_auth_lifecycle.py::test_active_sessions_slide_instead_of_expiring',
    ),
    'diagnostic': (
        'apps/api/tests/test_vehicle_binary_review_boundary.py::test_postcommit_response_permission_failure_preserves_committed_review_and_real_actor',
    ),
}
CHILD_BUDGETS = {'boundary': 64, 'compat': 256, 'diagnostic': 4}
# Fixed-suite/142-file observation plus static path review and one pytest digit
# of margin; source/fixture changes require review. Not production path support.
WINDOWS_REVIEWED_SUFFIX_CHARS = 188
S2 = (ROOT / '.artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f'
      / 'xiaomi-first-generation-2.pdf')
S2_SIZE = 3240150
S2_SHA256 = '0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f'
R38 = ROOT / '.artifacts/runtime/round38-before.sqlite'
R38_SIZE = 25374720
R38_SHA256 = 'a731a017d043aa1390ad5d138dfcfdaeafc419aec85cb8ce823674468f341fd4'
R96 = ROOT / '.artifacts/r96-close-41569a232f344c18a42148958f15125e/verification-final.json'
R96_SIZE = 23489
R96_SHA256 = '4781953e4dbdb516f3f2bdb00b48c156406df86d399b64feac6d52d86572dbfe'
CONTEXT = {'out': None, 'guard': None}


class StageObserver:
    """Observe original exceptions in exact reviewed parent frames, never args."""
    POINTS = {
        ('apps/api/tests/test_vehicle_pdf_runtime.py', 'reviewed_pdf.<locals>.load'): 's2_preuse_load',
        ('apps/api/tests/test_vehicle_binary_ingestion.py', 'PrivatePDFReplay.fetch'): 'private_adapter_fetch',
        ('apps/api/tests/test_vehicle_binary_ingestion.py', 'private.<locals>.guarded_recorder.<locals>.callback'): 'private_capture_callback',
        ('apps/api/tire_api/parser_provenance.py', 'verified_observation_recorder.<locals>.record'): 'verified_observation_record',
        ('apps/api/tire_api/captures.py', 'before_parse_recorder.<locals>.record'): 'capture_journal_record',
        ('apps/api/tire_api/captures.py', '_binary_journal_bind'): 'binary_journal_admission',
        ('apps/api/tire_api/captures.py', '_binary_original_run'): 'binary_journal_original',
        ('apps/api/tire_api/documents.py', 'record_object'): 'record_object',
        ('apps/api/tire_api/object_store.py', 'FileObjectStore.path'): 'object_path',
        ('apps/api/tire_api/object_store.py', 'FileObjectStore.put'): 'object_put',
        ('apps/api/tire_api/object_store.py', 'FileObjectStore.get'): 'object_get',
        ('apps/api/tire_api/object_store.py', 'comparable_path'): 'object_path_comparison',
        ('apps/api/tire_api/object_store.py', 'checked'): 'object_bytes_integrity',
    }
    CODES = frozenset({'object_write_failed', 'object_unavailable', 'object_integrity_failed',
        'object_path_not_allowed', 'evidence_capture_failed', 'vehicle_raw_integrity_failed',
        'parser_failed', 'parser_timeout', 'parser_bundle_missing', 'parser_identity_mismatch'})

    def __init__(self, private):
        self.private = private
        self.points = {(str(ROOT / path).replace('\\', '/').casefold(), qualname): label
                       for (path, qualname), label in self.POINTS.items()}
        self.rows, self.cache, self.threads = [], {}, set()
        self.lock = threading.RLock()
        self.discarded = self.errors = 0
        self.active = False
        self.old_sys = self.old_threads = None

    def trace(self, frame, event, argument):
        if not self.active:
            return None
        try:
            code = frame.f_code
            if code not in self.cache:
                self.cache[code] = self.points.get((code.co_filename.replace('\\', '/').casefold(), code.co_qualname))
            stage = self.cache[code]
            if stage is None:
                return None
            if event in {'call', 'return', 'exception'}:
                row = {'stage': stage, 'event': 'return_or_suspend' if event == 'return' else event,
                       'source_line': frame.f_lineno}
                if event == 'exception':
                    error = argument[1]
                    row['exception_type'] = type(error).__name__
                    row['errno'] = error.errno if isinstance(error, OSError) and type(error.errno) is int else None
                    value = getattr(error, 'winerror', None) if isinstance(error, OSError) else None
                    row['winerror'] = value if type(value) is int else None
                    value = vars(error).get('code') if hasattr(error, '__dict__') else None
                    row['fixed_error_code'] = value if type(value) is str and value in self.CODES else None
                    paths = []
                    for name in ('target', 'temporary', 'path', 'package_root', 'directory'):
                        value = frame.f_locals.get(name)
                        if isinstance(value, Path):
                            length = len(str(value))
                            paths.append({'local_slot': name, 'characters': length,
                                'length_category': 'at_least_260' if length >= 260 else 'below_260',
                                'scope': 'private' if RESOLVE(value).is_relative_to(self.private) else 'outside_private'})
                    row['path_categories'] = paths
                with self.lock:
                    self.threads.add(threading.get_ident())
                    if len(self.rows) < 128:
                        self.rows.append(row)
                    else:
                        self.discarded += 1
            return self.trace
        except Exception:
            # Observer defects are counted, never substituted for product results.
            with self.lock:
                self.errors += 1
            return self.trace

    def install(self):
        self.old_sys, self.old_threads = sys.gettrace(), threading.gettrace()
        if self.old_sys is not None or self.old_threads is not None:
            raise RuntimeError('diagnostic_trace_already_installed')
        self.active = True
        threading.settrace(self.trace)
        sys.settrace(self.trace)

    def uninstall(self):
        self.active = False
        sys.settrace(self.old_sys)
        threading.settrace(self.old_threads)

    def snapshot(self):
        return {'schema': 'r97-exact-parent-stage-observation@1', 'diagnostic_only': True,
                'observation_limit': 128, 'rows': self.rows, 'discarded_events': self.discarded,
                'observer_error_count': self.errors, 'observed_thread_count': len(self.threads),
                'trace_uninstalled_before_receipt': not self.active,
                'original_calls_results_and_exceptions_not_replaced': True,
                'raw_messages_arguments_bodies_cookies_environment_values_recorded': False}


def static_import_boundary():
    if any(name == 'tire_api' or name.startswith('tire_api.')
           or name in {'pytest', '_pytest'} or name.startswith('_pytest.')
           for name in sys.modules):
        raise RuntimeError('product_or_pytest_imported_before_guard')


def verify_bootstrap(out):
    private = out / 'private'
    database = 'sqlite:///' + (private / 'bootstrap.db').as_posix()
    exact = {'TIRE_DATABASE_URL': database, 'DATABASE_URL': database,
             'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0', 'TI_OBSERVABILITY_ENABLED': '0',
             'TI_OBJECT_STORE_BACKEND': 'filesystem', 'TI_OBJECT_STORE_ROOT': str(private / 'objects'),
             'TI_PARSER_BUNDLE_ROOT': str(private / 'bundles'),
             'TEMP': str(private / 'tmp'), 'TMP': str(private / 'tmp'), 'TMPDIR': str(private / 'tmp'),
             'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    if any(os.environ.get(name) != value for name, value in exact.items()) or Path.cwd() != private:
        raise ValueError('private_bootstrap_configuration_not_exact')
    static_import_boundary()
    return {'exact_private_database_object_bundle_tmp_environment': True,
            'guard_install_precedes_product_and_pytest_import': True}


def runtime_record(path):
    path = RESOLVE(Path(path), strict=True)
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def source_inputs():
    def protected(path, size, sha256):
        record = common.record(path)
        if record['bytes'] != size or record['sha256'] != sha256:
            raise ValueError('protected_historical_input_changed')
        return record
    return {'schema': 'r97-review-source-seal@1', 'sources': common.bindings(),
            'suites': {key: list(value) for key, value in SUITES.items()},
            'child_budgets': CHILD_BUDGETS,
            'historical_s2': protected(S2, S2_SIZE, S2_SHA256),
            'r38': protected(R38, R38_SIZE, R38_SHA256),
            'r96_seal': protected(R96, R96_SIZE, R96_SHA256),
            'python': runtime_record(sys.executable),
            'base_python': runtime_record(getattr(sys, '_base_executable', sys.executable))}


def new_output(value):
    out = RESOLVE(value)
    if (out.parent != RESOLVE(ROOT / '.artifacts') or out.exists()
            or not re.fullmatch(r'r97v-[a-f0-9]{16}', out.name)):
        raise ValueError('new_r97_short_output_required')
    if os.name == 'nt' and len(str(out)) + WINDOWS_REVIEWED_SUFFIX_CHARS > 259:
        raise ValueError('r97_private_path_budget_exceeded')
    out.mkdir(exist_ok=False)
    CONTEXT['out'] = common.RUN_CONTEXT['output'] = out
    return out


class ParserOnlyPolicy(ChildPolicy):
    """Use every original authorization check, then narrow category and budget."""
    def __init__(self, private, out, suite):
        super().__init__(ROOT, private, out)
        self.budget = CHILD_BUDGETS[suite]
        self.reserved = 0
        self.max_live_observed = 0

    def _prepare(self, options):
        prepared = super()._prepare(options)
        category = prepared[0]
        if category != 'managed_parser':
            self._deny('r97_only_managed_parser')
        with self._lock:
            if self.phase != 'run':
                self._deny('r97_child_outside_run')
            live = sum(process.poll() is None for process in self._processes)
            self.max_live_observed = max(self.max_live_observed, live)
            if live >= 2 or self.reserved >= self.budget:
                self._deny('r97_parser_budget')
            self.reserved += 1
        return prepared

    def snapshot(self):
        snapshot = super().snapshot()
        return {**snapshot, 'allowed_categories': ['managed_parser'],
                'launch_budget': self.budget, 'reserved_launches': self.reserved,
                'max_live_before_launch_observed': self.max_live_observed,
                'parser_wall_seconds': 8.0, 'parser_max_concurrent': 2}

    def cleanup_owned_processes(self):
        with self._lock:
            processes = tuple(self._processes)
        rows = []
        for index, process in enumerate(processes, 1):
            initial = process.poll()
            row = {'process_index': index, 'producer_exit_code': initial,
                   'producer_live_before_cleanup': initial is None,
                   'cleanup_actions': [], 'cleanup_failure_types': []}
            if initial is None:
                for action in ('terminate', 'kill'):
                    if process.poll() is not None:
                        break
                    row['cleanup_actions'].append(action)
                    try:
                        getattr(process, action)()
                        process.wait(timeout=3)
                    except BaseException as error:
                        row['cleanup_failure_types'].append(type(error).__name__)
            row['final_exit_code'] = process.poll()
            row['final_live'] = row['final_exit_code'] is None
            rows.append(row)
        return {'owned_process_count': len(rows),
                'producer_live_before_cleanup': sum(row['producer_live_before_cleanup'] for row in rows),
                'live_after_cleanup': sum(row['final_live'] for row in rows),
                'processes': rows}


class ObservedGuard(RegressionGuard):
    """Retain original denials and observe SQLite handles without replacement."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sqlite_handles = []

    def audit(self, event, args):
        if event in {'sqlite3.enable_load_extension', 'sqlite3.load_extension'}:
            self._deny('r97_sqlite_extension_loading')
        super().audit(event, args)
        if event == 'sqlite3.connect/handle':
            self.sqlite_handles.append((self.phase, args[0]))

    def close_sqlite(self, *, only_selfcheck=False):
        selected = [connection for phase, connection in self.sqlite_handles
                    if (phase == 'selfcheck') == only_selfcheck]
        producer_closed = explicit_closed = errors = 0
        for connection in selected:
            try:
                cursor = connection.execute('SELECT 1')
                cursor.close()
            except sqlite3.ProgrammingError as error:
                if error.args == ('Cannot operate on a closed database.',):
                    producer_closed += 1
                    continue
                # Cross-thread or other programming errors are not closure proof.
                errors += 1
            except Exception:
                # Do not label an unqueryable connection as already closed.
                errors += 1
            try:
                connection.close()
                try:
                    connection.execute('SELECT 1')
                except sqlite3.ProgrammingError as error:
                    if error.args == ('Cannot operate on a closed database.',):
                        explicit_closed += 1
                    else:
                        errors += 1
                else:
                    errors += 1
            except Exception:
                errors += 1
        return {'observed_handles': len(selected), 'already_closed': producer_closed,
                'explicit_final_cleanup_closed': explicit_closed, 'errors': errors,
                'all_closed_before_final_cleanup': producer_closed == len(selected),
                'all_closed_after_final_cleanup': errors == 0
                    and producer_closed + explicit_closed == len(selected)}


def dispose_engines():
    """Close retained SQLAlchemy pools after all pytest fixture teardown reports."""
    module = sys.modules.get('sqlalchemy.engine.base')
    engine_type = getattr(module, 'Engine', None)
    rows = []
    if engine_type is None:
        return rows
    for value in gc.get_objects():
        if type(value) is not engine_type:
            continue
        checkedout = getattr(value.pool, 'checkedout', None)
        row = {'checkedout_before_dispose': checkedout() if checkedout else None,
               'disposed': False, 'failure_type': None}
        try:
            value.dispose()
            row['disposed'] = True
        except BaseException as error:
            row['failure_type'] = type(error).__name__
        rows.append(row)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=('freeze', 'run'))
    parser.add_argument('--suite', choices=tuple(SUITES))
    parser.add_argument('--source-seal', type=Path)
    parser.add_argument('--source-seal-sha256')
    parser.add_argument('--output-root', required=True, type=Path)
    options = parser.parse_args(argv)
    static_import_boundary()
    if (RESOLVE(Path(sys.executable), strict=True)
            != RESOLVE(ROOT / 'apps/api/.venv/Scripts/python.exe', strict=True)
            or not sys.flags.isolated or not sys.dont_write_bytecode or not sys.flags.utf8_mode):
        raise ValueError('isolated_api_venv_utf8_no_bytecode_required')
    if options.phase == 'freeze':
        if options.suite or options.source_seal or options.source_seal_sha256:
            raise ValueError('freeze_accepts_no_execution_selection')
        inputs = source_inputs()
        out = new_output(options.output_root)
        common.write_json(out / 'reviewed-sources.json', inputs)
        print(json.dumps({'phase': 'freeze', 'product_or_pytest_imported': False,
                          'source_seal': common.record(out / 'reviewed-sources.json')}))
        return 0
    if (options.suite is None or options.source_seal is None
            or not re.fullmatch(r'[a-f0-9]{64}', options.source_seal_sha256 or '')):
        raise ValueError('exact_suite_and_reviewed_source_seal_required')
    seal = RESOLVE(options.source_seal, strict=True)
    if (seal.name != 'reviewed-sources.json' or seal.parent.parent != RESOLVE(ROOT / '.artifacts')
            or not re.fullmatch(r'r97v-[a-f0-9]{16}', seal.parent.name)):
        raise ValueError('source_seal_outside_reviewed_r97_output')
    raw_seal = seal.read_bytes()
    if hashlib.sha256(raw_seal).hexdigest() != options.source_seal_sha256:
        raise ValueError('reviewed_source_seal_digest_mismatch')
    before = source_inputs()
    if json.loads(raw_seal) != before:
        raise ValueError('reviewed_sources_changed_before_run')
    targets = [str(ROOT / value.split('::', 1)[0])
               + ('::' + value.split('::', 1)[1] if '::' in value else '')
               for value in SUITES[options.suite]]
    for target in targets:
        if not Path(target.split('::', 1)[0]).is_file():
            raise ValueError('literal_target_missing')
    out = new_output(options.output_root)
    config = common.bootstrap(out, None)
    config['r97_verified_boundary'] = verify_bootstrap(out)
    children = ParserOnlyPolicy(out / 'private', out, options.suite)
    guard = ObservedGuard(ROOT, out / 'private', out, child_policy=children)
    CONTEXT['guard'] = common.RUN_CONTEXT['guard'] = guard
    guard.install()
    children.install()
    common.write_json(out / 'source-before.json', before)
    common.write_json(out / 'bootstrap.json', config)
    common.write_json(out / 'invocation.json', {'argv': [str(sys.executable), '-I', '-X', 'utf8', '-B',
        str(ROOT / 'scripts/binary_quarantine_review_verify.py'), *(sys.argv[1:] if argv is None else argv)],
        'literal_targets': list(SUITES[options.suite]), 'source_seal': common.record(seal),
        'child_budget': children.budget, 'unknown_children_allowed': False})
    checks = execution = failure = selfcheck_closure = observer = observation = None
    try:
        checks = common.selfcheck(guard, children, out)
        selfcheck_closure = guard.close_sqlite(only_selfcheck=True)
        guard.phase = children.phase = 'receipt'
        common.write_json(out / 'selfcheck.json', checks)
        guard.phase = children.phase = 'run'
        try:
            if options.suite == 'diagnostic':
                observer = StageObserver(out / 'private')
                observer.install()
            execution = common.pytest_run('run', targets, out, out / 'private', guard, children)
        finally:
            if observer is not None:
                observer.uninstall()
                observation = observer.snapshot()
                common.write_json(out / 'stage-observations.json', observation)
    except BaseException as error:
        failure = common.safe_exception(error)
    guard.phase = children.phase = 'teardown'
    child_cleanup = children.cleanup_owned_processes()
    engines = dispose_engines()
    closure = guard.close_sqlite()
    backup = guard.verify_backup()
    after = source_inputs()
    guard.phase = children.phase = 'receipt'
    common.write_json(out / 'source-after.json', after)
    snapshot, child_snapshot = guard.snapshot(), children.snapshot()
    denied = sum(guard.denied_count(phase) + children.denied_count(phase)
                 for phase in ('bootstrap', 'collection', 'run', 'teardown', 'receipt'))
    resources_closed = (child_snapshot['live_process_count'] == 0
        and snapshot['metrics']['active_listeners'] == snapshot['metrics']['retained_closed_endpoints'] == 0
        and closure['all_closed_after_final_cleanup']
        and all(row['disposed'] and row['checkedout_before_dispose'] in (None, 0) for row in engines)
        and bool(selfcheck_closure and selfcheck_closure['all_closed_after_final_cleanup']))
    completed = bool(execution and execution['pytest_exit_code'] == 0
        and execution['failure_type'] is None and execution['reporting_failure_count'] == 0
        and execution['collected_items'] > 0 and execution['unique_nodeids']
        and execution['collected_items'] == execution['test_protocols_started'] == execution['tests_executed']
        and execution['outcomes']['failed'] == execution['outcomes']['skipped'] == execution['outcomes']['incomplete'] == 0
        and all(execution['phase_outcomes'][phase]['passed'] == execution['collected_items']
                for phase in ('setup', 'call', 'teardown')))
    passed = bool(completed and checks and checks['all_passed'] and failure is None
        and before == after and denied == 0 and resources_closed and backup['unchanged']
        and child_cleanup['producer_live_before_cleanup'] == 0
        and (observation is None or observation['observer_error_count'] == observation['discarded_events'] == 0)
        and child_snapshot['exit_counts'].get('0', 0) == child_snapshot['process_count'])
    result = {'schema': 'r97-binary-quarantine-review-verify@1', 'suite': options.suite,
        'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': passed,
        'runner_exit_code': 0 if passed else 3, 'failure': failure,
        'literal_targets': list(SUITES[options.suite]), 'source_seal': common.record(seal),
        'source_input_count': len(before['sources']), 'sources_stable': before == after,
        'execution': execution, 'selfcheck': checks, 'guard': snapshot, 'children': child_snapshot,
        'owned_child_cleanup': child_cleanup,
        'diagnostic_only': options.suite == 'diagnostic', 'parent_stage_observation': observation,
        'selfcheck_sqlite_closure': selfcheck_closure, 'sqlalchemy_engine_cleanup': engines,
        'sqlite_closure': closure, 'resources_closed': resources_closed,
        'raw_nonselfcheck_denials': denied, 'backup_verification': backup,
        'normal_database_started': False, 'real_external_network_or_provider_calls': 0,
        'limits': ['Reviewed Python audit boundary; not an OS or native syscall sandbox.',
                   'Private SQLite/S2/parser/API tests do not establish PG, UI, Native device, online source, production rights or complete V1 acceptance.',
                   'Explicit final SQLite cleanup is reported separately from closure by fixtures/pool disposal.',
                   'The freeze phase is a source seal only, never a product test result.']}
    common.write_json(out / 'result.json', result)
    print(json.dumps({'passed': passed, 'suite': options.suite, 'runner_exit_code': result['runner_exit_code'],
                      'result': common.record(out / 'result.json')}))
    return result['runner_exit_code']


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as error:
        # Keep raw exception values and captured product output out of receipts.
        out = CONTEXT['out']
        if out is not None:
            common.write_json(out / 'driver-exception.json', {'failure': common.safe_exception(error),
                'passed': False, 'resources_closed': None})
        print(json.dumps({'passed': False, 'failure_type': type(error).__name__,
                          'details_omitted': True}))
        raise SystemExit(3)
