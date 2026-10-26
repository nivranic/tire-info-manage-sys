"""Actor-private interests and notifications over local immutable event evidence."""
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.orm import defer

from .auth import session_scope
from .db import uid, utcnow
from .interest_events import historical_candidates
from .interest_matching import (InterestCriteria, InterestEdit, InterestReadState, InterestSettings,
                                InterestState, capabilities, match_event)
from .interest_models import Interest, InterestEvent, InterestNotification, InterestRevision
from .interest_source_quality import (DOMAIN as QUALITY_DOMAIN, POLICY as QUALITY_POLICY,
    quality_filters_supported, quality_notification_view, settings_fingerprint)
from .service import QueryService, timestamp

BASE = {'scope': 'actor', 'data_state': 'local_snapshot'}


def fail(code, message, status=409):
    raise HTTPException(status, {'code': code, 'message': message})


def latest(db, interest_id):
    return db.scalar(select(InterestRevision).where(InterestRevision.interest_id == interest_id)
                     .order_by(desc(InterestRevision.revision)).limit(1))


def owned(db, interest_id, session_id):
    item = db.scalar(select(Interest).where(Interest.id == interest_id,
                        Interest.session_id.in_(session_scope(db, session_id))))
    if item is None:
        fail('interest_not_found', '当前账户未找到此兴趣关注', 404)
    row = latest(db, item.id)
    if row is None:
        raise ValueError('interest_revision_missing:' + item.id)
    return item, row


def revision_view(row):
    return {key: getattr(row, key) for key in ('revision', 'name', 'enabled', 'archived',
        'conditions', 'metric_keys', 'changed_fields', 'source_quality_notifications',
        'fingerprint')} | {'created_at': timestamp(row.created_at)}


def view(item, row):
    return {**revision_view(row), 'id': item.id, 'scope': 'actor', 'monitoring_enabled': False,
            'created_at': timestamp(item.created_at), 'updated_at': timestamp(row.created_at)}


def validate_local_vehicles(db, criteria):
    from .vehicles import VehicleModel, VehicleSnapshot, VehicleTrim, WheelFitment
    for condition in criteria.conditions:
        if condition.kind != 'vehicle_fitment':
            continue
        for target in condition.values:
            vehicle = db.get(VehicleModel, target['vehicle_id'])
            trim = db.get(VehicleTrim, target.get('trim_id')) if target.get('trim_id') else None
            invalid = vehicle is None or (target.get('trim_id') and (trim is None or trim.vehicle_id != vehicle.id))
            if not invalid and target.get('wheel_option_id'):
                invalid = db.scalar(select(WheelFitment.id).join(VehicleSnapshot,
                    VehicleSnapshot.id == WheelFitment.snapshot_id).where(
                    VehicleSnapshot.vehicle_id == vehicle.id, WheelFitment.trim_id == trim.id,
                    WheelFitment.option_id == target['wheel_option_id']).limit(1)) is None
            if invalid:
                fail('invalid_interest', '车型、配置和轮毂项必须来自本地实际已录目录，不能靠名称或同尺寸推断', 422)


def append(db, item, payload, archived, actor, number):
    data = {key: payload[key] for key in ('name', 'enabled', 'conditions', 'metric_keys', 'changed_fields')}
    data['source_quality_notifications'] = payload.get('source_quality_notifications', False)
    row = InterestRevision(interest_id=item.id, revision=number, **data, archived=archived,
        fingerprint=settings_fingerprint(data, archived), actor_session_id=actor)
    db.add(row)
    db.flush()
    return row


def validate_quality_filters(payload):
    if not quality_filters_supported(payload):
        fail('source_quality_interest_filter_unsupported',
             '质量隔离提醒仅支持品牌、型号、尺寸、OE和技术条件，不能同时限定指标或变化字段。', 422)


def is_quality_notification(db, item):
    domain = db.scalar(select(InterestEvent.domain).where(InterestEvent.id == item.event_id))
    if domain == QUALITY_DOMAIN:
        return True
    return isinstance(item.match, dict) and item.match.get('policy_version') == QUALITY_POLICY


def notification_view(db, item, *, content=False):
    if is_quality_notification(db, item):
        return quality_notification_view(db, item, content=content)
    revision = db.get(InterestRevision, item.interest_revision_id)
    event = db.get(InterestEvent, item.event_id)
    if revision is None or event is None:
        raise ValueError('interest_notification_evidence_missing:' + item.id)
    return {'id': item.id, 'interest_id': item.interest_id, 'interest_revision': revision.revision,
            'interest_name': revision.name, 'delivered_at': timestamp(item.delivered_at),
            'read_at': timestamp(item.read_at), 'event': event.payload, 'match': item.match}


def owned_notification(db, notification_id, session_id):
    item = db.scalar(select(InterestNotification).options(defer(InterestNotification.match)).where(InterestNotification.id == notification_id,
        InterestNotification.session_id.in_(session_scope(db, session_id))))
    if item is None:
        fail('interest_notification_not_found', '当前账户未找到此兴趣通知', 404)
    return item


def register_interest_routes(app):
    from .interest_governance import register_governance_routes
    register_governance_routes(app)
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/interests/capabilities')
    def supported(mode: Literal['history'] = Query(...)):
        return capabilities()

    @app.post('/v1/interests/preview')
    def preview(payload: InterestCriteria, mode: Literal['history'] = Query(...),
                offset: int = Query(0, ge=0, le=100000), limit: int = Query(50, ge=1, le=100), db=Depends(get_db)):
        validate_local_vehicles(db, payload)
        # No audit writes, publication, commits, or source calls on preview.
        with db.no_autoflush:
            events, more = historical_candidates(db, offset, limit)
            matches = [{'event': event, 'match': match_event(event, payload)} for event in events]
        return {**BASE, 'schema': 'interest-preview@1',
            'items': [item for item in matches if item['match']['state'] != 'no_match'],
            'scanned_count': len(events), 'matched_count': sum(item['match']['state'] == 'matched' for item in matches),
            'indeterminate_count': sum(item['match']['state'] == 'indeterminate' for item in matches),
            'next_offset': offset + len(events) if more else None, 'capabilities': capabilities()}

    @app.get('/v1/interests')
    def listing(request: Request, archived: bool = False, offset: int = Query(0, ge=0, le=100000),
                limit: int = Query(50, ge=1, le=100), db=Depends(get_db)):
        heads = select(InterestRevision.interest_id, func.max(InterestRevision.revision).label('revision')).group_by(
            InterestRevision.interest_id).subquery()
        statement = select(Interest, InterestRevision).join(InterestRevision, InterestRevision.interest_id == Interest.id).join(
            heads, (heads.c.interest_id == Interest.id) & (heads.c.revision == InterestRevision.revision)).where(
            Interest.session_id.in_(session_scope(db, request.state.session_id)), InterestRevision.archived == archived)
        total = db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = db.execute(statement.order_by(desc(InterestRevision.created_at), Interest.id).offset(offset).limit(limit)).all()
        return {**BASE, 'items': [view(item, row) for item, row in rows], 'total': total,
                'offset': offset, 'limit': limit, 'capabilities': capabilities()}

    @app.post('/v1/interests', status_code=201)
    def create(payload: InterestSettings, request: Request, db=Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        validate_quality_filters(payload.model_dump())
        validate_local_vehicles(db, payload)
        item = Interest(id=uid(), session_id=request.state.session_id)
        db.add(item)
        db.flush()
        row = append(db, item, payload.model_dump(), False, request.state.session_id, 1)
        db.commit()
        return view(item, row)

    @app.get('/v1/interests/{interest_id}')
    def read(interest_id: str, request: Request, mode: Literal['history'] = Query(...), db=Depends(get_db)):
        item, row = owned(db, interest_id, request.state.session_id)
        history = db.scalars(select(InterestRevision).where(InterestRevision.interest_id == item.id)
                            .order_by(desc(InterestRevision.revision)).limit(101)).all()
        return {**view(item, row), 'history': [revision_view(revision) for revision in history[:100]],
                'history_truncated': len(history) > 100}

    @app.put('/v1/interests/{interest_id}')
    def edit(interest_id: str, payload: InterestEdit, request: Request, db=Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        item, old = owned(db, interest_id, request.state.session_id)
        if old.revision != payload.expected_revision:
            fail('interest_revision_conflict', '兴趣关注已更新，请重新载入')
        if old.archived:
            fail('interest_archived', '已归档的关注须先恢复，再明确启用')
        data = payload.model_dump(exclude={'expected_revision'})
        if 'source_quality_notifications' not in payload.model_fields_set:
            data['source_quality_notifications'] = old.source_quality_notifications
        validate_quality_filters(data)
        validate_local_vehicles(db, payload)
        if settings_fingerprint(data, False) == old.fingerprint:
            fail('interest_state_conflict', '兴趣关注内容未变化')
        row = append(db, item, data, False, request.state.session_id, old.revision + 1)
        db.commit()
        return view(item, row)

    @app.post('/v1/interests/{interest_id}/state')
    def set_state(interest_id: str, payload: InterestState, request: Request, db=Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        item, old = owned(db, interest_id, request.state.session_id)
        if old.revision != payload.expected_revision:
            fail('interest_revision_conflict', '兴趣关注已更新，请重新载入')
        archived = payload.action == 'archive'
        if old.archived == archived:
            fail('interest_state_conflict', '兴趣关注已处于此状态')
        data = {key: getattr(old, key) for key in
                ('name', 'conditions', 'metric_keys', 'changed_fields', 'source_quality_notifications')}
        row = append(db, item, {**data, 'enabled': False}, archived, request.state.session_id, old.revision + 1)
        db.commit()
        return view(item, row)

    @app.get('/v1/interest-notifications')
    def notifications(request: Request, mode: Literal['history'] = Query(...), unread: bool = False,
                      offset: int = Query(0, ge=0, le=100000), limit: int = Query(50, ge=1, le=100), db=Depends(get_db)):
        statement = select(InterestNotification).options(defer(InterestNotification.match)).where(
            InterestNotification.session_id.in_(session_scope(db, request.state.session_id)))
        if unread:
            statement = statement.where(InterestNotification.read_at.is_(None))
        total = db.scalar(select(func.count()).select_from(statement.subquery()))
        items = db.scalars(statement.order_by(desc(InterestNotification.delivered_at), InterestNotification.id)
                           .offset(offset).limit(limit)).all()
        return {**BASE, 'items': [notification_view(db, item) for item in items], 'total': total,
                'offset': offset, 'limit': limit}

    @app.get('/v1/interest-notifications/{notification_id}')
    def notification(notification_id: str, request: Request, mode: Literal['history'] = Query(...), db=Depends(get_db)):
        return notification_view(db, owned_notification(db, notification_id, request.state.session_id), content=True)

    @app.put('/v1/interest-notifications/{notification_id}/read')
    def mark_read(notification_id: str, payload: InterestReadState, request: Request, db=Depends(get_db)):
        item = owned_notification(db, notification_id, request.state.session_id)
        if is_quality_notification(db, item):
            quality_notification_view(db, item)
        item.read_at = (item.read_at or utcnow()) if payload.read else None
        db.commit()
        return {'id': item.id, 'read_at': timestamp(item.read_at)}
