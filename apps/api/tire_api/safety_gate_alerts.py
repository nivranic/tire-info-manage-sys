"""Source-native alert content, report observations and append-only change events."""
from copy import deepcopy
from datetime import datetime
import re
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, desc, event, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .adapters.safety_gate import SOURCE_ID
from .db import Base, uid
from .domain import digest
from .safety_gate import SafetyGateSnapshot, SafetyGateVerification, checked_snapshot
from .service import QueryService, timestamp


class AlertRevision(Base):
    __tablename__ = 'safety_gate_alert_revisions'
    __table_args__ = (UniqueConstraint('alert_id', 'revision'), UniqueConstraint('alert_id', 'content_hash'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    alert_id: Mapped[str] = mapped_column(String(16), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    alert: Mapped[dict] = mapped_column(JSON)
    first_snapshot_id: Mapped[str] = mapped_column(ForeignKey('safety_gate_snapshots.id'))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AlertObservation(Base):
    __tablename__ = 'safety_gate_alert_observations'
    __table_args__ = (UniqueConstraint('alert_id', 'sequence'), UniqueConstraint('snapshot_id', 'alert_id'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    alert_id: Mapped[str] = mapped_column(String(16), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    revision_id: Mapped[str] = mapped_column(ForeignKey('safety_gate_alert_revisions.id'))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('safety_gate_snapshots.id'), index=True)
    position: Mapped[int] = mapped_column(Integer)
    report_id: Mapped[str] = mapped_column(String(16))
    report_reference: Mapped[str] = mapped_column(String(24))
    report_published_date: Mapped[str] = mapped_column(String(10))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AlertChange(Base):
    __tablename__ = 'safety_gate_alert_changes'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    alert_id: Mapped[str] = mapped_column(String(16), index=True)
    observation_id: Mapped[str] = mapped_column(ForeignKey('safety_gate_alert_observations.id'), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    before_revision_ids: Mapped[list] = mapped_column(JSON)
    after_revision_ids: Mapped[list] = mapped_column(JSON)
    changes: Mapped[dict] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@event.listens_for(Session, 'before_flush')
def protect_alert_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (AlertRevision, AlertObservation, AlertChange)) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('Safety Gate告警内容、观察和变化事件只能追加')


def content(alert):
    value = deepcopy(alert)
    del value['fields']['order']
    return value


def observed_heads(db, alert_id, through_sequence):
    scope = (AlertObservation.alert_id == alert_id, AlertObservation.sequence <= through_sequence)
    sequences = (select(func.max(AlertObservation.sequence)).where(*scope)
        .group_by(AlertObservation.report_id).correlate(None))
    report_heads = (select(AlertObservation.id, AlertObservation.report_published_date)
        .where(*scope, AlertObservation.sequence.in_(sequences)).cte())
    newest_date = select(func.max(report_heads.c.report_published_date)).correlate(None).scalar_subquery()
    return db.scalars(select(AlertObservation).join(report_heads, report_heads.c.id == AlertObservation.id)
        .where(report_heads.c.report_published_date == newest_date)
        .order_by(desc(AlertObservation.sequence))).all()


def head_versions(heads):
    return sorted({row.revision_id for row in heads})


def change_kind(before, after):
    if not before:
        return 'first_observed'
    if len(after) > 1:
        return 'conflict_observed'
    if len(before) > 1:
        return 'conflict_resolved'
    return 'content_changed'


def field_changes(db, before, after):
    if not before:
        return {}
    if len(before) != 1 or len(after) != 1:
        return {'content_versions': {'before': before, 'after': after}}
    values = []
    for identity in [before[0], after[0]]:
        alert = db.get(AlertRevision, identity).alert
        values.append({**{key: value for key, value in alert.items() if key != 'fields'},
            **{'fields.' + key: value for key, value in alert['fields'].items()}})
    old, new = values
    return {key: {'before': old.get(key), 'after': new.get(key)} for key in sorted(old.keys() | new.keys())
        if old.get(key) != new.get(key)}


def backfill_alert_history(db):
    """Project accepted snapshots while the caller owns the ingestion transaction."""
    first_verified = (select(SafetyGateVerification.snapshot_id,
        func.min(SafetyGateVerification.verified_at).label('observed_at'))
        .group_by(SafetyGateVerification.snapshot_id).subquery())
    indexed = select(AlertObservation.id).where(AlertObservation.snapshot_id == SafetyGateSnapshot.id).exists()
    snapshots = db.execute(select(SafetyGateSnapshot, first_verified.c.observed_at)
        .join(first_verified, first_verified.c.snapshot_id == SafetyGateSnapshot.id)
        .where(SafetyGateSnapshot.query['operation'].as_string() == 'report', ~indexed)
        .order_by(first_verified.c.observed_at, SafetyGateSnapshot.id)).all()
    count = 0
    for snapshot, observed_at in snapshots:
        checked_snapshot(snapshot)
        report = snapshot.document['report']
        for position, alert in enumerate(snapshot.document['alerts'], 1):
            alert_id = alert['alert_id']
            last_sequence = db.scalar(select(func.max(AlertObservation.sequence)).where(AlertObservation.alert_id == alert_id)) or 0
            before = head_versions(observed_heads(db, alert_id, last_sequence))
            value = content(alert)
            fingerprint = digest(value)
            revision = db.scalar(select(AlertRevision).where(AlertRevision.alert_id == alert_id, AlertRevision.content_hash == fingerprint))
            if revision is None:
                number = db.scalar(select(func.max(AlertRevision.revision)).where(AlertRevision.alert_id == alert_id)) or 0
                revision = AlertRevision(id=uid(), alert_id=alert_id, revision=number + 1,
                    content_hash=fingerprint, alert=value, first_snapshot_id=snapshot.id, observed_at=observed_at)
                db.add(revision)
                db.flush()
            observation = AlertObservation(id=uid(), alert_id=alert_id, sequence=last_sequence + 1,
                revision_id=revision.id, snapshot_id=snapshot.id, position=position,
                report_id=report['report_id'], report_reference=report['reference'],
                report_published_date=report['published_date'], observed_at=observed_at)
            db.add(observation)
            db.flush()
            after = head_versions(observed_heads(db, alert_id, observation.sequence))
            if before != after:
                db.add(AlertChange(id=uid(), alert_id=alert_id, observation_id=observation.id,
                    kind=change_kind(before, after), before_revision_ids=before, after_revision_ids=after,
                    changes=field_changes(db, before, after), observed_at=observed_at))
                db.flush()
            count += 1
    return count


def observation_json(db, row, snapshots):
    try:
        if row.snapshot_id not in snapshots:
            snapshots[row.snapshot_id] = checked_snapshot(db.get(SafetyGateSnapshot, row.snapshot_id))
        snapshot = snapshots[row.snapshot_id]
        alert = snapshot.document['alerts'][row.position - 1]
        report = snapshot.document['report']
        revision = db.get(AlertRevision, row.revision_id)
        if (row.position < 1 or alert['alert_id'] != row.alert_id or revision.alert_id != row.alert_id
                or content(alert) != revision.alert or digest(revision.alert) != revision.content_hash
                or row.report_id != report['report_id'] or row.report_reference != report['reference']
                or row.report_published_date != report['published_date']):
            raise ValueError('safety_gate_alert_binding_invalid')
        change = db.scalar(select(AlertChange).where(AlertChange.observation_id == row.id))
        before = head_versions(observed_heads(db, row.alert_id, row.sequence - 1))
        after = head_versions(observed_heads(db, row.alert_id, row.sequence))
        if ((before != after) != (change is not None) or change is not None and (
                change.alert_id != row.alert_id or change.before_revision_ids != before or change.after_revision_ids != after
                or change.kind != change_kind(before, after) or change.changes != field_changes(db, before, after))):
            raise ValueError('safety_gate_alert_change_invalid')
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        raise HTTPException(503, 'Safety Gate告警历史完整性校验失败') from None
    return {'id': row.id, 'sequence': row.sequence, 'snapshot_id': row.snapshot_id, 'position': row.position,
        'report': report, 'observed_at': timestamp(row.observed_at),
        'evidence_path': f'/v1/safety-gate/evidence/{row.snapshot_id}?mode=history',
        'revision': {'id': revision.id, 'revision': revision.revision, 'content_hash': revision.content_hash,
            'alert': revision.alert, 'first_snapshot_id': revision.first_snapshot_id},
        'event': {'id': change.id, 'kind': change.kind, 'changes': change.changes,
            'before_revision_ids': before, 'after_revision_ids': after} if change else None}


def register_alert_history_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/safety-gate/alerts/{alert_id}/history')
    def history(alert_id: str, request: Request, mode: Literal['history'],
                offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=50),
                through_sequence: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
        if not re.fullmatch(r'-?[1-9][0-9]{0,11}', alert_id, re.ASCII):
            raise HTTPException(422, 'Safety Gate告警原生ID无效')
        shared = QueryService(db, None)
        shared.lock_ingestion()
        projected = backfill_alert_history(db)
        latest = db.scalar(select(func.max(AlertObservation.sequence)).where(AlertObservation.alert_id == alert_id))
        if latest is None:
            raise HTTPException(404, '尚无对应Safety Gate告警的已保存观察')
        if through_sequence is not None and through_sequence > latest:
            raise HTTPException(422, 'Safety Gate历史观察范围无效')
        anchor = through_sequence or latest
        scope = (AlertObservation.alert_id == alert_id, AlertObservation.sequence <= anchor)
        total = db.scalar(select(func.count()).select_from(AlertObservation).where(*scope))
        rows = db.scalars(select(AlertObservation).where(*scope).order_by(desc(AlertObservation.sequence))
            .offset(offset).limit(limit)).all()
        heads = observed_heads(db, alert_id, anchor)
        snapshots = {}
        response = {'source_id': SOURCE_ID, 'alert_id': alert_id, 'data_state': 'local_snapshot',
            'applicability': 'not_assessed', 'state': 'conflicting' if len(head_versions(heads)) > 1 else 'observed',
            'offset': offset, 'limit': limit, 'total': total, 'through_sequence': anchor,
            'heads': [observation_json(db, row, snapshots) for row in heads],
            'observations': [observation_json(db, row, snapshots) for row in rows],
            'notices': ['范围为已保存的英文周报告警，内容版本排除周报内展示序号。',
                '最新观察按周报发布日期选取，同日不同周报的内容冲突显式保留。',
                '告警缺席时保留上次观察，具体SKU及实物适用性继续待核对。']}
        shared.audit(request.state.session_id, 'safety_gate_alert_history_read', alert_id=alert_id,
            through_sequence=anchor, offset=offset, limit=limit, projected_observations=projected)
        db.commit()
        return response
