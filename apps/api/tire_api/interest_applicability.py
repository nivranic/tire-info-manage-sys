"""Source-base replacement invalidates overlays without changing curator rows."""
from copy import deepcopy
import hashlib

from sqlalchemy import func, select

from .db import FactVersion, ManualFactRevision, Snapshot, Verification, uid, utc
from .domain import digest
from .interest_applicability_models import TireCurationApplicabilityEvent
from .interest_events import _event
from .interest_governance import (_attach_relations, _label, primary_reference, public_record, snapshot_context)
from .interest_matching import changed_paths
from .service import timestamp

DOMAIN = 'tire_curation_validity'
KIND = 'tire_curation_applicability_event'


def manual_heads(db, variant_id, source_id, watermark):
    rows = db.scalars(select(ManualFactRevision).where(ManualFactRevision.variant_id == variant_id,
        ManualFactRevision.source_id == source_id, ManualFactRevision.revision <= watermark)
        .order_by(ManualFactRevision.revision)).all()
    return {row.field: row for row in rows}


def affected_heads(heads, before_fact_id):
    return [{'manual_revision_id': row.id, 'manual_revision': row.revision, 'field': row.field,
        'action': row.action, 'before_status': 'revoked' if row.action == 'revoke' else 'manual_override',
        'after_status': 'needs_review', 'manual_fingerprint': digest(public_record(row))}
        for field, row in sorted(heads.items())
        if row.base_fact_id == before_fact_id and row.action in ('manual_override', 'revoke')]


def fact_basis(db, fact, verification=None):
    snapshot = db.get(Snapshot, fact.snapshot_id) if fact else None
    members = [(index, item) for index, item in enumerate(snapshot.parsed_variants)
        if isinstance(item, dict) and item.get('id') == fact.variant_id] if snapshot else []
    index, member = members[0] if len(members) == 1 else (None, None)
    return {'snapshot_id': fact.snapshot_id if fact else None, 'source_id': fact.source_id if fact else None,
        'query_key': snapshot.query_key if snapshot else None, 'source_url': snapshot.source_url if snapshot else None,
        'raw_hash': snapshot.raw_hash if snapshot else None,
        'identity_contract_version': snapshot.identity_contract_version if snapshot else None,
        'parsed_variants_hash': digest(snapshot.parsed_variants) if snapshot else None,
        'verification_id': verification.id if verification else None,
        'verification_status': verification.status if verification else None,
        'verified_at': timestamp(verification.verified_at) if verification else None,
        'present': bool(members), 'member_hash': digest(member) if member is not None else None,
        'structured_locator': f'/parsed_variants/{index}' if member is not None else None,
        'fact_version_id': fact.id if fact else None, 'fact_version': fact.version if fact else None,
        'facts_hash': fact.facts_hash if fact else None,
        'snapshot_member_fact_version': member.get('fact_version') if member is not None else None}


def previous_proof(db, fact, asof):
    snapshot = db.get(Snapshot, fact.snapshot_id)
    if snapshot is None:
        return None
    return db.scalar(select(Verification).where(Verification.snapshot_id == snapshot.id,
        Verification.source_id == fact.source_id, Verification.query_key == snapshot.query_key,
        Verification.status.in_(['ok', 'not_modified']), Verification.verified_at <= asof)
        .order_by(Verification.verified_at, Verification.id).limit(1))


def material(db, row):
    before_fact, after_fact = db.get(FactVersion, row.before_fact_id), db.get(FactVersion, row.after_fact_id)
    heads = manual_heads(db, row.variant_id, row.source_id, row.manual_revision_watermark)
    expected = affected_heads(heads, row.before_fact_id)
    valid = bool(before_fact and after_fact and row.affected and expected == row.affected
        and all(fact.variant_id == row.variant_id and fact.source_id == row.source_id
                and digest(fact.facts) == fact.facts_hash for fact in (before_fact, after_fact))
        and after_fact.version == before_fact.version + 1 and row.action == 'invalidate')
    contexts, refs, proofs = [], [], []
    for name, fact in (('before', before_fact), ('after', after_fact)):
        bound = row.binding[name]
        proof = db.get(Verification, bound['verification_id']) if bound['verification_id'] else None
        proofs.append(proof)
        valid = bool(valid and fact_basis(db, fact, proof) == bound)
        if proof:
            snapshot = db.get(Snapshot, fact.snapshot_id) if fact else None
            valid = bool(valid and snapshot and proof.snapshot_id == snapshot.id
                and proof.source_id == snapshot.source_id == row.source_id
                and proof.query_key == snapshot.query_key and proof.status in ('ok', 'not_modified')
                and utc(proof.verified_at) <= utc(row.created_at))
        side, more = snapshot_context(db, fact.snapshot_id, row.variant_id, row.created_at, fact) if fact else (
            {'evidence_valid': False}, [])
        contexts.append(side)
        refs.extend(more)
    trigger = proofs[1]
    valid = bool(valid and trigger and trigger.id == row.verification_id
        and utc(after_fact.observed_at) == utc(trigger.verified_at) == utc(row.created_at))
    for head in heads.values():
        if head.base_fact_id == row.before_fact_id and head.action in ('manual_override', 'revoke'):
            refs.append(primary_reference('tire_curation_revision', head))
    return before_fact, after_fact, heads, contexts, refs, valid


def validate_original(db, row):
    """Check immutable linked material without reading current aggregate heads."""
    before, after, _heads, _contexts, _refs, valid = material(db, row)
    for fact in (before, after):
        snapshot = db.get(Snapshot, fact.snapshot_id) if fact else None
        if snapshot and hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest() != snapshot.raw_hash:
            valid = False
    return valid


def freeze_applicability(db, row):
    before_fact, after_fact, heads, contexts, refs, integrity = material(db, row)
    before, after = contexts
    effective = deepcopy(before_fact.facts) if before_fact else {}
    for field, head in heads.items():
        if head.base_fact_id != row.before_fact_id:
            continue
        if head.action == 'manual_override':
            effective[field] = deepcopy(head.after['value'])
        elif head.action == 'revoke':
            effective.pop(field, None)
    valid = bool(integrity and before.get('evidence_valid') and after.get('evidence_valid'))
    before.update(facts=effective, source_facts=deepcopy(before_fact.facts) if before_fact else {},
        state='applicable', curation_applicability={'affected': deepcopy(row.affected), 'state': 'applicable'},
        evidence_valid=valid)
    after.update(source_facts=deepcopy(after_fact.facts) if after_fact else {}, state='needs_review',
        curation_applicability={'affected': deepcopy(row.affected), 'state': 'needs_review'}, evidence_valid=valid)
    for side in (before, after):
        refs.extend(_attach_relations(db, side, row))
    refs.append(primary_reference(KIND, row))
    payload = _event(DOMAIN, row, 'invalidate', 'needs_review', row.revision, row.variant_id,
        _label([after], row.variant_id), before, after, refs, row.created_at)
    payload['changed_paths'] = sorted(set(changed_paths({'facts': before['facts']}, {'facts': after.get('facts', {})})
        + ['curation_applicability', 'state']))
    payload['event_hash'] = digest({key: value for key, value in payload.items() if key != 'event_hash'})
    return payload


def append_applicability(db, transitions, verification):
    from .interest_events import publish
    rows = []
    for before_fact, after_fact in transitions:
        if before_fact is None:
            continue
        existing = db.scalar(select(TireCurationApplicabilityEvent).where(
            TireCurationApplicabilityEvent.after_fact_id == after_fact.id))
        if existing:
            continue
        watermark = db.scalar(select(func.max(ManualFactRevision.revision)).where(
            ManualFactRevision.variant_id == after_fact.variant_id, ManualFactRevision.source_id == after_fact.source_id)) or 0
        heads = manual_heads(db, after_fact.variant_id, after_fact.source_id, watermark)
        affected = affected_heads(heads, before_fact.id)
        if not affected:
            continue
        revision = db.scalar(select(func.max(TireCurationApplicabilityEvent.revision)).where(
            TireCurationApplicabilityEvent.variant_id == after_fact.variant_id,
            TireCurationApplicabilityEvent.source_id == after_fact.source_id)) or 0
        row = TireCurationApplicabilityEvent(id=uid(), variant_id=after_fact.variant_id,
            source_id=after_fact.source_id, before_fact_id=before_fact.id, after_fact_id=after_fact.id,
            verification_id=verification.id, revision=revision + 1, action='invalidate',
            manual_revision_watermark=watermark, affected=affected,
            binding={'before': fact_basis(db, before_fact, previous_proof(db, before_fact, verification.verified_at)),
                     'after': fact_basis(db, after_fact, verification)}, created_at=verification.verified_at)
        db.add(row)
        db.flush()
        publish(db, DOMAIN, row, allow_indeterminate=True)
        rows.append(row)
    return rows
