"""Freeze accepted local evidence and deliver private interests in its transaction.

Historical preview calls the same adapters without persisting or delivering.
No adapter fetches a source, resolves a name, or substitutes today's tire identity.
"""
from copy import deepcopy
import hashlib

from sqlalchemy import Text, cast, desc, func, select, union_all, literal, or_

from .db import ChangeEvent, FactVersion, Snapshot, Verification, utc
from .domain import IDENTITY_CONTRACT_VERSION, VariantInput, digest
from .interest_matching import changed_paths, match_event
from .interest_models import Interest, InterestEvent, InterestNotification, InterestRevision
from .service import business_facts, timestamp


class InterestEvidenceError(ValueError):
    """A new accepted producer must roll back if its evidence cannot be frozen."""


def _reference(kind, record_id, entity_id, *, revision=None, snapshot=None, previous=None,
               source=None, url=None, verifications=(), fingerprint=None, contract=None):
    return {'kind': kind, 'record_id': record_id, 'entity_id': entity_id, 'revision': revision,
            'snapshot_id': snapshot, 'previous_snapshot_id': previous, 'source_id': source,
            'source_url': url, 'verification_ids': list(verifications),
            'fingerprint': fingerprint, 'contract_version': contract}


def _tire_side(db, snapshot_id, variant_id, fact, asof, *, reconciliation=False):
    snapshot = db.get(Snapshot, snapshot_id) if snapshot_id else None
    invalid = {'identity': None, 'facts': deepcopy(fact.facts) if fact else {}, 'evidence_valid': False}
    if snapshot is None or fact is None:
        return invalid, []
    verification = db.scalar(select(Verification).where(Verification.snapshot_id == snapshot.id,
        Verification.source_id == snapshot.source_id, Verification.query_key == snapshot.query_key,
        Verification.status.in_(['ok', 'not_modified']), Verification.verified_at <= asof)
        .order_by(Verification.verified_at, Verification.id).limit(1))
    members = [(index, item) for index, item in enumerate(snapshot.parsed_variants)
               if isinstance(item, dict) and item.get('id') == variant_id]
    refs = [_reference('tire_change', fact.id, variant_id, revision=fact.version, snapshot=snapshot.id,
        source=snapshot.source_id, url=snapshot.source_url,
        verifications=[verification.id] if verification else [], fingerprint=snapshot.raw_hash,
        contract=snapshot.identity_contract_version)]
    if len(members) != 1:
        return invalid, refs
    index, member = members[0]
    try:
        parsed = VariantInput.model_validate({key: value for key, value in member.items()
                                              if key in VariantInput.model_fields})
        if snapshot.identity_contract_version == IDENTITY_CONTRACT_VERSION:
            identity, (key, status) = parsed.identity(), parsed.identity_key(snapshot.source_id, snapshot.query_key, index)
        elif snapshot.identity_contract_version in (None, 'variant-identity@1'):
            identity, (key, status) = parsed.legacy_identity(), parsed.legacy_identity_key(snapshot.source_id, snapshot.query_key, index)
        else:
            return invalid, refs
    except (ValueError, TypeError):
        return invalid, refs
    archived_fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == variant_id,
        FactVersion.source_id == snapshot.source_id, FactVersion.version == member.get('fact_version')))
    archived_valid = (archived_fact is not None and archived_fact.facts_hash == digest(archived_fact.facts)
                      == digest(business_facts(parsed.facts)))
    version_valid = (fact.version == member.get('fact_version') or
        reconciliation and archived_valid and fact.snapshot_id == snapshot.id
        and fact.version > archived_fact.version and utc(fact.observed_at) >= utc(snapshot.observed_at))
    valid = (verification is not None and archived_valid and version_valid
        and hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest() == snapshot.raw_hash
        and key == member.get('identity_key') and status == member.get('identity_status')
        and fact.variant_id == variant_id and fact.source_id == snapshot.source_id
        and digest(fact.facts) == fact.facts_hash == digest(business_facts(parsed.facts)))
    return {'identity': identity, 'facts': deepcopy(fact.facts), 'evidence_valid': valid,
            'identity_key': key, 'identity_status': status,
            'identity_contract_version': snapshot.identity_contract_version,
            'snapshot_id': snapshot.id, 'fact_version_id': fact.id, 'fact_version': fact.version,
            'facts_hash': fact.facts_hash, 'snapshot_member_hash': digest(member),
            'snapshot_member_fact_version': member.get('fact_version'),
            'structured_locator': f'/parsed_variants/{index}'}, refs


def _vehicle_side(db, snapshot, asof):
    from .vehicles import VehicleVerification, fitment_fact_hash
    if snapshot is None:
        return {'evidence_valid': False}, []
    verification = db.scalar(select(VehicleVerification).where(VehicleVerification.snapshot_id == snapshot.id,
        VehicleVerification.vehicle_id == snapshot.vehicle_id, VehicleVerification.verified_at <= asof)
        .order_by(VehicleVerification.verified_at, VehicleVerification.id).limit(1))
    binary = snapshot.body_encoding == 'binary'
    from .vehicle_raw import FIRST_GENERATION_ID, SOURCE_ID, checked_vehicle_parse_provenance
    if binary or (snapshot.source_id == SOURCE_ID and snapshot.vehicle_id == FIRST_GENERATION_ID):
        checked_vehicle_parse_provenance(db, snapshot)
    try:
        valid = (verification is not None and snapshot.payload['vehicle']['id'] == snapshot.vehicle_id
                 and fitment_fact_hash(snapshot.payload) == snapshot.fact_hash
                 and (binary or hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest() == snapshot.raw_hash))
    except (KeyError, ValueError, TypeError):
        valid = False
    return {**deepcopy(snapshot.payload), 'evidence_valid': valid}, [_reference('vehicle_snapshot',
        snapshot.id, snapshot.vehicle_id, revision=snapshot.fact_version, snapshot=snapshot.id,
        source=snapshot.source_id, url=snapshot.source_url,
        verifications=[verification.id] if verification else [], fingerprint=snapshot.raw_hash)]


def _relation_side(db, row, asof):
    from .vehicles import VehicleSnapshot
    selected = row.selection
    fact = db.get(FactVersion, selected.get('fact_version_id'))
    tire, tire_refs = _tire_side(db, selected.get('tire_snapshot_id'), selected.get('variant_id'), fact, asof)
    vehicle_snapshot = db.get(VehicleSnapshot, selected.get('vehicle_snapshot_id'))
    vehicle, vehicle_refs = _vehicle_side(db, vehicle_snapshot, asof)
    fits = [fit for fit in vehicle.get('fitments', []) if fit.get('id') == selected.get('wheel_option_id')
            and fit.get('trim_id') == selected.get('trim_id')]
    valid = (tire['evidence_valid'] and vehicle.get('evidence_valid') and len(fits) == 1
        and selected.get('vehicle_id') == vehicle.get('vehicle', {}).get('id')
        and selected.get('axle') in ('front', 'rear')
        and row.binding_hash == digest(row.binding)
        and row.tire_evidence.get('identity') == tire.get('identity')
        and row.tire_evidence.get('facts_hash') == tire.get('facts_hash')
        and row.vehicle_evidence.get('fact_hash') == (vehicle_snapshot.fact_hash if vehicle_snapshot else None)
        and row.vehicle_evidence.get('requirements') == (fits[0].get(selected.get('axle')) if fits else None))
    side = {'review_state': row.review_state, 'selection': deepcopy(selected),
            'vehicle_evidence': deepcopy(row.vehicle_evidence), 'tire_evidence': deepcopy(row.tire_evidence),
            'binding': deepcopy(row.binding), 'evidence_valid': bool(valid)}
    return side, [_reference('fitment_relation_revision', row.id, row.relation_id, revision=row.revision,
                    fingerprint=row.binding_hash), *vehicle_refs, *tire_refs]


def _catalog_memberships(db, variant_id, asof, override=None):
    """Use the review binding's complete accepted history, including pre-017.

    Transport re-verification does not change a transition revision. A catalog
    producer supplies its exact predecessor instead of hiding the flushed row
    with timestamp arithmetic. New ledger revision numbers cannot stand in for
    this history because migration deliberately does not backfill old rows.
    """
    accepted = (Verification.snapshot_id == Snapshot.id,
        Verification.source_id == Snapshot.source_id, Verification.query_key == Snapshot.query_key,
        Verification.status.in_(['ok', 'not_modified']), Verification.verified_at <= asof)
    scopes = set(db.execute(select(Snapshot.source_id, Snapshot.query_key).join(Verification,
        Verification.snapshot_id == Snapshot.id).where(*accepted,
        cast(Snapshot.parsed_variants, Text).contains(variant_id, autoescape=True)).distinct()).all())
    if override:
        scopes.add((override['source_id'], override['query_key']))
    memberships = []
    for source_id, query_key in sorted(scopes):
        query = select(Snapshot, Verification).join(Verification, Verification.snapshot_id == Snapshot.id).where(
            *accepted, Verification.source_id == source_id, Verification.query_key == query_key)
        controlled = override and (source_id, query_key) == (override['source_id'], override['query_key'])
        if controlled:
            previous = db.get(Verification, override['previous_verification_id']) if override['previous_verification_id'] else None
            if previous:
                query = query.where(Verification.id != override['verification_id'], or_(
                    Verification.verified_at < previous.verified_at,
                    (Verification.verified_at == previous.verified_at) & (Verification.id <= previous.id)))
                history = db.execute(query.order_by(Verification.verified_at, Verification.id)).all()
            else:
                history = []
            if override['include_current']:
                current = db.get(Verification, override['verification_id'])
                history.append((db.get(Snapshot, current.snapshot_id), current))
        else:
            history = db.execute(query.order_by(Verification.verified_at, Verification.id)).all()
        present, transition_revision, ever_present = None, 0, False
        for snapshot, verification in history:
            if (snapshot.source_id != source_id or snapshot.query_key != query_key
                    or verification.source_id != source_id or verification.query_key != query_key
                    or hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest() != snapshot.raw_hash):
                return None
            members = [item for item in snapshot.parsed_variants
                       if isinstance(item, dict) and item.get('id') == variant_id]
            if len(members) > 1:
                return None
            next_present = bool(members)
            if present != next_present:
                transition_revision += 1
            present = next_present
            ever_present |= present
        if ever_present:
            memberships.append({'source_id': source_id, 'query_key': query_key,
                                'present': present, 'transition_revision': transition_revision})
    return memberships


def _reviewed_contexts(db, side, domain, subject_id, asof, *, lifecycle_override=None, resolution_override=None,
                       catalog_override=None):
    """Freeze an actual reviewed chain as of the event, never a size/name join.

    A review proves the exact identity and axle, not perpetual fact equality.
    Non-fitment facts (UTQG, tread depth) may change while identity and the
    vehicle's reviewed requirement stay equal. The fresh facts remain explicit.
    """
    from .fitment_relation_models import FitmentRelationRevision
    from .vehicles import VehicleSnapshot, VehicleVerification
    from .db import VariantLifecycleEvent
    from .identity_models import IdentityRevision
    def same_vehicle_scope(payload, selected, evidence):
        vehicle = payload.get('vehicle', {})
        recorded = evidence.get('vehicle', {})
        if any(vehicle.get(key) != recorded.get(key) for key in
               ('id', 'generation', 'model_year', 'region', 'source_vehicle_id')):
            return False
        trims = [trim for trim in payload.get('trims', []) if trim.get('id') == selected['trim_id']]
        fits = [fit for fit in payload.get('fitments', []) if fit.get('id') == selected['wheel_option_id']
                and fit.get('trim_id') == selected['trim_id']]
        return (len(trims) == len(fits) == 1
                and trims[0].get('model_year') == evidence.get('trim', {}).get('model_year')
                and fits[0].get(selected['axle']) == evidence.get('requirements')
                and all(fits[0].get(key) == evidence.get('wheel', {}).get(key)
                        for key in ('availability', 'wheel_diameter_inches', 'constraints')))
    heads = select(FitmentRelationRevision.relation_id,
        func.max(FitmentRelationRevision.revision).label('revision')).where(
        FitmentRelationRevision.created_at <= asof).group_by(FitmentRelationRevision.relation_id).subquery()
    scope_field = 'variant_id' if domain == 'tire' else 'vehicle_id'
    query = select(FitmentRelationRevision).join(heads,
        (heads.c.relation_id == FitmentRelationRevision.relation_id) &
        (heads.c.revision == FitmentRelationRevision.revision)).where(
        FitmentRelationRevision.selection[scope_field].as_string() == subject_id,
        FitmentRelationRevision.review_state == 'reviewed')
    rows = db.scalars(query.order_by(FitmentRelationRevision.relation_id)).all()
    contexts, refs = [], []
    catalog_states = {}
    for row in rows:
        selected = row.selection
        lifecycle = db.scalar(select(VariantLifecycleEvent).where(
            VariantLifecycleEvent.variant_id == selected.get('variant_id'), VariantLifecycleEvent.created_at <= asof)
            .order_by(desc(VariantLifecycleEvent.revision)).limit(1))
        resolution = db.scalar(select(IdentityRevision).where(
            IdentityRevision.variant_id == selected.get('variant_id'), IdentityRevision.created_at <= asof)
            .order_by(desc(IdentityRevision.revision)).limit(1))
        lifecycle_state = lifecycle_override if domain == 'tire' and lifecycle_override is not None else {
            'revision': lifecycle.revision if lifecycle else 0, 'state': lifecycle.after_state if lifecycle else 'active'}
        resolution_state = resolution_override if domain == 'tire' and resolution_override is not None else {
            'revision': resolution.revision if resolution else 0,
            'state': 'cleared' if resolution and resolution.action == 'clear' else 'blocked' if resolution else 'independent'}
        bound = row.binding.get('tire', {})
        variant_id = selected.get('variant_id')
        if variant_id not in catalog_states:
            catalog_states[variant_id] = _catalog_memberships(db, variant_id, asof,
                catalog_override if domain == 'tire' else None)
        catalogs = catalog_states[variant_id]
        if (lifecycle_state['state'] != 'active' or resolution_state['state'] == 'blocked'
                or any(bound.get('lifecycle', {}).get(key) != lifecycle_state[key] for key in ('revision', 'state'))
                or any(bound.get('identity_resolution', {}).get(key) != resolution_state[key] for key in ('revision', 'state'))
                or catalogs is None or bound.get('catalogs') != catalogs):
            continue
        frozen, frozen_refs = _relation_side(db, row, asof)
        if not frozen['evidence_valid']:
            continue
        if domain == 'tire':
            if side.get('identity') != row.tire_evidence.get('identity'):
                continue
            latest_vehicle = db.scalar(select(VehicleSnapshot).join(VehicleVerification,
                VehicleVerification.snapshot_id == VehicleSnapshot.id).where(
                VehicleSnapshot.vehicle_id == selected['vehicle_id'], VehicleVerification.verified_at <= asof)
                .order_by(desc(VehicleVerification.verified_at), desc(VehicleVerification.id)).limit(1))
            current, current_refs = _vehicle_side(db, latest_vehicle, asof)
            if (not current.get('evidence_valid') or not same_vehicle_scope(current, selected, row.vehicle_evidence)):
                continue
            identity, facts = side['identity'], side['facts']
            frozen_refs.extend(current_refs)
        else:
            if not same_vehicle_scope(side, selected, row.vehicle_evidence):
                continue
            identity, facts = row.tire_evidence['identity'], row.tire_evidence['facts']
        contexts.append({'identity': deepcopy(identity), 'facts': deepcopy(facts),
            'vehicle_scope': {key: selected[key] for key in ('vehicle_id', 'trim_id', 'wheel_option_id', 'axle')},
            'reviewed_relation': True, 'evidence_valid': True, 'relation_id': row.relation_id,
            'relation_revision': row.revision, 'binding_hash': row.binding_hash,
            'catalogs': deepcopy(catalogs),
            'current_vehicle_snapshot_id': latest_vehicle.id if domain == 'tire' else None})
        refs.extend(frozen_refs)
    return contexts, refs


def _event(domain, row, action, state, revision, subject_id, label, before, after, refs, observed_at):
    event_id = digest({'schema': 'interest-event@1', 'domain': domain, 'origin_id': row.id})
    unique_refs = {digest(ref): ref for ref in refs}
    # Bookkeeping is frozen but is not a business changed-field selector.
    excluded = {'reviewed_contexts', 'evidence_valid', 'snapshot_id', 'fact_version_id', 'fact_version',
                'facts_hash', 'snapshot_member_hash', 'snapshot_member_fact_version', 'structured_locator'}
    def business(side):
        return {key: value for key, value in (side or {}).items() if key not in excluded}
    payload = {'schema': 'interest-event@1', 'id': event_id, 'domain': domain, 'action': action,
        'state': state, 'revision': revision, 'observed_at': timestamp(observed_at),
        'subject_id': subject_id, 'label': label, 'before': before, 'after': after,
        'changed_paths': changed_paths(business(before), business(after)),
        'evidence': [unique_refs[key] for key in sorted(unique_refs)]}
    payload['event_hash'] = digest(payload)
    return payload


def freeze_tire(db, row):
    fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == row.variant_id,
        FactVersion.source_id == row.source_id, FactVersion.snapshot_id == row.snapshot_id,
        FactVersion.observed_at == row.observed_at).order_by(desc(FactVersion.version)).limit(1))
    after, refs = _tire_side(db, row.snapshot_id, row.variant_id, fact, row.observed_at, reconciliation=True)
    previous = db.scalar(select(FactVersion).where(FactVersion.variant_id == row.variant_id,
        FactVersion.source_id == row.source_id, FactVersion.version == fact.version - 1)) if fact else None
    before = None
    if row.previous_snapshot_id:
        before, more = _tire_side(db, row.previous_snapshot_id, row.variant_id, previous, row.observed_at, reconciliation=True)
        refs.extend(more)
    for side in (before, after):
        if side and side.get('evidence_valid'):
            side['reviewed_contexts'], more = _reviewed_contexts(db, side, 'tire', row.variant_id, row.observed_at)
            refs.extend(more)
    # The primary reference is the change, while facts retain their exact ids in
    # before/after and additional provenance. Reopening uses the raw snapshot.
    for ref in refs:
        if ref['kind'] == 'tire_change' and ref['snapshot_id'] == row.snapshot_id:
            ref.update(record_id=row.id, previous_snapshot_id=row.previous_snapshot_id)
    identity = after.get('identity') or {}
    label = ' '.join(str(identity.get(key) or '') for key in ('brand', 'model', 'size')).strip() or row.variant_id
    return _event('tire', row, row.kind, 'accepted', fact.version if fact else 0,
                  row.variant_id, label, before, after, refs, row.observed_at)


def freeze_test(db, row):
    from .test_events import EventPayload, TireTestRevision
    def side(revision):
        try:
            valid = EventPayload.model_validate(revision.payload).model_dump(mode='json') == revision.payload
        except (ValueError, TypeError):
            valid = False
        return {'state': revision.state, 'event': deepcopy(revision.payload),
                'evidence_valid': valid and digest(revision.payload) == revision.fingerprint}
    old = db.scalar(select(TireTestRevision).where(TireTestRevision.event_id == row.event_id,
                                                TireTestRevision.revision == row.revision - 1))
    refs = [_reference('test_revision', item.id, item.event_id, revision=item.revision,
        url=item.payload.get('source_url'), fingerprint=item.fingerprint) for item in (old, row) if item]
    return _event('test_event', row, row.action, row.state, row.revision, row.event_id,
        row.payload.get('title', row.event_id), side(old) if old else None, side(row), refs, row.created_at)


def freeze_vehicle(db, row):
    from .vehicles import VehicleSnapshot, VehicleVerification
    old = db.scalar(select(VehicleSnapshot).where(VehicleSnapshot.vehicle_id == row.vehicle_id,
        VehicleSnapshot.fact_version == row.fact_version - 1, select(VehicleVerification.id).where(
        VehicleVerification.snapshot_id == VehicleSnapshot.id).exists())
        .order_by(VehicleSnapshot.observed_at, VehicleSnapshot.id).limit(1))
    after, refs = _vehicle_side(db, row, row.observed_at)
    before = None
    if old:
        before, more = _vehicle_side(db, old, row.observed_at)
        refs.extend(more)
    for side in (before, after):
        if side and side.get('evidence_valid'):
            side['reviewed_contexts'], more = _reviewed_contexts(db, side, 'vehicle', row.vehicle_id, row.observed_at)
            refs.extend(more)
    return _event('vehicle', row, 'vehicle_observed' if row.fact_version == 1 else 'vehicle_facts_changed',
        'accepted', row.fact_version, row.vehicle_id, row.payload.get('vehicle', {}).get('model', row.vehicle_id),
        before, after, refs, row.observed_at)


def freeze_fitment(db, row):
    from .fitment_relation_models import FitmentRelationRevision
    old = db.scalar(select(FitmentRelationRevision).where(FitmentRelationRevision.relation_id == row.relation_id,
                                                        FitmentRelationRevision.revision == row.revision - 1))
    after, refs = _relation_side(db, row, row.created_at)
    before = None
    if old:
        before, more = _relation_side(db, old, row.created_at)
        refs.extend(more)
    tire = after.get('tire_evidence', {}).get('identity', {})
    label = ' '.join(str(tire.get(key) or '') for key in ('brand', 'model', 'size')).strip() or row.relation_id
    return _event('fitment', row, row.action, row.review_state, row.revision, row.relation_id,
                  label, before, after, refs, row.created_at)


def freeze(db, domain, row):
    from .interest_governance import FREEZERS
    return {'tire': freeze_tire, 'test_event': freeze_test,
            'vehicle': freeze_vehicle, 'fitment': freeze_fitment, **FREEZERS}[domain](db, row)


def publish(db, domain, row, *, allow_indeterminate=False):
    """Caller holds ingestion lock. No commit, backfill, retry or swallowed error."""
    existing = db.scalar(select(InterestEvent).where(InterestEvent.domain == domain, InterestEvent.origin_id == row.id))
    if existing:
        return existing
    payload = freeze(db, domain, row)
    if not allow_indeterminate and not payload['after'].get('evidence_valid'):
        raise InterestEvidenceError('new_interest_event_evidence_invalid:' + domain + ':' + row.id)
    event = InterestEvent(id=payload['id'], domain=domain, origin_id=row.id,
        observed_at=row.observed_at if hasattr(row, 'observed_at') else row.created_at,
        event_hash=payload['event_hash'], payload=payload)
    db.add(event)
    db.flush()
    heads = select(InterestRevision.interest_id, func.max(InterestRevision.revision).label('revision')).group_by(
        InterestRevision.interest_id).subquery()
    rows = db.execute(select(Interest, InterestRevision).join(InterestRevision,
        InterestRevision.interest_id == Interest.id).join(heads,
        (heads.c.interest_id == Interest.id) & (heads.c.revision == InterestRevision.revision))
        .where(InterestRevision.enabled.is_(True), InterestRevision.archived.is_(False),
               InterestRevision.created_at <= event.observed_at, Interest.created_at <= event.observed_at)).all()
    for interest, revision in rows:
        result = match_event(payload, {'conditions': revision.conditions,
                                      'metric_keys': revision.metric_keys, 'changed_fields': revision.changed_fields})
        if result['state'] == 'matched':
            from .db import uid, utcnow
            notification = InterestNotification(id=uid(), session_id=interest.session_id, interest_id=interest.id,
                interest_revision_id=revision.id, event_id=event.id, match=result, delivered_at=utcnow())
            db.add(notification)
            from .webhook_delivery import enqueue_notification
            enqueue_notification(db, 'interest', notification, event)
    db.flush()
    return event


def historical_candidate_query():
    """The shared nine-domain origin set; construction performs no I/O."""
    from .test_events import TireTestRevision
    from .vehicles import VehicleSnapshot, VehicleVerification
    from .fitment_relation_models import FitmentRelationRevision
    from .db import ManualFactRevision, VariantLifecycleEvent
    from .identity_models import IdentityRevision
    from .interest_catalog_models import TireCatalogRevision
    from .interest_applicability_models import TireCurationApplicabilityEvent
    vehicle_heads = select(VehicleSnapshot.id, func.row_number().over(
        partition_by=(VehicleSnapshot.vehicle_id, VehicleSnapshot.fact_version),
        order_by=(VehicleSnapshot.observed_at, VehicleSnapshot.id)).label('n')).where(
        select(VehicleVerification.id).where(VehicleVerification.snapshot_id == VehicleSnapshot.id).exists()).subquery()
    candidates = union_all(
        select(literal('tire').label('domain'), ChangeEvent.id.label('origin_id'), ChangeEvent.observed_at.label('at')),
        select(literal('test_event'), TireTestRevision.id, TireTestRevision.created_at),
        select(literal('vehicle'), VehicleSnapshot.id, VehicleSnapshot.observed_at).join(vehicle_heads,
            (vehicle_heads.c.id == VehicleSnapshot.id) & (vehicle_heads.c.n == 1)),
        select(literal('fitment'), FitmentRelationRevision.id, FitmentRelationRevision.created_at),
        select(literal('tire_curation'), ManualFactRevision.id, ManualFactRevision.created_at),
        select(literal('tire_lifecycle'), VariantLifecycleEvent.id, VariantLifecycleEvent.created_at),
        select(literal('tire_identity'), IdentityRevision.id, IdentityRevision.created_at),
        select(literal('tire_catalog'), TireCatalogRevision.id, TireCatalogRevision.created_at),
        select(literal('tire_curation_validity'), TireCurationApplicabilityEvent.id,
               TireCurationApplicabilityEvent.created_at)).subquery()
    return select(candidates).order_by(candidates.c.at.desc(), candidates.c.domain, candidates.c.origin_id)


def reconstruct_candidate(db, domain, origin_id, *, verify_stored=False):
    """Read one frozen event or reconstruct an old origin, without backfilling."""
    from .test_events import TireTestRevision
    from .vehicles import VehicleSnapshot
    from .fitment_relation_models import FitmentRelationRevision
    from .db import ManualFactRevision, VariantLifecycleEvent
    from .identity_models import IdentityRevision
    from .interest_catalog_models import TireCatalogRevision
    from .interest_applicability_models import TireCurationApplicabilityEvent
    models = {'tire': ChangeEvent, 'test_event': TireTestRevision, 'vehicle': VehicleSnapshot,
              'fitment': FitmentRelationRevision, 'tire_curation': ManualFactRevision,
              'tire_lifecycle': VariantLifecycleEvent, 'tire_identity': IdentityRevision, 'tire_catalog': TireCatalogRevision,
              'tire_curation_validity': TireCurationApplicabilityEvent}
    stored = db.scalar(select(InterestEvent).where(InterestEvent.domain == domain, InterestEvent.origin_id == origin_id))
    if stored:
        payload = deepcopy(stored.payload)
        if verify_stored:
            expected_id = digest({'schema': 'interest-event@1', 'domain': domain, 'origin_id': origin_id})
            if (not isinstance(payload, dict) or stored.id != expected_id or payload.get('id') != expected_id
                    or payload.get('schema') != 'interest-event@1' or payload.get('domain') != domain
                    or payload.get('event_hash') != stored.event_hash
                    or digest({k: v for k, v in payload.items() if k != 'event_hash'}) != stored.event_hash):
                raise InterestEvidenceError('stored_interest_event_binding_invalid')
        return payload
    return freeze(db, domain, db.get(models[domain], origin_id))


def historical_candidates(db, offset, limit):
    """Pagination bounds candidates scanned; reconstructing old rows is read-only."""
    origins = db.execute(historical_candidate_query().offset(offset).limit(limit + 1)).all()
    results = [reconstruct_candidate(db, item.domain, item.origin_id) for item in origins[:limit]]
    return results, len(origins) > limit
