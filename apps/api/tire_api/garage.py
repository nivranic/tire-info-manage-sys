"""Persistent local-workspace garage, separate from authoritative vehicle fitments."""
from copy import deepcopy
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import Field, StrictInt, ValidationError, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .db import GarageRevision, GarageVehicle, TireVariant, uid
from .domain import StrictModel, parse_size
from .lifecycle import annotate_variants
from .service import QueryService, timestamp
from .vehicles import VehicleSnapshot, vehicle_provenance
from .vehicle_raw import (FIRST_GENERATION_ID, PDF_URL, SOURCE_ID, SUPPORTED_RAW_SHA256,
                          VehicleRawIntegrityError, VehicleUseNotAllowed,
                          checked_vehicle_consumer_capsule, require_vehicle_consumer_use)


def _binding_failed():
    raise HTTPException(503, {'code': 'vehicle_raw_integrity_failed'})


def restricted_vehicle_reference(reference):
    """Frozen positive markers survive missing rows and illegal UTF-8 downgrades."""
    return (reference.get('source_url') == PDF_URL or reference.get('raw_hash') == SUPPORTED_RAW_SHA256
            or reference.get('vehicle_id') == FIRST_GENERATION_ID)


def checked_vehicle_reference(db, reference, *, vehicle_id=None, frozen=False):
    """Check identity/binding without rereading a genuine legacy frozen body."""
    if type(reference) is not dict or type(reference.get('snapshot_id')) is not str or not reference['snapshot_id']:
        _binding_failed()
    if any(key not in reference for key in ('source_id', 'source_url', 'raw_hash', 'parser_version',
                                            'parser_identity', 'observed_at')):
        _binding_failed()
    with db.no_autoflush:
        snapshot = db.get(VehicleSnapshot, reference['snapshot_id'], populate_existing=True)
        restricted = (restricted_vehicle_reference(reference) or vehicle_id == FIRST_GENERATION_ID
            or snapshot is not None and (snapshot.body_encoding == 'binary'
                or snapshot.source_id == SOURCE_ID and snapshot.vehicle_id == FIRST_GENERATION_ID))
        try:
            capsule = checked_vehicle_consumer_capsule(db, reference['snapshot_id'],
                verification_id=reference.get('verification_id')) if restricted else None
            if restricted and capsule is None:
                _binding_failed()
            if snapshot is None:
                # Only a complete frozen member can prove a missing source was
                # legacy. A garage-only reference has no frozen vehicle id.
                if not frozen or type(vehicle_id) is not str or not vehicle_id or restricted:
                    _binding_failed()
                return None
            if capsule is None and snapshot.body_encoding != 'utf-8':
                _binding_failed()
            if vehicle_id is not None and snapshot.vehicle_id != vehicle_id:
                _binding_failed()
            expected = capsule['provenance'] if capsule else vehicle_provenance(snapshot)
            for key in ('source_id', 'source_url', 'raw_hash', 'parser_version', 'parser_identity', 'observed_at'):
                if key not in reference or reference[key] != expected[key]:
                    _binding_failed()
            for key in ('source_page', 'evidence_path'):
                if key in reference and reference[key] != expected[key]:
                    _binding_failed()
            if capsule:
                for key in ('verification_id', 'verified_at', 'fact_hash'):
                    if key in reference and reference[key] != capsule[key]:
                        _binding_failed()
            return capsule
        except VehicleRawIntegrityError:
            _binding_failed()


def require_vehicle_reference_use(capsule, purpose):
    try:
        require_vehicle_consumer_use(capsule, purpose)
    except VehicleUseNotAllowed as error:
        raise HTTPException(403, {'code': error.code}) from None


def checked_fitment_reference(db, reference, *, purpose='local_structured', copied=False, frozen=False):
    """A retained source reference remains binding after personal profile edits."""
    if reference is None:
        if copied:
            _binding_failed()
        return None
    capsule = checked_vehicle_reference(db, reference, frozen=frozen)
    snapshot = db.get(VehicleSnapshot, reference['snapshot_id'])
    payload = capsule['payload'] if capsule else snapshot.payload
    try:
        expected = capsule['provenance'] if capsule else vehicle_provenance(snapshot)
        if any(key not in reference or reference[key] != value for key, value in expected.items()):
            _binding_failed()
        fits = [item for item in payload['fitments'] if item['id'] == reference.get('fitment_id')]
        if len(fits) != 1 or fits[0]['availability'] not in {'standard', 'optional'}:
            _binding_failed()
        fitment = fits[0]
        if any(reference.get(key) != fitment.get(key, [] if key == 'constraints' else None)
               for key in ('availability', 'constraints', 'source_description')):
            _binding_failed()
        receipt_keys = {'verification_id', 'verified_at', 'fact_hash'}
        if capsule and receipt_keys & reference.keys() and not receipt_keys.issubset(reference):
            _binding_failed()
    except (KeyError, TypeError, AttributeError):
        _binding_failed()
    require_vehicle_reference_use(capsule, purpose)
    return capsule


def checked_garage_revision(db, row, *, purpose='local_structured'):
    copied = row.basis == 'copied_fitment' or row.operation == 'from_fitment'
    if row.fitment_reference is None and not copied:
        # Public writes cannot clear this reference. Detect a damaged later
        # revision even if its personal edit changed basis to user_entry.
        history = db.execute(select(GarageRevision.fitment_reference, GarageRevision.operation, GarageRevision.basis)
            .where(GarageRevision.vehicle_id == row.vehicle_id, GarageRevision.revision <= row.revision)).all()
        copied = any(reference is not None or operation == 'from_fitment' or basis == 'copied_fitment'
                     for reference, operation, basis in history)
    return checked_fitment_reference(db, row.fitment_reference, copied=copied, purpose=purpose)


class GarageAxle(StrictModel):
    size: str | None = Field(None, max_length=24)
    current_variant_id: str | None = Field(None, min_length=1, max_length=64)

    @field_validator("size")
    @classmethod
    def normalize_size(cls, value: str | None) -> str | None:
        return parse_size(value) if value else None


class GarageProfile(StrictModel):
    nickname: str = Field(min_length=1, max_length=80)
    manufacturer: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    model_year: StrictInt | None = Field(None, ge=1900, le=2100)
    generation: str | None = Field(None, max_length=100)
    trim: str | None = Field(None, max_length=120)
    wheel_option: str | None = Field(None, max_length=160)
    optional_wheels: list[str] = Field(default_factory=list, max_length=20)
    front: GarageAxle = Field(default_factory=GarageAxle)
    rear: GarageAxle = Field(default_factory=GarageAxle)

    @field_validator("optional_wheels")
    @classmethod
    def wheel_names(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 160 for value in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("可选轮毂名称须为不同的非空文本，最多 160 字符")
        return normalized


class GarageUpdate(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    profile: GarageProfile


class GarageFromFitment(StrictModel):
    snapshot_id: str = Field(min_length=1, max_length=64)
    fitment_id: str = Field(min_length=1, max_length=120)
    nickname: str = Field(min_length=1, max_length=80)


class GarageStateRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    action: Literal["archive", "restore"]


class GarageTireRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    axle: Literal["front", "rear"]
    variant_id: str | None = Field(None, min_length=1, max_length=64)


def current(db: Session, vehicle_id: str, expected_revision: int | None = None) -> GarageRevision:
    row = db.scalar(select(GarageRevision).where(GarageRevision.vehicle_id == vehicle_id)
                    .order_by(desc(GarageRevision.revision)).limit(1))
    if row is None:
        raise HTTPException(404, "未找到车库记录")
    if expected_revision is not None and row.revision != expected_revision:
        raise HTTPException(409, "车库记录已更新，请重新载入并核对后提交")
    checked_garage_revision(db, row)
    return row


def tire_identities(db: Session, profiles: list[dict]) -> dict:
    ids = {profile[axle].get("current_variant_id") for profile in profiles for axle in ("front", "rear")}
    ids.discard(None)
    if not ids:
        return {}
    rows = db.scalars(select(TireVariant).where(TireVariant.id.in_(ids))).all()
    return {row["id"]: row for row in annotate_variants(db, [{"id": row.id, **row.identity} for row in rows])}


def representation(row: GarageRevision, tires: dict) -> dict:
    return {"id": row.vehicle_id, "revision": row.revision, "archived": row.archived,
            "profile": row.profile, "basis": row.basis, "fitment_reference": row.fitment_reference,
            "updated_at": timestamp(row.created_at), "data_state": "local_snapshot",
            "current_tires": {axle: tires.get(row.profile[axle].get("current_variant_id")) for axle in ("front", "rear")}}


def validate_tires(db: Session, profile: dict, previous: dict | None = None) -> dict:
    tires = tire_identities(db, [profile])
    for axle in ("front", "rear"):
        entry = profile[axle]
        variant_id = entry["current_variant_id"]
        if variant_id is None:
            continue
        tire = tires.get(variant_id)
        if tire is None:
            raise HTTPException(422, "当前轮胎必须引用已有的精确 SKU")
        unchanged = previous is not None and previous[axle] == entry
        if tire["lifecycle"]["state"] == "revoked" and not unchanged:
            raise HTTPException(422, "不能新关联已撤销的轮胎版本；已有记录会保留撤销提示")
        if entry["size"] is None:
            entry["size"] = tire["size"]
        if entry["size"] != tire["size"]:
            raise HTTPException(422, f"{'前' if axle == 'front' else '后'}轴尺寸与所选精确版本不同，请核对车库规格（R/ZR 也分别保留）")
    return profile


def append(db: Session, vehicle_id: str, profile: dict, session_id: str, *, operation: str,
           previous: GarageRevision | None = None, archived: bool = False,
           basis: str = "user_entry", reference: dict | None = None) -> dict:
    checked_fitment_reference(db, reference, copied=basis == 'copied_fitment' or operation == 'from_fitment')
    if previous is None:
        db.add(GarageVehicle(id=vehicle_id))
        db.flush()
    row = GarageRevision(vehicle_id=vehicle_id, revision=previous.revision + 1 if previous else 1,
        operation=operation, archived=archived, profile=profile, basis=basis,
        fitment_reference=reference, actor_session_id=session_id)
    db.add(row)
    QueryService(db, None).audit(session_id, "garage_revision_created", vehicle_id=vehicle_id,
                                revision=row.revision, operation=operation)
    db.commit()
    return representation(row, tire_identities(db, [profile]))


def register_garage_routes(app: FastAPI) -> None:
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get("/v1/garage")
    def garage(archived: bool = False, offset: int = Query(0, ge=0), db: Session = Depends(get_db)) -> dict:
        latest = select(GarageRevision.vehicle_id, func.max(GarageRevision.revision).label("revision")).group_by(GarageRevision.vehicle_id).subquery()
        statement = (select(GarageRevision).join(latest,
            (GarageRevision.vehicle_id == latest.c.vehicle_id) & (GarageRevision.revision == latest.c.revision))
            .where(GarageRevision.archived == archived))
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.scalars(statement.order_by(desc(GarageRevision.created_at), desc(GarageRevision.id)).offset(offset).limit(100)).all()
        for row in rows:
            checked_garage_revision(db, row)
        tires = tire_identities(db, [row.profile for row in rows])
        return {"data_state": "local_snapshot", "scope": "local_workspace", "items": [representation(row, tires) for row in rows],
                "limit": 100, "offset": offset, "total": total}

    @app.post("/v1/garage", status_code=201)
    def create(profile: GarageProfile, request: Request, db: Session = Depends(get_db)) -> dict:
        QueryService(db, None).lock_ingestion()
        return append(db, uid(), validate_tires(db, profile.model_dump()), request.state.session_id, operation="create")

    @app.post("/v1/garage/from-fitment", status_code=201)
    def from_fitment(payload: GarageFromFitment, request: Request, db: Session = Depends(get_db)) -> dict:
        QueryService(db, None).lock_ingestion()
        snapshot = db.get(VehicleSnapshot, payload.snapshot_id)
        if snapshot is None:
            raise HTTPException(422, "请选择已采纳车型快照中的标配或选配轮毂")
        try:
            capsule = checked_vehicle_consumer_capsule(db, snapshot.id)
        except VehicleRawIntegrityError:
            _binding_failed()
        require_vehicle_reference_use(capsule, 'local_structured')
        source_payload = capsule['payload'] if capsule else snapshot.payload
        fitment = next((row for row in source_payload["fitments"] if row["id"] == payload.fitment_id), None)
        if fitment is None or fitment["availability"] not in {"standard", "optional"}:
            raise HTTPException(422, "请选择已采纳车型快照中的标配或选配轮毂")
        vehicle = source_payload["vehicle"]
        trim = next((row for row in source_payload["trims"] if row["id"] == fitment["trim_id"]), {})
        year = trim.get("model_year") if trim.get("model_year") is not None else vehicle.get("model_year")
        try:
            profile = GarageProfile(nickname=payload.nickname, manufacturer=vehicle["manufacturer"]["name"],
                model=vehicle["model"], model_year=year, generation=vehicle["generation"],
                trim=fitment["trim_name"], wheel_option=fitment["wheel_option_name"],
                optional_wheels=list(dict.fromkeys(row["wheel_option_name"] for row in source_payload["fitments"]
                    if row["trim_id"] == fitment["trim_id"] and row["availability"] == "optional")),
                front=GarageAxle(size=fitment["front"]["size"]), rear=GarageAxle(size=fitment["rear"]["size"]))
        except (ValidationError, KeyError, TypeError):
            raise HTTPException(422, "此历史配置的车辆信息未通过车库校验，请核对来源后重新保存") from None
        reference = {**(capsule['provenance'] if capsule else vehicle_provenance(snapshot)), "fitment_id": fitment["id"],
                "availability": fitment["availability"], "constraints": fitment.get("constraints", []),
                "source_description": fitment["source_description"]}
        if capsule:
            reference.update({key: capsule[key] for key in ('verification_id', 'verified_at', 'fact_hash')})
        return append(db, uid(), profile.model_dump(), request.state.session_id, operation="from_fitment",
                      basis="copied_fitment", reference=reference)

    @app.get("/v1/garage/{vehicle_id}")
    def detail(vehicle_id: str, mode: Literal["history"] = Query(...), db: Session = Depends(get_db)) -> dict:
        row = current(db, vehicle_id)
        history = db.scalars(select(GarageRevision).where(GarageRevision.vehicle_id == vehicle_id)
                            .order_by(desc(GarageRevision.revision)).limit(51)).all()
        for item in history[:50]:
            checked_garage_revision(db, item)
        return {**representation(row, tire_identities(db, [row.profile])), "history_truncated": len(history) > 50,
                "history": [{"revision": item.revision, "operation": item.operation, "archived": item.archived,
                             "profile": item.profile, "basis": item.basis, "created_at": timestamp(item.created_at)} for item in history[:50]]}

    @app.put("/v1/garage/{vehicle_id}")
    def update(vehicle_id: str, payload: GarageUpdate, request: Request, db: Session = Depends(get_db)) -> dict:
        QueryService(db, None).lock_ingestion()
        row = current(db, vehicle_id, payload.expected_revision)
        if row.archived:
            raise HTTPException(409, "请先恢复已归档的车库记录")
        profile = validate_tires(db, payload.profile.model_dump(), row.profile)
        if profile == row.profile:
            return representation(row, tire_identities(db, [row.profile]))
        return append(db, vehicle_id, profile, request.state.session_id, operation="update", previous=row,
                      reference=row.fitment_reference)

    @app.post("/v1/garage/{vehicle_id}/tires")
    def set_tire(vehicle_id: str, payload: GarageTireRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        QueryService(db, None).lock_ingestion()
        row = current(db, vehicle_id, payload.expected_revision)
        if row.archived:
            raise HTTPException(409, "请先恢复已归档的车库记录")
        profile = deepcopy(row.profile)
        if profile[payload.axle]["current_variant_id"] == payload.variant_id:
            return representation(row, tire_identities(db, [row.profile]))
        profile[payload.axle]["current_variant_id"] = payload.variant_id
        profile = validate_tires(db, profile, row.profile)
        return append(db, vehicle_id, profile, request.state.session_id, operation="set_tire", previous=row,
                      basis=row.basis, reference=row.fitment_reference)

    @app.post("/v1/garage/{vehicle_id}/state")
    def state(vehicle_id: str, payload: GarageStateRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        QueryService(db, None).lock_ingestion()
        row = current(db, vehicle_id, payload.expected_revision)
        archived = payload.action == "archive"
        if row.archived == archived:
            raise HTTPException(409, "记录已经处于该状态")
        return append(db, vehicle_id, row.profile, request.state.session_id, operation=payload.action, previous=row,
                      archived=archived, basis=row.basis, reference=row.fitment_reference)
