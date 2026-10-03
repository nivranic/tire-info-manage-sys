"""Single-page NHTSA tire discovery evidence; candidates never adopt campaigns."""
from __future__ import annotations

import hashlib
from datetime import datetime
import re
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator
from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, desc, event, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from .adapters import nhtsa
from .captures import before_parse_recorder, retain_rejected_response, validated_observation
from .db import Base, FallbackConsent, QueryRun, uid, utc, utcnow
from .domain import StrictModel, digest
from .parser_provenance import check_result_identity, execution_outcome, parser_identity, verified_observation_recorder
from .recall_models import SOURCE_ID, RecallQuery
from .service import CONSENT_TTL, QueryService, timestamp
from .source_settings import SourceAccessBlocked

NOTICES = ["本页为美国 NHTSA 轮胎产品目录检索候选，未采纳为召回公告版本。",
           "名称和尺寸匹配不确认具体 SKU 或实物适用；须核对 DOT/TIN、生产批次及官方措施。",
           "仅显示当前页；本页没有召回不表示其他页、其他地区或具体轮胎无召回风险。"]


class RecallSearchQuery(StrictModel):
    search: str = Field(min_length=1, max_length=120)
    offset: StrictInt = Field(default=0, ge=0, le=10000, multiple_of=10)

    @field_validator("search")
    @classmethod
    def clean_search(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value or "\x00" in value or any(ord(char) < 32 for char in value):
            raise ValueError("请输入品牌或胎型搜索词")
        value.encode("utf-8", errors="strict")
        return value

    def canonical(self) -> dict[str, str]:
        return {"search": self.search, "offset": str(self.offset)}


class RecallSearchRequest(StrictModel):
    query: RecallSearchQuery
    fallback_policy: Literal["ask", "never"] = "ask"
    consent_id: str | None = Field(default=None, min_length=1, max_length=64)


class OfficialSearchModel(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    @field_validator("*", mode="after")
    @classmethod
    def bounded_text(cls, value: Any):
        if isinstance(value, str):
            if len(value) > 60000 or "\x00" in value:
                raise ValueError("官方字段超出长度或字符限制")
            value.encode("utf-8", errors="strict")
        return value


class SearchDocument(OfficialSearchModel):
    url: str = Field(max_length=8192)
    title: str | None = Field(default=None, max_length=60000)

    @field_validator("url")
    @classmethod
    def official_document(cls, value: str) -> str:
        parts = urlsplit(value)
        if (parts.scheme != "https" or parts.netloc != "static.nhtsa.gov" or parts.query or parts.fragment
                or not re.fullmatch(r"/odi/rcl/[0-9]{4}/[A-Za-z0-9_-]+\.(?:pdf|PDF)", parts.path)):
            raise ValueError("附件不是官方召回原文地址")
        return value


class SearchCampaign(OfficialSearchModel):
    campaign_number: str
    subject: str | None = None
    report_received_at: str
    summary: str
    consequence: str
    remedy: str
    manufacturer: str
    notes: str | None = None
    documents: list[SearchDocument] = Field(max_length=1000)
    associated_products: list[dict] = Field(max_length=1000)

    @field_validator("campaign_number")
    @classmethod
    def valid_campaign(cls, value: str) -> str:
        number = RecallQuery(campaign_number=value).campaign_number
        if number != value:
            raise ValueError("召回编号未规范化")
        return number

    @field_validator("report_received_at")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if not value.endswith("Z") or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("召回日期无效")
        return value


class SearchProduct(OfficialSearchModel):
    id: StrictInt = Field(gt=0)
    artemis_id: StrictInt = Field(gt=0)
    brand: str = Field(min_length=1, max_length=60000)
    tireline: str = Field(min_length=1, max_length=60000)
    size: str | None = Field(default=None, max_length=60000)
    recalls_count: StrictInt = Field(ge=0, le=1000)
    campaigns: list[SearchCampaign] = Field(max_length=1000)
    applicability: Literal["not_assessed"] = "not_assessed"

    @model_validator(mode="after")
    def campaign_count(self):
        if (not self.brand.strip() or not self.tireline.strip() or len(self.campaigns) != self.recalls_count
                or len({row.campaign_number for row in self.campaigns}) != len(self.campaigns)):
            raise ValueError("目录召回数量不完整")
        return self


class SearchPagination(StrictModel):
    offset: StrictInt = Field(ge=0, le=10000, multiple_of=10)
    max: Literal[10]
    count: StrictInt = Field(ge=0, le=10)
    total: StrictInt = Field(ge=0, le=10000000)
    has_next: StrictBool
    has_previous: StrictBool


class SearchDiscovery(StrictModel):
    products: list[SearchProduct] = Field(max_length=10)
    pagination: SearchPagination

    @model_validator(mode="after")
    def coherent_page(self):
        page = self.pagination
        if (page.count != len(self.products) or page.count != min(10, max(0, page.total - page.offset))
                or page.has_next != (page.offset + page.count < page.total)
                or page.has_previous != (page.offset > 0)
                or len({row.id for row in self.products}) != len(self.products)):
            raise ValueError("目录分页信息不一致")
        return self


class RecallSearchSnapshot(Base):
    __tablename__ = "recall_search_snapshots"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(String(80), default=SOURCE_ID)
    query: Mapped[dict] = mapped_column(JSON)
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    raw_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120))
    parser_version: Mapped[str] = mapped_column(String(100))
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    discovery: Mapped[dict] = mapped_column(JSON)
    discovery_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallSearchVerification(Base):
    __tablename__ = "recall_search_verifications"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("recall_search_snapshots.id"), index=True)
    query_id: Mapped[str] = mapped_column(ForeignKey("query_runs.id"), unique=True)
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24))
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, "before_flush")
def protect_search_evidence(session: Session, _context: Any, _instances: Any) -> None:
    for row in session.dirty | session.deleted:
        if isinstance(row, (RecallSearchSnapshot, RecallSearchVerification)) and (row in session.deleted or session.is_modified(row)):
            raise ValueError("召回检索证据只能追加，不能修改或删除")


def search_provenance(snapshot: RecallSearchSnapshot) -> dict:
    return {"snapshot_id": snapshot.id, "source_id": snapshot.source_id, "source_url": snapshot.source_url,
            "parser_version": snapshot.parser_version, "parser_identity": snapshot.parser_identity,
            "raw_hash": snapshot.raw_hash, "observed_at": timestamp(snapshot.observed_at),
            "evidence_path": f"/v1/recall-search-evidence/{snapshot.id}?mode=history"}


class RecallDiscoveryService:
    def __init__(self, db: Session, adapter: Any, *, ingestion_guard: Callable | None = None,
                 on_query_started: Callable[[str], None] | None = None, policy_registry=None):
        self.db, self.adapter, self.ingestion_guard = db, adapter, ingestion_guard
        self.on_query_started = on_query_started
        self.shared = QueryService(db, policy_registry, ingestion_guard=ingestion_guard)

    def latest(self, key: str) -> RecallSearchSnapshot | None:
        return self.db.scalar(select(RecallSearchSnapshot).join(RecallSearchVerification)
            .where(RecallSearchVerification.query_key == key)
            .order_by(desc(RecallSearchVerification.verified_at), desc(RecallSearchVerification.id)).limit(1))

    def transport_cache(self, key: str) -> dict | None:
        # Transport metadata and raw bytes only: no historical parsed candidates.
        row = self.db.execute(select(RecallSearchSnapshot.id, RecallSearchSnapshot.source_url,
            RecallSearchSnapshot.body, RecallSearchSnapshot.raw_hash, RecallSearchSnapshot.content_type,
            RecallSearchSnapshot.parser_version, RecallSearchVerification.parser_identity,
            RecallSearchVerification.etag, RecallSearchVerification.last_modified)
            .join(RecallSearchVerification).where(RecallSearchVerification.query_key == key)
            .order_by(desc(RecallSearchVerification.verified_at), desc(RecallSearchVerification.id)).limit(1)).first()
        if row is None:
            return None
        return {"snapshot_id": row.id, "url": row.source_url, "body": row.body, "raw_hash": row.raw_hash,
                "content_type": row.content_type, "parser_version": row.parser_version,
                "parser_identity": row.parser_identity, "etag": row.etag, "last_modified": row.last_modified}

    async def execute(self, request: RecallSearchRequest, session_id: str, *, audience='internal') -> dict:
        from .telemetry import observe
        with observe('source.query', component='crawler', source='nhtsa') as operation:
            result = await self._execute(request, session_id, audience=audience)
            operation.finish(result['data_state'])
            return result

    async def _execute(self, request: RecallSearchRequest, session_id: str, *, audience='internal') -> dict:
        query = request.query.canonical()
        key = digest(query)
        if request.consent_id:
            return self.consume_consent(request, session_id, key, audience=audience)
        run = QueryRun(id=uid(), session_id=session_id, source_id=SOURCE_ID, query=query,
                       query_key=key, fallback_policy=request.fallback_policy)
        self.db.add(run)
        self.shared.audit(session_id, "recall_search_online_started", run.id, search=query["search"], offset=query["offset"])
        self.db.commit()
        if self.on_query_started is not None:
            self.on_query_started(run.id)
        try:
            self.shared.pin_source_access(run)
        except SourceAccessBlocked as error:
            return self.block_source_access(query, run, error)
        cached = self.transport_cache(key)
        self.db.commit()
        from .parser_releases import ParserDeploymentError, pin_selection, record_execution
        selection = None
        try:
            kwargs = {}
            recorder = before_parse_recorder(self.db, run)
            if getattr(self.adapter, "supports_parser_deployments", False) is True:
                selection = pin_selection(self.db, run.id, SOURCE_ID)
                kwargs["parser_selection"] = selection
                recorder = verified_observation_recorder(recorder, selection)
            result = await self.adapter.fetch(query, cached=cached, on_observation=recorder, **kwargs)
        except ParserDeploymentError as error:
            self.db.rollback()
            result = {"status": "unavailable", "reason": error.code}
        except Exception:
            result = {"status": "unavailable", "reason": "recall_search_fetch_failed"}
        if selection is not None:
            try:
                record_execution(self.db, run.id, execution_outcome(result))
            except ParserDeploymentError as error:
                if not error.execution_recorded:
                    self.db.rollback()
                result = {"status": "unavailable", "reason": error.code}
            self.db.commit()
        if result.get("status") in {"ok", "not_modified"}:
            try:
                if result["status"] == "not_modified":
                    if (not self.shared.valid_304(cached, result, require_identity=True, require_tire_identity_contract=False)
                            or result.get("parser_version") != cached["parser_version"]):
                        raise ValueError("304 在线验证器或 Parser 身份不符")
                    result = {**cached, **result}
                    result["etag"] = result.get("etag") or cached.get("etag")
                    result["last_modified"] = result.get("last_modified") or cached.get("last_modified")
                if (validated_observation(result) is None or "\x00" in result["body"]
                        or result["url"] != nhtsa.query_url(query) or result["content_type"] != "application/json"):
                    raise ValueError("检索来源证据不符")
                if result["status"] == "not_modified":
                    if (cached is None or parser_identity(result.get("parser_identity")) is None
                            or result["url"] != cached["url"]
                            or hashlib.sha256(result["body"].encode("utf-8")).hexdigest() != cached["raw_hash"]
                            or result.get("parser_identity") != cached["parser_identity"]
                            or result["parser_version"] != cached["parser_version"]):
                        raise ValueError("304 检索原文或 Parser 身份不匹配")
                    discovery = None
                else:
                    discovery = SearchDiscovery.model_validate(result.get("discovery")).model_dump()
                    if discovery["pagination"]["offset"] != int(query["offset"]):
                        raise ValueError("检索页码不匹配")
            except (ValueError, TypeError, KeyError, UnicodeError):
                retain_rejected_response(self.db, run, result, "schema")
                self.db.commit()
                result = {"status": "unavailable", "reason": "recall_search_schema_changed"}
            else:
                try:
                    snapshot, verified_at = self.persist(run, result, discovery, cached, selection)
                except SourceAccessBlocked as error:
                    return self.block_source_access(query, run, error)
                except ParserDeploymentError as error:
                    self.db.rollback()
                    result = {"status": "unavailable", "reason": error.code}
                else:
                    run.state = "live"
                    self.shared.audit(session_id, "recall_search_online_succeeded", run.id, snapshot_id=snapshot.id)
                    if self.ingestion_guard:
                        self.ingestion_guard(self.db)
                    self.db.commit()
                    state = "live_verified_304" if result["status"] == "not_modified" else "live"
                    return self.response(query, state, snapshot, run.id, verified_at=verified_at,
                        reason="no_results" if not snapshot.discovery["products"] else None)
        if result.get("rejected_observation") is not None:
            retain_rejected_response(self.db, run, result["rejected_observation"], "parser")
            self.db.commit()
        self.shared.lock_ingestion()
        try:
            self.shared.assert_source_access(run)
        except SourceAccessBlocked as error:
            return self.block_source_access(query, run, error)
        if self.ingestion_guard:
            self.ingestion_guard(self.db)
        run.state = "consent_required" if request.fallback_policy == "ask" else "source_unavailable"
        run.reason = str(result.get("reason") or "recall_search_unavailable")[:200]
        self.shared.audit(session_id, "recall_search_online_failed", run.id, reason=run.reason)
        self.db.commit()
        from .query_fallback_policies import claim_policy_use, authorized_result
        use = claim_policy_use(self.db, self.shared.registry, run, 'recall_search', audience)
        if use is not None:
            snapshot = self.latest(key)
            self.shared.audit(session_id, 'policy_recall_search_snapshot_read', run.id, use_id=use.id,
                              snapshot_id=snapshot.id if snapshot else None)
            response = self.response(query, 'local_snapshot', snapshot, run.id,
                                     reason=run.reason if snapshot else 'no_matching_recall_search_snapshot')
            return authorized_result(self.db, self.shared.registry, run, use, response)
        return self.response(query, run.state, query_id=run.id, reason=run.reason)

    def block_source_access(self, query, run, error):
        self.shared.block_source_access(run, error)
        return self.response(query, run.state, query_id=run.id, reason=run.reason)

    def persist(self, run, result, discovery, cached, selection):
        self.shared.lock_ingestion()
        self.shared.assert_source_access(run)
        if self.ingestion_guard:
            self.ingestion_guard(self.db)
        if selection is not None:
            from .parser_releases import assert_selection_current
            assert_selection_current(self.db, selection)
            check_result_identity(selection, result)
        now = utcnow()
        if result["status"] == "not_modified":
            snapshot = self.latest(run.query_key)
            if snapshot is None or snapshot.id != cached["snapshot_id"]:
                from .parser_releases import ParserDeploymentError
                raise ParserDeploymentError("recall_search_cache_head_changed", 409)
        else:
            raw_hash = hashlib.sha256(result["body"].encode("utf-8")).hexdigest()
            discovery_hash = digest(discovery)
            last = self.latest(run.query_key)
            snapshot = last
            if (last is None or last.raw_hash != raw_hash or last.discovery_hash != discovery_hash
                    or last.parser_version != result["parser_version"] or last.parser_identity != result.get("parser_identity")):
                snapshot = RecallSearchSnapshot(id=uid(), source_id=SOURCE_ID, query=run.query, query_key=run.query_key,
                    source_url=result["url"], raw_hash=raw_hash, body=result["body"], content_type=result["content_type"],
                    parser_version=result["parser_version"], parser_identity=result.get("parser_identity"),
                    discovery=discovery, discovery_hash=discovery_hash, observed_at=now)
                self.db.add(snapshot)
                self.db.flush()
        self.db.add(RecallSearchVerification(snapshot_id=snapshot.id, query_id=run.id, query_key=run.query_key,
            status="not_modified" if result["status"] == "not_modified" else "ok", verified_at=now,
            parser_identity=result.get("parser_identity"), etag=result.get("etag"), last_modified=result.get("last_modified")))
        return snapshot, now

    def consume_consent(self, request, session_id, key, *, audience='internal'):
        self.shared.lock_ingestion()
        consent = self.db.get(FallbackConsent, request.consent_id)
        if consent is None or consent.session_id != session_id:
            raise HTTPException(403, "离线授权不属于当前会话")
        run = self.db.get(QueryRun, consent.query_id)
        if (run is None or run.session_id != session_id or run.source_id != SOURCE_ID or run.query_key != key
                or run.query != request.query.canonical() or run.fallback_policy != "ask"
                or request.fallback_policy != "ask" or consent.decision != "allow" or consent.scope != "once"):
            raise HTTPException(403, "检索授权的来源、搜索词、页码、策略或范围不匹配")
        try:
            self.shared.assert_source_access(run)
        except SourceAccessBlocked as error:
            return self.block_source_access(request.query.canonical(), run, error)
        now = utcnow()
        if utc(consent.expires_at) <= now or utc(run.created_at) + CONSENT_TTL <= now:
            raise HTTPException(410, "召回检索离线授权已过期")
        from .query_fallback_policies import assert_once_policy
        assert_once_policy(self.db, self.shared.registry, run, 'recall_search', audience)
        claimed = self.db.execute(update(FallbackConsent).where(FallbackConsent.id == consent.id,
            FallbackConsent.session_id == session_id, FallbackConsent.used_at.is_(None),
            FallbackConsent.decision == "allow", FallbackConsent.scope == "once", FallbackConsent.expires_at > now)
            .values(used_at=now).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            raise HTTPException(409, "召回检索离线授权已经使用")
        snapshot = self.latest(key)
        run.state = "local_snapshot"
        self.shared.audit(session_id, "recall_search_local_snapshot_read", run.id, consent.id,
                          snapshot_id=snapshot.id if snapshot else None)
        self.db.commit()
        assert_once_policy(self.db, self.shared.registry, run, 'recall_search', audience)
        response = self.response(request.query.canonical(), "local_snapshot", snapshot, run.id,
            consent_id=consent.id, reason=run.reason if snapshot else "no_matching_recall_search_snapshot")
        if audience == 'programmatic':
            self.db.commit()
        return response

    def response(self, query, state, snapshot=None, query_id=None, *, verified_at=None, reason=None, consent_id=None):
        if snapshot and verified_at is None:
            verified_at = self.db.scalar(select(RecallSearchVerification.verified_at)
                .where(RecallSearchVerification.snapshot_id == snapshot.id)
                .order_by(desc(RecallSearchVerification.verified_at)).limit(1))
        return {"query_id": query_id, "source_id": SOURCE_ID, "query": query, "data_state": state,
            "reason": reason, "verified_at": timestamp(verified_at), "consent_id": consent_id,
            "snapshot_observed_at": timestamp(snapshot.observed_at) if snapshot else None,
            "snapshot_age_seconds": max(0, int((utcnow() - utc(snapshot.observed_at)).total_seconds())) if snapshot else None,
            "products": snapshot.discovery["products"] if snapshot else [],
            "pagination": snapshot.discovery["pagination"] if snapshot else None,
            "provenance": [search_provenance(snapshot)] if snapshot else [], "notices": NOTICES}


def register_recall_discovery_routes(app: FastAPI) -> None:
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post("/v1/recalls/search")
    async def search(payload: RecallSearchRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        adapter = getattr(app.state, "recall_adapter", None) or nhtsa
        return await RecallDiscoveryService(db, adapter, policy_registry=app.state.registry).execute(
            payload, request.state.session_id, audience='programmatic')

    @app.get("/v1/recalls/search-history")
    def history(request: Request, search: str = Query(..., min_length=1, max_length=120),
                offset: int = Query(0, ge=0, le=10000, multiple_of=10),
                mode: Literal["history"] = Query(...), db: Session = Depends(get_db)) -> dict:
        try:
            query = RecallSearchQuery(search=search, offset=offset).canonical()
        except ValueError:
            raise HTTPException(422, "检索条件无效") from None
        service = RecallDiscoveryService(db, None)
        snapshot = service.latest(digest(query))
        service.shared.audit(request.state.session_id, "recall_search_history_read", search=query["search"], offset=query["offset"])
        db.commit()
        return service.response(query, "local_snapshot", snapshot,
            reason="explicit_history" if snapshot else "no_matching_recall_search_snapshot")

    @app.get("/v1/recall-search-evidence/{snapshot_id}")
    def evidence(snapshot_id: str, request: Request, mode: Literal["history"] = Query(...),
                 db: Session = Depends(get_db)) -> dict:
        snapshot = db.get(RecallSearchSnapshot, snapshot_id)
        if snapshot is None:
            raise HTTPException(404, "未找到召回检索证据")
        if hashlib.sha256(snapshot.body.encode("utf-8")).hexdigest() != snapshot.raw_hash:
            raise HTTPException(503, "检索原文完整性校验失败")
        verified = db.scalar(select(RecallSearchVerification.verified_at)
            .where(RecallSearchVerification.snapshot_id == snapshot.id)
            .order_by(desc(RecallSearchVerification.verified_at)).limit(1))
        QueryService(db, None).audit(request.state.session_id, "recall_search_evidence_history_read", snapshot_id=snapshot.id)
        db.commit()
        return {"id": snapshot.id, "query": snapshot.query, **search_provenance(snapshot),
            "verified_at": timestamp(verified), "content_type": snapshot.content_type, "body": snapshot.body,
            "data_state": "local_snapshot"}
