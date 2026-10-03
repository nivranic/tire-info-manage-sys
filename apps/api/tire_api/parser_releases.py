"""Local trusted Parser release gates. HTTP selects registered IDs, never executable input."""
import argparse
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
import hashlib
import re
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .captures import checked_capture_bytes
from .db import AuditEvent, QueryRun, RawCapture, Snapshot, Verification, uid, utc, utcnow
from .domain import StrictModel, digest, stable_json
from .parser_release_models import (ParserBundle, ParserDeploymentRevision, ParserEvaluation,
    ParserEvaluationCompletion, ParserEvaluationReview, ParserExecution, ParserSelection)
from .reparse import MAX_BASELINE_BYTES, capture_input, compare_candidate, validate_candidate
from .service import QueryService

SCOPE = {'scope': 'local_workspace', 'production_deployment': False}
NOTICE = ('评估只重放固定历史原文，不采纳事实。审批与切换仅影响本机后续请求，'
          '不代表官网已重新核验、完整 Golden Set 或数据库版本回退。')


class ParserDeploymentError(Exception):
    def __init__(self, code, status_code=409, *, execution_recorded=False):
        super().__init__(code)
        self.code, self.status_code = code, status_code
        self.execution_recorded = execution_recorded


def safe_code(error, fallback='parser_bundle_unavailable'):
    code = getattr(error, 'code', None)
    return code if isinstance(code, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,79}', code) else fallback


def require_uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ParserDeploymentError('invalid_idempotency_key', 422) from None


class SignedAction(StrictModel):
    operator: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator('operator', 'reason')
    @classmethod
    def plain(cls, value):
        if '\x00' in value:
            raise ValueError('文本不能包含空字符')
        value.encode('utf-8', errors='strict')
        return value


class EvaluationCreate(StrictModel):
    mode: Literal['history']
    source_id: str = Field(min_length=1, max_length=80)
    target_bundle_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    capture_ids: list[str] = Field(min_length=1, max_length=3)
    expected_deployment_revision: StrictInt = Field(ge=1)
    golden_set_id: str | None = Field(default=None, min_length=1, max_length=64)
    expected_golden_set_revision: StrictInt | None = Field(default=None, ge=1)
    golden_set_fingerprint: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def complete_golden_reference(self):
        values = (self.golden_set_id, self.expected_golden_set_revision, self.golden_set_fingerprint)
        if any(value is not None for value in values) and not all(value is not None for value in values):
            raise ValueError('Golden 冻结集须同时提供 ID、版本和指纹')
        return self

    @field_validator('capture_ids')
    @classmethod
    def unique(cls, values):
        if len(set(values)) != len(values) or any(not value or len(value) > 64 for value in values):
            raise ValueError('请选择 1–3 个不同的原文接收记录')
        return values


class EvaluationReviewCreate(SignedAction):
    mode: Literal['history']
    expected_revision: StrictInt = Field(ge=0)
    completion_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    action: Literal['approve', 'reject']
    acknowledged: StrictBool
    acknowledge_reference_gaps: StrictBool = False


class DeploymentTransition(SignedAction):
    action: Literal['activate', 'pause', 'resume', 'rollback']
    expected_revision: StrictInt = Field(ge=1)
    target_bundle_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    evaluation_id: str | None = Field(default=None, min_length=1, max_length=64)
    expected_review_revision: StrictInt | None = Field(default=None, ge=1)
    target_revision: StrictInt | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def exact_action(self):
        if self.action == 'activate':
            if not self.target_bundle_id or not self.evaluation_id or self.expected_review_revision is None or self.target_revision is not None:
                raise ValueError('启用必须绑定包、评估及审批修订')
        elif self.action == 'rollback':
            if self.target_revision is None or any(value is not None for value in (self.target_bundle_id, self.evaluation_id, self.expected_review_revision)):
                raise ValueError('回滚只接受该来源的历史部署修订')
        elif any(value is not None for value in (self.target_bundle_id, self.evaluation_id, self.expected_review_revision, self.target_revision)):
            raise ValueError('暂停或恢复不能替换 Parser 包')
        return self


def current_deployment(db, source_id):
    return db.scalar(select(ParserDeploymentRevision).where(ParserDeploymentRevision.source_id == source_id)
                     .order_by(desc(ParserDeploymentRevision.revision)).limit(1))


def _bundle(db, bundle_id):
    row = db.get(ParserBundle, bundle_id)
    if row is None:
        raise ParserDeploymentError('parser_bundle_not_registered', 404)
    if row.manifest.get('bundle_id') != row.id:
        raise ParserDeploymentError('parser_bundle_integrity_failed', 503)
    return row


def get_bundle_manifest(db: Session, bundle_id: str):
    """Only registered manifests authorize historical execution; runtime still verifies stored bytes."""
    return deepcopy(_bundle(db, bundle_id).manifest)


def _verify(manifest, source_id=None):
    try:
        from .parser_bundles import verify_bundle, bundle_descriptor
        verify_bundle(manifest)
        if source_id is not None:
            return bundle_descriptor(manifest, source_id)
        entries = manifest['parsers']
        source_ids = entries.keys() if isinstance(entries, dict) else [item['source_id'] for item in entries]
        return {source: bundle_descriptor(manifest, source) for source in source_ids}
    except Exception as error:
        raise ParserDeploymentError(safe_code(error), 503) from None


def _register_locked(db, manifest, descriptors, operator, reason, origin):
    previous = db.get(ParserBundle, manifest['bundle_id'])
    if previous:
        if previous.manifest != manifest:
            raise ParserDeploymentError('parser_bundle_registration_conflict', 409)
        return previous
    row = ParserBundle(id=manifest['bundle_id'], manifest=deepcopy(manifest), descriptors=deepcopy(descriptors),
                       operator=operator, reason=reason, origin=origin)
    db.add(row)
    db.flush()
    return row


def register_deployed_bundle(db: Session, operator: str, reason: str):
    """Local CLI only: seal the installed trusted module tree; no caller-supplied path/code."""
    signed = SignedAction(operator=operator, reason=reason)
    db.commit()
    try:
        from .parser_bundles import seal_deployed_bundle
        manifest = seal_deployed_bundle()
    except Exception as error:
        raise ParserDeploymentError(safe_code(error), 503) from None
    descriptors = _verify(manifest)
    QueryService(db, None).lock_ingestion()
    row = _register_locked(db, manifest, descriptors, signed.operator, signed.reason, 'local_deployed_import')
    db.commit()
    return bundle_view(row)


def bootstrap_source(db: Session, source_id: str, operator='本机兼容初始化', reason='首次使用固定当前受信 Parser 包'):
    signed = SignedAction(operator=operator, reason=reason)
    current = current_deployment(db, source_id)
    db.commit()
    if current:
        return current
    try:
        from .parser_bundles import seal_deployed_bundle
        manifest = seal_deployed_bundle()
    except Exception as error:
        raise ParserDeploymentError(safe_code(error), 503) from None
    descriptors = _verify(manifest)
    if source_id not in descriptors:
        raise ParserDeploymentError('parser_source_not_allowed', 422)
    QueryService(db, None).lock_ingestion()
    current = current_deployment(db, source_id)
    if current:
        db.commit()
        return current
    bundle = _register_locked(db, manifest, descriptors, signed.operator, signed.reason, 'builtin_bootstrap')
    row = ParserDeploymentRevision(id=uid(), source_id=source_id, revision=1, state='active', bundle_id=bundle.id,
        descriptor=descriptors[source_id], action='bootstrap', actor_session_id='local-bootstrap',
        idempotency_key=source_id, request_hash=digest({'source_id': source_id, 'bundle_id': bundle.id}),
        operator=signed.operator, reason=signed.reason)
    db.add(row)
    db.commit()
    return row


def public_selection(selection):
    return {key: selection[key] for key in ('source_id', 'query_run_id', 'bundle_id', 'deployment_revision',
        'parser_version', 'parser_digest', 'execution_digest') if key in selection}


def _selection_dict(db, row):
    bundle = _bundle(db, row.bundle_id)
    return {'source_id': row.source_id, 'query_run_id': row.query_run_id, 'bundle_id': row.bundle_id,
        'deployment_revision': row.deployment_revision, 'parser_version': row.descriptor['parser_version'],
        'parser_digest': row.descriptor['parser_digest'],
        'execution_digest': row.descriptor.get('execution_digest', row.descriptor['parser_digest']),
        'bundle_manifest': deepcopy(bundle.manifest)}


def pin_selection(db: Session, query_run_id: str, source_id: str):
    """Call after committing QueryRun and before network I/O; this function commits its pin."""
    previous = db.get(ParserSelection, query_run_id)
    if previous:
        if previous.source_id != source_id:
            raise ParserDeploymentError('parser_selection_source_mismatch', 409)
        result = _selection_dict(db, previous)
        db.commit()
        return result
    query = db.get(QueryRun, query_run_id)
    if query is None or query.source_id != source_id:
        raise ParserDeploymentError('parser_selection_source_mismatch', 409)
    db.commit()
    bootstrap_source(db, source_id)
    for _ in range(3):
        observed = current_deployment(db, source_id)
        if observed.state != 'active':
            raise ParserDeploymentError('parser_deployment_paused', 409)
        manifest = deepcopy(_bundle(db, observed.bundle_id).manifest)
        observed_id = observed.id
        db.commit()
        execution_descriptor = _verify(manifest, source_id)
        QueryService(db, None).lock_ingestion()
        previous = db.get(ParserSelection, query_run_id)
        if previous:
            result = _selection_dict(db, previous)
            db.commit()
            return result
        current = current_deployment(db, source_id)
        if current.id != observed_id:
            db.commit()
            continue
        row = ParserSelection(query_run_id=query_run_id, source_id=source_id,
            deployment_id=current.id, bundle_id=current.bundle_id, deployment_revision=current.revision,
            descriptor=deepcopy(execution_descriptor))
        db.add(row)
        db.flush()
        result = _selection_dict(db, row)
        db.commit()
        return result
    raise ParserDeploymentError('parser_deployment_changed', 409)


def assert_selection_current(db: Session, selection: dict):
    """Caller already holds the ingestion lock. Never commit or acquire a second lock here."""
    stored = db.get(ParserSelection, selection.get('query_run_id'))
    if stored is None or any(selection.get(key) != value for key, value in {
            'source_id': stored.source_id, 'bundle_id': stored.bundle_id,
            'deployment_revision': stored.deployment_revision,
            'parser_digest': stored.descriptor['parser_digest'],
            'parser_version': stored.descriptor['parser_version'],
            'execution_digest': stored.descriptor.get('execution_digest', stored.descriptor['parser_digest'])}.items()):
        raise ParserDeploymentError('parser_selection_mismatch', 409)
    current = current_deployment(db, stored.source_id)
    if current is None or current.id != stored.deployment_id:
        raise ParserDeploymentError('parser_deployment_changed', 409)
    if current.state != 'active':
        raise ParserDeploymentError('parser_deployment_paused', 409)


RECEIPT_FIELDS = {'run_id', 'source_id', 'parser_version', 'parser_digest', 'bundle_id', 'deployment_revision',
    'input_hash', 'execution_digest', 'manifest_hash', 'runtime_policy_hash', 'pid', 'exit_code', 'isolation',
    'network_enforced', 'python_network_guard', 'limits', 'limits_backend', 'reaped', 'elapsed_ms',
    'stdout_bytes', 'stderr_bytes'}


def record_execution(db: Session, query_run_id: str, outcome: dict):
    """Append one safe outcome. Caller commits before source adoption; no-op for unpinned legacy fixtures."""
    selected = db.get(ParserSelection, query_run_id)
    if selected is None:
        return None
    state = outcome.get('state') or {'ok': 'completed', 'unavailable': 'failed', 'not_modified': 'not_modified'}.get(outcome.get('status'))
    if state not in {'completed', 'failed', 'not_modified', 'not_started'}:
        raise ParserDeploymentError('parser_execution_state_invalid', 422)
    raw_receipt = outcome.get('receipt', outcome.get('parser_receipt', {})) or {}
    receipt_error = None
    receipt = {key: deepcopy(value) for key, value in raw_receipt.items() if key in RECEIPT_FIELDS} if isinstance(raw_receipt, dict) else {}
    if not isinstance(raw_receipt, dict):
        receipt_error = 'parser_receipt_invalid'
    try:
        encoded = stable_json(receipt).encode('utf-8')
        if len(encoded) > 16384 or b'\\u0000' in encoded:
            raise ValueError('oversized receipt')
    except (ValueError, UnicodeError, TypeError):
        receipt, receipt_error = {}, 'parser_receipt_invalid'
    for key, expected in {'bundle_id': selected.bundle_id, 'source_id': selected.source_id,
            'deployment_revision': selected.deployment_revision, 'parser_digest': selected.descriptor['parser_digest'],
            'parser_version': selected.descriptor['parser_version'],
            'execution_digest': selected.descriptor.get('execution_digest', selected.descriptor['parser_digest'])}.items():
        if (state == 'completed' or key in receipt) and receipt.get(key) != expected:
            receipt_error = 'parser_receipt_mismatch'
    if state == 'completed' and (not isinstance(receipt.get('input_hash'), str)
                                 or not re.fullmatch(r'[a-f0-9]{64}', receipt['input_hash'])):
        receipt_error = 'parser_receipt_invalid'
    if state == 'completed' and receipt_error is None:
        query = db.get(QueryRun, query_run_id)
        capture_hash = db.scalar(select(RawCapture.raw_hash).where(RawCapture.query_id == query_run_id))
        run_id = receipt.get('run_id')
        if (capture_hash is None or not isinstance(run_id, str) or not re.fullmatch(r'[a-f0-9]{32}', run_id)
                or receipt.get('exit_code') != 0 or receipt.get('reaped') is not True):
            receipt_error = 'parser_receipt_invalid'
        else:
            expected_input = digest({key: receipt[key] for key in ('run_id', 'source_id', 'parser_version',
                'parser_digest', 'bundle_id', 'execution_digest', 'deployment_revision')} |
                {'query': query.query, 'raw_sha256': capture_hash})
            if receipt['input_hash'] != expected_input:
                receipt_error = 'parser_receipt_input_mismatch'
    code = outcome.get('error_code', outcome.get('parser_error', outcome.get('reason')))
    if code is not None and (not isinstance(code, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,79}', code) is None):
        code = 'parser_execution_failed'
    if receipt_error:
        state, code = 'failed', receipt_error
    fingerprint = digest({'selection': public_selection(_selection_dict(db, selected)),
                          'state': state, 'error_code': code, 'receipt': receipt})
    previous = db.get(ParserExecution, query_run_id)
    if previous:
        if previous.fingerprint != fingerprint:
            raise ParserDeploymentError('parser_execution_already_recorded', 409)
        if receipt_error:
            raise ParserDeploymentError(receipt_error, 409, execution_recorded=True)
        return previous
    row = ParserExecution(query_run_id=query_run_id, state=state, error_code=code,
                          receipt=receipt, fingerprint=fingerprint)
    db.add(row)
    db.flush()
    if receipt_error:
        raise ParserDeploymentError(receipt_error, 409, execution_recorded=True)
    return row


def bundle_view(row):
    return {**SCOPE, 'id': row.id, 'created_at': utc(row.created_at).isoformat(), 'origin': row.origin,
            'operator': row.operator, 'reason': row.reason, 'parsers': list(row.descriptors.values()),
            'environment': row.manifest.get('environment'), 'notice': NOTICE}


def deployment_view(row, db=None):
    from .parser_runtime import source_catalog
    gate = {'state': 'unverified', 'applicable': True, 'scope': 'golden_tire_vehicle',
            'blockers': ['golden_release_review_required'], 'report': None}
    if (source_catalog().get(row.source_id, {}).get('target_kind') == 'recall'
            and row.descriptor.get('target_kind') == 'recall'):
        gate = {'state': 'not_applicable', 'applicable': False, 'scope': 'legacy_recall_regression', 'blockers': [], 'report': None,
                'notice': '本轮 Golden 仅覆盖轮胎与车型；召回维持既有历史回归与发布审批。'}
    if db is not None and row.evaluation_review_id:
        review = db.get(ParserEvaluationReview, row.evaluation_review_id)
        if review:
            evaluation = _evaluation(db, review.evaluation_id)
            latest = _latest_review(db, evaluation.id)
            completion = _completion(db, evaluation)
            gate = _golden_gate(db, evaluation, completion)
            if (latest is None or latest.action != 'approve' or completion is None
                    or latest.completion_fingerprint != completion.fingerprint
                    or evaluation.source_id != row.source_id or evaluation.target_bundle_id != row.bundle_id):
                gate = {**gate, 'state': 'stale', 'blockers': [*gate['blockers'], 'parser_release_approval_required']}
    return {**SCOPE, 'source_id': row.source_id, 'revision': row.revision, 'state': row.state,
        'bundle_id': row.bundle_id, 'parser': row.descriptor, 'action': row.action,
        'evaluation_review_id': row.evaluation_review_id, 'rollback_revision': row.rollback_revision,
        'operator': row.operator, 'reason': row.reason, 'created_at': utc(row.created_at).isoformat(),
        'golden_gate': gate, 'notice': NOTICE}


def _reference_snapshot(db, capture):
    if capture.target_kind == 'recall':
        from .recall_reparse import recall_reference_snapshot
        reference = recall_reference_snapshot(db, capture)
        if reference and len(stable_json(reference).encode('utf-8')) > MAX_BASELINE_BYTES:
            raise ParserDeploymentError('parser_reference_too_large', 422)
        return reference
    if capture.target_kind not in {'tire', 'vehicle'}:
        raise ParserDeploymentError('unsupported_reparse_source', 422)
    if capture.target_kind == 'vehicle':
        from .vehicles import VehicleSnapshot, VehicleVerification
        statement = (select(VehicleSnapshot).join(VehicleVerification, VehicleVerification.snapshot_id == VehicleSnapshot.id)
            .where(VehicleVerification.query_id == capture.query_id, VehicleSnapshot.source_id == capture.source_id,
                   VehicleSnapshot.raw_hash == capture.raw_hash))
    else:
        statement = (select(Snapshot).join(Verification, Verification.snapshot_id == Snapshot.id)
            .where(Verification.query_id == capture.query_id, Snapshot.source_id == capture.source_id,
                   Snapshot.query_key == capture.query_key, Snapshot.raw_hash == capture.raw_hash))
    row = db.scalar(statement.limit(1))
    if row is None:
        return None
    reference = {'snapshot_id': row.id, 'raw_hash': row.raw_hash, 'observed_at': utc(row.observed_at).isoformat(),
                 'payload': deepcopy(row.payload if capture.target_kind == 'vehicle' else row.parsed_variants)}
    if len(stable_json(reference).encode('utf-8')) > MAX_BASELINE_BYTES:
        raise ParserDeploymentError('parser_reference_too_large', 422)
    return reference


def _evaluation_input(row):
    return {'source_id': row.source_id, 'target_bundle_id': row.target_bundle_id,
            'control_bundle_id': row.control_bundle_id, 'deployment_revision': row.deployment_revision,
            'bindings': row.bindings}


def _evaluation(db, evaluation_id):
    row = db.get(ParserEvaluation, evaluation_id)
    if row is None:
        raise ParserDeploymentError('parser_evaluation_not_found', 404)
    if row.input_hash != digest(_evaluation_input(row)):
        raise ParserDeploymentError('parser_evaluation_integrity_failed', 503)
    return row


def _completion_hash(evaluation, state, results, hard_blocks, gaps):
    return digest({'evaluation_id': evaluation.id, 'input_hash': evaluation.input_hash, 'state': state,
                   'results': results, 'hard_blocks': hard_blocks, 'reference_gaps': gaps})


def _completion(db, evaluation):
    row = db.get(ParserEvaluationCompletion, evaluation.id)
    if row and row.fingerprint != _completion_hash(evaluation, row.state, row.results, row.hard_blocks, row.reference_gaps):
        raise ParserDeploymentError('parser_evaluation_integrity_failed', 503)
    return row


def _golden_gate(db, evaluation, completion, *, required=False):
    from .parser_runtime import source_catalog
    if (source_catalog().get(evaluation.source_id, {}).get('target_kind') == 'recall'
            and evaluation.bindings and all(item['input'].get('target_kind') == 'recall' for item in evaluation.bindings)):
        return {'state': 'not_applicable', 'applicable': False, 'scope': 'legacy_recall_regression', 'blockers': [], 'report': None,
                'notice': '本轮 Golden 仅覆盖轮胎与车型；召回维持既有历史回归与发布审批。'}
    from .golden import evaluation_gate
    gate = evaluation_gate(db, evaluation, completion, verify_bytes=required)
    if required and gate['state'] != 'passed':
        raise ParserDeploymentError(gate['blockers'][0] if gate['blockers'] else 'golden_gate_failed', 409)
    return gate


def _latest_review(db, evaluation_id):
    return db.scalar(select(ParserEvaluationReview).where(ParserEvaluationReview.evaluation_id == evaluation_id)
                     .order_by(desc(ParserEvaluationReview.revision)).limit(1))


def _review_view(row):
    return {'id': row.id, 'revision': row.revision, 'action': row.action,
            'completion_fingerprint': row.completion_fingerprint,
            'acknowledged_reference_gaps': row.acknowledged_reference_gaps, 'operator': row.operator,
            'reason': row.reason, 'created_at': utc(row.created_at).isoformat()}


def evaluation_view(db, row, detail=True):
    completion = _completion(db, row)
    golden_gate = _golden_gate(db, row, completion)
    latest = _latest_review(db, row.id)
    current = current_deployment(db, row.source_id)
    stale = current is None or current.revision != row.deployment_revision
    state = completion.state if completion else ('unknown' if utcnow() - utc(row.created_at) > timedelta(seconds=120) else 'pending')
    result = {**SCOPE, 'id': row.id, 'source_id': row.source_id, 'target_bundle_id': row.target_bundle_id,
        'control_bundle_id': row.control_bundle_id, 'deployment_revision': row.deployment_revision,
        'deployment_stale': stale, 'state': state, 'created_at': utc(row.created_at).isoformat(),
        'capture_ids': [item['input']['capture_id'] for item in row.bindings],
        'review_revision': latest.revision if latest else 0, 'latest_review': _review_view(latest) if latest else None,
        'can_approve': bool(completion and completion.state == 'completed' and not completion.hard_blocks
                            and not stale and golden_gate['state'] in {'passed', 'not_applicable'}),
        'golden_gate': golden_gate,
        'accepted_as_facts': False, 'completion': None, 'notice': NOTICE}
    if completion:
        result['completion'] = {'fingerprint': completion.fingerprint, 'hard_blocks': completion.hard_blocks,
            'reference_gaps': completion.reference_gaps, 'completed_at': utc(completion.completed_at).isoformat()}
        if detail:
            result['completion']['results'] = completion.results
    if detail:
        result['bindings'] = row.bindings
        reviews = db.scalars(select(ParserEvaluationReview).where(ParserEvaluationReview.evaluation_id == row.id)
                            .order_by(desc(ParserEvaluationReview.revision)).limit(100)).all()
        result['reviews'] = [_review_view(item) for item in reviews]
        result['reviews_truncated'] = bool(latest and latest.revision > len(reviews))
    return result


def create_evaluation(db, payload: EvaluationCreate, actor_session_id, idempotency_key):
    key, request_hash = require_uuid(idempotency_key), digest(payload.model_dump())
    previous = db.scalar(select(ParserEvaluation).where(ParserEvaluation.actor_session_id == actor_session_id,
                                                       ParserEvaluation.idempotency_key == key))
    if previous:
        if previous.request_hash != request_hash:
            raise ParserDeploymentError('idempotency_payload_mismatch', 409)
        return evaluation_view(db, _evaluation(db, previous.id))
    target_manifest = deepcopy(_bundle(db, payload.target_bundle_id).manifest)
    current = current_deployment(db, payload.source_id)
    if current is None:
        raise ParserDeploymentError('parser_deployment_bootstrap_required', 409)
    control_manifest = deepcopy(_bundle(db, current.bundle_id).manifest)
    observed_id = current.id
    db.commit()
    target_descriptor = _verify(target_manifest, payload.source_id)
    # Control verification is performed by its execution. A broken current parser
    # must not prevent a candidate repair from being assessed against accepted raw evidence.
    QueryService(db, None).lock_ingestion()
    previous = db.scalar(select(ParserEvaluation).where(ParserEvaluation.actor_session_id == actor_session_id,
                                                       ParserEvaluation.idempotency_key == key))
    if previous:
        if previous.request_hash != request_hash:
            raise ParserDeploymentError('idempotency_payload_mismatch', 409)
        db.commit()
        return evaluation_view(db, _evaluation(db, previous.id))
    current = current_deployment(db, payload.source_id)
    if current.id != observed_id or current.revision != payload.expected_deployment_revision:
        raise ParserDeploymentError('parser_deployment_revision_conflict', 409)
    bindings = []
    golden_bindings = {}
    if payload.golden_set_id is not None:
        from .golden import evaluation_bindings
        golden_bindings = evaluation_bindings(db, payload.source_id, payload.capture_ids, payload.golden_set_id,
            payload.expected_golden_set_revision, payload.golden_set_fingerprint, target_descriptor)
    for capture_id in payload.capture_ids:
        capture = db.get(RawCapture, capture_id)
        if capture is None:
            raise ParserDeploymentError('capture_not_found', 404)
        if capture.source_id != payload.source_id:
            raise ParserDeploymentError('parser_evaluation_source_mismatch', 422)
        source_input = capture_input(db, capture, {payload.source_id: target_descriptor})
        binding = {'input': source_input, 'reference': _reference_snapshot(db, capture)}
        if golden_bindings:
            binding['golden'] = golden_bindings[capture_id]
        bindings.append(binding)
    row = ParserEvaluation(id=uid(), actor_session_id=actor_session_id, idempotency_key=key, request_hash=request_hash,
        source_id=payload.source_id, target_bundle_id=payload.target_bundle_id, control_bundle_id=current.bundle_id,
        deployment_revision=current.revision, bindings=bindings)
    row.input_hash = digest(_evaluation_input(row))
    db.add(row)
    db.commit()
    results, hard_blocks, gaps = [], [], []
    for binding in bindings:
        source_input, reference = binding['input'], binding['reference']
        capture_id = source_input['capture_id']
        item = {'capture_id': capture_id, 'reference_kind': 'accepted_same_raw' if reference else 'control_same_raw',
                'candidate': None, 'control': None, 'quality': None, 'diff': None,
                'candidate_receipt': {}, 'control_receipt': {}, 'candidate_error': None, 'control_error': None}
        if binding.get('golden'):
            item['golden_report'] = None
        try:
            raw, _ = checked_capture_bytes(db, db.get(RawCapture, capture_id))
            if len(raw) != source_input['byte_count'] or hashlib.sha256(raw).hexdigest() != source_input['raw_hash']:
                raise ValueError('frozen capture mismatch')
            db.commit()
        except Exception:
            db.rollback()
            item['candidate_error'] = 'capture_integrity_failed'
            hard_blocks.append({'capture_id': capture_id, 'code': 'capture_integrity_failed'})
            results.append(item)
            continue
        for kind, manifest in (('control', control_manifest), ('candidate', target_manifest)):
            try:
                descriptor = _verify(manifest, row.source_id)
                from .parser_runtime import parse_isolated
                parsed = asyncio.run(parse_isolated(row.source_id, raw, source_input['query'],
                    descriptor['parser_version'], descriptor['parser_digest'], bundle_manifest=manifest,
                    deployment_revision=row.deployment_revision))
                item[kind + '_receipt'] = parsed['receipt']
                item[kind] = validate_candidate(parsed['payload'], source_input, raw)
            except Exception as error:
                item[kind + '_error'] = safe_code(error, 'candidate_validation_failed')
                item[kind + '_receipt'] = getattr(error, 'receipt', {}) or {}
        if reference is None:
            gaps.append(capture_id)
        if item['candidate'] is None:
            hard_blocks.append({'capture_id': capture_id, 'code': item['candidate_error'] or 'candidate_validation_failed'})
        else:
            baseline = reference or ({'payload': item['control']} if item['control'] is not None else None)
            if baseline is None:
                item['reference_kind'] = 'unavailable'
            item['quality'], item['diff'] = compare_candidate(baseline, item['candidate'], source_input['target_kind'])
            hard_blocks.extend({'capture_id': capture_id, 'code': code} for code in item['quality']['reason_codes'])
            if binding.get('golden'):
                from .golden_checks import compare_case
                from .golden import receipt_matches
                case = binding['golden']['case']
                item['golden_report'] = compare_case(case['kind'], case['expected'], item['candidate'],
                    {**source_input, 'case_id': case['case_id']})
                if not receipt_matches(row, binding, item['candidate_receipt']):
                    hard_blocks.append({'capture_id': capture_id, 'code': 'golden_candidate_receipt_mismatch'})
        results.append(item)
    if golden_bindings:
        from .golden_checks import aggregate_reports
        report = aggregate_reports([item.get('golden_report') for item in results], expected_case_count=len(bindings))
        if report['state'] != 'passed':
            hard_blocks.append({'code': 'golden_assertions_failed' if report['state'] == 'failed' else 'golden_coverage_inconclusive'})
    state = 'failed' if any(item['candidate_error'] for item in results) else 'completed'
    QueryService(db, None).lock_ingestion()
    db.add(ParserEvaluationCompletion(evaluation_id=row.id, state=state, results=results,
        hard_blocks=hard_blocks, reference_gaps=gaps,
        fingerprint=_completion_hash(row, state, results, hard_blocks, gaps)))
    db.commit()
    return evaluation_view(db, row)


def review_evaluation(db, evaluation_id, payload: EvaluationReviewCreate, actor_session_id):
    QueryService(db, None).lock_ingestion()
    evaluation = _evaluation(db, evaluation_id)
    completion = _completion(db, evaluation)
    if completion is None:
        raise ParserDeploymentError('parser_evaluation_not_completed', 409)
    latest = _latest_review(db, evaluation.id)
    revision = latest.revision if latest else 0
    if revision != payload.expected_revision:
        raise ParserDeploymentError('parser_review_revision_conflict', 409)
    if completion.fingerprint != payload.completion_fingerprint:
        raise ParserDeploymentError('parser_review_fingerprint_mismatch', 409)
    if not payload.acknowledged:
        raise ParserDeploymentError('parser_review_acknowledgement_required', 422)
    if payload.action == 'approve':
        current = current_deployment(db, evaluation.source_id)
        if current is None or current.revision != evaluation.deployment_revision:
            raise ParserDeploymentError('parser_evaluation_stale', 409)
        if completion.state != 'completed' or completion.hard_blocks:
            raise ParserDeploymentError('parser_evaluation_gate_failed', 409)
        _golden_gate(db, evaluation, completion, required=True)
        if completion.reference_gaps and not payload.acknowledge_reference_gaps:
            raise ParserDeploymentError('parser_reference_gap_acknowledgement_required', 422)
    db.add(ParserEvaluationReview(id=uid(), evaluation_id=evaluation.id, revision=revision + 1, action=payload.action,
        completion_fingerprint=completion.fingerprint, acknowledged_reference_gaps=payload.acknowledge_reference_gaps,
        operator=payload.operator, reason=payload.reason, actor_session_id=actor_session_id))
    db.commit()
    return evaluation_view(db, evaluation)


def _approved(db, evaluation_id, source_id, bundle_id, expected_review_revision=None, expected_deployment_revision=None):
    evaluation = _evaluation(db, evaluation_id)
    completion = _completion(db, evaluation)
    review = _latest_review(db, evaluation.id)
    if (evaluation.source_id != source_id or evaluation.target_bundle_id != bundle_id
            or completion is None or completion.state != 'completed' or completion.hard_blocks
            or review is None or review.action != 'approve' or review.completion_fingerprint != completion.fingerprint
            or (completion.reference_gaps and not review.acknowledged_reference_gaps)):
        raise ParserDeploymentError('parser_release_approval_required', 409)
    if expected_review_revision is not None and review.revision != expected_review_revision:
        raise ParserDeploymentError('parser_review_revision_conflict', 409)
    if expected_deployment_revision is not None and evaluation.deployment_revision != expected_deployment_revision:
        raise ParserDeploymentError('parser_evaluation_stale', 409)
    _golden_gate(db, evaluation, completion, required=True)
    return review


def transition_deployment(db, source_id, payload: DeploymentTransition, actor_session_id, idempotency_key):
    key = require_uuid(idempotency_key)
    request_hash = digest({'source_id': source_id, **payload.model_dump()})
    previous = db.scalar(select(ParserDeploymentRevision).where(ParserDeploymentRevision.actor_session_id == actor_session_id,
                                                                ParserDeploymentRevision.idempotency_key == key))
    if previous:
        if previous.request_hash != request_hash:
            raise ParserDeploymentError('idempotency_payload_mismatch', 409)
        return deployment_view(previous, db)
    current = current_deployment(db, source_id)
    if current is None:
        raise ParserDeploymentError('parser_deployment_bootstrap_required', 409)
    target = current
    if payload.action == 'rollback':
        target = db.scalar(select(ParserDeploymentRevision).where(ParserDeploymentRevision.source_id == source_id,
                                                                  ParserDeploymentRevision.revision == payload.target_revision))
        if target is None or target.state != 'active' or target.revision >= current.revision:
            raise ParserDeploymentError('parser_rollback_target_invalid', 409)
    target_bundle_id = payload.target_bundle_id if payload.action == 'activate' else target.bundle_id
    manifest = deepcopy(_bundle(db, target_bundle_id).manifest)
    target_id = target.id
    db.commit()
    # Pausing must remain available even when the active package is damaged.
    descriptor = _verify(manifest, source_id) if payload.action != 'pause' else deepcopy(current.descriptor)
    QueryService(db, None).lock_ingestion()
    previous = db.scalar(select(ParserDeploymentRevision).where(ParserDeploymentRevision.actor_session_id == actor_session_id,
                                                                ParserDeploymentRevision.idempotency_key == key))
    if previous:
        if previous.request_hash != request_hash:
            raise ParserDeploymentError('idempotency_payload_mismatch', 409)
        db.commit()
        return deployment_view(previous, db)
    current = current_deployment(db, source_id)
    if current.revision != payload.expected_revision:
        raise ParserDeploymentError('parser_deployment_revision_conflict', 409)
    review_id = current.evaluation_review_id
    if payload.action == 'activate':
        approved = _approved(db, payload.evaluation_id, source_id, target_bundle_id,
                             payload.expected_review_revision, current.revision)
        review_id = approved.id
    elif payload.action == 'rollback':
        target = db.get(ParserDeploymentRevision, target_id)
        review_id = target.evaluation_review_id
        if review_id:
            original = db.get(ParserEvaluationReview, review_id)
            review_id = _approved(db, original.evaluation_id, source_id, target_bundle_id).id
        elif target.descriptor.get('target_kind') == 'recall' and _recall_bootstrap_trust(db, source_id, target_bundle_id):
            pass
        else:
            raise ParserDeploymentError('golden_release_review_required', 409)
    elif payload.action == 'pause':
        if current.state != 'active':
            raise ParserDeploymentError('parser_deployment_already_paused', 409)
    elif payload.action == 'resume':
        if current.state != 'paused':
            raise ParserDeploymentError('parser_deployment_not_paused', 409)
        if review_id:
            original = db.get(ParserEvaluationReview, review_id)
            review_id = _approved(db, original.evaluation_id, source_id, target_bundle_id).id
        elif current.descriptor.get('target_kind') == 'recall' and _recall_bootstrap_trust(db, source_id, target_bundle_id):
            pass
        else:
            raise ParserDeploymentError('golden_release_review_required', 409)
    row = ParserDeploymentRevision(id=uid(), source_id=source_id, revision=current.revision + 1,
        state='paused' if payload.action == 'pause' else 'active', bundle_id=target_bundle_id,
        descriptor=descriptor, action=payload.action, evaluation_review_id=review_id,
        rollback_revision=payload.target_revision if payload.action == 'rollback' else None,
        actor_session_id=actor_session_id, idempotency_key=key, request_hash=request_hash,
        operator=payload.operator, reason=payload.reason)
    db.add(row)
    db.commit()
    return deployment_view(row, db)


def _recall_bootstrap_trust(db, source_id, bundle_id):
    """Preserve the recall-only initial trust path; it never claims Golden coverage."""
    from .parser_runtime import source_catalog
    return source_catalog().get(source_id, {}).get('target_kind') == 'recall' and db.scalar(
        select(ParserDeploymentRevision.id).where(ParserDeploymentRevision.source_id == source_id,
            ParserDeploymentRevision.revision == 1, ParserDeploymentRevision.action == 'bootstrap',
            ParserDeploymentRevision.bundle_id == bundle_id)) is not None


def register_parser_release_routes(app: FastAPI):
    async def deployment_error(_request, error):
        return JSONResponse(status_code=error.status_code, content={'detail': {'code': error.code}})
    app.add_exception_handler(ParserDeploymentError, deployment_error)

    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/parser-bundles')
    def bundles(mode: Literal['history'] = Query(...), offset: int = Query(0, ge=0),
                limit: int = Query(10, ge=1, le=25), db: Session = Depends(get_db)):
        rows = db.scalars(select(ParserBundle).order_by(desc(ParserBundle.created_at), ParserBundle.id).offset(offset).limit(limit)).all()
        return {**SCOPE, 'items': [bundle_view(row) for row in rows], 'offset': offset, 'limit': limit,
                'total': db.scalar(select(func.count()).select_from(ParserBundle))}

    @app.get('/v1/parser-bundles/{bundle_id}')
    def bundle(bundle_id: str, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        return bundle_view(_bundle(db, bundle_id))

    @app.get('/v1/parser-deployments/{source_id}')
    def deployment(source_id: str, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        current = current_deployment(db, source_id)
        if current is None:
            return {**SCOPE, 'source_id': source_id, 'revision': 0, 'state': 'builtin_unsealed',
                    'history': [], 'history_truncated': False, 'notice': NOTICE}
        history = db.scalars(select(ParserDeploymentRevision).where(ParserDeploymentRevision.source_id == source_id)
                            .order_by(desc(ParserDeploymentRevision.revision)).limit(100)).all()
        return {**deployment_view(current, db), 'history': [deployment_view(row, db) for row in history],
                'history_truncated': current.revision > len(history)}

    @app.post('/v1/parser-deployments/{source_id}/bootstrap', status_code=201)
    def bootstrap(source_id: str, payload: SignedAction, db: Session = Depends(get_db)):
        return deployment_view(bootstrap_source(db, source_id, payload.operator, payload.reason), db)

    @app.post('/v1/parser-deployments/{source_id}/transitions', status_code=201)
    def transition(source_id: str, payload: DeploymentTransition, request: Request,
                   idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db: Session = Depends(get_db)):
        return transition_deployment(db, source_id, payload, request.state.session_id, idempotency_key)

    @app.post('/v1/parser-evaluations', status_code=201)
    def evaluate(payload: EvaluationCreate, request: Request,
                 idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db: Session = Depends(get_db)):
        return create_evaluation(db, payload, request.state.session_id, idempotency_key)

    @app.get('/v1/parser-evaluations')
    def evaluations(mode: Literal['history'] = Query(...), source_id: str | None = Query(None, max_length=80),
                    offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=25), db: Session = Depends(get_db)):
        filters = [ParserEvaluation.source_id == source_id] if source_id else []
        rows = db.scalars(select(ParserEvaluation).where(*filters).order_by(desc(ParserEvaluation.created_at))
                          .offset(offset).limit(limit)).all()
        return {**SCOPE, 'items': [evaluation_view(db, _evaluation(db, row.id), False) for row in rows],
                'total': db.scalar(select(func.count()).select_from(ParserEvaluation).where(*filters)),
                'offset': offset, 'limit': limit}

    @app.get('/v1/parser-evaluations/{evaluation_id}')
    def evaluation(evaluation_id: str, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        return evaluation_view(db, _evaluation(db, evaluation_id))

    @app.get('/v1/parser-executions/{query_id}')
    def execution(query_id: str, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        selected = db.get(ParserSelection, query_id)
        if selected is None:
            raise ParserDeploymentError('parser_selection_not_found', 404)
        query = db.get(QueryRun, query_id)
        public = public_selection(_selection_dict(db, selected))
        completed = db.get(ParserExecution, query_id)
        result = {**SCOPE, 'data_state': 'local_snapshot', 'selection': public,
                  'query_state': query.state, 'query_reason': query.reason, 'completion': None}
        if completed:
            fingerprint = digest({'selection': public, 'state': completed.state,
                                  'error_code': completed.error_code, 'receipt': completed.receipt})
            if fingerprint != completed.fingerprint:
                raise ParserDeploymentError('parser_execution_integrity_failed', 503)
            result['completion'] = {'state': completed.state, 'error_code': completed.error_code,
                'receipt': completed.receipt, 'fingerprint': fingerprint,
                'completed_at': utc(completed.created_at).isoformat()}
        return result

    @app.post('/v1/parser-evaluations/{evaluation_id}/reviews', status_code=201)
    def review(evaluation_id: str, payload: EvaluationReviewCreate, request: Request, db: Session = Depends(get_db)):
        return review_evaluation(db, evaluation_id, payload, request.state.session_id)


def main():
    """Trusted local import plus the same gate service used by HTTP; never load supplied code."""
    parser = argparse.ArgumentParser(description='本机受信 Parser 封存与发布管理')
    parser.add_argument('action', choices=['import-deployed', 'bootstrap', 'evaluate', 'review', 'transition', 'list'])
    parser.add_argument('--request', help='本机 JSON 请求文件，仅接受 ID、操作和署名，不接受代码或源码路径')
    parser.add_argument('--source')
    parser.add_argument('--evaluation')
    parser.add_argument('--idempotency-key')
    args = parser.parse_args()
    payload = {}
    if args.request:
        from pathlib import Path
        with Path(args.request).open('rb') as stream:
            raw = stream.read(32769)
        if len(raw) > 32768:
            parser.error('请求文件过大')
        from .parser_runtime import strict_json
        payload = strict_json(raw)
    from .main import create_app
    app = create_app()
    database = app.state.database
    database.initialize()
    try:
        with database.sessions() as db:
            if args.action == 'import-deployed':
                signed = SignedAction.model_validate(payload)
                result = register_deployed_bundle(db, signed.operator, signed.reason)
            elif args.action == 'bootstrap':
                signed = SignedAction.model_validate(payload)
                result = deployment_view(bootstrap_source(db, args.source, signed.operator, signed.reason), db)
            elif args.action == 'evaluate':
                result = create_evaluation(db, EvaluationCreate.model_validate(payload), 'local-cli', args.idempotency_key)
            elif args.action == 'review':
                result = review_evaluation(db, args.evaluation, EvaluationReviewCreate.model_validate(payload), 'local-cli')
            elif args.action == 'transition':
                result = transition_deployment(db, args.source, DeploymentTransition.model_validate(payload), 'local-cli', args.idempotency_key)
            else:
                result = {'bundles': [bundle_view(row) for row in db.scalars(select(ParserBundle))]}
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except ParserDeploymentError as error:
        print(json.dumps({'error_code': error.code}, ensure_ascii=False))
        raise SystemExit(1) from None
    finally:
        database.close()


if __name__ == '__main__':
    main()
