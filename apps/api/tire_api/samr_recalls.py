"""Online-first Chinese recall pages, immutable evidence and explicit history."""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import ConfigDict, Field, StrictInt, StrictStr, model_validator
from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, desc, event, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from .adapters import samr as source
from .captures import before_parse_recorder, retain_rejected_response, validated_observation
from .db import Base, FallbackConsent, QueryRun, uid, utc, utcnow
from .domain import StrictModel, digest
from .parser_provenance import check_result_identity, execution_outcome, verified_observation_recorder
from .service import CONSENT_TTL, QueryService, timestamp
from .source_settings import SourceAccessBlocked

NOTICES = ['检索覆盖官方汽车召回栏目本页结果，声明总数与原站最多60页导航范围分别保留。',
    '公告原发布日期、部署时间、PubDate、系统观察时间及核验时间分别记录。',
    '公告中的批次与措施保留原文，具体SKU和实物适用性待核对。图片和附件本次未获取。',
    '开放再分发许可待核验，模型外发需单独授权。']


class SamrRecallQuery(StrictModel):
    operation: Literal['search', 'notice']
    keyword: StrictStr | None = None
    page: StrictStr | None = None
    reference: StrictStr | None = None

    @model_validator(mode='after')
    def valid_query(self):
        source.query_url(self.canonical())
        return self

    def canonical(self):
        return self.model_dump(exclude_none=True)


class SamrRecallRequest(StrictModel):
    query: SamrRecallQuery
    fallback_policy: Literal['ask', 'never'] = 'ask'
    consent_id: str | None = Field(default=None, min_length=1, max_length=64)


class OfficialModel(StrictModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)


class NoticeSummary(OfficialModel):
    article_id: str
    reference: str
    source_url: str
    title: str = Field(min_length=1, max_length=500)
    published_date: str
    publication_date_raw: str
    applicability: Literal['not_assessed']

    @model_validator(mode='after')
    def checked_identity(self):
        query = {'operation': 'notice', 'reference': self.reference}
        if (self.source_url != source.query_url(query) or source._REFERENCE.fullmatch(self.reference)[2] != self.article_id
                or source._date(self.publication_date_raw, '%Y-%m-%d') != self.published_date):
            raise ValueError('samr_recall_identity_invalid')
        return self


class NoticeAsset(OfficialModel):
    kind: Literal['image', 'link']
    source_reference: str = Field(min_length=1, max_length=2048)
    url: str | None
    label: str = Field(max_length=1000)
    fetch_status: Literal['not_fetched']

    @model_validator(mode='after')
    def checked_link(self):
        if source.resource_url(self.source_reference) != self.url:
            raise ValueError('samr_recall_asset_invalid')
        return self


class RecallNotice(NoticeSummary):
    deployed_at_raw: str
    pub_date_raw: str
    content_source_raw: str = Field(max_length=1000)
    text: str = Field(min_length=1, max_length=100000)
    assets: list[NoticeAsset] = Field(max_length=100)
    metadata: dict[str, str]

    @model_validator(mode='after')
    def checked_metadata(self):
        expected = {'SiteName': source.SITE_NAME, 'SiteDomain': 'www.samrdprc.org.cn',
            'SiteID': source.WEB_ID, 'ColId': source.COLUMN_ID, 'ColumnName': '汽车召回',
            'ArticleTitle': self.title, 'PubDate': self.pub_date_raw, 'DeployTime': self.deployed_at_raw,
            'ContentSource': self.content_source_raw, 'Url': self.reference, 'server': self.reference}
        if (self.metadata != expected or source._date(self.deployed_at_raw, '%Y-%m-%d %H:%M:%S') != self.published_date
                or '\x00' in self.text):
            raise ValueError('samr_recall_metadata_invalid')
        source._date(self.pub_date_raw, '%Y-%m-%d %H:%M')
        return self


class SamrRecallDocument(OfficialModel):
    operation: Literal['search', 'notice']
    keyword: str | None = None
    page: StrictInt | None = None
    page_size: Literal[15] | None = None
    declared_total: StrictInt | None = None
    source_navigation_page_limit: Literal[60] | None = None
    source_navigation_pages: StrictInt | None = None
    notices: list[NoticeSummary] = Field(max_length=15)
    notice: RecallNotice | None


def checked_document(value, query):
    keys = {'operation', 'notices', 'notice'}
    if query['operation'] == 'search':
        keys |= {'keyword', 'page', 'page_size', 'declared_total', 'source_navigation_page_limit', 'source_navigation_pages'}
    if type(value) is not dict or set(value) != keys:
        raise ValueError('samr_recall_document_invalid')
    document = SamrRecallDocument.model_validate(value)
    if document.operation != query['operation']:
        raise ValueError('samr_recall_query_mismatch')
    if document.operation == 'notice':
        if document.notices or document.notice is None or document.notice.reference != query['reference']:
            raise ValueError('samr_recall_query_mismatch')
    elif (document.notice is not None or document.keyword != query['keyword'] or document.page != int(query['page'])
            or document.declared_total is None or not 0 <= document.declared_total <= 999999999
            or document.source_navigation_pages != min(60, (document.declared_total + 14) // 15)
            or len(document.notices) != min(15, max(0, document.declared_total - (document.page - 1) * 15))
            or len({row.reference for row in document.notices}) != len(document.notices)):
        raise ValueError('samr_recall_pagination_invalid')
    return document.model_dump(exclude_unset=True)


def content_type(query):
    return 'application/json' if query['operation'] == 'search' else 'text/html'


class SamrRecallSnapshot(Base):
    __tablename__ = 'samr_recall_snapshots'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(String(80), default=source.SOURCE_ID)
    query: Mapped[dict] = mapped_column(JSON)
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    raw_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120))
    parser_version: Mapped[str] = mapped_column(String(100))
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    document: Mapped[dict] = mapped_column(JSON)
    document_hash: Mapped[str] = mapped_column(String(64))
    access_basis: Mapped[dict] = mapped_column(JSON)
    attribution: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SamrRecallVerification(Base):
    __tablename__ = 'samr_recall_verifications'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('samr_recall_snapshots.id'), index=True)
    query_id: Mapped[str] = mapped_column(ForeignKey('query_runs.id'), unique=True)
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24))
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_samr_recalls(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (SamrRecallSnapshot, SamrRecallVerification)) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('中国召回证据与核验记录只能追加')


def checked_snapshot(snapshot):
    if snapshot is not None:
        try:
            if (snapshot.source_id != source.SOURCE_ID or snapshot.query_key != digest(snapshot.query)
                    or snapshot.source_url != source.query_url(snapshot.query) or snapshot.content_type != content_type(snapshot.query)
                    or sha256(snapshot.body.encode('utf-8')).hexdigest() != snapshot.raw_hash
                    or digest(snapshot.document) != snapshot.document_hash
                    or snapshot.access_basis != source.ACCESS_BASIS or snapshot.attribution != source.ATTRIBUTION
                    or checked_document(snapshot.document, snapshot.query) != snapshot.document):
                raise ValueError('samr_recall_snapshot_invalid')
        except (ValueError, TypeError, KeyError):
            raise HTTPException(503, '中国召回历史证据完整性校验失败') from None
    return snapshot


class SamrRecallService:
    def __init__(self, db, adapter, registry=None, *, ingestion_guard=None):
        self.db, self.adapter = db, adapter
        self.ingestion_guard = ingestion_guard
        self.shared = QueryService(db, registry, ingestion_guard=ingestion_guard)

    def latest(self, key):
        return checked_snapshot(self.db.scalar(select(SamrRecallSnapshot).join(SamrRecallVerification)
            .where(SamrRecallVerification.query_key == key)
            .order_by(desc(SamrRecallVerification.verified_at), desc(SamrRecallVerification.id)).limit(1)))

    def transport_cache(self, key):
        row = self.db.execute(select(SamrRecallSnapshot.id, SamrRecallSnapshot.source_url,
            SamrRecallSnapshot.body, SamrRecallSnapshot.raw_hash, SamrRecallSnapshot.content_type,
            SamrRecallSnapshot.parser_version, SamrRecallVerification.parser_identity,
            SamrRecallVerification.etag, SamrRecallVerification.last_modified).join(SamrRecallVerification)
            .where(SamrRecallVerification.query_key == key)
            .order_by(desc(SamrRecallVerification.verified_at), desc(SamrRecallVerification.id)).limit(1)).first()
        if row is None:
            return None
        return {'snapshot_id': row.id, 'url': row.source_url, 'body': row.body, 'raw_hash': row.raw_hash,
            'content_type': row.content_type, 'parser_version': row.parser_version,
            'parser_identity': row.parser_identity, 'etag': row.etag, 'last_modified': row.last_modified}

    def blocked(self, query, run, error):
        self.shared.block_source_access(run, error)
        return self.response(query, run.state, query_id=run.id, reason=run.reason)

    async def execute(self, request, session_id, *, audience='internal', owner_actor=None):
        from .telemetry import observe
        with observe('source.query', component='crawler', source=source.SOURCE_ID) as operation:
            result = await self._execute(request, session_id, audience=audience, owner_actor=owner_actor)
            operation.finish(result['data_state'])
            return result

    async def _execute(self, request, session_id, *, audience='internal', owner_actor=None):
        query = request.query.canonical()
        key = digest(query)
        if request.consent_id:
            return self.consume_consent(request, session_id, audience=audience)
        run = QueryRun(id=uid(), session_id=session_id, source_id=source.SOURCE_ID, query=query,
            query_key=key, fallback_policy=request.fallback_policy)
        if owner_actor is None:
            self.db.add(run)
            self.shared.audit(session_id, 'samr_recall_online_started', run.id, query=query)
            self.db.commit()
        else:
            from .query_ownership import create_query_with_owner
            create_query_with_owner(self.db, run, owner_actor, lock_ingestion=self.shared.lock_ingestion)
        try:
            self.shared.pin_source_access(run)
        except SourceAccessBlocked as error:
            return self.blocked(query, run, error)
        cache = self.transport_cache(key)
        self.db.commit()
        from .parser_releases import ParserDeploymentError, pin_selection, record_execution
        selection = None
        try:
            options = {}
            recorder = before_parse_recorder(self.db, run)
            if getattr(self.adapter, 'supports_parser_deployments', False) is True:
                selection = pin_selection(self.db, run.id, source.SOURCE_ID)
                options['parser_selection'] = selection
                recorder = verified_observation_recorder(recorder, selection)
            result = await self.adapter.fetch(query, cached=cache, on_observation=recorder, **options)
        except ParserDeploymentError as error:
            self.db.rollback()
            result = {'status': 'unavailable', 'reason': error.code}
        except Exception:
            result = {'status': 'unavailable', 'reason': 'samr_recall_fetch_failed'}
        if selection is not None:
            try:
                record_execution(self.db, run.id, execution_outcome(result))
            except ParserDeploymentError as error:
                if not error.execution_recorded:
                    self.db.rollback()
                result = {'status': 'unavailable', 'reason': error.code}
            self.db.commit()
        if result.get('status') in {'ok', 'not_modified'}:
            try:
                if result['status'] == 'not_modified':
                    if (not self.shared.valid_304(cache, result, require_identity=True, require_tire_identity_contract=False)
                            or result.get('parser_version') != cache['parser_version']):
                        raise ValueError('samr_recall_304_invalid')
                    result = {**cache, **result}
                    result['etag'] = result.get('etag') or cache.get('etag')
                    result['last_modified'] = result.get('last_modified') or cache.get('last_modified')
                if (validated_observation(result, source_id=source.SOURCE_ID, query=query) is None
                        or result['url'] != source.query_url(query) or result['content_type'] != content_type(query)
                        or '\x00' in result['body']):
                    raise ValueError('samr_recall_observation_invalid')
                document = None if result['status'] == 'not_modified' else checked_document(result['document'], query)
                if result['status'] == 'not_modified' and sha256(result['body'].encode('utf-8')).hexdigest() != cache['raw_hash']:
                    raise ValueError('samr_recall_304_body_invalid')
            except (ValueError, TypeError, KeyError):
                retain_rejected_response(self.db, run, result, 'schema')
                self.db.commit()
                result = {'status': 'unavailable', 'reason': 'samr_recall_schema_changed'}
            else:
                try:
                    snapshot, verified = self.persist(run, result, document, cache, selection)
                except SourceAccessBlocked as error:
                    return self.blocked(query, run, error)
                except ParserDeploymentError as error:
                    self.db.rollback()
                    result = {'status': 'unavailable', 'reason': error.code}
                else:
                    run.state = 'live'
                    self.shared.audit(session_id, 'samr_recall_online_succeeded', run.id, snapshot_id=snapshot.id)
                    if self.ingestion_guard:
                        self.ingestion_guard(self.db)
                    self.db.commit()
                    return self.response(query, 'live_verified_304' if result['status'] == 'not_modified' else 'live',
                        snapshot, run.id, verified_at=verified)
        if result.get('rejected_observation') is not None:
            retain_rejected_response(self.db, run, result['rejected_observation'], 'parser')
            self.db.commit()
        self.shared.lock_ingestion()
        try:
            self.shared.assert_source_access(run)
        except SourceAccessBlocked as error:
            return self.blocked(query, run, error)
        if self.ingestion_guard:
            self.ingestion_guard(self.db)
        run.state = 'consent_required' if request.fallback_policy == 'ask' else 'source_unavailable'
        run.reason = str(result.get('reason') or 'samr_recall_unavailable')[:200]
        self.shared.audit(session_id, 'samr_recall_online_failed', run.id, reason=run.reason)
        self.db.commit()
        from .query_fallback_policies import claim_policy_use, authorized_result
        use = claim_policy_use(self.db, self.shared.registry, run, 'samr_recall_' + query['operation'], audience)
        if use is not None:
            snapshot = self.latest(key)
            self.shared.audit(session_id, 'policy_samr_recall_snapshot_read', run.id, use_id=use.id,
                snapshot_id=snapshot.id if snapshot else None)
            response = self.response(query, 'local_snapshot', snapshot, run.id,
                reason=run.reason if snapshot else 'no_matching_samr_recall_snapshot')
            return authorized_result(self.db, self.shared.registry, run, use, response)
        return self.response(query, run.state, query_id=run.id, reason=run.reason)

    def persist(self, run, result, document, cache, selection):
        from .parser_releases import ParserDeploymentError, assert_selection_current
        self.shared.lock_ingestion()
        self.shared.assert_source_access(run)
        if self.ingestion_guard:
            self.ingestion_guard(self.db)
        if selection is not None:
            assert_selection_current(self.db, selection)
            check_result_identity(selection, result)
        snapshot = self.latest(run.query_key)
        if result['status'] == 'not_modified':
            if snapshot is None or snapshot.id != cache['snapshot_id']:
                raise ParserDeploymentError('samr_recall_cache_head_changed', 409)
        else:
            raw_hash = sha256(result['body'].encode('utf-8')).hexdigest()
            document_hash = digest(document)
            if (snapshot is None or snapshot.raw_hash != raw_hash or snapshot.document_hash != document_hash
                    or snapshot.parser_version != result['parser_version'] or snapshot.parser_identity != result.get('parser_identity')):
                snapshot = SamrRecallSnapshot(id=uid(), query=run.query, query_key=run.query_key,
                    source_url=result['url'], raw_hash=raw_hash, body=result['body'], content_type=result['content_type'],
                    parser_version=result['parser_version'], parser_identity=result.get('parser_identity'),
                    document=document, document_hash=document_hash, access_basis=dict(source.ACCESS_BASIS),
                    attribution=source.ATTRIBUTION)
                self.db.add(snapshot)
                self.db.flush()
        verified = utcnow()
        self.db.add(SamrRecallVerification(snapshot_id=snapshot.id, query_id=run.id, query_key=run.query_key,
            status='not_modified' if result['status'] == 'not_modified' else 'ok',
            etag=result.get('etag'), last_modified=result.get('last_modified'),
            parser_identity=result.get('parser_identity'), verified_at=verified))
        self.db.flush()
        return snapshot, verified

    def consume_consent(self, request, session_id, *, audience='internal'):
        self.shared.lock_ingestion()
        query = request.query.canonical()
        consent = self.db.get(FallbackConsent, request.consent_id)
        if consent is None or consent.session_id != session_id:
            raise HTTPException(403, '离线授权不属于当前会话')
        run = self.db.get(QueryRun, consent.query_id)
        if (run is None or run.session_id != session_id or run.source_id != source.SOURCE_ID
                or run.query_key != digest(query) or run.query != query or run.state != 'consent_required'
                or run.fallback_policy != 'ask' or request.fallback_policy != 'ask'
                or consent.decision != 'allow' or consent.scope != 'once'):
            raise HTTPException(403, '离线授权的来源、公告查询或策略不匹配')
        try:
            self.shared.assert_source_access(run)
        except SourceAccessBlocked as error:
            return self.blocked(query, run, error)
        from .query_fallback_policies import assert_once_policy
        assert_once_policy(self.db, self.shared.registry, run, 'samr_recall_' + query['operation'], audience)
        now = utcnow()
        if utc(consent.expires_at) <= now or utc(run.created_at) + CONSENT_TTL <= now:
            raise HTTPException(410, '离线授权已过期')
        claimed = self.db.execute(update(FallbackConsent).where(FallbackConsent.id == consent.id,
            FallbackConsent.session_id == session_id, FallbackConsent.used_at.is_(None),
            FallbackConsent.decision == 'allow', FallbackConsent.expires_at > now)
            .values(used_at=now).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            raise HTTPException(409, '离线授权已经使用')
        snapshot = self.latest(run.query_key)
        run.state = 'local_snapshot'
        self.shared.audit(session_id, 'samr_recall_local_snapshot_read', run.id, consent.id,
            snapshot_id=snapshot.id if snapshot else None)
        self.db.commit()
        return self.response(query, 'local_snapshot', snapshot, run.id, reason=run.reason, consent_id=consent.id)

    def response(self, query, state, snapshot=None, query_id=None, *, verified_at=None, reason=None, consent_id=None):
        checked_snapshot(snapshot)
        if snapshot is not None and verified_at is None:
            verified_at = self.db.scalar(select(SamrRecallVerification.verified_at)
                .where(SamrRecallVerification.snapshot_id == snapshot.id)
                .order_by(desc(SamrRecallVerification.verified_at)).limit(1))
        return {'query_id': query_id, 'source_id': source.SOURCE_ID, 'query': query, 'data_state': state,
            'reason': reason, 'consent_id': consent_id, 'verified_at': timestamp(verified_at),
            'snapshot_observed_at': timestamp(snapshot.observed_at) if snapshot else None,
            'document': snapshot.document if snapshot else None, 'notices': NOTICES,
            'provenance': [{'snapshot_id': snapshot.id, 'source_id': snapshot.source_id,
                'source_url': snapshot.source_url, 'raw_hash': snapshot.raw_hash,
                'observed_at': timestamp(snapshot.observed_at), 'parser_version': snapshot.parser_version,
                'parser_identity': snapshot.parser_identity, 'access_basis': snapshot.access_basis,
                'attribution': snapshot.attribution,
                'evidence_path': f'/v1/samr-recalls/evidence/{snapshot.id}?mode=history'}] if snapshot else []}


def register_samr_recall_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/samr-recalls/query')
    async def query(payload: SamrRecallRequest, request: Request, db: Session = Depends(get_db)):
        adapter = getattr(app.state, 'samr_recall_adapter', None) or source
        from .query_ownership import QueryOwnershipError, capture_query_actor
        try:
            actor = None if payload.consent_id else capture_query_actor(db, request.state.session_id)
            return await SamrRecallService(db, adapter, app.state.registry).execute(payload, request.state.session_id,
                audience='programmatic', owner_actor=actor)
        except QueryOwnershipError as error:
            raise HTTPException(401 if error.code == 'query_actor_invalid' else 409, {'code': error.code}) from None

    @app.get('/v1/samr-recalls/history')
    def history(request: Request, operation: Literal['search', 'notice'], mode: Literal['history'],
                keyword: str | None = None, page: str | None = None, reference: str | None = None, db: Session = Depends(get_db)):
        try:
            query = SamrRecallQuery(operation=operation, keyword=keyword, page=page, reference=reference).canonical()
        except ValueError:
            raise HTTPException(422, '中国召回历史查询条件无效') from None
        service = SamrRecallService(db, None)
        snapshot = service.latest(digest(query))
        service.shared.audit(request.state.session_id, 'samr_recall_history_read', query=query)
        db.commit()
        return service.response(query, 'local_snapshot', snapshot, reason='explicit_history' if snapshot else 'no_matching_samr_recall_snapshot')

    @app.get('/v1/samr-recalls/evidence/{snapshot_id}')
    def evidence(snapshot_id: str, request: Request, mode: Literal['history'], db: Session = Depends(get_db)):
        snapshot = checked_snapshot(db.get(SamrRecallSnapshot, snapshot_id))
        if snapshot is None:
            raise HTTPException(404, '未找到中国召回证据')
        service = SamrRecallService(db, None)
        service.shared.audit(request.state.session_id, 'samr_recall_evidence_history_read', snapshot_id=snapshot.id)
        db.commit()
        return {'id': snapshot.id, 'query': snapshot.query, 'body': snapshot.body,
            'content_type': snapshot.content_type, 'data_state': 'local_snapshot',
            **service.response(snapshot.query, 'local_snapshot', snapshot)['provenance'][0]}
