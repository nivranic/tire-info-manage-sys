"""Read-only, caller-scoped field candidates over accepted evidence and v2 identities."""
from copy import deepcopy
import hashlib
import re

from fastapi import HTTPException
from sqlalchemy import desc, func, select

from .db import FactVersion, QueryRun, Snapshot, TireVariant, VariantLifecycleEvent, Verification
from .domain import VariantInput, digest, stable_json
from .field_authority import canonical_field, known_values_differ, policy_catalog, resolve_fields
from .identity_contract import contract_context, contract_metadata, schema_version
from .service import business_facts, timestamp


def _timestamp(value):
    return value if isinstance(value, str) else timestamp(value)


def latest_tire_heads(db, *, source_ids=None):
    """Rank entire query resources before membership filtering, including removals."""
    statement = select(Verification.id, Verification.snapshot_id, Verification.source_id,
        Verification.query_key, Verification.verified_at, func.row_number().over(
            partition_by=(Verification.source_id, Verification.query_key),
            order_by=(Verification.verified_at.desc(), Verification.id.desc())).label('n'))
    if source_ids is not None:
        statement = statement.where(Verification.source_id.in_(source_ids))
    ranks = statement.subquery()
    return [dict(row) for row in db.execute(select(ranks).where(ranks.c.n == 1)).mappings()]


def source_catalog(registry):
    if registry is None:
        from .adapters import registry
    return {row['id']: row for row in registry.sources()}


def _snapshots(db, ids, *, include_body=True):
    if not ids:
        return {}
    columns = (Snapshot.id, Snapshot.source_id, Snapshot.query_key, Snapshot.source_url,
        Snapshot.raw_hash, Snapshot.parser_version, Snapshot.parser_identity,
        Snapshot.identity_contract_version, Snapshot.observed_at, Snapshot.parsed_variants)
    if include_body:
        columns = (*columns, Snapshot.body)
    return {row['id']: dict(row) for row in db.execute(select(*columns).where(Snapshot.id.in_(ids))).mappings()}


def _verification(db, snapshot):
    row = db.execute(select(Verification.verified_at, QueryRun.query).join(QueryRun, QueryRun.id == Verification.query_id).where(
        Verification.snapshot_id == snapshot['id'], Verification.source_id == snapshot['source_id'],
        Verification.query_key == snapshot['query_key'], QueryRun.source_id == snapshot['source_id'],
        QueryRun.query_key == snapshot['query_key'], Verification.status.in_(['ok', 'not_modified']))
        .order_by(desc(Verification.verified_at), desc(Verification.id)).limit(1)).first()
    return row.verified_at if row is not None and digest(row.query) == snapshot['query_key'] else None


def _model(row):
    return VariantInput.model_validate({key: value for key, value in row.items() if key in VariantInput.model_fields})


def snapshot_field_candidates(db, snapshot_id, variant_id, registry, *, row=None, verified_at=None,
                              identity_match='exact', equivalence_event_id=None, fact_version_id=None, context=None):
    """Project this snapshot only. Never widen a selected source to other sources.

    Snapshot membership and a compatible FactVersion are independent references:
    unchanged facts on a newer page legitimately keep their original fact row.
    context is per-call batching only; callers must not retain it across requests.
    """
    context = context if context is not None else {}
    snapshots = context.setdefault('snapshots', {})
    if snapshot_id not in snapshots:
        snapshots.update(_snapshots(db, [snapshot_id]))
    snapshot = snapshots.get(snapshot_id)
    if snapshot is None:
        raise HTTPException(404, '未找到所选正式快照')
    members = [(index, member) for index, member in enumerate(snapshot['parsed_variants'])
               if isinstance(member, dict) and member.get('id') == variant_id]
    if row is None:
        if not members:
            raise HTTPException(422, '所选快照不包含此精确版本')
        row = members[0][1]
    row = deepcopy(row)
    facts = row.get('facts') if isinstance(row.get('facts'), dict) else {}
    missing = []
    if len(members) != 1:
        missing.append('snapshot_member_missing_or_ambiguous')
    else:
        try:
            if (_model(row).identity() != _model(members[0][1]).identity()
                    or digest(business_facts(facts)) != digest(business_facts(members[0][1].get('facts', {})))):
                missing.append('snapshot_member_value_mismatch')
        except (ValueError, TypeError, KeyError):
            missing.append('snapshot_member_invalid')
    if 'sources' not in context:
        context['sources'] = source_catalog(registry)
    sources = context['sources']
    source = sources.get(snapshot['source_id'], {})
    verification_key = ('verification', snapshot_id)
    if verification_key not in context:
        context[verification_key] = _verification(db, snapshot)
    accepted_at = context[verification_key]
    if accepted_at is None:
        missing.append('accepted_verification_missing')
    verified_at = verified_at or accepted_at
    contracts = context.get('contracts')
    if contracts is None or variant_id not in contracts['variants']:
        contracts = contract_context(db, [variant_id])
    contract = contract_metadata(db, variant_id, context=contracts)
    lifecycle_key = ('lifecycle', variant_id)
    if lifecycle_key not in context:
        context[lifecycle_key] = db.scalar(select(VariantLifecycleEvent.after_state).where(
            VariantLifecycleEvent.variant_id == variant_id).order_by(desc(VariantLifecycleEvent.revision)).limit(1))
    if context[lifecycle_key] == 'revoked':
        missing.append('variant_revoked')
    effective_match = identity_match
    if contract['state'] != 'current':
        missing.append('identity_contract_review_required')
        effective_match = 'unverified'
    try:
        parsed = _model(row)
        if contract['state'] == 'current':
            if stable_json(parsed.identity()) != stable_json(contract['current_identity']):
                missing.append('identity_snapshot_mismatch')
                effective_match = 'mismatch'
            elif snapshot['identity_contract_version'] == schema_version():
                if len(members) != 1 or members[0][1].get('identity_key') != contract['current_key']:
                    missing.append('identity_snapshot_key_mismatch')
                    effective_match = 'mismatch'
            elif snapshot['identity_contract_version'] is None:
                stored = contracts['variants'][variant_id]
                key, status = parsed.legacy_identity_key(snapshot['source_id'], snapshot['query_key'], members[0][0])
                if (stable_json(parsed.legacy_identity()) != stable_json(stored.identity)
                        or key != stored.identity_key or status != stored.identity_status
                        or members[0][1].get('identity_key') != key):
                    missing.append('legacy_identity_snapshot_mismatch')
                    effective_match = 'mismatch'
            else:
                missing.append('identity_contract_version_unknown')
                effective_match = 'unverified'
    except (ValueError, TypeError, KeyError):
        missing.append('variant_input_invalid')
        effective_match = 'unverified'
    if identity_match == 'reviewed_merge' and not equivalence_event_id:
        missing.append('equivalence_event_missing')
        effective_match = 'unverified'
    declared_version = row.get('fact_version') if type(row.get('fact_version')) is int else None
    fact_key = ('fact', variant_id, snapshot['source_id'], digest(business_facts(facts)),
                fact_version_id, snapshot_id, declared_version)
    if fact_key not in context:
        statement = select(FactVersion).where(FactVersion.variant_id == variant_id,
            FactVersion.source_id == snapshot['source_id'], FactVersion.facts_hash == fact_key[3])
        if fact_version_id is not None:
            statement = statement.where(FactVersion.id == fact_version_id)
        elif declared_version is not None:
            statement = statement.where(FactVersion.version == declared_version)
        else:
            statement = statement.where(FactVersion.observed_at <= snapshot['observed_at'])
        context[fact_key] = db.scalar(statement.order_by(desc(FactVersion.snapshot_id == snapshot_id),
            desc(FactVersion.version)).limit(1))
    fact = context[fact_key]
    if fact is None or digest(fact.facts) != fact.facts_hash:
        missing.append('compatible_fact_version_missing')
    if not re.fullmatch(r'[0-9a-f]{64}', snapshot['raw_hash'] or ''):
        missing.append('raw_hash_missing')
    raw_key = ('raw_integrity', snapshot_id)
    if raw_key not in context:
        context[raw_key] = (isinstance(snapshot['body'], str) and bool(snapshot['body'])
            and hashlib.sha256(snapshot['body'].encode('utf-8')).hexdigest() == snapshot['raw_hash'])
    if not context[raw_key]:
        missing.append('raw_integrity_failed')
    if not snapshot['source_url'] or not snapshot['parser_version']:
        missing.append('source_provenance_missing')
    if 'definitions' not in context:
        context['definitions'] = {item['field']: item for item in policy_catalog()['fields']}
    definitions = context['definitions']
    values = {key: value for key, value in facts.items() if key in definitions}
    values.update({key: row[key] for key in VariantInput.model_fields if key in definitions and key in row})
    spans = facts.get('evidence_spans') if isinstance(facts.get('evidence_spans'), dict) else {}
    conflicts = facts.get('source_field_conflicts') if isinstance(facts.get('source_field_conflicts'), list) else []
    conflicting = {canonical_field(str(item['field']).removeprefix('facts.').removeprefix('identity.'))
                   for item in conflicts if isinstance(item, dict) and isinstance(item.get('field'), str)}
    alias_values = {}
    for field, value in values.items():
        alias_values.setdefault(canonical_field(field), []).append(value)
    conflicting.update(field for field, group in alias_values.items() if known_values_differ(group))
    from .curation import FIELD_CATALOG
    base = {'variant_id': variant_id, 'source_id': snapshot['source_id'],
        'source_name': source.get('name', snapshot['source_id']), 'source_class': source.get('source_class', 'unclassified'),
        'source_region': source.get('region'), 'snapshot_id': snapshot_id, 'fact_version_id': fact.id if fact else None,
        'source_url': snapshot['source_url'], 'raw_hash': snapshot['raw_hash'], 'parser_version': snapshot['parser_version'],
        'observed_at': timestamp(snapshot['observed_at']), 'verified_at': _timestamp(verified_at),
        'published_at': facts.get('source_updated_at') if isinstance(facts.get('source_updated_at'), str) else None,
        'identity_match': effective_match,
        'region_match': 'exact' if contract['state'] == 'current' and row.get('region') == contract['current_identity'].get('region') else 'unverified',
        'evidence_valid': not missing, 'missing_evidence': sorted(set(missing))}
    if equivalence_event_id is not None:
        base['equivalence_event_id'] = equivalence_event_id
    candidates = []

    def add(field, value, *, source_field=None, locator=None, ordinal=0):
        source_field = source_field if isinstance(source_field, str) and source_field.strip() else field
        if locator is None:
            locator = spans.get(field) or spans.get('facts.' + field) or spans.get('identity.' + field)
        locator = locator if isinstance(locator, str) and locator.strip() else None
        definition = definitions[field]
        candidate = {**base, 'field': definition['canonical_field'], 'source_field': source_field,
            'present': True, 'value': deepcopy(value), 'evidence_locator': locator,
            'source_conflicted': definition['canonical_field'] in conflicting,
            'sku_specific': bool(row.get('manufacturer_product_code') and locator),
            'curation_field': field if field in FIELD_CATALOG and not definition['identity_bound'] else None}
        candidate['id'] = digest({'snapshot_id': snapshot_id, 'variant_id': variant_id,
            'fact_version_id': candidate['fact_version_id'], 'field': candidate['field'], 'source_field': source_field,
            'ordinal': ordinal, 'value': value, 'equivalence_event_id': equivalence_event_id})
        candidates.append(candidate)

    for field, value in sorted(values.items()):
        add(field, value)
    for index, conflict in enumerate(conflicts):
        if not isinstance(conflict, dict) or not isinstance(conflict.get('field'), str):
            continue
        field = conflict['field'].removeprefix('facts.').removeprefix('identity.')
        if field not in definitions or not isinstance(conflict.get('values'), list):
            continue
        for position, item in enumerate(conflict['values']):
            if isinstance(item, dict) and 'value' in item:
                add(field, item['value'], source_field=item.get('source_field', field),
                    locator=item.get('locator') or spans.get('facts.source_field_conflicts'), ordinal=1 + index * 100 + position)
    return candidates


def accepted_variant_candidates(db, registry, variant_ids, *, source_ids=None, context=None):
    """Current query snapshots; a 304 cannot evict another query's newer content."""
    ids = set(variant_ids)
    context = context if context is not None else {}
    if 'sources' not in context:
        context['sources'] = source_catalog(registry)
    if 'contracts' not in context:
        context['contracts'] = contract_context(db, ids)
    heads = latest_tire_heads(db, source_ids=source_ids)
    snapshots = _snapshots(db, {head['snapshot_id'] for head in heads}, include_body=False)
    context.setdefault('snapshots', {}).update(snapshots)
    selected = {}
    for head in sorted(heads, key=lambda item: (item['verified_at'], item['id']), reverse=True):
        snapshot = snapshots.get(head['snapshot_id'])
        if snapshot is None:
            continue
        for row in snapshot['parsed_variants']:
            if isinstance(row, dict) and row.get('id') in ids:
                selected.setdefault((row['id'], snapshot['id']), (row, head))
    result = {variant_id: [] for variant_id in ids}
    related_snapshots = {head['snapshot_id'] for _row, head in selected.values()}
    if related_snapshots:
        for snapshot_id, body in db.execute(select(Snapshot.id, Snapshot.body).where(Snapshot.id.in_(related_snapshots))):
            snapshots[snapshot_id]['body'] = body
    for (variant_id, _snapshot_id), (row, head) in selected.items():
        result[variant_id].extend(snapshot_field_candidates(db, head['snapshot_id'], variant_id, registry,
            row=row, verified_at=head['verified_at'], context=context))
    return result


def variant_field_resolution(db, registry, variant_id, *, scope='history', source_ids=None, equivalences=None):
    equivalences = equivalences or {}
    candidates = accepted_variant_candidates(db, registry, [variant_id, *equivalences], source_ids=source_ids)
    rows = candidates[variant_id]
    for original_id, event_id in equivalences.items():
        for item in candidates[original_id]:
            item = deepcopy(item)
            if item['identity_match'] == 'exact':
                item['identity_match'] = 'reviewed_merge'
                item['equivalence_event_id'] = event_id
            rows.append(item)
    return resolve_fields(complete_missing_candidates(rows), variant_id=variant_id, scope=scope)


def complete_missing_candidates(candidates):
    """Complete an authorized group of full snapshot projections, not arbitrary facts.

    Each caller must supply the unfiltered outputs of snapshot_field_candidates
    for its chosen observations. Only fields actually present somewhere in this
    group are considered; a missing field is never guessed by the pure engine.
    """
    rows = deepcopy(candidates)
    groups = {}
    fields = {}
    for item in rows:
        key = tuple(item.get(name) for name in ('variant_id', 'source_id', 'snapshot_id',
                                               'fact_version_id', 'equivalence_event_id'))
        groups.setdefault(key, []).append(item)
        fields.setdefault(item['field'], item)
    for key, group in groups.items():
        present_fields = {item['field'] for item in group}
        for field in sorted(fields.keys() - present_fields):
            template = deepcopy(group[0])
            template.update(field=field, source_field=field, present=False, value=None,
                evidence_locator=None, source_conflicted=False, sku_specific=False,
                curation_field=None)
            template['id'] = digest({'observation': key, 'field': field, 'present': False})
            rows.append(template)
    return rows


def resolution_conflicts(resolutions):
    """Compatibility projection for existing comparison consumers, not another scan."""
    return [{'variant_id': resolution['variant_id'], 'field': field['field'],
        'values': [{'source_id': item['source_id'], 'value': item['value'], 'snapshot_id': item['snapshot_id'],
                    'observed_at': item['observed_at'], 'data_state': resolution['data_state']}
                   for item in field['candidates'] if item['present'] and item['value'] is not None],
        'resolution': 'unresolved', 'display_state': field['state']}
        for resolution in resolutions for field in resolution['fields']
        if field['state'] in {'conflict_preferred', 'conflict_tied'}]
