"""Exact accepted recall observations and pure, frozen announcement facts.

Campaign/product scope never implies tire SKU, DOT/TIN or physical applicability.
The pure validators below do not fetch, parse, mutate or consult current policy.
"""
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
import hashlib
import re

from fastapi import HTTPException
from sqlalchemy import desc, select

from .db import QueryRun
from .domain import digest, stable_json
from .recall_models import SOURCE_ID, RecallQuery, RecallRevision, RecallSnapshot, RecallVerification
from .recalls import campaign_url, canonical_records
from .service import timestamp

# Archived contracts are immutable. A future policy adds another registry entry
# and renderer; it must not edit v1 fields, text or validation rules in place.
_V1_RECORD_FIELDS = {
    'campaign_number': '公告编号', 'manufacturer': '公告制造商',
    'report_received_date': '报告接收日期', 'report_received_date_raw': '报告接收日期原文',
    'component': '部件', 'potential_units': '公告潜在涉及数量', 'summary': '公告摘要',
    'consequence': '公告后果描述', 'remedy': '公告补救措施', 'notes': '公告备注',
    'make': '公告产品品牌', 'model': '公告产品型号', 'model_year_raw': '来源车型年原文（非轮胎生产年）',
    'applicability': '实物适用性评估状态',
}
_V1_OBSERVATION_FIELDS = {'campaign_number': '公告编号', 'record_count': '本次返回记录数',
                         'observation_kind': '本次观察类型', 'applicability': '实物适用性评估状态'}
_V1_BOUNDARY = {'policy': 'recall-fact-selection@1', 'applicability': 'not_assessed',
    'mode': 'announcement_facts_only',
    'notice': '仅解释所选 NHTSA 公告或查询观察中的事实；DOT/TIN、生产批次、具体实物适用性和安全结论均未评估。'
              '产品名称相同不证明受影响；空响应不表示无召回、无风险或召回解除。'
              '首次观察时间不等于公告发布时间；冻结的历史证据不代表当前最新状态。'}
_V1_POLICY = {'version': 'recall-fact-selection@1', 'digest': digest({
    'record_fields': _V1_RECORD_FIELDS, 'observation_fields': _V1_OBSERVATION_FIELDS,
    'boundary': _V1_BOUNDARY, 'record_identity': 'canonical-multiset-sha256-occurrence@1',
    'fact_text': 'campaign-and-canonical-record-ordinal@1',
    'claims': 'fact-only-one-snapshot-one-record-plus-observation@1', 'uncertainty': 'empty'})}
CURRENT_RECALL_POLICY_VERSION = 'recall-fact-selection@1'
RECALL_FIELDS = deepcopy(_V1_RECORD_FIELDS)
OBSERVATION_FIELDS = deepcopy(_V1_OBSERVATION_FIELDS)
FACT_KEYS = ('field', 'field_code', 'value', 'text', 'domain', 'scope', 'record_key')
HASH = re.compile(r'[0-9a-f]{64}')


def frozen_recall_contract(version):
    """Select a retained contract explicitly, independently of the active policy."""
    if version != 'recall-fact-selection@1':
        raise ValueError('unsupported_frozen_recall_policy')
    return deepcopy({'policy': _V1_POLICY, 'boundary': _V1_BOUNDARY,
                     'record_fields': _V1_RECORD_FIELDS, 'observation_fields': _V1_OBSERVATION_FIELDS})


def recall_boundary_descriptor():
    return frozen_recall_contract(CURRENT_RECALL_POLICY_VERSION)['boundary']


def recall_policy_descriptor():
    return frozen_recall_contract(CURRENT_RECALL_POLICY_VERSION)['policy']


def recall_field_authority(field):
    name = field.removeprefix('recall.') if isinstance(field, str) and field.startswith('recall.') else None
    if name not in RECALL_FIELDS and name not in OBSERVATION_FIELDS:
        return {'tier': None, 'rule': 'field_not_supported', 'explanation': '该召回字段没有可核对的权威规则'}
    if name in {'applicability', 'observation_kind'}:
        return {'tier': None, 'rule': 'recall:system_boundary', 'explanation': '这是系统观察分类或未评估边界，不是实物适用性结论'}
    return {'tier': 1, 'rule': 'recall:regulatory',
            'explanation': '正式 NHTSA 公告字段采用监管来源依据；权威不等于具体实物受影响或安全'}


def record_scopes(records):
    occurrences = Counter()
    result = []
    for index, record in enumerate(records):
        fingerprint = digest(record)
        occurrences[fingerprint] += 1
        occurrence = occurrences[fingerprint]
        result.append({'record_key': f'{fingerprint}:{occurrence}', 'record_hash': fingerprint,
                       'occurrence': occurrence, 'index': index})
    return result


def _v1_label(campaign, empty=False):
    return f'NHTSA 轮胎召回 {campaign}' + (' · 本次空响应观察' if empty else ' · 公告历史证据')


def _v1_canonical_records(records, campaign):
    """Archived normalized fields; do not reparse using a future source DTO."""
    if not isinstance(records, list) or len(records) > 1000:
        raise ValueError('invalid_frozen_recall_records')
    for record in records:
        if (not isinstance(record, dict) or set(record) != set(_V1_RECORD_FIELDS)
                or record['campaign_number'] != campaign or record['applicability'] != 'not_assessed'):
            raise ValueError('invalid_frozen_recall_record')
        units = record['potential_units']
        if units is not None and (type(units) is not int or units < 0):
            raise ValueError('invalid_frozen_recall_units')
        for field in set(_V1_RECORD_FIELDS) - {'potential_units'}:
            value = record[field]
            if value is not None:
                if not isinstance(value, str) or len(value) > 100000 or '\x00' in value:
                    raise ValueError('invalid_frozen_recall_text')
                value.encode('utf-8', errors='strict')
        received = record['report_received_date']
        if received is not None and date.fromisoformat(received).isoformat() != received:
            raise ValueError('invalid_frozen_recall_date')
    return sorted(records, key=digest)


def canonical_recall_facts(evidence, records, *, policy_version=None):
    """Return fact material without packet-local id/evidence_id; never truncate."""
    contract = frozen_recall_contract(policy_version or CURRENT_RECALL_POLICY_VERSION)
    campaign = evidence['campaign_number']
    canonical = _v1_canonical_records(records, campaign)
    if canonical != records or evidence['records_hash'] != digest(records):
        raise ValueError('recall_record_material_mismatch')
    scopes = record_scopes(records)
    if evidence['record_scopes'] != scopes or evidence['record_count'] != len(records):
        raise ValueError('recall_record_scope_mismatch')
    result = []

    def add(label, name, title, value, scope, key=None):
        rendered = '来源未标明' if value is None else value if isinstance(value, str) else stable_json(value)
        result.append({'field': title, 'field_code': 'recall.' + name, 'value': deepcopy(value),
            'text': f'{label}：{title} = {rendered}', 'domain': 'recall', 'scope': scope, 'record_key': key})

    values = {'campaign_number': campaign, 'record_count': len(records),
              'observation_kind': 'records' if records else 'empty', 'applicability': 'not_assessed'}
    for name, title in contract['observation_fields'].items():
        add(_v1_label(campaign, not records), name, title, values[name], 'observation')
    for scope, record in zip(scopes, records, strict=True):
        label = (f'NHTSA {campaign} · 公告产品 {record["make"] or "品牌未标明"} / '
                 f'{record["model"] or "型号未标明"} · 规范记录 {scope["index"] + 1}')
        for name, title in contract['record_fields'].items():
            add(label, name, title, record[name], 'record', scope['record_key'])
    return result


def _valid_time(value):
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None
    except ValueError:
        return False


def validate_frozen_recall_evidence(evidence, facts, *, policy_version='recall-fact-selection@1'):
    """Validate complete frozen material without today's database or policy."""
    try:
        contract = frozen_recall_contract(policy_version)
        record_fields = contract['record_fields']
        campaign = evidence['campaign_number']
        if not isinstance(campaign, str) or not re.fullmatch(r'[0-9]{2}T[0-9]{6}', campaign):
            raise ValueError('invalid_frozen_recall_campaign')
        count = evidence['record_count']
        if (evidence.get('evidence_type') != 'recall' or evidence.get('kind') != 'regulatory'
                or evidence.get('source_class') != 'regulatory' or evidence.get('source_id') != 'nhtsa-us-recalls'
                or evidence.get('region') != 'US' or evidence.get('source_url') !=
                    'https://api.nhtsa.gov/recalls/campaignNumber?campaignNumber=' + campaign
                or evidence.get('content_type') != 'application/json' or evidence.get('query_key') != digest({'campaign_number': campaign})
                or evidence.get('applicability') != 'not_assessed' or type(count) is not int or not 0 <= count <= 1000
                or evidence.get('observation_kind') != ('records' if count else 'empty')
                or evidence.get('label') != _v1_label(campaign, not count)
                or any(not isinstance(evidence.get(key), str) or not evidence[key]
                       for key in ('snapshot_id', 'verification_id', 'verification_query_id', 'parser_version'))
                or any(not isinstance(evidence.get(key), str) or not HASH.fullmatch(evidence[key])
                       for key in ('raw_hash', 'records_hash'))
                or not _valid_time(evidence.get('observed_at')) or not _valid_time(evidence.get('verified_at'))):
            raise ValueError('invalid_recall_frozen_provenance')
        if count:
            if (not isinstance(evidence.get('recall_revision_id'), str) or not evidence['recall_revision_id']
                    or type(evidence.get('recall_revision')) is not int or evidence['recall_revision'] < 1
                    or not isinstance(evidence.get('revision_snapshot_id'), str) or not evidence['revision_snapshot_id']
                    or not _valid_time(evidence.get('revision_observed_at'))):
                raise ValueError('invalid_recall_frozen_revision')
        elif any(evidence.get(key) is not None for key in
                 ('recall_revision_id', 'recall_revision', 'revision_snapshot_id', 'revision_observed_at')):
            raise ValueError('empty_recall_has_revision')
        if (not isinstance(evidence.get('record_scopes'), list) or len(evidence['record_scopes']) != count
                or not isinstance(facts, list) or len(facts) != 4 + count * len(record_fields)):
            raise ValueError('incomplete_recall_frozen_material')
        records = []
        for scope in evidence['record_scopes']:
            selected = [fact for fact in facts if fact.get('scope') == 'record' and fact.get('record_key') == scope['record_key']]
            if (len(selected) != len(record_fields)
                    or {fact.get('field_code') for fact in selected} != {'recall.' + name for name in record_fields}):
                raise ValueError('incomplete_recall_frozen_record')
            records.append({fact['field_code'].removeprefix('recall.'): fact['value'] for fact in selected})
        expected = canonical_recall_facts(evidence, records, policy_version=policy_version)
        actual = [{key: fact[key] for key in FACT_KEYS} for fact in facts]
        # Packet IDs are assigned elsewhere; compare the entire canonical fact multiset.
        if sorted(map(stable_json, expected)) != sorted(map(stable_json, actual)):
            raise ValueError('recall_frozen_fact_mismatch')
        if evidence.get('id') is not None and any(fact.get('evidence_id') != evidence['id'] for fact in facts):
            raise ValueError('recall_frozen_evidence_id_mismatch')
    except (KeyError, TypeError, AttributeError, UnicodeError) as error:
        raise ValueError('invalid_recall_frozen_material') from error


def load_recall_evidence(db, snapshot_id, recall_revision_id, *, verification_id=None):
    """Only accepted by-campaign evidence; exact snapshot time, never latest campaign time."""
    snapshot = db.get(RecallSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(404, '未找到正式召回快照')
    try:
        campaign = RecallQuery(campaign_number=snapshot.campaign_number).campaign_number
        query = {'campaign_number': campaign}
        records = canonical_records(snapshot.records, campaign)
        if (snapshot.source_id != SOURCE_ID or snapshot.source_url != campaign_url(campaign)
                or snapshot.query_key != digest(query) or snapshot.content_type != 'application/json'
                or records != snapshot.records or digest(records) != snapshot.records_hash
                or not isinstance(snapshot.parser_version, str) or not 1 <= len(snapshot.parser_version) <= 100
                or not snapshot.body or hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest() != snapshot.raw_hash):
            raise ValueError('recall_snapshot_integrity_failed')
        statement = (select(RecallVerification, QueryRun).join(QueryRun, QueryRun.id == RecallVerification.query_id)
            .where(RecallVerification.snapshot_id == snapshot.id, RecallVerification.query_key == snapshot.query_key,
                   RecallVerification.status.in_(('ok', 'not_modified')), QueryRun.source_id == SOURCE_ID,
                   QueryRun.query_key == snapshot.query_key)
            .order_by(desc(RecallVerification.verified_at), desc(RecallVerification.id)))
        if verification_id is not None:
            statement = statement.where(RecallVerification.id == verification_id)
        verified = db.execute(statement.limit(1)).first()
        if verified is None or verified[1].query != query:
            raise ValueError('recall_formal_verification_missing')
        verification, run = verified
        if verification.parser_identity != snapshot.parser_identity:
            raise ValueError('recall_verification_parser_mismatch')
        revision = db.get(RecallRevision, recall_revision_id) if recall_revision_id else None
        if records:
            if (revision is None or snapshot.revision != revision.revision or revision.campaign_number != campaign
                    or revision.records_hash != snapshot.records_hash or revision.records != records):
                raise HTTPException(409, '召回快照与所选内容修订不匹配')
            origin = db.get(RecallSnapshot, revision.snapshot_id)
            if (origin is None or origin.campaign_number != campaign or origin.revision != revision.revision
                    or origin.records_hash != snapshot.records_hash or origin.records != records):
                raise ValueError('recall_revision_origin_mismatch')
        elif recall_revision_id is not None or snapshot.revision is not None:
            raise HTTPException(409, '空响应观察不能绑定非空公告修订')
        evidence = {'kind': 'regulatory', 'evidence_type': 'recall', 'label': _v1_label(campaign, not records),
            'source_id': SOURCE_ID, 'source_class': 'regulatory', 'region': 'US', 'campaign_number': campaign,
            'snapshot_id': snapshot.id, 'query_key': snapshot.query_key, 'source_url': snapshot.source_url,
            'raw_hash': snapshot.raw_hash, 'records_hash': snapshot.records_hash, 'content_type': snapshot.content_type,
            'parser_version': snapshot.parser_version, 'parser_identity': deepcopy(snapshot.parser_identity),
            'observed_at': timestamp(snapshot.observed_at), 'verified_at': timestamp(verification.verified_at),
            'verification_id': verification.id, 'verification_query_id': run.id,
            'recall_revision_id': revision.id if revision else None,
            'recall_revision': revision.revision if revision else None,
            'revision_snapshot_id': revision.snapshot_id if revision else None,
            'revision_observed_at': timestamp(revision.observed_at) if revision else None,
            'observation_kind': 'records' if records else 'empty', 'record_count': len(records),
            'applicability': 'not_assessed', 'record_scopes': record_scopes(records),
            'evidence_path': f'/v1/recall-evidence/{snapshot.id}?mode=history'}
        return {'evidence': evidence, 'records': deepcopy(records)}
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise HTTPException(503, '正式召回证据完整性校验失败') from error


def recall_reference(db, snapshot):
    """Server-produced explicit binding; never guess an ID from a client revision number."""
    revision = (db.scalar(select(RecallRevision).where(RecallRevision.campaign_number == snapshot.campaign_number,
        RecallRevision.revision == snapshot.revision))) if snapshot.revision is not None else None
    ref = {'kind': 'recall', 'snapshot_id': snapshot.id, 'recall_revision_id': revision.id if revision else None}
    # Callers which offer references expose only material that will pass preparation.
    load_recall_evidence(db, snapshot.id, ref['recall_revision_id'])
    return ref
