"""Field-loss quarantine, separate from accepted evidence and explicit history APIs.

Rows align by product code namespace + code + brand/model/region/size, never by the mutable
load/speed/technology identity. This alignment does not merge product identities.
Row loss uses all baseline rows. Field loss uses known leaves of aligned baseline
rows; missing rows are counted by the independent row-loss rule, not counted twice.
At least 30% loss in either denominator rejects the observation. An unalignable or
duplicate key is ambiguous and fails closed once an accepted baseline exists.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, load_only

from .db import AuditEvent, QueryRun, RejectedObservation, SourceQuarantine, Verification, utc, utcnow
from .domain import VariantInput, product_code_namespace, stable_json

QUALITY_REASON = "source_quality_quarantined"
STABLE_FIELDS = ("manufacturer_product_code", "brand", "model", "region", "size")
IDENTITY_FIELDS = tuple(key for key in VariantInput.model_fields if key not in {"facts", "source_variant_name"})
IGNORED_FACT_FIELDS = {"evidence", "evidence_spans", "provenance", "source_updated_at", "source_start_date",
                       "source_end_date", "source_field_conflicts"}
METRIC_FIELDS = ("baseline_rows", "candidate_rows", "aligned_rows", "lost_rows", "row_loss_ratio",
                 "known_fields", "lost_fields", "field_loss_ratio")
SUCCESS_STATES = {"live", "live_verified_304"}
FAILURE_STATES = {"consent_required", "source_unavailable", "local_snapshot"}


class SourceQualityQuarantined(Exception):
    """Internal control flow; the caller commits the rejection and normal failure gate."""


def is_known(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(is_known(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(is_known(item) for item in value)
    return True  # Both False and numeric zero are real, known values.


def known_leaves(value: Any, path: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return {child: item for key, value in value.items() if key not in IGNORED_FACT_FIELDS
                for child, item in known_leaves(value, f"{path}.{key}").items()}
    return {path: value} if is_known(value) else {}


def row_fields(row: dict) -> dict[str, Any]:
    fields = {f"identity.{key}": row.get(key) for key in IDENTITY_FIELDS if is_known(row.get(key))}
    # GTIN and technology lists live under facts in the source contract: count
    # them once here, even though strict identity also uses them internally.
    for key, value in row.get("facts", {}).items():
        if key not in IGNORED_FACT_FIELDS:
            fields.update(known_leaves(value, f"facts.{key}"))
    return fields


def product_reference_key(row: dict) -> str | None:
    if any(not is_known(row.get(key)) for key in STABLE_FIELDS):
        return None
    return stable_json({key: row[key] for key in STABLE_FIELDS})


def namespace(row: dict) -> str | None:
    return product_code_namespace(row.get("facts", {}).get("product_code_type"))


def stable_key(row: dict) -> str | None:
    if product_reference_key(row) is None:
        return None
    try:
        code_type = namespace(row)
    except ValueError:
        return None
    return stable_json({**{key: row[key] for key in STABLE_FIELDS}, "product_code_type": code_type})


def namespace_reference_matches(baseline: list[dict] | None, candidates: list[dict]) -> dict[str, str]:
    """Unique unknown-to-known pairs are loss references, never entity aliases.

    Count the entire code family on both sides before allowing a reference. A
    family containing multiple namespaces cannot justify a historical split.
    """
    baseline = baseline or []
    old_groups, new_groups = {}, {}
    for rows, groups in ((baseline, old_groups), (candidates, new_groups)):
        for row in rows:
            key = product_reference_key(row)
            if key is not None:
                groups.setdefault(key, []).append(row)
    matches = {}
    for key in old_groups.keys() & new_groups.keys():
        before, after = old_groups[key], new_groups[key]
        if (len(before) == len(after) == 1 and stable_key(before[0]) is not None
                and stable_key(after[0]) is not None and namespace(before[0]) is None
                and namespace(after[0]) is not None):
            matches[stable_key(before[0])] = stable_key(after[0])
    return matches


def assess_quality(baseline: list[dict] | None, candidates: list[dict]) -> dict:
    references = namespace_reference_matches(baseline, candidates)
    report = assess_records(baseline, candidates, stable_key, row_fields, "field-loss@2",
                            reference_keys=references)
    report["namespace_reference_alignments"] = [
        {"baseline_key": key, "candidate_key": references[key], "entity_equivalence": False}
        for key in sorted(references)]
    return report


def assess_records(baseline: list[dict] | None, candidates: list[dict], key_of: Callable,
                   fields_of: Callable, ruleset: str, *, reference_keys: dict[str, str] | None = None) -> dict:
    """Shared loss arithmetic; each domain supplies its own stable identity and fields."""
    baseline = baseline or []
    report: dict[str, Any] = {
        "ruleset": ruleset, "threshold": 0.3,
        "baseline_rows": len(baseline), "candidate_rows": len(candidates), "aligned_rows": 0,
        "lost_rows": 0, "row_loss_ratio": 0.0, "known_fields": 0, "field_loss_ratio": 0.0,
        "lost_field_count": 0, "lost_fields": [], "lost_row_keys": [], "ambiguous_keys": [], "reason_codes": [],
    }
    if not baseline:
        return report
    old_keys, new_keys = [key_of(row) for row in baseline], [key_of(row) for row in candidates]
    old_counts, new_counts = Counter(old_keys), Counter(new_keys)
    for side, keys, counts in (("baseline", old_keys, old_counts), ("candidate", new_keys, new_counts)):
        report["ambiguous_keys"].extend(f"{side}[{index}]:missing_stable_key" for index, key in enumerate(keys) if key is None)
        report["ambiguous_keys"].extend(f"{side}:duplicate:{key}" for key, count in counts.items() if key is not None and count > 1)
    new_rows = {key: row for key, row in zip(new_keys, candidates) if key is not None and new_counts[key] == 1}
    for index, (key, previous) in enumerate(zip(old_keys, baseline)):
        candidate_key = key if key in new_rows else (reference_keys or {}).get(key)
        if key is None or old_counts[key] != 1 or candidate_key not in new_rows:
            report["lost_row_keys"].append(key or f"baseline[{index}]:missing_stable_key")
            continue
        report["aligned_rows"] += 1
        before, after = fields_of(previous), fields_of(new_rows[candidate_key])
        lost = sorted(before.keys() - after.keys())
        report["known_fields"] += len(before)
        report["lost_field_count"] += len(lost)
        if lost:
            report["lost_fields"].append({"row_key": key, "paths": lost})
    report["lost_rows"] = len(report["lost_row_keys"])
    report["row_loss_ratio"] = report["lost_rows"] / len(baseline)
    if report["known_fields"]:
        report["field_loss_ratio"] = report["lost_field_count"] / report["known_fields"]
    # Integer comparisons keep an exact 30% boundary independent of float rounding.
    if report["known_fields"] and report["lost_field_count"] * 10 >= report["known_fields"] * 3:
        report["reason_codes"].append("field_loss_threshold")
    if report["lost_rows"] * 10 >= len(baseline) * 3:
        report["reason_codes"].append("row_loss_threshold")
    if report["ambiguous_keys"]:
        report["reason_codes"].append("ambiguous_alignment")
    return report


def metrics(report: dict) -> dict:
    return {key: report["lost_field_count"] if key == "lost_fields" else report[key] for key in METRIC_FIELDS}


def timestamp(value: Any) -> str | None:
    return utc(value).isoformat() if value is not None else None


def quarantine_metadata(row: SourceQuarantine | RejectedObservation) -> dict:
    from .vehicles import VehicleQuarantine
    if isinstance(row, RejectedObservation):
        return {"id": row.id, "query_id": row.query_id, "source_id": row.source_id,
                "source_url": row.source_url, "parser_version": row.parser_version,
                "observed_at": timestamp(row.observed_at), "raw_hash": row.raw_hash,
                "previous_snapshot_id": None, "status": "quarantined", "kind": "response_rejected",
                "stage": row.stage, "target_kind": row.target_kind,
                "reason_codes": [row.reason], "metrics": None,
                "evidence_path": f"/v1/quarantines/{row.id}?mode=history"}
    return {"id": row.id, "query_id": row.query_id, "source_id": row.source_id,
            "source_url": row.source_url, "parser_version": row.parser_version,
            "observed_at": timestamp(row.observed_at), "raw_hash": row.raw_hash,
            "previous_snapshot_id": row.previous_snapshot_id, "status": "quarantined", "kind": "field_loss",
            "target_kind": "vehicle" if isinstance(row, VehicleQuarantine) else "tire",
            **({"vehicle_id": row.vehicle_id} if isinstance(row, VehicleQuarantine) else {}),
            "reason_codes": row.quality["reason_codes"], "metrics": metrics(row.quality),
            "evidence_path": f"/v1/quarantines/{row.id}?mode=history"}


def source_health(db: Session, registry: Any, vehicle_source_ids: tuple[str, ...] = ()) -> dict:
    until = utcnow()
    since = until - timedelta(hours=24)
    source_ids = list(dict.fromkeys([row["id"] for row in registry.sources()] + list(vehicle_source_ids)))
    rows = db.execute(select(QueryRun.source_id, QueryRun.state, QueryRun.reason, QueryRun.created_at)
                      .where(QueryRun.source_id.in_(source_ids), QueryRun.created_at >= since, QueryRun.created_at <= until)
                      .order_by(desc(QueryRun.created_at))).all()
    verified = dict(db.execute(select(Verification.source_id, func.max(Verification.verified_at))
                              .join(QueryRun, QueryRun.id == Verification.query_id)
                              .where(QueryRun.created_at >= since, QueryRun.created_at <= until,
                                     QueryRun.state.in_(SUCCESS_STATES), Verification.source_id.in_(source_ids))
                              .group_by(Verification.source_id)).all())
    if vehicle_source_ids:
        from .vehicles import VehicleVerification
        vehicle_verified = db.execute(select(QueryRun.source_id, func.max(VehicleVerification.verified_at))
            .join(VehicleVerification, VehicleVerification.query_id == QueryRun.id)
            .where(QueryRun.source_id.in_(vehicle_source_ids), QueryRun.created_at >= since,
                   QueryRun.created_at <= until, QueryRun.state.in_(SUCCESS_STATES)).group_by(QueryRun.source_id)).all()
        for source_id, last_verified in vehicle_verified:
            if source_id not in verified or utc(last_verified) > utc(verified[source_id]):
                verified[source_id] = last_verified
    sources = []
    rejected_counts = dict(db.execute(select(RejectedObservation.source_id, func.count())
                          .where(RejectedObservation.observed_at >= since, RejectedObservation.observed_at <= until,
                                 RejectedObservation.source_id.in_(source_ids))
                          .group_by(RejectedObservation.source_id)).all())
    for source_id in source_ids:
        attempts = [row for row in rows if row.source_id == source_id]
        completed = [row for row in attempts if row.state in SUCCESS_STATES | FAILURE_STATES]
        latest = completed[0] if completed else None
        status = ("unknown" if latest is None else "quarantined" if latest.reason == QUALITY_REASON
                  else "healthy" if latest.state in SUCCESS_STATES else "degraded")
        sources.append({"source_id": source_id, "status": status,
                        "last_attempt_at": timestamp(attempts[0].created_at) if attempts else None,
                        "last_success_at": timestamp(verified.get(source_id)),
                        "last_reason": latest.reason if latest else None,
                        "attempts": len(attempts), "successes": sum(row.state in SUCCESS_STATES for row in attempts),
                        "failures": sum(row.state in FAILURE_STATES for row in attempts),
                        "quarantined_count": sum(row.reason == QUALITY_REASON for row in attempts),
                        "rejected_count": rejected_counts.get(source_id, 0)})
    return {"window": {"kind": "rolling_24h", "since": timestamp(since), "until": timestamp(until)}, "sources": sources}


def health_trends(db: Session, registry: Any, days: int, vehicle_source_ids: tuple[str, ...] = ()) -> dict:
    """按 UTC 日聚合的来源成功率趋势（只读，原始数据来自 query_runs / rejected_observations）。

    逐日 Python 聚合避免 SQL 方言差异；空日补零，保证前端拿到连续日期序列。
    """
    until = utcnow()
    since_day = until.date() - timedelta(days=days - 1)
    since = datetime(since_day.year, since_day.month, since_day.day)
    day_keys = {since_day + timedelta(days=offset) for offset in range(days)}
    source_ids = list(dict.fromkeys([row["id"] for row in registry.sources()] + list(vehicle_source_ids)))
    runs = db.execute(select(QueryRun.source_id, QueryRun.state, QueryRun.created_at)
                      .where(QueryRun.source_id.in_(source_ids), QueryRun.created_at >= since)).all()
    rejected = db.execute(select(RejectedObservation.source_id, RejectedObservation.observed_at)
                          .where(RejectedObservation.observed_at >= since,
                                 RejectedObservation.source_id.in_(source_ids))).all()
    buckets: dict[str, dict[Any, dict[str, int]]] = {source_id: {day: {"attempts": 0, "successes": 0, "failures": 0, "rejected": 0}
                                                                for day in day_keys} for source_id in source_ids}
    for row in runs:
        bucket = buckets.get(row.source_id, {}).get(row.created_at.date())
        if bucket is None:
            continue
        bucket["attempts"] += 1
        if row.state in SUCCESS_STATES:
            bucket["successes"] += 1
        elif row.state in FAILURE_STATES:
            bucket["failures"] += 1
    for row in rejected:
        bucket = buckets.get(row.source_id, {}).get(row.observed_at.date())
        if bucket is not None:
            bucket["rejected"] += 1
    sources = []
    for source_id in source_ids:
        sources.append({"source_id": source_id,
                        "days": [{"date": (since_day + timedelta(days=offset)).isoformat(),
                                  **buckets[source_id][since_day + timedelta(days=offset)]}
                                 for offset in range(days)]})
    return {"window": {"kind": "daily", "days": days, "since_date": since_day.isoformat(),
                       "until_date": (since_day + timedelta(days=days - 1)).isoformat()}, "sources": sources}


def register_quality_routes(app: FastAPI) -> None:
    from .vehicles import VehicleQuarantine
    from .adapters import xiaomi
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get("/v1/source-health")
    def health(db: Session = Depends(get_db)) -> dict:
        return source_health(db, app.state.registry, (xiaomi.SOURCE_ID,))

    @app.get("/v1/source-health/trends")
    def trends(days: int = Query(default=14, ge=1, le=90), db: Session = Depends(get_db)) -> dict:
        return health_trends(db, app.state.registry, days, (xiaomi.SOURCE_ID,))

    @app.get("/v1/quarantines")
    def quarantines(request: Request, source_id: str | None = Query(default=None, max_length=80),
                    limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
        statement = select(SourceQuarantine).options(load_only(
            SourceQuarantine.id, SourceQuarantine.query_id, SourceQuarantine.source_id,
            SourceQuarantine.source_url, SourceQuarantine.parser_version, SourceQuarantine.observed_at,
            SourceQuarantine.raw_hash, SourceQuarantine.previous_snapshot_id, SourceQuarantine.quality))
        if source_id:
            statement = statement.where(SourceQuarantine.source_id == source_id)
        items = db.scalars(statement.order_by(desc(SourceQuarantine.observed_at)).limit(limit)).all()
        rejected_statement = select(RejectedObservation).options(load_only(
            RejectedObservation.id, RejectedObservation.query_id, RejectedObservation.source_id,
            RejectedObservation.source_url, RejectedObservation.parser_version, RejectedObservation.observed_at,
            RejectedObservation.raw_hash, RejectedObservation.stage, RejectedObservation.reason, RejectedObservation.target_kind))
        if source_id:
            rejected_statement = rejected_statement.where(RejectedObservation.source_id == source_id)
        rejected = db.scalars(rejected_statement.order_by(desc(RejectedObservation.observed_at)).limit(limit)).all()
        vehicle_statement = select(VehicleQuarantine).options(load_only(
            VehicleQuarantine.id, VehicleQuarantine.query_id, VehicleQuarantine.vehicle_id, VehicleQuarantine.source_id,
            VehicleQuarantine.source_url, VehicleQuarantine.parser_version, VehicleQuarantine.observed_at,
            VehicleQuarantine.raw_hash, VehicleQuarantine.previous_snapshot_id, VehicleQuarantine.quality))
        if source_id:
            vehicle_statement = vehicle_statement.where(VehicleQuarantine.source_id == source_id)
        vehicles = db.scalars(vehicle_statement.order_by(desc(VehicleQuarantine.observed_at)).limit(limit)).all()
        # Taking top N metadata from each stream suffices for a global top N.
        combined = sorted([*items, *rejected, *vehicles], key=lambda row: (utc(row.observed_at), row.id), reverse=True)[:limit]
        known_sources = sorted(set(db.scalars(select(SourceQuarantine.source_id).distinct()))
                               | set(db.scalars(select(RejectedObservation.source_id).distinct()))
                               | set(db.scalars(select(VehicleQuarantine.source_id).distinct())))
        db.add(AuditEvent(session_id=request.state.session_id, action="quarantines_list_read",
                          detail={"source_id": source_id, "limit": limit}))
        db.commit()
        return {"data_state": "local_snapshot", "items": [quarantine_metadata(row) for row in combined],
                "source_ids": known_sources}

    @app.get("/v1/quarantines/{quarantine_id}")
    def quarantine(quarantine_id: str, request: Request, mode: Literal["history"] = Query(...),
                   db: Session = Depends(get_db)) -> dict:
        row = db.get(SourceQuarantine, quarantine_id)
        if row is None:
            row = db.get(VehicleQuarantine, quarantine_id)
        if row is None:
            row = db.get(RejectedObservation, quarantine_id)
            if row is None:
                raise HTTPException(404, "未找到隔离证据")
        db.add(AuditEvent(session_id=request.state.session_id, action="quarantine_history_read",
                          query_id=row.query_id, detail={"quarantine_id": row.id, "source_id": row.source_id}))
        db.commit()
        if isinstance(row, RejectedObservation):
            return {**quarantine_metadata(row), "data_state": "local_snapshot", "accepted": False,
                    "content_type": row.content_type, "body": row.raw_body.decode("utf-8"), "candidates": [],
                    "quality": None}
        return {**quarantine_metadata(row), "data_state": "local_snapshot", "accepted": False,
                "content_type": row.content_type, "body": row.body,
                "candidates": row.payload["fitments"] if isinstance(row, VehicleQuarantine) else row.candidates,
                **({"vehicle_payload": row.payload} if isinstance(row, VehicleQuarantine) else {}),
                "quality": row.quality}
