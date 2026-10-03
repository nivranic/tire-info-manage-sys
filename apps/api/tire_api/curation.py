"""Explicit historical curation; online queries and ingestion never consult overlays."""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import Field, StrictInt, model_validator
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .db import FactVersion, ManualFactRevision, Snapshot, TireVariant, uid, utc, utcnow
from .domain import StrictModel
from .service import QueryService, provenance, timestamp

# Identity and identity-derived aliases are deliberately absent. Correcting them
# requires an explicit new SKU/entity-resolution workflow, never a facts patch.
FIELD_CATALOG: dict[str, dict] = {}
for key, label, unit in (
    ("utqg_treadwear", "UTQG 磨耗指数", ""), ("treadwear", "磨耗指数", ""),
    ("weight_lb", "重量", "lb"), ("weight_kg", "重量", "kg"),
    ("max_load_lb", "最大载重", "lb"), ("max_pressure_psi", "最大胎压", "psi"),
    ("overall_diameter_in", "外径", "in"), ("overall_width_in", "断面宽度", "in"),
    ("revolutions_per_mile", "每英里转数", ""), ("recommended_rim_width_in", "推荐轮辋宽度", "in"),
    ("ply_rating", "层级", ""), ("warranty_miles", "里程质保", "mile"),
    ("eu_external_noise_db", "欧盟外部滚动噪声", "dB"), ("noise_db", "外部滚动噪声", "dB"),
):
    FIELD_CATALOG[key] = {"label": label, "type": "number", "unit": unit}
for key, label, choices in (
    ("utqg_traction", "UTQG 牵引力等级", ["AA", "A", "B", "C"]),
    ("traction", "牵引力等级", ["AA", "A", "B", "C"]),
    ("utqg_temperature", "UTQG 耐热等级", ["A", "B", "C"]),
    ("temperature", "耐热等级", ["A", "B", "C"]),
    ("eu_fuel_class", "欧盟能效等级", list("ABCDEFG")),
    ("eu_wet_grip", "欧盟湿地抓地等级", list("ABCDEFG")),
    ("eu_noise_class", "欧盟噪声等级", list("ABC")),
    ("rim_width_range_in", "适配轮辋宽度范围（英寸）", []),
    ("manufacturing_origin", "制造地", []),
):
    FIELD_CATALOG[key] = {"label": label, "type": "string", "choices": choices, "unit": ""}
FIELD_CATALOG["for_sale"] = {"label": "来源标记在售", "type": "boolean", "unit": ""}
FIELD_CATALOG["tread_depth"] = {"label": "胎纹深度", "type": "measurement", "units": ["mm", "1/32 in", "in"]}


class EvidenceReference(StrictModel):
    snapshot_id: str = Field(min_length=1, max_length=64)
    locator: str = Field(min_length=3, max_length=2000)


class RevisionRequest(StrictModel):
    source_id: str = Field(min_length=1, max_length=80)
    base_fact_id: str = Field(min_length=1, max_length=64)
    expected_revision: StrictInt = Field(ge=0)
    field: str = Field(min_length=1, max_length=80)
    action: Literal["manual_override", "revoke", "clear_override"]
    value: Any = None
    operator: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=5, max_length=2000)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_action(self):
        definition = FIELD_CATALOG.get(self.field)
        if definition is None:
            raise ValueError("此字段不支持人工纠错；SKU 身份和证据元信息不可通过参数修改")
        if len({item.snapshot_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("证据引用不能重复")
        if self.action != "manual_override":
            if "value" in self.model_fields_set:
                raise ValueError("撤销或恢复来源值时不得携带新值")
            return self
        if "value" not in self.model_fields_set:
            raise ValueError("纠错需要提供新值；null 表示未知")
        value = self.value
        if value is None:
            return self
        kind = definition["type"]
        valid = False
        if kind == "number":
            valid = type(value) in {int, float} and 0 <= value <= 1_000_000 and math.isfinite(value)
        elif kind == "boolean":
            valid = type(value) is bool
        elif kind == "string":
            valid = (isinstance(value, str) and 1 <= len(value.strip()) <= 400
                     and (not definition["choices"] or value in definition["choices"]))
        elif kind == "measurement":
            valid = (isinstance(value, dict) and set(value) == {"value", "unit"}
                     and type(value["value"]) in {int, float} and 0 <= value["value"] <= 1000
                     and math.isfinite(value["value"]) and value["unit"] in definition["units"])
        if not valid:
            raise ValueError("参数类型、数值范围或来源单位无效")
        return self


def field_value(facts: dict, key: str) -> dict:
    return {"present": key in facts, "value": deepcopy(facts.get(key))}


def review_state(db: Session, variant_id: str, source_id: str) -> dict:
    variant = db.get(TireVariant, variant_id)
    if variant is None:
        raise HTTPException(404, "未找到轮胎版本")
    facts = db.scalars(select(FactVersion).where(FactVersion.variant_id == variant_id,
                      FactVersion.source_id == source_id).order_by(FactVersion.version)).all()
    if not facts:
        raise HTTPException(404, "此轮胎版本没有该来源的事实记录")
    current = facts[-1]
    records = db.scalars(select(ManualFactRevision).where(ManualFactRevision.variant_id == variant_id,
                        ManualFactRevision.source_id == source_id).order_by(ManualFactRevision.revision)).all()
    latest: dict[str, ManualFactRevision] = {}
    for row in records:
        latest[row.field] = row
    effective = deepcopy(current.facts)
    fields = {}
    for field, row in latest.items():
        status = ("cleared" if row.action == "clear_override" else "needs_review"
                  if row.base_fact_id != current.id else "revoked" if row.action == "revoke" else "manual_override")
        fields[field] = {"revision_id": row.id, "revision": row.revision, "status": status,
                         "operator": row.operator, "reason": row.reason, "after": row.after,
                         "base_fact_id": row.base_fact_id, "evidence": row.evidence}
        if status == "manual_override":
            effective[field] = deepcopy(row.after["value"])
        elif status == "revoked":
            effective.pop(field, None)
    # End times are derived from the next same-field action or source revision.
    # This closes applicability without modifying any old append-only record.
    source_ends = {fact.id: facts[index + 1].observed_at for index, fact in enumerate(facts[:-1])}
    next_field_time: dict[str, Any] = {}
    history = []
    for row in reversed(records):
        ends = [value for value in (next_field_time.get(row.field), source_ends.get(row.base_fact_id)) if value]
        history.append({"id": row.id, "revision": row.revision, "field": row.field, "action": row.action,
                        "operator": row.operator, "reason": row.reason, "before": row.before, "after": row.after,
                        "source_before": row.source_before, "base_fact_id": row.base_fact_id,
                        "evidence": row.evidence, "created_at": timestamp(row.created_at),
                        "valid_from": timestamp(row.created_at), "valid_to": timestamp(min(ends, key=utc)) if ends else None})
        next_field_time[row.field] = row.created_at
    snapshot = db.get(Snapshot, current.snapshot_id)
    from .identity_contract import contract_metadata
    return {"data_state": "local_snapshot", "mode": "local_single_user_poc",
            "variant_id": variant_id, "identity": variant.identity, "source_id": source_id,
            "identity_contract": contract_metadata(db, variant_id),
            "base_fact_id": current.id, "fact_version": current.version,
            "revision": records[-1].revision if records else 0,
            "source_facts": current.facts, "effective_facts": effective, "fields": fields,
            "history": history[:200], "history_truncated": len(history) > 200,
            "field_catalog": FIELD_CATALOG, "provenance": provenance(snapshot)}


def append_revision(db: Session, variant_id: str, payload: RevisionRequest, session_id: str) -> dict:
    shared = QueryService(db, None)
    shared.lock_ingestion()
    state = review_state(db, variant_id, payload.source_id)
    if payload.base_fact_id != state["base_fact_id"] or payload.expected_revision != state["revision"]:
        raise HTTPException(409, "来源事实或人工修订已更新，请重新载入并核对后提交")
    before = field_value(state["effective_facts"], payload.field)
    source_before = field_value(state["source_facts"], payload.field)
    previous = state["fields"].get(payload.field)
    if payload.action == "clear_override":
        if previous is None or previous["status"] == "cleared":
            raise HTTPException(409, "此字段没有需要撤回的人工处理")
        after = source_before
    elif payload.action == "revoke":
        if not before["present"]:
            raise HTTPException(409, "此字段已经撤销或当前不存在")
        after = {"present": False, "value": None}
    else:
        after = {"present": True, "value": payload.value}
        if before == after:
            raise HTTPException(409, "新值与当前核验值相同，无需重复创建修订")
    evidence = []
    for reference in payload.evidence:
        snapshot = db.get(Snapshot, reference.snapshot_id)
        if snapshot is None:
            raise HTTPException(422, "证据必须引用已采纳的原始快照，不能引用隔离记录或任意网址")
        evidence.append({**provenance(snapshot), "locator": reference.locator})
    row = ManualFactRevision(id=uid(), variant_id=variant_id, source_id=payload.source_id,
                             base_fact_id=payload.base_fact_id, revision=state["revision"] + 1,
                             field=payload.field, action=payload.action, operator_session_id=session_id,
                             operator=payload.operator, reason=payload.reason, before=before, after=after,
                             source_before=source_before, evidence=evidence, created_at=utcnow())
    db.add(row)
    shared.audit(session_id, "manual_fact_revision", variant_id=variant_id, source_id=payload.source_id,
                 revision_id=row.id, action_kind=row.action, field=row.field)
    db.commit()
    return review_state(db, variant_id, payload.source_id)


def register_curation_routes(app: FastAPI) -> None:
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get("/v1/tire-variants/{variant_id}/fact-review")
    def review(variant_id: str, request: Request, source_id: str = Query(min_length=1, max_length=80),
               mode: Literal["history"] = Query(...), db: Session = Depends(get_db)) -> dict:
        result = review_state(db, variant_id, source_id)
        QueryService(db, None).audit(request.state.session_id, "fact_review_history_read", variant_id=variant_id,
                                     source_id=source_id)
        db.commit()
        return result

    @app.post("/v1/tire-variants/{variant_id}/fact-revisions", status_code=201)
    def revise(variant_id: str, payload: RevisionRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        return append_revision(db, variant_id, payload, request.state.session_id)
