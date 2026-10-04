"""Frozen evidence-backed comparisons and separate personal preference history."""
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import AfterValidator, Field, StrictInt, model_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, load_only

from .auth import session_scope
from .curation import review_state
from .db import DrivingPreferenceRevision, SavedComparison, SavedComparisonRevision, Snapshot, uid
from .domain import CompareRequest, StrictModel, digest, stable_json
from .lifecycle import annotate_variants
from .service import QueryService, provenance, timestamp


def comparison_view(db: Session, payload: CompareRequest, *, registry=None) -> dict:
    """Caller holds the ingestion lock for a consistent multi-query fact view."""
    service = QueryService(db, None)
    ids = payload.variant_ids
    from .identity_resolution import require_current_contracts
    require_current_contracts(db, ids)
    mappings = None
    if payload.resolve_identities:
        from .identity_resolution import resolve_comparison_ids
        ids, mappings = resolve_comparison_ids(db, ids)
    equivalences = {}
    if mappings:
        from .identity_resolution import annotate_identities
        selected = annotate_identities(db, [{'id': key} for key in payload.variant_ids])
        for row in selected:
            state = row.get('identity_resolution', {})
            if state.get('state') == 'redirected' and state.get('action') == 'merge':
                equivalences.setdefault(state['target_id'], {})[row['id']] = state['event_id']
    rows = [service.historical_variant(variant_id) for variant_id in ids]
    excluded = [row for row in rows if row["lifecycle"]["state"] == "revoked"]
    variants = [row for row in rows if row["lifecycle"]["state"] != "revoked"]
    for variant in variants:
        # Keep the compared source versions, not every prior historical revision.
        latest = {}
        for version in variant["versions"]:
            latest.setdefault(version["source_id"], version)
        variant["versions"] = list(latest.values())
        if payload.include_manual and variant["versions"]:
            review = review_state(db, variant["id"], variant["versions"][0]["source_id"])
            variant["curation"] = {key: review[key] for key in ("source_id", "revision", "fields", "base_fact_id")}
            variant["effective_facts"] = review["effective_facts"]
        from .field_evidence import variant_field_resolution
        variant['field_resolution'] = variant_field_resolution(db, registry, variant['id'], scope='compare',
            equivalences=equivalences.get(variant['id']))
    snapshots = [db.get(Snapshot, variant["snapshot_id"]) for variant in variants if variant["snapshot_id"]]
    result = {"data_state": "local_snapshot", "variant_ids": payload.variant_ids, "include_manual": payload.include_manual,
              "variants": variants,
              "excluded_variants": [{key: row[key] for key in ("id", "brand", "model", "size", "region", "manufacturer_product_code", "lifecycle")} for row in excluded],
              "provenance": [provenance(snapshot) for snapshot in snapshots if snapshot],
              "conflicts": service.conflicts(variants),
              "notice": "历史精确 SKU 比较；不计算跨测试事件性能排名。"}
    if mappings is not None:
        result.update(resolve_identities=True, identity_mappings=mappings)
    return {**result, "fingerprint": digest(result)}


def valid_description(value: str) -> str:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError("名称或备注包含无效文字编码") from None
    if any(ord(character) < 32 and character not in "\r\n\t" for character in value):
        raise ValueError("名称或备注不得包含控制字符")
    return value


DescriptionText = Annotated[str, AfterValidator(valid_description)]


class SaveComparisonRequest(CompareRequest):
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: DescriptionText = Field(min_length=1, max_length=120)
    notes: DescriptionText = Field(default="", max_length=2000)


class ComparisonMetadataRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    title: DescriptionText = Field(min_length=1, max_length=120)
    notes: DescriptionText = Field(default="", max_length=2000)


class ComparisonStateRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    action: Literal["archive", "restore"]


Weight = Annotated[StrictInt, Field(ge=0, le=100)]


class DrivingWeights(StrictModel):
    dry: Weight
    wet: Weight
    quiet: Weight
    comfort: Weight
    wear: Weight
    energy: Weight
    appearance: Weight

    @model_validator(mode="after")
    def total_is_100(self):
        if sum(self.model_dump().values()) != 100:
            raise ValueError("七项偏好权重合计必须为 100")
        return self


class PreferenceRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=0)
    weights: DrivingWeights


class PreferenceClearRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=0)


def saved_metadata(saved: SavedComparison, row: SavedComparisonRevision) -> dict:
    return {"id": saved.id, "title": row.title, "notes": row.notes, "revision": row.revision,
            "archived": row.archived, "created_at": timestamp(saved.created_at), "updated_at": timestamp(row.created_at),
            "fingerprint": saved.fingerprint, "variant_count": saved.variant_count, "include_manual": saved.include_manual}


def latest_saved(db: Session, comparison_id: str, expected_revision: int | None = None) -> tuple:
    saved = db.get(SavedComparison, comparison_id)
    if saved is None:
        raise HTTPException(404, "未找到保存的比较")
    row = db.scalar(select(SavedComparisonRevision).where(SavedComparisonRevision.comparison_id == comparison_id)
                    .order_by(desc(SavedComparisonRevision.revision)).limit(1))
    if row is None:
        raise HTTPException(404, "未找到比较记录的描述")
    if expected_revision is not None and row.revision != expected_revision:
        raise HTTPException(409, "保存记录已更新，请重新载入后操作")
    return saved, row


def preference_state(db: Session, scope: list[str]) -> dict:
    rows = db.scalars(select(DrivingPreferenceRevision).where(DrivingPreferenceRevision.actor_session_id.in_(scope))
                      .order_by(desc(DrivingPreferenceRevision.revision)).limit(21)).all()
    row = rows[0] if rows else None
    return {"scope": "actor", "revision": row.revision if row else 0, "weights": row.weights if row else None,
            "updated_at": timestamp(row.created_at) if row else None, "history_truncated": len(rows) > 20,
            "history": [{"revision": item.revision, "weights": item.weights, "created_at": timestamp(item.created_at)} for item in rows[:20]],
            "notice": "个人偏好不改写官方参数或客观测试排序；偏好仅本人可见（登录按账户聚合，匿名按会话隔离）；当前未启用推荐评分。"}


def append_preference(db: Session, expected: int, weights: dict | None, session_id: str) -> dict:
    QueryService(db, None).lock_ingestion()
    before = preference_state(db, session_scope(db, session_id))
    if expected != before["revision"]:
        raise HTTPException(409, "驾驶偏好已更新，请重新载入并核对后保存")
    if weights == before["weights"]:
        return before
    # revision 列带全局唯一约束：沿用全局单调计数，各账户只看自己归属过滤后的链条（编号可能有跳档）。
    next_revision = (db.scalar(select(func.max(DrivingPreferenceRevision.revision))) or 0) + 1
    row = DrivingPreferenceRevision(revision=next_revision, weights=weights, actor_session_id=session_id)
    db.add(row)
    QueryService(db, None).audit(session_id, "driving_preferences_changed", revision=row.revision, cleared=weights is None)
    db.commit()
    return preference_state(db, session_scope(db, session_id))


def register_research_routes(app: FastAPI) -> None:
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post("/v1/saved-comparisons", status_code=201)
    def save(payload: SaveComparisonRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        service = QueryService(db, None)
        service.lock_ingestion()
        compared = comparison_view(db, payload, registry=app.state.registry)
        if compared["fingerprint"] != payload.expected_fingerprint:
            raise HTTPException(409, "比较中的事实、修订或版本状态已变化，请重新核对比较后再保存")
        if not compared["variants"]:
            raise HTTPException(422, "没有可保存的有效比较项")
        if len(stable_json(compared).encode("utf-8")) > 8 * 1024 * 1024:
            raise HTTPException(422, "比较记录过大，请减少所选规格")
        saved = SavedComparison(id=uid(), payload=compared, fingerprint=compared["fingerprint"],
            variant_count=len(compared["variants"]), include_manual=payload.include_manual, actor_session_id=request.state.session_id)
        db.add(saved)
        db.flush()
        row = SavedComparisonRevision(comparison_id=saved.id, revision=1, title=payload.title,
            notes=payload.notes, archived=False, operation="save", actor_session_id=request.state.session_id)
        db.add(row)
        service.audit(request.state.session_id, "comparison_snapshot_saved", comparison_id=saved.id, fingerprint=saved.fingerprint)
        db.commit()
        return saved_metadata(saved, row)

    @app.get("/v1/saved-comparisons")
    def listing(archived: bool = False, offset: int = Query(0, ge=0), db: Session = Depends(get_db)) -> dict:
        latest = select(SavedComparisonRevision.comparison_id, func.max(SavedComparisonRevision.revision).label("revision")).group_by(SavedComparisonRevision.comparison_id).subquery()
        statement = (select(SavedComparison, SavedComparisonRevision)
            .join(SavedComparisonRevision, SavedComparisonRevision.comparison_id == SavedComparison.id)
            .join(latest, (latest.c.comparison_id == SavedComparison.id) & (latest.c.revision == SavedComparisonRevision.revision))
            .where(SavedComparisonRevision.archived == archived))
        total = db.scalar(select(func.count()).select_from(statement.with_only_columns(SavedComparison.id).subquery())) or 0
        rows = db.execute(statement.options(load_only(SavedComparison.id, SavedComparison.fingerprint,
            SavedComparison.variant_count, SavedComparison.include_manual, SavedComparison.created_at))
            .order_by(desc(SavedComparison.created_at), desc(SavedComparison.id)).offset(offset).limit(50)).all()
        return {"data_state": "local_snapshot", "scope": "local_workspace", "items": [saved_metadata(saved, row) for saved, row in rows],
                "offset": offset, "limit": 50, "total": total}

    @app.get("/v1/saved-comparisons/{comparison_id}")
    def detail(comparison_id: str, request: Request, mode: Literal["history"] = Query(...), db: Session = Depends(get_db)) -> dict:
        saved, row = latest_saved(db, comparison_id)
        history = db.scalars(select(SavedComparisonRevision).where(SavedComparisonRevision.comparison_id == saved.id)
                            .order_by(desc(SavedComparisonRevision.revision)).limit(51)).all()
        current_ids = list(dict.fromkeys(saved.payload['variant_ids'] + [item['id'] for item in saved.payload['variants']]))
        current = annotate_variants(db, [{"id": key} for key in current_ids])
        result = {**saved_metadata(saved, row), "data_state": "local_snapshot", "comparison": saved.payload,
                  "current_lifecycle": {item["id"]: item["lifecycle"] for item in current},
                  "history_truncated": len(history) > 50,
                  "history": [{"revision": item.revision, "title": item.title, "notes": item.notes, "operation": item.operation,
                               "archived": item.archived, "created_at": timestamp(item.created_at)} for item in history[:50]]}
        result['current_identity_resolutions'] = {item['id']: item['identity_resolution'] for item in current
                                                  if 'identity_resolution' in item}
        QueryService(db, None).audit(request.state.session_id, "saved_comparison_history_read", comparison_id=saved.id)
        db.commit()
        return result

    def revise(comparison_id: str, expected: int, session_id: str, db: Session, *, title: str | None = None,
               notes: str | None = None, archived: bool | None = None) -> dict:
        service = QueryService(db, None)
        service.lock_ingestion()
        saved, before = latest_saved(db, comparison_id, expected)
        new_title = before.title if title is None else title
        new_notes = before.notes if notes is None else notes
        new_state = before.archived if archived is None else archived
        if (new_title, new_notes, new_state) == (before.title, before.notes, before.archived):
            return saved_metadata(saved, before)
        row = SavedComparisonRevision(comparison_id=saved.id, revision=before.revision + 1, title=new_title,
            notes=new_notes, archived=new_state, operation="edit" if archived is None else "archive" if archived else "restore",
            actor_session_id=session_id)
        db.add(row)
        service.audit(session_id, "saved_comparison_metadata_changed", comparison_id=saved.id, revision=row.revision, operation=row.operation)
        db.commit()
        return saved_metadata(saved, row)

    @app.put("/v1/saved-comparisons/{comparison_id}")
    def edit(comparison_id: str, payload: ComparisonMetadataRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        return revise(comparison_id, payload.expected_revision, request.state.session_id, db, title=payload.title, notes=payload.notes)

    @app.post("/v1/saved-comparisons/{comparison_id}/state")
    def state(comparison_id: str, payload: ComparisonStateRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        return revise(comparison_id, payload.expected_revision, request.state.session_id, db, archived=payload.action == "archive")

    @app.get("/v1/driving-preferences")
    def preferences(request: Request, db: Session = Depends(get_db)) -> dict:
        return preference_state(db, session_scope(db, request.state.session_id))

    @app.put("/v1/driving-preferences")
    def save_preferences(payload: PreferenceRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        return append_preference(db, payload.expected_revision, payload.weights.model_dump(), request.state.session_id)

    @app.post("/v1/driving-preferences/clear")
    def clear_preferences(payload: PreferenceClearRequest, request: Request, db: Session = Depends(get_db)) -> dict:
        return append_preference(db, payload.expected_revision, None, request.state.session_id)
