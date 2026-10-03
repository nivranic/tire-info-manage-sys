"""Exact structured evidence selection before any model call or document retrieval."""
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, StrictInt, model_validator
from sqlalchemy import desc, select
from sqlalchemy.orm import object_session

from .ai_models import AIEvidencePack
from .db import QueryRun, Snapshot, Verification, utcnow
from .domain import LiveQueryRequest, StrictModel, TireQuery, digest, stable_json
from .identity_contract import contract_context, contract_metadata
from .recall_models import RecallQuery, SOURCE_ID as RECALL_SOURCE_ID
from .service import QueryService, provenance, timestamp
from .source_settings import SourceAccessBlocked


class PackReference(StrictModel):
    kind: Literal['tire', 'vehicle', 'test_event', 'change_event', 'recall']
    snapshot_id: str | None = Field(default=None, min_length=1, max_length=64)
    variant_id: str | None = Field(default=None, min_length=1, max_length=64)
    event_id: str | None = Field(default=None, min_length=1, max_length=64)
    event_revision: StrictInt | None = Field(default=None, ge=1)
    change_id: str | None = Field(default=None, min_length=1, max_length=64)
    recall_revision_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode='after')
    def complete_reference(self):
        if self.kind == 'recall':
            valid = (self.snapshot_id and 'recall_revision_id' in self.model_fields_set
                     and not any((self.variant_id, self.event_id, self.event_revision, self.change_id)))
        elif self.kind == 'change_event':
            valid = self.change_id and not any((self.snapshot_id, self.variant_id, self.event_id, self.event_revision))
        elif self.kind == 'test_event':
            valid = self.event_id and self.event_revision and not self.snapshot_id and not self.variant_id and not self.change_id
        else:
            valid = self.snapshot_id and not self.event_id and not self.event_revision and not self.change_id
            valid = valid and (bool(self.variant_id) if self.kind == 'tire' else not self.variant_id)
        if not valid or self.kind != 'recall' and self.recall_revision_id is not None:
            raise ValueError('请提供该类证据的精确版本标识')
        return self


class PreparePack(StrictModel):
    mode: Literal['current', 'history']
    references: list[PackReference] = Field(default_factory=list, max_length=6)
    source_id: str | None = Field(default=None, max_length=80)
    query_kind: Literal['tire', 'recall_by_campaign'] | None = None
    query: TireQuery | RecallQuery | None = None
    variant_ids: list[str] = Field(default_factory=list, max_length=6)
    consent_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode='after')
    def mode_scope(self):
        if self.mode == 'current':
            if not self.source_id or self.query is None or self.references:
                raise ValueError('当前参数分析须先指定轮胎来源与在线查询，不混入历史引用')
            if self.query_kind == 'recall_by_campaign':
                if self.source_id != RECALL_SOURCE_ID or not isinstance(self.query, RecallQuery) or self.variant_ids:
                    raise ValueError('当前召回分析须明确按公告编号在线查询，不接受轮胎版本或名称发现查询')
            elif not isinstance(self.query, TireQuery) or self.source_id == RECALL_SOURCE_ID:
                raise ValueError('召回查询须显式指定 recall_by_campaign 类型')
        elif not self.references or self.source_id or self.query or self.query_kind or self.variant_ids or self.consent_id:
            raise ValueError('历史分析须显式选择精确证据版本')
        if len({digest(r.model_dump()) for r in self.references}) != len(self.references):
            raise ValueError('证据引用不能重复')
        if len(set(self.variant_ids)) != len(self.variant_ids) or any(not v or len(v) > 64 for v in self.variant_ids):
            raise ValueError('精确版本标识无效')
        return self


class PackBuilder:
    def __init__(self):
        self.evidence = []
        self.facts = []
        self.conflicts = []
        self.privacy = 'public'
        self.selected_tires = []
        self.field_candidates = {}

    def add(self, *, kind: str, label: str, provenance: dict, values: dict, private=False, field_codes=None):
        if private:
            self.privacy = 'private'
        evidence_id = f'e{len(self.evidence) + 1}'
        self.evidence.append({'id': evidence_id, 'kind': kind, 'label': label, **provenance})
        for index, (name, value) in enumerate(values.items(), start=1):
            if len(self.facts) >= 400:
                raise HTTPException(422, '证据字段过多，请缩小分析范围')
            rendered = ('来源未标明' if value is None else '是' if value is True else '否' if value is False
                        else str(value) if isinstance(value, str) else stable_json(value))
            self.facts.append({'id': f'f{len(self.facts) + 1}', 'evidence_id': evidence_id,
                              'field': name, 'field_code': (field_codes or {}).get(name, f'{kind}.field_{index}'),
                              'value': value, 'text': f'{label}：{name} = {rendered}'})
        return evidence_id

    def tire(self, db, row, source_provenance: dict, registry):
        from .identity_resolution import require_ai_identity
        require_ai_identity(db, [row['id']])
        from .lifecycle import annotate_variants
        from .curation import FIELD_CATALOG
        from .field_authority import canonical_field, evidence_value_key
        from .field_evidence import snapshot_field_candidates
        if annotate_variants(db, [row])[0]['lifecycle']['state'] == 'revoked':
            raise HTTPException(409, '已撤销版本不进入常规 AI 分析，请先核对版本状态')
        source_id = source_provenance['source_id']
        self.selected_tires.append(({**row, 'snapshot_id': source_provenance['snapshot_id']}, source_id))
        source = next((s for s in registry.sources() if s['id'] == source_id), {})
        source_class = source.get('source_class', 'unclassified')
        label = f'{row["brand"]} {row["model"]} · {row["size"]} · {row.get("manufacturer_product_code") or "代码未确认"}'
        names = {'brand': '品牌', 'model': '型号', 'region': '区域', 'size': '尺寸',
                 'manufacturer_product_code': '厂商产品代码', 'load_index': '载重指数',
                 'speed_rating': '速度级别', 'xl': 'XL', 'hl': 'HL',
                 'oe_mark': 'OE 标记', 'acoustic_technology': '静音技术', 'run_flat': '防爆'}
        fields = {name: row.get(key) for key, name in names.items()}
        codes = {name: key for key, name in names.items()}
        for key, value in row.get('facts', {}).items():
            if key not in {'evidence_spans', 'source_updated_at', 'source_start_date', 'source_end_date', 'source_field_conflicts'}:
                name = FIELD_CATALOG.get(key, {}).get('label', key) + f' [{key}]'
                fields[name] = value
                codes[name] = canonical_field(key)
        evidence_id = self.add(kind=source_class, label=label, values=fields, field_codes=codes,
                 provenance={**source_provenance, 'variant_id': row['id']},
                 private=source_class not in {'manufacturer_official', 'regulatory'})
        verified_at = source_provenance.get('verified_at')
        if isinstance(verified_at, str):
            verified_at = datetime.fromisoformat(verified_at.replace('Z', '+00:00'))
        candidates = snapshot_field_candidates(db, source_provenance['snapshot_id'], row['id'], registry,
            row=row, verified_at=verified_at)
        for candidate in candidates:
            candidate['evidence_id'] = evidence_id
            candidate['fact_ids'] = [fact['id'] for fact in self.facts
                if fact['evidence_id'] == evidence_id and fact['field_code'] == candidate['field']
                and evidence_value_key(fact['value']) == evidence_value_key(candidate['value'])]
        self.field_candidates.setdefault(row['id'], []).extend(candidates)
        self.conflicts.extend(QueryService.current_source_conflicts([row], source_id))

    def recall(self, db, snapshot_id, recall_revision_id, *, state, consent_id=None, verification_id=None):
        from .recall_evidence import RECALL_FIELDS, canonical_recall_facts, load_recall_evidence
        material = load_recall_evidence(db, snapshot_id, recall_revision_id, verification_id=verification_id)
        if len(self.facts) + 4 + len(material['records']) * len(RECALL_FIELDS) > 400:
            raise HTTPException(422, '召回公告字段过多，不能静默截断公告记录')
        evidence_id = f'e{len(self.evidence) + 1}'
        evidence = {**material['evidence'], 'id': evidence_id, 'data_state': state, 'consent_id': consent_id}
        self.evidence.append(evidence)
        for fact in canonical_recall_facts(evidence, material['records']):
            self.facts.append({'id': f'f{len(self.facts) + 1}', 'evidence_id': evidence_id, **fact})


def shared_field_materials(resolutions):
    """Losslessly intern frozen material; do not drop candidates to fit the limit."""
    materials, by_content = {}, {}

    def reference(value):
        key = stable_json(value)
        if key not in by_content:
            ref = f'm{len(materials) + 1}'
            by_content[key] = ref
            materials[ref] = deepcopy(value)
        return by_content[key]

    encoded = deepcopy(resolutions)
    individual = {'id', 'field', 'source_field', 'present', 'value', 'evidence_locator', 'fact_ids'}
    for resolution in encoded:
        for field in resolution['fields']:
            field['reasons_ref'] = reference(field.pop('reasons'))
            for candidate in field['candidates']:
                authority = candidate.pop('authority')
                dimensions = candidate.pop('dimensions')
                context = {key: candidate.pop(key) for key in list(candidate) if key not in individual}
                candidate['context_ref'] = reference(context)
                candidate['authority_ref'] = reference(authority)
                candidate['dimensions'] = {name: {'material_ref': reference(value)}
                                           for name, value in dimensions.items()}
    return {'field_resolutions': encoded, 'field_resolution_format': 'shared-materials@1',
            'field_resolution_materials': materials,
            'field_resolution_notice': '字段决策按本包冻结。context_ref、authority_ref、reasons_ref 和各维度 material_ref '
                '均引用 field_resolution_materials 中的同包材料；完整展开后才是候选和依据，不查询外部内容。'}


def frozen_field_resolutions(payload):
    """Expand only the stored pack's own frozen material, never today's policy or DB."""
    resolutions = deepcopy(payload.get('field_resolutions'))
    if payload.get('field_resolution_format') is None:
        return resolutions
    if payload['field_resolution_format'] != 'shared-materials@1' or not isinstance(resolutions, list):
        raise ValueError('invalid_frozen_field_format')
    if len(stable_json(payload).encode('utf-8')) > 44000 or len(resolutions) > 6:
        raise ValueError('frozen_field_contract_too_large')
    materials = payload.get('field_resolution_materials')
    if not isinstance(materials, dict):
        raise ValueError('invalid_frozen_field_materials')

    expanded_bytes = 0
    reference_keys = {'context_ref', 'authority_ref', 'reasons_ref', 'material_ref'}

    def material(ref, expected):
        nonlocal expanded_bytes
        if not isinstance(ref, str) or ref not in materials or not isinstance(materials[ref], expected):
            raise ValueError('invalid_frozen_field_reference')
        if isinstance(materials[ref], dict) and reference_keys & materials[ref].keys():
            raise ValueError('nested_frozen_field_reference')
        expanded_bytes += len(stable_json(materials[ref]).encode('utf-8'))
        if expanded_bytes > 2_000_000:
            raise ValueError('frozen_field_expansion_too_large')
        return deepcopy(materials[ref])

    candidate_count = 0
    for resolution in resolutions:
        if not isinstance(resolution, dict) or not isinstance(resolution.get('fields'), list):
            raise ValueError('invalid_frozen_field_resolution')
        for field in resolution['fields']:
            if not isinstance(field, dict) or not isinstance(field.get('candidates'), list):
                raise ValueError('invalid_frozen_field_candidates')
            field['reasons'] = material(field.pop('reasons_ref'), list)
            for candidate in field['candidates']:
                candidate_count += 1
                if not isinstance(candidate, dict) or candidate_count > 800:
                    raise ValueError('invalid_frozen_field_candidate')
                context = material(candidate.pop('context_ref'), dict)
                if context.keys() & candidate.keys():
                    raise ValueError('overlapping_frozen_field_material')
                candidate.update(context)
                candidate['authority'] = material(candidate.pop('authority_ref'), dict)
                if not isinstance(candidate.get('dimensions'), dict) or any(
                        not isinstance(value, dict) or set(value) != {'material_ref'}
                        for value in candidate['dimensions'].values()):
                    raise ValueError('invalid_frozen_field_dimensions')
                candidate['dimensions'] = {name: material(value['material_ref'], dict)
                                           for name, value in candidate['dimensions'].items()}
        if resolution.get('fingerprint') != digest({key: value for key, value in resolution.items() if key != 'fingerprint'}):
            raise ValueError('invalid_frozen_field_fingerprint')
    return resolutions


def _device_pack_origin(row: AIEvidencePack) -> bool:
    """Authoritative device-origin discriminator for read views (roundtable D1).

    A preparation row bound by its unique ai_pack_id FK is the structural
    marker; payload origin/purpose keys stay display-only redundancy. Rows
    detached from a session simply read as ordinary warehouse packs.
    """
    from .device_ai_models import DeviceAIPreparation
    session = object_session(row)
    if session is None:
        return False
    return session.scalar(select(DeviceAIPreparation.id).where(
        DeviceAIPreparation.ai_pack_id == row.id,
        DeviceAIPreparation.actor_session_id == row.actor_session_id)) is not None


def pack_view(row: AIEvidencePack) -> dict:
    content = dict(row.payload)
    if content.get('field_resolution_format') is not None:
        content['field_resolutions'] = frozen_field_resolutions(content)
        for key in ('field_resolution_format', 'field_resolution_materials', 'field_resolution_notice'):
            content.pop(key, None)
    view = {'id': row.id, 'mode': row.mode, 'data_state': row.data_state, 'privacy_class': row.privacy_class,
            'created_at': timestamp(row.created_at), 'expires_at': timestamp(row.expires_at),
            'fingerprint': row.fingerprint, **content}
    if _device_pack_origin(row):
        # Roundtable route #10/#8: device packs carry a server-derived origin
        # marker; warehouse packs are never retroactively labelled and keep
        # their exact legacy DTO shape.
        view['origin'] = 'device_history'
    return view


def evidence_identity_binding(contract):
    """Only immutable authority fields bind a packet; labels and candidates may grow."""
    fields = ('schema', 'state', 'current_key', 'current_identity', 'identity_status')
    if not isinstance(contract, dict) or any(key not in contract for key in fields):
        return None
    return {key: contract[key] for key in fields}


def require_frozen_identity_contracts(db, evidence):
    ids = {item['variant_id'] for item in evidence if item.get('variant_id')}
    context = contract_context(db, ids)
    for item in evidence:
        if not item.get('variant_id'):
            continue
        frozen = evidence_identity_binding(item.get('identity_contract'))
        current = evidence_identity_binding(contract_metadata(db, item['variant_id'], context=context))
        if frozen is None or frozen['state'] != 'current' or digest(frozen) != digest(current):
            raise HTTPException(409, {'code': 'ai_evidence_identity_contract_stale',
                'message': '证据包缺少现行身份合同或绑定已变化，请重新准备证据包；旧包与报告保持原样'})


def require_frozen_field_contract(payload):
    """Reject stale pending authorization before any AIRequest or model call."""
    from .field_authority import policy_descriptor
    # Rule drafts authorize a capability catalog, not parameter evidence.
    if (payload.get('purpose') == 'rule_draft' and payload.get('retrieval') == 'frozen_monitor_capability_catalog'
            and payload.get('evidence') == [] and payload.get('facts') == []):
        return
    policy = policy_descriptor()
    try:
        resolutions = frozen_field_resolutions(payload)
    except (ValueError, TypeError, KeyError):
        resolutions = None
    ids = {item['variant_id'] for item in payload.get('evidence', [])
           if item.get('variant_id') and not item.get('change_id')}
    valid = (payload.get('field_policy') == policy and isinstance(resolutions, list)
             and all(isinstance(fact.get('field_code'), str) and fact['field_code']
                     for fact in payload.get('facts', [])))
    if valid:
        valid = (len(resolutions) == len(ids)
                 and all(isinstance(item, dict) for item in resolutions)
                 and {item.get('variant_id') for item in resolutions} == ids
                 and all(item.get('policy') == policy and item.get('scope') == 'selected_evidence'
                     and item.get('fingerprint') == digest({key: value for key, value in item.items()
                                                           if key != 'fingerprint'})
                     for item in resolutions))
    if not valid:
        raise HTTPException(409, {'code': 'ai_evidence_field_contract_stale',
            'message': '证据包缺少准备时字段决策或字段策略已变化，请重新准备证据包并授权；旧包与完成报告保持原样'})


async def prepare_pack(db, registry, payload: PreparePack, session_id: str, *, recall_adapter=None) -> dict:
    builder = PackBuilder()
    state, query_result = 'local_snapshot', None
    if payload.mode == 'current' and payload.query_kind == 'recall_by_campaign':
        from .recall_models import RecallLiveRequest, RecallVerification
        from .recalls import RecallService
        if recall_adapter is None:
            from .adapters import nhtsa
            recall_adapter = nhtsa
        request = RecallLiveRequest(query=payload.query, fallback_policy='ask', consent_id=payload.consent_id)
        query_result = await RecallService(db, recall_adapter, policy_registry=registry).execute(
            request, session_id, audience='ai_current')
        ref = query_result.get('analysis_reference')
        if query_result['data_state'] not in {'live', 'live_verified_304', 'local_snapshot'} or ref is None:
            return {'pack': None, 'query_result': query_result, 'reason': query_result.get('reason') or 'no_matching_evidence'}
        state = query_result['data_state']
        verification_id = None
        if state in {'live', 'live_verified_304'}:
            verification_id = db.scalar(select(RecallVerification.id).where(
                RecallVerification.query_id == query_result['query_id'], RecallVerification.snapshot_id == ref['snapshot_id']))
            if verification_id is None:
                raise HTTPException(409, '本次召回查询缺少正式核验记录')
        builder.recall(db, ref['snapshot_id'], ref['recall_revision_id'], state=state,
                       consent_id=query_result['consent_id'], verification_id=verification_id)
    elif payload.mode == 'current':
        request = LiveQueryRequest(query=payload.query, fallback_policy='ask', consent_id=payload.consent_id)
        query_result = await QueryService(db, registry).execute(payload.source_id, request, session_id, audience='ai_current')
        if query_result['data_state'] not in {'live', 'live_verified_304', 'local_snapshot'} or not query_result['variants']:
            return {'pack': None, 'query_result': query_result, 'reason': query_result.get('reason') or 'no_matching_evidence'}
        rows = [row for row in query_result['variants'] if not payload.variant_ids or row['id'] in payload.variant_ids]
        if not rows or payload.variant_ids and set(payload.variant_ids) != {row['id'] for row in rows}:
            return {'pack': None, 'query_result': query_result, 'reason': 'exact_variant_not_returned'}
        if len(rows) > 6:
            raise HTTPException(422, '本次结果超过 6 个精确版本，请先选择要分析的版本')
        state = query_result['data_state']
        for row in rows:
            builder.tire(db, row, {**query_result['provenance'][0], 'verified_at': query_result['verified_at'],
                                  'data_state': state, 'consent_id': query_result['consent_id']}, registry)
    else:
        for ref in payload.references:
            if ref.kind == 'recall':
                builder.recall(db, ref.snapshot_id, ref.recall_revision_id, state=state)
            elif ref.kind == 'change_event':
                from .ai_monitoring import add_change_event
                add_change_event(builder, db, registry, ref.change_id)
            elif ref.kind == 'tire':
                snapshot = db.get(Snapshot, ref.snapshot_id)
                row = next((v for v in snapshot.parsed_variants if v['id'] == ref.variant_id), None) if snapshot else None
                if row is None:
                    raise HTTPException(404, '该精确版本不在所选正式快照中')
                verified = db.scalar(select(Verification.verified_at).where(Verification.snapshot_id == snapshot.id)
                                     .order_by(desc(Verification.verified_at)).limit(1))
                builder.tire(db, row, {**provenance(snapshot), 'verified_at': timestamp(verified),
                                      'data_state': state, 'consent_id': None}, registry)
            elif ref.kind == 'vehicle':
                from .vehicles import VehicleSnapshot, vehicle_provenance
                snapshot = db.get(VehicleSnapshot, ref.snapshot_id)
                if snapshot is None:
                    raise HTTPException(404, '未找到正式车型证据')
                data = snapshot.payload
                builder.add(kind='oem_fitment', label=data['vehicle']['model'] + ' · ' + data['vehicle']['generation'],
                    provenance={**vehicle_provenance(snapshot), 'data_state': state, 'verified_at': None},
                    values={'车型': data['vehicle'], '配置版本': data['trims'], '轮毂与轴位': data['fitments']})
            else:
                from .test_events import latest
                event = latest(db, ref.event_id, ref.event_revision)
                if event.state == 'revoked':
                    raise HTTPException(409, '已撤销测试事件不参与 AI 分析')
                data = event.payload
                values = {'发布日期': data['publication_date'], '测试尺寸': data['tested_size'],
                          '条件': data['conditions'], '车辆': data['vehicle'], '路面': data['surface'],
                          '覆盖范围': data['coverage'], '来源参测总数': data['reported_participants']}
                for i, measurement in enumerate(data['measurements']):
                    person = next(p for p in data['participants'] if p['key'] == measurement['participant_key'])
                    metric = next(m for m in data['metrics'] if m['key'] == measurement['metric_key'])
                    values[f'本场成绩 {i + 1}'] = {'参测胎': person, '指标与条件': metric, **measurement}
                builder.add(kind='manual_test_' + data['relationship'], label='人工记录 · ' + data['title'],
                    provenance={'event_id': event.event_id, 'revision': event.revision, 'source_url': data['source_url'],
                                'observed_at': timestamp(event.created_at), 'verified_at': None,
                                'data_state': state, 'verification_status': 'unverified'}, values=values, private=True)
    from .field_authority import policy_descriptor, resolve_fields
    from .field_evidence import complete_missing_candidates
    # Candidate collection is limited to the exact selected snapshot members.
    # Outside sources only contribute the separate bounded existence warning.
    field_resolutions = []
    for variant_id, candidates in sorted(builder.field_candidates.items()):
        completed = complete_missing_candidates(candidates)
        for candidate in completed:
            if not candidate['present']:
                candidate['fact_ids'] = []
        field_resolutions.append(resolve_fields(completed, variant_id=variant_id, scope='selected_evidence', data_state=state))
    for resolution in field_resolutions:
        for field in resolution['fields']:
            if field['state'] in {'conflict_preferred', 'conflict_tied'}:
                builder.conflicts.append({'variant_id': resolution['variant_id'], 'field': field['field'],
                    'scope': 'selected_versions', 'fact_ids': sorted({fact_id for candidate in field['candidates']
                        for fact_id in candidate.get('fact_ids', [])}), 'resolution': 'unresolved',
                    'default_state': field['state']})
    if payload.mode == 'history':
        from .ai_conflicts import unselected_conflicts
        outside, private = unselected_conflicts(db, registry, builder.selected_tires)
        builder.conflicts.extend(outside)
        if private:
            builder.privacy = 'private'
    # Freeze authority only while preparing a new pack. Never retrofit stored
    # packets or reports with today's identity mapping.
    ids = {item['variant_id'] for item in builder.evidence if item.get('variant_id')}
    contracts = contract_context(db, ids)
    for item in builder.evidence:
        if item.get('variant_id'):
            item['identity_contract'] = contract_metadata(db, item['variant_id'], context=contracts)
    content = {'retrieval': 'exact_structured_lookup', 'evidence': builder.evidence, 'facts': builder.facts,
               'field_policy': policy_descriptor(), **shared_field_materials(field_resolutions),
               'conflicts': builder.conflicts, 'query_id': query_result['query_id'] if query_result else None,
               'consent_id': query_result['consent_id'] if query_result else None,
               'source_state': 'snapshot' if state == 'local_snapshot' else 'live'}
    if any(reference.kind == 'change_event' for reference in payload.references):
        content['purpose'] = 'monitor_explanation'
    if any(item.get('evidence_type') == 'recall' for item in builder.evidence):
        from .recall_evidence import recall_boundary_descriptor, recall_policy_descriptor
        content.update(purpose='recall_research', recall_policy=recall_policy_descriptor(),
                       recall_boundary=recall_boundary_descriptor())
    if len(stable_json(content).encode('utf-8')) > 44000:
        raise HTTPException(422, '证据包过大，请缩小版本或场次范围；不会静默截断证据')
    if payload.mode == 'current':
        shared = QueryService(db, registry)
        shared.lock_ingestion()
        run = db.get(QueryRun, query_result['query_id'])
        if run is None:
            raise HTTPException(409, {'code': 'source_access_pin_missing'})
        try:
            shared.assert_source_access(run)
        except SourceAccessBlocked as error:
            shared.block_source_access(run, error)
            if payload.query_kind == 'recall_by_campaign':
                from .recalls import RecallService
                result = RecallService(db, None).response(payload.query.campaign_number, run.state,
                                                         query_id=run.id, reason=run.reason)
                return {'pack': None, 'query_result': result, 'reason': error.code}
            return {'pack': None, 'query_result': shared.result(run), 'reason': error.code}
    pack = AIEvidencePack(actor_session_id=session_id, mode=payload.mode, data_state=state,
        privacy_class=builder.privacy, payload=content, fingerprint=digest(content),
        expires_at=utcnow() + timedelta(minutes=2 if payload.mode == 'current' else 30))
    db.add(pack)
    db.flush()
    QueryService(db, None).audit(session_id, 'ai_evidence_pack_created', pack_id=pack.id,
                               data_state=state, fingerprint=pack.fingerprint)
    db.commit()
    return {'pack': pack_view(pack), 'query_result': query_result, 'reason': None}
