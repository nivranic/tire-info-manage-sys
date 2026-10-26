"""Bounded, actor-private projections of current interests over local history."""
import base64
from copy import deepcopy
import hashlib
import hmac
import json
import secrets
import time
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import ConfigDict, Field, StrictInt
from sqlalchemy import func, select

from .auth import session_scope
from .db import UserSession
from .domain import StrictModel, digest, stable_json
from .interest_events import InterestEvidenceError, historical_candidate_query, reconstruct_candidate
from .interest_matching import POLICY_VERSION as MATCH_POLICY, match_event
from .interest_models import Interest, InterestRevision
from .service import timestamp

POLICY_VERSION = 'current-interests-history@1'
MAX_INTERESTS = 100
MAX_CANDIDATES = 50_000
CURSOR_TTL_SECONDS = 3600
_CURSOR_KEY = secrets.token_bytes(32)
Domain = Literal['tire', 'test_event', 'vehicle', 'fitment', 'tire_curation', 'tire_lifecycle',
                 'tire_identity', 'tire_catalog', 'tire_curation_validity']


class PersonalFeedRequest(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    domain: Domain | None = None
    limit: StrictInt = Field(default=20, ge=1, le=50)
    cursor: str | None = Field(default=None, strict=True, min_length=1, max_length=4096)


def fail(code, message, status=409):
    raise HTTPException(status, {'code': code, 'message': message}, headers={'Cache-Control': 'no-store'})


def actor_binding(db, session_id):
    user = db.scalar(select(UserSession.user_id).where(UserSession.id == session_id))
    value = ['user', user] if user else ['anonymous', session_id]
    return hmac.new(_CURSOR_KEY, stable_json(value).encode(), hashlib.sha256).hexdigest()


def active_interests(db, session_id):
    heads = select(InterestRevision.interest_id, func.max(InterestRevision.revision).label('revision')).group_by(
        InterestRevision.interest_id).subquery()
    rows = db.execute(select(Interest, InterestRevision).join(InterestRevision,
        InterestRevision.interest_id == Interest.id).join(heads,
        (heads.c.interest_id == Interest.id) & (heads.c.revision == InterestRevision.revision)).where(
        Interest.session_id.in_(session_scope(db, session_id)), InterestRevision.enabled.is_(True),
        InterestRevision.archived.is_(False)).order_by(Interest.id).limit(MAX_INTERESTS + 1)).all()
    if len(rows) > MAX_INTERESTS:
        fail('personal_feed_capacity_exceeded', '启用的本人兴趣超过100条，请缩小范围后重试。')
    return [{'id': item.id, 'revision': row.revision, 'fingerprint': row.fingerprint, 'name': row.name,
             'conditions': deepcopy(row.conditions), 'metric_keys': deepcopy(row.metric_keys),
             'changed_fields': deepcopy(row.changed_fields)} for item, row in rows]


def candidate_metadata(db, domain):
    statement = historical_candidate_query()
    if domain is not None:
        statement = statement.where(statement.selected_columns.domain == domain)
    rows = db.execute(statement.limit(MAX_CANDIDATES + 1)).all()
    if len(rows) > MAX_CANDIDATES:
        fail('personal_feed_capacity_exceeded', '本地历史超过50000条候选，请选择单一领域缩小范围。')
    return [{'domain': row.domain, 'origin_id': row.origin_id, 'at': timestamp(row.at)} for row in rows]


def encode_cursor(payload):
    encoded = base64.urlsafe_b64encode(stable_json(payload).encode()).decode().rstrip('=')
    signature = hmac.new(_CURSOR_KEY, encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + '.' + signature


def decode_cursor(value, actor, payload):
    try:
        encoded, signature = value.split('.')
        expected = hmac.new(_CURSOR_KEY, encoded.encode('ascii'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError('signature')
        data = json.loads(base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True))
        if (data['actor'] != actor or data['policy'] != [POLICY_VERSION, MATCH_POLICY]
                or data['domain'] != payload.domain or data['limit'] != payload.limit
                or type(data['expires']) is not int or not isinstance(data['last'], dict)
                or not isinstance(data['binding'], dict)):
            raise ValueError('binding')
    except (ValueError, TypeError, KeyError, UnicodeError):
        fail('personal_feed_cursor_invalid', '历史信息流游标无效，请重新加载。', 400)
    if data['expires'] <= int(time.time()):
        fail('personal_feed_binding_changed', '历史信息流游标已过期，请重新加载。')
    return data


def personal_feed(db, session_id, payload):
    actor = actor_binding(db, session_id)
    cursor = decode_cursor(payload.cursor, actor, payload) if payload.cursor else None
    interests = active_interests(db, session_id)
    origins = candidate_metadata(db, payload.domain) if interests else []
    binding = {'interests_fingerprint': digest(interests), 'candidates_fingerprint': digest(origins)}
    if cursor and cursor['binding'] != binding:
        fail('personal_feed_binding_changed', '本人兴趣或本地历史已变化，请重新加载。')
    remaining = origins
    if cursor:
        try:
            index = origins.index(cursor['last'])
        except ValueError:
            fail('personal_feed_binding_changed', '历史扫描位置已变化，请重新加载。')
        # The frozen member list is already in the full SQL keyset order.
        remaining = origins[index + 1:]
    scanned = remaining[:payload.limit]
    items = []
    for origin in scanned:
        try:
            event = reconstruct_candidate(db, origin['domain'], origin['origin_id'], verify_stored=True)
        except (InterestEvidenceError, ValueError, TypeError, KeyError, AttributeError):
            fail('personal_feed_evidence_unavailable', '本地历史证据无法校验，本页未生成，请核对原始记录。')
        matches = []
        for interest in interests:
            result = match_event(event, interest)
            if result['state'] != 'no_match':
                matches.append({'interest_id': interest['id'], 'interest_revision': interest['revision'],
                    'interest_fingerprint': interest['fingerprint'], 'interest_name': interest['name'], 'match': result})
        if matches:
            state = 'matched' if any(row['match']['state'] == 'matched' for row in matches) else 'indeterminate'
            items.append({'state': state, 'event': event, 'matches': matches})
    # End the read transaction so the second read observes concurrent appends on
    # SQLite and PostgreSQL too. This is optimistic validation, not a durable
    # database snapshot; no audit, event, notification, or commit is performed.
    db.rollback()
    after_interests = active_interests(db, session_id)
    after_origins = candidate_metadata(db, payload.domain) if after_interests else []
    if (actor_binding(db, session_id) != actor or digest(after_interests) != binding['interests_fingerprint']
            or digest(after_origins) != binding['candidates_fingerprint']):
        fail('personal_feed_binding_changed', '读取期间本人兴趣或本地历史已变化，请重新加载。')
    more = len(remaining) > len(scanned)
    next_cursor = encode_cursor({'actor': actor, 'policy': [POLICY_VERSION, MATCH_POLICY],
        'domain': payload.domain, 'limit': payload.limit, 'binding': binding, 'last': scanned[-1],
        'expires': cursor['expires'] if cursor else int(time.time()) + CURSOR_TTL_SECONDS}) if more else None
    return {'schema': 'personal-feed@1', 'policy_version': POLICY_VERSION, 'data_state': 'local_snapshot',
        'scope': 'actor', 'feed_scope': 'current_interests_history', 'domain': payload.domain, 'limit': payload.limit,
        'active_interest_count': len(interests), 'items': items, 'scanned_count': len(scanned),
        'matched_count': sum(row['state'] == 'matched' for row in items),
        'indeterminate_count': sum(row['state'] == 'indeterminate' for row in items),
        'has_more': more, 'next_cursor': next_cursor, 'binding': binding,
        'notices': ['按本人当前启用兴趣回看本地九域历史；不是实时监控，也不代表外网完整历史。',
            '历史原证据和既有通知不改写、不补发；未确定的匹配不等于已命中。',
            '分页绑定当前兴趣与候选成员集合，变化须重新加载；响应到达后可能已有新记录。']}


def register_personal_feed_routes(app):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/personal-feed/preview')
    def preview(payload: PersonalFeedRequest, request: Request, response: Response,
                mode: Literal['history'] = Query(...), db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        with db.no_autoflush:
            return personal_feed(db, request.state.session_id, payload)
