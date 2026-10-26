"""Local test-event expectations, independent review, and read-only frozen consumers."""
from copy import deepcopy
from typing import Literal
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import object_session

from .auth import current_user, make_admin_guard
from .db import uid, utcnow
from .domain import digest
from .service import QueryService, timestamp
from .test_event_golden_checks import (BOUNDARY, CaseContent, CaseRef, EvaluateRequest, Expected,
    Material, ReviewRequest, SetWrite, compare_identities, compare_values)
from .test_event_golden_models import (TestEventGoldenCase as Case, TestEventGoldenCaseRevision as Content,
    TestEventGoldenCaseReview as Review, TestEventGoldenSetRevision as FrozenSet)
from .test_events import EventPayload, TireTestRevision, compare_revision, latest as latest_event
from .test_sku_link_models import TestSkuLinkRevision
from .test_sku_links import (BridgeSelection, assess_link, checked_revision, current_link_binding,
    freeze_materials, latest_revision, link_view)


class TestEventGoldenError(Exception):
    def __init__(self, code, status_code=409):
        self.code, self.status_code = code, status_code
        super().__init__(code)


def fail(code, status=409):
    raise TestEventGoldenError('test_event_golden_' + code, status)


def _actor(db, session_id, *, admin=False):
    user = current_user(db, session_id)
    if user is None:
        fail('login_required', 401)
    if admin and not user.is_admin:
        raise HTTPException(403, {'code': 'admin_required'})
    return user.id


def _key(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        fail('invalid_idempotency_key', 422)


def _hash(row):
    return digest({column.name: timestamp(getattr(row, column.name)) if column.name == 'created_at'
                   else getattr(row, column.name) for column in row.__table__.columns if column.name != 'fingerprint'})


def _checked(row, model, *, missing='revision_not_found'):
    if row is None:
        fail(missing, 404)
    if _hash(row) != row.fingerprint:
        fail('revision_integrity_failed', 422)
    owner = 'set_id' if model is FrozenSet else 'case_id'
    previous = row.previous_fingerprint
    if (row.revision == 1) != (previous is None) or row.revision < 1:
        fail('revision_integrity_failed', 422)
    if row.revision > 1:
        db = object_session(row)
        predecessor = db.scalar(select(model).where(getattr(model, owner) == getattr(row, owner),
            model.revision == row.revision - 1)) if db is not None else None
        if predecessor is None or predecessor.fingerprint != previous or _hash(predecessor) != previous:
            fail('revision_chain_invalid', 422)
    return row


def _latest(db, model, identifier):
    field = model.set_id if model is FrozenSet else model.case_id
    row = db.scalar(select(model).where(field == identifier).order_by(desc(model.revision)).limit(1))
    return _checked(row, model) if row else None


def _at(db, model, identifier, revision):
    field = model.set_id if model is FrozenSet else model.case_id
    return _checked(db.scalar(select(model).where(field == identifier, model.revision == revision)), model)


def _case(db, case_id):
    case = db.get(Case, case_id)
    if case is None:
        fail('case_not_found', 404)
    return case


def _fence(row, payload, kind):
    if payload.expected_revision != (row.revision if row else 0):
        fail(kind + '_revision_conflict')
    if payload.expected_fingerprint != (row.fingerprint if row else None):
        fail(kind + '_fingerprint_mismatch')


def _replay(db, model, user_id, key, request_hash):
    # A UUID belongs to one operation for this stable account, including other write tables.
    for candidate in (Content, Review, FrozenSet):
        row = db.scalar(select(candidate).where(candidate.actor_user_id == user_id, candidate.idempotency_key == key))
        if row is not None:
            if candidate is not model or row.request_hash != request_hash:
                fail('idempotency_payload_mismatch')
            return _checked(row, model)
    return None


def _signed(model, payload, user_id, session_id, key, request_hash, old, **values):
    row = model(id=uid(), revision=(old.revision if old else 0) + 1,
        previous_fingerprint=old.fingerprint if old else None, operator=payload.operator, reason=payload.reason,
        actor_user_id=user_id, actor_session_id=session_id, idempotency_key=key, request_hash=request_hash,
        created_at=utcnow(), **values)
    row.fingerprint = _hash(row)
    return row


def _event(db, reference):
    row = db.get(TireTestRevision, reference['event_revision_id'])
    if row is None or row.event_id != reference['event_id']:
        fail('event_scope_mismatch', 422)
    try:
        valid = EventPayload.model_validate(row.payload).model_dump(mode='json') == row.payload
    except (ValueError, TypeError):
        valid = False
    if not valid or digest(row.payload) != row.fingerprint or row.state not in ('active', 'revoked'):
        fail('event_evidence_invalid', 422)
    if row.fingerprint != reference['event_fingerprint']:
        fail('event_fingerprint_mismatch')
    return row


def _link(db, reference, event_ref):
    row = checked_revision(db.get(TestSkuLinkRevision, reference['link_revision_id']))
    if (row.link_id != reference['link_id'] or row.fingerprint != reference['link_fingerprint']
            or row.selection['event_id'] != event_ref['event_id']
            or row.selection['event_revision_id'] != event_ref['event_revision_id']
            or row.selection['participant_key'] != reference['participant_key']):
        fail('link_scope_mismatch', 422)
    view = link_view(db, row)
    return row, view


def _material_evidence(db, materials):
    try:
        return freeze_materials(db, materials)
    except HTTPException as error:
        code = error.detail.get('code', 'material_integrity_failed') if isinstance(error.detail, dict) else 'material_integrity_failed'
        fail(code.removeprefix('test_sku_'), error.status_code)


def _capture(db, payload):
    event_ref = payload.event_ref.model_dump()
    event = _event(db, event_ref)
    materials = _material_evidence(db, payload.materials)
    if any(m['metadata']['source_url'] != event.payload['source_url'] for m in materials):
        fail('material_event_scope_mismatch', 422)
    people = {p['key'] for p in event.payload['participants']}
    if {a.participant_key for a in payload.expected.identity_assertions} != people:
        fail('participant_scope_mismatch', 422)
    bindings = {}
    for reference in payload.link_refs:
        row, _ = _link(db, reference.model_dump(), event_ref)
        bindings[reference.participant_key] = current_link_binding(db, BridgeSelection.model_validate(row.selection))
    return {'event_ref': event_ref, 'event_snapshot': deepcopy(event.payload), 'event_state': event.state,
        'event_revision': event.revision, 'material_requests': [m.model_dump() for m in payload.materials],
        'link_bindings': bindings}, materials


def _evidence(db, case, content):
    _checked(content, Content)
    if content.case_id != case.id or content.input['event_ref']['event_id'] != case.event_id:
        fail('case_scope_invalid', 422)
    event = _event(db, content.input['event_ref'])
    if (content.event_revision_id != event.id or content.input['event_revision'] != event.revision
            or content.input['event_state'] != event.state
            or digest(content.input['event_snapshot']) != digest(event.payload)):
        fail('event_snapshot_invalid', 422)
    try:
        Expected.model_validate(content.expected)
        material_requests = [Material.model_validate(m) for m in content.input['material_requests']]
    except (ValueError, TypeError, KeyError):
        fail('revision_integrity_failed', 422)
    if digest(_material_evidence(db, material_requests)) != digest(content.materials):
        fail('material_snapshot_invalid', 422)
    links = {}
    for reference in content.link_refs:
        links[reference['participant_key']] = _link(db, reference, content.input['event_ref'])
    return event, links


def _review_status(content, review):
    if review is None or (review.case_revision, review.case_fingerprint) != (content.revision, content.fingerprint):
        return 'pending'
    return {'approve': 'approved', 'reject': 'rejected', 'revoke': 'revoked'}[review.action]


def _blockers(db, case, content, *, verify=True):
    event, links = _evidence(db, case, content) if verify else (None, {})
    blockers = []
    latest_content = _latest(db, Content, case.id)
    if latest_content.id != content.id:
        blockers.append('case_changed')
    current = latest_event(db, case.event_id)
    _event(db, {'event_id': case.event_id, 'event_revision_id': current.id, 'event_fingerprint': current.fingerprint})
    if current.id != content.event_revision_id:
        blockers.append('event_changed')
    if current.state != 'active' or content.input['event_state'] != 'active':
        blockers.append('event_revoked')
    for reference in content.link_refs:
        row, _ = links.get(reference['participant_key']) or _link(db, reference, content.input['event_ref'])
        if latest_revision(db, row.link_id).id != row.id:
            blockers.append('bridge_changed')
        binding = current_link_binding(db, BridgeSelection.model_validate(row.selection))
        if digest(binding) != digest(content.input['link_bindings'][reference['participant_key']]):
            blockers.append('bridge_binding_changed')
    return list(dict.fromkeys(blockers))


def _review_view(row):
    if row is None:
        return None
    _checked(row, Review)
    return {key: getattr(row, key) for key in ('id', 'case_revision', 'case_fingerprint', 'revision', 'action',
            'operator', 'reason', 'actor_user_id', 'fingerprint')} | {'created_at': timestamp(row.created_at)}


def _summary(case, row, review, blockers):
    return {'id': case.id, 'event_id': case.event_id, 'revision_id': row.id, 'revision': row.revision,
        'fingerprint': row.fingerprint, 'title': row.title, 'review_status': _review_status(row, review),
        'review_revision': review.revision if review else 0, 'review_fingerprint': review.fingerprint if review else None,
        'blockers': blockers, 'operator': row.operator, 'reason': row.reason, 'created_at': timestamp(row.created_at)}


def _error_code(error):
    if isinstance(error, TestEventGoldenError):
        return error.code
    return error.detail.get('code', 'evidence_unavailable') if isinstance(error.detail, dict) else 'evidence_unavailable'


def case_view(db, case, content=None, *, detail=True):
    content = _checked(content or _latest(db, Content, case.id), Content)
    review = _latest(db, Review, case.id)
    try:
        blockers = _blockers(db, case, content)
    except (TestEventGoldenError, HTTPException) as error:
        blockers = [_error_code(error)]
    result = _summary(case, content, review, blockers)
    if not detail:
        return result
    history = db.scalars(select(Content).where(Content.case_id == case.id).order_by(desc(Content.revision)).limit(101)).all()
    reviews = db.scalars(select(Review).where(Review.case_id == case.id).order_by(desc(Review.revision)).limit(101)).all()
    return {**result, 'event_ref': deepcopy(content.input['event_ref']),
        'event_snapshot': deepcopy(content.input['event_snapshot']),
        'materials': deepcopy(content.input['material_requests']), 'link_refs': deepcopy(content.link_refs),
        'expected': deepcopy(content.expected), 'evidence_note': content.evidence_note,
        'operator': content.operator, 'reason': content.reason, 'actor_user_id': content.actor_user_id,
        'latest_review': _review_view(review), 'history': [_summary(case, _checked(r, Content), None, []) for r in history[:100]],
        'reviews': [_review_view(r) for r in reviews[:100]], 'history_truncated': len(history) > 100,
        'reviews_truncated': len(reviews) > 100, 'is_current': history[0].id == content.id, 'boundary': deepcopy(BOUNDARY)}


def write_case(db, payload, session_id, idempotency_key, case_id=None):
    user_id, key = _actor(db, session_id), _key(idempotency_key)
    request_hash = digest({'operation': 'content', 'target': case_id, 'payload': payload.model_dump(mode='json')})
    QueryService(db, None).lock_ingestion()
    replay = _replay(db, Content, user_id, key, request_hash)
    if replay:
        return case_view(db, _case(db, replay.case_id), replay)
    case = _case(db, case_id) if case_id else Case(id=uid(), event_id=payload.event_ref.event_id, created_at=utcnow())
    old = _latest(db, Content, case.id) if case_id else None
    _fence(old, payload, 'case')
    if case.event_id != payload.event_ref.event_id:
        fail('event_scope_mismatch', 422)
    source_input, materials = _capture(db, payload)
    row = _signed(Content, payload, user_id, session_id, key, request_hash, old,
        case_id=case.id, event_revision_id=payload.event_ref.event_revision_id, title=payload.title,
        input=source_input, materials=materials, link_refs=[r.model_dump() for r in payload.link_refs],
        expected=payload.expected.model_dump(mode='json'), evidence_note=payload.evidence_note)
    if case_id is None:
        db.add(case)
        db.flush()
    db.add(row)
    db.commit()
    return case_view(db, case, row)


def review_case(db, case_id, payload, session_id, idempotency_key):
    user_id, key = _actor(db, session_id, admin=True), _key(idempotency_key)
    request_hash = digest({'operation': 'review', 'target': case_id, 'payload': payload.model_dump(mode='json')})
    QueryService(db, None).lock_ingestion()
    replay = _replay(db, Review, user_id, key, request_hash)
    case = _case(db, case_id)
    if replay:
        return {**case_view(db, case, _at(db, Content, case_id, replay.case_revision)), 'recorded_review': _review_view(replay)}
    content = _checked(_latest(db, Content, case_id), Content)
    old = _latest(db, Review, case_id)
    _fence(old, payload, 'review')
    if (content.revision, content.fingerprint) != (payload.case_revision, payload.case_fingerprint):
        fail('case_revision_conflict')
    if content.actor_user_id == user_id:
        fail('self_review', 403)
    if payload.action == 'approve':
        blockers = _blockers(db, case, content)
        if blockers:
            fail('case_stale')
        opened = [m.model_dump() for m in payload.opened_materials]
        wanted = [{'document_id': m['document_id'], 'raw_hash': m['raw_hash'], 'metadata_hash': m['metadata_hash']}
                  for m in content.materials]
        if sorted(opened, key=lambda m: m['document_id']) != sorted(wanted, key=lambda m: m['document_id']):
            fail('opened_materials_mismatch', 422)
    row = _signed(Review, payload, user_id, session_id, key, request_hash, old, case_id=case_id,
        case_revision=content.revision, case_fingerprint=content.fingerprint, action=payload.action,
        opened_materials=[m.model_dump() for m in payload.opened_materials])
    db.add(row)
    db.commit()
    return {**case_view(db, case, content), 'recorded_review': _review_view(row)}


def _bound_case(db, reference):
    reference = CaseRef.model_validate(reference).model_dump()
    case = _case(db, reference['case_id'])
    content = _at(db, Content, case.id, reference['case_revision'])
    review = _at(db, Review, case.id, reference['review_revision'])
    if (content.fingerprint != reference['case_fingerprint'] or review.fingerprint != reference['review_fingerprint']
            or (review.case_revision, review.case_fingerprint) != (content.revision, content.fingerprint)
            or review.action != 'approve' or review.actor_user_id == content.actor_user_id):
        fail('case_binding_invalid', 422)
    blockers = _blockers(db, case, content)
    if _latest(db, Review, case.id).id != review.id:
        blockers.append('review_changed')
    return case, content, review, list(dict.fromkeys(blockers))


def _set_summary(row):
    _checked(row, FrozenSet)
    return {'id': row.set_id, 'revision': row.revision, 'fingerprint': row.fingerprint, 'title': row.title,
        'action': row.action, 'state': 'frozen' if row.action == 'freeze' else 'revoked',
        'operator': row.operator, 'reason': row.reason, 'created_at': timestamp(row.created_at)}


def set_view(db, row, *, detail=True):
    result = _set_summary(row)
    blockers, cases = [], []
    if row.action != 'freeze':
        blockers.append('set_revoked')
    if _latest(db, FrozenSet, row.set_id).id != row.id:
        blockers.append('set_changed')
    for reference in row.cases:
        try:
            case, content, review, local = _bound_case(db, reference)
            cases.append(_summary(case, content, review, local))
            blockers.extend(local)
        except (TestEventGoldenError, HTTPException) as error:
            blockers.append(_error_code(error))
    result.update(case_refs=deepcopy(row.cases), cases=cases, eligible=not blockers,
                  blockers=list(dict.fromkeys(blockers)), boundary=deepcopy(BOUNDARY))
    if detail:
        history = db.scalars(select(FrozenSet).where(FrozenSet.set_id == row.set_id)
                             .order_by(desc(FrozenSet.revision)).limit(101)).all()
        result.update(history=[_set_summary(r) for r in history[:100]], history_truncated=len(history) > 100)
    return result


def write_set(db, payload, session_id, idempotency_key, set_id=None):
    user_id, key = _actor(db, session_id, admin=True), _key(idempotency_key)
    request_hash = digest({'operation': 'set', 'target': set_id, 'payload': payload.model_dump(mode='json')})
    QueryService(db, None).lock_ingestion()
    replay = _replay(db, FrozenSet, user_id, key, request_hash)
    if replay:
        return set_view(db, replay)
    old = _latest(db, FrozenSet, set_id) if set_id else None
    if set_id and old is None:
        fail('set_not_found', 404)
    _fence(old, payload, 'set')
    if payload.action == 'revoke':
        if old is None or old.action != 'freeze':
            fail('set_not_frozen')
        cases = deepcopy(old.cases)
    else:
        cases = [r.model_dump() for r in payload.case_refs]
        for reference in cases:
            _, _, _, blockers = _bound_case(db, reference)
            if blockers:
                fail('case_stale')
    row = _signed(FrozenSet, payload, user_id, session_id, key, request_hash, old,
                  set_id=set_id or uid(), title=payload.title, action=payload.action, cases=cases)
    db.add(row)
    db.commit()
    return set_view(db, row)


def _observe_link(db, row, target):
    view = link_view(db, row)
    if target == 'frozen_revision':
        assessment = assess_link(row.frozen_evidence, row.binding, prior_binding=row.binding,
            review_state=row.review_state, evidence_level=row.evidence_level, checks=row.checks,
            reviewed_by=row.actor_user_id if row.action == 'review' else None, declared_by=row.declared_by_user_id)
        identity_key = row.frozen_evidence['tire']['identity_key']
    else:
        assessment = view
        binding = current_link_binding(db, BridgeSelection.model_validate(row.selection))
        identity_key = binding['identity_contract']['current_key']
    return {'linked': assessment['eligibility'] == 'conditional_reviewed_transcription',
        'variant_id': row.selection['variant_id'], 'identity_key': identity_key,
        'blockers': list(dict.fromkeys(assessment['blockers'] + assessment['stale_reasons']))}


def evaluate_set(db, set_id, payload):
    row = _checked(_latest(db, FrozenSet, set_id), FrozenSet, missing='set_not_found')
    if row.revision != payload.expected_set_revision:
        fail('set_revision_conflict')
    if row.fingerprint != payload.expected_set_fingerprint:
        fail('set_fingerprint_mismatch')
    results, wrong_count, checked_count = [], 0, 0
    for reference in row.cases:
        case, content, review, blockers = _bound_case(db, reference)
        if row.action != 'freeze':
            blockers.append('set_revoked')
        actual = (_event(db, content.input['event_ref']) if payload.target == 'frozen_revision'
                  else latest_event(db, case.event_id))
        _event(db, {'event_id': case.event_id, 'event_revision_id': actual.id, 'event_fingerprint': actual.fingerprint})
        differences, truncated = compare_values(content.expected['event'], actual.payload)
        observations = {}
        for link_ref in content.link_refs:
            linked_row, _ = _link(db, link_ref, content.input['event_ref'])
            if payload.target == 'current_head':
                linked_row = latest_revision(db, linked_row.link_id)
            observations[link_ref['participant_key']] = _observe_link(db, linked_row, payload.target)
        identities, distinct, wrong, checked = compare_identities(content.expected, observations)
        wrong_count += wrong
        checked_count += checked
        comparison = (compare_revision(actual, [f'{case.event_id}:{p["key"]}' for p in actual.payload['participants']],
                                       [m['key'] for m in actual.payload['metrics']]) if actual.state == 'active' else None)
        failed = bool(differences or wrong or any(r['state'] == 'failed' for r in identities))
        incomplete = bool(blockers or any(r['state'] == 'inconclusive' for r in identities + distinct))
        results.append({'case_id': case.id, 'event_id': case.event_id,
            'expected_event_revision_id': content.event_revision_id, 'actual_event_revision_id': actual.id,
            'review_status': _review_status(content, _latest(db, Review, case.id)), 'eligible': not blockers,
            'blockers': list(dict.fromkeys(blockers)), 'state': 'failed' if failed else 'inconclusive' if incomplete else 'passed',
            'differences': differences, 'differences_truncated': truncated, 'comparison': comparison,
            'identity_results': identities, 'distinct_results': distinct})
    state = ('failed' if any(r['state'] == 'failed' for r in results) else
             'inconclusive' if not results or any(r['state'] == 'inconclusive' for r in results) else 'passed')
    return {'schema': 'test-event-golden-evaluation@1', 'set_id': row.set_id, 'set_revision': row.revision,
        'set_fingerprint': row.fingerprint, 'target': payload.target, 'state': state, 'case_results': results,
        'observed_wrong_merge_count': wrong_count, 'checked_distinct_pair_count': checked_count,
        'wrong_merge_count': None, 'human_truth_status': 'pending_external_review', 'boundary': deepcopy(BOUNDARY)}


def register_test_event_golden_routes(app):
    @app.exception_handler(TestEventGoldenError)
    async def error_response(_request, error):
        return JSONResponse(status_code=error.status_code, content={'detail': {'code': error.code}},
                            headers={'Cache-Control': 'no-store'})

    def get_db():
        with app.state.database.sessions() as db:
            yield db

    admin_guard = make_admin_guard(get_db)

    @app.get('/v1/test-event-golden/cases')
    def cases(mode: Literal['history'] = Query(...), event_id: str | None = Query(None, max_length=64),
              offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=25), db=Depends(get_db)):
        filters = [Case.event_id == event_id] if event_id else []
        rows = db.scalars(select(Case).where(*filters).order_by(desc(Case.created_at), Case.id).offset(offset).limit(limit)).all()
        return {'items': [case_view(db, case, detail=False) for case in rows], 'offset': offset, 'limit': limit,
            'total': db.scalar(select(func.count()).select_from(Case).where(*filters)), 'boundary': deepcopy(BOUNDARY)}

    @app.get('/v1/test-event-golden/cases/{case_id}')
    def read_case(case_id: str, mode: Literal['history'] = Query(...),
                  revision: int | None = Query(None, ge=1), db=Depends(get_db)):
        return case_view(db, _case(db, case_id), _at(db, Content, case_id, revision) if revision else None)

    @app.post('/v1/test-event-golden/cases', status_code=201)
    def create_case(payload: CaseContent, request: Request,
                    idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return write_case(db, payload, request.state.session_id, idempotency_key)

    @app.post('/v1/test-event-golden/cases/{case_id}/revisions', status_code=201)
    def revise_case(case_id: str, payload: CaseContent, request: Request,
                    idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return write_case(db, payload, request.state.session_id, idempotency_key, case_id)

    @app.post('/v1/test-event-golden/cases/{case_id}/reviews', status_code=201, dependencies=[Depends(admin_guard)])
    def review(case_id: str, payload: ReviewRequest, request: Request,
               idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return review_case(db, case_id, payload, request.state.session_id, idempotency_key)

    @app.get('/v1/test-event-golden/sets')
    def sets(mode: Literal['history'] = Query(...), offset: int = Query(0, ge=0),
             limit: int = Query(10, ge=1, le=25), db=Depends(get_db)):
        latest = select(FrozenSet.set_id, func.max(FrozenSet.revision).label('revision')).group_by(FrozenSet.set_id).subquery()
        query = select(FrozenSet).join(latest, (FrozenSet.set_id == latest.c.set_id) & (FrozenSet.revision == latest.c.revision))
        rows = db.scalars(query.order_by(desc(FrozenSet.created_at), FrozenSet.set_id).offset(offset).limit(limit)).all()
        return {'items': [set_view(db, row, detail=False) for row in rows], 'offset': offset, 'limit': limit,
            'total': db.scalar(select(func.count()).select_from(query.subquery())), 'boundary': deepcopy(BOUNDARY)}

    @app.get('/v1/test-event-golden/sets/{set_id}')
    def read_set(set_id: str, mode: Literal['history'] = Query(...),
                 revision: int | None = Query(None, ge=1), db=Depends(get_db)):
        row = _at(db, FrozenSet, set_id, revision) if revision else _latest(db, FrozenSet, set_id)
        return set_view(db, _checked(row, FrozenSet, missing='set_not_found'))

    @app.post('/v1/test-event-golden/sets', status_code=201, dependencies=[Depends(admin_guard)])
    def create_set(payload: SetWrite, request: Request,
                   idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return write_set(db, payload, request.state.session_id, idempotency_key)

    @app.post('/v1/test-event-golden/sets/{set_id}/revisions', status_code=201, dependencies=[Depends(admin_guard)])
    def revise_set(set_id: str, payload: SetWrite, request: Request,
                   idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return write_set(db, payload, request.state.session_id, idempotency_key, set_id)

    @app.post('/v1/test-event-golden/sets/{set_id}/evaluate')
    def evaluate(set_id: str, payload: EvaluateRequest, mode: Literal['history'] = Query(...), db=Depends(get_db)):
        return evaluate_set(db, set_id, payload)
