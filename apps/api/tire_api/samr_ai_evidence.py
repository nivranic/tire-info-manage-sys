"""Frozen Chinese recall announcement fields with exact raw and verification bindings."""
from copy import deepcopy
from datetime import date, datetime
import re

from fastapi import HTTPException
from sqlalchemy import desc, select

from .adapters.samr import ACCESS_BASIS, ATTRIBUTION, ORIGIN, SITE_NAME, SOURCE_ID
from .db import QueryRun, utc, utcnow
from .domain import digest
from .service import timestamp

VERSION = 'samr-recall-fact-selection@1'
_FIELDS = {
    'article_id': '原生文章ID', 'reference': '官方公告原生路径', 'source_url': '官方公告URL',
    'title': '公告标题原文', 'published_date': '规范发布日期', 'publication_date_raw': '原显示发布日期',
    'deployed_at_raw': 'DeployTime原值', 'pub_date_raw': 'PubDate原值',
    'content_source_raw': '内容来源原文', 'text': '公告正文原文', 'applicability': '实物适用性评估状态',
}
_BOUNDARY = {'policy': VERSION, 'applicability': 'not_assessed', 'mode': 'announcement_facts_only',
    'notice': '所选字段来自明确版本的中国官方召回公告。公告正文中的型号、批次及措施为来源原文，具体SKU、车辆和实物适用性待核对。'
              '原显示发布日期、DeployTime、PubDate、系统观察和核验时间分别保留，日期差异原因待来源说明。'
              '历史材料反映所选版本，空缺与未知字段的风险含义待核对。图片及附件尚未获取。'
              '开放再分发许可待核验，外发所选证据需逐包授权。'}
_POLICY = {'version': VERSION, 'digest': digest({'fields': _FIELDS, 'boundary': _BOUNDARY,
    'access_basis': ACCESS_BASIS, 'scope': 'one-snapshot-one-native-article@1', 'facts': 'complete-ordered-fields@1'})}
_HASH = re.compile(r'[0-9a-f]{64}')
_REFERENCE = re.compile(r'/zhxx/jdczh/jdczh/art/(20[0-9]{2})/art_([a-f0-9]{32})\.html(?:\?type=nFZcuWzfh2c41ylKrWj7k)?')
_FACT_KEYS = ('field', 'field_code', 'value', 'text', 'domain', 'scope', 'record_key')


def frozen_contract(version=VERSION):
    if version != 'samr-recall-fact-selection@1':
        raise ValueError('unsupported_frozen_samr_policy')
    return deepcopy({'policy': _POLICY, 'boundary': _BOUNDARY, 'fields': _FIELDS})


def canonical_facts(evidence):
    values = evidence['notice_values']
    if type(values) is not dict or set(values) != set(_FIELDS):
        raise ValueError('invalid_samr_field_set')
    return [{'field': label, 'field_code': 'samr_recall.' + name, 'value': values[name],
        'text': evidence['label'] + ' · ' + label + ' = ' + (values[name] or '来源未标明'),
        'domain': 'samr_recall', 'scope': 'notice', 'record_key': evidence['article_id']}
        for name, label in _FIELDS.items()]


def _time(value):
    if type(value) is not str:
        raise ValueError('invalid_samr_time')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('invalid_samr_time')
    return result


def validate_frozen_evidence(evidence, facts, *, policy_version=VERSION):
    frozen_contract(policy_version)
    try:
        values = evidence['notice_values']
        if (type(values) is not dict or set(values) != set(_FIELDS)
                or evidence.get('evidence_type') != 'samr_recall' or evidence.get('kind') != 'regulatory'
                or evidence.get('source_class') != 'regulatory' or evidence.get('region') != 'CN'
                or evidence.get('source_id') != SOURCE_ID or evidence.get('content_type') != 'text/html'
                or evidence.get('applicability') != 'not_assessed' or values['applicability'] != 'not_assessed'
                or evidence.get('access_basis') != ACCESS_BASIS or evidence.get('attribution') != ATTRIBUTION):
            raise ValueError('invalid_samr_frozen_provenance')
        for name, value in values.items():
            if type(value) is not str or len(value) > 100000 or '\x00' in value:
                raise ValueError('invalid_samr_frozen_text')
            value.encode('utf-8', errors='strict')
        match = _REFERENCE.fullmatch(values['reference'])
        if (match is None or match[2] != values['article_id'] or values['source_url'] != ORIGIN + values['reference']
                or any(values[name] != evidence[name] for name in ('article_id', 'reference', 'source_url'))
                or evidence['label'] != SITE_NAME + ' · ' + values['title'] or not values['title'] or not values['text']
                or evidence['content_hash'] != digest(values)
                or evidence['query_key'] != digest({'operation': 'notice', 'reference': values['reference']})
                or _time(evidence['observed_at']) > _time(evidence['verified_at'])
                or date.fromisoformat(values['published_date']).isoformat() != values['published_date']
                or values['publication_date_raw'] != values['published_date']
                or datetime.strptime(values['deployed_at_raw'], '%Y-%m-%d %H:%M:%S').date().isoformat() != values['published_date']):
            raise ValueError('invalid_samr_frozen_identity')
        datetime.strptime(values['pub_date_raw'], '%Y-%m-%d %H:%M')
        for name in ('raw_hash', 'document_hash', 'content_hash', 'query_key'):
            if type(evidence[name]) is not str or not _HASH.fullmatch(evidence[name]):
                raise ValueError('invalid_samr_frozen_hash')
        for name in ('snapshot_id', 'verification_id', 'verification_query_id', 'parser_version'):
            if type(evidence[name]) is not str or not 1 <= len(evidence[name]) <= 100:
                raise ValueError('invalid_samr_frozen_reference')
        identity = evidence.get('parser_identity')
        if identity is not None and (type(identity) is not dict
                or set(identity) != {'bundle_id', 'parser_digest', 'deployment_revision'}
                or any(type(identity[name]) is not str or not _HASH.fullmatch(identity[name]) for name in ('bundle_id', 'parser_digest'))
                or type(identity['deployment_revision']) is not int or identity['deployment_revision'] < 1):
            raise ValueError('invalid_samr_parser_identity')
        expected = canonical_facts(evidence)
        if (len(facts) != len(expected) or any(set(fact) != {'id', 'evidence_id', *_FACT_KEYS} for fact in facts)
                or [{name: fact[name] for name in _FACT_KEYS} for fact in facts] != expected):
            raise ValueError('invalid_samr_frozen_facts')
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError('invalid_samr_frozen_material') from error


def load_evidence(db, snapshot_id, article_id, *, verification_id=None):
    from .samr_recalls import SamrRecallSnapshot, SamrRecallVerification, checked_snapshot
    snapshot = checked_snapshot(db.get(SamrRecallSnapshot, snapshot_id))
    if snapshot is None or snapshot.query['operation'] != 'notice' or snapshot.document['notice']['article_id'] != article_id:
        raise HTTPException(404, '未找到所选中国召回公告版本')
    pairs = select(SamrRecallVerification, QueryRun).join(QueryRun, QueryRun.id == SamrRecallVerification.query_id).where(
        SamrRecallVerification.snapshot_id == snapshot.id, SamrRecallVerification.query_key == snapshot.query_key,
        SamrRecallVerification.status.in_(('ok', 'not_modified')), QueryRun.state == 'live',
        QueryRun.source_id == SOURCE_ID, QueryRun.query_key == snapshot.query_key)
    if verification_id is not None:
        pairs = pairs.where(SamrRecallVerification.id == verification_id)
    pair = db.execute(pairs.order_by(desc(SamrRecallVerification.verified_at), desc(SamrRecallVerification.id)).limit(1)).first()
    if (pair is None or pair[1].query != snapshot.query or pair[0].parser_identity != snapshot.parser_identity
            or not utc(pair[1].created_at) <= utc(pair[0].verified_at) <= utcnow()
            or not utc(snapshot.observed_at) <= utc(pair[0].verified_at)):
        raise HTTPException(409, '所选中国召回证据缺少完整成功核验')
    notice = snapshot.document['notice']
    values = {name: notice[name] for name in _FIELDS}
    return {'evidence_type': 'samr_recall', 'kind': 'regulatory', 'source_class': 'regulatory', 'region': 'CN',
        'source_id': SOURCE_ID, 'article_id': article_id, 'reference': notice['reference'],
        'label': SITE_NAME + ' · ' + notice['title'], 'snapshot_id': snapshot.id, 'source_url': snapshot.source_url,
        'query_key': snapshot.query_key, 'raw_hash': snapshot.raw_hash, 'document_hash': snapshot.document_hash,
        'content_type': snapshot.content_type, 'parser_version': snapshot.parser_version,
        'parser_identity': deepcopy(snapshot.parser_identity), 'verification_id': pair[0].id,
        'verification_query_id': pair[1].id, 'observed_at': timestamp(snapshot.observed_at),
        'verified_at': timestamp(pair[0].verified_at), 'access_basis': deepcopy(snapshot.access_basis),
        'attribution': snapshot.attribution, 'notice_values': values, 'content_hash': digest(values), 'applicability': 'not_assessed'}
