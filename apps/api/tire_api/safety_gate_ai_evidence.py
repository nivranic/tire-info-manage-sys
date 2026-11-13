"""Versioned, exact Safety Gate alert facts; no inferred SKU applicability."""
from copy import deepcopy
from datetime import date, datetime
import re

from fastapi import HTTPException
from sqlalchemy import desc, select

from .db import QueryRun, utc, utcnow
from .domain import digest, stable_json
from .service import timestamp

SOURCE_ID = 'eu-safety-gate'
BASE = 'https://ec.europa.eu/safety-gate-alerts'
VERSION = 'safety-gate-fact-selection@1'
_FACT_FIELDS = {
    'category': ('category', '产品类别'), 'product': ('product', '产品类型'),
    'brand': ('brand', '品牌'), 'name': ('name', '产品名称'),
    'model_number': ('type_numberOfModel', '型号原文'), 'batch_number': ('batchNumber', '批次原文'),
    'barcode': ('barcode', '条码原文'), 'risk_type': ('riskType', '风险类别原文'),
    'danger': ('danger', '风险原文'), 'measures': ('measures', '措施原文'),
    'recall_url': ('URLrecall', '来源声明的召回链接'), 'description': ('description', '描述原文'),
    'notifying_country': ('notifyingCountry', '通报国家'), 'country_of_origin': ('countryOfOrigin', '原产国'),
    'type': ('type', '通报类型'), 'level': ('level', '风险等级原文'),
    'online_trader': ('onlineTrader', '网络销售者原文'), 'company_recall_code': ('companyRecallCode', '企业召回代码'),
    'production_dates': ('productionDates', '生产日期声明原文'),
}
_FIELDS = {'report_id': '官方周报ID', 'report_reference': '官方周报编号', 'report_published_date': '周报发布日期',
    'alert_id': '原生告警ID', 'case_number': '原生通报编号', 'alert_published_date': '告警发布日期',
    'applicability': '实物适用性评估状态', **{name: pair[1] for name, pair in _FACT_FIELDS.items()}}
_LICENSE = {'distribution_id': 'http://data.europa.eu/88u/distribution/d932935c-3916-4421-a6a4-91efe196ef4b',
    'license_uri': 'http://publications.europa.eu/resource/authority/licence/CC0',
    'metadata_url': 'https://data.europa.eu/api/hub/repo/datasets/rapex-rapid-alert-system-non-food.jsonld'}
_ATTRIBUTION = 'European Commission — Safety Gate. © European Union. ' + BASE
_BOUNDARY = {'policy': VERSION, 'applicability': 'not_assessed', 'mode': 'announcement_facts_only',
    'notice': '仅选择所选Safety Gate官方告警中的冻结字段。产品名称、条码、批次或日期声明不建立精确轮胎SKU或实物关联；'
              '适用性、安全性与推荐均未评估。告警缺席、历史空缺和字段未知不表示无风险或解除措施。'
              '周报发布日期、告警发布日期、观察与核验时间分别保留；历史材料不代表当前最新状态。'}
_POLICY = {'version': VERSION, 'digest': digest({'fields': _FIELDS, 'boundary': _BOUNDARY,
    'license': _LICENSE, 'scope': 'one-snapshot-one-native-alert@1', 'facts': 'complete-ordered-fields@1'})}
_FACT_KEYS = ('field', 'field_code', 'value', 'text', 'domain', 'scope', 'record_key')
_HASH = re.compile(r'[0-9a-f]{64}')


def frozen_contract(version=VERSION):
    # Retain v1 literals/rendering when future versions are added.
    if version != 'safety-gate-fact-selection@1':
        raise ValueError('unsupported_frozen_safety_gate_policy')
    return deepcopy({'policy': _POLICY, 'boundary': _BOUNDARY, 'fields': _FIELDS})


def canonical_facts(evidence):
    values = evidence['alert_values']
    if type(values) is not dict or set(values) != set(_FIELDS):
        raise ValueError('invalid_safety_gate_field_set')
    facts = []
    for name, label in _FIELDS.items():
        value = values[name]
        rendered = '来源未标明' if value is None else value if isinstance(value, str) else stable_json(value)
        facts.append({'field': label, 'field_code': 'safety_gate.' + name, 'value': deepcopy(value),
            'text': evidence['label'] + '：' + label + ' = ' + rendered, 'domain': 'safety_gate',
            'scope': 'alert', 'record_key': evidence['alert_id']})
    return facts


def _date(value):
    return type(value) is str and date.fromisoformat(value).isoformat() == value


def _time(value):
    if type(value) is not str:
        raise ValueError('invalid_safety_gate_time')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('invalid_safety_gate_time')
    return result


def validate_frozen_evidence(evidence, facts, *, policy_version=VERSION):
    frozen_contract(policy_version)
    try:
        values = evidence['alert_values']
        if (type(values) is not dict or set(values) != set(_FIELDS)
                or evidence.get('evidence_type') != 'safety_gate' or evidence.get('kind') != 'regulatory'
                or evidence.get('source_class') != 'regulatory' or evidence.get('region') != 'EU'
                or evidence.get('source_id') != SOURCE_ID or evidence.get('content_type') != 'application/xml'
                or evidence.get('applicability') != 'not_assessed' or values['applicability'] != 'not_assessed'
                or evidence.get('license_basis') != _LICENSE or evidence.get('attribution') != _ATTRIBUTION):
            raise ValueError('invalid_safety_gate_frozen_provenance')
        for name in ('report_id', 'report_reference', 'report_published_date', 'alert_id', 'case_number', 'alert_published_date'):
            if values[name] != evidence[name]:
                raise ValueError('invalid_safety_gate_identity_binding')
        if (type(evidence['report_id']) is not str or not re.fullmatch(r'[1-9][0-9]{0,11}', evidence['report_id'])
                or type(evidence['alert_id']) is not str or not re.fullmatch(r'-?[1-9][0-9]{0,11}', evidence['alert_id'])
                or type(evidence['report_reference']) is not str or not re.fullmatch(r'Report-[0-9]{4}-[0-9]{1,3}', evidence['report_reference'])
                or not 1 <= int(evidence['report_reference'].rsplit('-', 1)[1]) <= 53
                or type(evidence['case_number']) is not str or not 1 <= len(evidence['case_number']) <= 80
                or not _date(evidence['report_published_date']) or not _date(evidence['alert_published_date'])
                or evidence['source_url'] != BASE + '/api/download/weeklyReport/detail/xml/' + evidence['report_id']
                    + '?language=en&search=WEB_REPORT%7C:%7C' + evidence['report_id'] + ','
                or evidence['alert_source_url'] != BASE + '/screen/webReport/alertDetail/' + evidence['alert_id']
                or evidence['label'] != 'Safety Gate ' + evidence['report_reference'] + ' · ' + evidence['case_number']
                or evidence['query_key'] != digest({'operation':'report','report_id':evidence['report_id'],'reference':evidence['report_reference']})
                or evidence['content_hash'] != digest(values)
                or _time(evidence['observed_at']) > _time(evidence['verified_at'])):
            raise ValueError('invalid_safety_gate_frozen_identity')
        for name in ('raw_hash', 'document_hash', 'content_hash', 'query_key'):
            if type(evidence[name]) is not str or not _HASH.fullmatch(evidence[name]):
                raise ValueError('invalid_safety_gate_frozen_hash')
        for name in ('snapshot_id', 'verification_id', 'verification_query_id', 'parser_version'):
            if type(evidence[name]) is not str or not 1 <= len(evidence[name]) <= 100:
                raise ValueError('invalid_safety_gate_frozen_reference')
        identity = evidence.get('parser_identity')
        if identity is not None and (type(identity) is not dict
                or set(identity) != {'bundle_id','parser_digest','deployment_revision'}
                or any(type(identity[name]) is not str or not _HASH.fullmatch(identity[name]) for name in ('bundle_id','parser_digest'))
                or type(identity['deployment_revision']) is not int or identity['deployment_revision'] < 1):
            raise ValueError('invalid_safety_gate_parser_identity')
        for value in values.values():
            if value is not None:
                if type(value) is not str or len(value) > 60000 or '\x00' in value:
                    raise ValueError('invalid_safety_gate_frozen_text')
                value.encode('utf-8', errors='strict')
        expected = canonical_facts(evidence)
        if (len(facts) != len(expected) or any(set(fact) != {'id','evidence_id', *_FACT_KEYS} for fact in facts)
                or [{name:fact[name] for name in _FACT_KEYS} for fact in facts] != expected):
            raise ValueError('invalid_safety_gate_frozen_facts')
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError('invalid_safety_gate_frozen_material') from error


def load_evidence(db, snapshot_id, alert_id, *, verification_id=None):
    from .safety_gate import SafetyGateSnapshot, SafetyGateVerification, checked_snapshot
    snapshot = checked_snapshot(db.get(SafetyGateSnapshot, snapshot_id))
    if snapshot is None or snapshot.query.get('operation') != 'report':
        raise HTTPException(404, '未找到所选Safety Gate正式周报')
    pairs = select(SafetyGateVerification, QueryRun).join(QueryRun, QueryRun.id == SafetyGateVerification.query_id).where(
        SafetyGateVerification.snapshot_id == snapshot.id, SafetyGateVerification.query_key == snapshot.query_key,
        SafetyGateVerification.status.in_(('ok','not_modified')), QueryRun.state == 'live',
        QueryRun.source_id == SOURCE_ID, QueryRun.query_key == snapshot.query_key)
    if verification_id is not None:
        pairs = pairs.where(SafetyGateVerification.id == verification_id)
    pair = db.execute(pairs.order_by(desc(SafetyGateVerification.verified_at), desc(SafetyGateVerification.id)).limit(1)).first()
    if (pair is None or pair[1].query != snapshot.query or pair[0].parser_identity != snapshot.parser_identity
            or not utc(pair[1].created_at) <= utc(pair[0].verified_at) <= utcnow()
            or not utc(snapshot.observed_at) <= utc(pair[0].verified_at)):
        raise HTTPException(409, '所选Safety Gate证据缺少完整成功核验')
    alert = next((value for value in snapshot.document['alerts'] if value['alert_id'] == alert_id), None)
    if alert is None:
        raise HTTPException(404, '所选告警不在该正式周报快照中')
    report = snapshot.document['report']
    values = {'report_id':report['report_id'], 'report_reference':report['reference'], 'report_published_date':report['published_date'],
        'alert_id':alert['alert_id'], 'case_number':alert['case_number'], 'alert_published_date':alert['published_date'],
        'applicability':'not_assessed', **{name:alert['fields'][original] for name,(original,_label) in _FACT_FIELDS.items()}}
    evidence = {**{name:values[name] for name in _FIELDS if name not in _FACT_FIELDS},
        'evidence_type':'safety_gate', 'kind':'regulatory', 'source_class':'regulatory', 'region':'EU', 'source_id':SOURCE_ID,
        'label':'Safety Gate '+report['reference']+' · '+alert['case_number'],
        'snapshot_id':snapshot.id, 'source_url':snapshot.source_url, 'alert_source_url':alert['source_url'],
        'query_key':snapshot.query_key, 'raw_hash':snapshot.raw_hash, 'document_hash':snapshot.document_hash,
        'content_type':snapshot.content_type, 'parser_version':snapshot.parser_version, 'parser_identity':deepcopy(snapshot.parser_identity),
        'verification_id':pair[0].id, 'verification_query_id':pair[1].id,
        'observed_at':timestamp(snapshot.observed_at), 'verified_at':timestamp(pair[0].verified_at),
        'license_basis':deepcopy(snapshot.license_basis), 'attribution':snapshot.attribution,
        'alert_values':values, 'content_hash':digest(values)}
    return evidence
