"""Materialize only accepted, latest verified query heads and active event revisions."""
import re
import unicodedata

from sqlalchemy import delete, func, select, text

from .curation import FIELD_CATALOG
from .db import Snapshot, VariantLifecycleEvent, utcnow
from .domain import digest, stable_json
from .knowledge_models import KnowledgeDocument, KnowledgeFacet, KnowledgeIndexState
from .service import QueryService, timestamp
from .test_events import TireTestRevision
from .vehicles import VehicleSnapshot, VehicleVerification

INDEX_VERSION = 'accepted-heads-fts@5'
OMIT_FACTS = {'evidence_spans', 'source_field_conflicts'}
IDENTITY_FIELDS = ('brand', 'model', 'region', 'size', 'manufacturer_product_code', 'load_index',
                   'speed_rating', 'xl', 'hl', 'oe_mark', 'acoustic_technology', 'run_flat')
FIELD_LABELS = {**{key: item['label'] for key, item in FIELD_CATALOG.items()},
                'brand': '品牌', 'model': '型号', 'size': '尺寸', 'region': '区域',
                'manufacturer_product_code': '厂商产品代码', 'acoustic_technology': '静音技术 Acoustic',
                'oe_mark': 'OE 标记', 'run_flat': '防爆', 'load_index': '载重指数', 'speed_rating': '速度级别'}
CONFLICT_FIELDS = set(FIELD_CATALOG) | set(IDENTITY_FIELDS) | {'gtin', 'eprel_id', 'technology_features'}


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value)).casefold().split())


def size_key(value):
    return normalized(value).replace(' ', '').replace('zr', 'r')


def tokens(value):
    """One tokenizer for indexing and queries: NFKC, English words, Han bigrams.

    Single Han characters are indexed too, so a one-character query has defined
    behavior. All query tokens become literals, never FTS operators.
    """
    result = []
    for part in re.findall(r'[a-z0-9_]+|[\u3400-\u9fff]+', normalized(value)):
        if '\u3400' <= part[0] <= '\u9fff':
            result.extend(part)
            result.extend(part[i:i + 2] for i in range(len(part) - 1))
        else:
            result.append(part)
    return list(dict.fromkeys(result))


def query_tokens(value):
    result = []
    for part in re.findall(r'[a-z0-9_]+|[\u3400-\u9fff]+', normalized(value)):
        if '\u3400' <= part[0] <= '\u9fff' and len(part) > 1:
            result.extend(part[i:i + 2] for i in range(len(part) - 1))
        else:
            result.append(part)
    return list(dict.fromkeys(result))


def _heads(db):
    """Do not select any payload/body columns while checking for changes."""
    from .field_evidence import latest_tire_heads
    tire = latest_tire_heads(db)
    ranks = select(VehicleVerification.id, VehicleVerification.snapshot_id, VehicleVerification.vehicle_id,
        VehicleVerification.verified_at, VehicleSnapshot.source_id,
        func.row_number().over(partition_by=(VehicleSnapshot.source_id, VehicleVerification.vehicle_id),
            order_by=(VehicleVerification.verified_at.desc(), VehicleVerification.id.desc())).label('n'))\
        .join(VehicleSnapshot, VehicleSnapshot.id == VehicleVerification.snapshot_id).subquery()
    vehicle = [dict(row) for row in db.execute(select(ranks).where(ranks.c.n == 1)).mappings()]
    ranks = select(TireTestRevision.id, TireTestRevision.event_id, TireTestRevision.revision, TireTestRevision.state,
        func.row_number().over(partition_by=TireTestRevision.event_id,
                              order_by=TireTestRevision.revision.desc()).label('n')).subquery()
    events = [dict(row) for row in db.execute(select(ranks).where(ranks.c.n == 1)).mappings()]
    ranks = select(VariantLifecycleEvent.id, VariantLifecycleEvent.variant_id, VariantLifecycleEvent.after_state,
        func.row_number().over(partition_by=VariantLifecycleEvent.variant_id,
                              order_by=VariantLifecycleEvent.revision.desc()).label('n')).subquery()
    lifecycle = [dict(row) for row in db.execute(select(ranks).where(ranks.c.n == 1)).mappings()]
    from .identity_models import IdentityRevision
    ranks = select(IdentityRevision.id, IdentityRevision.variant_id, IdentityRevision.action,
        func.row_number().over(partition_by=IdentityRevision.variant_id,
                              order_by=IdentityRevision.revision.desc()).label('n')).subquery()
    identities = [dict(row) for row in db.execute(select(ranks).where(ranks.c.n == 1)).mappings()]
    recall_content, recall_observations = _recall_heads(db)
    return tire, vehicle, events, lifecycle, identities, recall_content, recall_observations


def _recall_heads(db):
    from .db import QueryRun
    from .recall_models import SOURCE_ID, RecallSnapshot, RecallVerification

    def heads(nonempty):
        statement = (select(RecallVerification.id, RecallVerification.snapshot_id, RecallVerification.verified_at,
            RecallSnapshot.campaign_number, RecallSnapshot.revision,
            func.row_number().over(partition_by=RecallSnapshot.campaign_number,
                order_by=(RecallVerification.verified_at.desc(), RecallVerification.id.desc())).label('n'))
            .join(RecallSnapshot, RecallSnapshot.id == RecallVerification.snapshot_id)
            .join(QueryRun, QueryRun.id == RecallVerification.query_id)
            .where(RecallSnapshot.source_id == SOURCE_ID, QueryRun.source_id == SOURCE_ID,
                   QueryRun.query_key == RecallSnapshot.query_key,
                   RecallVerification.query_key == RecallSnapshot.query_key,
                   RecallVerification.status.in_(('ok', 'not_modified'))))
        if nonempty:
            statement = statement.where(RecallSnapshot.revision.is_not(None))
        ranked = statement.subquery()
        return [dict(row) for row in db.execute(select(ranked).where(ranked.c.n == 1)).mappings()]

    return heads(True), heads(False)


def _serialize_heads(groups):
    return [[{key: timestamp(value) if hasattr(value, 'tzinfo') else value for key, value in row.items()}
             for row in sorted(rows, key=lambda item: item['id'])] for rows in groups]


def _facets(**values):
    return {(name, size_key(value) if name == 'size' else normalized(value))
            for name, choices in values.items() for value in (choices if isinstance(choices, list) else [choices])
            if value is not None and str(value).strip() and len(str(value)) <= 400}


def _document(*, kind, reference, label, excerpt, source_id, source_url, region, observed_at,
              verified_at, source_class, values, facets, source_conflicts=None, sku_acoustic=False):
    fields = {key: value for key, value in values.items() if value is not None}
    searchable = label + ' ' + excerpt + ' ' + ' '.join(
        f'{key} {FIELD_LABELS.get(key, "")} {stable_json(value)}' for key, value in fields.items())
    # The projection stores bounded display excerpts; all structured fields enter
    # the lexical index. No downloaded page body or private operator metadata enters it.
    display = excerpt[:1100] + ('…（展示摘录已截短，打开证据查看完整结构化记录）' if len(excerpt) > 1100 else '')
    payload = {'reference': reference, 'kind': kind, 'label': label, 'excerpt': display,
               'source_id': source_id, 'source_url': source_url, 'region': region,
               'observed_at': timestamp(observed_at), 'verified_at': timestamp(verified_at),
               'privacy_class': 'public' if source_class in {'manufacturer_official', 'regulatory', 'oem_fitment'} else 'private',
               'conflicts': source_conflicts or [], '_source_class': source_class,
               '_values': dict(values), '_sku_acoustic': sku_acoustic}
    return {'id': digest({'kind': kind, 'reference': reference, 'source_id': source_id}), 'kind': kind,
            'source_id': source_id, 'variant_id': reference.get('variant_id'),
            'tokens': ' '.join(tokens(searchable)), 'payload': payload,
            'facets': facets | _facets(field=list(fields))}


def _tire_documents(db, heads, revoked, sources, registry):
    from .field_evidence import snapshot_field_candidates
    from .field_authority import canonical_field, known_values_differ
    ids = {head['snapshot_id'] for head in heads}
    snapshots = {row.id: row for row in db.execute(select(Snapshot.id, Snapshot.source_id, Snapshot.source_url,
        Snapshot.observed_at, Snapshot.parsed_variants).where(Snapshot.id.in_(ids)))} if ids else {}
    selected = {}
    for head in sorted(heads, key=lambda item: (item['verified_at'], item['id']), reverse=True):
        snapshot = snapshots[head['snapshot_id']]
        for row in snapshot.parsed_variants:
            if row['id'] not in revoked:
                # Distinct active query snapshots are independent observations.
                # A late 304 on one page must not erase another page's content.
                selected.setdefault((row['id'], snapshot.id), (row, snapshot, head))
    docs = []
    candidate_context = {}
    for row, snapshot, head in selected.values():
        values = {**{key: value for key, value in row.get('facts', {}).items() if key not in OMIT_FACTS},
                  **{field: row.get(field) for field in IDENTITY_FIELDS}}
        label = f'{row["brand"]} {row["model"]} · {row["size"]} · {row.get("manufacturer_product_code") or "代码未确认"}'
        excerpt = '轮胎历史参数；' + '；'.join(f'{FIELD_LABELS.get(key, key)}: {stable_json(value)}'
                                               for key, value in values.items() if value is not None)
        technology = row.get('acoustic_technology')
        technologies = [technology] if technology else []
        features = row.get('facts', {}).get('technology_features') or []
        technologies.extend(value for value in (features if isinstance(features, list) else [features])
                            if isinstance(value, str))
        if technology and re.search(r'\bacoustic\b', normalized(technology)):
            technologies.append('acoustic')
        source_class = sources.get(snapshot.source_id, 'unclassified')
        spans = row.get('facts', {}).get('evidence_spans', {})
        sku_acoustic = bool(source_class == 'manufacturer_official' and row.get('manufacturer_product_code')
                            and technology and isinstance(spans, dict)
                            and isinstance(spans.get('acoustic_technology'), str)
                            and spans['acoustic_technology'].strip())
        docs.append(_document(kind='tire', reference={'kind': 'tire', 'snapshot_id': snapshot.id, 'variant_id': row['id']},
            label=label, excerpt=excerpt, source_id=snapshot.source_id, source_url=snapshot.source_url,
            region=row['region'], observed_at=snapshot.observed_at, verified_at=head['verified_at'],
            source_class=source_class, values=values, sku_acoustic=sku_acoustic,
            facets=_facets(brand=row['brand'], model=row['model'], size=row['size'], region=row['region'],
                           product_code=row.get('manufacturer_product_code'), technology=technologies),
            source_conflicts=QueryService.current_source_conflicts([{**row, 'snapshot_id': snapshot.id}], snapshot.source_id)))
        # Store immutable candidate material in the derived projection. Resolve at
        # retrieval time, without rereading page bodies for a cached search.
        docs[-1]['payload']['_field_candidates'] = snapshot_field_candidates(
            db, snapshot.id, row['id'], registry, row=row, verified_at=head['verified_at'], context=candidate_context)
    # Compare only selected formal query heads for one exact identity. Historical
    # FactVersion rows must not resurrect products removed from a query's catalog.
    groups = {}
    for doc in docs:
        groups.setdefault(doc['variant_id'], []).append(doc)
    for group in groups.values():
        values_by_field = {}
        for doc in group:
            for key, value in doc['payload']['_values'].items():
                if key in CONFLICT_FIELDS:
                    values_by_field.setdefault(canonical_field(key), []).append({'source_id': doc['source_id'],
                        'snapshot_id': doc['payload']['reference']['snapshot_id'], 'value': value})
        for key, entries in sorted(values_by_field.items()):
            if known_values_differ(item['value'] for item in entries):
                conflict = {'variant_id': group[0]['variant_id'], 'field': key, 'scope': 'selected_formal_heads',
                            'values': entries, 'resolution': 'unresolved'}
                for doc in group:
                    doc['payload']['conflicts'].append(conflict)
    return docs


def _vehicle_documents(db, heads):
    ids = {head['snapshot_id'] for head in heads}
    snapshots = {row.id: row for row in db.execute(select(VehicleSnapshot.id, VehicleSnapshot.source_id,
        VehicleSnapshot.source_url, VehicleSnapshot.observed_at, VehicleSnapshot.payload).where(VehicleSnapshot.id.in_(ids)))} if ids else {}
    docs = []
    for head in heads:
        snapshot = snapshots[head['snapshot_id']]
        data = snapshot.payload
        vehicle = data['vehicle']
        label = f'{vehicle["manufacturer"]["name"]} {vehicle["model"]} · {vehicle["generation"]}'
        values = {'vehicle': vehicle, 'trims': data['trims'], 'fitments': data['fitments']}
        sizes = [row[axle]['size'] for row in data['fitments'] for axle in ('front', 'rear')]
        docs.append(_document(kind='vehicle', reference={'kind': 'vehicle', 'snapshot_id': snapshot.id},
            label=label, excerpt='车型历史配置；' + stable_json(values), source_id=snapshot.source_id,
            source_url=snapshot.source_url, region=vehicle['region'], observed_at=snapshot.observed_at,
            verified_at=head['verified_at'], source_class='oem_fitment', values=values,
            facets=_facets(brand=vehicle['manufacturer']['name'], model=vehicle['model'], size=sizes, region=vehicle['region'])))
    return docs


def _event_documents(db, heads):
    ids = {head['id'] for head in heads if head['state'] == 'active'}
    rows = db.execute(select(TireTestRevision.event_id, TireTestRevision.revision, TireTestRevision.payload,
                             TireTestRevision.created_at).where(TireTestRevision.id.in_(ids))) if ids else []
    docs = []
    for row in rows:
        data = row.payload
        values = {key: data[key] for key in ('organization', 'relationship', 'publication_date', 'tested_size',
                 'vehicle', 'surface', 'conditions', 'coverage', 'reported_participants', 'participants', 'metrics', 'measurements')}
        # Locators navigate evidence; they are not test conclusions. Exclude the
        # potentially long locator strings from lexical content, along with
        # rights/operator metadata already excluded above.
        values['measurements'] = [{key: value for key, value in item.items() if key != 'evidence_locator'}
                                  for item in data['measurements']]
        label = '人工测试记录 · ' + data['title']
        excerpt = f'{data["tested_size"]}；{data["conditions"]}；' + '；'.join(
            f'{person["brand"]} {person["model"]}' for person in data['participants'])
        docs.append(_document(kind='test_event', reference={'kind': 'test_event', 'event_id': row.event_id, 'event_revision': row.revision},
            label=label, excerpt=excerpt, source_id=None, source_url=data['source_url'], region=None,
            observed_at=row.created_at, verified_at=None, source_class='manual_test', values=values,
            facets=_facets(brand=[p['brand'] for p in data['participants']], model=[p['model'] for p in data['participants']],
                           brand_model=[normalized(p['brand']) + ' | ' + normalized(p['model']) for p in data['participants']],
                           size=data['tested_size'])))
    return docs


def _recall_documents(db, content_heads, observation_heads):
    from .recall_evidence import load_recall_evidence
    from .recall_models import RecallRevision
    material = {}

    def load(head):
        key = (head['snapshot_id'], head['id'])
        if key not in material:
            revision_id = (db.scalar(select(RecallRevision.id).where(
                RecallRevision.campaign_number == head['campaign_number'],
                RecallRevision.revision == head['revision']))) if head['revision'] is not None else None
            material[key] = load_recall_evidence(db, head['snapshot_id'], revision_id, verification_id=head['id'])
        return material[key]

    latest = {head['campaign_number']: load(head)['evidence'] for head in observation_heads}
    selected = list(content_heads) + [head for head in observation_heads if head['revision'] is None]
    docs = []
    for head in selected:
        value = load(head)
        evidence, records = value['evidence'], value['records']
        observation = latest[evidence['campaign_number']]
        reference = {'kind': 'recall', 'snapshot_id': evidence['snapshot_id'],
                     'recall_revision_id': evidence['recall_revision_id']}
        rows = list(zip(evidence['record_scopes'], records, strict=True)) if records else [(None, None)]
        for scope, record in rows:
            values = {'recall.' + name: value for name, value in (record or {}).items()}
            values.update({'recall.campaign_number': evidence['campaign_number'],
                'recall.record_count': evidence['record_count'], 'recall.observation_kind': evidence['observation_kind'],
                'recall.applicability': 'not_assessed'})
            label = (f'NHTSA {evidence["campaign_number"]} · 公告产品记录 · '
                     f'{record["make"] or "品牌未标明"} / {record["model"] or "型号未标明"}') if record else evidence['label']
            excerpt = ('正式召回历史产品记录；' if record else '正式按公告编号查询的空响应观察；') + stable_json(values)
            facets = _facets(campaign_number=evidence['campaign_number'], region='US')
            if record:
                facets |= _facets(brand=record['make'], model=record['model'])
            doc = _document(kind='recall', reference=reference, label=label, excerpt=excerpt,
                source_id=evidence['source_id'], source_url=evidence['source_url'], region='US',
                observed_at=datetime_value(evidence['observed_at']), verified_at=datetime_value(evidence['verified_at']),
                source_class='regulatory', values=values, facets=facets)
            record_key = scope['record_key'] if scope else None
            doc['id'] = digest({'reference': reference, 'record_key': record_key})
            doc['payload']['recall'] = {key: evidence[key] for key in ('campaign_number', 'recall_revision_id',
                'recall_revision', 'observation_kind', 'record_count', 'applicability')}
            doc['payload']['recall'].update(record_key=record_key,
                latest_observation={key: observation[key] for key in
                    ('snapshot_id', 'observation_kind', 'observed_at', 'verified_at')})
            docs.append(doc)
    return docs


def datetime_value(value):
    from datetime import datetime
    return datetime.fromisoformat(value) if value else None


def refresh_index(db, registry):
    """Caller holds ingestion lock; projection replacement and FTS are atomic."""
    heads = _heads(db)
    sources = {item['id']: item.get('source_class', 'unclassified') for item in registry.sources()}
    from .field_authority import policy_descriptor
    from .recall_evidence import recall_policy_descriptor
    from .identity_contract_models import VariantIdentityBinding
    bindings = [dict(row) for row in db.execute(select(VariantIdentityBinding.id, VariantIdentityBinding.schema,
        VariantIdentityBinding.fingerprint).order_by(VariantIdentityBinding.id)).mappings()]
    source_metadata = [{key: item.get(key) for key in ('id', 'name', 'region', 'source_class')}
                       for item in registry.sources()]
    signature = digest({'heads': _serialize_heads(heads), 'sources': source_metadata,
                        'identity_bindings': bindings, 'field_policy': policy_descriptor(),
                        'recall_policy': recall_policy_descriptor(), 'version': INDEX_VERSION})
    state = db.get(KnowledgeIndexState, 'accepted')
    if state and state.signature == signature and state.version == INDEX_VERSION:
        return state
    revoked = {row['variant_id'] for row in heads[3] if row['after_state'] == 'revoked'}
    revoked |= {row['variant_id'] for row in heads[4] if row['action'] != 'clear'}
    docs = _tire_documents(db, heads[0], revoked, sources, registry)
    docs.extend(_vehicle_documents(db, heads[1]))
    docs.extend(_event_documents(db, heads[2]))
    docs.extend(_recall_documents(db, heads[5], heads[6]))
    backend = db.get_bind().dialect.name
    if backend == 'sqlite':
        db.execute(text('DELETE FROM knowledge_fts'))
    db.execute(delete(KnowledgeFacet))
    db.execute(delete(KnowledgeDocument))
    for doc in docs:
        facets = doc.pop('facets')
        db.add(KnowledgeDocument(**doc))
        db.flush()
        db.add_all(KnowledgeFacet(document_id=doc['id'], name=name, value=value) for name, value in facets)
        if backend == 'sqlite':
            db.execute(text('INSERT INTO knowledge_fts (document_id, tokens) VALUES (:id, :tokens)'),
                       {'id': doc['id'], 'tokens': doc['tokens']})
    if backend == 'postgresql':
        db.execute(text("UPDATE knowledge_documents SET search_vector = to_tsvector('simple', tokens)"))
    if state is None:
        state = KnowledgeIndexState(id='accepted')
        db.add(state)
    state.version, state.signature = INDEX_VERSION, signature
    state.documents, state.refreshed_at = len(docs), utcnow()
    db.flush()
    return state
