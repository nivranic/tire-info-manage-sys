"""Explicit interest settings and exact matching for unaccepted quality states."""
from copy import deepcopy
import hashlib
import re

from fastapi import HTTPException
from sqlalchemy import desc, func, inspect, select

from .db import (FactVersion, QueryRun, Snapshot, SourceQuarantine, Verification,
                 utc, utcnow, uid)
from .domain import IDENTITY_CONTRACT_VERSION, TireQuery, VariantInput, digest
from .interest_models import Interest, InterestEvent, InterestNotification, InterestRevision

DOMAIN = 'tire_source_quality'
POLICY = 'source-quality-interest@1'
QUALITY_KINDS = frozenset({'brand', 'model', 'size', 'oe', 'technology'})
SHA = re.compile(r'[0-9a-f]{64}')


class BaselineProofUnavailable(Exception):
    """An old, never-frozen baseline lacks a supported identity/member proof."""


def invalid():
    raise HTTPException(503, {'code': 'source_quality_interest_history_invalid',
                              'message': '来源质量通知的历史绑定未通过核对，请检查保留记录。'})


def stamp(value):
    return utc(value).isoformat()


def settings_fingerprint(data, archived):
    """Absent/false preserves the historical five-field settings contract."""
    frozen = {key: data[key] for key in
              ('name', 'enabled', 'conditions', 'metric_keys', 'changed_fields')}
    if data.get('source_quality_notifications', False):
        frozen.update(source_quality_notifications=True,
                      quality_subscription_schema='interest-source-quality@1')
    return digest({**frozen, 'archived': archived})


def quality_filters_supported(data):
    if data.get('source_quality_notifications', False) is not True:
        return True
    return (not data['metric_keys'] and not data['changed_fields']
            and all(condition['kind'] in QUALITY_KINDS for condition in data['conditions']))


def match_source_quality_event(event, criteria):
    """Match only one proven baseline member, never a rejected candidate."""
    from .interest_matching import _condition
    criteria = criteria.model_dump() if hasattr(criteria, 'model_dump') else criteria
    frozen = deepcopy({key: criteria[key] for key in ('conditions', 'metric_keys', 'changed_fields')})
    frozen['source_quality_notifications'] = criteria.get('source_quality_notifications', False)
    result = {'state': 'no_match', 'matched_sides': [], 'matched_baseline_members': [],
              'reasons': [], 'policy_version': POLICY, 'criteria': frozen}
    if frozen['source_quality_notifications'] is not True:
        return {**result, 'reasons': ['source_quality_not_subscribed']}
    if not quality_filters_supported(frozen):
        return {**result, 'state': 'indeterminate',
                'reasons': ['source_quality_interest_filter_unsupported']}
    after = event.get('after')
    if (event.get('domain') != DOMAIN or not isinstance(after, dict)
            or after.get('accepted') is not False or after.get('evidence_valid') is not True
            or not isinstance(after.get('baseline_members'), list) or not after['baseline_members']):
        return {**result, 'state': 'indeterminate', 'reasons': ['baseline_evidence_unverifiable']}
    unknown = set()
    matches = []
    for member in after['baseline_members']:
        if not isinstance(member, dict) or member.get('evidence_valid') is not True:
            unknown.add('baseline_evidence_unverifiable')
            continue
        checks = [_condition(member, condition) for condition in frozen['conditions']]
        if all(value is True for value, _reason in checks):
            reference = {key: member.get(key) for key in ('variant_id', 'structured_locator', 'member_hash')}
            if all(isinstance(value, str) and value for value in reference.values()):
                matches.append(reference)
            else:
                unknown.add('baseline_evidence_unverifiable')
        elif not any(value is False for value, _reason in checks):
            unknown.update(reason for value, reason in checks if value is None)
    if matches:
        return {**result, 'state': 'matched', 'matched_sides': ['after'],
                'matched_baseline_members': matches, 'reasons': ['matches_baseline_member']}
    if unknown:
        return {**result, 'state': 'indeterminate', 'reasons': sorted(unknown)}
    return {**result, 'reasons': ['condition_not_matched']}


def _quarantine(db, origin_id, *, content):
    columns = [SourceQuarantine.id, SourceQuarantine.query_id, SourceQuarantine.source_id,
        SourceQuarantine.query_key, SourceQuarantine.previous_snapshot_id, SourceQuarantine.source_url,
        SourceQuarantine.raw_hash, SourceQuarantine.content_type, SourceQuarantine.parser_version,
        SourceQuarantine.observed_at, SourceQuarantine.quality]
    if content:
        columns.append(SourceQuarantine.body)
    return db.execute(select(*columns).where(SourceQuarantine.id == origin_id)).one_or_none()


def _snapshot(db, snapshot_id, *, content):
    columns = [Snapshot.id, Snapshot.source_id, Snapshot.query_key, Snapshot.source_url,
        Snapshot.raw_hash, Snapshot.content_type, Snapshot.parser_version, Snapshot.observed_at,
        Snapshot.identity_contract_version, Snapshot.parsed_variants]
    if content:
        columns.append(Snapshot.body)
    return db.execute(select(*columns).where(Snapshot.id == snapshot_id)).one_or_none()


def _reference(kind, record_id, entity_id, *, snapshot=None, previous=None,
               source, url, verification_ids, fingerprint, contract):
    return {'kind': kind, 'record_id': record_id, 'entity_id': entity_id, 'revision': None,
        'snapshot_id': snapshot, 'previous_snapshot_id': previous, 'source_id': source,
        'source_url': url, 'verification_ids': verification_ids,
        'fingerprint': fingerprint, 'contract_version': contract}


def _payload(db, q, previous, *, content, initial):
    """Build the same public binding from exact rows, without selecting today's predecessor."""
    from .quality import metrics
    from .service import business_facts
    if q is None or previous is None:
        invalid()
    snapshot = _snapshot(db, q.previous_snapshot_id, content=content)
    queries = {row.id: row for row in db.execute(select(
        QueryRun.id, QueryRun.source_id, QueryRun.query_key, QueryRun.query).where(
        QueryRun.id.in_({q.query_id, previous.query_id})))}
    query, prior_query = queries.get(q.query_id), queries.get(previous.query_id)
    if snapshot is None or query is None or prior_query is None:
        invalid()
    canonical = TireQuery.model_validate(query.query).canonical()
    if (query.query != canonical or digest(canonical) != q.query_key
            or query.source_id != q.source_id or query.query_key != q.query_key
            or prior_query.query != canonical or prior_query.query_key != q.query_key
            or prior_query.source_id != q.source_id
            or previous.snapshot_id != snapshot.id or previous.source_id != q.source_id
            or previous.query_key != q.query_key or previous.status not in {'ok', 'not_modified'}
            or snapshot.source_id != q.source_id or snapshot.query_key != q.query_key
            or utc(snapshot.observed_at) > utc(previous.verified_at)
            or utc(previous.verified_at) > utc(q.observed_at)
            or not isinstance(q.source_url, str) or not q.source_url
            or not isinstance(snapshot.source_url, str) or not snapshot.source_url
            or not isinstance(q.parser_version, str) or not q.parser_version
            or not isinstance(snapshot.parser_version, str) or not snapshot.parser_version
            or not SHA.fullmatch(q.raw_hash) or not SHA.fullmatch(snapshot.raw_hash)):
        invalid()
    if initial:
        latest_id = db.scalar(select(Verification.id).where(
            Verification.source_id == q.source_id, Verification.query_key == q.query_key,
            Verification.status.in_(['ok', 'not_modified']))
            .order_by(desc(Verification.verified_at), desc(Verification.id)).limit(1))
        if latest_id != previous.id:
            invalid()
    if content:
        for row in (q, snapshot):
            if (not isinstance(row.body, str)
                    or hashlib.sha256(row.body.encode('utf-8')).hexdigest() != row.raw_hash):
                invalid()
    if not isinstance(snapshot.parsed_variants, list):
        invalid()
    if (not isinstance(q.quality, dict) or not isinstance(q.quality.get('reason_codes'), list)
            or not q.quality['reason_codes']
            or any(not isinstance(reason, str) or not reason for reason in q.quality['reason_codes'])):
        invalid()
    if q.quality.get('baseline_rows') != len(snapshot.parsed_variants):
        invalid()
    # A known old identity contract is a first-build proof gap. None of the
    # hash, source, query, predecessor or quality checks can be waived by it.
    if snapshot.identity_contract_version in (None, 'variant-identity@1'):
        raise BaselineProofUnavailable()
    if snapshot.identity_contract_version != IDENTITY_CONTRACT_VERSION:
        invalid()
    if not snapshot.parsed_variants:
        raise BaselineProofUnavailable()
    members = []
    proof_gap = False
    for index, member in enumerate(snapshot.parsed_variants):
        if not isinstance(member, dict):
            invalid()
        if not {'id', 'identity_key', 'identity_status', 'fact_version'}.issubset(member):
            proof_gap = True
            continue
        if (not isinstance(member['id'], str) or not member['id']
                or type(member['fact_version']) is not int or member['fact_version'] < 1):
            invalid()
        parsed = VariantInput.model_validate({key: value for key, value in member.items()
                                              if key in VariantInput.model_fields})
        identity_key, identity_status = parsed.identity_key(snapshot.source_id, snapshot.query_key, index)
        fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == member['id'],
            FactVersion.source_id == q.source_id, FactVersion.version == member['fact_version']))
        if (fact is None or utc(fact.observed_at) > utc(previous.verified_at)
                or identity_key != member['identity_key'] or identity_status != member['identity_status']
                or fact.facts_hash != digest(fact.facts)
                or fact.facts_hash != digest(business_facts(parsed.facts))):
            invalid()
        members.append({'variant_id': member['id'], 'structured_locator': f'/parsed_variants/{index}',
            'member_hash': digest(member), 'identity': parsed.identity(), 'facts': deepcopy(fact.facts),
            'fact_version_id': fact.id, 'fact_version': fact.version,
            'facts_hash': fact.facts_hash, 'evidence_valid': True})
    if proof_gap:
        raise BaselineProofUnavailable()
    if len({member['variant_id'] for member in members}) != len(members):
        invalid()
    quarantine = {'id': q.id, 'query_id': q.query_id, 'source_id': q.source_id, 'query_key': q.query_key,
        'query': canonical, 'source_url': q.source_url, 'raw_hash': q.raw_hash,
        'parser_version': q.parser_version, 'observed_at': stamp(q.observed_at),
        'reason_codes': deepcopy(q.quality['reason_codes']), 'metrics': metrics(q.quality),
        'previous_snapshot_id': snapshot.id}
    baseline = {'snapshot_id': snapshot.id, 'source_id': snapshot.source_id, 'query_key': snapshot.query_key,
        'source_url': snapshot.source_url, 'raw_hash': snapshot.raw_hash,
        'identity_contract_version': snapshot.identity_contract_version,
        'parsed_variants_hash': digest(snapshot.parsed_variants), 'verification_id': previous.id,
        'verification_status': previous.status, 'verified_at': stamp(previous.verified_at),
        'observed_at': stamp(snapshot.observed_at), 'parser_version': snapshot.parser_version}
    evidence = [
        _reference('tire_source_quarantine', q.id, q.id, previous=snapshot.id,
            source=q.source_id, url=q.source_url, verification_ids=[], fingerprint=q.raw_hash, contract=POLICY),
        _reference('tire_source_quality_baseline', snapshot.id, snapshot.id, snapshot=snapshot.id,
            source=snapshot.source_id, url=snapshot.source_url, verification_ids=[previous.id],
            fingerprint=snapshot.raw_hash, contract=snapshot.identity_contract_version),
    ]
    payload = {'schema': 'interest-event@1',
        'id': digest({'schema': 'interest-event@1', 'domain': DOMAIN, 'origin_id': q.id}),
        'domain': DOMAIN, 'action': 'quarantined', 'state': 'quarantined', 'revision': 1,
        'observed_at': stamp(q.observed_at), 'subject_id': q.id,
        'label': q.source_id + ' · 来源查询更新被质量隔离', 'before': None,
        'after': {'accepted': False, 'state': 'quarantined', 'evidence_valid': True,
                  'quarantine': quarantine, 'baseline': baseline, 'baseline_members': members},
        'changed_paths': ['source_quality'], 'evidence': evidence}
    payload['event_hash'] = digest(payload)
    return payload


def build_quality_payload(db, q, previous, *, content, initial=False):
    try:
        return _payload(db, q, previous, content=content, initial=initial)
    except BaselineProofUnavailable:
        if initial:
            return None
        invalid()
    except (ValueError, TypeError, AttributeError, KeyError, UnicodeError):
        invalid()


def checked_quality_event(db, event, *, content=False):
    """A successfully frozen event never degrades missing bindings to unknown."""
    try:
        payload = event.payload
        if (event.domain != DOMAIN or not isinstance(payload, dict)
                or event.event_hash != payload.get('event_hash')
                or event.event_hash != digest({key: value for key, value in payload.items() if key != 'event_hash'})):
            invalid()
        previous_id = payload['after']['baseline']['verification_id']
        q = _quarantine(db, event.origin_id, content=content)
        previous = db.get(Verification, previous_id)
        expected = build_quality_payload(db, q, previous, content=content)
        if (expected != payload or event.id != expected['id']
                or utc(event.observed_at) != utc(q.observed_at)):
            invalid()
        return deepcopy(payload)
    except (ValueError, TypeError, AttributeError, KeyError, UnicodeError):
        invalid()


def revision_criteria(row):
    return {key: getattr(row, key) for key in
            ('conditions', 'metric_keys', 'changed_fields', 'source_quality_notifications')}


def _valid_revision(row):
    data = {key: getattr(row, key) for key in
            ('name', 'enabled', 'conditions', 'metric_keys', 'changed_fields', 'source_quality_notifications')}
    if (row.source_quality_notifications is not True or row.enabled is not True or row.archived is not False
            or not quality_filters_supported(data)
            or row.fingerprint != settings_fingerprint(data, row.archived)):
        invalid()


def publish_quality_quarantine(db, quarantine, previous):
    """New-origin caller owns the ingestion lock and the isolation transaction."""
    is_new = inspect(quarantine).pending
    with db.no_autoflush:
        existing = db.scalar(select(InterestEvent).where(
            InterestEvent.domain == DOMAIN, InterestEvent.origin_id == quarantine.id))
    if existing is not None:
        checked_quality_event(db, existing)
        return existing
    # History reads, restored proofs and replays of old unpublished origins can
    # never become a new delivery opportunity.
    if not is_new:
        return None
    db.flush()
    payload = build_quality_payload(db, quarantine, previous, content=True, initial=True)
    if payload is None:
        return None
    event = InterestEvent(id=payload['id'], domain=DOMAIN, origin_id=quarantine.id,
        observed_at=quarantine.observed_at, event_hash=payload['event_hash'], payload=payload)
    db.add(event)
    db.flush()
    heads = select(InterestRevision.interest_id, func.max(InterestRevision.revision).label('revision')).group_by(
        InterestRevision.interest_id).subquery()
    try:
        revisions = db.execute(select(Interest, InterestRevision).join(InterestRevision,
            InterestRevision.interest_id == Interest.id).join(heads,
            (heads.c.interest_id == Interest.id) & (heads.c.revision == InterestRevision.revision))
            .where(InterestRevision.enabled.is_(True), InterestRevision.archived.is_(False),
                   InterestRevision.source_quality_notifications.is_(True),
                   Interest.created_at <= quarantine.observed_at,
                   InterestRevision.created_at <= quarantine.observed_at)).all()
    except (ValueError, TypeError, AttributeError, KeyError, UnicodeError):
        invalid()
    for interest, revision in revisions:
        try:
            _valid_revision(revision)
            result = match_source_quality_event(payload, revision_criteria(revision))
        except (ValueError, TypeError, AttributeError, KeyError, UnicodeError):
            invalid()
        if result['state'] != 'matched':
            continue
        db.add(InterestNotification(id=uid(), session_id=interest.session_id, interest_id=interest.id,
            interest_revision_id=revision.id, event_id=event.id, match=result, delivered_at=utcnow()))
        # This domain is explicitly local-only. The old publisher's outbox
        # validates only its existing nine-domain origin contract.
    db.flush()
    return event


def quality_notification_view(db, notice, *, content=False):
    try:
        event = db.get(InterestEvent, notice.event_id)
        revision = db.get(InterestRevision, notice.interest_revision_id)
        interest = db.get(Interest, notice.interest_id)
        if event is None or revision is None or interest is None:
            invalid()
        payload = checked_quality_event(db, event, content=content)
        _valid_revision(revision)
        if (revision.interest_id != interest.id or notice.session_id != interest.session_id
                or utc(interest.created_at) > utc(event.observed_at)
                or utc(revision.created_at) > utc(event.observed_at)
                or utc(notice.delivered_at) < utc(event.observed_at)):
            invalid()
        # Equal criteria cannot prove the original revision: names and other
        # settings may differ. Later edits must not invalidate frozen history.
        historical_head = db.scalar(select(InterestRevision.id).where(
            InterestRevision.interest_id == interest.id,
            InterestRevision.created_at <= event.observed_at).order_by(
                desc(InterestRevision.revision)).limit(1))
        if historical_head != revision.id:
            invalid()
        expected_match = match_source_quality_event(payload, revision_criteria(revision))
        if expected_match['state'] != 'matched' or digest(notice.match) != digest(expected_match):
            invalid()
        return {'id': notice.id, 'interest_id': interest.id, 'interest_revision': revision.revision,
            'interest_name': revision.name, 'delivered_at': stamp(notice.delivered_at),
            'read_at': stamp(notice.read_at) if notice.read_at is not None else None,
            'event': payload, 'match': deepcopy(expected_match)}
    except (ValueError, TypeError, AttributeError, KeyError, UnicodeError):
        invalid()
