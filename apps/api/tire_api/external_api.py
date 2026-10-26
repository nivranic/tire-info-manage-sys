"""Local account management and a separate Bearer-only, reference-only API."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, StrictInt, field_validator
from sqlalchemy import and_, func, or_, select

from .db import User, UserSession, uid, utc, utcnow
from .domain import StrictModel, digest, stable_json
from .external_api_models import ApiKey, ApiKeyMinute, ApiKeyOperation, ApiKeyRevocation
from .service import QueryService, timestamp
from .webhook_delivery import HistoryInvalid, seal, valid_seal
from .webhook_models import WebhookEnvelope
from .webhook_policy import CHANNELS, strict_json
from .webhooks import delivery_view

SCOPES = ('sources:read', 'webhooks:read', 'facts:read')
SAFE_HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
TOKEN_PATTERN = re.compile(r'ti_([a-f0-9]{32})\.([a-f0-9]{64})')
SOURCE_ID = re.compile(r'[A-Za-z0-9_-]{1,80}')
CURSOR_KEYS = {'schema', 'key_id', 'owner', 'route', 'limit', 'filters', 'expires', 'context', 'after'}


def fail(code, status=409, headers=None):
    raise HTTPException(status, {'code': code}, headers={**SAFE_HEADERS, **(headers or {})})


def unauthorized():
    fail('external_unauthorized', 401, {'WWW-Authenticate': 'Bearer'})


def _valid_key(row):
    return (valid_seal(row) and re.fullmatch(r'[a-f0-9]{32}', row.id) is not None
        and type(row.scopes) is list and bool(row.scopes) and row.scopes == sorted(set(row.scopes))
        and all(scope in SCOPES for scope in row.scopes)
        and re.fullmatch(r'[a-f0-9]{64}', row.bearer_sha256) is not None
        and re.fullmatch(r'[a-f0-9]{64}', row.cursor_secret) is not None)


def _revocation(db, key_id):
    row = db.get(ApiKeyRevocation, key_id)
    if row and not valid_seal(row):
        fail('external_key_history_invalid')
    return row


def key_view(db, row):
    if not _valid_key(row):
        fail('external_key_history_invalid')
    revocation = _revocation(db, row.id)
    return {'schema': 'api-key@1', 'id': row.id, 'name': row.name, 'scopes': deepcopy(row.scopes),
        'created_at': timestamp(row.created_at), 'expires_at': timestamp(row.expires_at),
        'revoked_at': timestamp(revocation.revoked_at) if revocation else None}


def revoke_account_keys(db, owner_user_id, reason='password_reset'):
    """Caller owns the ingestion lock and the password/account transaction."""
    now = utcnow()
    count = 0
    for row in db.scalars(select(ApiKey).where(ApiKey.owner_user_id == owner_user_id)).all():
        if _revocation(db, row.id) is None:
            db.add(seal(ApiKeyRevocation(key_id=row.id, revoked_at=now, reason=reason)))
            count += 1
    db.flush()
    return count


def _account(db, session_id):
    session = db.get(UserSession, session_id, populate_existing=True)
    if not session or not session.user_id or utc(session.expires_at) <= utcnow():
        fail('api_key_login_required', 401)
    user = db.get(User, session.user_id, populate_existing=True)
    if user is None:
        fail('api_key_login_required', 401)
    return user.id


def authenticate_external(database, request):
    """Authenticate and commit one rate reservation before any external routing."""
    headers = request.headers.getlist('authorization')
    if len(headers) != 1 or len(headers[0]) != 107 or not headers[0].startswith('Bearer '):
        unauthorized()
    token = headers[0][7:]
    match = TOKEN_PATTERN.fullmatch(token)
    if match is None:
        unauthorized()
    hashed = hashlib.sha256(token.encode('ascii')).hexdigest()
    with database.sessions() as db:
        row = db.get(ApiKey, match.group(1))
        try:
            valid = (row is not None and _valid_key(row) and hmac.compare_digest(row.bearer_sha256, hashed)
                and utc(row.expires_at) > utcnow() and _revocation(db, row.id) is None
                and db.get(User, row.owner_user_id) is not None)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            unauthorized()
        QueryService(db, None).lock_ingestion()
        db.expire_all()
        row = db.get(ApiKey, match.group(1))
        try:
            valid = (row is not None and _valid_key(row) and hmac.compare_digest(row.bearer_sha256, hashed)
                and utc(row.expires_at) > utcnow() and _revocation(db, row.id) is None
                and db.get(User, row.owner_user_id) is not None)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            unauthorized()
        now = utcnow()
        epoch = int(utc(now).timestamp())
        minute = epoch // 60
        bucket = db.get(ApiKeyMinute, row.id)
        if bucket is None:
            bucket = ApiKeyMinute(key_id=row.id, minute=minute, requests=0)
            db.add(bucket)
        elif bucket.minute != minute:
            bucket.minute, bucket.requests = minute, 0
        if type(bucket.requests) is not int or not 0 <= bucket.requests <= 60:
            fail('external_rate_state_invalid')
        if bucket.requests >= 60:
            fail('external_rate_limited', 429, {'Retry-After': str(60 - epoch % 60)})
        bucket.requests += 1
        principal = {'id': row.id, 'owner': row.owner_user_id, 'scopes': tuple(row.scopes),
            'cursor_secret': row.cursor_secret}
        db.commit()
    request.state.external_principal = principal


def external_namespace(path):
    return path == '/external' or path.startswith('/external/')


def external_response(code, status, headers=None):
    return JSONResponse(status_code=status, content={'detail': {'code': code}},
        headers={**SAFE_HEADERS, **(headers or {})})


async def external_boundary(request, call_next, database, origins=()):
    path = request.url.path
    if external_namespace(path):
        origin = request.headers.get('origin')
        if ((request.client and request.client.host not in {'127.0.0.1', '::1', 'testclient'})
                or (origin and origin not in origins and origin != str(request.base_url).rstrip('/'))
                or request.headers.get('sec-fetch-site') == 'cross-site'):
            return external_response('external_local_boundary_required', 403)
        try:
            authenticate_external(database, request)
        except HTTPException as error:
            return JSONResponse(status_code=error.status_code, content={'detail': error.detail}, headers=error.headers)
        if request.method != 'GET':
            return external_response('external_method_not_allowed', 405, {'Allow': 'GET'})
        if path not in ('/external/v1/sources', '/external/v1/webhook-deliveries', '/external/v1/tire-facts') and not re.fullmatch(
                r'/external/v1/webhook-deliveries/[A-Za-z0-9_-]{1,64}', path) and not re.fullmatch(
                r'/external/v1/tire-facts/[^/]+', path):
            return external_response('external_not_found', 404)
    elif request.headers.getlist('authorization'):
        return external_response('external_bearer_route_required', 401, {'WWW-Authenticate': 'Bearer'})
    response = await call_next(request)
    if external_namespace(path) or path.startswith('/v1/api-key'):
        response.headers.update(SAFE_HEADERS)
    return response


def _scope(request, required):
    principal = request.state.external_principal
    if required not in principal['scopes']:
        fail('external_scope_required', 403)
    return principal


def _queries(request, allowed):
    pairs = request.query_params.multi_items()
    if any(key not in allowed for key, _value in pairs) or len({key for key, _value in pairs}) != len(pairs):
        fail('external_query_invalid', 422)
    return dict(pairs)


def _paging(request, allowed=()):
    params = _queries(request, {'limit', 'cursor', *allowed})
    raw_limit = params.get('limit', '20')
    if len(raw_limit) > 3 or re.fullmatch(r'[0-9]+', raw_limit) is None or not 1 <= int(raw_limit) <= 100:
        fail('external_query_invalid', 422)
    raw_cursor = params.get('cursor')
    if raw_cursor is not None and (not raw_cursor or len(raw_cursor) > 2048):
        fail('external_cursor_invalid', 422)
    return params, int(raw_limit), raw_cursor


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def encode_cursor(principal, payload):
    raw = stable_json(payload).encode('utf-8')
    return _b64(raw) + '.' + _b64(hmac.new(bytes.fromhex(principal['cursor_secret']), raw, hashlib.sha256).digest())


def _owner_binding(principal):
    return hmac.new(bytes.fromhex(principal['cursor_secret']),
        ('owner.' + principal['owner']).encode('utf-8'), hashlib.sha256).hexdigest()


def decode_cursor(principal, value, route, limit, filters):
    try:
        if len(value) > 2048 or re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}', value) is None:
            raise ValueError()
        body, signature = value.split('.')
        raw = base64.urlsafe_b64decode(body + '=' * (-len(body) % 4))
        expected = _b64(hmac.new(bytes.fromhex(principal['cursor_secret']), raw, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        payload = strict_json(raw.decode('utf-8'))
        if (type(payload) is not dict or set(payload) != CURSOR_KEYS or payload['schema'] != 'external-cursor@1'
                or payload['key_id'] != principal['id'] or payload['owner'] != _owner_binding(principal)
                or payload['route'] != route or payload['limit'] != limit or payload['filters'] != filters
                or type(payload['expires']) is not int or payload['expires'] <= int(utc(utcnow()).timestamp())
                or payload['expires'] > int(utc(utcnow()).timestamp()) + 900):
            raise ValueError()
        return payload
    except (ValueError, TypeError, UnicodeError, KeyError, OverflowError):
        fail('external_cursor_invalid', 422)


def _cursor(principal, route, limit, filters, context, after):
    return {'schema': 'external-cursor@1', 'key_id': principal['id'], 'owner': _owner_binding(principal),
        'route': route, 'limit': limit, 'filters': filters, 'context': context, 'after': after,
        'expires': int(utc(utcnow()).timestamp()) + 900}


def _key_idempotency(value):
    try:
        if type(value) is not str or str(UUID(value)) != value.lower():
            raise ValueError()
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        fail('api_key_idempotency_required', 422)


def _operation_view(db, row, replayed, token=None):
    if not valid_seal(row):
        fail('external_key_history_invalid')
    key = db.get(ApiKey, row.key_id)
    if (not key or not _valid_key(key) or key.owner_user_id != row.owner_user_id
            or row.key_snapshot.get('id') != key.id or row.key_snapshot.get('name') != key.name
            or row.key_snapshot.get('scopes') != key.scopes
            or row.key_snapshot.get('created_at') != timestamp(key.created_at)
            or row.key_snapshot.get('expires_at') != timestamp(key.expires_at)):
        fail('external_key_history_invalid')
    return {'schema': 'api-key-operation@1', 'idempotency_key': row.idempotency_key,
        'action': row.action, 'key': deepcopy(row.key_snapshot), 'token': None if replayed else token, 'replayed': replayed}


class Acknowledged(StrictModel):
    acknowledged: Literal[True]

    @field_validator('acknowledged', mode='before')
    @classmethod
    def strict_ack(cls, value):
        if value is not True:
            raise ValueError('api_key_acknowledgement_required')
        return value


class KeyCreate(Acknowledged):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[Literal['sources:read', 'webhooks:read', 'facts:read']] = Field(min_length=1, max_length=3)
    expires_in_days: StrictInt = Field(ge=1, le=90)

    @field_validator('name')
    @classmethod
    def safe_name(cls, value):
        value = value.strip()
        if not value or not value.isprintable():
            raise ValueError('api_key_name_invalid')
        return value

    @field_validator('scopes')
    @classmethod
    def scope_set(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('api_key_scopes_duplicate')
        return sorted(value)


def register_external_api_routes(app: FastAPI, *, fact_reader=None):
    from .api_key_inventory import register_api_key_inventory_routes
    register_api_key_inventory_routes(app)
    # Older direct registration callers need no database or registry state.
    # A complete app injects its one reader; a missing reader fails closed.
    from .external_fact_http import register_external_fact_routes
    register_external_fact_routes(app, fact_reader)

    def get_db():
        with app.state.database.sessions() as db:
            yield db

    def account(request: Request, db=Depends(get_db)):
        return _account(db, request.state.session_id)

    def mutation(request: Request, db=Depends(get_db)):
        _account(db, request.state.session_id)
        QueryService(db, None).lock_ingestion()
        return _account(db, request.state.session_id)

    def owned(db, owner, key_id):
        row = db.get(ApiKey, key_id)
        if row is None or row.owner_user_id != owner:
            fail('api_key_not_found', 404)
        return row

    def own_mutation(key_id: str, owner=Depends(mutation), db=Depends(get_db)):
        return owned(db, owner, key_id)

    def begin(db, request, owner, header, action, payload):
        key = _key_idempotency(header)
        request_hash = digest({'method': request.method, 'path': request.url.path, 'action': action, 'body': payload})
        old = db.scalar(select(ApiKeyOperation).where(ApiKeyOperation.owner_user_id == owner,
            ApiKeyOperation.idempotency_key == key))
        if old:
            if old.request_hash != request_hash or old.method != request.method or old.path != request.url.path or old.action != action:
                fail('api_key_idempotency_conflict')
            return key, request_hash, _operation_view(db, old, True)
        return key, request_hash, None

    def finish(db, request, owner, idempotency_key, action, request_hash, key, token=None):
        operation = seal(ApiKeyOperation(id=uid(), owner_user_id=owner, idempotency_key=idempotency_key,
            action=action, method=request.method, path=request.url.path, request_hash=request_hash,
            key_id=key.id, key_snapshot=key_view(db, key), created_at=utcnow()))
        db.add(operation)
        db.flush()
        response = _operation_view(db, operation, False, token)
        db.commit()
        return response

    @app.get('/v1/api-keys', dependencies=[Depends(account)])
    def keys(mode: Literal['history'], owner=Depends(account), db=Depends(get_db)):
        rows = db.scalars(select(ApiKey).where(ApiKey.owner_user_id == owner)
            .order_by(ApiKey.created_at.desc(), ApiKey.id.desc()).limit(100)).all()
        return {'schema': 'api-keys@1', 'items': [key_view(db, row) for row in rows]}

    @app.get('/v1/api-key-operations', dependencies=[Depends(account)])
    def operations(key: str, mode: Literal['history'], owner=Depends(account), db=Depends(get_db)):
        row = db.scalar(select(ApiKeyOperation).where(ApiKeyOperation.owner_user_id == owner,
            ApiKeyOperation.idempotency_key == _key_idempotency(key)))
        if row is None:
            fail('api_key_operation_not_found', 404)
        return _operation_view(db, row, True)

    @app.post('/v1/api-keys', status_code=201, dependencies=[Depends(mutation)])
    def create(payload: KeyCreate, request: Request, owner=Depends(mutation),
            idempotency_key: str | None = Header(default=None), db=Depends(get_db)):
        operation_key, request_hash, replay = begin(db, request, owner, idempotency_key, 'create', payload.model_dump())
        if replay:
            return replay
        active = db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.owner_user_id == owner,
            ApiKey.expires_at > utcnow(), ~select(ApiKeyRevocation.key_id).where(ApiKeyRevocation.key_id == ApiKey.id).exists()))
        if active >= 16:
            fail('api_key_limit')
        key_id = secrets.token_hex(16)
        token = 'ti_' + key_id + '.' + secrets.token_hex(32)
        now = utcnow()
        key = seal(ApiKey(id=key_id, owner_user_id=owner, name=payload.name, scopes=payload.scopes,
            bearer_sha256=hashlib.sha256(token.encode('ascii')).hexdigest(), cursor_secret=secrets.token_hex(32),
            created_at=now, expires_at=now + timedelta(days=payload.expires_in_days)))
        db.add(key)
        db.flush()
        return finish(db, request, owner, operation_key, 'create', request_hash, key, token)

    @app.post('/v1/api-keys/{key_id}/revoke', dependencies=[Depends(own_mutation)])
    def revoke(key_id: str, payload: Acknowledged, request: Request, owner=Depends(mutation),
            idempotency_key: str | None = Header(default=None), db=Depends(get_db)):
        operation_key, request_hash, replay = begin(db, request, owner, idempotency_key, 'revoke', payload.model_dump())
        if replay:
            return replay
        row = owned(db, owner, key_id)
        if _revocation(db, row.id) is None:
            db.add(seal(ApiKeyRevocation(key_id=row.id, revoked_at=utcnow(), reason='owner_revoke')))
            db.flush()
        return finish(db, request, owner, operation_key, 'revoke', request_hash, row)

    @app.get('/external/v1/sources')
    def sources(request: Request):
        principal = _scope(request, 'sources:read')
        _params, limit, raw_cursor = _paging(request)
        values = []
        sources = app.state.registry.sources()
        if type(sources) is not list:
            fail('external_catalog_invalid')
        for source in sources:
            if type(source) is not dict or type(source.get('id')) is not str or SOURCE_ID.fullmatch(source['id']) is None:
                fail('external_catalog_invalid')
            projected = {}
            for name in ('id', 'name', 'source_class', 'region', 'parser_version', 'status'):
                value = source.get(name)
                if value is not None and (type(value) is not str or len(value) > 500
                        or not all(character.isprintable() for character in value)):
                    fail('external_catalog_invalid')
                projected[name] = value
            values.append(projected)
        values.sort(key=lambda value: value['id'])
        if len({value['id'] for value in values}) != len(values):
            fail('external_catalog_invalid')
        summary = digest(values)
        payload = decode_cursor(principal, raw_cursor, request.url.path, limit, {}) if raw_cursor else _cursor(
            principal, request.url.path, limit, {}, summary, None)
        if payload['context'] != summary:
            fail('external_catalog_changed')
        if payload['after'] is not None and (type(payload['after']) is not str or SOURCE_ID.fullmatch(payload['after']) is None):
            fail('external_cursor_invalid', 422)
        remaining = [value for value in values if payload['after'] is None or value['id'] > payload['after']]
        page = remaining[:limit]
        next_cursor = None
        if len(remaining) > limit:
            payload['after'] = page[-1]['id']
            next_cursor = encode_cursor(principal, payload)
        return {'schema': 'external-sources@1', 'items': page, 'next_cursor': next_cursor,
            'limit': limit, 'data_state': 'local_snapshot'}

    @app.get('/external/v1/webhook-deliveries')
    def deliveries(request: Request, db=Depends(get_db)):
        principal = _scope(request, 'webhooks:read')
        params, limit, raw_cursor = _paging(request, ('channel', 'webhook_id'))
        filters = {key: params[key] for key in ('channel', 'webhook_id') if key in params}
        if ('channel' in filters and filters['channel'] not in CHANNELS) or ('webhook_id' in filters
                and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', filters['webhook_id']) is None):
            fail('external_query_invalid', 422)
        query = select(WebhookEnvelope).where(WebhookEnvelope.owner_user_id == principal['owner'])
        if 'channel' in filters:
            query = query.where(WebhookEnvelope.channel == filters['channel'])
        if 'webhook_id' in filters:
            query = query.where(WebhookEnvelope.subscription_id == filters['webhook_id'])
        def pair(row):
            return [timestamp(row.created_at), row.id]
        if raw_cursor:
            payload = decode_cursor(principal, raw_cursor, request.url.path, limit, filters)
        else:
            upper = db.scalar(query.order_by(WebhookEnvelope.created_at.desc(), WebhookEnvelope.id.desc()).limit(1))
            payload = _cursor(principal, request.url.path, limit, filters, pair(upper) if upper else None, None)
        def parse_pair(value):
            if (type(value) is not list or len(value) != 2 or type(value[0]) is not str
                    or type(value[1]) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value[1]) is None):
                fail('external_cursor_invalid', 422)
            try:
                at = datetime.fromisoformat(value[0])
                if at.tzinfo is None or at.utcoffset() != timedelta(0):
                    raise ValueError()
            except (ValueError, TypeError):
                fail('external_cursor_invalid', 422)
            return at, value[1]
        if payload['context'] is None:
            return {'schema': 'external-webhook-deliveries@1', 'items': [], 'next_cursor': None,
                'limit': limit, 'data_state': 'local_snapshot'}
        upper_at, upper_id = parse_pair(payload['context'])
        query = query.where(or_(WebhookEnvelope.created_at < upper_at,
            and_(WebhookEnvelope.created_at == upper_at, WebhookEnvelope.id <= upper_id)))
        if payload['after'] is not None:
            after_at, after_id = parse_pair(payload['after'])
            query = query.where(or_(WebhookEnvelope.created_at > after_at,
                and_(WebhookEnvelope.created_at == after_at, WebhookEnvelope.id > after_id)))
        rows = db.scalars(query.order_by(WebhookEnvelope.created_at, WebhookEnvelope.id).limit(limit + 1)).all()
        page = rows[:limit]
        items = [delivery_view(db, row) for row in page]
        next_cursor = None
        if len(rows) > limit:
            payload['after'] = pair(page[-1])
            next_cursor = encode_cursor(principal, payload)
        return {'schema': 'external-webhook-deliveries@1', 'items': items, 'next_cursor': next_cursor,
            'limit': limit, 'data_state': 'local_snapshot'}

    @app.get('/external/v1/webhook-deliveries/{delivery_id}')
    def delivery_detail(delivery_id: str, request: Request, db=Depends(get_db)):
        principal = _scope(request, 'webhooks:read')
        _queries(request, set())
        envelope = db.get(WebhookEnvelope, delivery_id)
        if envelope is None or envelope.owner_user_id != principal['owner']:
            fail('external_delivery_not_found', 404)
        return delivery_view(db, envelope, True)
