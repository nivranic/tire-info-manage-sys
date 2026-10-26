"""Transactional reference-only outbox and durable, globally fenced dispatch."""
from datetime import datetime, timedelta
import hashlib
import re

from sqlalchemy import func, inspect, select

from .db import AlertEvent, ChangeEvent, NotificationDelivery, User, UserSession, uid, utc, utcnow
from .domain import digest, stable_json
from .service import QueryService, timestamp
from .webhook_models import (WebhookAttempt, WebhookCompletion, WebhookDispatchSlot,
    WebhookEnvelope, WebhookOverflow, WebhookQueue, WebhookRevision, WebhookStatistics,
    WebhookSubscription, WebhookTargetSlot)
from .webhook_policy import BODY_NOTICE, CHANNELS, DOMAINS, Catalog
from .webhook_transport import WebhookTransport, signed_headers

LEASE_SECONDS = 30
QUEUE_CAPACITY = 1000
TTL = timedelta(days=7)
NONTERMINAL = ('pending', 'inflight')


class HistoryInvalid(ValueError):
    def __init__(self):
        super().__init__('webhook_history_invalid')


def row_values(row, exclude=()):
    return {column.key: timestamp(value) if isinstance(value, datetime) else value
        for column in inspect(type(row)).columns
        if column.key not in exclude
        for value in [getattr(row, column.key)]}


def seal(row):
    row.fingerprint = digest(row_values(row, ('fingerprint',)))
    return row


def valid_seal(row):
    return row is not None and row.fingerprint == digest(row_values(row, ('fingerprint',)))


def _safe_status(value):
    return value is None or type(value) is int and 100 <= value <= 599


def _safe_code(value):
    return value is None or type(value) is str and re.fullmatch(r'webhook_[a-z0-9_]{1,64}', value) is not None


def catalog(db):
    return db.info.get('webhook_catalog', Catalog('empty'))


def head(db, subscription_id):
    return db.scalar(select(WebhookRevision).where(WebhookRevision.subscription_id == subscription_id)
        .order_by(WebhookRevision.revision.desc()).limit(1))


def valid_revision(db, subscription, revision):
    if (not subscription or not revision or revision.subscription_id != subscription.id or not valid_seal(revision)
            or type(revision.payload) is not dict or set(revision.payload) != {
                'name', 'channels', 'enabled', 'archived', 'target_fingerprint',
                'endpoint_host', 'acknowledged_external_delivery'}):
        raise HistoryInvalid()
    payload = revision.payload
    if (type(payload['name']) is not str or not payload['name'] or len(payload['name']) > 120
            or type(payload['channels']) is not list or not payload['channels']
            or len(set(payload['channels'])) != len(payload['channels'])
            or any(channel not in CHANNELS for channel in payload['channels'])
            or any(type(payload[key]) is not bool for key in ('enabled', 'archived', 'acknowledged_external_delivery'))
            or (payload['enabled'] and (payload['archived'] or not payload['acknowledged_external_delivery']))):
        raise HistoryInvalid()
    return payload


def readiness(db, subscription, revision):
    payload = valid_revision(db, subscription, revision)
    directory = catalog(db)
    target = directory.targets.get(subscription.target_id)
    if payload['archived']:
        return 'archived'
    if not db.get(User, subscription.owner_user_id):
        return 'owner_missing'
    if directory.state == 'invalid':
        return 'configuration_invalid'
    if not target:
        return 'target_missing'
    if not target.key:
        return 'key_unavailable'
    if target.policy_fingerprint != payload['target_fingerprint']:
        return 'policy_changed'
    return 'ready' if payload['enabled'] else 'paused'


def _origin(db, channel, event):
    if channel == 'tire_monitor':
        return db.get(ChangeEvent, event.change_id)
    if channel == 'recall_monitor':
        from .recall_models import RecallRevision
        return db.get(RecallRevision, event.revision_id)
    from .test_events import TireTestRevision
    from .vehicles import VehicleSnapshot
    from .fitment_relation_models import FitmentRelationRevision
    from .db import ManualFactRevision, VariantLifecycleEvent
    from .identity_models import IdentityRevision
    from .interest_catalog_models import TireCatalogRevision
    from .interest_applicability_models import TireCurationApplicabilityEvent
    models = {'tire': ChangeEvent, 'test_event': TireTestRevision, 'vehicle': VehicleSnapshot,
        'fitment': FitmentRelationRevision, 'tire_curation': ManualFactRevision,
        'tire_lifecycle': VariantLifecycleEvent, 'tire_identity': IdentityRevision,
        'tire_catalog': TireCatalogRevision, 'tire_curation_validity': TireCurationApplicabilityEvent}
    return db.get(models[event.domain], event.origin_id) if event.domain in models else None


def _references(db, channel, notification_id, event_id):
    from .interest_models import InterestEvent, InterestNotification
    from .recall_models import RecallEvent, RecallNotification
    models = {'tire_monitor': (NotificationDelivery, AlertEvent),
        'recall_monitor': (RecallNotification, RecallEvent), 'interest': (InterestNotification, InterestEvent)}
    if channel not in models:
        raise HistoryInvalid()
    notification_type, event_type = models[channel]
    notification, event = db.get(notification_type, notification_id), db.get(event_type, event_id)
    if not notification or not event or getattr(notification, 'alert_id' if channel == 'tire_monitor' else 'event_id') != event.id:
        raise HistoryInvalid()
    origin = _origin(db, channel, event)
    if origin is None:
        raise HistoryInvalid()
    if channel == 'interest':
        payload = event.payload
        if (event.domain not in DOMAINS or type(payload) is not dict or payload.get('event_hash') != event.event_hash
                or digest({key: value for key, value in payload.items() if key != 'event_hash'}) != event.event_hash
                or payload.get('id') != event.id or payload.get('domain') != event.domain):
            raise HistoryInvalid()
    return notification, event, origin


def association_for(db, channel, notification, event, origin):
    return {'notification_sha256': digest(row_values(notification, ('read_at',))),
        'event_sha256': digest(row_values(event)), 'origin_id': origin.id,
        'origin_sha256': digest(row_values(origin))}


def _body(delivery_id, channel, notification, event, origin):
    return {'schema': 'tire-webhook-event@1', 'delivery_id': delivery_id, 'channel': channel,
        'notification_id': notification.id, 'event_id': event.id,
        'domain': event.domain if channel == 'interest' else None,
        'occurred_at': timestamp(origin.observed_at if channel == 'tire_monitor' else event.observed_at),
        'data_scope': 'notification_reference_only', 'notice': BODY_NOTICE}


def validate_envelope(db, envelope, *, pending_retry=False):
    if not valid_seal(envelope):
        raise HistoryInvalid()
    subscription = db.get(WebhookSubscription, envelope.subscription_id)
    revision = db.get(WebhookRevision, envelope.revision_id)
    payload = valid_revision(db, subscription, revision)
    notification, event, origin = _references(db, envelope.channel, envelope.notification_id, envelope.event_id)
    expected = stable_json(_body(envelope.id, envelope.channel, notification, event, origin))
    if (envelope.owner_user_id != subscription.owner_user_id or envelope.channel not in payload['channels']
            or not payload['enabled'] or payload['archived'] or not payload['acknowledged_external_delivery']
            or envelope.domain != (event.domain if envelope.channel == 'interest' else None)
            or envelope.association != association_for(db, envelope.channel, notification, event, origin)
            or envelope.body != expected or envelope.body_sha256 != hashlib.sha256(expected.encode('utf-8')).hexdigest()):
        raise HistoryInvalid()
    queue = db.get(WebhookQueue, envelope.id)
    from .webhook_models import WebhookOperation
    retries = db.scalars(select(WebhookOperation).where(WebhookOperation.resource_type == 'delivery',
        WebhookOperation.resource_id == envelope.id, WebhookOperation.action == 'retry')).all()
    if any(not valid_seal(row) or row.owner_user_id != envelope.owner_user_id
            or row.response_hash != digest(row.response) for row in retries):
        raise HistoryInvalid()
    attempts = db.scalars(select(WebhookAttempt).where(WebhookAttempt.envelope_id == envelope.id)
        .order_by(WebhookAttempt.number)).all()
    if (not queue or queue.state not in (*NONTERMINAL, 'delivered', 'failed', 'blocked', 'cancelled')
            or type(queue.attempts) is not int or queue.attempts != len(attempts)
            or not 0 <= queue.attempts <= queue.max_attempts <= 20 or queue.max_attempts < 5
            or queue.max_attempts != 5 + 5 * (len(retries) + int(pending_retry))
            or not _safe_status(queue.http_status) or not _safe_code(queue.error_code)
            or (queue.state in NONTERMINAL) != (queue.completed_at is None)
            or (queue.state == 'pending') != (queue.next_attempt_at is not None)):
        raise HistoryInvalid()
    completions = []
    for number, attempt in enumerate(attempts, 1):
        completion = db.get(WebhookCompletion, attempt.id)
        if (attempt.number != number or not valid_seal(attempt) or attempt.body_sha256 != envelope.body_sha256
                or attempt.policy_fingerprint != payload['target_fingerprint']
                or utc(attempt.lease_until) != utc(attempt.started_at) + timedelta(seconds=LEASE_SECONDS)
                or attempt.signing_timestamp != str(int(utc(attempt.started_at).timestamp()))
                or (number < len(attempts) and completion is None)
                or (completion is not None and (not valid_seal(completion) or completion.state not in (
                    'delivered', 'retryable_failure', 'failed', 'blocked', 'unknown', 'cancelled')
                    or not _safe_status(completion.http_status) or not _safe_code(completion.error_code)
                    or utc(completion.completed_at) < utc(attempt.started_at)
                    or (completion.state == 'delivered' and (completion.error_code is not None
                        or completion.http_status is None or not 200 <= completion.http_status < 300))
                    or (completion.state == 'unknown' and (completion.http_status is not None
                        or completion.error_code != 'webhook_lease_expired'))))):
            raise HistoryInvalid()
        completions.append(completion)
    latest = completions[-1] if completions else None
    if queue.state == 'delivered' and (latest is None or latest.state != 'delivered'
            or queue.http_status != latest.http_status or queue.error_code is not None
            or utc(queue.completed_at) != utc(latest.completed_at)):
        raise HistoryInvalid()
    if queue.state == 'failed' and latest is None:
        raise HistoryInvalid()
    if queue.state == 'inflight' or queue.lease_token is not None:
        slot = db.get(WebhookDispatchSlot, 'global')
        if (not attempts or latest is not None or queue.state not in ('inflight', 'cancelled')
                or queue.lease_token != attempts[-1].token or queue.lease_until is None
                or utc(queue.lease_until) != utc(attempts[-1].lease_until)
                or not slot or slot.token != queue.lease_token or slot.attempt_id != attempts[-1].id
                or slot.lease_until is None or utc(slot.lease_until) != utc(queue.lease_until)):
            raise HistoryInvalid()
    elif queue.lease_until is not None or (attempts and latest is None):
        raise HistoryInvalid()
    if queue.state == 'pending' and attempts:
        retried = pending_retry or any(row.response.get('attempts') == queue.attempts
            and row.response.get('state') == 'pending' for row in retries)
        if latest is None or latest.state == 'delivered' or (latest.state not in ('unknown', 'retryable_failure') and not retried):
            raise HistoryInvalid()
    return subscription, revision, queue, attempts


def enqueue_notification(db, channel, notification, event, origin=None):
    """Only the caller's notification transaction; no lock/commit/session/network."""
    if channel not in CHANNELS:
        raise ValueError('webhook_channel_invalid')
    db.flush()
    owner = None
    if channel != 'tire_monitor':
        session = db.get(UserSession, notification.session_id)
        if not session or not session.user_id or utc(session.expires_at) <= utcnow() or not db.get(User, session.user_id):
            return
        owner = session.user_id
    origin = origin or _origin(db, channel, event)
    if origin is None:
        raise HistoryInvalid()
    query = select(WebhookSubscription)
    if owner:
        query = query.where(WebhookSubscription.owner_user_id == owner)
    for subscription in db.scalars(query).all():
        revision = head(db, subscription.id)
        if readiness(db, subscription, revision) != 'ready' or channel not in revision.payload['channels']:
            continue
        if db.scalar(select(WebhookEnvelope.id).where(WebhookEnvelope.subscription_id == subscription.id,
                WebhookEnvelope.channel == channel, WebhookEnvelope.notification_id == notification.id)):
            continue
        count = db.scalar(select(func.count()).select_from(WebhookQueue).join(WebhookEnvelope,
            WebhookEnvelope.id == WebhookQueue.id).where(WebhookEnvelope.subscription_id == subscription.id,
                WebhookQueue.state.in_(NONTERMINAL)))
        if count >= QUEUE_CAPACITY:
            stats = db.get(WebhookStatistics, subscription.id)
            if stats is None:
                stats = WebhookStatistics(subscription_id=subscription.id, suppressed_count=0)
                db.add(stats)
            stats.suppressed_count += 1
            stats.last_suppressed_at = utcnow()
            if db.get(WebhookOverflow, revision.id) is None:
                db.add(WebhookOverflow(revision_id=revision.id, created_at=utcnow()))
            db.flush()
            continue
        delivery_id, now = uid(), utcnow()
        body = stable_json(_body(delivery_id, channel, notification, event, origin))
        envelope = seal(WebhookEnvelope(id=delivery_id, subscription_id=subscription.id, revision_id=revision.id,
            owner_user_id=subscription.owner_user_id, channel=channel, notification_id=notification.id,
            event_id=event.id, domain=event.domain if channel == 'interest' else None,
            association=association_for(db, channel, notification, event, origin), body=body,
            body_sha256=hashlib.sha256(body.encode('utf-8')).hexdigest(), created_at=now))
        db.add(envelope)
        db.flush()
        db.add(WebhookQueue(id=delivery_id, state='pending', attempts=0, max_attempts=5, next_attempt_at=now))
        db.flush()


def cancel_old_queues(db, subscription_id, now):
    for queue in db.scalars(select(WebhookQueue).join(WebhookEnvelope, WebhookQueue.id == WebhookEnvelope.id)
            .where(WebhookEnvelope.subscription_id == subscription_id, WebhookQueue.state.in_(NONTERMINAL))).all():
        queue.state, queue.error_code, queue.completed_at = 'cancelled', 'webhook_revision_changed', now
        queue.next_attempt_at = None


def _completion(db, attempt, state, code, status, now):
    row = seal(WebhookCompletion(attempt_id=attempt.id, state=state, error_code=code,
        http_status=status, completed_at=now))
    db.add(row)
    return row


def _release(slot):
    slot.token = slot.attempt_id = slot.lease_until = None


def _retry_time(number, now, retry_after=None):
    return now + timedelta(seconds=retry_after or (60, 300, 1800, 7200)[(number - 1) % 5 % 4])


def _expire_locked(db, slot, now):
    if not slot or not slot.token or not slot.lease_until or utc(slot.lease_until) > now:
        return
    attempt = db.get(WebhookAttempt, slot.attempt_id)
    if attempt and attempt.token == slot.token:
        queue = db.get(WebhookQueue, attempt.envelope_id)
        envelope = db.get(WebhookEnvelope, attempt.envelope_id)
        if db.get(WebhookCompletion, attempt.id) is None:
            _completion(db, attempt, 'unknown', 'webhook_lease_expired', None, now)
        if queue and queue.lease_token == slot.token:
            if queue.state != 'cancelled':
                eligible = queue.attempts < queue.max_attempts and envelope and now < utc(envelope.created_at) + TTL
                queue.state = 'pending' if eligible else 'failed'
                queue.error_code, queue.http_status = 'webhook_lease_expired', None
                queue.next_attempt_at = _retry_time(queue.attempts, now) if eligible else None
                queue.completed_at = None if eligible else now
            queue.lease_token = queue.lease_until = None
    _release(slot)
    db.flush()


def claim_delivery(database, now=None):
    now = utc(now or utcnow())
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        slot = db.get(WebhookDispatchSlot, 'global')
        if slot is None:
            slot = WebhookDispatchSlot(id='global')
            db.add(slot)
            db.flush()
        _expire_locked(db, slot, now)
        if slot.token:
            db.commit()
            return None
        queues = db.scalars(select(WebhookQueue).where(WebhookQueue.state == 'pending',
            WebhookQueue.next_attempt_at <= now).order_by(WebhookQueue.next_attempt_at, WebhookQueue.id)).all()
        for queue in queues:
            envelope = db.get(WebhookEnvelope, queue.id)
            try:
                subscription, revision, _, _ = validate_envelope(db, envelope)
                current = head(db, subscription.id)
                code = readiness(db, subscription, revision)
                if current.id != revision.id or code in ('paused', 'archived'):
                    queue.state, queue.error_code, queue.completed_at = 'cancelled', 'webhook_revision_changed', now
                    queue.http_status = None
                    queue.next_attempt_at = None
                    continue
                if now >= utc(envelope.created_at) + TTL:
                    code = 'expired'
                if queue.attempts >= queue.max_attempts:
                    code = 'attempts_exhausted'
                if code != 'ready':
                    queue.state, queue.error_code, queue.completed_at = 'blocked', 'webhook_' + code, now
                    queue.http_status = None
                    queue.next_attempt_at = None
                    continue
            except (HistoryInvalid, ValueError, TypeError, KeyError):
                queue.state, queue.error_code, queue.completed_at = 'blocked', 'webhook_history_invalid', now
                queue.http_status = None
                queue.next_attempt_at = None
                continue
            target_slot = db.get(WebhookTargetSlot, subscription.target_id)
            if target_slot and utc(target_slot.next_allowed_at) > now:
                continue
            if target_slot is None:
                target_slot = WebhookTargetSlot(target_id=subscription.target_id, next_allowed_at=now)
                db.add(target_slot)
            target_slot.next_allowed_at = now + timedelta(seconds=1)
            token, attempt_id = uid(), uid()
            lease_until = now + timedelta(seconds=LEASE_SECONDS)
            attempt = seal(WebhookAttempt(id=attempt_id, envelope_id=envelope.id, number=queue.attempts + 1,
                token=token, started_at=now, lease_until=lease_until, signing_timestamp=str(int(now.timestamp())),
                body_sha256=envelope.body_sha256, policy_fingerprint=revision.payload['target_fingerprint']))
            db.add(attempt)
            queue.state, queue.attempts = 'inflight', attempt.number
            queue.lease_token, queue.lease_until, queue.next_attempt_at = token, lease_until, None
            queue.error_code = queue.http_status = queue.completed_at = None
            slot.token, slot.attempt_id, slot.lease_until = token, attempt_id, lease_until
            db.commit()
            return {'id': envelope.id, 'token': token, 'attempt_id': attempt_id, 'number': attempt.number}
        db.commit()
    return None


def _claim_rows(db, claim, now):
    slot = db.get(WebhookDispatchSlot, 'global')
    attempt = db.get(WebhookAttempt, claim.get('attempt_id'))
    queue = db.get(WebhookQueue, claim.get('id'))
    if (not slot or not attempt or not queue or not valid_seal(attempt) or slot.token != claim.get('token')
            or slot.attempt_id != attempt.id or attempt.token != slot.token or queue.lease_token != slot.token
            or attempt.envelope_id != queue.id or attempt.number != claim.get('number')
            or not slot.lease_until or utc(slot.lease_until) <= now
            or not queue.lease_until or utc(queue.lease_until) != utc(slot.lease_until)
            or utc(attempt.lease_until) != utc(slot.lease_until)
            or db.get(WebhookCompletion, attempt.id) is not None):
        return None
    try:
        validate_envelope(db, db.get(WebhookEnvelope, queue.id))
    except (ValueError, TypeError, KeyError):
        return None
    return slot, attempt, queue


def finish_delivery(database, claim, result, now=None):
    now = utc(now or utcnow())
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        rows = _claim_rows(db, claim, now)
        if rows is None:
            db.rollback()
            return False
        slot, attempt, queue = rows
        status = result.get('http_status')
        status = status if type(status) is int and 100 <= status <= 599 else None
        code = result.get('error_code')
        code = code if type(code) is str and re.fullmatch(r'webhook_[a-z0-9_]{1,64}', code) else None
        retryable = code in ('webhook_timeout', 'webhook_network_error') or (
            code in (None, 'webhook_http_error') and status is not None and (status in (408, 429) or status >= 500))
        success = status is not None and 200 <= status < 300 and code is None
        state = 'delivered' if success else 'blocked' if result.get('blocked') else 'retryable_failure' if retryable else 'failed'
        code = None if success else code or 'webhook_http_error'
        _completion(db, attempt, state, code, status, now)
        if queue.state != 'cancelled':
            envelope = db.get(WebhookEnvelope, queue.id)
            eligible = retryable and queue.attempts < queue.max_attempts and now < utc(envelope.created_at) + TTL
            queue.state = 'pending' if eligible else state if state in ('delivered', 'blocked') else 'failed'
            retry_after = result.get('retry_after')
            retry_after = max(1, min(3600, retry_after)) if type(retry_after) is int and status in (429, 503) else None
            queue.next_attempt_at = _retry_time(queue.attempts, now, retry_after) if eligible else None
            queue.completed_at = None if eligible else now
            queue.error_code, queue.http_status = code, status
        queue.lease_token = queue.lease_until = None
        _release(slot)
        db.commit()
    return True


async def dispatch_claim(database, claim, adapter=None, now=None):
    check_at = utc(now or utcnow())
    blocked = None
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        rows = _claim_rows(db, claim, check_at)
        if rows is None:
            return {'id': claim['id'], 'state': 'stale', 'finalized': False}
        _, attempt, queue = rows
        if utc(attempt.lease_until) < check_at + timedelta(seconds=10):
            return {'id': claim['id'], 'state': 'stale', 'finalized': False}
        try:
            envelope = db.get(WebhookEnvelope, claim['id'])
            subscription, revision, _, _ = validate_envelope(db, envelope)
            current = head(db, subscription.id)
            state = readiness(db, subscription, revision)
            if queue.state == 'cancelled' or current.id != revision.id or state != 'ready':
                blocked = 'webhook_revision_changed' if current.id != revision.id or queue.state == 'cancelled' else 'webhook_' + state
            else:
                target = catalog(db).targets[subscription.target_id]
                raw_body = envelope.body.encode('utf-8')
                headers = signed_headers(target, envelope.id, attempt.number, attempt.signing_timestamp, raw_body)
        except (ValueError, TypeError, KeyError):
            blocked = 'webhook_history_invalid'
        db.commit()
    if blocked:
        result = {'http_status': None, 'error_code': blocked, 'blocked': True}
    else:
        try:
            result = await (adapter or WebhookTransport()).send(target, raw_body, headers)
        except Exception:
            result = {'http_status': None, 'error_code': 'webhook_network_error'}
    finalized = finish_delivery(database, claim, result, now=now)
    return {'id': claim['id'], 'state': 'completed' if finalized else 'stale', 'finalized': finalized}


async def run_webhook_cycle(database, max_jobs=100, adapter=None, now=None):
    results = []
    for _ in range(max(0, min(100, max_jobs))):
        claim = claim_delivery(database, now=now)
        if claim is None:
            break
        results.append(await dispatch_claim(database, claim, adapter=adapter, now=now))
    return {'checked_at': timestamp(now or utcnow()), 'jobs': len(results), 'results': results}
