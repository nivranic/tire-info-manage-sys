"""Adjacent-observation URL moves for registered source queries; reference-only alerts.

A url_moved event records that the same canonical query's successful
observations moved from one source URL to another. Content is never compared
across addresses (R134 contract); content changes keep using page_changed on
the new URL's own baseline.
"""
import hashlib
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import StrictBool
from sqlalchemy import desc, func, select

from .db import AlertRule, AlertRuleRevision, MonitorJob, QueryRun, Snapshot, uid, utc, utcnow
from .domain import StrictModel, TireQuery, digest
from .source_page_monitoring import (contexts, fingerprint, invalid, latest_previous_verification_id,
                                     notice_fingerprint, stamp)
from .source_page_url_models import SCHEMA, SourcePageUrlMove, SourcePageUrlMoveNotification

MOVE_FIELDS = ('id', 'schema_version', 'source_id', 'query_key', 'query',
    'previous_verification_id', 'verification_id', 'previous_snapshot_id', 'snapshot_id',
    'previous_source_url', 'source_url', 'observed_at')


def url_settings(revision):
    return revision.kinds == ['url_moved'] and revision.fields == [] and revision.conditions == {}


def job_identity(job):
    return digest({'source_id': job.source_id, 'query': job.query})


def checked_url_move(row, context, *, content=False):
    """Metadata lists never select body; precise detail checks both retained texts."""
    verifications, snapshots, queries = context
    try:
        canonical = TireQuery.model_validate(row.query).canonical()
        if (row.schema_version != SCHEMA or row.query != canonical or row.query_key != digest(row.query)
                or row.fingerprint != fingerprint(row, MOVE_FIELDS)
                or not isinstance(row.previous_source_url, str) or not isinstance(row.source_url, str)
                or not row.previous_source_url or not row.source_url
                or row.previous_source_url == row.source_url):
            invalid()
        sides = []
        for verification_id, snapshot_id, source_url in (
                (row.previous_verification_id, row.previous_snapshot_id, row.previous_source_url),
                (row.verification_id, row.snapshot_id, row.source_url)):
            verification, snapshot = verifications.get(verification_id), snapshots.get(snapshot_id)
            query = queries.get(verification.query_id) if verification else None
            if (verification is None or snapshot is None or query is None
                    or verification.snapshot_id != snapshot_id
                    or verification.source_id != row.source_id or verification.query_key != row.query_key
                    or snapshot.source_id != row.source_id or snapshot.query_key != row.query_key
                    or snapshot.source_url != source_url
                    or query.source_id != row.source_id or query.query_key != row.query_key
                    or query.query != canonical
                    or verification.status not in {'ok', 'not_modified'}
                    or utc(snapshot.observed_at) > utc(verification.verified_at)
                    or not snapshot.parser_version):
                invalid()
            if content and hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest() != snapshot.raw_hash:
                invalid()
            sides.append({'snapshot_id': snapshot_id, 'verification_id': verification_id,
                'source_url': source_url, 'observed_at': stamp(snapshot.observed_at),
                'verified_at': stamp(verification.verified_at), 'parser_version': snapshot.parser_version})
        before, after = verifications[row.previous_verification_id], verifications[row.verification_id]
        if (after.status != 'ok' or utc(before.verified_at) > utc(after.verified_at)
                or utc(row.observed_at) != utc(after.verified_at)):
            invalid()
        return {'id': row.id, 'kind': 'url_moved', 'source_id': row.source_id,
                'query': canonical, 'previous_source_url': row.previous_source_url,
                'source_url': row.source_url, 'before': sides[0], 'after': sides[1]}
    except (ValueError, TypeError, AttributeError, UnicodeError, KeyError):
        invalid()


def append_url_move(db, verification, previous):
    """Caller owns ingestion lock and commit. Existing events are never re-evaluated."""
    existing = db.scalar(select(SourcePageUrlMove).where(SourcePageUrlMove.verification_id == verification.id))
    if existing is not None:
        checked_url_move(existing, contexts(db, [existing]), content=False)
        return existing
    if verification.status != 'ok' or previous is None:
        return None
    if latest_previous_verification_id(db, verification) != previous.id:
        invalid()
    after, before = db.get(Snapshot, verification.snapshot_id), db.get(Snapshot, previous.snapshot_id)
    if after is None or before is None:
        invalid()
    if before.source_url == after.source_url:
        return None
    query = db.scalar(select(QueryRun.query).where(QueryRun.id == verification.query_id))
    move = SourcePageUrlMove(id=uid(), schema_version=SCHEMA, source_id=verification.source_id,
        query_key=verification.query_key, query=query, previous_verification_id=previous.id,
        verification_id=verification.id, previous_snapshot_id=before.id, snapshot_id=after.id,
        previous_source_url=before.source_url, source_url=after.source_url,
        observed_at=verification.verified_at)
    move.fingerprint = fingerprint(move, MOVE_FIELDS)
    checked_url_move(move, contexts(db, [move], content=True), content=True)
    db.add(move)
    db.flush()
    from .monitoring import current_rules
    rules = db.execute(current_rules(db).where(AlertRuleRevision.enabled.is_(True),
        AlertRuleRevision.archived.is_(False), AlertRule.created_at <= move.observed_at,
        AlertRuleRevision.created_at <= move.observed_at)).all()
    for rule, revision in rules:
        if rule.variant_id is not None or not url_settings(revision):
            continue
        job = db.get(MonitorJob, rule.job_id)
        if (job is None or job.source_id != move.source_id or job.query != move.query
                or job.id != job_identity(job)):
            continue
        notification = SourcePageUrlMoveNotification(id=uid(), rule_id=rule.id,
            rule_revision_id=revision.id, event_id=move.id, delivered_at=utcnow(), read_at=None)
        notification.fingerprint = notice_fingerprint(notification, rule, revision, job)
        db.add(notification)
    db.flush()
    return move


def url_move_notification_statement():
    # Outer joins retain invalid associations so corruption fails rather than hiding a row.
    return (select(SourcePageUrlMoveNotification, SourcePageUrlMove, AlertRule, AlertRuleRevision, MonitorJob)
        .outerjoin(SourcePageUrlMove, SourcePageUrlMove.id == SourcePageUrlMoveNotification.event_id)
        .outerjoin(AlertRule, AlertRule.id == SourcePageUrlMoveNotification.rule_id)
        .outerjoin(AlertRuleRevision, AlertRuleRevision.id == SourcePageUrlMoveNotification.rule_revision_id)
        .outerjoin(MonitorJob, MonitorJob.id == AlertRule.job_id))


def url_move_notification_views(db, rows, *, content=False):
    if any(move is None or rule is None or revision is None or job is None
           for _notice, move, rule, revision, job in rows):
        invalid()
    context = contexts(db, [row[1] for row in rows], content=content)
    items = []
    for notice, move, rule, revision, job in rows:
        try:
            if (notice.fingerprint != notice_fingerprint(notice, rule, revision, job)
                    or revision.rule_id != rule.id or rule.variant_id is not None
                    or not url_settings(revision) or not revision.enabled or revision.archived
                    or job.source_id != move.source_id or job.query != move.query
                    or job.id != job_identity(job)
                    or utc(rule.created_at) > utc(move.observed_at)
                    or utc(revision.created_at) > utc(move.observed_at)
                    or utc(notice.delivered_at) < utc(move.observed_at)):
                invalid()
            event = checked_url_move(move, context, content=content)
            items.append({'id': notice.id, 'rule_id': rule.id, 'rule_name': revision.name,
                'rule_revision': revision.revision, 'read_at': stamp(notice.read_at) if notice.read_at else None,
                'delivered_at': stamp(notice.delivered_at), 'event': event})
        except (ValueError, TypeError, AttributeError):
            invalid()
    return items


def require_url_move_notification(db, notification_id, *, content=False):
    row = db.execute(url_move_notification_statement().where(
        SourcePageUrlMoveNotification.id == notification_id)).first()
    if row is None:
        raise HTTPException(404, {'code': 'source_page_url_notification_not_found',
                                  'message': '未找到来源地址迁移站内提醒。'})
    return row[0], url_move_notification_views(db, [row], content=content)[0]


class UrlMoveReadState(StrictModel):
    read: StrictBool


def register_source_page_url_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/source-page-url-move-notifications')
    def listing(mode: Literal['history'] = Query(...), unread: bool = False,
                offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=50), db=Depends(get_db)):
        statement = url_move_notification_statement()
        if unread:
            statement = statement.where(SourcePageUrlMoveNotification.read_at.is_(None))
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.order_by(desc(SourcePageUrlMoveNotification.delivered_at),
            SourcePageUrlMoveNotification.id).offset(offset).limit(limit)).all()
        return {'scope': 'local_workspace', 'data_state': 'local_snapshot',
                'items': url_move_notification_views(db, rows), 'total': total, 'offset': offset, 'limit': limit}

    @app.get('/v1/source-page-url-move-notifications/{notification_id}')
    def detail(notification_id: str, mode: Literal['history'] = Query(...), db=Depends(get_db)):
        _row, item = require_url_move_notification(db, notification_id, content=True)
        return {'scope': 'local_workspace', 'data_state': 'local_snapshot', 'item': item}

    @app.put('/v1/source-page-url-move-notifications/{notification_id}/read')
    def mark(notification_id: str, payload: UrlMoveReadState, request: Request, db=Depends(get_db)):
        from .service import QueryService
        service = QueryService(db, None)
        service.lock_ingestion()
        row, _item = require_url_move_notification(db, notification_id)
        if payload.read != (row.read_at is not None):
            row.read_at = utcnow() if payload.read else None
            service.audit(request.state.session_id, 'source_page_url_notification_read',
                          delivery_id=row.id, read=payload.read)
            db.commit()
        return {'id': row.id, 'read_at': stamp(row.read_at) if row.read_at else None}
