"""Owned programmatic data permission, independent of devices, AI and sync.

All previews contain metadata only. A failed attempt burns its own durable use
before reading answer material; policy changes are append-only revisions.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Header, HTTPException, Query, Request
from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator
from sqlalchemy import BigInteger, DateTime, ForeignKey, JSON, String, UniqueConstraint, event, func, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, FallbackConsent, QueryRun, UserSession, uid, utc, utcnow
from .domain import StrictModel, digest
from .source_settings import SourceAccessBlocked, SourceSettingError, assert_source_run_access, source_setting

QueryKind = Literal['tire', 'vehicle_fitments', 'recall_campaign', 'recall_search']
QueryAudience = Literal['programmatic', 'ai_current', 'background_monitor', 'internal']
PolicyMode = Literal['ask', 'never', 'session_allow', 'source_allow', 'query_allow']
ALLOW_MODES = frozenset({'session_allow', 'source_allow', 'query_allow'})
ELIGIBLE_FAILURES = frozenset({'upstream_network_error', 'upstream_timeout'})
MAX_POLICIES = 16
PREVIEW_TTL = 300
SAFE_INTEGER = 9007199254740991


def fail(code, status=409):
    raise HTTPException(status, {'code': code})


def stamp(value):
    return utc(value).isoformat().replace('+00:00', 'Z')


def date(value):
    return utc(datetime.fromisoformat(value.replace('Z', '+00:00')))


def owner_scope(session_id):
    return digest({'namespace': 'offline-owner-scope@1', 'session': session_id})


class SourceBinding(StrictModel):
    source_id: str = Field(pattern=r'^[a-z0-9-]{1,80}$')
    access_generation: StrictInt = Field(ge=0, le=SAFE_INTEGER)


class SourceKindsBinding(SourceBinding):
    query_kinds: list[QueryKind] = Field(min_length=1, max_length=4)

    @field_validator('query_kinds')
    @classmethod
    def canonical_kinds(cls, values):
        return sorted(set(values))


class SessionScope(StrictModel):
    kind: Literal['session']
    sources: list[SourceKindsBinding] = Field(min_length=1, max_length=10)


class SourceScope(SourceKindsBinding):
    kind: Literal['source']


class QueryScope(StrictModel):
    kind: Literal['query']
    query_kind: QueryKind
    sources: list[SourceBinding] = Field(min_length=1, max_length=10)


TypedScope = Annotated[SessionScope | SourceScope | QueryScope, Field(discriminator='kind')]


class PolicyPreviewRequest(StrictModel):
    mode: PolicyMode
    scope: TypedScope
    expires_in_seconds: StrictInt = Field(default=86400, ge=900, le=604800)
    policy_id: str | None = Field(default=None, min_length=1, max_length=64)
    expected_revision: StrictInt = Field(default=0, ge=0, le=SAFE_INTEGER)

    @model_validator(mode='after')
    def correct_scope(self):
        expected = {'session_allow': 'session', 'source_allow': 'source', 'query_allow': 'query'}.get(self.mode)
        if expected is not None and self.scope.kind != expected:
            raise ValueError('授权策略与范围类型不匹配')
        if self.policy_id is None and self.expected_revision != 0:
            raise ValueError('新策略的 expected_revision 必须为 0')
        if self.policy_id is not None:
            try:
                UUID(self.policy_id)
            except ValueError:
                raise ValueError('policy_id 必须为 UUID') from None
        return self


class PolicyApplyRequest(StrictModel):
    preview_id: str = Field(min_length=1, max_length=64)
    expected_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    expected_revision: StrictInt = Field(ge=0, le=SAFE_INTEGER)
    allow_continuous_history_fallback: StrictBool

    @field_validator('allow_continuous_history_fallback')
    @classmethod
    def explicit_permission(cls, value):
        if value is not True:
            raise ValueError('需要明确确认此查询回退策略')
        return value


class PolicyChangeRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=1, le=SAFE_INTEGER)


class QueryFallbackPreview(Base):
    __tablename__ = 'query_fallback_previews'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(ForeignKey('local_sessions.id'), index=True)
    policy_id: Mapped[str] = mapped_column(String(64), index=True)
    expected_revision: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QueryFallbackPolicyRevision(Base):
    __tablename__ = 'query_fallback_policy_revisions'
    __table_args__ = (UniqueConstraint('policy_id', 'revision'),
                      UniqueConstraint('actor_session_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    policy_id: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(BigInteger)
    actor_session_id: Mapped[str] = mapped_column(ForeignKey('local_sessions.id'), index=True)
    state: Mapped[str] = mapped_column(String(12))
    mode: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QueryFallbackUse(Base):
    __tablename__ = 'query_fallback_uses'
    __table_args__ = (UniqueConstraint('query_id', 'query_kind', 'audience'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(ForeignKey('local_sessions.id'), index=True)
    policy_id: Mapped[str] = mapped_column(String(64), index=True)
    policy_revision: Mapped[int] = mapped_column(BigInteger)
    query_id: Mapped[str] = mapped_column(ForeignKey('query_runs.id'), index=True)
    query_kind: Mapped[str] = mapped_column(String(24))
    audience: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_policy_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (QueryFallbackPolicyRevision, QueryFallbackUse)):
            if row in session.deleted or session.is_modified(row):
                raise ValueError('查询回退策略修订和消费回执只能追加')
        if isinstance(row, QueryFallbackPreview):
            changed = {attr.key for attr in inspect(row).attrs if attr.history.has_changes()}
            if row in session.deleted or changed - {'applied_at'}:
                raise ValueError('查询回退预览内容不可修改')


def lock(db):
    from .service import QueryService
    QueryService(db, None).lock_ingestion()


def current_owner(db, session_id):
    row = db.get(UserSession, session_id, populate_existing=True)
    if row is None or utc(row.expires_at) <= utcnow():
        fail('query_fallback_session_required', 401)
    return row


def checked(row):
    if row.fingerprint != digest(row.payload):
        fail('query_fallback_integrity_failed', 503)
    if isinstance(row, QueryFallbackPolicyRevision) and (
            row.payload.get('id') != row.policy_id or row.payload.get('revision') != row.revision
            or row.payload.get('state') != row.state or row.payload.get('mode') != row.mode
            or row.payload.get('schema') != 'query-fallback-policy@1'
            or row.payload.get('audience') != 'programmatic'
            or row.payload.get('owner_scope_id') != owner_scope(row.actor_session_id)
            or date(row.payload['expires_at']) != utc(row.expires_at)):
        fail('query_fallback_integrity_failed', 503)
    if isinstance(row, QueryFallbackUse) and (
            row.payload.get('id') != row.id or row.payload.get('query_id') != row.query_id
            or row.payload.get('policy_id') != row.policy_id or row.payload.get('policy_revision') != row.policy_revision
            or row.payload.get('query_kind') != row.query_kind or row.payload.get('audience') != row.audience):
        fail('query_fallback_integrity_failed', 503)
    return row


def latest_statement(session_id):
    heads = select(QueryFallbackPolicyRevision.policy_id,
                   func.max(QueryFallbackPolicyRevision.revision).label('revision')).where(
                       QueryFallbackPolicyRevision.actor_session_id == session_id).group_by(
                           QueryFallbackPolicyRevision.policy_id).subquery()
    return select(QueryFallbackPolicyRevision).join(heads,
        (QueryFallbackPolicyRevision.policy_id == heads.c.policy_id)
        & (QueryFallbackPolicyRevision.revision == heads.c.revision)).where(
            QueryFallbackPolicyRevision.actor_session_id == session_id)


def latest(db, session_id, policy_id):
    row = db.scalar(latest_statement(session_id).where(QueryFallbackPolicyRevision.policy_id == policy_id))
    return checked(row) if row is not None else None


def view(row):
    return {**deepcopy(checked(row).payload), 'fingerprint': row.fingerprint}


def canonical_scope(scope):
    value = scope.model_dump() if hasattr(scope, 'model_dump') else deepcopy(scope)
    if value['kind'] != 'source':
        sources = value['sources']
        if len({item['source_id'] for item in sources}) != len(sources):
            fail('query_fallback_duplicate_source', 422)
        value['sources'] = sorted(sources, key=lambda item: item['source_id'])
    return value


def bindings(scope):
    if scope['kind'] == 'source':
        return [{key: scope[key] for key in ('source_id', 'access_generation', 'query_kinds')}]
    if scope['kind'] == 'query':
        return [{**source, 'query_kinds': [scope['query_kind']]} for source in scope['sources']]
    return scope['sources']


def scope_metadata(db, registry, scope, *, require_fetch=True):
    result = []
    for binding in bindings(scope):
        try:
            source = source_setting(db, binding['source_id'], registry=registry)
        except SourceSettingError as error:
            fail(error.code, error.status_code)
        if (source['management']['access_generation'] != binding['access_generation']
                or require_fetch and not source['can_fetch']):
            fail('query_fallback_source_changed')
        kinds = ({'vehicle_fitments'} if source['target_kind'] == 'vehicle' else
                 {'recall_campaign', 'recall_search'} if binding['source_id'] == 'nhtsa-us-recalls'
                 and source['target_kind'] == 'recall' else {'tire'} if source['target_kind'] == 'tire' else set())
        if not set(binding['query_kinds']).issubset(kinds):
            fail('query_fallback_source_kind_mismatch', 422)
        result.append({'source_id': binding['source_id'], 'access_generation': binding['access_generation'],
                       'query_kinds': sorted(binding['query_kinds']), 'fingerprint': source['fingerprint']})
    return result


def idempotency_key(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        fail('query_fallback_idempotency_key_invalid', 422)


def replay(db, session_id, key, request_hash):
    row = db.scalar(select(QueryFallbackPolicyRevision).where(
        QueryFallbackPolicyRevision.actor_session_id == session_id,
        QueryFallbackPolicyRevision.idempotency_key == key))
    if row is not None and row.request_hash != request_hash:
        fail('query_fallback_idempotency_payload_mismatch')
    return row


def append_revision(db, session_id, payload, key, request_hash):
    row = QueryFallbackPolicyRevision(policy_id=payload['id'], revision=payload['revision'],
        actor_session_id=session_id, state=payload['state'], mode=payload['mode'], payload=deepcopy(payload),
        fingerprint=digest(payload), idempotency_key=key, request_hash=request_hash,
        expires_at=date(payload['expires_at']))
    db.add(row)
    from .service import QueryService
    QueryService(db, None).audit(session_id, 'query_fallback_policy_changed', policy_id=payload['id'],
                               revision=payload['revision'], state=payload['state'], mode=payload['mode'])
    return row


def preview_policy(db, registry, request, session_id):
    lock(db)
    owner = current_owner(db, session_id)
    current = latest(db, session_id, request.policy_id) if request.policy_id else None
    if request.policy_id and current is None:
        fail('query_fallback_policy_not_found', 404)
    if (current.revision if current else 0) != request.expected_revision:
        fail('query_fallback_revision_conflict')
    now = utcnow()
    pending = db.scalar(select(func.count()).select_from(QueryFallbackPreview).where(
        QueryFallbackPreview.actor_session_id == session_id, QueryFallbackPreview.applied_at.is_(None),
        QueryFallbackPreview.expires_at > now)) or 0
    if pending >= MAX_POLICIES:
        fail('query_fallback_preview_limit', 429)
    scope = canonical_scope(request.scope)
    metadata = scope_metadata(db, registry, scope, require_fetch=request.mode in ALLOW_MODES)
    expiry = min(utc(owner.expires_at), now + timedelta(seconds=request.expires_in_seconds))
    if expiry < now + timedelta(seconds=900):
        fail('query_fallback_session_expiry_too_close')
    proposed = {'schema': 'query-fallback-policy@1', 'layer': 'canonical_warehouse',
        'id': request.policy_id or uid(), 'revision': request.expected_revision + 1, 'state': 'enabled',
        'mode': request.mode, 'audience': 'programmatic', 'owner_scope_id': owner_scope(session_id),
        'scope': scope, 'approved_at': None, 'expires_at': stamp(expiry), 'updated_at': None, 'reason': None}
    payload = {'schema': 'query-fallback-policy-preview@1', 'preview_id': uid(),
        'expires_at': stamp(min(expiry, now + timedelta(seconds=PREVIEW_TTL))),
        'expected_revision': request.expected_revision, 'owner_scope_id': owner_scope(session_id),
        'proposed_policy': proposed, 'source_metadata': metadata,
        'notice': '仅授权明确范围内普通查询失败后的历史读取；不授权设备安装、更新、外发、AI或OS任务。'}
    fingerprint = digest(payload)
    db.add(QueryFallbackPreview(id=payload['preview_id'], actor_session_id=session_id,
        policy_id=proposed['id'], expected_revision=request.expected_revision, payload=deepcopy(payload),
        fingerprint=fingerprint, expires_at=date(payload['expires_at'])))
    db.commit()
    return {**payload, 'fingerprint': fingerprint}


def apply_policy(db, registry, request, session_id, key):
    lock(db)
    current_owner(db, session_id)
    key = idempotency_key(key)
    request_hash = digest({'action': 'apply', **request.model_dump()})
    old = replay(db, session_id, key, request_hash)
    if old is not None:
        return view(old)
    preview = db.scalar(select(QueryFallbackPreview).where(
        QueryFallbackPreview.id == request.preview_id, QueryFallbackPreview.actor_session_id == session_id))
    if preview is None:
        fail('query_fallback_preview_not_found', 404)
    checked(preview)
    if preview.fingerprint != request.expected_fingerprint or preview.expected_revision != request.expected_revision:
        fail('query_fallback_preview_mismatch')
    now = utcnow()
    if utc(preview.expires_at) <= now or now < utc(preview.created_at):
        fail('query_fallback_preview_expired')
    proposed = deepcopy(preview.payload['proposed_policy'])
    current = latest(db, session_id, preview.policy_id)
    if (current.revision if current else 0) != request.expected_revision:
        fail('query_fallback_revision_conflict')
    if scope_metadata(db, registry, proposed['scope'], require_fetch=proposed['mode'] in ALLOW_MODES) != preview.payload['source_metadata']:
        fail('query_fallback_preview_stale')
    active = db.scalar(select(func.count()).select_from(latest_statement(session_id).where(
        QueryFallbackPolicyRevision.state == 'enabled', QueryFallbackPolicyRevision.expires_at > now).subquery())) or 0
    adding_active = current is None or current.state != 'enabled' or utc(current.expires_at) <= now
    if adding_active and active >= MAX_POLICIES:
        fail('query_fallback_policy_limit', 429)
    claimed = db.execute(update(QueryFallbackPreview).where(QueryFallbackPreview.id == preview.id,
        QueryFallbackPreview.applied_at.is_(None), QueryFallbackPreview.expires_at > now).values(applied_at=now)
        .execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        fail('query_fallback_preview_already_applied')
    proposed.update(approved_at=stamp(now), updated_at=stamp(now))
    row = append_revision(db, session_id, proposed, key, request_hash)
    db.commit()
    return view(row)


def change_policy(db, request, session_id, policy_id, key, state):
    lock(db)
    current_owner(db, session_id)
    key = idempotency_key(key)
    request_hash = digest({'action': state, 'policy_id': policy_id, **request.model_dump()})
    old = replay(db, session_id, key, request_hash)
    if old is not None:
        return view(old)
    current = latest(db, session_id, policy_id)
    if current is None:
        fail('query_fallback_policy_not_found', 404)
    if current.revision != request.expected_revision:
        fail('query_fallback_revision_conflict')
    payload = deepcopy(current.payload)
    payload.update(revision=current.revision + 1, state=state, updated_at=stamp(utcnow()), reason=state)
    row = append_revision(db, session_id, payload, key, request_hash)
    db.commit()
    return view(row)


def matches(row, run, query_kind):
    return any(binding['source_id'] == run.source_id
               and binding['access_generation'] == run.source_access_generation
               and query_kind in binding['query_kinds'] for binding in bindings(row.payload['scope']))


def source_authority(db, registry, run):
    try:
        assert_source_run_access(db, run, registry=registry)
    except SourceSettingError as error:
        fail(error.code, error.status_code)


def effective_decision(db, registry, run, query_kind, audience):
    if audience != 'programmatic':
        return 'ask', None
    rows = [checked(row) for row in db.scalars(latest_statement(run.session_id).where(
        QueryFallbackPolicyRevision.state == 'enabled', QueryFallbackPolicyRevision.expires_at > utcnow()))]
    rows = [row for row in rows if matches(row, run, query_kind)]
    if not rows:
        return 'ask', None
    current_owner(db, run.session_id)
    source_authority(db, registry, run)
    for row in rows:
        if utcnow() < date(row.payload['approved_at']) or utcnow() < date(row.payload['updated_at']):
            payload = deepcopy(row.payload)
            payload.update(revision=row.revision + 1, state='paused', reason='clock_regression', updated_at=stamp(utcnow()))
            append_revision(db, run.session_id, payload, uid(), digest({'clock_regression': row.id}))
            db.commit()
            return 'ask', None
    never = next((row for row in rows if row.mode == 'never'), None)
    if never is not None:
        return 'never', never
    asking = next((row for row in rows if row.mode == 'ask'), None)
    if asking is not None:
        return 'ask', asking
    rows = [row for row in rows if row.mode in ALLOW_MODES]
    rank = {'query': 0, 'source': 1, 'session': 2}
    rows.sort(key=lambda row: (rank[row.payload['scope']['kind']], -date(row.payload['approved_at']).timestamp(), row.policy_id))
    return ('allow', rows[0]) if rows else ('ask', None)


def assert_once_policy(db, registry, run, query_kind, audience):
    if audience != 'programmatic':
        return
    lock(db)
    mode, _ = effective_decision(db, registry, run, query_kind, audience)
    if mode == 'never':
        fail('query_fallback_never', 403)


def claim_policy_use(db, registry, run, query_kind, audience, *, failure_reason=None):
    if audience != 'programmatic' or run.fallback_policy != 'ask':
        return None
    lock(db)
    mode, policy = effective_decision(db, registry, run, query_kind, audience)
    if mode == 'never':
        run.state = 'source_unavailable'
        db.commit()
        return None
    cause = run.reason if failure_reason is None else failure_reason
    if (mode != 'allow' or cause not in ELIGIBLE_FAILURES
            or db.scalar(select(FallbackConsent.id).where(FallbackConsent.query_id == run.id)) is not None):
        return None
    scope_metadata(db, registry, policy.payload['scope'])
    now = utcnow()
    payload = {'schema': 'query-fallback-use@1', 'id': uid(), 'policy_id': policy.policy_id,
        'policy_revision': policy.revision, 'query_id': run.id, 'query_kind': query_kind,
        'audience': 'programmatic', 'data_state': 'local_snapshot', 'reason': cause,
        'criteria_fingerprint': digest({'source_id': run.source_id, 'source_access_generation': run.source_access_generation,
                                      'query_kind': query_kind, 'query': run.query, 'filters': run.selection_filters or []}),
        'claimed_at': stamp(now), 'expires_at': stamp(now + timedelta(seconds=300)), 'scope': 'policy_once'}
    use = QueryFallbackUse(id=payload['id'], actor_session_id=run.session_id, policy_id=policy.policy_id,
        policy_revision=policy.revision, query_id=run.id, query_kind=query_kind, audience='programmatic',
        payload=payload, fingerprint=digest(payload), created_at=now)
    db.add(use)
    run.state = 'local_snapshot'
    from .service import QueryService
    QueryService(db, None).audit(run.session_id, 'query_fallback_policy_claimed', run.id,
                               policy_id=policy.policy_id, policy_revision=policy.revision, use_id=use.id)
    try:
        db.commit()  # Durable burn and audit precede every historical business-content read.
    except IntegrityError:
        db.rollback()
        fail('query_fallback_attempt_already_used')
    revalidate_use(db, registry, run, use)
    return use


def revalidate_use(db, registry, run, use):
    lock(db)
    checked(use)
    if utcnow() < date(use.payload['claimed_at']) or date(use.payload['expires_at']) <= utcnow():
        fail('query_fallback_use_expired')
    db.refresh(run)
    current_owner(db, run.session_id)
    source_authority(db, registry, run)
    criteria = digest({'source_id': run.source_id, 'source_access_generation': run.source_access_generation,
                       'query_kind': use.query_kind, 'query': run.query, 'filters': run.selection_filters or []})
    if criteria != use.payload['criteria_fingerprint']:
        fail('query_fallback_criteria_changed')
    policy = latest(db, run.session_id, use.policy_id)
    if (policy is None or policy.revision != use.policy_revision or policy.state != 'enabled'
            or policy.mode not in ALLOW_MODES or utc(policy.expires_at) <= utcnow()
            or utcnow() < date(policy.payload['approved_at']) or not matches(policy, run, use.query_kind)):
        fail('query_fallback_policy_changed')
    mode, chosen = effective_decision(db, registry, run, use.query_kind, 'programmatic')
    if mode != 'allow' or chosen is None or chosen.policy_id != policy.policy_id or chosen.revision != policy.revision:
        fail('query_fallback_policy_changed')
    scope_metadata(db, registry, policy.payload['scope'])
    if use.actor_session_id != run.session_id or use.query_id != run.id:
        fail('query_fallback_use_owner_mismatch', 403)


def authorized_result(db, registry, run, use, result):
    revalidate_use(db, registry, run, use)
    result['fallback_authorization'] = {'type': 'policy_once', 'use': deepcopy(use.payload)}
    db.commit()
    return result


def register_query_fallback_routes(app):
    @app.post('/v1/query-fallback-policies:preview')
    def preview(payload: PolicyPreviewRequest, request: Request):
        with app.state.database.sessions() as db:
            return preview_policy(db, app.state.registry, payload, request.state.session_id)

    @app.post('/v1/query-fallback-policies:apply')
    def apply(payload: PolicyApplyRequest, request: Request,
              key: str = Header(alias='Idempotency-Key', max_length=64)):
        with app.state.database.sessions() as db:
            return apply_policy(db, app.state.registry, payload, request.state.session_id, key)

    @app.get('/v1/query-fallback-policies')
    def policies(request: Request, limit: int = Query(16, ge=1, le=16), offset: int = Query(0, ge=0, le=10000)):
        with app.state.database.sessions() as db:
            current_owner(db, request.state.session_id)
            rows = db.scalars(latest_statement(request.state.session_id).order_by(
                QueryFallbackPolicyRevision.policy_id).offset(offset).limit(limit)).all()
            return {'schema': 'query-fallback-policy-list@1', 'scope': 'current_session',
                    'audience': 'programmatic', 'items': [view(row) for row in rows]}

    @app.post('/v1/query-fallback-policies/{policy_id}:pause')
    def pause(policy_id: str, payload: PolicyChangeRequest, request: Request,
              key: str = Header(alias='Idempotency-Key', max_length=64)):
        with app.state.database.sessions() as db:
            return change_policy(db, payload, request.state.session_id, policy_id, key, 'paused')

    @app.post('/v1/query-fallback-policies/{policy_id}:revoke')
    def revoke(policy_id: str, payload: PolicyChangeRequest, request: Request,
               key: str = Header(alias='Idempotency-Key', max_length=64)):
        with app.state.database.sessions() as db:
            return change_policy(db, payload, request.state.session_id, policy_id, key, 'revoked')
