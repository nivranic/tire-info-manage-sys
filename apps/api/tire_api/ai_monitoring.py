"""Frozen change-event evidence, distinct from competing-source fact conflicts."""
from fastapi import HTTPException
from sqlalchemy import select

from .db import ChangeEvent, Snapshot, TireVariant
from .domain import digest, stable_json
from .knowledge_index import FIELD_LABELS
from .service import business_facts, timestamp


def add_change_event(builder, db, registry, change_id):
    change = db.get(ChangeEvent, change_id)
    if change is None:
        raise HTTPException(404, '未找到正式变化事件')
    from .identity_resolution import require_ai_identity
    require_ai_identity(db, [change.variant_id])
    # Select structured payload/provenance only, never the downloaded page body.
    ids = [value for value in (change.snapshot_id, change.previous_snapshot_id) if value]
    snapshots = {row.id: row for row in db.execute(select(Snapshot.id, Snapshot.source_id, Snapshot.source_url,
        Snapshot.raw_hash, Snapshot.parser_version, Snapshot.observed_at, Snapshot.parsed_variants).where(Snapshot.id.in_(ids)))}
    after = snapshots.get(change.snapshot_id)
    before = snapshots.get(change.previous_snapshot_id)
    if (after is None or after.source_id != change.source_id
            or change.previous_snapshot_id and (before is None or before.source_id != change.source_id)):
        raise HTTPException(409, '变化前后证据链不完整，不能解释此事件')
    if change.kind not in {'facts_changed', 'variant_observed'}:
        raise HTTPException(422, '当前仅支持参数变化和首次观察事件')
    if (change.kind == 'facts_changed') != bool(before):
        raise HTTPException(409, '变化类型与历史证据链不一致')
    from .lifecycle import annotate_variants
    if annotate_variants(db, [{'id': change.variant_id}])[0]['lifecycle']['state'] == 'revoked':
        raise HTTPException(409, '变化事件的精确版本已撤销，请先核对身份状态')
    sides = {}
    for side, snapshot in (('before', before), ('after', after)):
        if snapshot is None:
            sides[side] = {}
            continue
        members = [row for row in snapshot.parsed_variants if row.get('id') == change.variant_id]
        if len(members) != 1:
            raise HTTPException(409, '变化事件的精确 SKU 不属于前后快照成员集合')
        sides[side] = business_facts(members[0].get('facts', {}))
    source = next((value for value in registry.sources() if value['id'] == change.source_id), {})
    source_class = source.get('source_class', 'unclassified')
    identity = db.get(TireVariant, change.variant_id)
    if identity is None:
        raise HTTPException(409, '变化事件缺少精确 SKU 身份')
    label = f'{identity.identity.get("brand", "")} {identity.identity.get("model", "")} · {identity.identity.get("size", "")} · 历史变化'
    values = {}
    for key, delta in sorted(change.changes.items()):
        if not isinstance(delta, dict) or set(delta) != {'before', 'after', 'before_present', 'after_present'}:
            raise HTTPException(409, '历史变化缺少字段存在性标记，请核对原始事件')
        if type(delta['before_present']) is not bool or type(delta['after_present']) is not bool:
            raise HTTPException(409, '历史字段存在性标记无效')
        for side in ('before', 'after'):
            if (delta[side + '_present'] != (key in sides[side])
                    or digest(delta[side]) != digest(sides[side].get(key))):
                raise HTTPException(409, '冻结差异与前后精确快照不一致，不能生成事实解释')
        values[f'{FIELD_LABELS.get(key, key)} [{key}] · 冻结差异'] = delta
    if not values:
        raise HTTPException(409, '变化事件没有可解释的字段差异')
    values['事件边界'] = ('本工作区在该来源首次观察到这个精确版本，不代表产品刚发布或新上市'
                        if change.kind == 'variant_observed' else '所示是两次正式采纳记录之间的参数变化，不代表当前值')
    provenance = {'change_id': change.id, 'variant_id': change.variant_id, 'source_id': change.source_id,
        'source_class': source_class, 'snapshot_id': after.id, 'source_url': after.source_url, 'raw_hash': after.raw_hash,
        'parser_version': after.parser_version, 'observed_at': timestamp(after.observed_at), 'verified_at': None,
        'change_observed_at': timestamp(change.observed_at), 'change_kind': change.kind,
        'previous_snapshot_id': before.id if before else None, 'previous_source_url': before.source_url if before else None,
        'previous_raw_hash': before.raw_hash if before else None, 'previous_observed_at': timestamp(before.observed_at) if before else None,
        'data_state': 'local_snapshot', 'changes_hash': digest(change.changes), 'source_state': 'snapshot'}
    start = len(builder.facts)
    builder.add(kind='change_event', label=label, provenance=provenance, values=values,
                private=source_class not in {'manufacturer_official', 'regulatory'})
    # Human-readable canonical rendering preserves absent versus explicitly null.
    for fact in builder.facts[start:]:
        value = fact['value']
        if not isinstance(value, dict):
            continue
        def rendered(side):
            if not value[side + '_present']:
                return '未声明此字段'
            return '明确未知（null）' if value[side] is None else stable_json(value[side])
        fact['text'] = f'{label}：{fact["field"]}，{rendered("before")} → {rendered("after")}'
