"""Private capture/replay boundary for the frozen current-023 synthetic baseline.

This tool never implements migration024 or registers another pytest module.
Freeze and capture/replay each run in a fresh short .artifacts/r84-* root.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.abc
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

# -I deliberately removes the script directory. Restore only this pinned,
# absolute sibling location; never use the caller's cwd or PYTHONPATH.
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIRECTORY))
import run_api_worker_regression as common
from regression_guard import GuardDenied, RegressionGuard

ROOT = SCRIPT_DIRECTORY.parent
RESOLVE = Path.resolve
BUILDER = 'scripts/build_vehicle_binary_023_fixture.py'
DRIVER = 'scripts/run_vehicle_binary_023_gate.py'
DEPENDENCIES = ('apps/api/pyproject.toml', 'apps/api/uv.lock')
HARNESS = (
    'scripts/run_api_worker_regression.py', 'scripts/regression_guard.py',
    'scripts/regression_children.py', 'scripts/regression_child.py',
    'scripts/regression_node_guard.cjs',
)
RESOURCES = {
    'assets/fonts/TireEvidenceSC-Regular.ttf', 'assets/fonts/README.md',
    'assets/fonts/provenance.json', 'assets/fonts/OFL.txt',
}
FIXTURE_FILES = ('schema_023.sql', 'seed_023.sql', 'expected_023.json', 'source-index.json', 'README.md')
EXTRA_DENIALS = {'sqlite_extension_loading', 'sqlite_unreviewed_virtual_table',
                 'product_import_not_sealed', 'forbidden_replay_import'}
DRIVER_CONTEXT = {'output': None, 'guard': None}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def fingerprint(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            'source_changed_during_hash')
    return {'bytes': after.st_size, 'sha256': digest.hexdigest()}


def record(path):
    return {'path': RESOLVE(path).relative_to(ROOT).as_posix(), **fingerprint(path)}


def source_paths():
    package = ROOT / 'apps/api/tire_api'
    package_files = [path for path in package.rglob('*') if path.is_file()
                     and '__pycache__' not in path.parts and path.suffix not in {'.pyc', '.pyo'}]
    python = [path for path in package_files if path.suffix == '.py']
    other = {path.relative_to(package).as_posix() for path in package_files if path.suffix != '.py'}
    require(len(python) == 140 and other == RESOURCES, 'current_023_package_catalog_changed')
    paths = package_files + [ROOT / path for path in (*DEPENDENCIES, BUILDER, DRIVER, *HARNESS)]
    require(all(path.is_file() for path in paths), 'declared_closure_file_missing')
    return sorted(paths)


def live_bindings():
    return [record(path) for path in source_paths()]


def environment_identity():
    return {'python_version': sys.version, 'python_implementation': sys.implementation.name,
            'python_cache_tag': sys.implementation.cache_tag,
            'sqlite_version': sqlite3.sqlite_version,
            'sqlalchemy_version': importlib.metadata.version('SQLAlchemy'),
            'interpreter': record(Path(sys.executable)) if RESOLVE(Path(sys.executable)).is_relative_to(ROOT)
                           else {'basename': Path(sys.executable).name, **fingerprint(Path(sys.executable))}}


class GateGuard(RegressionGuard):
    """Only narrow the existing boundary: exact SQLite file, no child/extensions."""
    def __init__(self, output, mode):
        super().__init__(ROOT, output / 'private', output, child_policy=None)
        self.mode = mode
        self.connections = []
        self.allowed_database = RESOLVE(output / 'private' / (mode + '.sqlite'))

    def sqlite_kind(self, target):
        try:
            value = os.fsdecode(target)
        except (TypeError, ValueError):
            return None
        if value == ':memory:':
            return 'memory' if self.phase == 'selfcheck' else None
        if self.mode not in {'capture', 'replay'} or value.startswith('file:'):
            return None
        try:
            return 'private' if RESOLVE(Path(value)) == self.allowed_database else None
        except (OSError, ValueError):
            return None

    def _authorizer(self, kind, action, first, second, database, trigger):
        inherited = super()._authorizer(kind, action, first, second, database, trigger)
        if inherited != sqlite3.SQLITE_OK:
            return inherited
        if action == sqlite3.SQLITE_CREATE_VTABLE and (kind != 'private' or first != 'knowledge_fts'
                                                      or second != 'fts5'):
            self._bump('denied.sqlite_unreviewed_virtual_table')
            self._denials.append({'phase': self.phase, 'category': 'sqlite_unreviewed_virtual_table',
                                  'classification': 'unclassified', 'frames': self._frames()})
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def audit(self, event, args):
        if event in {'sqlite3.enable_load_extension', 'sqlite3.load_extension'}:
            self._deny('sqlite_extension_loading')
        super().audit(event, args)
        if event == 'sqlite3.connect/handle':
            self.connections.append((self.phase, args[0]))

    def database_closure(self):
        opened = [connection for phase, connection in self.connections if phase != 'selfcheck']
        closed = forced = 0
        for connection in opened:
            try:
                cursor = connection.execute('SELECT 1')
                cursor.close()
            except sqlite3.ProgrammingError:
                closed += 1
            except Exception:
                connection.close()
                forced += 1
            else:
                connection.close()
                forced += 1
        return {'observed_connections': len(opened), 'closed_by_producer': closed,
                'forced_close_count': forced,
                'all_closed_by_producer': closed == len(opened) and forced == 0,
                'required_database_observed': self.mode == 'freeze' or len(opened) > 0}


class ProductBoundary(importlib.abc.MetaPathFinder):
    def __init__(self, guard, frozen_root, files, replay):
        self.guard, self.frozen_root, self.files, self.replay = guard, frozen_root, files, replay
        self.package_root = frozen_root / 'apps/api/tire_api'

    def find_spec(self, fullname, path=None, target=None):
        product = fullname == 'tire_api' or fullname.startswith('tire_api.')
        if self.replay and (product or fullname == 'sqlalchemy' or fullname.startswith('sqlalchemy.')):
            self.guard._deny('forbidden_replay_import')
        if not product:
            return None
        if fullname == 'tire_api.main' or fullname.startswith('tire_api.main.'):
            self.guard._deny('product_import_not_sealed')
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or not spec.origin:
            self.guard._deny('product_import_not_sealed')
        origin = RESOLVE(Path(spec.origin))
        if not origin.is_relative_to(self.package_root):
            self.guard._deny('product_import_not_sealed')
        relative = origin.relative_to(self.frozen_root).as_posix()
        if relative not in self.files or fingerprint(origin) != self.files[relative]:
            self.guard._deny('product_import_not_sealed')
        return spec


def selfcheck(guard):
    guard.phase = 'selfcheck'
    checks = []
    def denied(name, action, accepted=(PermissionError,)):
        previous = guard.denied_count('selfcheck')
        try:
            action()
        except accepted:
            passed = guard.denied_count('selfcheck') > previous
        else:
            passed = False
        checks.append({'name': name, 'passed': passed})
        require(passed, 'boundary_selfcheck_failed')
    denied('DNS', lambda: socket.getaddrinfo('r84-denied.invalid', 443))
    with socket.socket() as connection:
        denied('external connection', lambda: connection.connect(('198.51.100.1', 443)))
    denied('all child launches', lambda: subprocess.Popen([sys.executable, '-c', 'raise SystemExit(99)']))
    forbidden = ROOT / '.artifacts' / 'r84-forbidden.sqlite'
    denied('nonprivate SQLite', lambda: sqlite3.connect(forbidden))
    denied('normal file write', lambda: (ROOT / '.artifacts/r84-forbidden.txt').write_bytes(b'x'))
    memory = sqlite3.connect(':memory:')
    try:
        denied('ATTACH', lambda: memory.execute('ATTACH DATABASE ? AS forbidden', (str(forbidden),)),
               (sqlite3.DatabaseError,))
        denied('extension enable', lambda: memory.enable_load_extension(True))
        denied('unreviewed virtual table', lambda: memory.execute('CREATE VIRTUAL TABLE forbidden USING fts5(body)'),
               (sqlite3.DatabaseError,))
    finally:
        memory.close()
    return {'all_passed': all(check['passed'] for check in checks), 'checks': checks,
            'intentional_denial_actions': len(checks)}


def artifact_input(path):
    resolved = RESOLVE(path if path.is_absolute() else ROOT / path, strict=True)
    require(resolved.is_relative_to(ROOT / '.artifacts'), 'explicit_artifact_input_required')
    return resolved


def freeze_source(output, identity_file):
    identity_file = artifact_input(identity_file)
    identity = read_json(identity_file)
    require(identity.get('schema') == 'vehicle-binary-023-dirty-identity@1'
            and re.fullmatch(r'[0-9a-f]{40}', identity.get('head', '')),
            'reviewed_dirty_identity_required')
    before = live_bindings()
    require(identity['files'] == {entry['path']: {'bytes': entry['bytes'], 'sha256': entry['sha256']}
                                  for entry in before}, 'dirty_identity_source_mismatch')
    frozen = output / 'frozen_source'
    for entry in before:
        destination = frozen / entry['path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as handle:
            handle.write((ROOT / entry['path']).read_bytes())
        require(fingerprint(destination) == {'bytes': entry['bytes'], 'sha256': entry['sha256']},
                'frozen_copy_mismatch')
    manifest = {'schema': 'vehicle-binary-023-frozen-source@1', 'production_python_files': 140,
                'nonpython_resources': sorted(RESOURCES),
                'files': {entry['path']: {'bytes': entry['bytes'], 'sha256': entry['sha256']} for entry in before},
                'environment': environment_identity(), 'dirty_identity': identity,
                'dirty_identity_receipt': record(identity_file),
                'baseline_qualification': 'Frozen current023 code, synthetic historical rows; not a normal-database backup or retained historical production database'}
    write_json(output / 'source-index.json', manifest)
    return {'success': True, 'source_index': record(output / 'source-index.json'),
            'frozen_tree': frozen.relative_to(ROOT).as_posix()}


def verify_frozen_tree(frozen, manifest):
    require(set(manifest['files']) == {path.relative_to(ROOT).as_posix() for path in source_paths()},
            'frozen_manifest_closed_file_set_changed')
    actual = set()
    for path in frozen.rglob('*'):
        require('__pycache__' not in path.parts and path.suffix.lower() not in {'.pyc', '.pyo'},
                'frozen_cache_or_bytecode_present')
        if path.is_file():
            candidate = RESOLVE(path, strict=True)
            require(candidate.is_relative_to(frozen), 'frozen_file_boundary_failed')
            relative = path.relative_to(frozen).as_posix()
            actual.add(relative)
            require(relative in manifest['files'] and fingerprint(candidate) == manifest['files'][relative],
                    'frozen_file_unbound_or_changed')
    require(actual == set(manifest['files']), 'frozen_tree_has_extra_or_missing_files')
    return len(actual)


def activate_frozen(guard, source_run, replay):
    source_run = artifact_input(source_run)
    manifest_path = source_run / 'source-index.json'
    manifest = read_json(manifest_path)
    freeze_result_path = source_run / 'result.json'
    freeze_result = read_json(freeze_result_path)
    require(freeze_result.get('schema') == 'vehicle-binary-023-managed-gate@1'
            and freeze_result['phase'] == 'freeze' and freeze_result['passed'] is True
            and freeze_result['sources_stable'] and freeze_result['resources_closed']
            and freeze_result['raw_nonselfcheck_denials'] == 0
            and freeze_result['frozen_source_index'] == record(manifest_path),
            'passed_freeze_result_and_index_binding_required')
    require(manifest.get('schema') == 'vehicle-binary-023-frozen-source@1'
            and manifest['production_python_files'] == 140, 'frozen_source_manifest_required')
    require(manifest['environment'] == environment_identity(), 'interpreter_or_dependency_version_changed')
    frozen = source_run / 'frozen_source'
    frozen_file_count = verify_frozen_tree(frozen, manifest)
    for relative, expected in manifest['files'].items():
        candidate = RESOLVE(frozen / relative, strict=True)
        require(candidate.is_relative_to(frozen) and fingerprint(candidate) == expected,
                'frozen_source_file_changed')
        require(fingerprint(ROOT / relative) == expected, 'live_source_drift_from_frozen')
    require(not any(name == 'tire_api' or name.startswith('tire_api.') for name in sys.modules),
            'product_imported_before_frozen_activation')
    if replay:
        require(not any(name == 'sqlalchemy' or name.startswith('sqlalchemy.') for name in sys.modules),
                'sqlalchemy_imported_before_replay')
    live_roots = {RESOLVE(ROOT / directory) for directory in ('apps/api', 'apps/api/tests', 'apps/worker', 'scripts')}
    sys.path[:] = [entry for entry in sys.path if entry and RESOLVE(Path(entry)) not in live_roots]
    sys.path[:0] = [str(frozen / 'apps/api'), str(frozen / 'scripts')]
    sys.meta_path.insert(0, ProductBoundary(guard, frozen, manifest['files'], replay))
    spec = importlib.util.spec_from_file_location('r84_frozen_fixture_builder', frozen / BUILDER)
    require(spec is not None and spec.loader is not None, 'frozen_builder_loader_missing')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    binding = {'freeze_result': record(freeze_result_path), 'source_index': record(manifest_path),
               'exact_frozen_file_count': frozen_file_count, 'frozen_tree_exact_and_without_bytecode': True}
    return frozen, manifest, module, binding


def check_product_origins(frozen, manifest, replay):
    observed = []
    for name, module in sys.modules.copy().items():
        if name == 'tire_api' or name.startswith('tire_api.'):
            require(not replay and name != 'tire_api.main', 'forbidden_product_import_observed')
            location = getattr(module, '__file__', None)
            require(location and RESOLVE(Path(location)).is_relative_to(frozen / 'apps/api/tire_api'),
                    'product_import_origin_outside_sealed_tree')
            relative = RESOLVE(Path(location)).relative_to(frozen).as_posix()
            require(relative in manifest['files'] and fingerprint(Path(location)) == manifest['files'][relative],
                    'executed_product_origin_not_bound')
            observed.append(name)
        if replay and (name == 'sqlalchemy' or name.startswith('sqlalchemy.')):
            raise ValueError('forbidden_sqlalchemy_replay_import_observed')
    return {'all_product_imports_from_sealed_tree': True, 'product_module_count': len(observed),
            'main_imported': False, 'replay_product_or_sqlalchemy_imported': False}


def reviewed_fixture(path, review_file, source_manifest):
    path = RESOLVE(path if path.is_absolute() else ROOT / path, strict=True)
    require(path.is_relative_to(ROOT / '.artifacts')
            or path == RESOLVE(ROOT / 'apps/api/tests/fixtures/vehicle_binary_023'),
            'explicit_fixture_root_required')
    review_file = artifact_input(review_file)
    review = read_json(review_file)
    require(review.get('schema') == 'vehicle-binary-023-independent-static-review@1'
            and review.get('passed') is True and set(review.get('files', {})) == set(FIXTURE_FILES),
            'independent_static_review_required')
    require({child.name for child in path.iterdir()} == set(FIXTURE_FILES)
            and all(child.is_file() and not child.is_symlink() for child in path.iterdir()),
            'reviewed_fixture_extra_or_nonplain_files')
    for name, expected in review['files'].items():
        require(fingerprint(path / name) == expected, 'reviewed_fixture_changed')
    require(read_json(path / 'source-index.json')['frozen_source_manifest'] == source_manifest,
            'reviewed_fixture_frozen_source_binding_changed')
    return path, record(review_file)


def check_assets(expected_path, private):
    expected = read_json(expected_path)['private_assets']
    require(any(name.startswith('objects/sha256/') for name in expected)
            and any(name.startswith('bundles/sha256/') for name in expected),
            'objects_and_bundles_must_both_be_present')
    actual = set()
    for folder in (private / 'objects', private / 'bundles'):
        require(folder.is_dir(), 'private_asset_root_missing')
        for path in folder.rglob('*'):
            if path.is_file():
                require(not path.is_symlink() and RESOLVE(path).is_relative_to(private),
                        'private_asset_path_escape')
                relative = path.relative_to(private).as_posix()
                actual.add(relative)
                require(relative in expected and fingerprint(path) == {
                    'bytes': expected[relative]['bytes'], 'sha256': expected[relative]['sha256']},
                    'private_asset_integrity_mismatch')
    require(actual == set(expected), 'private_asset_inventory_mismatch')
    return {'all_verified': True, 'object_files': sum(name.startswith('objects/') for name in actual),
            'bundle_files': sum(name.startswith('bundles/') for name in actual),
            'private_asset_files': len(actual)}


def safe_error(error, phase):
    result = common.safe_exception(error)
    result['phase'] = phase
    if type(error).__name__ == 'GuardDenied' and len(error.args) == 1:
        for category in EXTRA_DENIALS:
            if error.args[0] == 'regression_guard_denied:' + category:
                result['guard_category'] = category
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=('freeze', 'capture', 'replay'))
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--identity-file', type=Path)
    parser.add_argument('--source-run', type=Path)
    parser.add_argument('--fixture-root', type=Path)
    parser.add_argument('--review-file', type=Path)
    options = parser.parse_args(argv)
    require((options.phase == 'freeze' and options.identity_file is not None)
            or (options.phase in {'capture', 'replay'} and options.source_run is not None),
            'phase_inputs_missing')
    require(options.phase != 'replay' or (options.fixture_root is not None and options.review_file is not None),
            'replay_review_inputs_missing')
    output = RESOLVE(options.output_root if options.output_root.is_absolute() else ROOT / options.output_root)
    require(output.parent == ROOT / '.artifacts'
            and re.fullmatch(r'r84-[fcr]-[0-9a-f]{12}', output.name) and not output.exists(),
            'fresh_short_private_output_required')
    output.mkdir(exist_ok=False)
    DRIVER_CONTEXT['output'] = output
    bootstrap = common.bootstrap(output, None)
    database = output / 'private' / (options.phase + '.sqlite')
    os.environ['TIRE_DATABASE_URL'] = os.environ['DATABASE_URL'] = 'sqlite:///' + database.as_posix()
    for variable, folder in (('TI_OBJECT_STORE_ROOT', 'objects'), ('TI_PARSER_BUNDLE_ROOT', 'bundles')):
        require(RESOLVE(Path(os.environ[variable])) == output / 'private' / folder,
                'bootstrap_asset_root_contract_mismatch')
    guard = GateGuard(output, options.phase)
    DRIVER_CONTEXT['guard'] = common.RUN_CONTEXT['guard'] = guard
    guard.install()
    checks = detail = error_detail = origins = review_receipt = frozen_binding = assets = None
    before = live_bindings()
    write_json(output / 'source-before.json', before)
    suppressed = io.StringIO()
    try:
        checks = selfcheck(guard)
        guard.phase = options.phase
        with redirect_stdout(suppressed), redirect_stderr(suppressed):
            if options.phase == 'freeze':
                detail = freeze_source(output, options.identity_file)
            else:
                frozen, manifest, builder, frozen_binding = activate_frozen(guard, options.source_run, options.phase == 'replay')
                if options.phase == 'capture':
                    detail = builder.run_capture(frozen, manifest, output)
                    staging = output / 'staging'
                    require({child.name for child in staging.iterdir()} == set(FIXTURE_FILES)
                            and all(child.is_file() and not child.is_symlink() for child in staging.iterdir()),
                            'capture_staging_file_set_changed')
                    require(read_json(staging / 'source-index.json')['frozen_source_manifest'] == manifest,
                            'capture_frozen_source_binding_changed')
                    assets = check_assets(output / 'staging/expected_023.json', output / 'private')
                else:
                    fixture, review_receipt = reviewed_fixture(options.fixture_root, options.review_file, manifest)
                    detail = builder.run_replay(fixture, output)
                    assets = check_assets(fixture / 'expected_023.json', output / 'private')
                origins = check_product_origins(frozen, manifest, options.phase == 'replay')
                verify_frozen_tree(frozen, manifest)
                frozen_binding['frozen_tree_verified_after_execution'] = True
    except BaseException as error:
        error_detail = safe_error(error, options.phase)
    guard.phase = 'teardown'
    closure = guard.database_closure()
    backup = guard.verify_backup()
    after = live_bindings()
    guard.phase = 'receipt'
    write_json(output / 'source-after.json', after)
    snapshot = guard.snapshot()
    denied = sum(guard.denied_count(phase) for phase in ('bootstrap', 'freeze', 'capture', 'replay', 'teardown', 'receipt'))
    known = snapshot['known_blocked_ipv6_probes']
    resources_closed = closure['all_closed_by_producer'] and snapshot['metrics']['active_listeners'] == 0
    passed = bool(checks and checks['all_passed'] and error_detail is None
                  and isinstance(detail, dict) and detail.get('success') is True
                  and before == after and denied == 0 and resources_closed
                  and closure['required_database_observed'] and backup['unchanged'])
    fixtures = []
    if options.phase == 'capture' and (output / 'staging').is_dir():
        fixtures = [record(output / 'staging' / name) for name in FIXTURE_FILES if (output / 'staging' / name).is_file()]
        passed = passed and len(fixtures) == len(FIXTURE_FILES)
    result = {'schema': 'vehicle-binary-023-managed-gate@1', 'phase': options.phase,
              'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': passed,
              'runner_exit_code': 0 if passed else 3, 'failure': error_detail,
              'selfcheck': checks, 'source_input_count': len(before), 'sources_stable': before == after,
              'production_python_file_count': 140, 'source_environment': environment_identity(),
              'bootstrap': {'removed_environment_variable_count': bootstrap['removed_environment_variable_count'],
                            'environment_values_recorded': False},
              'product_import_origins': origins, 'database_resources': closure,
              'frozen_source_binding': frozen_binding, 'private_assets': assets,
              'frozen_source_index': record(output / 'source-index.json') if options.phase == 'freeze'
                                     and (output / 'source-index.json').is_file() else None,
              'resources_closed': resources_closed, 'guard': snapshot,
              'raw_nonselfcheck_denials': denied, 'known_blocked_ipv6_import_probes': known,
              'other_unexpected_denials': denied - known, 'r38_backup_verification': backup,
              'independent_review': review_receipt, 'fixture_outputs': fixtures,
              'producer_success': isinstance(detail, dict) and detail.get('success') is True,
              'suppressed_output_characters': len(suppressed.getvalue()),
              'all_child_launches_denied': True, 'authorized_children': 0,
              'normal_database_started': False, 'real_network_or_provider_calls': 0,
              'raw_argv_environment_logs_or_error_messages_persisted': False,
              'qualification': 'Frozen current023 source with synthetic historical rows; not a normal backup or retained historical production database',
              'limits': ['Python audit boundary, not an OS syscall sandbox',
                         'No migration024, production model changes, overlay DDL or full149 pytest execution']}
    write_json(output / 'result.json', result)
    print(json.dumps({'passed': passed, 'phase': options.phase, 'result': record(output / 'result.json'),
                      'runner_exit_code': result['runner_exit_code']}))
    return result['runner_exit_code']


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        failure = {'schema': 'vehicle-binary-023-driver-failure@1',
                   'failure': safe_error(error, 'driver'), 'runner_exit_code': 4,
                   'sources_stable': None, 'resources_closed': None}
        output = DRIVER_CONTEXT['output']
        if output is not None:
            try:
                write_json(output / 'driver-failure.json', failure)
                failure['receipt'] = record(output / 'driver-failure.json')
            except Exception as reporting_error:
                failure['reporting_failure_type'] = type(reporting_error).__name__
        print(json.dumps(failure))
        raise SystemExit(4)
