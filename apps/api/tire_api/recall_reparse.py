"""Recall-only historical comparisons. These functions never adopt source evidence.

Names identify campaign product rows for comparison only, never tire applicability.
Each lost member and known field is gated independently of aggregate denominators.
"""
from collections import Counter
from copy import deepcopy

from sqlalchemy import desc, select
from sqlalchemy.orm import defer

from .adapters import nhtsa
from .db import QueryRun, utc, utcnow
from .domain import digest, stable_json
from .quality import assess_records, is_known, known_leaves
from .recall_models import RecallQuery, RecallRecord, RecallSnapshot, RecallVerification

RULESET = 'recall-field-loss@1'
ASSOCIATED_FIELDS = {'type', 'productYear', 'productMake', 'productModel', 'size',
                     'productionDates', 'manufacturer'}


def validate_recall_input(source_id, query, source_url, content_type):
    if source_id != nhtsa.SOURCE_ID or content_type != 'application/json':
        raise ValueError('recall source or mime')
    expected_url = nhtsa.query_url(query)
    if 'campaign_number' in query and RecallQuery.model_validate(query).canonical() != query:
        raise ValueError('noncanonical recall query')
    if source_url != expected_url:
        raise ValueError('recall query url')


def _models(query):
    if 'search' in query:
        from .recall_discovery import RecallSearchSnapshot, RecallSearchVerification
        return RecallSearchSnapshot, RecallSearchVerification, 'discovery'
    return RecallSnapshot, RecallVerification, 'records'


def _statement(source_id, query_key, query):
    snapshot, verification, _ = _models(query)
    return (select(snapshot, verification, QueryRun.query).options(defer(snapshot.body))
        .join(verification, verification.snapshot_id == snapshot.id)
        .join(QueryRun, QueryRun.id == verification.query_id)
        .where(snapshot.source_id == source_id, snapshot.query_key == query_key,
               verification.query_key == query_key, QueryRun.source_id == source_id,
               QueryRun.query_key == query_key, verification.status.in_(('ok', 'not_modified')))
        .order_by(desc(verification.verified_at), desc(verification.id)).limit(1))


def _matches(snapshot, query):
    return (snapshot.query == query if 'search' in query
            else snapshot.campaign_number == query['campaign_number'])


def latest_recall_baseline(db, source_id, query_key, query):
    validate_recall_input(source_id, query, nhtsa.query_url(query), 'application/json')
    if digest(query) != query_key:
        raise ValueError('recall query identity')
    _, _, field = _models(query)
    # Compare JSON in Python for portability across SQLite and PostgreSQL JSON.
    for snapshot, verification, verified_query in db.execute(_statement(source_id, query_key, query)):
        if verified_query != query or not _matches(snapshot, query):
            return None
        if snapshot.source_url != nhtsa.query_url(query) or snapshot.content_type != 'application/json':
            return None
        return {'snapshot_id': snapshot.id, 'verification_id': verification.id,
            'verified_at': utc(verification.verified_at).isoformat(),
            'observed_at': utc(snapshot.observed_at).isoformat(), 'raw_hash': snapshot.raw_hash,
            'source_url': snapshot.source_url, 'parser_version': snapshot.parser_version,
            'parser_identity': deepcopy(snapshot.parser_identity), 'selected_at': utcnow().isoformat(),
            'payload': deepcopy(getattr(snapshot, field))}
    return None


def recall_reference_snapshot(db, capture):
    run = db.get(QueryRun, capture.query_id)
    if (run is None or run.source_id != capture.source_id or run.query_key != capture.query_key
            or digest(run.query) != capture.query_key):
        return None
    validate_recall_input(capture.source_id, run.query, capture.source_url, capture.content_type)
    snapshot_type, verification_type, field = _models(run.query)
    statement = _statement(capture.source_id, capture.query_key, run.query).where(
        verification_type.query_id == capture.query_id, snapshot_type.raw_hash == capture.raw_hash,
        snapshot_type.source_url == capture.source_url, snapshot_type.content_type == capture.content_type)
    for snapshot, _, verified_query in db.execute(statement):
        if verified_query == run.query and _matches(snapshot, run.query):
            return {'snapshot_id': snapshot.id, 'raw_hash': snapshot.raw_hash,
                'observed_at': utc(snapshot.observed_at).isoformat(), 'payload': deepcopy(getattr(snapshot, field))}
    return None


def validate_recall_candidate(payload, source_input):
    query = source_input['query']
    validate_recall_input(source_input['source_id'], query, source_input['source_url'], source_input['content_type'])
    if 'campaign_number' in query:
        if not isinstance(payload, list) or len(payload) > 1000:
            raise ValueError('recall candidate collection')
        records = [RecallRecord.model_validate(row, strict=True).model_dump() for row in payload]
        if (any(row['campaign_number'] != query['campaign_number']
                or row['potential_units'] is not None and row['potential_units'] > 2**53 for row in records)
                or len({digest(row) for row in records}) != len(records)):
            raise ValueError('recall candidate identity or duplicates')
        # Campaign endpoint has no meaningful row order; retain the entire multiset.
        return sorted(records, key=digest)
    from .recall_discovery import SearchDiscovery
    discovery = SearchDiscovery.model_validate(payload, strict=True).model_dump()
    # Pydantic Literal[10] accepts equal floats even with strict=True; keep the
    # published pagination integer contract, without coercing archived output.
    if type(payload['pagination']['max']) is not int or discovery['pagination']['offset'] != int(query['offset']):
        raise ValueError('recall search query page mismatch')
    for product in discovery['products']:
        for campaign in product['campaigns']:
            links = [row['url'] for row in campaign['documents']]
            if len(set(links)) != len(links):
                raise ValueError('duplicate recall documents')
            associated = campaign['associated_products']
            if len({digest(row) for row in associated}) != len(associated):
                raise ValueError('duplicate associated products')
            for row in associated:
                # The parent validates the published candidate schema independently
                # of the selected archive. Opaque arbitrary nested JSON is not a fact.
                if (not row or set(row) - ASSOCIATED_FIELDS or any(value is not None and
                        (not isinstance(value, str) or len(value) > 60000 or '\x00' in value)
                        for value in row.values())):
                    raise ValueError('recall associated product schema')
    return discovery


def _key(group, values):
    return group + ':' + stable_json(values)


def _rows(payload):
    groups = {name: [] for name in ('products', 'campaigns', 'documents', 'associated_products')}
    if payload is None:
        return groups
    if isinstance(payload, list):
        for row in payload:
            identity = [row.get(key) for key in ('campaign_number', 'make', 'model', 'model_year_raw')]
            key = _key('campaigns', identity) if all(is_known(value) for value in identity[:3]) else None
            groups['campaigns'].append({'key': key, 'value': row})
        return groups
    for product in payload['products']:
        product_key = _key('products', [product['id']])
        groups['products'].append({'key': product_key, 'value': {key: value for key, value in product.items()
            if key not in {'campaigns', 'recalls_count'}}})
        for campaign in product['campaigns']:
            campaign_key = _key('campaigns', [product['id'], campaign['campaign_number']])
            groups['campaigns'].append({'key': campaign_key, 'value': {key: value for key, value in campaign.items()
                if key not in {'documents', 'associated_products'}}})
            for document in campaign['documents']:
                groups['documents'].append({'key': _key('documents', [product['id'], campaign['campaign_number'],
                    document['url']]), 'value': document})
            for associated in campaign['associated_products']:
                identity = [associated.get(key) for key in ('type', 'productMake', 'productModel', 'productYear', 'size')]
                key = (_key('associated_products', [product['id'], campaign['campaign_number'], *identity])
                       if all(is_known(value) for value in identity[:3]) else None)
                groups['associated_products'].append({'key': key, 'value': associated})
    return groups


def _fields(row):
    # Identity, display text and duplicated locators cannot inflate loss denominators.
    ignored = {'id', 'artemis_id', 'campaign_number', 'applicability', 'url', 'brand', 'tireline',
               'make', 'model', 'model_year_raw', 'type', 'productMake', 'productModel', 'productYear'}
    return {path: value for key, child in row['value'].items() if key not in ignored
            for path, value in known_leaves(child, key).items()}


def _unique_rows(groups):
    result = {}
    for group, rows in groups.items():
        counts = Counter(row['key'] for row in rows)
        # Ambiguous rows stay visible with occurrence locators. They are never silently
        # overwritten or represented as safely aligned by a fabricated identity.
        occurrences = Counter()
        for row in rows:
            key = row['key'] or group + ':missing_identity'
            occurrences[key] += 1
            if row['key'] is None or counts[row['key']] > 1:
                key += ':occurrence:' + str(occurrences[key])
            result[key] = row['value']
    return result


def compare_recall_candidate(baseline, candidate):
    from .reparse import flattened
    previous = baseline['payload'] if baseline else None
    old_groups, new_groups = _rows(previous), _rows(candidate)
    groups, reasons = {}, set()
    for name in old_groups:
        group = assess_records(old_groups[name], new_groups[name], lambda row: row['key'], _fields, RULESET)
        # assess_records skips empty baselines. Candidate ambiguity is still unsafe,
        # including on the first experiment, and must never collapse distinct rows.
        counts = Counter(row['key'] for row in new_groups[name])
        if None in counts or any(count > 1 for count in counts.values()):
            group['reason_codes'].append('ambiguous_alignment')
            group['ambiguous_keys'].extend('candidate:' + str(key) for key, count in counts.items()
                                            if key is None or count > 1)
        if group['lost_rows']:
            group['reason_codes'].append('recall_member_loss')
        if group['lost_field_count']:
            group['reason_codes'].append('recall_safety_field_loss')
        group['reason_codes'] = sorted(set(group['reason_codes']))
        reasons.update(group['reason_codes'])
        groups[name] = group
    old, new = _unique_rows(old_groups), _unique_rows(new_groups)
    identities = []
    for key in old.keys() & new.keys():
        if key.startswith('products:') and any(old[key].get(field) != new[key].get(field)
                for field in ('id', 'artemis_id', 'brand', 'tireline', 'size')):
            identities.append(key)
    if identities:
        reasons.add('recall_identity_changed')
    if previous is not None and isinstance(previous, list) != isinstance(candidate, list):
        reasons.add('recall_payload_kind_changed')
    if isinstance(previous, dict) and isinstance(candidate, dict):
        if previous['pagination'] != candidate['pagination']:
            reasons.add('recall_pagination_changed')
        old['pagination'] = previous['pagination']
        new['pagination'] = candidate['pagination']
        # Order is explicit diff evidence (the search endpoint promises productName ASC),
        # while content identity and loss metrics remain independent of list positions.
        old['order'] = {'product_ids': [row['id'] for row in previous['products']]}
        new['order'] = {'product_ids': [row['id'] for row in candidate['products']]}
    quality = {'ruleset': RULESET, 'threshold': 0.3, 'groups': groups,
               'reason_codes': sorted(reasons), 'blocked': bool(reasons)}
    for key in ('baseline_rows', 'candidate_rows', 'aligned_rows', 'lost_rows', 'known_fields', 'lost_field_count'):
        quality[key] = sum(group[key] for group in groups.values())
    for key in ('lost_fields', 'lost_row_keys', 'ambiguous_keys'):
        quality[key] = [item for group in groups.values() for item in group[key]]
    quality['row_loss_ratio'] = quality['lost_rows'] / quality['baseline_rows'] if quality['baseline_rows'] else 0.0
    quality['field_loss_ratio'] = quality['lost_field_count'] / quality['known_fields'] if quality['known_fields'] else 0.0
    changes, count = [], 0
    for key in sorted(old.keys() & new.keys()):
        before, after = flattened(old[key]), flattened(new[key])
        fields = []
        for path in sorted(before.keys() | after.keys()):
            if before.get(path) != after.get(path) or (path in before) != (path in after):
                count += 1
                if count <= 2000:
                    fields.append({'path': path, 'before': before.get(path), 'after': after.get(path),
                                   'before_present': path in before, 'after_present': path in after})
        if fields:
            changes.append({'row_key': key, 'changes': fields})
    return quality, {'baseline_available': baseline is not None,
        'added_row_keys': sorted(new.keys() - old.keys()), 'removed_row_keys': sorted(old.keys() - new.keys()),
        'changed_rows': changes, 'identity_changed_row_keys': sorted(identities),
        'total_changed_fields': count, 'truncated': count > 2000}
