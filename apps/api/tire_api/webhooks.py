"""Account-owned webhook revisions, frozen operations and history-only reads."""
from copy import deepcopy
import re
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, StrictBool, StrictInt, field_validator
from sqlalchemy import func, select

from .db import User, UserSession, uid, utc, utcnow
from .domain import StrictModel, digest
from .service import QueryService, timestamp
from .webhook_delivery import (HistoryInvalid, NONTERMINAL, TTL, cancel_old_queues, catalog, head,
    readiness, seal, valid_revision, valid_seal, validate_envelope)
from .webhook_models import (WebhookCompletion, WebhookEnvelope, WebhookOperation, WebhookQueue,
    WebhookRevision, WebhookStatistics, WebhookSubscription)
from .webhook_policy import NOTICE

Channel = Literal['tire_monitor', 'recall_monitor', 'interest']


class Settings(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    target_fingerprint: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    channels: list[Channel] = Field(min_length=1, max_length=3)
    enabled: StrictBool = False
    acknowledged_external_delivery: StrictBool = False

    @field_validator('name')
    @classmethod
    def safe_name(cls, value):
        if not value.strip() or not value.isprintable():
            raise ValueError('webhook_name_invalid')
        return value.strip()

    @field_validator('channels')
    @classmethod
    def unique_channels(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('webhook_channels_duplicate')
        return sorted(value)


class Create(Settings):
    target_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')


class Edit(Settings):
    expected_revision: StrictInt = Field(ge=1)


class State(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    action: Literal['pause', 'resume', 'archive', 'restore']
    target_fingerprint: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    acknowledged_external_delivery: StrictBool = False


class DeliveryAction(StrictModel):
    expected_attempts: StrictInt = Field(ge=0, le=20)
    acknowledged: Literal[True]

    @field_validator('acknowledged', mode='before')
    @classmethod
    def strict_ack(cls, value):
        if value is not True:
            raise ValueError('webhook_acknowledgement_required')
        return value


def fail(code, status=409):
    raise HTTPException(status, {'code': code})


def authenticated(db, session_id):
    session = db.get(UserSession, session_id, populate_existing=True)
    if not session or not session.user_id or utc(session.expires_at) <= utcnow():
        fail('webhook_login_required', 401)
    user = db.get(User, session.user_id)
    if user is None:
        fail('webhook_login_required', 401)
    return user.id


def subscription_view(db, subscription, revision=None):
    revision = revision or head(db, subscription.id)
    payload = valid_revision(db, subscription, revision)
    stats = db.get(WebhookStatistics, subscription.id)
    return {'schema': 'webhook@1', 'id': subscription.id, 'owner_scope': 'current_account',
        'revision': revision.revision, 'revision_id': revision.id, 'name': payload['name'],
        'target_id': subscription.target_id, 'target_fingerprint': payload['target_fingerprint'],
        'endpoint_host': payload['endpoint_host'], 'channels': deepcopy(payload['channels']),
        'enabled': payload['enabled'], 'archived': payload['archived'],
        'created_at': timestamp(subscription.created_at), 'updated_at': timestamp(revision.created_at),
        'readiness': readiness(db, subscription, revision), 'notice': NOTICE,
        'suppressed_count': stats.suppressed_count if stats else 0,
        'last_suppressed_at': timestamp(stats.last_suppressed_at) if stats else None}


def delivery_view(db, envelope, detail=False, *, pending_retry=False):
    subscription, revision, queue, attempts = validate_envelope(db, envelope, pending_retry=pending_retry)
    result = {'id': envelope.id, 'webhook_id': subscription.id, 'webhook_revision': revision.revision,
        'channel': envelope.channel, 'notification_id': envelope.notification_id, 'event_id': envelope.event_id,
        'domain': envelope.domain, 'state': queue.state, 'attempts': queue.attempts,
        'max_attempts': queue.max_attempts, 'next_attempt_at': timestamp(queue.next_attempt_at),
        'created_at': timestamp(envelope.created_at), 'completed_at': timestamp(queue.completed_at),
        'error_code': queue.error_code, 'http_status': queue.http_status, 'body_sha256': envelope.body_sha256}
    if detail:
        from .webhook_policy import strict_json
        history = []
        for attempt in attempts:
            completion = db.get(WebhookCompletion, attempt.id)
            history.append({'number': attempt.number, 'started_at': timestamp(attempt.started_at),
                'completed_at': timestamp(completion.completed_at) if completion else None,
                'state': completion.state if completion else 'inflight',
                'error_code': completion.error_code if completion else None,
                'http_status': completion.http_status if completion else None})
        result.update(schema='webhook-delivery@1', body=strict_json(envelope.body), attempt_history=history, current=False)
    return result


def operation_view(db, operation, replayed):
    if not valid_seal(operation) or operation.response_hash != digest(operation.response):
        raise HistoryInvalid()
    if operation.resource_type == 'webhook':
        subscription = db.get(WebhookSubscription, operation.resource_id)
        revision = db.get(WebhookRevision, operation.response.get('revision_id'))
        payload = valid_revision(db, subscription, revision)
        if (subscription.owner_user_id != operation.owner_user_id or operation.response.get('id') != subscription.id
                or operation.response.get('revision') != revision.revision or operation.response.get('name') != payload['name']):
            raise HistoryInvalid()
    elif operation.resource_type == 'delivery':
        envelope = db.get(WebhookEnvelope, operation.resource_id)
        validate_envelope(db, envelope)
        if envelope.owner_user_id != operation.owner_user_id or operation.response.get('id') != envelope.id:
            raise HistoryInvalid()
    else:
        raise HistoryInvalid()
    return {'schema': 'webhook-operation@1', 'id': operation.id, 'idempotency_key': operation.idempotency_key,
        'action': operation.action, 'created_at': timestamp(operation.created_at),
        'resource_type': operation.resource_type, 'resource_id': operation.resource_id,
        'response': deepcopy(operation.response), 'current': False, 'replayed': replayed}


def _key(value):
    try:
        if type(value) is not str or str(UUID(value)) != value.lower():
            raise ValueError()
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError):
        fail('webhook_idempotency_key_required', 422)


def _owned(db, owner, subscription_id):
    row = db.get(WebhookSubscription, subscription_id)
    if row is None or row.owner_user_id != owner:
        fail('webhook_not_found', 404)
    return row


def _target(db, target_id, fingerprint, enabled, acknowledged):
    directory = catalog(db)
    target = directory.targets.get(target_id)
    if directory.state == 'invalid':
        fail('webhook_configuration_invalid')
    if target is None:
        fail('webhook_target_missing')
    if target.policy_fingerprint != fingerprint:
        fail('webhook_policy_changed')
    if enabled and (not target.key or not fingerprint or not acknowledged):
        fail('webhook_external_delivery_consent_required' if not acknowledged else 'webhook_key_unavailable')
    return target


def _revision(db, subscription, number, payload):
    revision = seal(WebhookRevision(id=uid(), subscription_id=subscription.id, revision=number,
        payload=deepcopy(payload), created_at=utcnow()))
    db.add(revision)
    db.flush()
    cancel_old_queues(db, subscription.id, utcnow())
    db.flush()
    return revision


def _begin(db, request, key, action, payload):
    QueryService(db, None).lock_ingestion()
    owner = authenticated(db, request.state.session_id)
    key = _key(key)
    request_hash = digest({'method': request.method, 'path': request.url.path, 'action': action, 'body': payload})
    previous = db.scalar(select(WebhookOperation).where(WebhookOperation.owner_user_id == owner,
        WebhookOperation.idempotency_key == key))
    if previous:
        if (previous.request_hash != request_hash or previous.method != request.method
                or previous.path != request.url.path or previous.action != action):
            fail('webhook_idempotency_conflict')
        return owner, key, request_hash, operation_view(db, previous, True)
    return owner, key, request_hash, None


def _finish(db, owner, key, request_hash, request, action, resource_type, resource_id, response):
    operation = seal(WebhookOperation(id=uid(), owner_user_id=owner, idempotency_key=key,
        action=action, method=request.method, path=request.url.path, request_hash=request_hash,
        resource_type=resource_type, resource_id=resource_id, response=deepcopy(response),
        response_hash=digest(response), created_at=utcnow()))
    db.add(operation)
    db.flush()
    result = operation_view(db, operation, False)
    db.commit()
    return result


def register_webhook_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    def guard(request: Request, db=Depends(get_db)):
        return authenticated(db, request.state.session_id)

    def resource_guard(subscription_id: str, owner=Depends(guard), db=Depends(get_db)):
        return _owned(db, owner, subscription_id)

    def delivery_guard(subscription_id: str, delivery_id: str, owner=Depends(guard), db=Depends(get_db)):
        _owned(db, owner, subscription_id)
        envelope = db.get(WebhookEnvelope, delivery_id)
        if not envelope or envelope.subscription_id != subscription_id or envelope.owner_user_id != owner:
            fail('webhook_delivery_not_found', 404)

    def page(limit: str = Query('20'), offset: str = Query('0')):
        if not re.fullmatch(r'[0-9]+', limit) or not re.fullmatch(r'[0-9]+', offset):
            fail('webhook_pagination_invalid', 422)
        size, start = int(limit), int(offset)
        if not 1 <= size <= 100 or not 0 <= start <= 10000:
            fail('webhook_pagination_invalid', 422)
        return size, start

    @app.exception_handler(HistoryInvalid)
    async def invalid_history(_request, _error):
        return JSONResponse(status_code=409, content={'detail': {'code': 'webhook_history_invalid'}})

    @app.get('/v1/webhooks/targets', dependencies=[Depends(guard)])
    def targets(db=Depends(get_db)):
        return catalog(db).public()

    @app.get('/v1/webhook-operations', dependencies=[Depends(guard)])
    def operation_history(key: str, mode: Literal['history'], owner=Depends(guard), db=Depends(get_db)):
        operation = db.scalar(select(WebhookOperation).where(WebhookOperation.owner_user_id == owner,
            WebhookOperation.idempotency_key == _key(key)))
        if operation is None:
            fail('webhook_operation_not_found', 404)
        return operation_view(db, operation, True)

    @app.post('/v1/webhooks', status_code=201, dependencies=[Depends(guard)])
    def create(payload: Create, request: Request, idempotency_key: str | None = Header(default=None), db=Depends(get_db)):
        owner, key, request_hash, replay = _begin(db, request, idempotency_key, 'create', payload.model_dump())
        if replay:
            return replay
        target = _target(db, payload.target_id, payload.target_fingerprint, payload.enabled, payload.acknowledged_external_delivery)
        rows = db.scalars(select(WebhookSubscription).where(WebhookSubscription.owner_user_id == owner)).all()
        if sum(not valid_revision(db, row, head(db, row.id))['archived'] for row in rows) >= 16:
            fail('webhook_subscription_limit')
        subscription = WebhookSubscription(id=uid(), owner_user_id=owner, target_id=target.id, created_at=utcnow())
        db.add(subscription)
        db.flush()
        settings = payload.model_dump(exclude={'target_id'})
        settings.update(archived=False, endpoint_host=target.endpoint_host)
        revision = _revision(db, subscription, 1, settings)
        return _finish(db, owner, key, request_hash, request, 'create', 'webhook', subscription.id,
            subscription_view(db, subscription, revision))

    @app.get('/v1/webhooks', dependencies=[Depends(guard)])
    def listing(mode: Literal['history'], owner=Depends(guard), pagination=Depends(page), db=Depends(get_db)):
        limit, offset = pagination
        query = select(WebhookSubscription).where(WebhookSubscription.owner_user_id == owner)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        items = db.scalars(query.order_by(WebhookSubscription.created_at.desc(), WebhookSubscription.id).limit(limit).offset(offset)).all()
        return {'schema': 'webhooks@1', 'items': [subscription_view(db, row) for row in items],
            'total': total, 'limit': limit, 'offset': offset}

    @app.get('/v1/webhooks/{subscription_id}', dependencies=[Depends(resource_guard)])
    def detail(subscription_id: str, mode: Literal['history'], owner=Depends(guard), db=Depends(get_db)):
        return subscription_view(db, _owned(db, owner, subscription_id))

    @app.put('/v1/webhooks/{subscription_id}', dependencies=[Depends(resource_guard)])
    def edit(subscription_id: str, payload: Edit, request: Request,
            idempotency_key: str | None = Header(default=None), db=Depends(get_db)):
        owner, key, request_hash, replay = _begin(db, request, idempotency_key, 'edit', payload.model_dump())
        if replay:
            return replay
        subscription = _owned(db, owner, subscription_id)
        current = head(db, subscription.id)
        old = valid_revision(db, subscription, current)
        if old['archived'] or current.revision != payload.expected_revision:
            fail('webhook_revision_conflict')
        target = _target(db, subscription.target_id, payload.target_fingerprint, payload.enabled, payload.acknowledged_external_delivery)
        settings = payload.model_dump(exclude={'expected_revision'})
        settings.update(archived=False, endpoint_host=target.endpoint_host)
        revision = _revision(db, subscription, current.revision + 1, settings)
        return _finish(db, owner, key, request_hash, request, 'edit', 'webhook', subscription.id,
            subscription_view(db, subscription, revision))

    @app.post('/v1/webhooks/{subscription_id}/state', dependencies=[Depends(resource_guard)])
    def state(subscription_id: str, payload: State, request: Request,
            idempotency_key: str | None = Header(default=None), db=Depends(get_db)):
        owner, key, request_hash, replay = _begin(db, request, idempotency_key, payload.action, payload.model_dump())
        if replay:
            return replay
        subscription = _owned(db, owner, subscription_id)
        current = head(db, subscription.id)
        settings = deepcopy(valid_revision(db, subscription, current))
        if current.revision != payload.expected_revision:
            fail('webhook_revision_conflict')
        if payload.action == 'restore':
            if not settings['archived']:
                fail('webhook_state_conflict')
            active = db.scalars(select(WebhookSubscription).where(WebhookSubscription.owner_user_id == owner)).all()
            if sum(not valid_revision(db, row, head(db, row.id))['archived'] for row in active) >= 16:
                fail('webhook_subscription_limit')
            settings.update(archived=False, enabled=False)
        elif payload.action == 'archive':
            settings.update(archived=True, enabled=False)
        elif payload.action == 'pause':
            settings['enabled'] = False
        else:
            if settings['archived']:
                fail('webhook_state_conflict')
            target = _target(db, subscription.target_id, payload.target_fingerprint, True, payload.acknowledged_external_delivery)
            settings.update(enabled=True, target_fingerprint=target.policy_fingerprint,
                endpoint_host=target.endpoint_host, acknowledged_external_delivery=True)
        revision = _revision(db, subscription, current.revision + 1, settings)
        return _finish(db, owner, key, request_hash, request, payload.action, 'webhook', subscription.id,
            subscription_view(db, subscription, revision))

    @app.get('/v1/webhooks/{subscription_id}/deliveries', dependencies=[Depends(resource_guard)])
    def deliveries(subscription_id: str, mode: Literal['history'], owner=Depends(guard), pagination=Depends(page), db=Depends(get_db)):
        subscription = _owned(db, owner, subscription_id)
        query = select(WebhookEnvelope).where(WebhookEnvelope.subscription_id == subscription.id)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        limit, offset = pagination
        rows = db.scalars(query.order_by(WebhookEnvelope.created_at.desc(), WebhookEnvelope.id).limit(limit).offset(offset)).all()
        return {'schema': 'webhook-deliveries@1', 'items': [delivery_view(db, row) for row in rows],
            'total': total, 'limit': limit, 'offset': offset}

    def owned_envelope(db, owner, subscription_id, delivery_id):
        _owned(db, owner, subscription_id)
        envelope = db.get(WebhookEnvelope, delivery_id)
        if not envelope or envelope.subscription_id != subscription_id or envelope.owner_user_id != owner:
            fail('webhook_delivery_not_found', 404)
        return envelope

    @app.get('/v1/webhooks/{subscription_id}/deliveries/{delivery_id}', dependencies=[Depends(delivery_guard)])
    def delivery_detail(subscription_id: str, delivery_id: str, mode: Literal['history'], owner=Depends(guard), db=Depends(get_db)):
        return delivery_view(db, owned_envelope(db, owner, subscription_id, delivery_id), True)

    def delivery_action(subscription_id, delivery_id, payload, request, key_header, db, action):
        owner, key, request_hash, replay = _begin(db, request, key_header, action, payload.model_dump())
        if replay:
            return replay
        envelope = owned_envelope(db, owner, subscription_id, delivery_id)
        subscription, revision, queue, _ = validate_envelope(db, envelope)
        if queue.attempts != payload.expected_attempts:
            fail('webhook_attempt_conflict')
        now = utcnow()
        if action == 'retry':
            if (queue.state not in ('failed', 'blocked') or head(db, subscription.id).id != revision.id
                    or readiness(db, subscription, revision) != 'ready' or now >= utc(envelope.created_at) + TTL
                    or queue.max_attempts >= 20):
                fail('webhook_retry_unavailable')
            queue.max_attempts += 5
            queue.state, queue.next_attempt_at = 'pending', now
            queue.error_code = queue.http_status = queue.completed_at = None
        else:
            if queue.state == 'delivered':
                fail('webhook_cancel_unavailable')
            queue.state, queue.completed_at, queue.next_attempt_at = 'cancelled', now, None
            queue.error_code = 'webhook_cancelled'
        db.flush()
        return _finish(db, owner, key, request_hash, request, action, 'delivery', envelope.id,
            delivery_view(db, envelope, True, pending_retry=action == 'retry'))

    @app.post('/v1/webhooks/{subscription_id}/deliveries/{delivery_id}/retry', dependencies=[Depends(delivery_guard)])
    def retry(subscription_id: str, delivery_id: str, payload: DeliveryAction, request: Request,
            idempotency_key: str | None = Header(default=None), db=Depends(get_db)):
        return delivery_action(subscription_id, delivery_id, payload, request, idempotency_key, db, 'retry')

    @app.post('/v1/webhooks/{subscription_id}/deliveries/{delivery_id}/cancel', dependencies=[Depends(delivery_guard)])
    def cancel(subscription_id: str, delivery_id: str, payload: DeliveryAction, request: Request,
            idempotency_key: str | None = Header(default=None), db=Depends(get_db)):
        return delivery_action(subscription_id, delivery_id, payload, request, idempotency_key, db, 'cancel')
