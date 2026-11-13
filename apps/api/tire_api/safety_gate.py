"""Online-first Safety Gate weekly evidence with explicit historical reads."""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import ConfigDict, Field, StrictStr, model_validator
from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, desc, event, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from .adapters import safety_gate as source
from .captures import before_parse_recorder, retain_rejected_response, validated_observation
from .db import Base, FallbackConsent, QueryRun, uid, utc, utcnow
from .domain import StrictModel, digest
from .parser_provenance import check_result_identity, execution_outcome, verified_observation_recorder
from .service import CONSENT_TTL, QueryService, timestamp
from .source_settings import SourceAccessBlocked

NOTICES = ['覆盖所选英文周报或本次官方周报索引，周报编号按官方原值保留。',
    '告警中的产品名称、批次、序列号和措施为官方声明，具体SKU及实物适用性待核对。',
    '告警发布日、周报发布日、系统观察时间及核验时间分别记录。']


class SafetyGateQuery(StrictModel):
    operation: Literal['reports', 'report']
    report_id: StrictStr | None = None
    reference: StrictStr | None = None

    @model_validator(mode='after')
    def valid_query(self):
        source.query_url(self.canonical())
        return self

    def canonical(self):
        return self.model_dump(exclude_none=True)


class SafetyGateRequest(StrictModel):
    query: SafetyGateQuery
    fallback_policy: Literal['ask', 'never'] = 'ask'
    consent_id: str | None = Field(default=None, min_length=1, max_length=64)


class OfficialModel(StrictModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)


class ReportSummary(OfficialModel):
    report_id: str
    reference: str
    published_date: str
    publication_date_raw: str
    url: str
    addendum_raw: str | None = None

    @model_validator(mode='after')
    def checked_identity(self):
        if (self.url != source.query_url({'operation': 'report', 'report_id': self.report_id, 'reference': self.reference})
                or date.fromisoformat(self.published_date).isoformat() != self.published_date
                or source._date(self.publication_date_raw, '%d/%m/%Y') != self.published_date):
            raise ValueError('safety_gate_report_invalid')
        return self


class SafetyGateAlert(OfficialModel):
    alert_id: str
    case_number: str = Field(min_length=1, max_length=80)
    published_date: str
    source_url: str
    fields: dict[str, str | None]
    pictures: list[str] = Field(max_length=100)
    applicability: Literal['not_assessed']

    @model_validator(mode='after')
    def checked_identity(self):
        import re
        if (not re.fullmatch(r'-?[1-9][0-9]{0,11}', self.alert_id, re.ASCII)
                or self.source_url != source.BASE + '/screen/webReport/alertDetail/' + self.alert_id
                or set(self.fields) != source.ALERT_FIELDS - {'pictures'}
                or self.fields['caseNumber'] != self.case_number or self.fields['reference'] != self.source_url
                or source._date(self.fields['publicationDate'], '%d-%m-%Y') != self.published_date
                or any(value is not None and (len(value) > 60000 or '\x00' in value) for value in self.fields.values())
                or any(not re.fullmatch(re.escape(source.BASE) + r'/public/api/notification/image/-?[1-9][0-9]{0,11}', value) for value in self.pictures)):
            raise ValueError('safety_gate_alert_invalid')
        return self


class SafetyGateDocument(OfficialModel):
    operation: Literal['reports', 'report']
    reports: list[ReportSummary] = Field(max_length=3000)
    report: ReportSummary | None
    alerts: list[SafetyGateAlert] = Field(max_length=1000)

    @model_validator(mode='after')
    def complete_document(self):
        if self.operation == 'reports':
            if self.report is not None or self.alerts or len({row.report_id for row in self.reports}) != len(self.reports) or len({row.reference for row in self.reports}) != len(self.reports):
                raise ValueError('safety_gate_index_invalid')
        elif (self.reports or self.report is None or len({row.alert_id for row in self.alerts}) != len(self.alerts)
                or len({row.case_number for row in self.alerts}) != len(self.alerts)
                or any(row.fields['order'] != str(index) for index, row in enumerate(self.alerts, 1))):
            raise ValueError('safety_gate_report_invalid')
        return self


def checked_document(value, query):
    document = SafetyGateDocument.model_validate(value)
    if (document.operation != query['operation'] or document.operation == 'report'
            and (document.report.report_id != query['report_id'] or document.report.reference != query['reference'])):
        raise ValueError('safety_gate_query_mismatch')
    return document.model_dump(exclude_unset=True)


class SafetyGateSnapshot(Base):
    __tablename__ = 'safety_gate_snapshots'
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
    license_basis: Mapped[dict] = mapped_column(JSON)
    attribution: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SafetyGateVerification(Base):
    __tablename__ = 'safety_gate_verifications'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('safety_gate_snapshots.id'), index=True)
    query_id: Mapped[str] = mapped_column(ForeignKey('query_runs.id'), unique=True)
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24))
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_safety_gate(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (SafetyGateSnapshot, SafetyGateVerification)) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('Safety Gate证据与核验记录只能追加')


def checked_snapshot(snapshot):
    if snapshot is not None:
        try:
            if (snapshot.source_id != source.SOURCE_ID or snapshot.query_key != digest(snapshot.query)
                    or snapshot.source_url != source.query_url(snapshot.query) or snapshot.content_type != 'application/xml'
                    or sha256(snapshot.body.encode('utf-8')).hexdigest() != snapshot.raw_hash
                    or digest(snapshot.document) != snapshot.document_hash
                    or checked_document(snapshot.document, snapshot.query) != snapshot.document):
                raise ValueError('safety_gate_snapshot_invalid')
        except (ValueError, TypeError, KeyError):
            raise HTTPException(503, 'Safety Gate历史证据完整性校验失败') from None
    return snapshot


class SafetyGateService:
    def __init__(self, db, adapter, registry=None, *, ingestion_guard=None):
        self.db, self.adapter = db, adapter
        self.ingestion_guard = ingestion_guard
        self.shared = QueryService(db, registry, ingestion_guard=ingestion_guard)

    def latest(self, key):
        return checked_snapshot(self.db.scalar(select(SafetyGateSnapshot).join(SafetyGateVerification)
            .where(SafetyGateVerification.query_key == key)
            .order_by(desc(SafetyGateVerification.verified_at), desc(SafetyGateVerification.id)).limit(1)))

    def transport_cache(self, key):
        row = self.db.execute(select(SafetyGateSnapshot.id, SafetyGateSnapshot.source_url,
            SafetyGateSnapshot.body, SafetyGateSnapshot.raw_hash, SafetyGateSnapshot.content_type,
            SafetyGateSnapshot.parser_version, SafetyGateVerification.parser_identity,
            SafetyGateVerification.etag, SafetyGateVerification.last_modified).join(SafetyGateVerification)
            .where(SafetyGateVerification.query_key == key)
            .order_by(desc(SafetyGateVerification.verified_at), desc(SafetyGateVerification.id)).limit(1)).first()
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
            self.shared.audit(session_id, 'safety_gate_online_started', run.id, query=query)
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
            result = {'status': 'unavailable', 'reason': 'safety_gate_fetch_failed'}
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
                        raise ValueError('safety_gate_304_invalid')
                    result = {**cache, **result}
                    result['etag'] = result.get('etag') or cache.get('etag')
                    result['last_modified'] = result.get('last_modified') or cache.get('last_modified')
                if (validated_observation(result, source_id=source.SOURCE_ID, query=query) is None
                        or result['url'] != source.query_url(query) or result['content_type'] != 'application/xml'
                        or '\x00' in result['body']):
                    raise ValueError('safety_gate_observation_invalid')
                document = None if result['status'] == 'not_modified' else checked_document(result['document'], query)
                if result['status'] == 'not_modified' and sha256(result['body'].encode('utf-8')).hexdigest() != cache['raw_hash']:
                    raise ValueError('safety_gate_304_body_invalid')
            except (ValueError, TypeError, KeyError):
                retain_rejected_response(self.db, run, result, 'schema')
                self.db.commit()
                result = {'status': 'unavailable', 'reason': 'safety_gate_schema_changed'}
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
                    self.shared.audit(session_id, 'safety_gate_online_succeeded', run.id, snapshot_id=snapshot.id)
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
        run.reason = str(result.get('reason') or 'safety_gate_unavailable')[:200]
        self.shared.audit(session_id, 'safety_gate_online_failed', run.id, reason=run.reason)
        self.db.commit()
        from .query_fallback_policies import claim_policy_use, authorized_result
        use = claim_policy_use(self.db, self.shared.registry, run, 'safety_gate_' + query['operation'], audience)
        if use is not None:
            snapshot = self.latest(key)
            self.shared.audit(session_id, 'policy_safety_gate_snapshot_read', run.id, use_id=use.id,
                snapshot_id=snapshot.id if snapshot else None)
            response = self.response(query, 'local_snapshot', snapshot, run.id,
                reason=run.reason if snapshot else 'no_matching_safety_gate_snapshot')
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
                raise ParserDeploymentError('safety_gate_cache_head_changed', 409)
        else:
            raw_hash = sha256(result['body'].encode('utf-8')).hexdigest()
            document_hash = digest(document)
            if (snapshot is None or snapshot.raw_hash != raw_hash or snapshot.document_hash != document_hash
                    or snapshot.parser_version != result['parser_version'] or snapshot.parser_identity != result.get('parser_identity')):
                snapshot = SafetyGateSnapshot(id=uid(), query=run.query, query_key=run.query_key,
                    source_url=result['url'], raw_hash=raw_hash, body=result['body'], content_type=result['content_type'],
                    parser_version=result['parser_version'], parser_identity=result.get('parser_identity'),
                    document=document, document_hash=document_hash, license_basis=dict(source.LICENSE),
                    attribution=source.ATTRIBUTION)
                self.db.add(snapshot)
                self.db.flush()
        verified = utcnow()
        self.db.add(SafetyGateVerification(snapshot_id=snapshot.id, query_id=run.id, query_key=run.query_key,
            status='not_modified' if result['status'] == 'not_modified' else 'ok',
            etag=result.get('etag'), last_modified=result.get('last_modified'),
            parser_identity=result.get('parser_identity'), verified_at=verified))
        self.db.flush()
        from .safety_gate_alerts import backfill_alert_history
        backfill_alert_history(self.db)
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
            raise HTTPException(403, '离线授权的来源、周报或策略不匹配')
        try:
            self.shared.assert_source_access(run)
        except SourceAccessBlocked as error:
            return self.blocked(query, run, error)
        from .query_fallback_policies import assert_once_policy
        assert_once_policy(self.db, self.shared.registry, run, 'safety_gate_' + query['operation'], audience)
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
        self.shared.audit(session_id, 'safety_gate_local_snapshot_read', run.id, consent.id,
            snapshot_id=snapshot.id if snapshot else None)
        self.db.commit()
        return self.response(query, 'local_snapshot', snapshot, run.id, reason=run.reason, consent_id=consent.id)

    def response(self, query, state, snapshot=None, query_id=None, *, verified_at=None, reason=None, consent_id=None):
        checked_snapshot(snapshot)
        if snapshot is not None and verified_at is None:
            verified_at = self.db.scalar(select(SafetyGateVerification.verified_at)
                .where(SafetyGateVerification.snapshot_id == snapshot.id)
                .order_by(desc(SafetyGateVerification.verified_at)).limit(1))
        return {'query_id': query_id, 'source_id': source.SOURCE_ID, 'query': query, 'data_state': state,
            'reason': reason, 'consent_id': consent_id, 'verified_at': timestamp(verified_at),
            'snapshot_observed_at': timestamp(snapshot.observed_at) if snapshot else None,
            'document': snapshot.document if snapshot else None, 'notices': NOTICES,
            'provenance': [{'snapshot_id': snapshot.id, 'source_id': snapshot.source_id,
                'source_url': snapshot.source_url, 'raw_hash': snapshot.raw_hash,
                'observed_at': timestamp(snapshot.observed_at), 'parser_version': snapshot.parser_version,
                'parser_identity': snapshot.parser_identity, 'license_basis': snapshot.license_basis,
                'attribution': snapshot.attribution,
                'evidence_path': f'/v1/safety-gate/evidence/{snapshot.id}?mode=history'}] if snapshot else []}


def register_safety_gate_routes(app: FastAPI):
    from .safety_gate_alerts import register_alert_history_routes
    register_alert_history_routes(app)

    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/safety-gate/query')
    async def query(payload: SafetyGateRequest, request: Request, db: Session = Depends(get_db)):
        adapter = getattr(app.state, 'safety_gate_adapter', None) or source
        from .query_ownership import QueryOwnershipError, capture_query_actor
        try:
            actor = None if payload.consent_id else capture_query_actor(db, request.state.session_id)
            return await SafetyGateService(db, adapter, app.state.registry).execute(payload, request.state.session_id,
                audience='programmatic', owner_actor=actor)
        except QueryOwnershipError as error:
            raise HTTPException(401 if error.code == 'query_actor_invalid' else 409, {'code': error.code}) from None

    @app.get('/v1/safety-gate/history')
    def history(request: Request, operation: Literal['reports', 'report'], mode: Literal['history'],
                report_id: str | None = None, reference: str | None = None, db: Session = Depends(get_db)):
        try:
            query = SafetyGateQuery(operation=operation, report_id=report_id, reference=reference).canonical()
        except ValueError:
            raise HTTPException(422, 'Safety Gate历史查询条件无效') from None
        service = SafetyGateService(db, None)
        snapshot = service.latest(digest(query))
        service.shared.audit(request.state.session_id, 'safety_gate_history_read', query=query)
        db.commit()
        return service.response(query, 'local_snapshot', snapshot, reason='explicit_history' if snapshot else 'no_matching_safety_gate_snapshot')

    @app.get('/v1/safety-gate/evidence/{snapshot_id}')
    def evidence(snapshot_id: str, request: Request, mode: Literal['history'], db: Session = Depends(get_db)):
        snapshot = checked_snapshot(db.get(SafetyGateSnapshot, snapshot_id))
        if snapshot is None:
            raise HTTPException(404, '未找到Safety Gate证据')
        service = SafetyGateService(db, None)
        service.shared.audit(request.state.session_id, 'safety_gate_evidence_history_read', snapshot_id=snapshot.id)
        db.commit()
        return {'id': snapshot.id, 'query': snapshot.query, 'body': snapshot.body,
            'content_type': snapshot.content_type, 'data_state': 'local_snapshot',
            **service.response(snapshot.query, 'local_snapshot', snapshot)['provenance'][0]}
