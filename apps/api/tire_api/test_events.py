"""Event-scoped test measurements, separate from manufacturer facts and SKU identity."""
from datetime import date, datetime
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import Field, StrictInt, field_validator, model_validator
from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, desc, event, func, select
from sqlalchemy.orm import Mapped, Session, load_only, mapped_column

from .db import Base, uid, utcnow
from .documents import DocumentMetadata
from .domain import StrictModel, digest, parse_size, stable_json
from .research import DescriptionText
from .service import QueryService, timestamp


class Participant(StrictModel):
    key: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,39}$')
    brand: DescriptionText = Field(min_length=1, max_length=120)
    model: DescriptionText = Field(min_length=1, max_length=200)
    source_designation: DescriptionText = Field(default='', max_length=300)
    # A Participant is sufficient when the publication cannot identify an exact SKU.
    # No name/size-based automatic linkage to TireVariant is performed.


class MetricDefinition(StrictModel):
    key: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,39}$')
    label: DescriptionText = Field(min_length=1, max_length=120)
    unit: DescriptionText = Field(min_length=1, max_length=40)
    protocol: DescriptionText = Field(min_length=3, max_length=1000)
    direction: Literal['lower', 'higher', 'unspecified'] = 'unspecified'


class Measurement(StrictModel):
    participant_key: str = Field(min_length=1, max_length=40)
    metric_key: str = Field(min_length=1, max_length=40)
    raw_value: str = Field(pattern=r'^-?\d{1,12}(?:\.\d{1,8})?$', max_length=22)
    source_rank: StrictInt | None = Field(default=None, ge=1, le=10000)
    evidence_span: DescriptionText = Field(min_length=1, max_length=300)
    evidence_locator: DescriptionText = Field(min_length=1, max_length=300)


class EventPayload(StrictModel):
    title: DescriptionText = Field(min_length=1, max_length=200)
    organization: DescriptionText = Field(min_length=1, max_length=160)
    relationship: Literal['independent', 'manufacturer_commissioned', 'unknown']
    publication_date: date | None = None
    source_url: str = Field(min_length=1, max_length=2048)
    rights_basis: DescriptionText = Field(min_length=5, max_length=1000)
    tested_size: str = Field(max_length=24)
    vehicle: DescriptionText | None = Field(default=None, max_length=200)
    surface: DescriptionText | None = Field(default=None, max_length=200)
    conditions: DescriptionText = Field(min_length=3, max_length=2000)
    coverage: Literal['selected_results', 'full_event'] = 'selected_results'
    reported_participants: StrictInt | None = Field(default=None, ge=1, le=10000)
    participants: list[Participant] = Field(min_length=1, max_length=60)
    metrics: list[MetricDefinition] = Field(min_length=1, max_length=24)
    measurements: list[Measurement] = Field(min_length=1, max_length=1000)

    @field_validator('source_url')
    @classmethod
    def reference_url(cls, value):
        return DocumentMetadata.public_reference(value)

    @field_validator('tested_size')
    @classmethod
    def size(cls, value):
        return parse_size(value)

    @model_validator(mode='after')
    def consistent_event(self):
        people = {row.key for row in self.participants}
        metrics = {row.key for row in self.metrics}
        if len(people) != len(self.participants) or len(metrics) != len(self.metrics):
            raise ValueError('参测胎和指标标识不能重复')
        pairs = set()
        for row in self.measurements:
            if row.participant_key not in people or row.metric_key not in metrics:
                raise ValueError('成绩必须关联本场的参测胎与指标')
            pair = (row.participant_key, row.metric_key)
            if pair in pairs:
                raise ValueError('同一参测胎和同一条件指标只能有一个成绩；不同条件请另建指标')
            pairs.add(pair)
        if {x.participant_key for x in self.measurements} != people or {x.metric_key for x in self.measurements} != metrics:
            raise ValueError('每个参测胎与指标至少需要一条有证据的成绩')
        if self.reported_participants is not None and self.reported_participants < len(people):
            raise ValueError('已录入数量不得超过来源声明的参测总数')
        if self.coverage == 'full_event' and self.reported_participants != len(people):
            raise ValueError('完整场次须明确来源参测总数并录入全部参测胎')
        if any(row.source_rank and self.reported_participants and row.source_rank > self.reported_participants
               for row in self.measurements):
            raise ValueError('来源名次不得超过来源声明的参测总数')
        if sum(len(row.evidence_span) for row in self.measurements) > 8000:
            raise ValueError('仅留存有界证据短摘录，不接受全文或整篇文章镜像')
        if len(stable_json(self.model_dump(mode='json'))) > 500_000:
            raise ValueError('本次事件记录超过大小限制')
        return self


class SaveEvent(StrictModel):
    event: EventPayload
    operator: DescriptionText = Field(min_length=1, max_length=80)
    reason: DescriptionText = Field(min_length=5, max_length=2000)


class ReviseEvent(SaveEvent):
    expected_revision: StrictInt = Field(ge=1)


class EventStateRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    action: Literal['revoke', 'restore']
    operator: DescriptionText = Field(min_length=1, max_length=80)
    reason: DescriptionText = Field(min_length=5, max_length=2000)


class EventComparison(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    participant_ids: list[str] = Field(min_length=1, max_length=60)
    metric_keys: list[str] = Field(min_length=1, max_length=24)


class TireTestEvent(Base):
    __tablename__ = 'test_events'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TireTestRevision(Base):
    __tablename__ = 'test_event_revisions'
    __table_args__ = (UniqueConstraint('event_id', 'revision'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey('test_events.id'), index=True)
    revision: Mapped[int]
    state: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    operator: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_test_history(session, _context, _instances):
    for item in session.dirty | session.deleted:
        if isinstance(item, (TireTestEvent, TireTestRevision)) and (item in session.deleted or session.is_modified(item)):
            raise ValueError('测试事件和成绩历史只能追加，不能覆盖或删除')


def latest(db, event_id, expected=None):
    row = db.scalar(select(TireTestRevision).where(TireTestRevision.event_id == event_id)
        .order_by(desc(TireTestRevision.revision)).limit(1))
    if row is None:
        raise HTTPException(404, '未找到测试事件')
    if expected is not None and expected != row.revision:
        raise HTTPException(409, '测试事件已更新，请重新载入并核对')
    return row


def metadata(row):
    return {'id': row.event_id, 'revision': row.revision, 'revision_id': row.id, 'state': row.state,
            **row.summary,
            'recorded_at': timestamp(row.created_at), 'fingerprint': row.fingerprint,
            'record_kind': 'manual_transcription', 'verification_status': 'unverified', 'verified_at': None}


def metadata_columns():
    return [getattr(TireTestRevision, col.name) for col in TireTestRevision.__table__.columns if col.name != 'payload']


def detail(db, row):
    history = db.scalars(select(TireTestRevision).options(load_only(*metadata_columns())).where(TireTestRevision.event_id == row.event_id)
        .order_by(desc(TireTestRevision.revision)).limit(101)).all()
    return {**metadata(row), 'data_state': 'local_snapshot', 'scope': 'local_workspace',
            'event': row.payload,
            'participants': [{**p, 'id': f'{row.event_id}:{p["key"]}', 'identity_status': 'participant_only'}
                             for p in row.payload['participants']],
            'history': [{'id': r.id, 'revision': r.revision, 'action': r.action, 'state': r.state,
                         'operator': r.operator, 'reason': r.reason, 'recorded_at': timestamp(r.created_at),
                         'fingerprint': r.fingerprint} for r in history[:100]], 'history_truncated': len(history) > 100}


def append(db, event_id, payload, action, state, operator, reason, session_id, revision):
    row = TireTestRevision(event_id=event_id, revision=revision, state=state, action=action,
        payload=payload, fingerprint=digest(payload), operator=operator, reason=reason, actor_session_id=session_id,
        summary={**{key: payload[key] for key in ('title', 'organization', 'tested_size', 'publication_date', 'relationship', 'coverage')},
                 'participant_count': len(payload['participants']), 'metric_count': len(payload['metrics'])})
    db.add(row)
    db.flush()
    QueryService(db, None).audit(session_id, 'test_event_revision_recorded', event_id=event_id,
                               revision_id=row.id, revision=revision, operation=action)
    db.commit()
    return detail(db, row)


def register_test_event_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/test-events', status_code=201)
    def create(payload: SaveEvent, request: Request, db: Session = Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        item = TireTestEvent(id=uid())
        db.add(item)
        db.flush()
        return append(db, item.id, payload.event.model_dump(mode='json'), 'create', 'active',
                      payload.operator, payload.reason, request.state.session_id, 1)

    @app.get('/v1/test-events')
    def listing(mode: Literal['history'] = Query(...), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
        heads = select(TireTestRevision.event_id, func.max(TireTestRevision.revision).label('revision')).group_by(
            TireTestRevision.event_id).subquery()
        rows = db.scalars(select(TireTestRevision).options(load_only(*metadata_columns())).join(heads,
            (heads.c.event_id == TireTestRevision.event_id) & (heads.c.revision == TireTestRevision.revision))
            .order_by(desc(TireTestRevision.created_at), desc(TireTestRevision.id)).offset(offset).limit(50)).all()
        return {'data_state': 'local_snapshot', 'items': [metadata(row) for row in rows], 'offset': offset,
                'total': db.scalar(select(func.count()).select_from(TireTestEvent)) or 0}

    @app.get('/v1/test-events/{event_id}')
    def read(event_id: str, request: Request, mode: Literal['history'] = Query(...),
             revision: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
        row = latest(db, event_id) if revision is None else db.scalar(select(TireTestRevision)
            .where(TireTestRevision.event_id == event_id, TireTestRevision.revision == revision))
        if row is None:
            raise HTTPException(404, '未找到该事件修订')
        QueryService(db, None).audit(request.state.session_id, 'test_event_history_read',
                                    event_id=event_id, revision=row.revision)
        db.commit()
        return detail(db, row)

    @app.put('/v1/test-events/{event_id}')
    def revise(event_id: str, payload: ReviseEvent, request: Request, db: Session = Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        old = latest(db, event_id, payload.expected_revision)
        if old.state == 'revoked':
            raise HTTPException(409, '测试事件已撤销，请先明确恢复后再修订')
        value = payload.event.model_dump(mode='json')
        if digest(value) == old.fingerprint:
            raise HTTPException(409, '测试内容未变化，无需新增修订')
        return append(db, event_id, value, 'revise', 'active', payload.operator, payload.reason,
                      request.state.session_id, old.revision + 1)

    @app.post('/v1/test-events/{event_id}/state')
    def set_state(event_id: str, payload: EventStateRequest, request: Request, db: Session = Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        old = latest(db, event_id, payload.expected_revision)
        desired = 'revoked' if payload.action == 'revoke' else 'active'
        if old.state == desired:
            raise HTTPException(409, '事件已处于此状态')
        return append(db, event_id, old.payload, payload.action, desired, payload.operator, payload.reason,
                      request.state.session_id, old.revision + 1)

    @app.post('/v1/test-events/{event_id}/compare')
    def compare(event_id: str, payload: EventComparison, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        row = latest(db, event_id, payload.expected_revision)
        if row.state == 'revoked':
            raise HTTPException(409, '已撤销事件不参与成绩比较，原记录仍可按历史查看')
        people = {f'{event_id}:{p["key"]}': p for p in row.payload['participants']}
        metrics = {m['key']: m for m in row.payload['metrics']}
        if (len(set(payload.participant_ids)) != len(payload.participant_ids)
                or not set(payload.participant_ids) <= people.keys()
                or len(set(payload.metric_keys)) != len(payload.metric_keys)
                or not set(payload.metric_keys) <= metrics.keys()):
            raise HTTPException(422, '只能比较同一事件内不同参测胎及本场指标；不能混入其他场次')
        selected = {people[k]['key'] for k in payload.participant_ids}
        measurements = [m for m in row.payload['measurements']
                        if m['participant_key'] in selected and m['metric_key'] in payload.metric_keys]
        # Preserve original decimals and source ranks. No rank recomputation on a subset,
        # cross-event unit conversion, inferred overall score, or fact overwrite.
        return {**metadata(row), 'data_state': 'local_snapshot', 'comparison_scope': 'same_event_only',
                'event': {k: v for k, v in row.payload.items() if k not in {'participants', 'metrics', 'measurements'}},
                'participants': [{**people[k], 'id': k} for k in payload.participant_ids],
                'metrics': [metrics[k] for k in payload.metric_keys], 'measurements': measurements,
                'ranking': 'source_reported_only', 'notice': '人工录入的历史测试记录，未经在线核验；不同事件不可直接排名，缺少成绩不等于零。'}
