"""Entity tombstones are explicit local management decisions, never official facts."""
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import Field, StrictInt, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .auth import make_admin_guard
from .curation import EvidenceReference
from .db import FactVersion, Snapshot, TireVariant, VariantLifecycleEvent, uid
from .domain import StrictModel
from .service import QueryService, provenance, timestamp


class LifecycleRequest(StrictModel):
    action: Literal["revoke", "restore"]
    expected_revision: StrictInt = Field(ge=0)
    operator: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=5, max_length=2000)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=5)

    @field_validator("operator", "reason", mode="before")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value or any(ord(character) < 32 and character not in "\n\t" for character in value):
            raise ValueError("署名和原因不得为空或包含控制字符")
        return value


def summary(event: VariantLifecycleEvent | None) -> dict:
    return {"state": event.after_state if event else "active", "revision": event.revision if event else 0,
            "event_id": event.id if event else None, "operator": event.operator if event else None,
            "reason": event.reason if event else None, "changed_at": timestamp(event.created_at) if event else None}


def annotate_variants(db: Session, variants: list[dict]) -> list[dict]:
    """Batch status read only after live validation, explicit history or consent."""
    ids = [row["id"] for row in variants]
    if not ids:
        return []
    latest = (select(VariantLifecycleEvent.variant_id, func.max(VariantLifecycleEvent.revision).label("revision"))
              .where(VariantLifecycleEvent.variant_id.in_(ids)).group_by(VariantLifecycleEvent.variant_id).subquery())
    events = db.scalars(select(VariantLifecycleEvent).join(latest,
        (VariantLifecycleEvent.variant_id == latest.c.variant_id) &
        (VariantLifecycleEvent.revision == latest.c.revision))).all()
    states = {row.variant_id: summary(row) for row in events}
    from .identity_resolution import annotate_identities
    return annotate_identities(db, [{**row, "lifecycle": states.get(row["id"], summary(None))} for row in variants])


def lifecycle_review(db: Session, variant_id: str) -> dict:
    variant = db.get(TireVariant, variant_id)
    if variant is None:
        raise HTTPException(404, "未找到轮胎版本")
    events = db.scalars(select(VariantLifecycleEvent).where(VariantLifecycleEvent.variant_id == variant_id)
                       .order_by(desc(VariantLifecycleEvent.revision)).limit(201)).all()
    fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == variant_id)
                     .order_by(desc(FactVersion.observed_at), desc(FactVersion.id)).limit(1))
    snapshot = db.get(Snapshot, fact.snapshot_id) if fact else None
    from .identity_contract import contract_metadata
    return {"data_state": "local_snapshot", "variant_id": variant_id, "identity": variant.identity,
            "identity_contract": contract_metadata(db, variant_id),
            "lifecycle": summary(events[0] if events else None),
            "provenance": provenance(snapshot) if snapshot else None,
            "history": [{"id": row.id, "revision": row.revision, "action": row.action,
                         "before_state": row.before_state, "after_state": row.after_state,
                         "operator": row.operator, "reason": row.reason, "evidence": row.evidence,
                         "created_at": timestamp(row.created_at)} for row in events[:200]],
            "history_truncated": len(events) > 200}


def append_lifecycle_event(db: Session, variant_id: str, payload: LifecycleRequest, session_id: str) -> dict:
    shared = QueryService(db, None)
    shared.lock_ingestion()
    review = lifecycle_review(db, variant_id)
    before = review["lifecycle"]
    if before["revision"] != payload.expected_revision:
        raise HTTPException(409, "版本状态已被更新，请重新载入并核对后提交")
    after = "revoked" if payload.action == "revoke" else "active"
    if after == before["state"]:
        raise HTTPException(409, "版本已经处于该状态，无需重复处理")
    if len({reference.snapshot_id for reference in payload.evidence}) != len(payload.evidence):
        raise HTTPException(422, "证据引用不能重复")
    evidence = []
    for reference in payload.evidence:
        snapshot = db.get(Snapshot, reference.snapshot_id)
        # A tombstone must cite accepted evidence of this exact entity, not another
        # product of the same name/size, or an unparsed/unaccepted response.
        if snapshot is None or not any(row.get("id") == variant_id for row in snapshot.parsed_variants):
            raise HTTPException(422, "证据必须是包含此精确版本的已采纳快照")
        if len(reference.locator.strip()) < 3:
            raise HTTPException(422, "请填写可核对的证据位置")
        evidence.append({**provenance(snapshot), "locator": reference.locator.strip()})
    row = VariantLifecycleEvent(id=uid(), variant_id=variant_id, revision=before["revision"] + 1,
        action=payload.action, before_state=before["state"], after_state=after,
        operator_session_id=session_id, operator=payload.operator, reason=payload.reason, evidence=evidence)
    db.add(row)
    shared.audit(session_id, "variant_lifecycle_changed", variant_id=variant_id, event_id=row.id,
                 action_kind=row.action, before=before["state"], after=after)
    db.commit()
    return lifecycle_review(db, variant_id)


def register_lifecycle_routes(app: FastAPI) -> None:
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    admin_guard = make_admin_guard(get_db)

    @app.get("/v1/tire-variants/{variant_id}/lifecycle")
    def review(variant_id: str, request: Request, mode: Literal["history"] = Query(...),
               db: Session = Depends(get_db)) -> dict:
        result = lifecycle_review(db, variant_id)
        QueryService(db, None).audit(request.state.session_id, "variant_lifecycle_history_read", variant_id=variant_id)
        db.commit()
        return result

    @app.post("/v1/tire-variants/{variant_id}/lifecycle-events", status_code=201, dependencies=[Depends(admin_guard)])
    def revise(variant_id: str, payload: LifecycleRequest, request: Request,
               db: Session = Depends(get_db)) -> dict:
        return append_lifecycle_event(db, variant_id, payload, request.state.session_id)
