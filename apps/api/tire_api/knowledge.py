"""Explicit historical lexical retrieval. No network, model, or fallback behavior."""
import re
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import Field, StrictInt, ValidationInfo, field_validator, model_validator
from sqlalchemy import Float, String, exists, or_, select, text
from sqlalchemy.orm import Session

from .domain import StrictModel, TireQuery, parse_size
from .knowledge_index import FIELD_CATALOG, IDENTITY_FIELDS, normalized, query_tokens, refresh_index, size_key
from .knowledge_models import KnowledgeDocument, KnowledgeFacet
from .service import QueryService
from .recall_evidence import OBSERVATION_FIELDS, RECALL_FIELDS
from .recall_models import RecallQuery

CURRENT_WORDS = re.compile(r'当前|最新|现在|今天|目前|现售|还有没有|\b(?:current|latest|today|now)\b', re.I)
ALIASES = {'ps4s': 'Pilot Sport 4 S', 'psev': 'Pilot Sport EV',
           'pilot sport 4 s': 'Pilot Sport 4 S', 'pilot sport ev': 'Pilot Sport EV'}
SIZE_PATTERN = re.compile(r'(?<!\d)\d{3}\s*/\s*\d{2}\s*(?:ZR|R)\s*\d{2}(?:\.5)?(?!\d)', re.I)
SEARCH_FIELDS = (set(FIELD_CATALOG) | set(IDENTITY_FIELDS) | {'gtin', 'eprel_id', 'technology_features'}
                 | {'recall.' + name for name in RECALL_FIELDS | OBSERVATION_FIELDS})
CAMPAIGN_PATTERN = re.compile(r'(?<![a-z0-9])[0-9]{2}t[0-9]{6}(?![a-z0-9])', re.I)


class SearchFilters(StrictModel):
    kind: Literal['tire', 'vehicle', 'test_event', 'recall'] | None = None
    campaign_number: str | None = Field(default=None, min_length=9, max_length=9)
    brand: str | None = Field(default=None, min_length=1, max_length=120)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    size: str | None = Field(default=None, min_length=1, max_length=24)
    region: str | None = Field(default=None, min_length=1, max_length=40)
    product_code: str | None = Field(default=None, min_length=1, max_length=100)
    source_id: str | None = Field(default=None, min_length=1, max_length=80)
    variant_id: str | None = Field(default=None, min_length=1, max_length=64)
    technology: str | None = Field(default=None, min_length=1, max_length=100)
    field: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator('size')
    @classmethod
    def size_format(cls, value):
        return parse_size(value) if value else value

    @field_validator('model')
    @classmethod
    def model_alias(cls, value, info: ValidationInfo):
        if info.data.get('kind') == 'recall' or info.data.get('campaign_number'):
            return value
        return TireQuery.normalize_model(value) if value else value

    @field_validator('campaign_number')
    @classmethod
    def campaign_format(cls, value):
        return RecallQuery(campaign_number=value).campaign_number if value is not None else None

    @field_validator('field')
    @classmethod
    def canonical_field(cls, value):
        if value is None:
            return None
        value = normalized(value)
        if value not in SEARCH_FIELDS:
            raise ValueError('不支持该检索字段，请选择明确的规格字段代码')
        return value

    @field_validator('*', mode='after')
    @classmethod
    def safe_text(cls, value):
        if isinstance(value, str) and any(ord(char) < 32 for char in value):
            raise ValueError('筛选字段不得包含控制字符')
        return value


class KnowledgeSearch(StrictModel):
    mode: Literal['history']
    text: str = Field(default='', max_length=500)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: StrictInt = Field(default=12, ge=1, le=30)
    offset: StrictInt = Field(default=0, ge=0, le=2000)

    @model_validator(mode='after')
    def useful_query(self):
        if not self.text and not self.filters.model_dump(exclude_none=True):
            raise ValueError('请提供历史检索文本或至少一个有效筛选条件')
        if '\x00' in self.text:
            raise ValueError('检索文本不得包含空字符')
        return self


def interpret(payload):
    """Only syntax-level aliases become filters; unresolved language remains FTS."""
    explicit = payload.filters.model_dump(exclude_none=True)
    inferred = {}
    residual = normalized(payload.text)
    campaigns = set(match.group().upper() for match in CAMPAIGN_PATTERN.finditer(residual))
    recall_scope = (explicit.get('kind') == 'recall' or 'campaign_number' in explicit
                    or len(campaigns) == 1 and explicit.get('kind') in (None, 'recall'))
    if recall_scope:
        if 'kind' not in explicit:
            inferred['kind'] = 'recall'
        if len(campaigns) == 1:
            campaign = next(iter(campaigns))
            if 'campaign_number' not in explicit:
                inferred['campaign_number'] = campaign
            if explicit.get('campaign_number', campaign) == campaign:
                residual = CAMPAIGN_PATTERN.sub(' ', residual)
        for name in ('brand', 'model', 'campaign_number', 'source_id'):
            if name in explicit and residual.strip() == normalized(explicit[name]):
                residual = ''
        filters = {**inferred, **explicit}
        sufficient = bool(filters) and not residual.strip(' ,;/|+-()[]{}\t\r\n')
        return filters, inferred, query_tokens(residual), sufficient
    matches = list(SIZE_PATTERN.finditer(residual))
    sizes = set()
    for match in matches:
        try:
            sizes.add(parse_size(match.group()))
        except ValueError:
            pass
    if len(sizes) == 1:
        value = next(iter(sizes))
        if 'size' not in explicit:
            inferred['size'] = value
        if size_key(explicit.get('size', value)) == size_key(value):
            residual = SIZE_PATTERN.sub(' ', residual)
    model_pattern = re.compile(r'\b(?:pilot sport 4 s|pilot sport ev|ps4s|psev)\b')
    models = {ALIASES[match.group()] for match in model_pattern.finditer(residual)}
    if len(models) == 1:
        value = next(iter(models))
        if 'model' not in explicit:
            inferred['model'] = value
        if normalized(explicit.get('model', value)) == normalized(value):
            residual = model_pattern.sub(' ', residual)
    if re.search(r'\bacoustic\b', residual):
        if 'technology' not in explicit:
            inferred['technology'] = 'Acoustic'
        if normalized(explicit.get('technology', 'acoustic')) == 'acoustic':
            residual = re.sub(r'\bacoustic\b', ' ', residual)
    # A text which is exactly an explicit structured value adds no lexical
    # constraint. Do not remove arbitrary natural-language substrings.
    for name in ('brand', 'model', 'product_code', 'variant_id', 'source_id'):
        if name in explicit and residual.strip() == normalized(explicit[name]):
            residual = ''
    filters = {**inferred, **explicit}
    terms = query_tokens(residual)
    sufficient = bool(filters) and not residual.strip(' ,;/|+-()[]{}\t\r\n')
    return filters, inferred, terms, sufficient


def authority(document, field):
    from .field_authority import canonical_field, source_authority
    if not field:
        return None, 'field_not_selected', '未指定目标字段，不使用来源权威加权'
    if field not in document['_values'] or document['_values'][field] is None:
        return None, 'field_not_present', '所选字段没有可核对的记录'
    if document['kind'] == 'recall':
        from .recall_evidence import recall_field_authority
        rule = recall_field_authority(field)
        return rule['tier'], rule['rule'], rule['explanation']
    sku_specific = any(candidate['field'] == canonical_field(field) and candidate.get('sku_specific') is True
                       for candidate in document.get('_field_candidates', []))
    if '_field_candidates' not in document and field == 'acoustic_technology':
        sku_specific = document.get('_sku_acoustic', False)
    rule = source_authority(field, document['_source_class'], sku_specific=sku_specific)
    return rule['tier'], rule['rule'], rule['explanation']


def _filtered_statement(filters):
    statement = select(KnowledgeDocument)
    for name, value in filters.items():
        if name in {'kind', 'source_id', 'variant_id'}:
            statement = statement.where(getattr(KnowledgeDocument, name) == value)
        else:
            key = size_key(value) if name == 'size' else normalized(value)
            statement = statement.where(exists(select(KnowledgeFacet.document_id).where(
                KnowledgeFacet.document_id == KnowledgeDocument.id,
                KnowledgeFacet.name == name, KnowledgeFacet.value == key)))
    if filters.get('brand') and filters.get('model'):
        # One event can contain several brands/models: do not join brand from
        # participant A to model from participant B.
        pair = normalized(filters['brand']) + ' | ' + normalized(filters['model'])
        statement = statement.where(or_(KnowledgeDocument.kind != 'test_event', exists(
            select(KnowledgeFacet.document_id).where(KnowledgeFacet.document_id == KnowledgeDocument.id,
                KnowledgeFacet.name == 'brand_model', KnowledgeFacet.value == pair))))
    return statement


def lexical_candidates(db, filters, terms, sufficient=False, limit=None):
    """Apply identical structured filters before optional lexical candidate caps."""
    statement = _filtered_statement(filters)
    if sufficient:
        return [(doc, 0.0) for doc in db.scalars(statement)]
    if not terms:
        return []
    if db.get_bind().dialect.name == 'sqlite':
        fulltext = text('SELECT document_id AS id, bm25(knowledge_fts) AS score FROM knowledge_fts '
                        'WHERE knowledge_fts MATCH :search_terms').columns(id=String, score=Float).subquery()
        query = ' AND '.join('"' + term.replace('"', '""') + '"' for term in terms)
    else:
        fulltext = text("SELECT id, -ts_rank_cd(search_vector, plainto_tsquery('simple', :search_terms)) AS score "
                        "FROM knowledge_documents WHERE search_vector @@ plainto_tsquery('simple', :search_terms)")\
            .columns(id=String, score=Float).subquery()
        query = ' '.join(terms)
    statement = statement.add_columns(fulltext.c.score).join(fulltext, fulltext.c.id == KnowledgeDocument.id)
    if limit is not None:
        statement = statement.order_by(fulltext.c.score, KnowledgeDocument.id).limit(limit)
    return list(db.execute(statement, {'search_terms': query}))


def render_ranked(candidates, filters, terms, sufficient=False, methods=None, details=None):
    ranked = []
    for document, score in candidates:
        data = document.payload
        tier, rule, explanation = authority(data, filters.get('field'))
        public = {key: value for key, value in data.items() if not key.startswith('_')}
        reasons = [explanation, '仅检索正式历史证据，不代表当前在售或库存；OE 标记不等于车型适配']
        if filters:
            reasons.append('先应用全部结构化筛选条件，再计算文本匹配和结果数量')
        if filters.get('size'):
            reasons.append('尺寸按几何规格匹配，R/ZR 身份仍分别保留；不据此合并或替代 SKU')
        if data['kind'] == 'test_event':
            reasons.append('人工录入，未经外部核验；参测名称未关联到精确 SKU，成绩仅限本场')
        if data['kind'] == 'recall':
            reasons = [explanation, '正式召回历史证据；产品名称不证明实物适用性，DOT/TIN 与批次仍未评估',
                       '所有精确筛选按同一公告产品记录匹配；选择分析会包含该快照的全部公告记录',
                       '空响应为独立观察，不表示无召回或解除，不刷新旧公告的观察或核验时间']
        public['id'] = document.id
        method = methods.get(document.id) if methods else ('structured' if sufficient else 'fts')
        public['match'] = {'method': method,
            'matched_terms': [f'{key}={value}' for key, value in filters.items()] if sufficient else terms if method != 'dense' else [],
            'authority_tier': tier, 'authority_rule': rule, 'explanation': reasons,
            **(details.get(document.id, {}) if details else {})}
        ranked.append((tier or 999, float(score), data['observed_at'], document.id, public))
    ranked.sort(key=lambda row: row[3])
    ranked.sort(key=lambda row: row[2], reverse=True)
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [row[4] for row in ranked]


def attach_identity_contracts(db, items):
    """Retrieval-time metadata only; never mutate indexed or previously saved evidence."""
    from .identity_contract import contract_context, contract_metadata
    ids = {item['reference']['variant_id'] for item in items if item.get('kind') == 'tire'}
    context = contract_context(db, ids)
    return [{**item, 'identity_contract': contract_metadata(db, item['reference']['variant_id'], context=context)}
            if item.get('kind') == 'tire' else item for item in items]


def attach_field_resolutions(db, items):
    """Response sidecars over the same accepted-head corpus, never saved-result rewrites."""
    from .field_authority import resolve_fields
    from .field_evidence import complete_missing_candidates
    ids = {item['reference']['variant_id'] for item in items if item.get('kind') == 'tire'}
    candidates = {variant_id: [] for variant_id in ids}
    if ids:
        for document in db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.variant_id.in_(ids))):
            candidates[document.variant_id].extend(document.payload.get('_field_candidates', []))
    resolutions = {variant_id: resolve_fields(complete_missing_candidates(values), variant_id=variant_id, scope='accepted_heads')
                   for variant_id, values in candidates.items()}
    return [{**item, 'field_resolution': resolutions[item['reference']['variant_id']]}
            if item.get('kind') == 'tire' else item for item in items]


def online_query_detail(payload):
    filters, _, _, _ = interpret(payload)
    recall = filters.get('kind') == 'recall' or filters.get('campaign_number') is not None
    result = {'code': 'online_query_required',
        'message': '历史知识检索不能回答当前或最新状态，请使用在线查询。',
        'route': '/v1/recalls/live-query' if recall else '/v1/sources/{source_id}/live-query'}
    if recall:
        result['query_kind'] = 'recall_by_campaign'
        result['query'] = {'campaign_number': filters['campaign_number']} if filters.get('campaign_number') else None
    return result


def search_history(db, registry, payload: KnowledgeSearch):
    if CURRENT_WORDS.search(payload.text):
        raise HTTPException(409, online_query_detail(payload))
    filters, inferred, terms, sufficient = interpret(payload)
    QueryService(db, None).lock_ingestion()
    state = refresh_index(db, registry)
    # Release the write lock before read-only matching/ranking. The rebuilt FTS
    # and its projection commit together; subsequent searches read that version.
    db.commit()
    # A second search may replace the derived corpus after we release the write
    # lock. Read both metadata and candidates in one database snapshot, so index
    # counts cannot describe an older projection than the returned references.
    backend = db.get_bind().dialect.name
    if backend == 'sqlite':
        db.connection().exec_driver_sql('BEGIN')
    elif backend == 'postgresql':
        db.connection().exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    db.refresh(state)
    index = {'engine': 'sqlite_fts5' if backend == 'sqlite' else 'postgresql_fts',
             'documents': state.documents, 'version': state.version}
    ranked = render_ranked(lexical_candidates(db, filters, terms, sufficient), filters, terms, sufficient)
    total = len(ranked)
    end = payload.offset + payload.limit
    has_more = total > end
    stages = [
        {'name': 'structured', 'state': 'succeeded' if filters else 'not_needed',
         'reason': '已执行精确筛选与保守别名解析' if filters else '无结构化筛选条件'},
        {'name': 'fts', 'state': 'not_needed' if sufficient else 'succeeded',
         'reason': '查询已被精确筛选完整表达' if sufficient else '已执行数据库全文检索' if terms else '文本无可检索词元，返回空结果'},
        {'name': 'dense', 'state': 'not_needed', 'reason': '普通检索本次未使用向量；可另行明确授权混合检索'},
        {'name': 'hybrid', 'state': 'not_needed', 'reason': '本次仅在本机执行词法检索，未发送查询文本'},
        {'name': 'rerank', 'state': 'succeeded', 'reason': '精确筛选后按字段权威、词法相关度与时间排序；未使用语义重排模型'},
    ]
    return {'mode': 'history', 'data_state': 'local_snapshot', 'text': payload.text,
            'applied_filters': filters, 'inferred_filters': inferred,
            'items': attach_field_resolutions(db, attach_identity_contracts(db, ranked[payload.offset:end])),
            'total': total, 'has_more': has_more, 'offset': payload.offset, 'limit': payload.limit,
            'index': index, 'stages': stages,
            'notice': '显式历史检索：来自各查询最新正式核验快照、有效测试修订及最新非空召回历史内容；召回空观察独立保留，'
                      '不表示解除或无风险，也不刷新旧公告时间。不同查询的历史范围可能重叠，'
                      '不保证覆盖当前完整目录。已执行字段规则排序；本次未使用向量或混合检索，可另行授权混合路径。'
                      '语义重排模型尚未接入。'
                      + (f'共 {total} 条匹配，当前展示第 {payload.offset + 1}–{min(end, total)} 条；可用 offset 继续加载。' if has_more else '')}


def register_knowledge_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/knowledge/search')
    def search(payload: KnowledgeSearch, db: Session = Depends(get_db)):
        return search_history(db, app.state.registry, payload)
