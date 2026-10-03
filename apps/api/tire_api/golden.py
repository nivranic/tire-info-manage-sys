"""Human-reviewed Golden evidence. No fetching, fact adoption or executable input."""
from copy import deepcopy
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator
from sqlalchemy import desc, func, select

from .captures import checked_capture_bytes
from .db import RawCapture, uid, utc
from .domain import StrictModel, digest, stable_json
from .golden_models import GoldenCase, GoldenCaseRevision, GoldenCaseReview, GoldenSetRevision
from .reparse import capture_input
from .service import QueryService

SCOPE = {'scope': 'local_workspace', 'data_state': 'local_snapshot', 'accepted_as_facts': False,
         'review_identity': 'self_reported_local_operator', 'test_event_supported': False}
NOTICE = ('Golden 预期须由人工对照原始证据填写并签署；本机署名不是身份认证或数字签名。'
          '冻结集仅覆盖同源 1–3 份轮胎或车型原文，不代表完整生产 Golden 集或官网在线核验。')
MAX_EXPECTED_BYTES = 500_000


class GoldenError(Exception):
    def __init__(self, code, status_code=409):
        self.code, self.status_code = code, status_code
        super().__init__(code)


class Signed(StrictModel):
    operator: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator('operator', 'reason')
    @classmethod
    def nonempty_text(cls, value):
        if not value.strip() or '\x00' in value:
            raise ValueError('请填写非空文本，不能包含空字符')
        value.encode('utf-8', errors='strict')
        return value


class Fence(Signed):
    expected_revision: StrictInt = Field(ge=0)
    expected_fingerprint: str | None = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def exact_fence(self):
        if (self.expected_revision == 0) != (self.expected_fingerprint is None):
            raise ValueError('首次操作使用版本 0 和 null 指纹；后续操作须绑定当前版本与指纹')
        return self


class CaseContent(Fence):
    title: str = Field(min_length=1, max_length=200)
    capture_id: str = Field(min_length=1, max_length=64)
    evidence_note: str = Field(min_length=1, max_length=2000)
    expected: dict

    @field_validator('title', 'evidence_note')
    @classmethod
    def content_text(cls, value):
        return Signed.nonempty_text(value)


class CaseCreate(CaseContent):
    kind: Literal['tire', 'vehicle']
    source_id: str = Field(min_length=1, max_length=80)


class CaseReviewCreate(Fence):
    case_revision: StrictInt = Field(ge=1)
    case_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    action: Literal['approve', 'reject', 'revoke']
    acknowledged: StrictBool


class CaseReference(StrictModel):
    case_id: str = Field(min_length=1, max_length=64)
    case_revision: StrictInt = Field(ge=1)
    case_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    review_revision: StrictInt = Field(ge=1)
    review_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


class SetCreate(Fence):
    title: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=80)
    case_refs: list[CaseReference] = Field(min_length=1, max_length=3)
    acknowledged: StrictBool

    @field_validator('title')
    @classmethod
    def title_text(cls, value):
        return Signed.nonempty_text(value)


class SetRevise(SetCreate):
    action: Literal['freeze', 'revoke']
    case_refs: list[CaseReference] = Field(default_factory=list, max_length=3)


def _key(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise GoldenError('invalid_idempotency_key', 422) from None


def _hash_payload(operation, payload, target=None):
    return digest({'operation': operation, 'target': target, 'payload': payload.model_dump(mode='json')})


def _replay(db, model, actor, key, request_hash):
    previous = db.scalar(select(model).where(model.actor_session_id == actor, model.idempotency_key == key))
    if previous and previous.request_hash != request_hash:
        raise GoldenError('idempotency_payload_mismatch')
    return previous


def _fence(row, payload, code):
    if payload.expected_revision != (row.revision if row else 0):
        raise GoldenError(code + '_revision_conflict')
    if payload.expected_fingerprint != (row.fingerprint if row else None):
        raise GoldenError(code + '_fingerprint_mismatch')


def _case(db, case_id):
    row = db.get(GoldenCase, case_id)
    if row is None:
        raise GoldenError('golden_case_not_found', 404)
    return row


def _latest_content(db, case_id):
    return db.scalar(select(GoldenCaseRevision).where(GoldenCaseRevision.case_id == case_id)
                     .order_by(desc(GoldenCaseRevision.revision)).limit(1))


def _latest_review(db, case_id):
    return db.scalar(select(GoldenCaseReview).where(GoldenCaseReview.case_id == case_id)
                     .order_by(desc(GoldenCaseReview.revision)).limit(1))


def _latest_set(db, set_id):
    return db.scalar(select(GoldenSetRevision).where(GoldenSetRevision.set_id == set_id)
                     .order_by(desc(GoldenSetRevision.revision)).limit(1))


def _content_hash(case, row):
    return digest({'case_id': case.id, 'kind': case.kind, 'source_id': case.source_id,
        **{key: getattr(row, key) for key in ('revision', 'title', 'capture_id', 'input', 'evidence_note',
                                           'expected', 'previous_fingerprint', 'operator', 'reason')}})


def _review_hash(row):
    return digest({key: getattr(row, key) for key in ('case_id', 'case_revision', 'case_fingerprint', 'revision',
                  'action', 'previous_fingerprint', 'operator', 'reason')})


def _set_hash(row):
    return digest({key: getattr(row, key) for key in ('set_id', 'revision', 'action', 'title', 'source_id', 'kind',
                  'cases', 'previous_fingerprint', 'operator', 'reason')})


def _expected(kind, value):
    try:
        from .golden_checks import validate_expected
        encoded = stable_json(value).encode('utf-8')
        if len(encoded) > MAX_EXPECTED_BYTES or b'\\u0000' in encoded:
            raise ValueError('bounded expected content')
        return validate_expected(kind, value)
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise GoldenError('golden_expected_invalid', 422) from None


def _capture(db, capture_id, source_id, kind, *, verify_bytes=True):
    from .parser_runtime import source_catalog
    capture = db.get(RawCapture, capture_id)
    if capture is None:
        raise GoldenError('capture_not_found', 404)
    if capture.source_id != source_id or capture.target_kind != kind or kind not in {'tire', 'vehicle'}:
        raise GoldenError('golden_capture_scope_mismatch', 422)
    catalog = source_catalog()  # Catalog labels only; never resolve/execute an installed bundle here.
    if catalog.get(source_id, {}).get('target_kind') != kind:
        raise GoldenError('golden_source_unsupported', 422)
    try:
        value = capture_input(db, capture, catalog)
        if verify_bytes:
            checked_capture_bytes(db, capture)
    except Exception:
        raise GoldenError('golden_capture_integrity_failed', 503) from None
    return value


def _checked_content(case, row):
    if row is None or row.fingerprint != _content_hash(case, row):
        raise GoldenError('golden_content_integrity_failed', 503)
    if stable_json(_expected(case.kind, row.expected)) != stable_json(row.expected):
        raise GoldenError('golden_expected_contract_changed')
    return row


def _checked_review(row):
    if row and row.fingerprint != _review_hash(row):
        raise GoldenError('golden_review_integrity_failed', 503)
    return row


def _review_view(row):
    if row is None:
        return None
    _checked_review(row)
    return {key: getattr(row, key) for key in ('case_revision', 'case_fingerprint', 'revision', 'fingerprint',
        'action', 'operator', 'reason')} | {'created_at': utc(row.created_at).isoformat()}


def case_view(db, case, content=None, *, detail=True):
    current = _latest_content(db, case.id)
    row = _checked_content(case, content or current)
    review = _checked_review(_latest_review(db, case.id))
    applies = bool(review and review.case_revision == row.revision and review.case_fingerprint == row.fingerprint)
    status = {'approve': 'approved', 'reject': 'rejected', 'revoke': 'revoked'}.get(review.action, 'pending') if applies else 'pending'
    result = {**SCOPE, 'id': case.id, 'kind': case.kind, 'source_id': case.source_id, 'title': row.title,
        'revision': row.revision, 'fingerprint': row.fingerprint, 'current_revision': current.revision,
        'is_current': row.id == current.id, 'capture_id': row.capture_id, 'evidence_note': row.evidence_note,
        'review_revision': review.revision if review else 0, 'review_fingerprint': review.fingerprint if review else None,
        'latest_review': _review_view(review), 'status': status, 'operator': row.operator, 'reason': row.reason,
        'created_at': utc(row.created_at).isoformat(), 'notice': NOTICE}
    if detail:
        result.update(expected=row.expected, input=row.input)
        history = db.scalars(select(GoldenCaseRevision).where(GoldenCaseRevision.case_id == case.id)
                             .order_by(desc(GoldenCaseRevision.revision)).limit(100)).all()
        result['history'] = [{'revision': item.revision, 'fingerprint': item.fingerprint, 'title': item.title,
            'capture_id': item.capture_id, 'operator': item.operator, 'reason': item.reason,
            'created_at': utc(item.created_at).isoformat()} for item in history]
        result['history_truncated'] = current.revision > len(history)
        reviews = db.scalars(select(GoldenCaseReview).where(GoldenCaseReview.case_id == case.id)
                             .order_by(desc(GoldenCaseReview.revision)).limit(100)).all()
        result['reviews'] = [_review_view(item) for item in reviews]
        result['reviews_truncated'] = bool(review and review.revision > len(reviews))
    return result


def write_case(db, payload, actor, idempotency_key, case_id=None):
    key = _key(idempotency_key)
    request_hash = _hash_payload('revise' if case_id else 'create', payload, case_id)
    QueryService(db, None).lock_ingestion()
    replay = _replay(db, GoldenCaseRevision, actor, key, request_hash)
    if replay:
        return case_view(db, _case(db, replay.case_id), replay)
    case = _case(db, case_id) if case_id else GoldenCase(id=uid(), kind=payload.kind, source_id=payload.source_id)
    old = _latest_content(db, case.id) if case_id else None
    _fence(old, payload, 'golden_case')
    if old:
        _checked_content(case, old)
    expected = _expected(case.kind, payload.expected)
    source_input = _capture(db, payload.capture_id, case.source_id, case.kind)
    if not case_id:
        db.add(case)
        db.flush()
    row = GoldenCaseRevision(case_id=case.id, revision=(old.revision if old else 0) + 1,
        title=payload.title, capture_id=payload.capture_id, input=source_input, evidence_note=payload.evidence_note,
        expected=expected, previous_fingerprint=old.fingerprint if old else None,
        operator=payload.operator, reason=payload.reason, actor_session_id=actor, idempotency_key=key,
        request_hash=request_hash)
    row.fingerprint = _content_hash(case, row)
    db.add(row)
    db.commit()
    return case_view(db, case, row)


def review_case(db, case_id, payload, actor, idempotency_key):
    key, request_hash = _key(idempotency_key), _hash_payload('review', payload, case_id)
    QueryService(db, None).lock_ingestion()
    replay = _replay(db, GoldenCaseReview, actor, key, request_hash)
    case = _case(db, case_id)
    if replay:
        return {**case_view(db, case), 'recorded_review': _review_view(replay)}
    content = _checked_content(case, _latest_content(db, case_id))
    latest = _checked_review(_latest_review(db, case_id))
    _fence(latest, payload, 'golden_review')
    if content.revision != payload.case_revision or content.fingerprint != payload.case_fingerprint:
        raise GoldenError('golden_case_revision_conflict')
    if not payload.acknowledged:
        raise GoldenError('golden_human_acknowledgement_required', 422)
    # Even reject/revoke is bound to exact content. Approval additionally requires readable original bytes.
    if payload.action == 'approve':
        value = _capture(db, content.capture_id, case.source_id, case.kind)
        if value != content.input:
            raise GoldenError('golden_capture_binding_changed')
    row = GoldenCaseReview(case_id=case_id, case_revision=content.revision, case_fingerprint=content.fingerprint,
        revision=(latest.revision if latest else 0) + 1, action=payload.action,
        previous_fingerprint=latest.fingerprint if latest else None, operator=payload.operator, reason=payload.reason,
        actor_session_id=actor, idempotency_key=key, request_hash=request_hash)
    row.fingerprint = _review_hash(row)
    db.add(row)
    db.commit()
    return {**case_view(db, case), 'recorded_review': _review_view(row)}


def _case_binding(db, reference, source_id, *, verify_bytes=True):
    case = _case(db, reference['case_id'])
    content = _checked_content(case, _latest_content(db, case.id))
    review = _checked_review(_latest_review(db, case.id))
    if case.source_id != source_id:
        raise GoldenError('golden_set_source_mismatch', 422)
    if content.revision != reference['case_revision'] or content.fingerprint != reference['case_fingerprint']:
        raise GoldenError('golden_case_stale')
    if (review is None or review.revision != reference['review_revision'] or review.fingerprint != reference['review_fingerprint']
            or review.case_revision != content.revision or review.case_fingerprint != content.fingerprint
            or review.action != 'approve'):
        raise GoldenError('golden_case_review_required')
    if verify_bytes and _capture(db, content.capture_id, case.source_id, case.kind) != content.input:
        raise GoldenError('golden_capture_binding_changed')
    return {**reference, 'kind': case.kind, 'source_id': case.source_id, 'capture_id': content.capture_id,
        'title': content.title, 'evidence_note': content.evidence_note, 'input': deepcopy(content.input),
        'expected': deepcopy(content.expected), 'review': _review_view(review)}


def _case_ref(binding):
    return {key: binding[key] for key in CaseReference.model_fields}


def checked_set(db, set_id, revision=None, fingerprint=None, *, verify_bytes=True):
    row = _latest_set(db, set_id)
    if row is None:
        raise GoldenError('golden_set_not_found', 404)
    if row.fingerprint != _set_hash(row):
        raise GoldenError('golden_set_integrity_failed', 503)
    if ((revision is not None and row.revision != revision)
            or (fingerprint is not None and row.fingerprint != fingerprint)):
        raise GoldenError('golden_set_stale')
    if row.action != 'freeze':
        raise GoldenError('golden_set_revoked')
    if not 1 <= len(row.cases) <= 3 or len({item['capture_id'] for item in row.cases}) != len(row.cases):
        raise GoldenError('golden_set_coverage_invalid')
    for frozen in row.cases:
        current = _case_binding(db, _case_ref(frozen), row.source_id, verify_bytes=verify_bytes)
        if stable_json(current) != stable_json(frozen) or current['kind'] != row.kind:
            raise GoldenError('golden_case_binding_changed')
    return row


def set_snapshot(row):
    return {'set_id': row.set_id, 'set_revision': row.revision, 'set_fingerprint': row.fingerprint,
        'source_id': row.source_id, 'kind': row.kind, 'cases': deepcopy(row.cases)}


def set_view(db, row, *, detail=True):
    if row.fingerprint != _set_hash(row):
        raise GoldenError('golden_set_integrity_failed', 503)
    blockers = []
    try:
        checked_set(db, row.set_id, row.revision, row.fingerprint, verify_bytes=False)
    except GoldenError as error:
        blockers.append(error.code)
    result = {**SCOPE, 'id': row.set_id, 'title': row.title, 'source_id': row.source_id, 'kind': row.kind,
        'revision': row.revision, 'fingerprint': row.fingerprint, 'action': row.action,
        'state': 'frozen' if row.action == 'freeze' else 'revoked', 'case_refs': [_case_ref(item) for item in row.cases],
        'capture_ids': [item['capture_id'] for item in row.cases], 'eligible': not blockers, 'blockers': blockers,
        'operator': row.operator, 'reason': row.reason, 'created_at': utc(row.created_at).isoformat(), 'notice': NOTICE}
    if detail:
        result['cases'] = row.cases
        history = db.scalars(select(GoldenSetRevision).where(GoldenSetRevision.set_id == row.set_id)
                             .order_by(desc(GoldenSetRevision.revision)).limit(100)).all()
        result['history'] = [{'revision': item.revision, 'fingerprint': item.fingerprint, 'action': item.action,
            'operator': item.operator, 'reason': item.reason, 'created_at': utc(item.created_at).isoformat()} for item in history]
        result['history_truncated'] = bool(history and history[0].revision > len(history))
    return result


def write_set(db, payload, actor, idempotency_key, set_id=None):
    key, request_hash = _key(idempotency_key), _hash_payload('set-revise' if set_id else 'set-create', payload, set_id)
    QueryService(db, None).lock_ingestion()
    replay = _replay(db, GoldenSetRevision, actor, key, request_hash)
    if replay:
        return set_view(db, replay)
    old = _latest_set(db, set_id) if set_id else None
    if set_id and old is None:
        raise GoldenError('golden_set_not_found', 404)
    _fence(old, payload, 'golden_set')
    if old and old.fingerprint != _set_hash(old):
        raise GoldenError('golden_set_integrity_failed', 503)
    if not payload.acknowledged:
        raise GoldenError('golden_human_acknowledgement_required', 422)
    action = payload.action if set_id else 'freeze'
    if old and payload.source_id != old.source_id:
        raise GoldenError('golden_set_source_mismatch', 422)
    if action == 'revoke':
        if old.action == 'revoke':
            raise GoldenError('golden_set_already_revoked')
        if payload.case_refs:
            raise GoldenError('golden_revoke_cannot_replace_members', 422)
        cases = deepcopy(old.cases)
    else:
        if not payload.case_refs or len({item.case_id for item in payload.case_refs}) != len(payload.case_refs):
            raise GoldenError('golden_set_coverage_invalid', 422)
        cases = [_case_binding(db, item.model_dump(), payload.source_id) for item in payload.case_refs]
        if len({item['capture_id'] for item in cases}) != len(cases) or len({item['kind'] for item in cases}) != 1:
            raise GoldenError('golden_set_coverage_invalid', 422)
    row = GoldenSetRevision(set_id=set_id or uid(), revision=(old.revision if old else 0) + 1,
        action=action, title=payload.title, source_id=payload.source_id, kind=cases[0]['kind'], cases=cases,
        previous_fingerprint=old.fingerprint if old else None, operator=payload.operator, reason=payload.reason,
        actor_session_id=actor, idempotency_key=key, request_hash=request_hash)
    row.fingerprint = _set_hash(row)
    db.add(row)
    db.commit()
    return set_view(db, row)


def evaluation_bindings(db, source_id, capture_ids, set_id, revision, fingerprint, parser_descriptor):
    """Freeze the entire bounded set; selection cannot silently omit a reviewed member."""
    from .golden_checks import contract_descriptor
    row = checked_set(db, set_id, revision, fingerprint)
    if row.source_id != source_id:
        raise GoldenError('golden_set_source_mismatch', 422)
    if set(capture_ids) != {item['capture_id'] for item in row.cases}:
        raise GoldenError('golden_set_capture_mismatch', 422)
    common = {'set_id': row.set_id, 'set_revision': row.revision, 'set_fingerprint': row.fingerprint,
              'contract': contract_descriptor(), 'parser': deepcopy(parser_descriptor)}
    return {item['capture_id']: {**deepcopy(common), 'case': deepcopy(item)} for item in row.cases}


def receipt_matches(evaluation, binding, receipt):
    """Check the candidate receipt against its frozen package and exact raw/query input."""
    if not isinstance(receipt, dict):
        return False
    parser = binding['golden']['parser']
    expected = {'source_id': evaluation.source_id, 'bundle_id': evaluation.target_bundle_id,
                'deployment_revision': evaluation.deployment_revision,
                **{key: parser[key] for key in ('parser_version', 'parser_digest', 'execution_digest')}}
    if any(receipt.get(key) != value for key, value in expected.items()):
        return False
    run_id = receipt.get('run_id')
    if not isinstance(run_id, str) or len(run_id) != 32 or any(ch not in '0123456789abcdef' for ch in run_id):
        return False
    expected_hash = digest({**expected, 'run_id': run_id, 'query': binding['input']['query'],
                            'raw_sha256': binding['input']['raw_hash']})
    return receipt.get('input_hash') == expected_hash and receipt.get('exit_code') == 0 and receipt.get('reaped') is True


def evaluation_gate(db, evaluation, completion, *, verify_bytes=False):
    """Current gate eligibility, independent of whether historical execution passed at the time."""
    from .golden_checks import aggregate_reports, contract_descriptor
    gate = {'state': 'unverified', 'applicable': True, 'scope': 'golden_tire_vehicle', 'blockers': [], 'report': None}
    bindings = evaluation.bindings
    if not bindings or any(not item.get('golden') for item in bindings):
        gate['blockers'] = ['golden_set_required']
        return gate
    first = bindings[0]['golden']
    gate.update({key: first.get(key) for key in ('set_id', 'set_revision', 'set_fingerprint')})
    try:
        frozen = checked_set(db, first['set_id'], first['set_revision'], first['set_fingerprint'], verify_bytes=verify_bytes)
        if frozen.source_id != evaluation.source_id or first['contract'] != contract_descriptor():
            raise GoldenError('golden_contract_or_source_changed')
        # The sealed package may be unchanged while the current execution host changes.
        # Both identities must match the execution that produced the Golden report.
        from .parser_release_models import ParserBundle
        from .parser_bundles import bundle_descriptor, verify_bundle
        bundle = db.get(ParserBundle, evaluation.target_bundle_id)
        try:
            if bundle is None or bundle.manifest.get('bundle_id') != bundle.id:
                raise ValueError('registered bundle missing')
            if verify_bytes:
                verify_bundle(bundle.manifest)
            current_parser = bundle_descriptor(bundle.manifest, evaluation.source_id)
        except Exception:
            raise GoldenError('golden_parser_unavailable') from None
        if stable_json(current_parser) != stable_json(first['parser']):
            raise GoldenError('golden_parser_execution_changed')
        if len(bindings) != len(frozen.cases):
            raise GoldenError('golden_set_capture_mismatch')
        by_capture = {item['capture_id']: item for item in frozen.cases}
        if {item['input']['capture_id'] for item in bindings} != set(by_capture):
            raise GoldenError('golden_set_capture_mismatch')
        for item in bindings:
            binding = item['golden']
            if (any(binding.get(key) != first.get(key) for key in ('set_id', 'set_revision', 'set_fingerprint', 'contract', 'parser'))
                    or stable_json(binding['case']) != stable_json(by_capture[item['input']['capture_id']])
                    or stable_json(item['input']) != stable_json(binding['case']['input'])
                    or binding['parser']['bundle_id'] != evaluation.target_bundle_id):
                raise GoldenError('golden_evaluation_binding_mismatch')
    except GoldenError as error:
        gate.update(state='stale', blockers=[error.code])
        return gate
    except (KeyError, TypeError, ValueError):
        gate.update(state='failed', blockers=['golden_evaluation_binding_invalid'])
        return gate
    if completion is None:
        gate['state'] = 'pending'
        return gate
    if (len(completion.results) != len(bindings)
            or [item.get('capture_id') for item in completion.results] != [item['input']['capture_id'] for item in bindings]):
        gate.update(state='failed', blockers=['golden_result_coverage_invalid'])
        return gate
    report = aggregate_reports([item.get('golden_report') for item in completion.results], expected_case_count=len(bindings))
    gate.update(state=report['state'], report=report)
    if report['state'] != 'passed':
        gate['blockers'].append('golden_assertions_failed' if report['state'] == 'failed' else 'golden_coverage_inconclusive')
    if completion.state != 'completed':
        gate['blockers'].append('golden_execution_incomplete')
    for binding, result in zip(bindings, completion.results):
        if not receipt_matches(evaluation, binding, result.get('candidate_receipt')):
            gate['blockers'].append('golden_candidate_receipt_mismatch')
            break
    if gate['blockers'] and gate['state'] == 'passed':
        gate['state'] = 'failed'
    return gate


def register_golden_routes(app: FastAPI):
    @app.exception_handler(GoldenError)
    async def golden_error(_request, error):
        return JSONResponse(status_code=error.status_code, content={'detail': {'code': error.code}})

    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/golden/cases')
    def cases(mode: Literal['history'] = Query(...), source_id: str | None = Query(None, max_length=80),
              offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=25), db=Depends(get_db)):
        filters = [GoldenCase.source_id == source_id] if source_id else []
        rows = db.scalars(select(GoldenCase).where(*filters).order_by(desc(GoldenCase.created_at), GoldenCase.id)
                          .offset(offset).limit(limit)).all()
        return {**SCOPE, 'items': [case_view(db, item, detail=False) for item in rows], 'offset': offset, 'limit': limit,
            'total': db.scalar(select(func.count()).select_from(GoldenCase).where(*filters)), 'notice': NOTICE}

    @app.get('/v1/golden/cases/{case_id}')
    def case(case_id: str, mode: Literal['history'] = Query(...), revision: int | None = Query(None, ge=1), db=Depends(get_db)):
        selected = None
        if revision is not None:
            selected = db.scalar(select(GoldenCaseRevision).where(GoldenCaseRevision.case_id == case_id,
                                                                  GoldenCaseRevision.revision == revision))
            if selected is None:
                raise GoldenError('golden_case_revision_not_found', 404)
        return case_view(db, _case(db, case_id), selected)

    @app.post('/v1/golden/cases', status_code=201)
    def create(payload: CaseCreate, request: Request,
               idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return write_case(db, payload, request.state.session_id, idempotency_key)

    @app.post('/v1/golden/cases/{case_id}/revisions', status_code=201)
    def revise(case_id: str, payload: CaseContent, request: Request,
               idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return write_case(db, payload, request.state.session_id, idempotency_key, case_id)

    @app.post('/v1/golden/cases/{case_id}/reviews', status_code=201)
    def review(case_id: str, payload: CaseReviewCreate, request: Request,
               idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return review_case(db, case_id, payload, request.state.session_id, idempotency_key)

    @app.get('/v1/golden/sets')
    def sets(mode: Literal['history'] = Query(...), source_id: str | None = Query(None, max_length=80),
             offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=25), db=Depends(get_db)):
        latest = select(GoldenSetRevision.set_id, func.max(GoldenSetRevision.revision).label('revision')).group_by(
            GoldenSetRevision.set_id).subquery()
        statement = select(GoldenSetRevision).join(latest, (GoldenSetRevision.set_id == latest.c.set_id)
                                                   & (GoldenSetRevision.revision == latest.c.revision))
        if source_id:
            statement = statement.where(GoldenSetRevision.source_id == source_id)
        total = db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = db.scalars(statement.order_by(desc(GoldenSetRevision.created_at), GoldenSetRevision.set_id)
                          .offset(offset).limit(limit)).all()
        return {**SCOPE, 'items': [set_view(db, item, detail=False) for item in rows], 'total': total,
                'offset': offset, 'limit': limit, 'notice': NOTICE}

    @app.get('/v1/golden/sets/{set_id}')
    def frozen_set(set_id: str, mode: Literal['history'] = Query(...), revision: int | None = Query(None, ge=1), db=Depends(get_db)):
        row = (db.scalar(select(GoldenSetRevision).where(GoldenSetRevision.set_id == set_id,
             GoldenSetRevision.revision == revision)) if revision is not None else _latest_set(db, set_id))
        if row is None:
            raise GoldenError('golden_set_not_found', 404)
        return set_view(db, row)

    @app.post('/v1/golden/sets', status_code=201)
    def freeze(payload: SetCreate, request: Request,
               idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return write_set(db, payload, request.state.session_id, idempotency_key)

    @app.post('/v1/golden/sets/{set_id}/revisions', status_code=201)
    def revise_set(set_id: str, payload: SetRevise, request: Request,
                   idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return write_set(db, payload, request.state.session_id, idempotency_key, set_id)
