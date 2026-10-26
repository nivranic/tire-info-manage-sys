"""Complete active inventory and bounded keyset issuance history, without writes."""
import base64
from datetime import datetime, timedelta
import hashlib
import hmac
import re

from fastapi import Depends, FastAPI, Request
from sqlalchemy import and_, or_, select, true
from sqlalchemy.orm import aliased

from .db import utc, utcnow
from .domain import stable_json
from .external_api import _account, _valid_key, fail
from .external_api_models import ApiKey, ApiKeyRevocation
from .service import timestamp
from .webhook_delivery import valid_seal
from .webhook_policy import strict_json

ROUTE = '/v1/api-key-history'
NAMESPACE = b'tire-api-key-history@1\x00'
OWNER_NAMESPACE = b'tire-api-key-history-owner@1\x00'
CURSOR_FIELDS = {'schema', 'route', 'limit', 'owner', 'anchor', 'upper', 'after', 'window_started_at', 'expires'}


def _invalid_cursor():
    fail('api_key_history_cursor_invalid', 422)


def _record(key, revocation):
    """Project only the two records read together; never fetch current revocation."""
    if not _valid_key(key) or (revocation is not None and (
            revocation.key_id != key.id or not valid_seal(revocation))):
        fail('external_key_history_invalid')
    return {'schema': 'api-key@1', 'id': key.id, 'name': key.name, 'scopes': list(key.scopes),
        'created_at': timestamp(key.created_at), 'expires_at': timestamp(key.expires_at),
        'revoked_at': timestamp(revocation.revoked_at) if revocation is not None else None}


def _parameters(request, history):
    allowed = {'mode', 'limit', 'cursor'} if history else {'mode'}
    pairs = request.query_params.multi_items()
    if (any(key not in allowed for key, _value in pairs) or len({key for key, _value in pairs}) != len(pairs)
            or dict(pairs).get('mode') != 'history'):
        fail('api_key_inventory_query_invalid', 422)
    params = dict(pairs)
    if not history:
        return params
    raw_limit = params.get('limit', '20')
    if len(raw_limit) > 3 or re.fullmatch(r'[0-9]+', raw_limit) is None or not 1 <= int(raw_limit) <= 100:
        fail('api_key_inventory_query_invalid', 422)
    cursor = params.get('cursor')
    if cursor is not None and (not cursor or len(cursor) > 2048):
        _invalid_cursor()
    return int(raw_limit), cursor


def _pair(key):
    return [timestamp(key.created_at), key.id]


def _parse_time(value):
    try:
        if type(value) is not str or len(value) > 40:
            raise ValueError()
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0) or timestamp(parsed) != value:
            raise ValueError()
        return parsed
    except (ValueError, TypeError, OverflowError):
        _invalid_cursor()


def _parse_pair(value):
    if (type(value) is not list or len(value) != 2 or type(value[1]) is not str
            or re.fullmatch(r'[a-f0-9]{32}', value[1]) is None):
        _invalid_cursor()
    return _parse_time(value[0]), value[1]


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _owner(anchor, owner):
    return hmac.new(bytes.fromhex(anchor.cursor_secret), OWNER_NAMESPACE + owner.encode('utf-8'), hashlib.sha256).hexdigest()


def _encode(anchor, payload):
    raw = stable_json(payload).encode('utf-8')
    signature = hmac.new(bytes.fromhex(anchor.cursor_secret), NAMESPACE + raw, hashlib.sha256).digest()
    return _b64(raw) + '.' + _b64(signature)


def _unpack(value, limit):
    try:
        if len(value) > 2048 or re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}', value) is None:
            raise ValueError()
        encoded, signature = value.split('.')
        raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        if _b64(raw) != encoded:
            raise ValueError()
        payload = strict_json(raw.decode('utf-8'))
        if (type(payload) is not dict or set(payload) != CURSOR_FIELDS
                or payload['schema'] != 'api-key-history-cursor@1' or payload['route'] != ROUTE
                or type(payload['limit']) is not int or payload['limit'] != limit
                or type(payload['anchor']) is not str or re.fullmatch(r'[a-f0-9]{32}', payload['anchor']) is None
                or type(payload['owner']) is not str or re.fullmatch(r'[a-f0-9]{64}', payload['owner']) is None
                or type(payload['expires']) is not int or stable_json(payload).encode('utf-8') != raw):
            raise ValueError()
        upper, after = _parse_pair(payload['upper']), _parse_pair(payload['after'])
        window = _parse_time(payload['window_started_at'])
        if (payload['anchor'] != upper[1] or after > upper
                or payload['expires'] != int(window.timestamp()) + 900):
            raise ValueError()
        return payload, raw, signature, upper, after
    except (ValueError, TypeError, UnicodeError, KeyError, OverflowError):
        _invalid_cursor()


def _verify(anchor, owner, payload, raw, signature, now):
    if (not _valid_key(anchor) or anchor.owner_user_id != owner or anchor.id != payload['anchor']
            or _pair(anchor) != payload['upper'] or payload['owner'] != _owner(anchor, owner)):
        _invalid_cursor()
    expected = _b64(hmac.new(bytes.fromhex(anchor.cursor_secret), NAMESPACE + raw, hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        _invalid_cursor()
    if _parse_time(payload['window_started_at']) > utc(now):
        _invalid_cursor()
    if int(utc(now).timestamp()) >= payload['expires']:
        fail('api_key_history_cursor_expired', 409)


def register_api_key_inventory_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    def account(request: Request, db=Depends(get_db)):
        owner = _account(db, request.state.session_id)
        values = request.headers.getlist('x-tire-expected-account')
        if (len(values) != 1 or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', values[0]) is None):
            fail('api_key_expected_account_invalid', 422)
        if values[0] != owner:
            fail('api_key_owner_changed')
        return owner

    @app.get('/v1/api-keys/active', dependencies=[Depends(account)])
    def active(request: Request, owner=Depends(account), db=Depends(get_db)):
        _parameters(request, False)
        now = utcnow()
        rows = db.execute(select(ApiKey, ApiKeyRevocation).outerjoin(ApiKeyRevocation,
            ApiKeyRevocation.key_id == ApiKey.id).where(ApiKey.owner_user_id == owner,
                ApiKey.expires_at > now, ApiKeyRevocation.key_id.is_(None))
            .order_by(ApiKey.created_at.desc(), ApiKey.id.desc()).limit(17)).all()
        if len(rows) > 16:
            fail('api_key_active_limit_invalid')
        return {'schema': 'active-api-keys@1', 'items': [_record(key, revoked) for key, revoked in rows],
            'read_at': timestamp(now)}

    @app.get(ROUTE, dependencies=[Depends(account)])
    def history(request: Request, owner=Depends(account), db=Depends(get_db)):
        limit, cursor = _parameters(request, True)
        now = utcnow()
        if cursor:
            payload, raw, signature, upper, after = _unpack(cursor, limit)
            # One SQL reads the immutable anchor plus a bounded page and all of
            # its revocations. The page projection never re-reads mutable time.
            page = select(ApiKey.id.label('page_id')).where(ApiKey.owner_user_id == owner,
                or_(ApiKey.created_at < upper[0], and_(ApiKey.created_at == upper[0], ApiKey.id <= upper[1])),
                or_(ApiKey.created_at < after[0], and_(ApiKey.created_at == after[0], ApiKey.id < after[1])))
            page = page.order_by(ApiKey.created_at.desc(), ApiKey.id.desc()).limit(limit + 1).subquery()
            anchor_model = aliased(ApiKey)
            rows = db.execute(select(anchor_model, ApiKey, ApiKeyRevocation).select_from(anchor_model)
                .outerjoin(page, true()).outerjoin(ApiKey, ApiKey.id == page.c.page_id)
                .outerjoin(ApiKeyRevocation, ApiKeyRevocation.key_id == ApiKey.id)
                .where(anchor_model.id == payload['anchor'], anchor_model.owner_user_id == owner)
                .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())).all()
            if not rows:
                _invalid_cursor()
            anchor = rows[0][0]
            _verify(anchor, owner, payload, raw, signature, now)
            entries = [(key, revocation) for _anchor, key, revocation in rows if key is not None]
        else:
            entries = db.execute(select(ApiKey, ApiKeyRevocation).outerjoin(ApiKeyRevocation,
                ApiKeyRevocation.key_id == ApiKey.id).where(ApiKey.owner_user_id == owner)
                .order_by(ApiKey.created_at.desc(), ApiKey.id.desc()).limit(limit + 1)).all()
            if not entries:
                return {'schema': 'api-key-history@1', 'items': [], 'limit': limit, 'next_cursor': None,
                    'window_started_at': timestamp(now), 'read_at': timestamp(now)}
            anchor = entries[0][0]
            if not _valid_key(anchor):
                fail('external_key_history_invalid')
            payload = {'schema': 'api-key-history-cursor@1', 'route': ROUTE, 'limit': limit,
                'owner': _owner(anchor, owner), 'anchor': anchor.id, 'upper': _pair(anchor),
                'after': None, 'window_started_at': timestamp(now), 'expires': int(utc(now).timestamp()) + 900}
        page = entries[:limit]
        items = [_record(key, revocation) for key, revocation in page]
        next_cursor = None
        if len(entries) > limit:
            payload['after'] = _pair(page[-1][0])
            next_cursor = _encode(anchor, payload)
        return {'schema': 'api-key-history@1', 'items': items, 'limit': limit, 'next_cursor': next_cursor,
            'window_started_at': payload['window_started_at'], 'read_at': timestamp(now)}
