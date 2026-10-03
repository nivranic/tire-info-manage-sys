"""Online-first NHTSA campaign evidence, with a separate recall consent gate."""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import desc, select, update
from sqlalchemy.orm import Session

from .captures import before_parse_recorder, retain_rejected_response, validated_observation
from .source_settings import SourceAccessBlocked
from .db import FallbackConsent, QueryRun, uid, utc, utcnow
from .domain import digest
from .parser_provenance import check_result_identity, execution_outcome, parser_identity, verified_observation_recorder
from .recall_models import (SOURCE_ID, RecallEvent, RecallLiveRequest, RecallQuery, RecallRecord,
                            RecallRevision, RecallSnapshot, RecallVerification)
from .service import CONSENT_TTL, QueryService, timestamp

NOTICES = ["本来源为美国 NHTSA 轮胎召回公告；不代表其他地区的全部召回。",
           "产品名称匹配不能证明具体轮胎受影响。DOT/TIN、生产批次及适用性未评估，请按官方措施核对。",
           "首次观察表示本系统首次记录，不表示公告刚刚发布；空结果不表示无风险或召回解除。"]


def campaign_url(campaign_number: str) -> str:
    return "https://api.nhtsa.gov/recalls/campaignNumber?campaignNumber=" + campaign_number


def recall_provenance(snapshot: RecallSnapshot) -> dict:
    return {"snapshot_id": snapshot.id, "source_id": snapshot.source_id, "source_url": snapshot.source_url,
            "parser_version": snapshot.parser_version, "parser_identity": snapshot.parser_identity,
            "raw_hash": snapshot.raw_hash, "observed_at": timestamp(snapshot.observed_at),
            "evidence_path": f"/v1/recall-evidence/{snapshot.id}?mode=history"}


def canonical_records(values: Any, campaign_number: str) -> list[dict]:
    if not isinstance(values, list) or len(values) > 1000:
        raise ValueError("召回结果集合无效")
    records = [RecallRecord.model_validate(row).model_dump() for row in values]
    if any(row["campaign_number"] != campaign_number for row in records):
        raise ValueError("召回记录不属于所查询公告")
    # A campaign can contain multiple product records. Preserve the whole multiset;
    # ordering alone is not a semantic change and no one product overwrites another.
    return sorted(records, key=digest)


class RecallService:
    def __init__(self, db: Session, adapter: Any, *, ingestion_guard: Callable | None = None, policy_registry=None):
        self.db, self.adapter, self.ingestion_guard = db, adapter, ingestion_guard
        self.shared = QueryService(db, policy_registry, ingestion_guard=ingestion_guard)

    def latest(self, campaign: str) -> RecallSnapshot | None:
        return self.db.scalar(select(RecallSnapshot).join(RecallVerification)
            .where(RecallSnapshot.campaign_number == campaign)
            .order_by(desc(RecallVerification.verified_at), desc(RecallVerification.id)).limit(1))

    def transport_cache(self, key: str) -> dict | None:
        # Never select parsed records or campaign revisions before live success or consent.
        row = self.db.execute(select(RecallSnapshot.id, RecallSnapshot.source_url, RecallSnapshot.body,
            RecallSnapshot.raw_hash, RecallSnapshot.content_type, RecallSnapshot.parser_version,
            RecallVerification.parser_identity, RecallVerification.etag, RecallVerification.last_modified)
            .join(RecallVerification).where(RecallVerification.query_key == key)
            .order_by(desc(RecallVerification.verified_at), desc(RecallVerification.id)).limit(1)).first()
        if row is None:
            return None
        return {"snapshot_id": row.id, "url": row.source_url, "body": row.body, "raw_hash": row.raw_hash,
                "content_type": row.content_type, "parser_version": row.parser_version,
                "parser_identity": row.parser_identity, "etag": row.etag, "last_modified": row.last_modified}

    async def execute(self, request: RecallLiveRequest, session_id: str, *, audience='internal') -> dict:
        from .telemetry import observe
        with observe('source.query', component='crawler', source='nhtsa') as operation:
            result = await self._execute(request, session_id, audience=audience)
            operation.finish(result['data_state'])
            return result

    async def _execute(self, request: RecallLiveRequest, session_id: str, *, audience='internal') -> dict:
        query = request.query.canonical()
        campaign, key = query["campaign_number"], digest(query)
        if request.consent_id:
            return self.consume_consent(request, session_id, key, audience=audience)
        run = QueryRun(id=uid(), session_id=session_id, source_id=SOURCE_ID, query=query,
                       query_key=key, fallback_policy=request.fallback_policy)
        self.db.add(run)
        self.shared.audit(session_id, "recall_online_started", run.id, campaign_number=campaign)
        self.db.commit()
        try:
            self.shared.pin_source_access(run)
        except SourceAccessBlocked as error:
            return self.block_source_access(campaign, run, error)
        cached = self.transport_cache(key)
        self.db.commit()  # Do not hold a DB transaction across transport/parser work.
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
            result = {"status": "unavailable", "reason": "recall_source_fetch_failed"}
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
                        raise ValueError("304 未通过在线验证器与 Parser 身份校验")
                    result = {**cached, **result}
                    result["etag"] = result.get("etag") or cached.get("etag")
                    result["last_modified"] = result.get("last_modified") or cached.get("last_modified")
                if (validated_observation(result) is None or "\x00" in result["body"]
                        or result["url"] != campaign_url(campaign)
                        or result["content_type"] != "application/json"):
                    raise ValueError("召回来源证据不符")
                if result["status"] == "not_modified":
                    if (cached is None or parser_identity(result.get("parser_identity")) is None
                            or result["url"] != cached["url"]
                            or hashlib.sha256(result["body"].encode()).hexdigest() != cached["raw_hash"]
                            or result.get("parser_identity") != cached["parser_identity"]
                            or result["parser_version"] != cached["parser_version"]):
                        raise ValueError("304 未通过原文及 Parser 身份校验")
                    records = None
                else:
                    records = canonical_records(result.get("records"), campaign)
            except (ValueError, TypeError, KeyError, UnicodeError):
                retain_rejected_response(self.db, run, result, "schema")
                self.db.commit()
                result = {"status": "unavailable", "reason": "recall_source_schema_changed"}
            else:
                try:
                    snapshot, verified_at = self.persist(run, result, records, cached, selection)
                except SourceAccessBlocked as error:
                    return self.block_source_access(campaign, run, error)
                except ParserDeploymentError as error:
                    self.db.rollback()
                    result = {"status": "unavailable", "reason": error.code}
                else:
                    run.state = "live"
                    self.shared.audit(session_id, "recall_online_succeeded", run.id, snapshot_id=snapshot.id,
                                      campaign_number=campaign, empty_result=not snapshot.records)
                    if self.ingestion_guard:
                        self.ingestion_guard(self.db)
                    self.db.commit()
                    return self.response(campaign, "live_verified_304" if result["status"] == "not_modified" else "live",
                                         snapshot, run.id, verified_at=verified_at,
                                         reason="no_results" if not snapshot.records else None)
        if result.get("rejected_observation") is not None:
            retain_rejected_response(self.db, run, result["rejected_observation"], "parser")
            self.db.commit()
        self.shared.lock_ingestion()
        try:
            self.shared.assert_source_access(run)
        except SourceAccessBlocked as error:
            return self.block_source_access(campaign, run, error)
        if self.ingestion_guard:
            self.ingestion_guard(self.db)
        run.state = "consent_required" if request.fallback_policy == "ask" else "source_unavailable"
        run.reason = str(result.get("reason") or "recall_source_unavailable")[:200]
        self.shared.audit(session_id, "recall_online_failed", run.id, reason=run.reason)
        self.db.commit()
        from .query_fallback_policies import claim_policy_use, authorized_result
        use = claim_policy_use(self.db, self.shared.registry, run, 'recall_campaign', audience)
        if use is not None:
            snapshot = self.latest(campaign)
            self.shared.audit(session_id, 'policy_recall_snapshot_read', run.id, use_id=use.id,
                              snapshot_id=snapshot.id if snapshot else None)
            response = self.response(campaign, 'local_snapshot', snapshot, run.id,
                                     reason=run.reason if snapshot else 'no_matching_recall_snapshot')
            return authorized_result(self.db, self.shared.registry, run, use, response)
        return self.response(campaign, run.state, query_id=run.id, reason=run.reason)

    def block_source_access(self, campaign, run, error):
        self.shared.block_source_access(run, error)
        return self.response(campaign, run.state, query_id=run.id, reason=run.reason)

    def persist(self, run, result, records, cached, selection):
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
            from .parser_releases import ParserDeploymentError
            latest = self.latest(run.query["campaign_number"])
            if latest is None or latest.id != cached["snapshot_id"]:
                # A delayed response must not move the current observation back
                # past evidence accepted while this request was in flight.
                raise ParserDeploymentError("recall_cache_head_changed", 409)
            snapshot = self.db.get(RecallSnapshot, cached["snapshot_id"])
            if snapshot is None:
                raise ValueError("missing_recall_cache")
        else:
            campaign = run.query["campaign_number"]
            previous = self.db.scalar(select(RecallRevision).where(RecallRevision.campaign_number == campaign)
                                       .order_by(desc(RecallRevision.revision)).limit(1))
            records_hash = digest(records)
            # A valid empty observation is evidence, not a withdrawal/resolution.
            changed = bool(records) and (previous is None or previous.records_hash != records_hash)
            revision = (previous.revision + 1 if previous else 1) if changed else previous.revision if previous and records else None
            raw_hash = hashlib.sha256(result["body"].encode("utf-8")).hexdigest()
            last = self.latest(campaign)
            snapshot = last
            if (last is None or last.raw_hash != raw_hash or last.records_hash != records_hash
                    or last.parser_version != result["parser_version"] or last.parser_identity != result.get("parser_identity")):
                snapshot = RecallSnapshot(id=uid(), campaign_number=campaign, query_key=run.query_key,
                    source_id=SOURCE_ID, source_url=result["url"], raw_hash=raw_hash, body=result["body"],
                    content_type=result["content_type"], parser_version=result["parser_version"],
                    parser_identity=result.get("parser_identity"), records=records, records_hash=records_hash,
                    revision=revision, observed_at=now)
                self.db.add(snapshot)
                self.db.flush()
            if changed:
                row = RecallRevision(id=uid(), campaign_number=campaign, revision=revision,
                    snapshot_id=snapshot.id, previous_snapshot_id=previous.snapshot_id if previous else None,
                    records=records, records_hash=records_hash, observed_at=now)
                self.db.add(row)
                self.db.flush()
                change = RecallEvent(id=uid(), revision_id=row.id,
                    kind="content_changed" if previous else "first_observed",
                    changes={"before": previous.records if previous else None, "after": records}, observed_at=now)
                self.db.add(change)
                self.db.flush()
                from .recall_monitoring import record_notifications
                record_notifications(self.db, row, change)
        self.db.add(RecallVerification(snapshot_id=snapshot.id, query_id=run.id, query_key=run.query_key,
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
            raise HTTPException(403, "召回授权的来源、查询、策略或范围不匹配")
        try:
            self.shared.assert_source_access(run)
        except SourceAccessBlocked as error:
            return self.block_source_access(request.query.campaign_number, run, error)
        now = utcnow()
        if utc(consent.expires_at) <= now or utc(run.created_at) + CONSENT_TTL <= now:
            raise HTTPException(410, "召回离线授权已过期")
        from .query_fallback_policies import assert_once_policy
        assert_once_policy(self.db, self.shared.registry, run, 'recall_campaign', audience)
        claimed = self.db.execute(update(FallbackConsent).where(FallbackConsent.id == consent.id,
            FallbackConsent.session_id == session_id, FallbackConsent.used_at.is_(None),
            FallbackConsent.decision == "allow", FallbackConsent.scope == "once", FallbackConsent.expires_at > now)
            .values(used_at=now).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            raise HTTPException(409, "召回离线授权已经使用")
        snapshot = self.latest(request.query.campaign_number)
        run.state = "local_snapshot"
        self.shared.audit(session_id, "recall_local_snapshot_read", run.id, consent.id,
                          snapshot_id=snapshot.id if snapshot else None)
        self.db.commit()
        assert_once_policy(self.db, self.shared.registry, run, 'recall_campaign', audience)
        response = self.response(request.query.campaign_number, "local_snapshot", snapshot, run.id,
            consent_id=consent.id, reason=run.reason if snapshot else "no_matching_recall_snapshot")
        if audience == 'programmatic':
            self.db.commit()
        return response

    def response(self, campaign, state, snapshot=None, query_id=None, *, verified_at=None, reason=None, consent_id=None):
        from .recall_evidence import recall_reference
        if snapshot and verified_at is None:
            verified_at = self.db.scalar(select(RecallVerification.verified_at)
                .where(RecallVerification.snapshot_id == snapshot.id).order_by(desc(RecallVerification.verified_at)).limit(1))
        return {"query_id": query_id, "source_id": SOURCE_ID, "query": {"campaign_number": campaign},
            "data_state": state, "reason": reason, "verified_at": timestamp(verified_at), "consent_id": consent_id,
            "snapshot_observed_at": timestamp(snapshot.observed_at) if snapshot else None,
            "snapshot_age_seconds": max(0, int((utcnow() - utc(snapshot.observed_at)).total_seconds())) if snapshot else None,
            "revision": snapshot.revision if snapshot else None, "records": snapshot.records if snapshot else [],
            "analysis_reference": recall_reference(self.db, snapshot) if snapshot else None,
            "provenance": [recall_provenance(snapshot)] if snapshot else [], "notices": NOTICES}


def register_recall_routes(app: FastAPI) -> None:
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    def adapter():
        if getattr(app.state, "recall_adapter", None) is not None:
            return app.state.recall_adapter
        from .adapters import nhtsa
        return nhtsa

    @app.post("/v1/recalls/live-query")
    async def live(payload: RecallLiveRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        return await RecallService(db, adapter(), policy_registry=app.state.registry).execute(
            payload, request.state.session_id, audience='programmatic')

    @app.get("/v1/recalls/{campaign_number}/history")
    def history(campaign_number: str, request: Request, mode: Literal["history"] = Query(...),
                db: Session = Depends(get_db)) -> dict:
        try:
            campaign = RecallQuery(campaign_number=campaign_number).campaign_number
        except ValueError:
            raise HTTPException(422, "召回编号格式无效") from None
        service = RecallService(db, None)
        snapshot = service.latest(campaign)
        revisions = db.scalars(select(RecallRevision).where(RecallRevision.campaign_number == campaign)
            .order_by(desc(RecallRevision.revision)).limit(51)).all()
        response = service.response(campaign, "local_snapshot", snapshot,
            reason="explicit_history" if snapshot else "no_matching_recall_snapshot")
        response["revisions"] = [{"id": row.id, "revision": row.revision, "snapshot_id": row.snapshot_id,
            "previous_snapshot_id": row.previous_snapshot_id, "records": row.records,
            "observed_at": timestamp(row.observed_at), "kind": "first_observed" if row.revision == 1 else "content_changed"}
            for row in revisions[:50]]
        response["revisions_truncated"] = len(revisions) > 50
        service.shared.audit(request.state.session_id, "recall_history_read", campaign_number=campaign)
        db.commit()
        return response

    @app.get("/v1/recall-evidence/{snapshot_id}")
    def evidence(snapshot_id: str, request: Request, mode: Literal["history"] = Query(...),
                 db: Session = Depends(get_db)) -> dict:
        snapshot = db.get(RecallSnapshot, snapshot_id)
        if snapshot is None:
            raise HTTPException(404, "未找到召回证据")
        if hashlib.sha256(snapshot.body.encode("utf-8")).hexdigest() != snapshot.raw_hash:
            raise HTTPException(503, "召回原文完整性校验失败")
        verified = db.scalar(select(RecallVerification.verified_at).where(RecallVerification.snapshot_id == snapshot.id)
            .order_by(desc(RecallVerification.verified_at)).limit(1))
        QueryService(db, None).audit(request.state.session_id, "recall_evidence_history_read", snapshot_id=snapshot.id)
        db.commit()
        return {"id": snapshot.id, "campaign_number": snapshot.campaign_number, **recall_provenance(snapshot),
            "verified_at": timestamp(verified), "content_type": snapshot.content_type, "body": snapshot.body,
            "data_state": "local_snapshot"}
