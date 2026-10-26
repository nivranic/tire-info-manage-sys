#!/usr/bin/env python3
"""Isolated API/Worker selfchecks, collection and explicitly selected test runs.

Run in a fresh process with the API venv: python -X utf8 -B this_file.py --help.
Output intentionally omits arbitrary failure messages and captured output. This
protects report files without rewriting what capsys/caplog/child PIPE consumers see.
"""
from __future__ import annotations

import argparse
import _sqlite3
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import platform
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import sysconfig
import tempfile
from types import SimpleNamespace
from uuid import uuid4
import xml.etree.ElementTree as ET

TRUSTED_PATH_RESOLVE = Path.resolve
ROOT = TRUSTED_PATH_RESOLVE(Path(__file__)).parents[1]
RUN_CONTEXT = {'output': None, 'guard': None, 'pytest_exit_code': None}
GUARD_DENIAL_CATEGORIES = frozenset({
    'r38_backup_changed', 'sqlite_attach', 'sqlite_detach', 'sqlite_r38_write',
    'metrics_listener_leaked', 'metrics_start_not_authorized', 'metrics_nested_start',
    'metrics_listener_identity_mismatch', 'metrics_listener_not_closed', 'network_bind',
    'network_connect', 'network_dns_or_datagram', 'child_process',
    'sqlite_nonprivate_or_untrusted_uri', 'sqlite_unexpected_handle',
    'filesystem_write_outside', 'filesystem_mutation_outside',
    'filesystem_move_or_link_outside', 'cwd_outside', 'nested_socketpair',
    'network_listen', 'sqlite_unreviewed_factory', 'sqlite_connection_identity_mismatch',
    'filesystem_untrusted_dir_fd',
})
# Explicit 180 API + 2 Worker module manifest. Never substitute discovery for it.
TEST_MODULES = (
    'apps/api/tests/test_adapter_import_behavior.py',
    'apps/api/tests/test_adapters.py',
    'apps/api/tests/test_ai.py',
    'apps/api/tests/test_ai_anthropic_provider.py',
    'apps/api/tests/test_ai_chat_provider.py',
    'apps/api/tests/test_ai_monitoring.py',
    'apps/api/tests/test_ai_pricing.py',
    'apps/api/tests/test_ai_pricing_migration.py',
    'apps/api/tests/test_ai_rule_contract.py',
    'apps/api/tests/test_ai_rule_drafts.py',
    'apps/api/tests/test_ai_stream_api.py',
    'apps/api/tests/test_ai_stream_execution.py',
    'apps/api/tests/test_ai_stream_migration.py',
    'apps/api/tests/test_ai_stream_parser.py',
    'apps/api/tests/test_api_key_inventory.py',
    'apps/api/tests/test_api_key_inventory_review.py',
    'apps/api/tests/test_auth_accounts.py',
    'apps/api/tests/test_auth_governance.py',
    'apps/api/tests/test_auth_lifecycle.py',
    'apps/api/tests/test_brand_adapters.py',
    'apps/api/tests/test_canary.py',
    'apps/api/tests/test_candidate_ai.py',
    'apps/api/tests/test_candidate_ai_review.py',
    'apps/api/tests/test_core.py',
    'apps/api/tests/test_curation.py',
    'apps/api/tests/test_device_ai_archive.py',
    'apps/api/tests/test_device_ai_capacity.py',
    'apps/api/tests/test_device_ai_decoder_fixtures.py',
    'apps/api/tests/test_device_ai_domains.py',
    'apps/api/tests/test_device_ai_dto.py',
    'apps/api/tests/test_device_ai_fixture_corpus.py',
    'apps/api/tests/test_device_ai_migration012.py',
    'apps/api/tests/test_device_ai_migration013.py',
    'apps/api/tests/test_device_ai_models.py',
    'apps/api/tests/test_device_ai_projection.py',
    'apps/api/tests/test_device_ai_public_contract.py',
    'apps/api/tests/test_device_ai_read_paths.py',
    'apps/api/tests/test_device_ai_routes_prepare.py',
    'apps/api/tests/test_device_ai_submit.py',
    'apps/api/tests/test_device_ai_value_encoder.py',
    'apps/api/tests/test_e1_vectors.py',
    'apps/api/tests/test_embeddings.py',
    'apps/api/tests/test_external_api.py',
    'apps/api/tests/test_external_api_review.py',
    'apps/api/tests/test_external_fact_governance.py',
    'apps/api/tests/test_external_fact_governance_cli.py',
    'apps/api/tests/test_external_fact_migration.py',
    'apps/api/tests/test_external_fact_policy.py',
    'apps/api/tests/test_external_tire_fact_page.py',
    'apps/api/tests/test_external_tire_fact_projection.py',
    'apps/api/tests/test_external_tire_fact_reader.py',
    'apps/api/tests/test_field_authority.py',
    'apps/api/tests/test_field_authority_consumers.py',
    'apps/api/tests/test_field_evidence.py',
    'apps/api/tests/test_fitment_relations.py',
    'apps/api/tests/test_garage.py',
    'apps/api/tests/test_golden.py',
    'apps/api/tests/test_golden_checks.py',
    'apps/api/tests/test_golden_release_gate.py',
    'apps/api/tests/test_identity_batch.py',
    'apps/api/tests/test_identity_keys_v2.py',
    'apps/api/tests/test_identity_migration.py',
    'apps/api/tests/test_identity_resolution.py',
    'apps/api/tests/test_identity_view_contracts.py',
    'apps/api/tests/test_interest_applicability.py',
    'apps/api/tests/test_interest_applicability_review.py',
    'apps/api/tests/test_interest_events.py',
    'apps/api/tests/test_interest_governance.py',
    'apps/api/tests/test_interest_governance_review.py',
    'apps/api/tests/test_interest_migration.py',
    'apps/api/tests/test_interest_review.py',
    'apps/api/tests/test_knowledge.py',
    'apps/api/tests/test_legacy024_isolation.py',
    'apps/api/tests/test_lifecycle.py',
    'apps/api/tests/test_main_lazy_app.py',
    'apps/api/tests/test_michelin.py',
    'apps/api/tests/test_monitor_conditions.py',
    'apps/api/tests/test_monitor_task_execution.py',
    'apps/api/tests/test_monitor_tasks.py',
    'apps/api/tests/test_monitoring.py',
    'apps/api/tests/test_namespace_ai.py',
    'apps/api/tests/test_namespace_quality.py',
    'apps/api/tests/test_nhtsa.py',
    'apps/api/tests/test_object_store.py',
    'apps/api/tests/test_observability_trends.py',
    'apps/api/tests/test_offline_migration.py',
    'apps/api/tests/test_offline_packs.py',
    'apps/api/tests/test_offline_packs_v2.py',
    'apps/api/tests/test_offline_sync_owner.py',
    'apps/api/tests/test_offline_updates.py',
    'apps/api/tests/test_parser_bundles.py',
    'apps/api/tests/test_parser_cache_policy.py',
    'apps/api/tests/test_parser_deployment_adapters.py',
    'apps/api/tests/test_parser_failure_reasons.py',
    'apps/api/tests/test_parser_releases.py',
    'apps/api/tests/test_parser_runtime.py',
    'apps/api/tests/test_parser_runtime_environment.py',
    'apps/api/tests/test_personalization.py',
    'apps/api/tests/test_personalization_review.py',
    'apps/api/tests/test_pirelli.py',
    'apps/api/tests/test_professional_golden_bindings.py',
    'apps/api/tests/test_professional_golden_checks.py',
    'apps/api/tests/test_professional_golden_cli.py',
    'apps/api/tests/test_professional_golden_corpus.py',
    'apps/api/tests/test_professional_golden_review.py',
    'apps/api/tests/test_quality.py',
    'apps/api/tests/test_quarantine_review.py',
    'apps/api/tests/test_query_fallback_migration49.py',
    'apps/api/tests/test_query_fallback_policies49.py',
    'apps/api/tests/test_query_fallback_policy_boundaries49.py',
    'apps/api/tests/test_query_fallback_preferences49.py',
    'apps/api/tests/test_query_filter_reference49.py',
    'apps/api/tests/test_query_filters.py',
    'apps/api/tests/test_query_ownership.py',
    'apps/api/tests/test_raw_captures.py',
    'apps/api/tests/test_raw_evidence_v2_sdk.py',
    'apps/api/tests/test_recall_ai_consumers.py',
    'apps/api/tests/test_recall_discovery.py',
    'apps/api/tests/test_recall_discovery_migration.py',
    'apps/api/tests/test_recall_discovery_monitor_api.py',
    'apps/api/tests/test_recall_discovery_monitor_execution.py',
    'apps/api/tests/test_recall_grounding.py',
    'apps/api/tests/test_recall_knowledge_ai.py',
    'apps/api/tests/test_recall_monitoring.py',
    'apps/api/tests/test_recall_parser_releases.py',
    'apps/api/tests/test_recall_reparse.py',
    'apps/api/tests/test_recall_reports.py',
    'apps/api/tests/test_recalls.py',
    'apps/api/tests/test_rejected_observations.py',
    'apps/api/tests/test_reparse.py',
    'apps/api/tests/test_report_rendering.py',
    'apps/api/tests/test_reports.py',
    'apps/api/tests/test_research.py',
    'apps/api/tests/test_robots.py',
    'apps/api/tests/test_schema_startup.py',
    'apps/api/tests/test_source_access.py',
    'apps/api/tests/test_source_materials.py',
    'apps/api/tests/test_source_materials_review.py',
    'apps/api/tests/test_source_material_stop_migration.py',
    'apps/api/tests/test_source_page_migration.py',
    'apps/api/tests/test_source_page_monitoring.py',
    'apps/api/tests/test_source_quality_interest_migration.py',
    'apps/api/tests/test_source_quality_interests.py',
    'apps/api/tests/test_source_settings.py',
    'apps/api/tests/test_telemetry.py',
    'apps/api/tests/test_telemetry_api.py',
    'apps/api/tests/test_telemetry_domain.py',
    'apps/api/tests/test_test_ai_contract.py',
    'apps/api/tests/test_test_ai_grounding_review.py',
    'apps/api/tests/test_test_ai_reports.py',
    'apps/api/tests/test_test_ai_stream_terminal.py',
    'apps/api/tests/test_test_candidate_actor_scope.py',
    'apps/api/tests/test_test_candidate_interpretation.py',
    'apps/api/tests/test_test_candidate_interpretation_review.py',
    'apps/api/tests/test_test_events.py',
    'apps/api/tests/test_test_event_golden.py',
    'apps/api/tests/test_test_event_golden_migration.py',
    'apps/api/tests/test_test_preference_interpretation.py',
    'apps/api/tests/test_test_preference_routes.py',
    'apps/api/tests/test_test_sku_bridge_review.py',
    'apps/api/tests/test_test_sku_links.py',
    'apps/api/tests/test_vehicle_binary_approval.py',
    'apps/api/tests/test_vehicle_binary_captures.py',
    'apps/api/tests/test_vehicle_binary_consumers.py',
    'apps/api/tests/test_vehicle_binary_dispatch.py',
    'apps/api/tests/test_vehicle_binary_garage_offline.py',
    'apps/api/tests/test_vehicle_binary_ingestion.py',
    'apps/api/tests/test_vehicle_binary_knowledge.py',
    'apps/api/tests/test_vehicle_binary_migration.py',
    'apps/api/tests/test_vehicle_binary_reparse.py',
    'apps/api/tests/test_vehicle_binary_review_boundary.py',
    'apps/api/tests/test_vehicle_pdf.py',
    'apps/api/tests/test_vehicle_pdf_runtime.py',
    'apps/api/tests/test_vehicle_quality.py',
    'apps/api/tests/test_vehicle_query_fallback_cause49.py',
    'apps/api/tests/test_vehicle_raw.py',
    'apps/api/tests/test_vehicle_raw_v2.py',
    'apps/api/tests/test_vehicles.py',
    'apps/api/tests/test_webhooks.py',
    'apps/api/tests/test_webhooks_review.py',
    'apps/worker/test_monitor.py',
    'apps/worker/test_telemetry_monitor.py',
)
SAFE_SKIP_REASONS = {
    'independent live capture unavailable; synthetic tests are not a canary',
    'Cross-language public contract check requires the monorepo Node runtime',
    'Public SDK response parity requires the monorepo Node runtime',
    'explicit read-only Round 38 backup not available',
    'Independent live source capture unavailable; fixture replay is not a live canary',
    'Requires one explicitly supplied private HTTP actual directory',
    'Host does not permit an actual filesystem symlink/junction',
    'Set R76_REVIEW_ACTUAL_DIR to one explicit private HTTP run',
}


def write_json(path: Path, value) -> None:
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def record(path: Path) -> dict:
    raw = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(), 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


def safe_exception(error: BaseException) -> dict:
    guard = RUN_CONTEXT['guard']
    phase = getattr(guard, 'phase', 'startup')
    if phase not in {'startup', 'bootstrap', 'selfcheck', 'collection', 'run', 'teardown', 'receipt'}:
        phase = 'unknown'
    category = None
    if type(error).__name__ == 'GuardDenied' and len(error.args) == 1:
        for allowed in GUARD_DENIAL_CATEGORIES:
            if error.args[0] == 'regression_guard_denied:' + allowed:
                category = allowed
                break
    frames, traceback = [], error.__traceback__
    while traceback is not None and len(frames) < 64:
        code = traceback.tb_frame.f_code
        frames.append({'path': safe_nodeid(code.co_filename, 0)['nodeid'],
                       'function': code.co_name, 'line': traceback.tb_lineno})
        traceback = traceback.tb_next
    return {'failure_type': type(error).__name__, 'phase': phase,
            'guard_category': category, 'frames': frames, 'message_omitted': True,
            'locals_and_arguments_omitted': True}


def bindings() -> list[dict]:
    paths = {ROOT / 'apps/api/pyproject.toml'}
    for directory in ('apps/api/tire_api', 'apps/api/tests', 'apps/worker', 'scripts'):
        paths.update(p for p in (ROOT / directory).rglob('*.py')
                     if not {'__pycache__', '.venv', 'node_modules'} & set(p.parts))
    for directory in ('apps/api/tests/fixtures', 'packages/domain-types/fixtures',
                      'packages/api-client/src', 'packages/api-client/tests', 'packages/domain-types/src'):
        base = ROOT / directory
        if base.is_dir():
            paths.update(p for p in base.rglob('*') if p.is_file()
                         and not {'__pycache__', 'node_modules'} & set(p.parts))
    paths.update(p for p in (ROOT / 'scripts').glob('regression_*.cjs') if p.is_file())
    paths.update(ROOT / name for name in ('package.json', 'package-lock.json', 'tsconfig.json',
        'packages/api-client/package.json', 'packages/api-client/tsconfig.json',
        'packages/domain-types/package.json', 'packages/domain-types/tsconfig.json') if (ROOT / name).is_file())
    return [record(path) for path in sorted(paths)]


def selected_targets(values: list[str] | None) -> list[str]:
    modules = set(TEST_MODULES)
    actual = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'apps/api/tests').glob('test_*.py')}
    if actual != {p for p in modules if p.startswith('apps/api/tests/')}:
        raise ValueError('explicit_module_manifest_drift')
    result = []
    for value in values or list(TEST_MODULES):
        filename, separator, selection = value.replace('\\', '/').partition('::')
        path = Path(filename)
        path = TRUSTED_PATH_RESOLVE(path if path.is_absolute() else ROOT / path)
        if not path.is_relative_to(ROOT) or path.relative_to(ROOT).as_posix() not in modules:
            raise ValueError('target_outside_explicit_module_manifest')
        if not path.is_file():
            raise ValueError('target_file_missing')
        result.append(str(path) + (separator + selection if separator else ''))
    if len(result) != len(set(result)):
        raise ValueError('duplicate_target')
    return result


def bootstrap(out: Path, actual_dir: Path | None) -> dict:
    private = out / 'private'
    for path in (private, private / 'tmp', private / 'r70', private / 'r71', private / 'r72',
                 private / 'r75', private / 'r119', out / 'r75'):
        path.mkdir(exist_ok=False)
    removed = 0
    for name in list(os.environ):
        upper = name.upper()
        if (upper.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_', 'AWS_',
                              'GOOGLE_', 'GCP_', 'HF_', 'HUGGINGFACE_', 'EPREL_', 'R70_',
                              'R71_', 'R72_', 'R75_', 'R76_', 'R77_', 'R78_', 'R79_', 'R80_', 'R82_', 'R119_'))
                or upper in ('DATABASE_URL', 'CODEX_DEV_TEST_URL', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS',
                             'NODE_OPTIONS', 'NODE_PATH', 'NODE_COMPILE_CACHE',
                             'PYTHONSTARTUP', 'PYTHONHOME', 'PYTHONINSPECT') or upper.endswith(
                    ('_PROXY', '_API_KEY', '_TOKEN', '_PASSWORD', '_SECRET', '_ACCESS_KEY_ID',
                     '_SECRET_ACCESS_KEY'))):
            del os.environ[name]
            removed += 1
    architecture = {'win-amd64': 'AMD64', 'win-arm64': 'ARM64', 'win32': 'x86'}.get(sysconfig.get_platform())
    if sys.platform == 'win32':
        if architecture is None:
            raise RuntimeError('trusted_python_architecture_unknown')
        os.environ.pop('PROCESSOR_ARCHITEW6432', None)
        os.environ['PROCESSOR_ARCHITECTURE'] = architecture
        def native_win32_ver(release='', version='', csd='', ptype=''):
            native = sys.getwindowsversion()
            return str(native.major), f'{native.major}.{native.minor}.{native.build}', native.service_pack, ptype
        platform.win32_ver = native_win32_ver
    url = 'sqlite:///' + (private / 'bootstrap.db').as_posix()
    values = {
        'TIRE_DATABASE_URL': url, 'DATABASE_URL': url,
        'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0', 'TI_OBSERVABILITY_ENABLED': '0',
        'TI_OBJECT_STORE_BACKEND': 'filesystem', 'TI_OBJECT_STORE_ROOT': str(private / 'objects'),
        'TI_PARSER_BUNDLE_ROOT': str(private / 'bundles'),
        'TEMP': str(private / 'tmp'), 'TMP': str(private / 'tmp'), 'TMPDIR': str(private / 'tmp'),
        'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1',
        'R70_REVIEW_STORAGE_ROOT': str(private / 'r70'), 'R70_REVIEW_GUARD_REPORT': str(out / 'r70-guard.json'),
        'R71_REVIEW_STORAGE_ROOT': str(private / 'r71'), 'R72_REVIEW_STORAGE_ROOT': str(private / 'r72'),
        'R75_TEST_STORAGE_ROOT': str(private / 'r75'), 'R75_REVIEW_OUTPUT': str(out / 'r75'),
        'R77_TEST_STORAGE_ROOT': str(private), 'R77_REVIEW_STORAGE_ROOT': str(private),
        'R78_TEST_STORAGE_ROOT': str(private), 'R79_TEST_STORAGE_ROOT': str(private),
        'R80_TEST_STORAGE_ROOT': str(private),
        'R119_TEST_STORAGE_ROOT': str(private / 'r119'),
        'PYTHONPATH': os.pathsep.join(str(ROOT / p) for p in
                                    ('apps/api', 'apps/api/tests', 'apps/worker', 'scripts')),
    }
    if actual_dir is not None:
        actual_dir = TRUSTED_PATH_RESOLVE(actual_dir)
        if not actual_dir.is_relative_to(TRUSTED_PATH_RESOLVE(ROOT / '.artifacts')) or not actual_dir.name.startswith('r76-') or not actual_dir.is_dir():
            raise ValueError('explicit_r76_actual_directory_required')
        observations = actual_dir / 'actuals'
        if not observations.is_dir():
            raise ValueError('explicit_r76_actuals_child_directory_required')
        values['R76_REVIEW_ACTUAL_DIR'] = str(observations)
    os.environ.update(values)
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(private / 'tmp')
    sys.path[:0] = [str(ROOT / p) for p in ('apps/api', 'apps/api/tests', 'apps/worker', 'scripts')]
    os.chdir(private)
    return {'removed_environment_variable_count': removed, 'credential_values_recorded': False,
            'private_configuration': values, 'python_platform': sysconfig.get_platform(),
            'process_only_architecture': architecture, 'cwd': str(private),
            'r76_actuals': 'explicit directory supplied' if actual_dir else 'unset; affected tests may skip'}


class SuppressedStream(io.TextIOBase):
    """Discard arbitrary reporter output at the final boundary, not at test capture."""
    def __init__(self):
        super().__init__()
        self.characters_suppressed = 0
    @property
    def encoding(self):
        return 'utf-8'
    def writable(self):
        return True
    def isatty(self):
        return False
    def write(self, value):
        self.characters_suppressed += len(value)
        return len(value)
    def flush(self):
        pass


def configure_safe_file_logging() -> None:
    """Only replace pytest's independent file sink; caplog/report handlers stay real."""
    import _pytest.logging as pytest_logging
    class PrivateReportHandler(logging.StreamHandler):
        def __init__(self, filename, mode='w', encoding=None):
            self.baseFilename = str(filename)
            self.mode = mode
            super().__init__(SuppressedStream())
    def no_raw_log_path(self, filename):
        # No current test uses this reporting-only API. Never open a raw fallback.
        self.log_file_handler.setStream(SuppressedStream())
    pytest_logging._FileHandler = PrivateReportHandler
    pytest_logging.LoggingPlugin.set_log_path = no_raw_log_path


def safe_nodeid(nodeid: str, index: int) -> dict:
    parts = nodeid.replace('\\', '/').split('::')
    filename = parts[0]
    try:
        path = Path(filename)
        filename = TRUSTED_PATH_RESOLVE(path if path.is_absolute() else ROOT / path).relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        filename = '<external>'
    names = []
    omitted = False
    for part in parts[1:]:
        name, marker, _parameters = part.partition('[')
        names.append(name if re.fullmatch(r'[A-Za-z_]\w*', name) else '<name>')
        omitted |= bool(marker)
    return {'index': index, 'nodeid': '::'.join([filename, *names]),
            'parameter_id_omitted': omitted}


def safe_failure(report) -> dict:
    crash = getattr(report.longrepr, 'reprcrash', None)
    message = getattr(crash, 'message', '')
    match = re.match(r'(?:E\s+)?([A-Za-z_]\w*(?:Error|Exception|Denied))\b', message)
    error_type = match.group(1) if match else ('AssertionError' if 'AssertionError' in message[:100] else 'Failure')
    location = getattr(report, 'location', ('<unknown>', 0, ''))
    crash_path = getattr(crash, 'path', None)
    crash_line = getattr(crash, 'lineno', None)
    return {'error_type': error_type, 'source_file': safe_nodeid(str(crash_path or location[0]), 0)['nodeid'],
            'line': int(crash_line) if crash_line is not None else int(location[1]) + 1, 'message_omitted': True,
            'captured_sections_omitted': True, 'assertion_details_omitted': True}


def safe_skip(report) -> str:
    representation = report.longrepr
    reason = representation[2] if isinstance(representation, tuple) and len(representation) == 3 else ''
    if reason.startswith('Skipped: '):
        reason = reason[len('Skipped: '):]
    return reason if reason in SAFE_SKIP_REASONS else 'skip_message_omitted_for_privacy'


def case_outcome(case: dict) -> str:
    reports = case['reports']
    if any(row['outcome'] == 'failed' for row in reports):
        return 'failed'
    if any(row['outcome'] == 'skipped' for row in reports):
        return 'skipped'
    if any(row['when'] == 'call' and row['outcome'] == 'passed' for row in reports):
        return 'passed'
    return 'incomplete'


def safe_junit(path: Path, cases: dict) -> None:
    outcomes = {index: case_outcome(case) for index, case in cases.items()}
    errors = {index for index, case in cases.items() if any(
        row['outcome'] == 'failed' and row['when'] != 'call' for row in case['reports'])}
    suite = ET.Element('testsuite', name='isolated-api-worker', tests=str(len(cases)),
        failures=str(sum(value == 'failed' and index not in errors for index, value in outcomes.items())),
        errors=str(len(errors) + sum(value == 'incomplete' for value in outcomes.values())),
        skipped=str(sum(value == 'skipped' for value in outcomes.values())))
    for index, case in cases.items():
        element = ET.SubElement(suite, 'testcase', name=f"{case['nodeid']} [case-{case['index']}]",
            time=f"{sum(row['duration_seconds'] for row in case['reports']):.6f}")
        outcome = outcomes[index]
        if outcome == 'failed':
            failed = next(row for row in case['reports'] if row['outcome'] == 'failed'
                          and (row['when'] != 'call' if index in errors else True))
            details = failed['failure']
            failure = ET.SubElement(element, 'error' if index in errors else 'failure',
                type=details['error_type'], message='Failure details omitted for privacy')
            failure.text = f"{details['source_file']}:{details['line']} ({failed['when']})"
        elif outcome == 'skipped':
            skipped = next(row for row in case['reports'] if row['outcome'] == 'skipped')
            ET.SubElement(element, 'skipped', message=skipped['skip_reason'])
        elif outcome == 'incomplete':
            ET.SubElement(element, 'error', type='IncompleteProtocol', message='No completed call report')
    ET.ElementTree(suite).write(path, encoding='utf-8', xml_declaration=True)


def privacy_selfcheck(out: Path) -> dict:
    secret = secrets.token_urlsafe(32)
    sink = SuppressedStream()
    sink.write(secret)
    fake = SimpleNamespace(longrepr=SimpleNamespace(reprcrash=SimpleNamespace(
        message='AssertionError: ' + secret)), location=('scripts/run_api_worker_regression.py', 1, ''))
    sample = {'failure': safe_failure(fake), 'node': safe_nodeid('apps/api/tests/test_vehicles.py::test_case[' + secret + ']', 1)}
    def stage(when, outcome):
        row = {'when': when, 'outcome': outcome, 'duration_seconds': 0.0}
        if outcome == 'failed':
            row['failure'] = sample['failure']
        if outcome == 'skipped':
            row['skip_reason'] = 'skip_message_omitted_for_privacy'
        return row
    cases = {index: {**sample['node'], 'index': index, 'reports': rows} for index, rows in enumerate([
        [stage('setup', 'passed'), stage('call', 'passed'), stage('teardown', 'passed')],
        [stage('setup', 'passed'), stage('call', 'failed'), stage('teardown', 'passed')],
        [stage('setup', 'passed'), stage('call', 'skipped'), stage('teardown', 'passed')],
        [stage('setup', 'failed'), stage('teardown', 'passed')],
        [stage('setup', 'passed')]], 1)}
    junit = out / 'privacy-selfcheck-junit.xml'
    safe_junit(junit, cases)
    document = ET.parse(junit).getroot()
    assert document.attrib['tests'] == '5' and document.attrib['failures'] == '1'
    assert document.attrib['errors'] == '2' and document.attrib['skipped'] == '1'
    assert [case_outcome(case) for case in cases.values()] == ['passed', 'failed', 'skipped', 'failed', 'incomplete']
    path = out / 'privacy-selfcheck.json'
    write_json(path, {'passed': secret not in json.dumps(sample), 'safe_sample': sample,
                      'raw_terminal_and_log_sink_suppressed': sink.characters_suppressed == len(secret),
                      'junit_mutually_exclusive_counts_checked': True,
                      'junit': record(junit), 'secret_value_or_hash_recorded': False})
    assert secret not in path.read_text(encoding='utf-8') and secret not in junit.read_text(encoding='utf-8')
    return {'passed': True, 'receipt': record(path), 'capsys_caplog_and_child_output_not_rewritten': True}


def selfcheck(guard, children, out: Path) -> dict:
    guard.phase = children.phase = 'selfcheck'
    checks = []
    def denied(name, action, accepted=(PermissionError,)):
        before = guard.denied_count('selfcheck') + children.denied_count('selfcheck')
        try:
            action()
        except accepted:
            passed = guard.denied_count('selfcheck') + children.denied_count('selfcheck') > before
        else:
            passed = False
        checks.append({'name': name, 'passed': passed, 'expected_denial': True})
        if not passed:
            raise RuntimeError('guard_selfcheck_failed')
    denied('DNS', lambda: socket.getaddrinfo('r82-denied.invalid', 443))
    for endpoint, name in ((('198.51.100.1', 443), 'external connect'), (('127.0.0.1', 18881), 'unregistered loopback connect')):
        with socket.socket() as connection:
            denied(name, lambda: connection.connect(endpoint))
    with socket.socket() as listener:
        denied('unregistered bind', lambda: listener.bind(('127.0.0.1', 0)))
    with socket.socket() as listener:
        denied('unregistered listen', lambda: listener.listen(1))
    denied('unreviewed child', lambda: subprocess.Popen([sys.executable, '-c', 'raise SystemExit(99)']))
    forbidden_db = ROOT / '.artifacts' / ('r82-forbidden-' + uuid4().hex + '.sqlite')
    forbidden_file = forbidden_db.with_suffix('.txt')
    denied('nonprivate SQLite', lambda: sqlite3.connect(forbidden_db))
    denied('native SQLite entry without wrapper ticket', lambda: _sqlite3.connect(':memory:'))
    factory_calls = []
    def untrusted_factory(*args, **kwargs):
        factory_calls.append(True)
        raise AssertionError('untrusted_factory_must_not_execute')
    denied('custom SQLite factory before callback', lambda: sqlite3.connect(':memory:', factory=untrusted_factory))
    assert not factory_calls
    denied('nonprivate write', lambda: forbidden_file.write_text('must-not-write', encoding='utf-8'))
    with sqlite3.connect(':memory:') as memory:
        denied('nonprivate ATTACH', lambda: memory.execute('ATTACH DATABASE ? AS forbidden', (str(forbidden_db),)), (sqlite3.DatabaseError,))
    assert not forbidden_db.exists() and not forbidden_file.exists()
    left, right = socket.socketpair()
    left.close()
    right.close()
    checks.append({'name': 'exact internal socketpair', 'passed': True, 'expected_denial': False})
    privacy = privacy_selfcheck(out)
    return {'all_passed': all(row['passed'] for row in checks), 'checks': checks,
            'intentional_denial_actions': sum(row['expected_denial'] for row in checks),
            'privacy': privacy, 'normal_database_opened': False, 'external_network_reached': False}


def pytest_run(phase: str, targets: list[str], out: Path, private: Path, guard, children) -> dict:
    import pytest
    configure_safe_file_logging()
    nodeids, collection_reports, cases, subtests = [], [], {}, []
    raw_ids, protocols = [], []
    reporting_failures, reporting_failure_count = [], 0
    output = SuppressedStream()
    progress_path = out / 'progress.jsonl'
    with progress_path.open('x', encoding='utf-8', newline='\n'):
        pass
    def report_write(destination, action):
        nonlocal reporting_failure_count
        try:
            return action()
        except BaseException as error:
            reporting_failure_count += 1
            if len(reporting_failures) < 16:
                reporting_failures.append({'destination': destination, 'failure': safe_exception(error)})
            return None
    def progress(row):
        def append():
            with progress_path.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                stream.flush()
        report_write('progress.jsonl', append)
    class Recorder:
        def pytest_collection_finish(self, session):
            raw_ids.extend(item.nodeid for item in session.items)
            nodeids.extend(safe_nodeid(item.nodeid, i + 1) for i, item in enumerate(session.items))
            report_write('nodeids.json', lambda: write_json(out / 'nodeids.json', nodeids))
            progress({'event': 'collection_finished', 'collected_items': len(nodeids)})
            module = sys.modules.get('tire_api.telemetry')
            if module is not None and hasattr(module, 'TelemetryRuntime'):
                guard.register_metrics_runtime(module.TelemetryRuntime)
        def pytest_collectreport(self, report):
            item = {'node': safe_nodeid(report.nodeid, len(collection_reports) + 1), 'outcome': report.outcome}
            if report.failed:
                item['failure'] = safe_failure(report)
            collection_reports.append(item)
        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_protocol(self, item, nextitem):
            if phase == 'collect':
                raise RuntimeError('collect_must_not_execute_protocol')
            protocols.append(item.nodeid)
            guard.set_test_nodeid(item.nodeid)
            try:
                yield
            finally:
                guard.set_test_nodeid(None)
        def pytest_runtest_logreport(self, report):
            index = raw_ids.index(report.nodeid) + 1
            is_subtest = type(report).__name__ == 'SubTestReport' or hasattr(report, 'context')
            case = cases.setdefault(index, {**safe_nodeid(report.nodeid, index), 'reports': []})
            row = {'when': report.when, 'outcome': report.outcome,
                   'duration_seconds': round(float(report.duration), 6)}
            if report.failed:
                row['failure'] = safe_failure(report)
            if report.skipped:
                row['skip_reason'] = safe_skip(report)
                row['skip_reason_code'] = ('source_literal' if row['skip_reason'] in SAFE_SKIP_REASONS
                    else f'unclassified_skip_case_{index}')
            if is_subtest:
                subtests.append({'parent_case_index': index, 'subtest_index': len(subtests) + 1, **row})
            else:
                case['reports'].append(row)
            progress({'event': 'subtest_report' if is_subtest else 'test_report',
                      'case_index': index, 'nodeid': case['nodeid'],
                      'when': row['when'], 'outcome': row['outcome'],
                      'duration_seconds': row['duration_seconds']})
    args = [*targets, '-c', str(ROOT / 'apps/api/pyproject.toml'), '--rootdir', str(ROOT),
            '--capture=sys', '-q', '-p', 'no:cacheprovider', '-p', 'no:junitxml',
            '-o', 'log_file=', '-o', 'log_cli=false', '--basetemp', str(private / 'pytest-tmp'),
            '--tb=short', '--color=no']
    if phase == 'collect':
        args.append('--collect-only')
    failure_type, pytest_api_failure = None, None
    with redirect_stdout(output), redirect_stderr(output):
        try:
            code = int(pytest.main(args, plugins=[Recorder()]))
            RUN_CONTEXT['pytest_exit_code'] = code
        except BaseException as error:
            code, failure_type = None, type(error).__name__
            pytest_api_failure = safe_exception(error)
    if not (out / 'nodeids.json').exists():
        report_write('nodeids.json', lambda: write_json(out / 'nodeids.json', nodeids))
    for filename, value in (('collection-reports.json', collection_reports),
                            ('test-reports.json', list(cases.values())), ('subtest-reports.json', subtests)):
        report_write(filename, lambda name=filename, data=value: write_json(out / name, data))
    report_write('junit.xml', lambda: safe_junit(out / 'junit.xml', cases))
    progress_record = report_write('progress.jsonl binding', lambda: record(progress_path))
    return {'pytest_exit_code': code, 'failure_type': failure_type, 'pytest_api_failure': pytest_api_failure,
            'reporting_failure_count': reporting_failure_count, 'reporting_failures': reporting_failures,
            'collected_items': len(raw_ids),
            'unique_nodeids': len(raw_ids) == len(set(raw_ids)),
            'collected_modules': len({item.split('::', 1)[0] for item in raw_ids}),
            'test_protocols_started': len(protocols),
            'tests_executed': sum(any(r['when'] == 'call' for r in case['reports']) for case in cases.values()),
            'outcomes': {kind: sum(case_outcome(case) == kind for case in cases.values())
                         for kind in ('passed', 'failed', 'skipped', 'incomplete')},
            'phase_outcomes': {when: {kind: sum(row['when'] == when and row['outcome'] == kind
                for case in cases.values() for row in case['reports']) for kind in ('passed', 'failed', 'skipped')}
                for when in ('setup', 'call', 'teardown')},
            'subtest_outcomes': {kind: sum(row['outcome'] == kind for row in subtests)
                                for kind in ('passed', 'failed', 'skipped')},
            'report_characters_suppressed': output.characters_suppressed,
            'safe_progress': progress_record,
            'raw_node_parameter_ids_and_failure_sections_persisted': False,
            'logging_note': 'Only pytest file/report sinks suppressed; caplog/capsys and child PIPE values unchanged'}


def dispose_cached_default_app(loaded) -> None:
    """Dispose only an existing instance; never resolve main's lazy export."""
    cached = vars(loaded).get('app') if loaded is not None else None
    if cached is not None:
        cached.state.database.engine.dispose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=('selfcheck', 'collect', 'run'))
    parser.add_argument('--output-root', type=Path, default=None)
    parser.add_argument('--targets', nargs='+', help='Only registered file paths or nodeids; default explicit 182 modules')
    parser.add_argument('--actual-dir', type=Path, help='One existing explicit r76-* actual run, never latest')
    options = parser.parse_args(argv)
    targets = selected_targets(options.targets)
    out = TRUSTED_PATH_RESOLVE(options.output_root or ROOT / '.artifacts' / ('r82-regression-' + uuid4().hex))
    if not out.is_relative_to(TRUSTED_PATH_RESOLVE(ROOT / '.artifacts')) or out.exists():
        raise ValueError('new_private_artifact_output_required')
    out.mkdir(parents=True, exist_ok=False)
    RUN_CONTEXT['output'] = out
    config = bootstrap(out, options.actual_dir)
    from regression_children import ChildPolicy
    from regression_guard import RegressionGuard
    children = ChildPolicy(ROOT, out / 'private', out)
    guard = RegressionGuard(ROOT, out / 'private', out, child_policy=children)
    RUN_CONTEXT['guard'] = guard
    guard.install()
    children.install()
    before = bindings()
    write_json(out / 'source-before.json', before)
    write_json(out / 'bootstrap.json', config)
    checks, execution, failure_type, failure_detail = None, None, None, None
    try:
        checks = selfcheck(guard, children, out)
        guard.phase = children.phase = 'receipt'
        write_json(out / 'selfcheck.json', checks)
        if options.phase != 'selfcheck':
            guard.phase = children.phase = 'collection' if options.phase == 'collect' else 'run'
            execution = pytest_run(options.phase, targets, out, out / 'private', guard, children)
    except BaseException as error:
        failure_type = type(error).__name__
        failure_detail = safe_exception(error)
    guard.phase = children.phase = 'teardown'
    try:
        dispose_cached_default_app(sys.modules.get('tire_api.main'))
    except Exception as error:
        failure_type = failure_type or type(error).__name__
    backup_verification = None
    try:
        backup_verification = guard.verify_backup()
    except Exception as error:
        failure_type = failure_type or type(error).__name__
    after = bindings()
    guard.phase = children.phase = 'receipt'
    write_json(out / 'source-after.json', after)
    snapshot, child_snapshot = guard.snapshot(), children.snapshot()
    denied = sum(guard.denied_count(p) + children.denied_count(p)
                 for p in ('bootstrap', 'collection', 'run', 'teardown', 'receipt'))
    known = snapshot.get('known_blocked_ipv6_probes', 0)
    stable = before == after
    resources_closed = (child_snapshot.get('live_process_count') == 0
                        and snapshot.get('metrics', {}).get('active_listeners') == 0)
    passed = bool(checks and checks['all_passed'] and not failure_type and stable and denied == 0
                  and resources_closed and backup_verification and backup_verification['unchanged'])
    if execution is not None:
        passed &= (execution['pytest_exit_code'] == 0 and not execution['failure_type']
                   and execution['reporting_failure_count'] == 0
                   and execution['collected_items'] > 0 and execution['unique_nodeids'])
        if options.phase == 'run':
            passed &= (execution['test_protocols_started'] == execution['collected_items']
                       and execution['outcomes']['incomplete'] == 0)
        if options.phase == 'collect':
            passed &= execution['test_protocols_started'] == execution['tests_executed'] == 0
    result = {'schema': 'r82-api-worker-regression@1', 'phase': options.phase,
              'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': bool(passed),
              'runner_exit_code': 0 if passed else 3, 'failure_type': failure_type,
              'failure_detail': failure_detail,
              'target_module_manifest_count': len(TEST_MODULES),
              'targets': [safe_nodeid(target, index + 1) for index, target in enumerate(targets)],
              'selfcheck': checks, 'execution': execution, 'source_input_count': len(before),
              'sources_stable': stable, 'guard': snapshot, 'children': child_snapshot,
              'backup_verification': backup_verification, 'resources_closed': resources_closed,
              'raw_nonselfcheck_denials': denied, 'known_blocked_ipv6_import_probes': known,
              'other_unexpected_denials': denied - known,
              'normal_database_started': False, 'real_provider_or_receiver_calls': 0,
              'privacy': {'raw_reports_or_logs_persisted': False, 'failure_detail_policy': 'safe type/file/line only; other content omitted',
                          'capture_mode': 'sys, in-memory; no raw FD capture files', 'capsys_caplog_and_child_pipe_values_not_rewritten': True,
                          'default_fd_capture_equivalence_claimed': False,
                          'nodeids': 'Parameter IDs omitted; stable case index and source binding identify scope, not a full exact-nodeid replay manifest'},
              'limits': ['Python audit boundary, not an OS syscall sandbox',
                         'Only a run-phase executed suite can establish current API/Worker test results',
                         'Synthetic/private actuals are not real professional SKU or human Golden acceptance']}
    write_json(out / 'result.json', result)
    write_json(out / 'classification.json', {'raw_passed': bool(passed), 'raw_runner_exit_code': result['runner_exit_code'],
               'pytest_exit_code': execution['pytest_exit_code'] if execution else None,
               'known_blocked_ipv6_import_probes': known, 'other_unexpected_denials': denied - known,
               'classification': 'completed_with_known_blocked_dependency_probe' if (
                   execution and execution['pytest_exit_code'] == 0 and not execution['failure_type']
                   and execution['reporting_failure_count'] == 0
                   and checks and checks['all_passed'] and not failure_type and stable
                   and resources_closed and backup_verification and backup_verification['unchanged']
                   and execution['collected_items'] > 0 and execution['unique_nodeids']
                   and ((options.phase == 'collect' and execution['test_protocols_started'] == execution['tests_executed'] == 0)
                        or (options.phase == 'run' and execution['test_protocols_started'] == execution['collected_items']
                            and execution['outcomes']['incomplete'] == 0))
                   and known and denied == known) else 'raw_verdict_preserved',
               'not_a_full_suite_pass': options.phase != 'run' or bool(options.targets) or not passed})
    print(json.dumps({'passed': bool(passed), 'phase': options.phase, 'output': out.relative_to(ROOT).as_posix(),
                      'runner_exit_code': result['runner_exit_code'], 'failure_type': failure_type,
                      'result': record(out / 'result.json')}, ensure_ascii=False))
    return result['runner_exit_code']


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        failure = {'schema': 'r82-runner-failure@1', 'runner_failed': True,
                   'failure': safe_exception(error), 'pytest_exit_code': RUN_CONTEXT['pytest_exit_code'],
                   'message_omitted_for_privacy': True, 'failure_receipt_written': False}
        if RUN_CONTEXT['output'] is not None:
            try:
                failure['failure_receipt_written'] = True
                write_json(RUN_CONTEXT['output'] / 'runner-failure.json', failure)
            except Exception:
                failure['failure_receipt_written'] = False
        print(json.dumps(failure, ensure_ascii=False))
        raise SystemExit(4)
