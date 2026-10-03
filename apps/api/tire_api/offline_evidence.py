"""Read-only exact formal evidence projection for portable device packages.

No API self-calls, source refresh, parser or AI execution. User context remains
separate from source facts; selection never infers a tire/vehicle relationship.
"""
from copy import deepcopy
import hashlib

from fastapi import HTTPException
from sqlalchemy import desc, func, select

from .db import GarageRevision, QueryRun, Snapshot, VariantLifecycleEvent, Verification, WatchItem
from .domain import VariantInput, digest, stable_json
from .field_authority import resolve_fields
from .field_evidence import complete_missing_candidates, latest_tire_heads, snapshot_field_candidates
from .identity_contract import contract_metadata
from .recall_evidence import (canonical_recall_facts, load_recall_evidence, recall_boundary_descriptor,
                              recall_policy_descriptor)
from .recall_models import RecallRevision, RecallSnapshot, RecallVerification
from .recall_discovery import (NOTICES as RECALL_SEARCH_NOTICES, RecallSearchQuery, RecallSearchSnapshot,
                               RecallSearchVerification, SearchDiscovery)
from .service import timestamp
from .test_events import EventPayload, TireTestRevision, metadata
from .vehicles import VehicleSnapshot, VehicleVerification, fitment_fact_hash, validate_vehicle_structure


def member_key(reference):
    # A new receipt on identical content is a changed member, not a new entity.
    return digest({key: value for key, value in reference.items() if key != 'verification_id'})


def omission(selector, object_id, reason, blocking=False):
    return {'selector': selector, 'object_id': object_id, 'reason': reason, 'blocking': blocking}


def reason(selector, object_id=None, revision=None, axle=None):
    return {'selector': selector, 'scope': 'local_workspace' if selector == 'garage' else
            'explicit' if selector == 'explicit' else 'current_session',
            'object_id': object_id, 'revision': revision, 'axle': axle}


def check_material(value):
    """Raw/media is not a supported normalized fact, even inside arbitrary JSON."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {'body', 'raw', 'raw_body', 'raw_content', 'html', 'full_text', 'full_html',
                               'full_document', 'image_base64', 'pdf_base64', 'session_cookie',
                               'actor_session_id', 'api_key', 'access_token'}:
                raise HTTPException(422, 'offline_raw_or_secret_material_excluded')
            check_material(item)
    elif isinstance(value, list):
        for item in value:
            check_material(item)
    elif isinstance(value, str) and ('\x00' in value or len(value) > 100000):
        raise HTTPException(422, 'offline_unbounded_material_excluded')


def _source(snapshot, receipt):
    return {'source_id': snapshot.source_id, 'source_url': snapshot.source_url,
            'raw_hash': snapshot.raw_hash, 'parser_version': snapshot.parser_version,
            'parser_identity': deepcopy(snapshot.parser_identity), 'observed_at': timestamp(snapshot.observed_at),
            'verified_at': timestamp(receipt.verified_at), 'verification_id': receipt.id}


def _receipt(db, model, snapshot, reference):
    statement = select(model, QueryRun).join(QueryRun, QueryRun.id == model.query_id).where(
        model.snapshot_id == snapshot.id).order_by(desc(model.verified_at), desc(model.id))
    if reference.get('verification_id'):
        statement = statement.where(model.id == reference['verification_id'])
    pair = db.execute(statement.limit(1)).first()
    if pair is None:
        raise HTTPException(422, 'offline_formal_receipt_missing')
    receipt, run = pair
    if (run.source_id != snapshot.source_id or digest(run.query) != run.query_key
            or receipt.parser_identity != snapshot.parser_identity):
        raise HTTPException(422, 'offline_formal_receipt_mismatch')
    if isinstance(snapshot, Snapshot):
        if (run.query_key != snapshot.query_key or receipt.query_key != snapshot.query_key
                or receipt.source_id != snapshot.source_id or receipt.status not in {'ok', 'not_modified'}):
            raise HTTPException(422, 'offline_formal_receipt_mismatch')
    elif (run.query != {'vehicle_id': snapshot.vehicle_id} or receipt.vehicle_id != snapshot.vehicle_id):
        raise HTTPException(422, 'offline_vehicle_receipt_mismatch')
    if (not snapshot.body or hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest() != snapshot.raw_hash
            or not snapshot.source_url or not snapshot.parser_version):
        raise HTTPException(422, 'offline_raw_integrity_failed')
    return receipt


def _tire_candidates(db, registry, snapshot_id, variant_id, receipt):
    candidates = snapshot_field_candidates(db, snapshot_id, variant_id, registry,
        verified_at=receipt.verified_at, context={('verification', snapshot_id): receipt.verified_at})
    return [{**candidate, 'verification_id': receipt.id} for candidate in candidates]


def _tire_resolution(candidates, variant_id):
    """Preserve separate fixed receipts over an unchanged source observation.

    The shared field engine identifies source observations, not verification
    receipts. Offline scope can explicitly contain both. Bind each candidate
    (including generated missing-field candidates) to its own receipt without
    letting verification time participate in authority/freshness ranking.
    """
    def observation(candidate):
        return tuple(candidate.get(name) for name in ('variant_id', 'source_id', 'snapshot_id',
                                                       'fact_version_id', 'equivalence_event_id'))

    receipts = {}
    for candidate in candidates:
        receipts.setdefault(observation(candidate), {})[candidate['verification_id']] = candidate['verified_at']
    bound = []
    for candidate in complete_missing_candidates(candidates):
        # Shared completion groups by observation. Expand its missing field for
        # every selected receipt of that observation, rather than dropping the
        # second receipt's explicit evidence gap.
        selected = (receipts[observation(candidate)] if not candidate['present'] else
                    {candidate['verification_id']: candidate['verified_at']})
        for verification_id, verified_at in selected.items():
            item = deepcopy(candidate)
            item.update(verification_id=verification_id, verified_at=verified_at,
                id=digest({'contract': 'offline-receipt-candidate@1', 'candidate_id': candidate['id'],
                           'verification_id': verification_id}))
            bound.append(item)
    return resolve_fields(bound, variant_id=variant_id, scope='offline_pack')


def load_recall_search_member(db, reference, session_id):
    """Freeze exactly one owned, formally verified discovery page, never a campaign."""
    snapshot = db.get(RecallSearchSnapshot, reference['snapshot_id'])
    receipt = db.get(RecallSearchVerification, reference['verification_id'])
    run = db.get(QueryRun, receipt.query_id) if receipt is not None else None
    if snapshot is None or receipt is None or run is None:
        raise HTTPException(422, 'offline_recall_search_formal_receipt_missing')
    if run.session_id != session_id:
        raise HTTPException(422, 'offline_recall_search_receipt_owner_mismatch')
    query = snapshot.query
    if (not isinstance(query, dict) or set(query) != {'search', 'offset'}
            or not isinstance(query['offset'], str) or not query['offset'].isascii()
            or not query['offset'].isdigit()):
        raise HTTPException(422, 'offline_recall_search_query_invalid')
    canonical = RecallSearchQuery(search=query['search'], offset=int(query['offset'])).canonical()
    if (canonical != query or run.query != query or digest(query) != snapshot.query_key
            or run.query_key != snapshot.query_key or receipt.query_key != snapshot.query_key
            or snapshot.source_id != 'nhtsa-us-recalls' or run.source_id != snapshot.source_id
            or receipt.snapshot_id != snapshot.id or receipt.status not in {'ok', 'not_modified'}
            or receipt.parser_identity != snapshot.parser_identity):
        raise HTTPException(422, 'offline_recall_search_formal_receipt_mismatch')
    if (not snapshot.body or hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest() != snapshot.raw_hash
            or not snapshot.source_url or not snapshot.parser_version):
        raise HTTPException(422, 'offline_raw_integrity_failed')
    SearchDiscovery.model_validate(snapshot.discovery)
    if (digest(snapshot.discovery) != snapshot.discovery_hash
            or snapshot.discovery['pagination']['offset'] != int(query['offset'])):
        raise HTTPException(422, 'offline_recall_search_page_integrity_failed')
    evidence = {'snapshot_id': snapshot.id, 'query_id': run.id, 'verification_id': receipt.id,
                'data_state': 'local_snapshot', 'observed_at': timestamp(snapshot.observed_at),
                'verified_at': timestamp(receipt.verified_at)}
    payload = {'query': deepcopy(query), 'discovery': deepcopy(snapshot.discovery),
               'discovery_hash': snapshot.discovery_hash, 'evidence': evidence,
               'empty_observation': not snapshot.discovery['products'], 'notices': list(RECALL_SEARCH_NOTICES),
               'boundary': {'kind': 'recall_search_candidate_page', 'formal_campaign_revision': False,
                            'applicability': 'not_assessed', 'complete_query_result': False}}
    return payload, _source(snapshot, receipt)


def load_member(db, registry, reference, *, candidate_cache=None, session_id=None, pack_schema='offline-pack@1'):
    ref = deepcopy(reference)
    kind = ref['kind']
    privacy = 'public'
    if kind == 'tire':
        snapshot = db.get(Snapshot, ref['snapshot_id'])
        if snapshot is None:
            raise HTTPException(404, 'offline_snapshot_missing')
        receipt = _receipt(db, Verification, snapshot, ref)
        rows = [item for item in snapshot.parsed_variants if item.get('id') == ref['variant_id']]
        if len(rows) != 1:
            raise HTTPException(422, 'offline_snapshot_member_missing_or_ambiguous')
        variant = deepcopy(rows[0])
        VariantInput.model_validate({key: value for key, value in variant.items() if key in VariantInput.model_fields})
        candidates = _tire_candidates(db, registry, snapshot.id, ref['variant_id'], receipt)
        if candidate_cache is not None:
            candidate_cache[(snapshot.id, ref['variant_id'], receipt.id)] = candidates
        fatal = {item for candidate in candidates for item in candidate['missing_evidence']} - {
            'variant_revoked', 'identity_contract_review_required', 'identity_contract_version_unknown'}
        if fatal or not candidates:
            raise HTTPException(422, 'offline_tire_material_integrity_failed')
        payload = {'variant': variant, 'identity_contract': contract_metadata(db, ref['variant_id']),
                   'snapshot_identity_contract': snapshot.identity_contract_version,
                   # Scope preparation fills one shared immutable group decision
                   # only after its distinct-reference limit has been checked.
                   'field_resolution': None if candidate_cache is not None else _tire_resolution(candidates, ref['variant_id']),
                   'lifecycle': db.scalar(select(VariantLifecycleEvent.after_state).where(
                       VariantLifecycleEvent.variant_id == ref['variant_id']).order_by(
                           desc(VariantLifecycleEvent.revision)).limit(1)) or 'unreviewed'}
        source = _source(snapshot, receipt)
        ref['verification_id'] = receipt.id
    elif kind == 'vehicle':
        snapshot = db.get(VehicleSnapshot, ref['snapshot_id'])
        if snapshot is None:
            raise HTTPException(404, 'offline_vehicle_snapshot_missing')
        receipt = _receipt(db, VehicleVerification, snapshot, ref)
        original = snapshot.payload
        validate_vehicle_structure(original, original['fitments'])
        if fitment_fact_hash(original) != snapshot.fact_hash or original['vehicle']['id'] != snapshot.vehicle_id:
            raise HTTPException(422, 'offline_vehicle_fact_integrity_failed')
        payload = {key: deepcopy(original.get(key, [])) for key in ('vehicle', 'trims', 'fitments', 'footnotes')}
        payload.update(fact_hash=snapshot.fact_hash, fact_version=snapshot.fact_version,
                       excluded_document_count=len(original.get('documents', [])))
        source = _source(snapshot, receipt)
        ref['verification_id'] = receipt.id
    elif kind == 'recall':
        loaded = load_recall_evidence(db, ref['snapshot_id'], ref['recall_revision_id'],
                                     verification_id=ref.get('verification_id'))
        evidence, records = loaded['evidence'], loaded['records']
        ref['verification_id'] = evidence['verification_id']
        source = {key: deepcopy(evidence[key]) for key in ('source_id', 'source_url', 'raw_hash',
            'parser_version', 'parser_identity', 'observed_at', 'verified_at', 'verification_id')}
        payload = {**loaded, 'facts': canonical_recall_facts(evidence, records),
                   'policy': recall_policy_descriptor(), 'boundary': recall_boundary_descriptor()}
    elif kind == 'recall_search':
        if pack_schema != 'offline-pack@2' or session_id is None:
            raise HTTPException(422, 'offline_reference_schema_not_supported')
        payload, source = load_recall_search_member(db, ref, session_id)
    elif kind == 'test_event':
        row = db.scalar(select(TireTestRevision).where(TireTestRevision.event_id == ref['event_id'],
                                                       TireTestRevision.revision == ref['event_revision']))
        if row is None:
            raise HTTPException(404, 'offline_test_revision_missing')
        EventPayload.model_validate(row.payload)
        if digest(row.payload) != row.fingerprint:
            raise HTTPException(422, 'offline_test_revision_integrity_failed')
        payload = {'metadata': metadata(row), 'event': deepcopy(row.payload)}
        privacy = 'restricted'
        source = {'source_id': None, 'source_url': row.payload['source_url'], 'raw_hash': None,
                  'parser_version': None, 'parser_identity': None, 'observed_at': timestamp(row.created_at),
                  'verified_at': None, 'verification_id': None}
    else:
        raise HTTPException(422, 'offline_reference_kind_unsupported')
    check_material(payload)
    return {'key': member_key(ref), 'reference': ref, 'member_reasons': [], 'privacy_class': privacy,
            'raw_included': False, 'source': source, 'payload': payload}


def _recall_ref(db, snapshot, receipt):
    revision = db.scalar(select(RecallRevision).where(RecallRevision.campaign_number == snapshot.campaign_number,
        RecallRevision.revision == snapshot.revision)) if snapshot.revision is not None else None
    return {'kind': 'recall', 'snapshot_id': snapshot.id, 'recall_revision_id': revision.id if revision else None,
            'verification_id': receipt.id}


def scope_limit(name, count, limit, *, at_least=False):
    if count > limit:
        raise HTTPException(413, {'code': 'offline_scope_capacity_exceeded', 'dimension': name,
            'count': count, 'count_is_lower_bound': at_least, 'limit': limit,
            'action': 'narrow_scope_and_prepare_again',
            'message': '所选范围超过离线容量限制，请缩小范围后重新准备；未生成部分离线包。'})


def resolve_scope(db, registry, scope, session_id, *, limits=None, pack_schema='offline-pack@1'):
    if pack_schema not in {'offline-pack@1', 'offline-pack@2'}:
        raise HTTPException(422, 'offline_pack_schema_not_supported')
    contexts, omissions, selected = [], [], []
    counts = {'garage_profiles': 0, 'watch_items': 0, 'recent_queries': 0}
    heads = None

    def tire_refs(variant_id):
        nonlocal heads
        if heads is None:
            heads = []
            for head in latest_tire_heads(db):
                snapshot = db.get(Snapshot, head['snapshot_id'])
                if snapshot:
                    heads.append((head, snapshot))
        return [{'kind': 'tire', 'snapshot_id': snapshot.id, 'variant_id': variant_id,
                 'verification_id': head['id']} for head, snapshot in heads
                if any(item.get('id') == variant_id for item in snapshot.parsed_variants)]

    if scope['garage']['include']:
        latest = select(GarageRevision.vehicle_id, func.max(GarageRevision.revision).label('revision')).group_by(
            GarageRevision.vehicle_id).subquery()
        statement = select(GarageRevision).join(latest, (GarageRevision.vehicle_id == latest.c.vehicle_id) &
            (GarageRevision.revision == latest.c.revision)).where(GarageRevision.archived.is_(False))
        requested = scope['garage']['vehicle_ids']
        if requested is not None:
            statement = statement.where(GarageRevision.vehicle_id.in_(requested))
        counts['garage_profiles'] = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        if limits:
            scope_limit('garage_profiles', counts['garage_profiles'], limits['max_garage_profiles'])
        rows = db.scalars(statement.order_by(GarageRevision.vehicle_id)).all()
        for missing in sorted(set(requested or []) - {row.vehicle_id for row in rows}):
            omissions.append(omission('garage', missing, 'active_garage_missing', True))
        for row in rows:
            context = {'id': 'garage:' + row.vehicle_id, 'kind': 'garage', 'scope': 'local_workspace',
                'privacy_class': 'private', 'payload': {'vehicle_id': row.vehicle_id, 'revision': row.revision,
                'basis': row.basis, 'profile': deepcopy(row.profile), 'fitment_reference': deepcopy(row.fitment_reference),
                'created_at': timestamp(row.created_at)}, 'evidence_keys': []}
            contexts.append(context)
            for axle in ('front', 'rear'):
                variant_id = row.profile.get(axle, {}).get('current_variant_id')
                if variant_id:
                    refs = tire_refs(variant_id)
                    if not refs:
                        omissions.append(omission('garage', row.vehicle_id, 'selected_axle_evidence_unavailable:' + axle))
                    selected.extend((ref, reason('garage', row.vehicle_id, row.revision, axle), context) for ref in refs)
            copied = row.fitment_reference
            if copied and copied.get('snapshot_id'):
                selected.append(({'kind': 'vehicle', 'snapshot_id': copied['snapshot_id']},
                                 reason('garage', row.vehicle_id, row.revision), context))

    if scope['watchlist']['include']:
        statement = select(WatchItem).where(WatchItem.session_id == session_id)
        requested = scope['watchlist']['item_ids']
        if requested is not None:
            statement = statement.where(WatchItem.id.in_(requested))
        counts['watch_items'] = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        if limits:
            scope_limit('watch_items', counts['watch_items'], limits['max_watch_items'])
        rows = db.scalars(statement.order_by(WatchItem.id)).all()
        for missing in sorted(set(requested or []) - {row.id for row in rows}):
            omissions.append(omission('watchlist', missing, 'owned_watch_item_missing', True))
        for row in rows:
            context = {'id': 'watchlist:' + row.id, 'kind': 'watchlist', 'scope': 'current_session',
                'privacy_class': 'private', 'payload': {'item_id': row.id, 'variant_id': row.variant_id,
                'created_at': timestamp(row.created_at)}, 'evidence_keys': []}
            contexts.append(context)
            refs = tire_refs(row.variant_id)
            if not refs:
                omissions.append(omission('watchlist', row.id, 'watched_tire_evidence_unavailable'))
            selected.extend((ref, reason('watchlist', row.id), context) for ref in refs)

    if scope['recent']['include']:
        # Candidates are bounded by query-created time. Failed candidates remain
        # visible omissions, and can never borrow proof from a matching query_key.
        runs = db.scalars(select(QueryRun).where(QueryRun.session_id == session_id).order_by(
            desc(QueryRun.created_at), desc(QueryRun.id)).limit(scope['recent']['limit'])).all()
        counts['recent_queries'] = len(runs)
        for run in runs:
            refs = []
            for receipt in db.scalars(select(Verification).where(Verification.query_id == run.id)):
                snapshot = db.get(Snapshot, receipt.snapshot_id)
                if snapshot and receipt.status in {'ok', 'not_modified'}:
                    refs.extend({'kind': 'tire', 'snapshot_id': snapshot.id, 'variant_id': item['id'],
                        'verification_id': receipt.id} for item in snapshot.parsed_variants)
            refs.extend({'kind': 'vehicle', 'snapshot_id': receipt.snapshot_id, 'verification_id': receipt.id}
                        for receipt in db.scalars(select(VehicleVerification).where(VehicleVerification.query_id == run.id)))
            for receipt in db.scalars(select(RecallVerification).where(RecallVerification.query_id == run.id)):
                snapshot = db.get(RecallSnapshot, receipt.snapshot_id)
                if snapshot:
                    refs.append(_recall_ref(db, snapshot, receipt))
            if pack_schema == 'offline-pack@2':
                refs.extend({'kind': 'recall_search', 'snapshot_id': receipt.snapshot_id, 'verification_id': receipt.id}
                            for receipt in db.scalars(select(RecallSearchVerification).where(
                                RecallSearchVerification.query_id == run.id)))
            if not refs:
                omissions.append(omission('recent', run.id, 'query_has_no_formal_receipt'))
            selected.extend((ref, reason('recent', run.id), None) for ref in refs)
    selected.extend((ref, reason('explicit'), None) for ref in scope['references'])

    members, loaded_cache, candidate_cache = {}, {}, {}
    for ref, why, context in selected:
        requested_key = digest(ref)
        if requested_key not in loaded_cache:
            try:
                loaded_cache[requested_key] = (load_member(db, registry, ref, candidate_cache=candidate_cache,
                                                         session_id=session_id, pack_schema=pack_schema), None)
            except (HTTPException, ValueError, KeyError, TypeError) as error:
                detail = error.detail if isinstance(error, HTTPException) else 'offline_invalid_formal_material'
                loaded_cache[requested_key] = (None, str(detail))
        cached, detail = loaded_cache[requested_key]
        if cached is None:
            omissions.append(omission(why['selector'], why['object_id'] or member_key(ref), str(detail),
                                     why['selector'] == 'explicit'))
            continue
        # Alternate receipt keys and accumulated membership are per-member;
        # never mutate the cached formal loader result shared by later selectors.
        loaded = {**cached, 'member_reasons': [], 'payload': dict(cached['payload'])}
        key = loaded['key']
        if key in members and members[key]['reference'] != loaded['reference']:
            # Same exact content can have several selected formal receipts. Keep
            # the first selected receipt and report every alternate binding;
            # never silently rewrite a selected query's proof.
            key = digest(loaded['reference'])
            loaded['key'] = key
        member = members.setdefault(key, loaded)
        if limits:
            scope_limit('distinct_evidence', len(members), limits['max_distinct_evidence'], at_least=True)
        if why not in member['member_reasons']:
            member['member_reasons'].append(why)
        if context is not None and key not in context['evidence_keys']:
            context['evidence_keys'].append(key)
    members = sorted(members.values(), key=lambda item: item['key'])
    if limits:
        scope_limit('searchable_documents', document_count(contexts, members), limits['max_searchable_documents'])
    # All selected source candidates for the exact same variant share a complete
    # frozen field decision. No six-reference/token/fact cap applies here.
    groups = {}
    for item in members:
        if item['reference']['kind'] == 'tire':
            groups.setdefault(item['reference']['variant_id'], []).append(item)
    for variant_id, group in groups.items():
        candidates = []
        for item in group:
            ref = item['reference']
            candidates.extend(candidate_cache[(ref['snapshot_id'], variant_id, ref['verification_id'])])
        resolution = _tire_resolution(candidates, variant_id)
        for item in group:
            # Frozen for the remainder of this preparation; sharing changes no
            # JSON field/value and avoids n copies of an n-candidate decision.
            item['payload']['field_resolution'] = resolution
    omissions.append(omission('rights', None, 'raw_html_json_pdf_images_and_linked_media_excluded'))
    return contexts, members, omissions, counts


def document_count(contexts, members):
    return len(contexts) + sum(max(1, len(item['payload']['records'])) if item['reference']['kind'] == 'recall'
        else max(1, len(item['payload']['discovery']['products'])) if item['reference']['kind'] == 'recall_search'
        else len(item['payload']['event']['participants']) if item['reference']['kind'] == 'test_event' else 1
        for item in members)


def documents(contexts, members, *, preview_byte_limit=None):
    result = []
    text_bytes = 0
    def add(*, id, category, kind, member=None, context=None, record_index=None, title, text, facets=None):
        nonlocal text_bytes
        text_bytes += len(text.encode('utf-8')) + len(title.encode('utf-8'))
        if preview_byte_limit is not None and text_bytes > preview_byte_limit:
            raise HTTPException(413, {'code': 'offline_preview_transport_limit_exceeded',
                'preview_bytes_at_least': text_bytes, 'max_preview_bytes': preview_byte_limit,
                'action': 'narrow_scope_and_prepare_again'})
        source = member['source'] if member else {}
        values = {name: None for name in ('brand', 'model', 'size', 'source_id', 'campaign_number')}
        values.update(source_id=source.get('source_id'))
        values.update(facets or {})
        result.append({'id': id, 'category': category, 'kind': kind,
            'member_key': member['key'] if member else None, 'context_id': context['id'] if context else None,
            'record_index': record_index, 'title': title, 'text': text, 'facets': values,
            'membership': sorted({why['selector'] for why in member['member_reasons']}) if member else [kind],
            'privacy_class': member['privacy_class'] if member else 'private',
            'observed_at': source.get('observed_at'), 'verified_at': source.get('verified_at')})
    for item in contexts:
        payload, kind = item['payload'], item['kind']
        profile = payload.get('profile', {})
        add(id='context:' + item['id'], category=kind, kind=kind, context=item,
            title=profile.get('nickname') or payload.get('variant_id') or item['id'], text=stable_json(payload),
            facets={'brand': profile.get('manufacturer'), 'model': profile.get('model')})
    for item in members:
        kind, payload = item['reference']['kind'], item['payload']
        prefix = 'member:' + item['key']
        if kind == 'recall' and payload['records']:
            for index, record in enumerate(payload['records']):
                add(id=prefix + ':record:' + str(index), category='evidence', kind=kind, member=item,
                    record_index=index, title=f"NHTSA {record['campaign_number']} · {record.get('make') or ''} {record.get('model') or ''}",
                    text=stable_json(record), facets={'brand': record.get('make'), 'model': record.get('model'),
                    'campaign_number': record['campaign_number']})
        elif kind == 'recall_search':
            page = payload['discovery']
            if page['products']:
                for index, product in enumerate(page['products']):
                    scoped = {'query': payload['query'], 'product': product, 'pagination': page['pagination'],
                              'boundary': payload['boundary'], 'notices': payload['notices']}
                    add(id=prefix + ':record:' + str(index), category='evidence', kind=kind, member=item,
                        record_index=index, title='NHTSA 搜索 · ' + product['brand'] + ' ' + product['tireline'],
                        text=stable_json(scoped), facets={'brand': product['brand'], 'model': product['tireline'],
                                                       'size': product['size']})
            else:
                add(id=prefix, category='evidence', kind=kind, member=item,
                    title='NHTSA 搜索空观察 · ' + payload['query']['search'], text=stable_json(payload))
        elif kind == 'test_event':
            event = payload['event']
            for index, participant in enumerate(event['participants']):
                scoped = {key: value for key, value in event.items() if key not in {'participants', 'measurements'}}
                scoped.update(participant=participant, measurements=[row for row in event['measurements']
                    if row['participant_key'] == participant['key']])
                add(id=prefix + ':record:' + str(index), category='evidence', kind=kind, member=item,
                    record_index=index, title=event['title'] + ' · ' + participant['brand'] + ' ' + participant['model'],
                    text=stable_json(scoped), facets={'brand': participant['brand'], 'model': participant['model'],
                    'size': event['tested_size']})
        else:
            value = payload.get('variant') or payload.get('vehicle') or payload['evidence']
            facets = {'brand': value.get('brand') or value.get('manufacturer', {}).get('name'),
                      'model': value.get('model'), 'size': value.get('size'),
                      'campaign_number': value.get('campaign_number')}
            title = ' '.join(str(v) for v in facets.values() if v) or kind
            add(id=prefix, category='evidence', kind=kind, member=item, title=title,
                text=stable_json(value if kind == 'tire' else payload), facets=facets)
    return result
