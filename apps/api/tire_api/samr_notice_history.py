"""Source-native Chinese notice versions and evidence-bound observation history."""
from copy import deepcopy
from datetime import datetime
import re
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, JSON, String, UniqueConstraint, desc, event, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .adapters.samr import SOURCE_ID
from .db import Base, uid, utc
from .domain import digest
from .samr_recalls import SamrRecallSnapshot, SamrRecallVerification, checked_snapshot
from .service import QueryService, timestamp

MAX_SEQUENCE = 9007199254740991


class SamrNoticeRevision(Base):
    __tablename__ = 'samr_notice_revisions'
    __table_args__ = (UniqueConstraint('article_id', 'revision'), UniqueConstraint('article_id', 'content_hash'),
        CheckConstraint('revision > 0 AND revision <= 9007199254740991'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    article_id: Mapped[str] = mapped_column(String(32), index=True)
    revision: Mapped[int] = mapped_column(BigInteger)
    content_hash: Mapped[str] = mapped_column(String(64))
    notice: Mapped[dict] = mapped_column(JSON)
    first_snapshot_id: Mapped[str] = mapped_column(ForeignKey('samr_recall_snapshots.id'))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SamrNoticeObservation(Base):
    __tablename__ = 'samr_notice_observations'
    __table_args__ = (UniqueConstraint('article_id', 'sequence'), UniqueConstraint('snapshot_id'),
        CheckConstraint('sequence > 0 AND sequence <= 9007199254740991'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    article_id: Mapped[str] = mapped_column(String(32), index=True)
    sequence: Mapped[int] = mapped_column(BigInteger)
    revision_id: Mapped[str] = mapped_column(ForeignKey('samr_notice_revisions.id'))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('samr_recall_snapshots.id'))
    verification_id: Mapped[str] = mapped_column(ForeignKey('samr_recall_verifications.id'), unique=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SamrNoticeChange(Base):
    __tablename__ = 'samr_notice_changes'
    __table_args__ = (CheckConstraint("kind IN ('first_observed', 'content_changed')"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    article_id: Mapped[str] = mapped_column(String(32), index=True)
    observation_id: Mapped[str] = mapped_column(ForeignKey('samr_notice_observations.id'), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    before_revision_id: Mapped[str | None] = mapped_column(ForeignKey('samr_notice_revisions.id'), nullable=True)
    after_revision_id: Mapped[str] = mapped_column(ForeignKey('samr_notice_revisions.id'))
    changes: Mapped[dict] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@event.listens_for(Session, 'before_flush')
def protect_notice_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (SamrNoticeRevision, SamrNoticeObservation, SamrNoticeChange)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('中国召回公告内容、观察和变化事件只能追加')


def field_changes(before, after):
    if before is None:
        return {}
    return {key: {'before': before.get(key), 'after': after.get(key)}
        for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)}


def backfill_notice_history(db):
    """Project accepted notice snapshots under the caller's ingestion lock."""
    first_verification = (select(SamrRecallVerification.snapshot_id,
        func.min(SamrRecallVerification.verified_at).label('verified_at'))
        .group_by(SamrRecallVerification.snapshot_id).subquery())
    indexed = select(SamrNoticeObservation.id).where(SamrNoticeObservation.snapshot_id == SamrRecallSnapshot.id).exists()
    snapshots = db.scalars(select(SamrRecallSnapshot).join(first_verification,
        first_verification.c.snapshot_id == SamrRecallSnapshot.id)
        .where(SamrRecallSnapshot.query['operation'].as_string() == 'notice', ~indexed)
        .order_by(first_verification.c.verified_at, SamrRecallSnapshot.id)).all()
    for snapshot in snapshots:
        checked_snapshot(snapshot)
        notice = deepcopy(snapshot.document['notice'])
        article_id = notice['article_id']
        verification = db.scalar(select(SamrRecallVerification).where(SamrRecallVerification.snapshot_id == snapshot.id)
            .order_by(SamrRecallVerification.verified_at, SamrRecallVerification.id).limit(1))
        previous = db.scalar(select(SamrNoticeObservation).where(SamrNoticeObservation.article_id == article_id)
            .order_by(desc(SamrNoticeObservation.sequence)).limit(1))
        fingerprint = digest(notice)
        revision = db.scalar(select(SamrNoticeRevision).where(SamrNoticeRevision.article_id == article_id,
            SamrNoticeRevision.content_hash == fingerprint))
        if revision is None:
            number = db.scalar(select(func.max(SamrNoticeRevision.revision)).where(SamrNoticeRevision.article_id == article_id)) or 0
            revision = SamrNoticeRevision(id=uid(), article_id=article_id, revision=number + 1,
                content_hash=fingerprint, notice=notice, first_snapshot_id=snapshot.id, observed_at=verification.verified_at)
            db.add(revision)
            db.flush()
        observation = SamrNoticeObservation(id=uid(), article_id=article_id,
            sequence=previous.sequence + 1 if previous else 1, revision_id=revision.id,
            snapshot_id=snapshot.id, verification_id=verification.id, observed_at=verification.verified_at)
        db.add(observation)
        db.flush()
        if previous is None or previous.revision_id != revision.id:
            before = db.get(SamrNoticeRevision, previous.revision_id) if previous else None
            db.add(SamrNoticeChange(id=uid(), article_id=article_id, observation_id=observation.id,
                kind='content_changed' if previous else 'first_observed',
                before_revision_id=before.id if before else None, after_revision_id=revision.id,
                changes=field_changes(before.notice if before else None, notice), observed_at=verification.verified_at))
            db.flush()
    return len(snapshots)


def bound_observation(db, row, snapshots):
    if row is None:
        raise ValueError('samr_notice_observation_missing')
    if row.snapshot_id not in snapshots:
        snapshots[row.snapshot_id] = checked_snapshot(db.get(SamrRecallSnapshot, row.snapshot_id))
    snapshot = snapshots[row.snapshot_id]
    revision = db.get(SamrNoticeRevision, row.revision_id)
    verification = db.get(SamrRecallVerification, row.verification_id)
    if revision.first_snapshot_id not in snapshots:
        snapshots[revision.first_snapshot_id] = checked_snapshot(db.get(SamrRecallSnapshot, revision.first_snapshot_id))
    first_snapshot = snapshots[revision.first_snapshot_id]
    if (snapshot.query['operation'] != 'notice' or snapshot.document['notice']['article_id'] != row.article_id
            or revision.article_id != row.article_id or snapshot.document['notice'] != revision.notice
            or first_snapshot.document['notice'] != revision.notice or digest(revision.notice) != revision.content_hash
            or verification.snapshot_id != snapshot.id or verification.query_key != snapshot.query_key
            or verification.status not in {'ok', 'not_modified'} or verification.parser_identity != snapshot.parser_identity
            or utc(verification.verified_at) != utc(row.observed_at)):
        raise ValueError('samr_notice_binding_invalid')
    return snapshot, revision


def observation_json(db, row, snapshots):
    try:
        snapshot, revision = bound_observation(db, row, snapshots)
        previous = None
        if row.sequence > 1:
            previous = db.scalar(select(SamrNoticeObservation).where(SamrNoticeObservation.article_id == row.article_id,
                SamrNoticeObservation.sequence == row.sequence - 1))
            _, before = bound_observation(db, previous, snapshots)
        else:
            before = None
        change = db.scalar(select(SamrNoticeChange).where(SamrNoticeChange.observation_id == row.id))
        changed = before is None or before.id != revision.id
        if (changed != (change is not None) or change is not None and (
                change.article_id != row.article_id or change.before_revision_id != (before.id if before else None)
                or change.after_revision_id != revision.id or change.kind != ('content_changed' if before else 'first_observed')
                or change.changes != field_changes(before.notice if before else None, revision.notice)
                or utc(change.observed_at) != utc(row.observed_at))):
            raise ValueError('samr_notice_change_invalid')
    except (AttributeError, KeyError, TypeError, ValueError):
        raise HTTPException(503, '中国召回公告历史完整性校验失败') from None
    return {'id': row.id, 'sequence': row.sequence, 'snapshot_id': row.snapshot_id,
        'verification_id': row.verification_id, 'observed_at': timestamp(row.observed_at),
        'evidence_path': f'/v1/samr-recalls/evidence/{snapshot.id}?mode=history',
        'revision': {'id': revision.id, 'revision': revision.revision, 'content_hash': revision.content_hash,
            'notice': deepcopy(revision.notice), 'first_snapshot_id': revision.first_snapshot_id},
        'event': {'id': change.id, 'kind': change.kind, 'changes': deepcopy(change.changes),
            'before_revision_id': change.before_revision_id, 'after_revision_id': change.after_revision_id,
            'previous_snapshot_id': previous.snapshot_id if previous else None} if change else None}


def register_samr_notice_history_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/samr-recalls/notices/{article_id}/history')
    def history(article_id: str, request: Request, mode: Literal['history'],
                offset: int = Query(0, ge=0, le=MAX_SEQUENCE), limit: int = Query(10, ge=1, le=50),
                through_sequence: int | None = Query(None, ge=1, le=MAX_SEQUENCE), db: Session = Depends(get_db)):
        if re.fullmatch(r'[a-f0-9]{32}', article_id, re.ASCII) is None:
            raise HTTPException(422, '中国召回公告原生文章ID无效')
        shared = QueryService(db, None)
        shared.lock_ingestion()
        projected = backfill_notice_history(db)
        latest = db.scalar(select(func.max(SamrNoticeObservation.sequence)).where(SamrNoticeObservation.article_id == article_id))
        if latest is None:
            raise HTTPException(404, '尚无此中国召回公告的已保存观察')
        if through_sequence is not None and through_sequence > latest:
            raise HTTPException(422, '中国召回公告历史观察范围无效')
        anchor = through_sequence or latest
        scope = (SamrNoticeObservation.article_id == article_id, SamrNoticeObservation.sequence <= anchor)
        rows = db.scalars(select(SamrNoticeObservation).where(*scope)
            .order_by(desc(SamrNoticeObservation.sequence)).offset(offset).limit(limit)).all()
        head = db.scalar(select(SamrNoticeObservation).where(*scope).order_by(desc(SamrNoticeObservation.sequence)).limit(1))
        snapshots = {}
        response = {'source_id': SOURCE_ID, 'article_id': article_id, 'data_state': 'local_snapshot',
            'applicability': 'not_assessed', 'offset': offset, 'limit': limit,
            'total': db.scalar(select(func.count()).select_from(SamrNoticeObservation).where(*scope)),
            'through_sequence': anchor, 'head': observation_json(db, head, snapshots),
            'observations': [observation_json(db, row, snapshots) for row in rows],
            'notices': ['观察顺序依据系统采纳过程，原发布日期、DeployTime与PubDate分别保留。',
                '首次观察表示本系统首次保存该文章，当前官方状态需在线核验。',
                '公告缺席或查询失败时保留既有观察，具体SKU及实物适用性待核对。']}
        shared.audit(request.state.session_id, 'samr_notice_history_read', article_id=article_id,
            through_sequence=anchor, offset=offset, limit=limit, projected_observations=projected)
        db.commit()
        return response
