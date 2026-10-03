"""Opt-in real Pirelli acceptance followed by explicitly injected offline checks.

Use --live to authorize public source requests. The production allowlist, DNS,
HTTPS, robots and sealed parser run unchanged against an independent temporary
SQLite database/object store/bundle directory. A network or source-contract
failure fails this run; recorded HTML is never substituted for live transport.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tire_api.adapters import registry
from tire_api.ai_models import AIRequest
from tire_api.captures import checked_capture_bytes
from tire_api.db import (CaptureObject, ChangeEvent, EvidenceObject, FactVersion,
                         FallbackConsent, QueryRun, RawCapture, Snapshot, TireVariant)
from tire_api.domain import digest
from tire_api.embedding_models import EmbeddingRequest
from tire_api.parser_release_models import ParserBundle, ParserExecution
from tire_api.parser_runtime import input_hash

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'pirelli-us'
MODEL = 'P ZERO (PZ4)'
EXPECTED_CATALOG = {'michelin-us', 'michelin-uk', 'michelin-fr', 'michelin-de', 'michelin-cn',
                    'toyo-us', 'hankook-us', 'xiaomi-cn-vehicles', 'nhtsa-us-recalls', SOURCE}
ENDPOINT = f'/v1/sources/{SOURCE}/live-query'
QUERY20 = {'model': MODEL, 'size': '265/40R20'}
QUERY21 = {'model': MODEL, 'size': '265/40R21'}
PNCS_XL = [{'field': 'acoustic_technology', 'op': 'eq', 'value': 'PNCS'},
           {'field': 'xl', 'op': 'eq', 'value': True}]
ELECT_PNCS_NON_RUNFLAT = [
    {'field': 'ev_marketing_mark', 'op': 'eq', 'value': True},
    {'field': 'acoustic_technology', 'op': 'eq', 'value': 'PNCS'},
    {'field': 'run_flat', 'op': 'eq', 'value': False}]
EXPECTED20 = {
    '2524000': ('8019227252408', '265/40R20', '104', 'Y', 'AO', True, False, False),
    '4080500': ('8019227408058', '265/40R20', '104', 'Y', 'RE0', False, True, True),
    '4159300': ('8019227415933', '265/40ZR20', '104', 'W', 'MO1', True, True, False),
}
EXPECTED21 = {
    '2679200': ('8019227267921', '265/40ZR21', '105', '(Y)', 'B', True, False, False),
    '3768200': ('8019227376821', '265/40ZR21', '105', '(Y)', 'BL', True, False, False),
    '3791000': ('8019227379105', '265/40R21', '105', 'H', 'MO-S', True, True, False),
    '3973300': ('8019227397338', '265/40R21', '105', 'H', 'MO-S', True, True, False),
    '4059000': ('8019227405903', '265/40ZR21', '105', '(Y)', 'MGT1', False, False, False),
    '4188600': ('8019227418866', '265/40ZR21', '105', '(Y)', 'BH', True, True, False),
    '4193300': ('8019227419337', '265/40R21', '105', 'Y', 'LTS', True, True, False),
    '4220800': ('8019227422085', '265/40R21', '105', 'W', 'KRM', True, True, False),
}


def now():
    return datetime.now(UTC).isoformat()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                               default=str), encoding='utf-8')


def require(condition, code):
    if not condition:
        raise AssertionError(code)


class ObservedRegistry:
    """Observe the real registry; only the subsequent offline fault is synthetic."""
    supports_parser_deployments = True

    def __init__(self, output):
        self.output = output
        self.offline = False
        self.real = []
        self.product_attempts = 0
        self.injected_calls = 0

    @staticmethod
    def sources():
        return registry.sources()

    async def fetch(self, source_id, query, cached=None, *, on_observation=None, **kwargs):
        if self.offline:
            self.injected_calls += 1
            return {'status': 'unavailable', 'reason': 'explicit_pirelli_acceptance_offline'}
        if query.get('size'):
            self.product_attempts += 1
            require(self.product_attempts <= 5, 'real_product_attempt_limit_exceeded')
        entry = {'source_id': source_id, 'query': deepcopy(query), 'started_at': now(),
                 'cached_validators': {key: cached.get(key) if cached else None
                                       for key in ('etag', 'last_modified')},
                 'observations': [], 'transport': 'production_registry_fetch_unchanged'}
        self.real.append(entry)
        start = time.monotonic()

        def observe(observation):
            raw = observation['body'].encode('utf-8')
            entry['observations'].append({key: deepcopy(observation.get(key)) for key in
                                         ('url', 'content_type', 'parser_version', 'parser_identity')}
                                        | {'received_at': now(), 'byte_count': len(raw),
                                           'raw_sha256': hashlib.sha256(raw).hexdigest()})
            if on_observation is not None:
                on_observation(observation)
            received = self.output / 'real' / f'network-{len(self.real):02d}-received-{len(entry["observations"]):02d}.raw'
            received.parent.mkdir(parents=True, exist_ok=True)
            received.write_bytes(raw)
            entry['observations'][-1]['received_file'] = received.relative_to(self.output).as_posix()

        try:
            result = await registry.fetch(source_id, query, cached=cached,
                                          on_observation=observe, **kwargs)
            entry.update({key: deepcopy(result.get(key)) for key in
                          ('status', 'reason', 'url', 'content_type', 'etag', 'last_modified',
                           'parser_version', 'parser_identity', 'parser_error')})
            # SafeHttpClient admits only 200 for products; 304 has its own branch.
            # This is a status implied by the production result, not a wire trace.
            entry['product_http_status_from_registry_contract'] = (
                200 if result.get('status') == 'ok' or entry['observations'] else
                304 if result.get('status') == 'not_modified' else None)
            if entry['observations']:
                entry['url'] = entry.get('url') or entry['observations'][-1]['url']
                entry['content_type'] = entry.get('content_type') or entry['observations'][-1]['content_type']
            entry['parser_receipt'] = deepcopy(result.get('parser_receipt'))
            return result
        finally:
            entry.update(completed_at=now(), elapsed_ms=round((time.monotonic() - start) * 1000))
            origin = registry.SPECS[SOURCE].origin
            entry['origin_policy'] = {key: registry._states.get(origin, {}).get(key)
                                      for key in ('interval', 'failures', 'busy')}
            policy = registry._robots.get(origin)
            if policy:
                entry['current_robots'] = {'minimum_interval': policy[1].minimum_interval,
                    'rules': [{'allow': rule.allow, 'pattern': rule.pattern} for rule in policy[1].rules],
                    'requested_url_allowed': policy[1].can_fetch(entry['url']) if entry.get('url') else None}
            save_json(self.output / 'real' / f'network-{len(self.real):02d}.json', entry)


def api(client, output, label, method, path, payload=None, expected=200):
    response = client.request(method, path, json=payload) if payload is not None else client.request(method, path)
    try:
        body = response.json()
    except ValueError:
        body = {'non_json_response': True}
    save_json(output / f'{label}.json', {'path': path, 'method': method, 'request': payload,
        'http_status': response.status_code, 'received_at': now(), 'response': body})
    require(response.status_code == expected, f'{label}_unexpected_http_{response.status_code}')
    return body


def formal_fingerprints(database):
    with database.sessions() as db:
        return {model.__tablename__: sorted(digest({column.name: str(getattr(row, column.name))
                if isinstance(getattr(row, column.name), datetime) else getattr(row, column.name)
                for column in model.__table__.columns}) for row in db.scalars(select(model)))
                for model in (Snapshot, TireVariant, FactVersion, ChangeEvent)}


def model_ledger(database):
    with database.sessions() as db:
        return {'ai_requests': db.scalar(select(func.count()).select_from(AIRequest)),
                'embedding_requests': db.scalar(select(func.count()).select_from(EmbeddingRequest))}


def save_checkpoint(isolated, output, database, *, partial=False):
    """Keep this run's isolated evidence so an offline-only retry needs no network."""
    checkpoint = output / ('partial-checkpoint' if partial else 'checkpoint')
    checkpoint.mkdir()
    with closing(sqlite3.connect(isolated / 'acceptance.db')) as source_db:
        with closing(sqlite3.connect(checkpoint / 'acceptance.db')) as backup_db:
            source_db.backup(backup_db)
    for name in ('objects', 'bundles'):
        if (isolated / name).exists():
            shutil.copytree(isolated / name, checkpoint / name)
        else:
            (checkpoint / name).mkdir()
    save_json(checkpoint / 'metadata.json', {'created_at': now(),
        'scope': 'isolated_partial_real_acceptance_failure' if partial else 'isolated_real_acceptance_before_offline_fault',
        'formal_fingerprints': formal_fingerprints(database), 'model_ledger': model_ledger(database),
        'normal_database_used': False, 'source_id': SOURCE, 'query': QUERY20})
    return checkpoint.name


def wait_source_gap():
    state = registry._states.get(registry.SPECS[SOURCE].origin, {})
    interval, last = state.get('interval', 2.0), state.get('last', -float('inf'))
    require(type(interval) in (int, float) and math.isfinite(interval) and interval >= 0 and
            type(last) in (int, float) and (math.isfinite(last) or last == -math.inf),
            'invalid_source_wait')
    remaining = 0.0 if last == -math.inf else interval + 0.15 - (time.monotonic() - last)
    require(math.isfinite(remaining), 'invalid_source_wait')
    delay = max(0.0, remaining)
    require(math.isfinite(delay) and 0 <= delay <= 60, 'source_wait_exceeds_acceptance_window')
    if delay:
        time.sleep(delay)


def unavailable_without_history(row, state):
    require(row['data_state'] == state, f'expected_{state}')
    require(not row['variants'] and not row['provenance'] and not row['conflicts'], 'unauthorized_history_exposed')
    require(row['verified_at'] is None and row['snapshot_observed_at'] is None, 'unauthorized_snapshot_metadata')
    require(all(row['selection'][key] is None for key in
                ('source_count', 'matched_count', 'excluded_count', 'undetermined_count')), 'unauthorized_counts_exposed')


def validate_rows(rows, expected):
    actual = {row['manufacturer_product_code']: row for row in rows}
    require(len(actual) == len(rows) and set(actual) == set(expected), 'official_sku_set_changed_manual_review_required')
    for code, values in expected.items():
        row, facts = actual[code], actual[code]['facts']
        gtin, size, load, speed, oe, pncs, elect, run_flat = values
        require((row['brand'], row['model'], row['region']) == ('Pirelli', MODEL, 'US'), 'brand_model_region_mismatch')
        require((facts.get('gtin'), row['size'], row['load_index'], row['speed_rating'], row['oe_mark']) ==
                (gtin, size, load, speed, oe), f'official_identity_mismatch_{code}')
        require(row['xl'] is True and row['hl'] is None, f'load_class_mismatch_{code}')
        require(row['run_flat'] is run_flat, f'run_flat_mismatch_{code}')
        require((row['acoustic_technology'] == 'PNCS') is pncs, f'pncs_mismatch_{code}')
        require(facts.get('pncs') is pncs and facts.get('elect') is elect and
                facts.get('ev_marketing_mark') is elect, f'official_technology_flags_mismatch_{code}')
        require(facts.get('construction') == ('ZR' if 'ZR' in size else 'R'), f'construction_mismatch_{code}')
        features = facts.get('technology_features', [])
        require(('PNCS' in features) is pncs and ('ELECT' in features) is elect and
                ('RUNFLAT' in features) is run_flat, f'official_technology_features_mismatch_{code}')
        components = facts.get('source_utqg_components', {})
        require(facts.get('source_utqg_raw') in {'220/A/AA', '280/A/AA'} and
                components.get('temperature') == 'AA' and components.get('traction') == 'A' and
                any(item.get('field') == 'utqg_temperature' and item.get('raw_value') == 'AA' and
                    item.get('reason') == 'source_temperature_outside_standard_enum'
                    for item in facts.get('source_field_anomalies', [])), f'source_utqg_anomaly_lost_{code}')
        require(all(facts.get(key) is None for key in
                    ('utqg_treadwear', 'utqg_traction', 'utqg_temperature')), f'noncanonical_utqg_adopted_{code}')
    return actual


def live_evidence(client, app, output, label, row, query):
    execution = api(client, output, label + '-execution', 'GET',
                    f'/v1/parser-executions/{row["query_id"]}?mode=history')
    completion = execution['completion']
    require(completion is not None, 'parser_execution_missing')
    if row['data_state'] == 'live_verified_304':
        require(completion['state'] == 'not_modified' and completion['receipt'] == {},
                '304_invented_parser_receipt')
        with app.state.database.sessions() as db:
            completed = db.get(ParserExecution, row['query_id'])
            require(completed is not None and completed.state == 'not_modified' and completed.receipt == {},
                    '304_invented_durable_parser_receipt')
            require(db.scalar(select(RawCapture).where(RawCapture.query_id == row['query_id'])) is None,
                    '304_invented_raw_capture')
        return {'execution': execution, 'capture': None}
    require(completion['state'] == 'completed', 'real_parser_not_completed')
    receipt = completion['receipt']
    require(receipt['exit_code'] == 0 and receipt['reaped'] is True and receipt['pid'] > 0, 'parser_child_not_reaped')
    require(receipt['limits']['wall_seconds'] == 8 and receipt['limits']['max_concurrent'] == 2,
            'production_parser_limits_changed')
    identity = row['provenance'][0]['parser_identity']
    require(receipt['bundle_id'] == identity['bundle_id'] and receipt['deployment_revision'] == 1,
            'parser_receipt_deployment_mismatch')
    with app.state.database.sessions() as db:
        run = db.get(QueryRun, row['query_id'])
        completed = db.get(ParserExecution, row['query_id'])
        capture = db.scalar(select(RawCapture).where(RawCapture.query_id == row['query_id']))
        snapshot = db.get(Snapshot, row['provenance'][0]['snapshot_id'])
        require(completed.state == 'completed' and completed.receipt == receipt and capture is not None,
                'durable_receipt_or_capture_missing')
        body, storage = checked_capture_bytes(db, capture)
        require(storage == 'object_store', 'capture_not_in_independent_object_store')
        mapping = db.get(CaptureObject, capture.id)
        obj = db.get(EvidenceObject, mapping.raw_hash) if mapping else None
        raw_hash = hashlib.sha256(body).hexdigest()
        require(obj is not None and obj.byte_count == len(body) and obj.raw_hash == raw_hash == capture.raw_hash ==
                snapshot.raw_hash == row['provenance'][0]['raw_hash'], 'capture_object_snapshot_hash_mismatch')
        require(capture.parser_identity == snapshot.parser_identity == identity, 'capture_parser_pin_mismatch')
        require(run.query == query and run.query_key == capture.query_key == snapshot.query_key == digest(query) and
                run.source_id == capture.source_id == snapshot.source_id == SOURCE and
                run.selection_filters == row['selection']['filters'], 'acquisition_query_identity_mismatch')
        require(receipt['input_hash'] == input_hash({**receipt, 'query': query}, body), 'receipt_input_hash_mismatch')
        require(len(snapshot.parsed_variants) == row['selection']['source_count'], 'filtered_snapshot_lost_rows')
        capture_id = capture.id
        save_json(output / f'{label}-object.json', {'capture_id': capture.id, 'snapshot_id': snapshot.id,
            'raw_hash': raw_hash, 'byte_count': len(body), 'storage_kind': storage,
            'object_hash': obj.raw_hash, 'query_key': capture.query_key,
            'parser_identity': identity, 'snapshot_source_count': len(snapshot.parsed_variants)})
        (output / f'{label}.raw').write_bytes(body)
    captured = api(client, output, label + '-capture', 'GET', f'/v1/captures/{capture_id}?mode=history')
    evidence = api(client, output, label + '-evidence', 'GET', f'/v1/evidence/{row["provenance"][0]["snapshot_id"]}')
    require(hashlib.sha256(captured['body'].encode()).hexdigest() == raw_hash ==
            hashlib.sha256(evidence['body'].encode()).hexdigest(), 'evidence_api_hash_mismatch')
    return {'execution': execution, 'capture': {key: captured[key] for key in
            ('id', 'raw_hash', 'byte_count', 'storage_kind', 'parser_identity')}}


def offline_checks(client, app, source, output, report):
    report['step'] = 'explicit_offline_fault_injection'
    report['fault_injected']['status'] = 'running'
    source.offline = True
    baseline = formal_fingerprints(app.state.database)
    save_json(output / 'fault-injected' / 'formal-before.json', baseline)
    payload = {'query': QUERY20, 'filters': PNCS_XL, 'fallback_policy': 'ask'}
    pending = api(client, output / 'fault-injected', 'unanswered', 'POST', ENDPOINT, payload)
    unavailable_without_history(pending, 'consent_required')
    denied = api(client, output / 'fault-injected', 'deny', 'POST', '/v1/fallback-consents',
                 {'query_id': pending['query_id'], 'decision': 'deny'}, 201)
    api(client, output / 'fault-injected', 'denied-replay', 'POST', ENDPOINT,
        {**payload, 'consent_id': denied['id']}, 403)
    never = api(client, output / 'fault-injected', 'never', 'POST', ENDPOINT,
                {**payload, 'fallback_policy': 'never'})
    unavailable_without_history(never, 'source_unavailable')
    pending2 = api(client, output / 'fault-injected', 'allow-pending', 'POST', ENDPOINT, payload)
    unavailable_without_history(pending2, 'consent_required')
    grant = api(client, output / 'fault-injected', 'allow', 'POST', '/v1/fallback-consents',
                {'query_id': pending2['query_id'], 'decision': 'allow'}, 201)
    for label, path, changed in [
            ('changed-filter', ENDPOINT, {**payload, 'filters': []}),
            ('changed-query', ENDPOINT, {**payload, 'query': QUERY21}),
            ('changed-policy', ENDPOINT, {**payload, 'fallback_policy': 'never'}),
            ('changed-source', '/v1/sources/hankook-us/live-query', payload)]:
        api(client, output / 'fault-injected', label, 'POST', path,
            {**changed, 'consent_id': grant['id']}, 403)
    # A separate cookie jar creates a real second local API session.
    other = TestClient(app)
    try:
        api(other, output / 'fault-injected', 'changed-session', 'POST', ENDPOINT,
            {**payload, 'consent_id': grant['id']}, 403)
    finally:
        other.close()
    with app.state.database.sessions() as db:
        require(db.get(FallbackConsent, grant['id']).used_at is None, 'mismatch_consumed_permit')
    local = api(client, output / 'fault-injected', 'allowed-reordered-filters', 'POST', ENDPOINT,
                {**payload, 'filters': list(reversed(PNCS_XL)), 'consent_id': grant['id']})
    require(local['data_state'] == 'local_snapshot' and
            {row['manufacturer_product_code'] for row in local['variants']} == {'2524000', '4159300'} and
            local['selection']['source_count'] == 3 and local['selection']['matched_count'] == 2,
            'authorized_local_filter_projection_mismatch')
    api(client, output / 'fault-injected', 'single-use-replay', 'POST', ENDPOINT,
        {**payload, 'consent_id': grant['id']}, 409)
    after = formal_fingerprints(app.state.database)
    save_json(output / 'fault-injected' / 'formal-after.json', after)
    require(after == baseline, 'injected_fault_changed_formal_fingerprints')
    report['fault_injected']['checks'].extend([
        'unanswered_denied_and_never_expose_no_variants_counts_or_provenance',
        'permit_bound_to_source_query_filters_policy_session_and_order_canonicalization',
        'permit_single_use_and_formal_snapshot_variant_fact_change_fingerprints_unchanged'])
    report['fault_injected']['status'] = 'passed'


def run(output, report):
    with tempfile.TemporaryDirectory(prefix='tire-pirelli-real-') as directory:
        isolated = Path(directory)
        settings = {'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0',
                    'TIRE_DATABASE_URL': 'sqlite:///' + (isolated / 'acceptance.db').as_posix(),
                    'DATABASE_URL': 'sqlite:///' + (isolated / 'acceptance.db').as_posix(),
                    'TI_PARSER_BUNDLE_ROOT': str(isolated / 'bundles'),
                    'TI_OBJECT_STORE_BACKEND': 'filesystem', 'TI_OBJECT_STORE_ROOT': str(isolated / 'objects')}
        with patch.dict(os.environ, settings):
            from tire_api.main import create_app
            source = ObservedRegistry(output)
            app = create_app('sqlite:///' + (isolated / 'acceptance.db').as_posix(), source)
            try:
                with TestClient(app) as client:
                    report['step'] = 'metadata_and_missing_size'
                    metadata = api(client, output / 'real', 'sources', 'GET', '/v1/sources')
                    public = next(row for row in metadata['sources'] if row['id'] == SOURCE)
                    require(public['status'] == 'ready' and public.get('requires_size') is True and
                            MODEL in public['supported_models'], 'pirelli_source_metadata_incomplete')
                    origin = registry.SPECS[SOURCE].origin
                    before = (registry._robots_requests.get(origin), deepcopy(registry._states.get(origin)))
                    missing = api(client, output / 'real', 'missing-size', 'POST', ENDPOINT,
                                  {'query': {'model': MODEL}, 'fallback_policy': 'never'})
                    unavailable_without_history(missing, 'source_unavailable')
                    require(missing['reason'] == 'source_size_required', 'missing_size_reason_not_explicit')
                    api(client, output / 'real', 'missing-size-execution', 'GET',
                        f'/v1/parser-executions/{missing["query_id"]}?mode=history')
                    require(not source.real[-1]['observations'] and before[0] == registry._robots_requests.get(origin),
                            'missing_size_sent_upstream')
                    require(registry._states.get(origin, {}).get('last', -float('inf')) ==
                            (before[1] or {}).get('last', -float('inf')), 'missing_size_sent_product_request')
                    report['real']['checks'].append('requires_size_metadata_and_missing_size_without_upstream')
                    results = []
                    for label, query, filters, expected_codes, source_count, undetermined_count in [
                            ('20-full', QUERY20, [], set(EXPECTED20), 3, 0),
                            # No PNCS name is an unknown text attribute, while facts.pncs is false.
                            ('20-pncs-xl', QUERY20, PNCS_XL, {'2524000', '4159300'}, 3, 1),
                            ('20-elect-pncs-non-runflat', QUERY20, ELECT_PNCS_NON_RUNFLAT, {'4159300'}, 3, 0),
                            ('21-full', QUERY21, [], set(EXPECTED21), 8, 0)]:
                        report['step'] = 'real_' + label
                        wait_source_gap()
                        row = api(client, output / 'real', label, 'POST', ENDPOINT,
                                  {'query': query, 'filters': filters, 'fallback_policy': 'ask'})
                        # Record execution before checking contract drift, preserving failure evidence.
                        if row['data_state'] not in {'live', 'live_verified_304'}:
                            failed = api(client, output / 'real', label + '-execution', 'GET',
                                         f'/v1/parser-executions/{row["query_id"]}?mode=history')
                            completion = failed.get('completion') or {}
                            error_code = completion.get('error_code') or row.get('reason') or 'source_unavailable'
                            report['real']['failure'] = {'label': label, 'query_id': row['query_id'],
                                'api_state': row['data_state'], 'api_reason': row.get('reason'),
                                'parser_execution_state': completion.get('state'),
                                'parser_error_code': completion.get('error_code'),
                                'receipt': completion.get('receipt'),
                                'boundary': 'An API parser_schema_changed reason alone does not prove source contract drift.'}
                            with app.state.database.sessions() as db:
                                rejected_capture = db.scalar(select(RawCapture).where(RawCapture.query_id == row['query_id']))
                                capture_id = rejected_capture.id if rejected_capture else None
                            if capture_id:
                                api(client, output / 'real', label + '-received-capture', 'GET',
                                    f'/v1/captures/{capture_id}?mode=history')
                            require(False, f'{label}_real_source_failed_{error_code}')
                        proofs = live_evidence(client, app, output / 'real', label, row, query)
                        require(row['selection']['source_count'] == source_count and
                                row['selection']['matched_count'] == len(expected_codes) and
                                row['selection']['undetermined_count'] == undetermined_count and
                                row['selection']['excluded_count'] == source_count - len(expected_codes) - undetermined_count,
                                f'{label}_selection_mismatch')
                        require({v['manufacturer_product_code'] for v in row['variants']} == expected_codes,
                                f'{label}_official_sku_set_changed_manual_review_required')
                        if label == '20-full':
                            validate_rows(row['variants'], EXPECTED20)
                        if label == '21-full':
                            validate_rows(row['variants'], EXPECTED21)
                        results.append(row)
                        report['real']['observations'].append({'label': label, 'query_id': row['query_id'],
                            'data_state': row['data_state'], 'selection': row['selection'],
                            'provenance': row['provenance'], 'product_codes': sorted(expected_codes), **proofs})
                        report['real']['checks'].append(label + '_real_production_api_parser_and_evidence')
                    deployment = api(client, output / 'real', 'deployment', 'GET',
                                     f'/v1/parser-deployments/{SOURCE}?mode=history')
                    bundle = api(client, output / 'real', 'bundle', 'GET',
                                 f'/v1/parser-bundles/{deployment["bundle_id"]}?mode=history')
                    require(deployment['state'] == 'active' and deployment['revision'] == 1 and
                            len(bundle['parsers']) == 10 and {p['source_id'] for p in bundle['parsers']} == EXPECTED_CATALOG,
                            'new_source_not_initial_revision_one_complete_ten_source_bundle')
                    with app.state.database.sessions() as db:
                        sealed = db.get(ParserBundle, deployment['bundle_id'])
                        require('adapters/pirelli.py' in sealed.manifest['files'], 'sealed_adapter_missing')
                        save_json(output / 'real' / 'bundle-manifest.json', sealed.manifest)
                        require(db.scalar(select(func.count()).select_from(TireVariant)) == 11,
                                'same_size_skus_merged_or_formal_adoption_incomplete')
                    report['real']['checks'].append('initial_active_revision_one_and_complete_ten_source_bundle')
                    # The second 20-inch request uses the same acquisition identity and
                    # existing transport cache; filters do not replace acquisition scope.
                    second_network = source.real[2]
                    report['real']['reverification'] = {'data_state': results[1]['data_state'],
                        'product_http_status_from_registry_contract': second_network['product_http_status_from_registry_contract'],
                        'cached_validators': second_network['cached_validators'],
                        'returned_validators': {key: second_network.get(key) for key in ('etag', 'last_modified')},
                        'actual_304_observed': results[1]['data_state'] == 'live_verified_304',
                        'boundary': 'No validator means a new 200 fetch; no claim that the real 304 branch passed.'}
                    report['step'] = 'formal_historical_comparison_and_lexical_search'
                    ids = [row['id'] for row in results[0]['variants']]
                    before_history = formal_fingerprints(app.state.database)
                    comparison = api(client, output / 'real', 'comparison', 'POST', '/v1/compare', {'variant_ids': ids})
                    require(comparison['data_state'] == 'local_snapshot' and
                            {row['id'] for row in comparison['variants']} == set(ids) and
                            all(row['source_id'] == SOURCE for row in comparison['provenance']), 'formal_compare_missing_source_evidence')
                    history = api(client, output / 'real', 'lexical-history', 'POST', '/v1/knowledge/search',
                                  {'mode': 'history', 'text': 'P ZERO', 'filters': {'kind': 'tire',
                                   'source_id': SOURCE, 'brand': 'Pirelli'}, 'limit': 30})
                    require(history['data_state'] == 'local_snapshot' and history['total'] == 11 and
                            {item['reference']['variant_id'] for item in history['items']} ==
                            {row['id'] for row in results[0]['variants'] + results[3]['variants']} and
                            all(item['source_id'] == SOURCE for item in history['items']) and
                            any(stage['name'] == 'fts' and stage['state'] == 'succeeded' for stage in history['stages']),
                            'formal_source_brand_lexical_history_mismatch')
                    excluded = api(client, output / 'real', 'history-other-brand', 'POST', '/v1/knowledge/search',
                                   {'mode': 'history', 'text': 'P ZERO', 'filters': {'source_id': SOURCE,
                                    'brand': 'Michelin'}, 'limit': 30})
                    require(excluded['total'] == 0 and not excluded['items'], 'history_brand_filter_not_applied')
                    require(formal_fingerprints(app.state.database) == before_history, 'historical_reads_changed_formal_evidence')
                    report['real']['checks'].append('formal_comparison_and_source_brand_filtered_lexical_history')
                    report['real']['status'] = 'passed'
                    report['step'] = 'save_real_checkpoint'
                    report['checkpoint'] = save_checkpoint(isolated, output, app.state.database)
                    offline_checks(client, app, source, output, report)
                    require(model_ledger(app.state.database) == {'ai_requests': 0, 'embedding_requests': 0}, 'model_ledger_nonzero')
                    report['checks'].append('actual_ai_and_embedding_ledgers_zero')
            finally:
                if source.product_attempts and report['real']['status'] != 'passed':
                    report['partial_checkpoint'] = save_checkpoint(isolated, output, app.state.database, partial=True)
                report['real_registry_calls'] = len(source.real)
                report['real_product_attempts'] = source.product_attempts
                report['real_product_results'] = sum(entry.get('product_http_status_from_registry_contract') is not None
                                                     for entry in source.real)
                report['fault_injected']['registry_calls'] = source.injected_calls
                report['model_ledger'] = model_ledger(app.state.database)
                save_json(output / 'real' / 'network-observations.json', source.real)
                app.state.database.close()


def resume_faults(checkpoint, output, report, *, partial=False):
    """Restore an actual isolated checkpoint; this mode makes zero source requests."""
    metadata = json.loads((checkpoint / 'metadata.json').read_text(encoding='utf-8'))
    expected_scope = 'isolated_partial_real_acceptance_failure' if partial else 'isolated_real_acceptance_before_offline_fault'
    require(metadata['scope'] == expected_scope and
            metadata['normal_database_used'] is False and metadata['source_id'] == SOURCE,
            'invalid_offline_checkpoint_scope')
    if partial:
        original_path = checkpoint.parent / 'acceptance.json'
        original = json.loads(original_path.read_text(encoding='utf-8'))
        require(original['status'] == 'failed' and original['real']['status'] == 'failed' and
                '20-full_real_production_api_parser_and_evidence' in original['real']['checks'],
                'partial_checkpoint_has_no_successful_actual_20_scope')
        report['real'] = deepcopy(original['real'])
        report['source_acceptance_report'] = str(original_path)
        report['scoped_faults'] = {'status': 'running', 'query': QUERY20, 'checks': [],
            'scope': 'restored_successfully_adopted_20_inch_actual_evidence_only',
            'unverified': ['265/40R21 eight-SKU scope', '11-item lexical history', 'complete real acceptance']}
    with tempfile.TemporaryDirectory(prefix='tire-pirelli-offline-resume-') as directory:
        isolated = Path(directory)
        with closing(sqlite3.connect(checkpoint / 'acceptance.db')) as source_db:
            with closing(sqlite3.connect(isolated / 'acceptance.db')) as restored_db:
                source_db.backup(restored_db)
        for name in ('objects', 'bundles'):
            shutil.copytree(checkpoint / name, isolated / name)
        with patch.dict(os.environ, {'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0',
                'TIRE_DATABASE_URL': 'sqlite:///' + (isolated / 'acceptance.db').as_posix(),
                'DATABASE_URL': 'sqlite:///' + (isolated / 'acceptance.db').as_posix(),
                'TI_PARSER_BUNDLE_ROOT': str(isolated / 'bundles'), 'TI_OBJECT_STORE_BACKEND': 'filesystem',
                'TI_OBJECT_STORE_ROOT': str(isolated / 'objects')}):
            from tire_api.main import create_app
            source = ObservedRegistry(output)
            source.offline = True
            app = create_app('sqlite:///' + (isolated / 'acceptance.db').as_posix(), source)
            if not partial:
                report['real']['status'] = 'not_run'
            report['scope'] = ('actual_partial_checkpoint_20_only_offline_faults_real_still_failed' if partial else
                               'explicit_offline_fault_from_actual_live_checkpoint_no_source_requests')
            report['fault_injected']['setup'] = 'restore_actual_isolated_checkpoint_without_new_transport_or_parser'
            if partial:
                report['fault_injected']['query'] = QUERY20
                report['boundaries'][0] = 'Only successfully adopted 265/40R20 scope is restored; 265/40R21 and 11-item lexical history were not verified in this partial run.'
            try:
                with TestClient(app) as client:
                    require(formal_fingerprints(app.state.database) == metadata['formal_fingerprints'],
                            'restored_formal_checkpoint_mismatch')
                    offline_checks(client, app, source, output, report)
                    require(model_ledger(app.state.database) == {'ai_requests': 0, 'embedding_requests': 0},
                            'model_ledger_nonzero')
                    report['checks'].append('actual_ai_and_embedding_ledgers_zero')
                    require(not source.real and source.product_attempts == 0, 'offline_restore_sent_upstream')
                    if partial:
                        report['scoped_faults'].update(status='passed', checks=list(report['fault_injected']['checks']))
            finally:
                report['real_registry_calls'] = len(source.real)
                report['real_product_attempts'] = source.product_attempts
                report['real_product_results'] = 0
                report['fault_injected']['registry_calls'] = source.injected_calls
                report['model_ledger'] = model_ledger(app.state.database)
                app.state.database.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--live', action='store_true', help='Opt in to actual public Pirelli requests.')
    mode.add_argument('--faults-only', type=Path, help='Resume only offline checks from an actual isolated checkpoint.')
    mode.add_argument('--partial-checkpoint', type=Path,
                      help='Check only adopted 20-inch offline scope from a failed actual checkpoint; real remains failed.')
    parser.add_argument('--output', type=Path, help='New report directory inside .artifacts/pirelli/round31-live.')
    args = parser.parse_args()
    base = (ROOT / '.artifacts/pirelli/round31-live').resolve()
    partial = args.partial_checkpoint is not None
    selected_checkpoint = args.partial_checkpoint or args.faults_only
    checkpoint = selected_checkpoint.resolve() if selected_checkpoint else None
    expected_name = 'partial-checkpoint' if partial else 'checkpoint'
    if checkpoint is not None and (not checkpoint.is_relative_to(base) or checkpoint.name != expected_name):
        parser.error('The selected checkpoint must be an isolated checkpoint inside .artifacts/pirelli/round31-live')
    output = args.output.resolve() if args.output else base / ('run-' + uuid4().hex)
    if not output.is_relative_to(base) or output == base:
        parser.error('--output must be a new child directory of .artifacts/pirelli/round31-live')
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'started_at': now(), 'step': 'initialize', 'checks': [],
        'scope': 'local_single_user_poc_real_pirelli_then_explicit_offline_fault',
        'isolation': 'independent_temporary_sqlite_objects_bundles_never_normal_database',
        'settings': {'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0'},
        'real': {'status': 'not_completed', 'checks': [], 'observations': []},
        'fault_injected': {'status': 'not_run', 'checks': []},
        'boundaries': ['Only P ZERO (PZ4) 265/40R20 and 265/40R21 source response sets are checked.',
            'This is source-contract acceptance, not a human Golden Set or commercial redistribution permission.',
            'Production transport does not expose wire headers, redirect-hop or retry counts; network metadata is registry-level.',
            'Raw bytes are the production capture UTF-8 bytes, hash-checked against the evidence object and parser input.',
            'No model, credentials, normal database, browser, device or production deployment acceptance.']}
    try:
        if checkpoint is not None:
            resume_faults(checkpoint, output, report, partial=partial)
        else:
            run(output, report)
        report['status'] = 'failed' if partial else 'passed'
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__)
        if report['real']['status'] == 'not_completed':
            report['real']['status'] = 'failed'
        if report['fault_injected']['status'] == 'running':
            report['fault_injected']['status'] = 'failed'
        if report.get('scoped_faults', {}).get('status') == 'running':
            report['scoped_faults']['status'] = 'failed'
        if isinstance(error, AssertionError):
            report['error_code'] = str(error)
        raise
    finally:
        report['completed_at'] = now()
        save_json(output / 'acceptance.json', report)
        print(json.dumps({'status': report['status'], 'step': report['step'],
                          'report': str(output / 'acceptance.json'),
                          'real_status': report['real']['status'],
                          'scoped_faults_status': report.get('scoped_faults', {}).get('status'),
                          'real': report['real']['checks'], 'fault_injected': report['fault_injected']['checks']},
                         ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
