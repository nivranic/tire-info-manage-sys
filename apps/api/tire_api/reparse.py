"""Historical, non-publishing parser experiments with frozen inputs and reviews."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import re
from sys import platform as HOST_PLATFORM
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import Field, StrictInt, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .auth import make_admin_guard
from .captures import checked_capture_bytes
from .db import AuditEvent, CaptureObject, QueryRun, RawCapture, Snapshot, Verification, uid, utc, utcnow
from .domain import StrictModel, TireQuery, VariantInput, digest, stable_json
from .quality import assess_quality, namespace_reference_matches, product_reference_key, stable_key
from .reparse_models import ReparseCompletion, ReparseReview, ReparseRun
from .service import QueryService

NOTICE = ('历史重解析只生成未采纳候选与审阅记录，不更新事实、核验、索引或提醒；'
          '审阅不等于批准采纳。当前只隔离进程故障，未提供操作系统级网络隔离。Parser 部署使用独立评估与审批。')
SCOPE = {'scope': 'workspace', 'data_state': 'local_snapshot', 'accepted_as_facts': False}
MAX_CANDIDATE_BYTES = 2 * 1024 * 1024
MAX_BASELINE_BYTES = 2 * 1024 * 1024


class ReparseCreate(StrictModel):
    mode: Literal['history']
    capture_id: str = Field(min_length=1, max_length=64)
    parser_version: str = Field(min_length=1, max_length=100)
    parser_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    bundle_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class ReviewCreate(StrictModel):
    mode: Literal['history']
    expected_revision: StrictInt = Field(ge=0)
    status: Literal['reviewed', 'needs_fix', 'rejected']
    operator: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator('operator', 'reason')
    @classmethod
    def plain_text(cls, value):
        if '\x00' in value:
            raise ValueError('文本不能包含空字符')
        value.encode('utf-8', errors='strict')
        return value


def catalog_entries():
    # Discovery is lazy: a damaged deployment must not prevent ordinary API startup.
    try:
        from .parser_runtime import parser_catalog
        entries = parser_catalog()
        if not isinstance(entries, dict) or not entries:
            raise ValueError('empty parser catalog')
        return entries
    except Exception:
        raise HTTPException(503, {'code': 'parser_catalog_unavailable'}) from None


def bundle_entries(db, bundle_id):
    from .parser_bundles import BundleError, bundle_descriptor, verify_bundle
    from .parser_releases import get_bundle_manifest
    manifest = get_bundle_manifest(db, bundle_id)
    db.commit()
    try:
        verify_bundle(manifest)
        entries = {source: bundle_descriptor(manifest, source) for source in manifest['parsers']}
    except BundleError as error:
        raise HTTPException(503, {'code': error.code}) from None
    return entries, manifest


def latest_baseline(db, source_id, target_kind, query_key, query):
    if target_kind == 'recall':
        from .recall_reparse import latest_recall_baseline
        return latest_recall_baseline(db, source_id, query_key, query)
    if target_kind not in {'tire', 'vehicle'}:
        raise HTTPException(422, {'code': 'unsupported_reparse_source'})
    if target_kind == 'vehicle':
        from .vehicles import VehicleSnapshot, VehicleVerification
        item = db.execute(select(VehicleSnapshot, VehicleVerification)
            .join(VehicleVerification, VehicleVerification.snapshot_id == VehicleSnapshot.id)
            .join(QueryRun, QueryRun.id == VehicleVerification.query_id)
            .where(QueryRun.source_id == source_id, QueryRun.query_key == query_key,
                   VehicleVerification.vehicle_id == query['vehicle_id'])
            .order_by(desc(VehicleVerification.verified_at), desc(VehicleVerification.id)).limit(1)).first()
    else:
        item = db.execute(select(Snapshot, Verification)
            .join(Verification, Verification.snapshot_id == Snapshot.id)
            .where(Verification.source_id == source_id, Verification.query_key == query_key)
            .order_by(desc(Verification.verified_at), desc(Verification.id)).limit(1)).first()
    if item is None:
        return None
    snapshot, verification = item
    return {'snapshot_id': snapshot.id, 'verification_id': verification.id,
            'verified_at': utc(verification.verified_at).isoformat(),
            'observed_at': utc(snapshot.observed_at).isoformat(), 'raw_hash': snapshot.raw_hash,
            'source_url': snapshot.source_url, 'parser_version': snapshot.parser_version,
            'parser_identity': deepcopy(snapshot.parser_identity),
            'selected_at': utcnow().isoformat(),
            'payload': deepcopy(snapshot.payload if target_kind == 'vehicle' else snapshot.parsed_variants)}


def capture_input(db, capture, entries):
    from .adapters import registry, xiaomi
    from .adapters.transport import SourceAccessError
    run = db.get(QueryRun, capture.query_id)
    entry = entries.get(capture.source_id)
    if entry is None or capture.target_kind not in {'tire', 'vehicle', 'recall'}:
        raise HTTPException(422, {'code': 'unsupported_reparse_source'})
    if (run is None or run.source_id != capture.source_id or run.query_key != capture.query_key
            or digest(run.query) != capture.query_key or capture.target_kind != entry['target_kind']):
        raise HTTPException(422, {'code': 'capture_query_mismatch'})
    try:
        if capture.target_kind == 'recall':
            from .recall_reparse import validate_recall_input
            validate_recall_input(capture.source_id, run.query, capture.source_url, capture.content_type)
        elif capture.target_kind == 'vehicle':
            if (set(run.query) != {'vehicle_id'} or run.query['vehicle_id'] != xiaomi.CURRENT_ID
                    or capture.source_url != xiaomi.API_URL or capture.content_type != 'application/json'):
                raise ValueError('vehicle input')
        else:
            canonical = TireQuery.model_validate(run.query).canonical()
            if canonical != run.query or capture.content_type not in registry.SPECS[capture.source_id].content_types:
                raise ValueError('query or mime')
            if capture.source_url.rstrip('/') != registry.query_url(canonical, capture.source_id).rstrip('/'):
                raise ValueError('source query url')
    except (ValueError, TypeError, KeyError, SourceAccessError):
        raise HTTPException(422, {'code': 'capture_source_metadata_mismatch'}) from None
    return {'capture_id': capture.id, 'query_id': run.id, 'source_id': capture.source_id,
            'target_kind': capture.target_kind, 'query': deepcopy(run.query), 'query_key': capture.query_key,
            'source_url': capture.source_url, 'content_type': capture.content_type,
            'raw_hash': capture.raw_hash, 'byte_count': capture.byte_count,
            'observed_at': utc(capture.observed_at).isoformat(),
            'storage_kind': 'object_store' if db.get(CaptureObject, capture.id) else 'database_legacy',
            'original_parser_version': capture.parser_version,
            'original_parser_identity': deepcopy(capture.parser_identity)}


def validate_candidate(payload, source_input, raw):
    if source_input.get('target_kind') not in {'tire', 'vehicle', 'recall'}:
        raise ValueError('unsupported_reparse_source')
    def validate_text(value):
        if isinstance(value, str):
            if '\x00' in value:
                raise ValueError('null character in candidate')
        elif isinstance(value, dict):
            for key, child in value.items():
                validate_text(key)
                validate_text(child)
        elif isinstance(value, list):
            for child in value:
                validate_text(child)
    validate_text(payload)
    if len(stable_json(payload).encode('utf-8')) > MAX_CANDIDATE_BYTES:
        raise ValueError('candidate too large')
    if source_input['target_kind'] == 'recall':
        from .recall_reparse import validate_recall_candidate
        return validate_recall_candidate(payload, source_input)
    if source_input['target_kind'] == 'tire':
        variants = QueryService.validate_result({'variants': payload, 'body': raw.decode('utf-8'),
            'url': source_input['source_url'], 'parser_version': source_input['original_parser_version'],
            'content_type': source_input['content_type']}, source_input['query'])
        return [variant.model_dump() for variant in variants]
    from .vehicles import WheelFitmentSpecification, validate_vehicle_structure
    if (not isinstance(payload, dict) or payload['vehicle']['id'] != source_input['query']['vehicle_id']
            or not payload.get('fitments') or len(payload['fitments']) > 100):
        raise ValueError('vehicle identity or fitments')
    fits = [WheelFitmentSpecification.model_validate(row).model_dump() for row in payload['fitments']]
    if len({row['id'] for row in fits}) != len(fits):
        raise ValueError('duplicate fitments')
    trim_ids = {row['id'] for row in payload['trims']}
    if any(row['trim_id'] not in trim_ids for row in fits):
        raise ValueError('unknown trim')
    validate_vehicle_structure(payload, fits)
    return {**payload, 'fitments': fits}


def tire_identity(row):
    return VariantInput.model_validate({key: value for key, value in row.items()
                                      if key in VariantInput.model_fields}).identity()


def flattened(value, prefix=''):
    if isinstance(value, dict):
        return {path: leaf for key, child in value.items()
                for path, leaf in flattened(child, f'{prefix}.{key}' if prefix else key).items()}
    return {prefix: value}


def compare_candidate(baseline, candidate, target_kind):
    if target_kind == 'recall':
        from .recall_reparse import compare_recall_candidate
        return compare_recall_candidate(baseline, candidate)
    previous = baseline['payload'] if baseline else None
    if target_kind == 'vehicle':
        from .vehicle_quality import assess_vehicle_quality
        quality = assess_vehicle_quality(previous, candidate)
        old = {'vehicle': previous['vehicle'], **{f'{group}:{row["id"]}': row
            for group in ('trims', 'fitments') for row in previous[group]}} if previous else {}
        new = {'vehicle': candidate['vehicle'], **{f'{group}:{row["id"]}': row
            for group in ('trims', 'fitments') for row in candidate[group]}}
        identities = ['vehicle'] if 'vehicle_identity_changed' in quality['reason_codes'] else []
    else:
        quality = assess_quality(previous, candidate)
        old = {stable_key(row): {key: value for key, value in row.items() if key in VariantInput.model_fields}
               for row in previous or [] if stable_key(row) is not None}
        new = {stable_key(row): row for row in candidate if stable_key(row) is not None}
        references = namespace_reference_matches(previous, candidate)
        pairs = {key: key for key in old.keys() & new.keys()} | references
        # A known namespace change remains an identity regression, even when it
        # affects too few rows to cross the independent row-loss threshold.
        old_families, new_families = {}, {}
        for rows, groups in ((old, old_families), (new, new_families)):
            for key, row in rows.items():
                groups.setdefault(product_reference_key(row), []).append(key)
        for family in old_families.keys() & new_families.keys():
            before, after = old_families[family], new_families[family]
            if len(before) == len(after) == 1 and before[0] not in pairs:
                pairs[before[0]] = after[0]
        identities = []
        for key, candidate_key in pairs.items():
            before, after = tire_identity(old[key]), tire_identity(new[candidate_key])
            if key in references:
                # This is only a historical regression reference. Preserve the
                # actual added/removed keys and field change in the report.
                before = {field: value for field, value in before.items() if field != 'product_code_type'}
                after = {field: value for field, value in after.items() if field != 'product_code_type'}
            if digest(before) != digest(after):
                identities.append(key)
        if identities:
            quality['reason_codes'].append('tire_identity_changed')
    changes, count = [], 0
    compared_pairs = pairs if target_kind == 'tire' else {key: key for key in old.keys() & new.keys()}
    for key, candidate_key in sorted(compared_pairs.items()):
        before, after = flattened(old[key]), flattened(new[candidate_key])
        fields = []
        for path in sorted(before.keys() | after.keys()):
            if path in {'id', 'variant_id', 'snapshot_id', 'version'}:
                continue
            if digest(before.get(path)) != digest(after.get(path)) or (path in before) != (path in after):
                count += 1
                if count <= 2000:
                    fields.append({'path': path, 'before': before.get(path), 'after': after.get(path),
                                   'before_present': path in before, 'after_present': path in after})
        if fields:
            changes.append({'row_key': key, **({'candidate_row_key': candidate_key} if key != candidate_key else {}),
                            'changes': fields})
    quality['blocked'] = bool(quality['reason_codes'])
    return quality, {'baseline_available': baseline is not None,
        'added_row_keys': sorted(new.keys() - old.keys()), 'removed_row_keys': sorted(old.keys() - new.keys()),
        'changed_rows': changes, 'identity_changed_row_keys': sorted(identities),
        'total_changed_fields': count, 'truncated': count > 2000}


def completion_binding(run, state, error_code, candidate, quality, difference, receipt):
    return digest({'run_id': run.id, 'input_hash': run.input_hash, 'state': state, 'error_code': error_code,
                   'candidate': candidate, 'quality': quality, 'diff': difference, 'receipt': receipt})


def checked_run(db, run_id):
    run = db.get(ReparseRun, run_id)
    if run is None:
        raise HTTPException(404, {'code': 'reparse_not_found'})
    if run.input_hash != digest({'input': run.input, 'parser': run.parser, 'baseline': run.baseline}):
        raise HTTPException(503, {'code': 'reparse_integrity_failed'})
    return run


def checked_completion(db, run):
    row = db.scalar(select(ReparseCompletion).where(ReparseCompletion.run_id == run.id))
    if row and row.fingerprint != completion_binding(run, row.state, row.error_code, row.candidate,
                                                    row.quality, row.diff, row.receipt):
        raise HTTPException(503, {'code': 'reparse_integrity_failed'})
    return row


def review_view(row):
    return {'id': row.id, 'revision': row.revision, 'status': row.status,
            'operator': row.operator, 'reason': row.reason, 'created_at': utc(row.created_at).isoformat()}


def run_view(db, run, detail=True):
    completion = checked_completion(db, run)
    latest = db.scalar(select(ReparseReview).where(ReparseReview.run_id == run.id)
                       .order_by(desc(ReparseReview.revision)).limit(1))
    state = completion.state if completion else ('unknown' if utcnow() - utc(run.created_at) > timedelta(seconds=120) else 'pending')
    baseline = {key: value for key, value in run.baseline.items() if detail or key != 'payload'} if run.baseline else None
    result = {**SCOPE, 'id': run.id, 'state': state, 'created_at': utc(run.created_at).isoformat(),
              'started_at': utc(run.created_at).isoformat(), 'input': run.input, 'parser': run.parser,
              'baseline': baseline, 'completion': None, 'review_revision': latest.revision if latest else 0,
              'latest_review': review_view(latest) if latest else None, 'notice': NOTICE}
    if completion:
        result['completion'] = {'error_code': completion.error_code,
            'completed_at': utc(completion.completed_at).isoformat(),
            'candidate_hash': digest(completion.candidate) if completion.candidate is not None else None,
            'quality_reason_codes': completion.quality['reason_codes'] if completion.quality else [],
            'quality_blocked': bool(completion.quality and completion.quality['reason_codes'])}
        if detail:
            result['completion'].update(candidate=completion.candidate, quality=completion.quality,
                diff=completion.diff, receipt=completion.receipt, fingerprint=completion.fingerprint)
    if detail:
        current = latest_baseline(db, run.input['source_id'], run.input['target_kind'],
                                  run.input['query_key'], run.input['query'])
        result['baseline_current'] = ((current or {}).get('verification_id') == (run.baseline or {}).get('verification_id'))
        reviews = db.scalars(select(ReparseReview).where(ReparseReview.run_id == run.id)
                             .order_by(desc(ReparseReview.revision)).limit(100)).all()
        result['reviews'] = [review_view(row) for row in reviews]
        result['reviews_truncated'] = bool(latest and latest.revision > len(reviews))
    return result


def register_reparse_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    admin_guard = make_admin_guard(get_db)

    @app.get('/v1/reparse/status')
    @app.get('/v1/reparse/catalog')
    def catalog(mode: Literal['history'] = Query(...),
                bundle_id: str | None = Query(None, pattern=r'^[a-f0-9]{64}$'), db: Session = Depends(get_db)):
        entries = [entry for entry in (bundle_entries(db, bundle_id)[0] if bundle_id else catalog_entries()).values()
                   if entry['target_kind'] in {'tire', 'vehicle', 'recall'}]
        runtime = entries[0]['limits']
        supported_platform = HOST_PLATFORM in {'win32', 'linux'}
        return {**SCOPE, 'available': supported_platform,
                'availability_reason': None if supported_platform else 'parser_platform_not_supported', 'parsers': entries,
                'limits': {'max_body_bytes': runtime['input_bytes'], 'max_candidate_bytes': MAX_CANDIDATE_BYTES,
                           'max_baseline_bytes': MAX_BASELINE_BYTES,
                           'max_output_bytes': runtime['output_bytes'], 'max_stderr_bytes': runtime['stderr_bytes'],
                           'timeout_seconds': runtime['wall_seconds'], 'cpu_seconds': runtime['cpu_seconds'],
                           'max_memory_bytes': runtime['memory_bytes'], 'max_concurrency': runtime['max_concurrent'],
                           'unknown_after_seconds': 120}, 'notice': NOTICE}

    @app.get('/v1/reparse/runs')
    def runs(mode: Literal['history'] = Query(...), capture_id: str | None = Query(None, max_length=64),
             offset: int = Query(0, ge=0, le=100000), limit: int = Query(10, ge=1, le=25),
             db: Session = Depends(get_db)):
        filters = [ReparseRun.capture_id == capture_id] if capture_id else []
        total = db.scalar(select(func.count()).select_from(ReparseRun).where(*filters))
        items = db.scalars(select(ReparseRun).where(*filters)
            .order_by(desc(ReparseRun.created_at), desc(ReparseRun.id)).offset(offset).limit(limit)).all()
        return {**SCOPE, 'items': [run_view(db, checked_run(db, row.id), False) for row in items],
                'total': total, 'offset': offset, 'limit': limit}

    @app.get('/v1/reparse/runs/{run_id}')
    def read(run_id: str, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        return run_view(db, checked_run(db, run_id))

    @app.post('/v1/reparse/runs', status_code=201)
    def create(payload: ReparseCreate, request: Request,
               idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64),
               db: Session = Depends(get_db)):
        try:
            key = str(UUID(idempotency_key))
        except ValueError:
            raise HTTPException(422, {'code': 'invalid_idempotency_key'}) from None
        request_hash = digest(payload.model_dump(exclude_none=True))
        previous = db.scalar(select(ReparseRun).where(ReparseRun.actor_session_id == request.state.session_id,
                                                      ReparseRun.idempotency_key == key))
        if previous:
            if previous.request_hash != request_hash:
                raise HTTPException(409, {'code': 'idempotency_payload_mismatch'})
            return run_view(db, checked_run(db, previous.id))
        db.commit()
        # Hash and verify code before reserving the write lock. Registered immutable
        # manifests are the authority; the on-disk manifest cannot register itself.
        if payload.bundle_id:
            entries, bundle_manifest = bundle_entries(db, payload.bundle_id)
        else:
            entries, bundle_manifest = catalog_entries(), None
        QueryService(db, None).lock_ingestion()
        previous = db.scalar(select(ReparseRun).where(ReparseRun.actor_session_id == request.state.session_id,
                                                      ReparseRun.idempotency_key == key))
        if previous:
            if previous.request_hash != request_hash:
                raise HTTPException(409, {'code': 'idempotency_payload_mismatch'})
            db.commit()
            return run_view(db, checked_run(db, previous.id))
        capture = db.get(RawCapture, payload.capture_id)
        if capture is None:
            raise HTTPException(404, {'code': 'capture_not_found'})
        source_input = capture_input(db, capture, entries)
        current = entries[capture.source_id]
        if payload.parser_version != current['parser_version'] or payload.parser_digest != current['parser_digest']:
            raise HTTPException(409, {'code': 'parser_deployment_changed'})
        parser = {'version': current['parser_version'], 'digest': current['parser_digest']}
        if payload.bundle_id:
            parser['bundle_id'] = payload.bundle_id
        baseline = latest_baseline(db, capture.source_id, capture.target_kind, capture.query_key, source_input['query'])
        if baseline and len(stable_json(baseline).encode('utf-8')) > MAX_BASELINE_BYTES:
            raise HTTPException(422, {'code': 'reparse_baseline_too_large'})
        run = ReparseRun(id=uid(), actor_session_id=request.state.session_id, idempotency_key=key,
            request_hash=request_hash, capture_id=capture.id, input=source_input, parser=parser,
            baseline=baseline, input_hash=digest({'input': source_input, 'parser': parser, 'baseline': baseline}))
        db.add(run)
        db.add(AuditEvent(session_id=request.state.session_id, query_id=capture.query_id,
                         action='historical_reparse_reserved', detail={'run_id': run.id, 'capture_id': capture.id}))
        db.commit()
        error_code, candidate, quality, difference, receipt, http_failure = None, None, None, None, {}, None
        runtime_error_type = ()
        try:
            raw, _storage = checked_capture_bytes(db, capture)
            db.commit()  # No database lock or read transaction spans parser execution.
            from .parser_runtime import parse_isolated, ParserRunError
            runtime_error_type = ParserRunError
            parsed = asyncio.run(parse_isolated(capture.source_id, raw, source_input['query'],
                                                parser['version'], parser['digest'],
                                                **({'bundle_manifest': bundle_manifest} if bundle_manifest else {})))
            receipt = parsed['receipt']
            candidate = validate_candidate(parsed['payload'], source_input, raw)
            quality, difference = compare_candidate(baseline, candidate, source_input['target_kind'])
        except HTTPException:
            error_code, http_failure = 'capture_integrity_failed', 503
        except Exception as error:
            if isinstance(error, runtime_error_type):
                error_code = error.code if re.fullmatch(r'[a-z][a-z0-9_]{0,79}', error.code) else 'parser_execution_failed'
                receipt = getattr(error, 'receipt', {}) or {}
            else:
                error_code = 'candidate_validation_failed'
            candidate, quality, difference = None, None, None
        state = 'failed' if error_code else 'completed'
        QueryService(db, None).lock_ingestion()
        completion = ReparseCompletion(run_id=run.id, state=state, error_code=error_code,
            candidate=candidate, quality=quality, diff=difference, receipt=receipt,
            fingerprint=completion_binding(run, state, error_code, candidate, quality, difference, receipt))
        db.add(completion)
        db.add(AuditEvent(session_id=request.state.session_id, query_id=capture.query_id,
            action='historical_reparse_completed', detail={'run_id': run.id, 'state': state, 'error_code': error_code,
                                                         'accepted_as_facts': False}))
        db.commit()
        if http_failure:
            raise HTTPException(http_failure, {'code': error_code, 'run_id': run.id})
        return run_view(db, run)

    @app.post('/v1/reparse/runs/{run_id}/reviews', status_code=201, dependencies=[Depends(admin_guard)])
    def review(run_id: str, payload: ReviewCreate, request: Request, db: Session = Depends(get_db)):
        from .auth import session_scope
        QueryService(db, None).lock_ingestion()
        run = checked_run(db, run_id)
        if run.actor_session_id not in session_scope(db, request.state.session_id):
            raise HTTPException(404, {'code': 'reparse_not_found'})
        completion = checked_completion(db, run)
        if completion is None:
            raise HTTPException(409, {'code': 'reparse_not_completed'})
        revision = db.scalar(select(func.max(ReparseReview.revision)).where(ReparseReview.run_id == run.id)) or 0
        if payload.expected_revision != revision:
            raise HTTPException(409, {'code': 'reparse_review_revision_conflict'})
        db.add(ReparseReview(run_id=run.id, revision=revision + 1, status=payload.status,
            operator=payload.operator, reason=payload.reason, actor_session_id=request.state.session_id,
            completion_fingerprint=completion.fingerprint))
        db.add(AuditEvent(session_id=request.state.session_id, query_id=run.input['query_id'],
            action='historical_reparse_reviewed', detail={'run_id': run.id, 'revision': revision + 1,
                                                        'status': payload.status, 'accepted_as_facts': False}))
        db.commit()
        return run_view(db, run)
