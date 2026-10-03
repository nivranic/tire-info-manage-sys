"""Vehicle/trim/axle evidence slice, sharing the same one-use fallback consent gate."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import Field, StrictBool, field_validator, model_validator
from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, desc, event, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from .adapters import xiaomi
from .captures import before_parse_recorder, validated_observation
from .source_settings import SourceAccessBlocked, source_setting
from .db import Base, FallbackConsent, QueryRun, uid, utc, utcnow
from .domain import StrictModel, digest, parse_size
from .service import QueryService, timestamp
from .quality import QUALITY_REASON, SourceQualityQuarantined, metrics
from .vehicle_quality import assess_vehicle_quality
from .parser_provenance import check_result_identity, execution_outcome, verified_observation_recorder


class AxleSpecification(StrictModel):
    size: str
    load_index: str | None = None
    speed_rating: str | None = None
    oe_mark: str | None = None
    manufacturer_product_code: str | None = None
    matched_tire_variant_id: str | None = None

    @field_validator("size")
    @classmethod
    def valid_size(cls, value: str) -> str:
        return parse_size(value)


class WheelFitmentSpecification(StrictModel):
    id: str
    trim_id: str
    trim_name: str
    wheel_option_name: str
    wheel_diameter_inches: int = Field(ge=10, le=30)
    availability: Literal["standard", "optional", "unavailable"]
    front: AxleSpecification
    rear: AxleSpecification
    staggered: StrictBool
    source_tire_description: str | None = None
    constraints: list[str] = Field(default_factory=list)
    source_description: str
    evidence_locator: str

    @model_validator(mode="after")
    def correct_axles(self):
        if self.staggered != (self.front.size != self.rear.size):
            raise ValueError("前后轴是否异宽必须与明确规格一致")
        if any(not axle.size.endswith(f"R{self.wheel_diameter_inches}") for axle in (self.front, self.rear)):
            raise ValueError("轮毂直径与轮胎轴位规格不符")
        return self


class VehicleLiveRequest(StrictModel):
    fallback_policy: Literal["ask", "never"] = "ask"
    consent_id: str | None = Field(default=None, min_length=1, max_length=64)


class VehicleManufacturer(Base):
    __tablename__ = "vehicle_manufacturers"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))


class VehicleModel(Base):
    __tablename__ = "vehicle_models"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    manufacturer_id: Mapped[str] = mapped_column(ForeignKey("vehicle_manufacturers.id"))
    name: Mapped[str] = mapped_column(String(160))
    generation: Mapped[str] = mapped_column(String(80))
    model_year: Mapped[int | None] = mapped_column(nullable=True)
    region: Mapped[str] = mapped_column(String(40))
    source_vehicle_id: Mapped[str] = mapped_column(String(80))


class VehicleTrim(Base):
    __tablename__ = "vehicle_trims"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicle_models.id"), index=True)
    source_trim_id: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    model_year: Mapped[int | None] = mapped_column(nullable=True)


class VehicleSnapshot(Base):
    __tablename__ = "vehicle_snapshots"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicle_models.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str] = mapped_column(Text)
    raw_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120))
    parser_version: Mapped[str] = mapped_column(String(100))
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    fact_hash: Mapped[str] = mapped_column(String(64))
    fact_version: Mapped[int]


class VehicleQuarantine(Base):
    __tablename__ = "vehicle_quarantines"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    query_id: Mapped[str] = mapped_column(ForeignKey("query_runs.id"), unique=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicle_models.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    previous_snapshot_id: Mapped[str] = mapped_column(ForeignKey("vehicle_snapshots.id"))
    source_url: Mapped[str] = mapped_column(Text)
    raw_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120))
    parser_version: Mapped[str] = mapped_column(String(100))
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    quality: Mapped[dict[str, Any]] = mapped_column(JSON)


class VehicleVerification(Base):
    __tablename__ = "vehicle_verifications"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("vehicle_snapshots.id"), index=True)
    query_id: Mapped[str] = mapped_column(ForeignKey("query_runs.id"))
    vehicle_id: Mapped[str] = mapped_column(String(80), index=True)
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WheelFitment(Base):
    __tablename__ = "vehicle_wheel_fitments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    option_id: Mapped[str] = mapped_column(String(64), index=True)
    trim_id: Mapped[str] = mapped_column(ForeignKey("vehicle_trims.id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("vehicle_snapshots.id"))
    version: Mapped[int]
    specification: Mapped[dict[str, Any]] = mapped_column(JSON)


VEHICLE_IMMUTABLE = (VehicleManufacturer, VehicleModel, VehicleTrim, VehicleSnapshot, VehicleVerification, WheelFitment, VehicleQuarantine)


@event.listens_for(Session, "before_flush")
def protect_vehicle_evidence(session: Session, _context: Any, _instances: Any) -> None:
    for row in session.dirty | session.deleted:
        if isinstance(row, VEHICLE_IMMUTABLE) and (row in session.deleted or session.is_modified(row)):
            raise ValueError("车型证据和适配版本只能追加，不能修改或删除")


def fitment_fact_hash(payload: dict) -> str:
    """Source table versions, JSON locations and unrelated page changes are metadata."""
    vehicle = {key: value for key, value in payload["vehicle"].items() if key != "source_version"}
    fits = [{key: value for key, value in row.items() if key not in {"evidence_locator", "source_description"}}
            for row in payload["fitments"]]
    trims = [{**row, "wheel_option_ids": sorted(row["wheel_option_ids"])} for row in payload["trims"]]
    return digest({"vehicle": vehicle, "trims": sorted(trims, key=lambda row: row["id"]),
                   "fitments": sorted(fits, key=lambda row: row["id"]),
                   "footnotes": sorted(payload.get("footnotes", []))})


def validate_vehicle_structure(payload: dict, fits: list[dict]) -> None:
    def text(value, maximum=160):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
            raise ValueError("车型字段缺失或无效")
        value.encode("utf-8", errors="strict")

    vehicle = payload["vehicle"]
    for key in ("id", "model", "generation", "region", "source_vehicle_id"):
        text(vehicle[key], 80 if key != "model" else 160)
    for key in ("id", "name"):
        text(vehicle["manufacturer"][key], 80 if key == "id" else 160)
    trims = payload["trims"]
    if not isinstance(trims, list) or not 1 <= len(trims) <= 12 or len({row["id"] for row in trims}) != len(trims):
        raise ValueError("配置版本集合无效")
    for row in [vehicle, *trims]:
        year = row.get("model_year")
        if year is not None and (type(year) is not int or not 1900 <= year <= 2100):
            raise ValueError("车型年款无效")
    for trim in trims:
        for key in ("id", "name", "source_trim_id"):
            text(trim[key], 160 if key == "name" else 120 if key == "id" else 80)
        ids = trim["wheel_option_ids"]
        expected = [row["id"] for row in fits if row["trim_id"] == trim["id"]]
        if (not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or set(ids) != set(expected)
                or any(row["trim_name"] != trim["name"] for row in fits if row["trim_id"] == trim["id"])):
            raise ValueError("配置与轮毂项映射不一致")
    for row in fits:
        for key in ("id", "trim_id", "trim_name", "wheel_option_name", "source_description", "evidence_locator"):
            text(row[key], 64 if key == "id" else 120 if key == "trim_id" else 8192)


def vehicle_provenance(snapshot: VehicleSnapshot) -> dict:
    return {"snapshot_id": snapshot.id, "source_id": snapshot.source_id, "source_url": snapshot.source_url,
            "source_page": xiaomi.SOURCE_PAGE, "parser_version": snapshot.parser_version,
            "parser_identity": snapshot.parser_identity,
            "observed_at": timestamp(snapshot.observed_at), "raw_hash": snapshot.raw_hash,
            "evidence_path": f"/v1/vehicle-evidence/{snapshot.id}"}


class VehicleService:
    def __init__(self, db: Session, adapter: Any, *, policy_registry=None):
        self.db, self.adapter = db, adapter
        self.shared = QueryService(db, policy_registry)

    def require_vehicle(self, vehicle_id: str) -> None:
        if vehicle_id not in {row["id"] for row in self.adapter.candidates()}:
            raise HTTPException(404, "未知车型候选")

    def latest(self, vehicle_id: str) -> VehicleSnapshot | None:
        return self.db.scalar(select(VehicleSnapshot)
                              .join(VehicleVerification, VehicleVerification.snapshot_id == VehicleSnapshot.id)
                              .where(VehicleVerification.vehicle_id == vehicle_id)
                              .order_by(desc(VehicleVerification.verified_at)).limit(1))

    async def execute(self, vehicle_id: str, request: VehicleLiveRequest, session_id: str, *, audience='internal') -> dict:
        from .telemetry import observe
        with observe('source.query', component='crawler', source='xiaomi-su7') as operation:
            result = await self._execute(vehicle_id, request, session_id, audience=audience)
            operation.finish(result['data_state'])
            return result

    async def _execute(self, vehicle_id: str, request: VehicleLiveRequest, session_id: str, *, audience='internal') -> dict:
        self.require_vehicle(vehicle_id)
        query = {"vehicle_id": vehicle_id}
        key = digest(query)
        if request.consent_id:
            return self.consume_consent(vehicle_id, request, session_id, key, audience=audience)
        run = QueryRun(id=uid(), session_id=session_id, source_id=xiaomi.SOURCE_ID, query=query,
                       query_key=key, fallback_policy=request.fallback_policy)
        self.db.add(run)
        self.shared.audit(session_id, "vehicle_online_started", run.id, vehicle_id=vehicle_id)
        self.db.commit()
        try:
            self.shared.pin_source_access(run)
        except SourceAccessBlocked as error:
            return self.block_source_access(vehicle_id, run, error)
        from .parser_releases import ParserDeploymentError, pin_selection, record_execution
        selection = None
        try:
            kwargs = {}
            recorder = before_parse_recorder(self.db, run)
            if (getattr(self.adapter, 'supports_parser_deployments', False) is True
                    and any(row['id'] == vehicle_id and row['status'] == 'ready' for row in self.adapter.candidates())):
                selection = pin_selection(self.db, run.id, run.source_id)
                kwargs['parser_selection'] = selection
                recorder = verified_observation_recorder(recorder, selection)
            result = await self.adapter.fetch(vehicle_id, on_observation=recorder, **kwargs)
        except ParserDeploymentError as error:
            self.db.rollback()
            result = {"status": "unavailable", "reason": error.code}
        except Exception:
            result = {"status": "unavailable", "reason": "vehicle_source_fetch_failed"}
        if selection is not None:
            try:
                record_execution(self.db, run.id, execution_outcome(result))
            except ParserDeploymentError as error:
                if not error.execution_recorded:
                    self.db.rollback()
                result = {"status": "unavailable", "reason": error.code}
            self.db.commit()
        if result.get("status") == "ok":
            try:
                payload = result["payload"]
                if (validated_observation(result) is None or "\x00" in result["body"] or result.get("url") != xiaomi.API_URL
                        or result.get("content_type") != "application/json"
                        or not result.get("parser_version") or payload["vehicle"]["id"] != vehicle_id):
                    raise ValueError("来源证据缺失或身份不符")
                if not payload.get("fitments") or len(payload["fitments"]) > 100:
                    raise ValueError("适配列表无效")
                fits = [WheelFitmentSpecification.model_validate(row).model_dump() for row in payload["fitments"]]
                if len({row["id"] for row in fits}) != len(fits):
                    raise ValueError("重复配置项")
                trim_ids = {row["id"] for row in payload["trims"]}
                if any(row["trim_id"] not in trim_ids for row in fits):
                    raise ValueError("适配指向未知版本")
                validate_vehicle_structure(payload, fits)
                payload = {**payload, "fitments": fits}
            except (ValueError, KeyError, TypeError):
                from .captures import retain_rejected_response
                retain_rejected_response(self.db, run, result, "schema")
                result = {"status": "unavailable", "reason": "vehicle_source_schema_changed"}
            else:
                try:
                    snapshot, verified_at = self.persist(run, result, payload, parser_selection=selection)
                except SourceAccessBlocked as error:
                    return self.block_source_access(vehicle_id, run, error)
                except ParserDeploymentError as error:
                    result = {"status": "unavailable", "reason": error.code}
                except SourceQualityQuarantined:
                    result = {"status": "unavailable", "reason": QUALITY_REASON}
                else:
                    run.state = "live"
                    self.shared.audit(session_id, "vehicle_online_succeeded", run.id,
                                      vehicle_id=vehicle_id, snapshot_id=snapshot.id)
                    self.db.commit()
                    return self.response(vehicle_id, "live", snapshot, run.id, verified_at=verified_at)
        if result.get("rejected_observation") is not None:
            from .captures import retain_rejected_response
            retain_rejected_response(self.db, run, result["rejected_observation"], "parser")
        self.shared.lock_ingestion()
        try:
            self.shared.assert_source_access(run)
        except SourceAccessBlocked as error:
            return self.block_source_access(vehicle_id, run, error)
        run.state = "consent_required" if request.fallback_policy == "ask" else "source_unavailable"
        run.reason = str(result.get("reason") or "vehicle_source_unavailable")[:200]
        self.shared.audit(session_id, "vehicle_online_failed", run.id, vehicle_id=vehicle_id, reason=run.reason)
        self.db.commit()
        from .query_fallback_policies import ELIGIBLE_FAILURES, claim_policy_use, authorized_result
        failure_reason = result.get('fallback_failure_reason')
        if failure_reason not in ELIGIBLE_FAILURES:
            failure_reason = None
        use = claim_policy_use(self.db, self.shared.registry, run, 'vehicle_fitments', audience,
                               failure_reason=failure_reason)
        if use is not None:
            snapshot = self.latest(vehicle_id)
            self.shared.audit(session_id, 'policy_vehicle_snapshot_read', run.id, use_id=use.id,
                              snapshot_id=snapshot.id if snapshot else None)
            response = self.response(vehicle_id, 'local_snapshot', snapshot, run.id,
                                     reason=run.reason if snapshot else 'no_matching_vehicle_snapshot')
            return authorized_result(self.db, self.shared.registry, run, use, response)
        response = self.response(vehicle_id, run.state, query_id=run.id, reason=run.reason)
        if failure_reason is not None:
            response['fallback_failure'] = {'scope': 'source_response', 'reason': failure_reason, 'query_id': run.id}
        return response

    def block_source_access(self, vehicle_id, run, error):
        self.shared.block_source_access(run, error)
        return self.response(vehicle_id, run.state, query_id=run.id, reason=run.reason)

    def persist(self, run: QueryRun, result: dict, payload: dict, *,
                parser_selection: dict | None = None) -> tuple[VehicleSnapshot, datetime]:
        self.shared.lock_ingestion()
        self.shared.assert_source_access(run)
        if parser_selection is not None:
            from .parser_releases import assert_selection_current
            assert_selection_current(self.db, parser_selection)
            check_result_identity(parser_selection, result)
        verified_at = utcnow()
        vehicle = payload["vehicle"]
        previous = self.latest(vehicle["id"])
        quality = assess_vehicle_quality(previous.payload if previous else None, payload)
        raw_hash = hashlib.sha256(result["body"].encode("utf-8")).hexdigest()
        applied_review = None
        if quality["reason_codes"] and previous is not None:
            from .quarantine_review import consume_approval
            applied_review = consume_approval(self.db, run, 'vehicle', previous, result, payload, quality)
        if quality["reason_codes"] and not applied_review:
            assert previous is not None
            quarantine = VehicleQuarantine(id=uid(), query_id=run.id, vehicle_id=vehicle["id"], source_id=run.source_id,
                previous_snapshot_id=previous.id, source_url=result["url"], raw_hash=raw_hash, body=result["body"],
                content_type=result["content_type"], parser_version=result["parser_version"], observed_at=verified_at,
                parser_identity=result.get('parser_identity'),
                payload=payload, quality=quality)
            self.db.add(quarantine)
            self.shared.audit(run.session_id, "vehicle_quality_quarantined", run.id, quarantine_id=quarantine.id,
                              vehicle_id=vehicle["id"], reason_codes=quality["reason_codes"], metrics=metrics(quality))
            raise SourceQualityQuarantined()
        manufacturer = vehicle["manufacturer"]
        if self.db.get(VehicleManufacturer, manufacturer["id"]) is None:
            self.db.add(VehicleManufacturer(id=manufacturer["id"], name=manufacturer["name"]))
            self.db.flush()
        if self.db.get(VehicleModel, vehicle["id"]) is None:
            self.db.add(VehicleModel(id=vehicle["id"], manufacturer_id=manufacturer["id"],
                                    name=vehicle["model"], generation=vehicle["generation"],
                                    model_year=vehicle.get("model_year"), region=vehicle["region"],
                                    source_vehicle_id=vehicle["source_vehicle_id"]))
            self.db.flush()
        for trim in payload["trims"]:
            if self.db.get(VehicleTrim, trim["id"]) is None:
                self.db.add(VehicleTrim(id=trim["id"], vehicle_id=vehicle["id"], name=trim["name"],
                                        source_trim_id=trim["source_trim_id"], model_year=trim.get("model_year")))
        self.db.flush()
        fact_hash = fitment_fact_hash(payload)
        version = previous.fact_version if previous else 0
        changed = previous is None or previous.fact_hash != fact_hash
        if changed:
            version += 1
        snapshot = previous
        if (applied_review or previous is None or previous.raw_hash != raw_hash
                or previous.parser_version != result["parser_version"]
                or previous.parser_identity != result.get('parser_identity')):
            snapshot = VehicleSnapshot(id=uid(), vehicle_id=vehicle["id"], source_id=xiaomi.SOURCE_ID,
                                       source_url=result["url"], body=result["body"], raw_hash=raw_hash,
                                       content_type=result["content_type"], parser_version=result["parser_version"],
                                       parser_identity=result.get('parser_identity'),
                                       payload=payload, fact_hash=fact_hash, fact_version=version, observed_at=verified_at)
            self.db.add(snapshot)
            self.db.flush()
            if changed:
                self.db.add_all([WheelFitment(option_id=row["id"], trim_id=row["trim_id"],
                                              snapshot_id=snapshot.id, version=version, specification=row)
                                 for row in payload["fitments"]])
        assert snapshot is not None
        self.db.add(VehicleVerification(snapshot_id=snapshot.id, query_id=run.id,
                                        vehicle_id=vehicle["id"], verified_at=verified_at,
                                        parser_identity=result.get('parser_identity')))
        return snapshot, verified_at

    def consume_consent(self, vehicle_id: str, request: VehicleLiveRequest, session_id: str, query_key: str, *, audience='internal') -> dict:
        self.shared.lock_ingestion()
        consent = self.db.get(FallbackConsent, request.consent_id)
        if not consent or consent.session_id != session_id:
            raise HTTPException(403, "离线授权不属于当前会话")
        run = self.db.get(QueryRun, consent.query_id)
        if (not run or run.source_id != xiaomi.SOURCE_ID or run.query_key != query_key
                or run.query != {"vehicle_id": vehicle_id} or request.fallback_policy != "ask"):
            raise HTTPException(403, "离线授权的车型、来源或查询类型不匹配")
        try:
            self.shared.assert_source_access(run)
        except SourceAccessBlocked as error:
            return self.block_source_access(vehicle_id, run, error)
        if consent.decision != "allow":
            raise HTTPException(403, "已拒绝使用车型历史快照")
        now = utcnow()
        if utc(consent.expires_at) <= now:
            raise HTTPException(410, "车型离线授权已过期")
        from .query_fallback_policies import assert_once_policy
        assert_once_policy(self.db, self.shared.registry, run, 'vehicle_fitments', audience)
        claimed = self.db.execute(update(FallbackConsent).where(
            FallbackConsent.id == consent.id, FallbackConsent.session_id == session_id,
            FallbackConsent.decision == "allow", FallbackConsent.scope == "once",
            FallbackConsent.used_at.is_(None), FallbackConsent.expires_at > now,
        ).values(used_at=now).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            raise HTTPException(409, "车型离线授权已经使用")
        snapshot = self.latest(vehicle_id)
        run.state = "local_snapshot"
        self.shared.audit(session_id, "vehicle_local_snapshot_read", run.id, consent.id,
                          vehicle_id=vehicle_id, snapshot_id=snapshot.id if snapshot else None)
        self.db.commit()
        assert_once_policy(self.db, self.shared.registry, run, 'vehicle_fitments', audience)
        response = self.response(vehicle_id, "local_snapshot", snapshot, run.id,
                                 reason=run.reason if snapshot else "no_matching_vehicle_snapshot", consent_id=consent.id)
        if audience == 'programmatic':
            self.db.commit()
        return response

    def response(self, vehicle_id: str, state: str, snapshot: VehicleSnapshot | None = None,
                 query_id: str | None = None, *, reason: str | None = None,
                 consent_id: str | None = None, verified_at: datetime | None = None) -> dict:
        if snapshot and verified_at is None:
            verified_at = self.db.scalar(select(VehicleVerification.verified_at)
                                         .where(VehicleVerification.snapshot_id == snapshot.id)
                                         .order_by(desc(VehicleVerification.verified_at)).limit(1))
        return {"query_id": query_id, "vehicle_id": vehicle_id, "source_id": xiaomi.SOURCE_ID,
                "data_state": state, "reason": reason, "consent_id": consent_id,
                "verified_at": timestamp(verified_at),
                "snapshot_observed_at": timestamp(snapshot.observed_at) if snapshot else None,
                "snapshot_age_seconds": max(0, int((utcnow() - utc(snapshot.observed_at)).total_seconds())) if snapshot else None,
                "fact_version": snapshot.fact_version if snapshot else None,
                "vehicle": snapshot.payload["vehicle"] if snapshot else None,
                "trims": snapshot.payload["trims"] if snapshot else [],
                "fitments": snapshot.payload["fitments"] if snapshot else [],
                "coverage": snapshot.payload.get("coverage") if snapshot else None,
                "documents": snapshot.payload.get("documents", []) if snapshot else [],
                "footnotes": snapshot.payload.get("footnotes", []) if snapshot else [],
                "provenance": [vehicle_provenance(snapshot)] if snapshot else []}


def register_vehicle_routes(app: FastAPI, adapter: Any = None) -> None:
    """Call while constructing the app, before Database.initialize / lifespan starts."""
    if getattr(app.state, "vehicle_routes_registered", False):
        if adapter is not None:
            app.state.vehicle_adapter = adapter
        return
    app.state.vehicle_routes_registered = True
    app.state.vehicle_adapter = adapter or xiaomi

    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get("/v1/vehicles")
    def vehicles(db: Session = Depends(get_db)) -> dict:
        setting = source_setting(db, xiaomi.SOURCE_ID, registry=app.state.registry)
        rows = [{**row, 'source_setting': setting,
                 'status': setting['effective_status'] if row['status'] == 'ready' else row['status']}
                for row in app.state.vehicle_adapter.candidates()]
        return {"data_state": "source_catalog", "vehicles": rows}

    @app.post("/v1/vehicles/{vehicle_id}/live-fitments")
    async def live_fitments(vehicle_id: str, payload: VehicleLiveRequest, request: Request,
                            db: Session = Depends(get_db)) -> dict:
        return await VehicleService(db, app.state.vehicle_adapter, policy_registry=app.state.registry).execute(
            vehicle_id, payload, request.state.session_id, audience='programmatic')

    @app.get("/v1/vehicles/{vehicle_id}/fitments")
    def fitment_history(vehicle_id: str, request: Request, mode: Literal["history"] = Query(...),
                        db: Session = Depends(get_db)) -> dict:
        service = VehicleService(db, app.state.vehicle_adapter)
        service.require_vehicle(vehicle_id)
        snapshot = service.latest(vehicle_id)
        service.shared.audit(request.state.session_id, "vehicle_history_read", vehicle_id=vehicle_id)
        db.commit()
        return service.response(vehicle_id, "local_snapshot", snapshot,
                                reason="explicit_history" if snapshot else "no_matching_vehicle_snapshot")

    @app.get("/v1/vehicle-evidence/{snapshot_id}")
    def vehicle_evidence(snapshot_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
        snapshot = db.get(VehicleSnapshot, snapshot_id)
        if not snapshot:
            raise HTTPException(404, "未找到车型证据")
        verified_at = db.scalar(select(VehicleVerification.verified_at)
                                .where(VehicleVerification.snapshot_id == snapshot_id)
                                .order_by(desc(VehicleVerification.verified_at)).limit(1))
        QueryService(db, None).audit(request.state.session_id, "vehicle_evidence_history_read", snapshot_id=snapshot_id)
        db.commit()
        from .quarantine_review import snapshot_review
        return {"id": snapshot.id, "vehicle_id": snapshot.vehicle_id, **vehicle_provenance(snapshot),
                "quality_review": snapshot_review(db, snapshot.id, 'vehicle'),
                "verified_at": timestamp(verified_at), "content_type": snapshot.content_type,
                "body": snapshot.body, "data_state": "local_snapshot", "documents": snapshot.payload.get("documents", [])}
