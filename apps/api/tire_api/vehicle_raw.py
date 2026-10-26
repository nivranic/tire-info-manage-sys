"""Vehicle-only raw integrity and frozen mapping identity; no ingestion or routes.

Capture checks deliberately do not imply successful parsing. Structured binary
evidence additionally requires the historical registered execution and mapping.
These helpers do not commit, repair history, consult current deployments, or
execute archived source. Caller authorization and adoption locks remain external.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from functools import wraps
import hashlib
import re
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import CaptureObject, EvidenceObject, QueryRun, RawCapture, RejectedObservation
from .domain import digest
from .parser_release_models import ParserBundle, ParserDeploymentRevision, ParserExecution, ParserSelection

SOURCE_ID = 'xiaomi-cn-vehicles'
CURRENT_ID = 'xiaomi-su7-current'
FIRST_GENERATION_ID = 'xiaomi-su7-first-generation'
JSON_URL = 'https://website-api.xiaomiev.com/mtop/guidemarketing/product/pc/paramComparison'
PDF_URL = ('https://s1.xiaomiev.com/activity-outer-assets/0328/env/'
           'SU7%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E8%A1%A8.pdf')
MAX_BYTES = 8 * 1024 * 1024
SUPPORTED_RAW_SHA256 = '0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f'
SUPPORTED_BYTE_COUNT = 3240150
MAPPING_FILE = 'adapters/xiaomi_first_generation_pdf.py'
PARSE_METHOD = 'sha256_bound_reviewed_mapping'
PROVENANCE_KEYS = frozenset({'contract', 'method', 'mapping_id', 'source_raw_hash',
                             'bundle_id', 'mapping_file_sha256'})
_HASH = re.compile(r'[a-f0-9]{64}')


class VehicleRawIntegrityError(ValueError):
    """One fixed public failure; never retain received bodies, paths or SQL."""

    code = 'vehicle_raw_integrity_failed'

    def __init__(self):
        super().__init__(self.code)


def _require(condition):
    if not condition:
        raise VehicleRawIntegrityError()


def _closed(function):
    @wraps(function)
    def checked(db, *args, **kwargs):
        try:
            with db.no_autoflush:
                return function(db, *args, **kwargs)
        except VehicleRawIntegrityError:
            raise
        except Exception:
            raise VehicleRawIntegrityError() from None
    return checked


def _hash(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _identity(value):
    if value is None:
        return None
    _require(type(value) is dict and set(value) == {'bundle_id', 'parser_digest', 'deployment_revision'}
             and _hash(value['bundle_id']) and _hash(value['parser_digest'])
             and type(value['deployment_revision']) is int and value['deployment_revision'] > 0)
    return value


def _source(encoding, source, vehicle, url, mime):
    _require(source == SOURCE_ID and encoding in ('utf-8', 'binary'))
    if encoding == 'binary':
        _require(vehicle == FIRST_GENERATION_ID and url == PDF_URL and mime == 'application/pdf')
    else:
        _require(vehicle == CURRENT_ID and url == JSON_URL and mime == 'application/json')


def _raw(raw, raw_hash, encoding):
    _require(type(raw) is bytes and 1 <= len(raw) <= MAX_BYTES and _hash(raw_hash)
             and hashlib.sha256(raw).hexdigest() == raw_hash)
    if encoding == 'binary':
        _require(raw.startswith(b'%PDF-'))
    else:
        _require(encoding == 'utf-8')
        raw.decode('utf-8', errors='strict')
    return raw


def _query(db, capture):
    _require(type(capture) in (RawCapture, RejectedObservation) and capture.target_kind == 'vehicle')
    run = db.get(QueryRun, capture.query_id)
    _require(run is not None and type(run.query) is dict and set(run.query) == {'vehicle_id'}
             and type(run.query['vehicle_id']) is str and run.source_id == capture.source_id
             and run.query_key == capture.query_key == digest(run.query))
    _source(capture.body_encoding, capture.source_id, run.query['vehicle_id'],
            capture.source_url, capture.content_type)
    return run


def _selection_identity(db, run, parser_version, parser_identity):
    selected = db.get(ParserSelection, run.id)
    _require(selected is not None and selected.query_run_id == run.id and selected.source_id == run.source_id
             and type(selected.descriptor) is dict and selected.descriptor.get('source_id') == run.source_id
             and selected.descriptor.get('bundle_id') == selected.bundle_id
             and selected.descriptor.get('target_kind') == 'vehicle'
             and selected.descriptor.get('parser_version') == parser_version)
    expected = {'bundle_id': selected.bundle_id, 'parser_digest': selected.descriptor.get('parser_digest'),
                'deployment_revision': selected.deployment_revision}
    _require(_identity(expected) == _identity(parser_identity))
    return selected


def _capture_selection(db, capture, run):
    return _selection_identity(db, run, capture.parser_version, capture.parser_identity)


def _capture_bytes(db, capture):
    _require(type(capture) is RawCapture)
    run = _query(db, capture)
    _require(type(capture.byte_count) is int and 1 <= capture.byte_count <= MAX_BYTES
             and type(capture.raw_body) is bytes and len(capture.raw_body) == capture.byte_count
             and type(capture.parser_version) is str and 1 <= len(capture.parser_version) <= 100)
    _identity(capture.parser_identity)
    if capture.body_encoding == 'binary':
        _capture_selection(db, capture, run)
    # The retained DB original is checked too, but never substitutes for an
    # existing authoritative object or for the required binary object mapping.
    _raw(capture.raw_body, capture.raw_hash, capture.body_encoding)
    reference = db.get(CaptureObject, capture.id)
    if reference is None:
        _require(capture.body_encoding == 'utf-8')
        return capture.raw_body, run
    obj = db.get(EvidenceObject, reference.raw_hash)
    _require(reference.raw_hash == capture.raw_hash and obj is not None
             and obj.raw_hash == capture.raw_hash and type(obj.byte_count) is int
             and obj.byte_count == capture.byte_count)
    raw = db.info['object_store'].get(reference.raw_hash, capture.byte_count)
    _raw(raw, capture.raw_hash, capture.body_encoding)
    _require(len(raw) == capture.byte_count and raw == capture.raw_body)
    return raw, run


def _observation_capture(db, run, observation):
    _require(type(run) is QueryRun and type(observation) is dict)
    capture = db.scalar(select(RawCapture).where(RawCapture.query_id == run.id))
    _require(capture is not None)
    raw, stored_run = _capture_bytes(db, capture)
    _require(stored_run.id == run.id and stored_run.source_id == run.source_id
             and stored_run.query == run.query and stored_run.query_key == run.query_key)
    encoding = observation.get('body_encoding', 'utf-8')
    body = observation.get('body')
    _require(encoding == capture.body_encoding)
    if encoding == 'utf-8':
        _require(type(body) is str and bool(body))
        body = body.encode('utf-8', errors='strict')
    else:
        _require(type(body) is bytes)
    _require(body == raw and observation.get('url') == capture.source_url
             and observation.get('content_type') == capture.content_type
             and observation.get('parser_version') == capture.parser_version
             and _identity(observation.get('parser_identity')) == capture.parser_identity)
    return capture, raw, stored_run


def _mapping_literals(path, expected):
    from .parser_bundles import _plain_path
    with _plain_path(path, directory=False).open('rb') as source:
        data = source.read(expected['byte_count'] + 1)
    _require(len(data) == expected['byte_count'] and hashlib.sha256(data).hexdigest() == expected['sha256'])
    wanted = {'PARSE_METHOD', 'MAPPING_ID', 'REVIEWED_RAW_SHA256', 'REVIEWED_BYTE_COUNT'}
    values = {}
    tree = ast.parse(data)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in wanted:
                _require(name not in values)
                values[name] = ast.literal_eval(node.value)
    _require(set(values) == wanted and values['PARSE_METHOD'] == PARSE_METHOD
             and type(values['MAPPING_ID']) is str
             and re.fullmatch(r'xiaomi-su7-first-generation-pdf@[1-9][0-9]{0,8}', values['MAPPING_ID'])
             and values['REVIEWED_RAW_SHA256'] == SUPPORTED_RAW_SHA256
             and type(values['REVIEWED_BYTE_COUNT']) is int
             and values['REVIEWED_BYTE_COUNT'] == SUPPORTED_BYTE_COUNT)
    # Reject duplicate/rebound declarations, including annotated or conditional
    # writes; only the four literal module assignments above are supported.
    for name in wanted:
        _require(sum(isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == name
                     for node in ast.walk(tree)) == 1)
    return values


def _completed_provenance(db, capture, raw, run):
    _require(capture.body_encoding == 'binary' and capture.raw_hash == SUPPORTED_RAW_SHA256
             and len(raw) == SUPPORTED_BYTE_COUNT)
    selected = _capture_selection(db, capture, run)
    registered = db.get(ParserBundle, selected.bundle_id)
    deployment = db.get(ParserDeploymentRevision, selected.deployment_id)
    _require(registered is not None and registered.id == selected.bundle_id
             and deployment is not None and deployment.source_id == selected.source_id
             and deployment.bundle_id == selected.bundle_id and deployment.revision == selected.deployment_revision
             and type(deployment.revision) is int and deployment.state == 'active'
             and type(selected.deployment_revision) is int
             and selected.deployment_revision > 0)
    from .parser_releases import RECEIPT_FIELDS, get_bundle_manifest
    from .parser_bundles import verify_bundle
    manifest = get_bundle_manifest(db, selected.bundle_id)
    verified = verify_bundle(manifest)
    entry = manifest['parsers'][SOURCE_ID]
    _require(entry['target_kind'] == 'vehicle')
    parser_digest = digest({'bundle_id': selected.bundle_id, 'source_id': SOURCE_ID, **entry})
    stable = {'source_id': SOURCE_ID, 'bundle_id': selected.bundle_id, 'parser_digest': parser_digest,
              'parser_version': entry['parser_version'], 'target_kind': 'vehicle'}
    for descriptor in (selected.descriptor, deployment.descriptor, registered.descriptors[SOURCE_ID]):
        _require(type(descriptor) is dict and all(descriptor.get(k) == v for k, v in stable.items()))
    expected_identity = {'bundle_id': selected.bundle_id, 'parser_digest': parser_digest,
                         'deployment_revision': selected.deployment_revision}
    _require(_identity(capture.parser_identity) == expected_identity
             and capture.parser_version == entry['parser_version'])
    execution_digest = selected.descriptor.get('execution_digest', parser_digest)
    _require(_hash(execution_digest))
    selection = {'source_id': selected.source_id, 'query_run_id': run.id, 'bundle_id': selected.bundle_id,
                 'deployment_revision': selected.deployment_revision, 'parser_version': entry['parser_version'],
                 'parser_digest': parser_digest, 'execution_digest': execution_digest}
    execution = db.get(ParserExecution, run.id)
    _require(execution is not None and execution.state == 'completed' and execution.error_code is None
             and type(execution.receipt) is dict)
    receipt = execution.receipt
    _require(set(receipt) <= RECEIPT_FIELDS
             and all(receipt.get(key) == value for key, value in selection.items() if key != 'query_run_id')
             and type(receipt.get('deployment_revision')) is int
             and type(receipt.get('run_id')) is str and re.fullmatch(r'[a-f0-9]{32}', receipt['run_id'])
             and type(receipt.get('exit_code')) is int and receipt['exit_code'] == 0
             and receipt.get('reaped') is True)
    expected_input = digest({key: receipt[key] for key in ('run_id', 'source_id', 'parser_version',
        'parser_digest', 'bundle_id', 'execution_digest', 'deployment_revision')}
        | {'query': run.query, 'raw_sha256': capture.raw_hash})
    _require(receipt.get('input_hash') == expected_input and execution.fingerprint
             == digest({'selection': selection, 'state': 'completed', 'error_code': None, 'receipt': receipt}))
    provenance = _mapping_provenance(manifest, verified, capture.raw_hash)
    return provenance, selection, manifest, receipt


def _kind(row):
    from .vehicles import VehicleQuarantine, VehicleSnapshot
    _require(type(row) in (VehicleSnapshot, VehicleQuarantine, RawCapture, RejectedObservation))
    return ('snapshot' if type(row) is VehicleSnapshot else 'quarantine' if type(row) is VehicleQuarantine
            else 'capture' if type(row) is RawCapture else 'rejected')


def _payload_identity(payload, expected):
    _require(type(payload) is dict and type(payload.get('vehicle')) is dict
             and payload['vehicle'].get('id') == FIRST_GENERATION_ID
             and payload['vehicle'].get('source_version') == 'pdf-sha256:' + SUPPORTED_RAW_SHA256
             and payload.get('parse_method') == expected['method']
             and payload.get('mapping_id') == expected['mapping_id'])


def _row_data(db, row):
    kind = _kind(row)
    if kind == 'capture':
        raw, _ = _capture_bytes(db, row)
        return raw, row, None
    if kind == 'rejected':
        capture = db.scalar(select(RawCapture).where(RawCapture.query_id == row.query_id))
        if capture is None:
            _require(row.body_encoding == 'utf-8' and type(row.parser_version) is str
                     and 1 <= len(row.parser_version) <= 100)
            _query(db, row)
            _identity(row.parser_identity)
            return _raw(row.raw_body, row.raw_hash, 'utf-8'), None, None
        _require(row.target_kind == 'vehicle')
        raw, _ = _capture_bytes(db, capture)
        _require(all(getattr(row, key) == getattr(capture, key) for key in
                     ('source_id', 'query_key', 'target_kind', 'source_url', 'raw_hash', 'body_encoding',
                      'content_type', 'parser_version', 'parser_identity')) and type(row.raw_body) is bytes
                 and row.raw_body == raw)
        return raw, capture, None
    _source(row.body_encoding, row.source_id, row.vehicle_id, row.source_url, row.content_type)
    _require(type(row.parser_version) is str and 1 <= len(row.parser_version) <= 100)
    _identity(row.parser_identity)
    if row.body_encoding == 'utf-8':
        _require(type(row.body) is str and bool(row.body))
        raw = _raw(row.body.encode('utf-8', errors='strict'), row.raw_hash, 'utf-8')
        if row.raw_capture_id is None:
            return raw, None, None
    else:
        _require(row.body is None and type(row.raw_capture_id) is str and bool(row.raw_capture_id))
    capture = db.get(RawCapture, row.raw_capture_id)
    _require(capture is not None)
    captured, run = _capture_bytes(db, capture)
    _require(run.query == {'vehicle_id': row.vehicle_id}
             and all(getattr(row, key) == getattr(capture, key) for key in
                     ('source_id', 'source_url', 'content_type', 'raw_hash', 'body_encoding',
                      'parser_version', 'parser_identity'))
             and (kind != 'quarantine' or capture.query_id == row.query_id))
    if row.body_encoding == 'utf-8':
        _require(raw == captured)
        return raw, capture, None
    expected, _, _, _ = _completed_provenance(db, capture, captured, run)
    _require(type(row.payload) is dict and type(row.payload.get('parse_provenance')) is dict
             and set(row.payload['parse_provenance']) == PROVENANCE_KEYS
             and row.payload['parse_provenance'] == expected)
    _payload_identity(row.payload, expected)
    return captured, capture, expected


def _mapping_provenance(manifest, verified, raw_hash):
    """One sealed mapping rule shared by online and historical executions."""
    _require(MAPPING_FILE in manifest['files'])
    file_pin = manifest['files'][MAPPING_FILE]
    values = _mapping_literals(verified['package_root'] / MAPPING_FILE, file_pin)
    return {'contract': 'vehicle-pdf-parse@1', 'method': values['PARSE_METHOD'],
            'mapping_id': values['MAPPING_ID'], 'source_raw_hash': raw_hash,
            'bundle_id': manifest['bundle_id'], 'mapping_file_sha256': file_pin['sha256']}


@_closed
def checked_vehicle_history_capture_bytes(db: Session, capture: RawCapture) -> tuple[bytes, str]:
    """Raw qualification only: a failed/absent original execution is allowed."""
    _require(type(capture) is RawCapture)
    capture = db.get(RawCapture, capture.id, populate_existing=True)
    db.get(QueryRun, capture.query_id, populate_existing=True)
    selected = db.get(ParserSelection, capture.query_id, populate_existing=True)
    reference = db.get(CaptureObject, capture.id, populate_existing=True)
    if reference is not None:
        db.get(EvidenceObject, reference.raw_hash, populate_existing=True)
    if selected is not None:
        db.get(ParserBundle, selected.bundle_id, populate_existing=True)
        db.get(ParserDeploymentRevision, selected.deployment_id, populate_existing=True)
        db.get(ParserExecution, capture.query_id, populate_existing=True)
    raw, _ = _capture_bytes(db, capture)
    return raw, 'object_store' if db.get(CaptureObject, capture.id) else 'database_legacy'


@_closed
def checked_vehicle_history_baseline(db: Session, snapshot, verification=None) -> None:
    """Require intact schema/facts and the exact formal verification's selection."""
    from .vehicles import (VehicleSnapshot, VehicleVerification, WheelFitmentSpecification,
                           fitment_fact_hash, validate_vehicle_structure)
    _require(type(snapshot) is VehicleSnapshot)
    snapshot = db.get(VehicleSnapshot, snapshot.id, populate_existing=True)
    if snapshot.raw_capture_id is not None:
        capture = db.get(RawCapture, snapshot.raw_capture_id, populate_existing=True)
        checked_vehicle_history_capture_bytes(db, capture)
    _row_data(db, snapshot)
    if verification is None:
        verification = db.scalar(select(VehicleVerification).where(
            VehicleVerification.snapshot_id == snapshot.id).order_by(
            VehicleVerification.verified_at.desc(), VehicleVerification.id.desc()).limit(1)
            .execution_options(populate_existing=True))
    _require(type(verification) is VehicleVerification and verification.snapshot_id == snapshot.id
             and verification.vehicle_id == snapshot.vehicle_id)
    run = db.get(QueryRun, verification.query_id, populate_existing=True)
    query = {'vehicle_id': snapshot.vehicle_id}
    _require(run is not None and run.source_id == snapshot.source_id and run.query == query
             and run.query_key == digest(query) and verification.parser_identity == snapshot.parser_identity)
    db.get(ParserSelection, run.id, populate_existing=True)
    _selection_identity(db, run, snapshot.parser_version, verification.parser_identity)
    payload = snapshot.payload
    _require(type(payload) is dict and payload['vehicle']['id'] == snapshot.vehicle_id
             and type(payload.get('fitments')) is list and 1 <= len(payload['fitments']) <= 100)
    fits = [WheelFitmentSpecification.model_validate(item).model_dump() for item in payload['fitments']]
    _require(len({item['id'] for item in fits}) == len(fits))
    trim_ids = {item['id'] for item in payload['trims']}
    _require(all(item['trim_id'] in trim_ids for item in fits))
    validate_vehicle_structure(payload, fits)
    _require(fitment_fact_hash(payload) == snapshot.fact_hash)


@_closed
def build_vehicle_history_parse_provenance(db: Session, *, source_input: dict, raw: bytes,
        payload: dict, bundle_manifest: dict, receipt: dict, deployment_revision: int | None) -> dict:
    """Attest this historical child; never reuse the capture's online execution."""
    _require(source_input.get('body_encoding') == 'binary'
             and source_input.get('original_mapping_status') == 'not_attested'
             and type(payload) is dict and 'parse_provenance' not in payload)
    capture = db.get(RawCapture, source_input['capture_id'], populate_existing=True)
    retained, _ = checked_vehicle_history_capture_bytes(db, capture)
    run = _query(db, capture)
    _require(source_input['query_key'] == capture.query_key
             and source_input['target_kind'] == capture.target_kind == 'vehicle'
             and source_input['source_url'] == capture.source_url
             and source_input['content_type'] == capture.content_type
             and source_input['original_parser_version'] == capture.parser_version
             and source_input['original_parser_identity'] == capture.parser_identity)
    _require(capture.body_encoding == 'binary' and retained == raw
             and source_input['query'] == run.query and source_input['query_id'] == run.id
             and source_input['source_id'] == capture.source_id == SOURCE_ID
             and source_input['raw_hash'] == capture.raw_hash == SUPPORTED_RAW_SHA256
             and source_input['byte_count'] == len(raw) == SUPPORTED_BYTE_COUNT)
    from .parser_releases import RECEIPT_FIELDS, get_bundle_manifest
    from .parser_bundles import verify_bundle, XIAOMI_PDF_PARSER_VERSIONS
    from .parser_runtime import descriptor_for_manifest, input_hash
    _require(type(bundle_manifest) is dict)
    manifest = get_bundle_manifest(db, bundle_manifest['bundle_id'])
    _require(manifest == bundle_manifest)
    verified = verify_bundle(manifest)
    descriptor = descriptor_for_manifest(manifest, SOURCE_ID)
    _require(descriptor['parser_version'] in XIAOMI_PDF_PARSER_VERSIONS
             and type(receipt) is dict and set(receipt) <= RECEIPT_FIELDS)
    expected = {key: descriptor[key] for key in
                ('source_id', 'bundle_id', 'parser_version', 'parser_digest', 'execution_digest')}
    _require(all(receipt.get(key) == value for key, value in expected.items())
             and receipt.get('deployment_revision') == deployment_revision
             and (deployment_revision is None or type(deployment_revision) is int)
             and (receipt.get('deployment_revision') is None or type(receipt['deployment_revision']) is int)
             and type(receipt.get('run_id')) is str and re.fullmatch(r'[a-f0-9]{32}', receipt['run_id'])
             and type(receipt.get('exit_code')) is int and receipt['exit_code'] == 0
             and receipt.get('reaped') is True)
    _require(receipt.get('input_hash') == input_hash({**receipt, 'query': run.query}, raw))
    provenance = _mapping_provenance(manifest, verified, capture.raw_hash)
    _payload_identity(payload, provenance)
    return deepcopy(provenance)


@_closed
def checked_vehicle_bytes(db: Session, row) -> bytes:
    """Read a Snapshot/Quarantine original, validating its frozen parse identity."""
    _require(_kind(row) in ('snapshot', 'quarantine'))
    return _row_data(db, row)[0]


@_closed
def checked_vehicle_capture_pin(db: Session, run: QueryRun, *, parser_version: str,
                                parser_identity: dict) -> None:
    """Read-only binary pre-admission; caller must supply an independent journal.

    No bytes, objects or execution completion are required. This check precedes
    object.put; the existing capture checker still verifies the complete write.
    """
    _require(type(run) is QueryRun)
    stored = db.get(QueryRun, run.id)
    _require(stored is not None and stored.source_id == run.source_id == SOURCE_ID
             and stored.query == run.query == {'vehicle_id': FIRST_GENERATION_ID}
             and stored.query_key == run.query_key == digest(stored.query)
             and type(parser_version) is str and 1 <= len(parser_version) <= 100)
    _selection_identity(db, stored, parser_version, parser_identity)


@_closed
def checked_vehicle_capture(db: Session, run: QueryRun, observation: dict) -> RawCapture:
    """Validate an existing durable receipt; no Parser completion is required."""
    return _observation_capture(db, run, observation)[0]


@_closed
def build_vehicle_parse_provenance(db: Session, run: QueryRun, observation: dict,
                                 payload: dict, *, parser_selection: dict) -> dict:
    """Return a fresh server block; caller payload and all stored rows stay intact."""
    _require(type(payload) is dict and 'parse_provenance' not in payload
             and type(observation) is dict and 'parse_provenance' not in observation
             and not (type(observation.get('payload')) is dict and 'parse_provenance' in observation['payload']))
    capture, raw, stored_run = _observation_capture(db, run, observation)
    expected, selected, manifest, receipt = _completed_provenance(db, capture, raw, stored_run)
    _require(type(parser_selection) is dict and all(parser_selection.get(k) == v for k, v in selected.items())
             and parser_selection.get('bundle_manifest') == manifest
             and observation.get('parser_receipt') == receipt)
    _payload_identity(payload, expected)
    return deepcopy(expected)


@_closed
def checked_vehicle_parse_provenance(db: Session, row) -> dict | None:
    """Read the historical six-key block; legacy UTF-8 is never backfilled."""
    _require(_kind(row) in ('snapshot', 'quarantine'))
    return deepcopy(_row_data(db, row)[2])


@_closed
def vehicle_raw_metadata(db: Session, row) -> dict:
    """Internal V2 field builder for exactly four vehicle evidence row types."""
    kind = _kind(row)
    raw, capture, provenance = _row_data(db, row)
    binary = row.body_encoding == 'binary'
    endpoint = 'vehicle-evidence' if kind == 'snapshot' else 'captures' if kind == 'capture' else 'quarantines'
    _require(type(row.id) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', row.id))
    return {'evidence_format': 'raw-evidence-v2', 'body_encoding': row.body_encoding,
            'body': None if binary else raw.decode('utf-8', errors='strict'),
            'raw_capture_id': capture.id if capture is not None else None,
            'raw_hash': row.raw_hash, 'byte_count': len(raw), 'content_type': row.content_type,
            'content_path': f'/v1/{endpoint}/{quote(row.id, safe="")}/content?mode=history' if binary else None,
            'parse_method': provenance['method'] if provenance else None,
            'mapping_id': provenance['mapping_id'] if provenance else None}


class VehicleUseNotAllowed(PermissionError):
    """Fixed source-use refusal, independent of user or Provider consent."""

    status_code = 403
    _CODES = {'local_structured': 'vehicle_structured_fact_use_not_allowed',
              'provider': 'vehicle_provider_use_not_allowed',
              'export': 'vehicle_export_use_not_allowed'}

    def __init__(self, purpose):
        _require(type(purpose) is str and purpose in self._CODES)
        self.code = self._CODES[purpose]
        super().__init__(self.code)


def _vehicle_consumer_rights(capsule):
    """Trusted fixed-source policy. Capture/enable/consent cannot grant rights."""
    _require(capsule['source_id'] == SOURCE_ID and capsule['vehicle_id'] == FIRST_GENERATION_ID)
    return {'structured_fact_use': 'pending_review', 'provider_use': False,
            'export_or_redistribution': False}


def require_vehicle_consumer_use(capsule, purpose):
    """Only a trusted private policy fixture may permit local structured use."""
    _require(type(purpose) is str and purpose in VehicleUseNotAllowed._CODES)
    if capsule is None:  # Real legacy text retains each caller's existing gates.
        return
    _require(type(capsule) is dict)
    # No resolver, caller value, environment or consent may enable these uses.
    if purpose in {'provider', 'export'}:
        raise VehicleUseNotAllowed(purpose)
    policy = _vehicle_consumer_rights(capsule)
    if type(policy) is not dict or policy.get('structured_fact_use') != 'allowed':
        raise VehicleUseNotAllowed(purpose)


@_closed
def vehicle_raw_requires_v2(db: Session, row) -> bool:
    """Routing guard: fixed first-generation identity cannot become legacy text."""
    kind = _kind(row)
    if row.body_encoding == 'binary':
        return True
    if row.source_id != SOURCE_ID:
        return False
    if kind in ('snapshot', 'quarantine'):
        return row.vehicle_id == FIRST_GENERATION_ID
    run = db.get(QueryRun, row.query_id)
    if (run is not None and type(run.query) is dict
            and run.query.get('vehicle_id') == FIRST_GENERATION_ID):
        return True
    if row.source_url == PDF_URL:
        return True
    capture = db.scalar(select(RawCapture).where(RawCapture.query_id == row.query_id))
    return (capture is not None and capture.source_id == SOURCE_ID
            and (capture.body_encoding == 'binary' or capture.source_url == PDF_URL))


class VehicleOriginalUseNotAllowed(PermissionError):
    """An original-read refusal is independent of acceptance and other uses."""

    code = 'vehicle_original_read_not_allowed'

    def __init__(self):
        super().__init__(self.code)


def _vehicle_original_policy(binding):
    """Fixed trusted source policy; a private reviewed fixture may replace it."""
    _require(type(binding) is dict and binding['source_id'] == SOURCE_ID
             and binding['vehicle_id'] == FIRST_GENERATION_ID)
    return {'policy_version': 'xiaomi-vehicle-original@1',
            'evidence_basis': 'official-vehicle-pdf-contract@1/section-7',
            'scope': deepcopy(binding), 'expires_at': None,
            'capture_storage': 'pending_review', 'local_original_read': 'pending_review',
            'structured_fact_use': 'pending_review', 'provider_use': False,
            'export_or_redistribution': False}


@_closed
def _checked_vehicle_original_data(db: Session, row):
    raw, capture, _ = _row_data(db, row)
    if row.body_encoding == 'utf-8':
        return raw, None
    _require(capture is not None and type(row.id) is str
             and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', row.id))
    run = _query(db, capture)
    return raw, {'kind': _kind(row), 'id': row.id, 'query_id': run.id,
                 'raw_capture_id': capture.id, 'source_id': capture.source_id,
                 'vehicle_id': run.query['vehicle_id'], 'raw_hash': capture.raw_hash}


def checked_vehicle_original_bytes(db: Session, row, *, structured=False) -> bytes:
    """Read intact originals without requiring acceptance or granting facts use."""
    _require(type(structured) is bool)
    raw, binding = _checked_vehicle_original_data(db, row)
    if binding is None:  # Preserve real legacy text's existing use boundaries.
        return raw
    policy = _vehicle_original_policy(deepcopy(binding))
    expected_keys = {'policy_version', 'evidence_basis', 'scope', 'expires_at', 'capture_storage',
                     'local_original_read', 'structured_fact_use', 'provider_use',
                     'export_or_redistribution'}
    valid = (type(policy) is dict and set(policy) == expected_keys
             and policy.get('policy_version') == 'xiaomi-vehicle-original@1'
             and policy.get('evidence_basis') == 'official-vehicle-pdf-contract@1/section-7'
             and policy.get('scope') == binding and policy.get('expires_at') is None
             and policy.get('capture_storage') in ('pending_review', 'allowed')
             and policy.get('structured_fact_use') in ('pending_review', 'allowed')
             and policy.get('provider_use') is False and policy.get('export_or_redistribution') is False)
    if not valid or policy.get('local_original_read') != 'allowed':
        raise VehicleOriginalUseNotAllowed()
    if structured and policy['structured_fact_use'] != 'allowed':
        raise VehicleUseNotAllowed('local_structured')
    return raw


def checked_vehicle_v2_metadata(db: Session, row, *, structured=False) -> dict:
    """V2 metadata has the same original-use gate as its associated content."""
    checked_vehicle_original_bytes(db, row, structured=structured)
    return vehicle_raw_metadata(db, row)


@_closed
def checked_vehicle_consumer_capsule(db: Session, snapshot_id, verification_id=None) -> dict | None:
    """Thin read-only accepted-binary gate; never overwrite pending evidence."""
    from .service import timestamp
    from .vehicles import VehicleSnapshot, VehicleVerification, vehicle_provenance
    evidence_models = (VehicleSnapshot, VehicleVerification, QueryRun, RawCapture,
        CaptureObject, EvidenceObject, ParserSelection, ParserExecution, ParserBundle,
        ParserDeploymentRevision)
    _require(not any(isinstance(row, evidence_models)
                     for group in (db.new, db.dirty, db.deleted) for row in group))
    _require(type(snapshot_id) is str and bool(snapshot_id))
    snapshot = db.get(VehicleSnapshot, snapshot_id, populate_existing=True)
    _require(snapshot is not None)
    binary = (snapshot.body_encoding == 'binary'
              or (snapshot.source_id == SOURCE_ID and snapshot.vehicle_id == FIRST_GENERATION_ID))
    if not binary:
        _require(snapshot.body_encoding == 'utf-8')
        return None
    # Fixed first-generation identity cannot downgrade to the text shortcut.
    _require(snapshot.body_encoding == 'binary')
    if verification_id is None:
        verification = db.scalar(select(VehicleVerification).where(
            VehicleVerification.snapshot_id == snapshot.id).order_by(
            VehicleVerification.verified_at.desc(), VehicleVerification.id.desc()).limit(1)
            .execution_options(populate_existing=True))
    else:
        _require(type(verification_id) is str and bool(verification_id))
        verification = db.get(VehicleVerification, verification_id, populate_existing=True)
    _require(type(verification) is VehicleVerification)
    checked_vehicle_history_baseline(db, snapshot, verification=verification)
    return deepcopy({'snapshot_id': snapshot.id, 'vehicle_id': snapshot.vehicle_id,
        'source_id': snapshot.source_id, 'raw_hash': snapshot.raw_hash,
        'parser_version': snapshot.parser_version, 'parser_identity': snapshot.parser_identity,
        'observed_at': timestamp(snapshot.observed_at), 'verification_id': verification.id,
        'verified_at': timestamp(verification.verified_at), 'payload': snapshot.payload,
        'fact_hash': snapshot.fact_hash, 'provenance': vehicle_provenance(snapshot)})
