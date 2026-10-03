"""Local monitoring rules, fenced job leases and transactional in-app alerts.

No external messages are sent. The evidence ingestion transaction publishes the
in-app delivery, so a worker crash cannot leave a fact committed without its alert.
"""
from datetime import timedelta
from typing import Annotated, Literal
import unicodedata

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import Field, StrictBool, StrictInt, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .db import (AlertEvent, AlertRule, AlertRuleRevision, ChangeEvent, FactVersion,
                 MonitorJob, MonitorRun, NotificationDelivery, TireVariant, uid, utc, utcnow)
from .domain import StrictModel, TireQuery, digest
from .research import DescriptionText
from .identity_contract import contract_metadata, require_current_identity
from .service import QueryService, timestamp
from .source_settings import SourceAccessBlocked, assert_source_access

LEASE_SECONDS = 600


class LeaseLost(RuntimeError):
    pass


def guard_claim(db: Session, claim: dict) -> None:
    job = db.get(MonitorJob, claim["id"], populate_existing=True)
    if not job or job.lease_token != claim["token"] or not job.lease_until or utc(job.lease_until) <= utcnow():
        raise LeaseLost("monitor_lease_lost")
    generation = claim.get('source_access_generation')
    if type(generation) is not int:
        raise SourceAccessBlocked('source_access_pin_missing')
    assert_source_access(db, job.source_id, generation)


Kind = Literal["facts_changed", "variant_observed"]
FieldName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")]


def normalize_technology(value: str) -> str:
    """Only spelling normalization, never substring or cross-technology aliases."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def canonical_conditions(value: dict) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) - {"technology"}:
        raise ValueError("监控条件仅支持 technology 技术名称")
    if not value:
        return {}
    technology = value["technology"]
    if (not isinstance(technology, str) or len(technology) > 100
            or any(unicodedata.category(char).startswith("C") for char in technology)):
        raise ValueError("技术名称须为不超过 100 字符的文本，不得包含控制字符")
    normalized = normalize_technology(technology)
    if len(normalized) > 100:
        raise ValueError("规范化后的技术名称不得超过 100 字符")
    if not normalized:
        return {}
    labels = {"acoustic": "Acoustic", "pncs": "PNCS", "contisilent": "ContiSilent", "foam": "Foam"}
    return {"technology": labels.get(normalized, normalized)}


def matches_conditions(identity: dict, conditions: dict | None) -> bool:
    """Match only exact SKU identity fields; unknown/marketing text is not proof."""
    if not conditions:
        return True
    if not isinstance(conditions, dict) or set(conditions) != {"technology"}:
        return False
    technology = conditions.get("technology")
    if not isinstance(technology, str) or not technology.strip():
        return False
    expected = normalize_technology(technology)
    candidates = [identity.get("acoustic_technology")]
    features = identity.get("technology_features")
    if isinstance(features, list):
        candidates.extend(features)
    return any(isinstance(candidate, str) and normalize_technology(candidate) == expected for candidate in candidates)


class RuleSettings(StrictModel):
    name: DescriptionText = Field(min_length=1, max_length=120)
    interval_seconds: StrictInt = Field(default=21600, ge=14400, le=604800)
    enabled: StrictBool = False
    kinds: list[Kind] = Field(default_factory=lambda: ["facts_changed"], min_length=1, max_length=2)
    fields: list[FieldName] = Field(default_factory=list, max_length=40)
    conditions: dict[str, str] = Field(default_factory=dict)

    @field_validator("conditions", mode="before")
    @classmethod
    def technology_condition(cls, value):
        return canonical_conditions(value)

    @field_validator("kinds", "fields")
    @classmethod
    def unique_values(cls, values):
        return sorted(set(values))


class RuleCreate(RuleSettings):
    source_id: str = Field(min_length=1, max_length=80)
    query: TireQuery
    variant_id: str | None = Field(default=None, min_length=1, max_length=64)


class RuleEdit(RuleSettings):
    expected_revision: StrictInt = Field(ge=1)


class RuleState(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    action: Literal["archive", "restore"]


class ReadState(StrictModel):
    read: StrictBool


def current_rules(db: Session, job_id: str | None = None):
    latest = (select(AlertRuleRevision.rule_id, func.max(AlertRuleRevision.revision).label("revision"))
              .group_by(AlertRuleRevision.rule_id).subquery())
    statement = (select(AlertRule, AlertRuleRevision).join(AlertRuleRevision, AlertRuleRevision.rule_id == AlertRule.id)
                 .join(latest, (latest.c.rule_id == AlertRule.id) & (latest.c.revision == AlertRuleRevision.revision)))
    return statement.where(AlertRule.job_id == job_id) if job_id else statement


def matches(identity: dict, query: dict) -> bool:
    return ((not query.get("model") or query["model"].casefold() in identity["model"].casefold())
            and (not query.get("size") or query["size"].replace("ZR", "R") == identity["size"].replace("ZR", "R")))


def record_alerts(db: Session, events: list[ChangeEvent]) -> None:
    """Called under ingestion lock, without committing or starting another lock."""
    if not events:
        return
    rules = db.execute(current_rules(db).where(AlertRuleRevision.enabled.is_(True), AlertRuleRevision.archived.is_(False))).all()
    for change in events:
        contract = contract_metadata(db, change.variant_id)
        if contract['state'] != 'current':
            continue
        identity = contract['current_identity']
        for rule, revision in rules:
            job = db.get(MonitorJob, rule.job_id)
            if (job.source_id != change.source_id or change.kind not in revision.kinds
                    or (rule.variant_id and rule.variant_id != change.variant_id)
                    or not matches(identity, job.query)
                    or not matches_conditions(identity, revision.conditions)
                    or (revision.fields and not set(revision.fields).intersection(change.changes))):
                continue
            # Replay safety complements the unique rule/change constraint.
            if db.scalar(select(AlertEvent.id).where(AlertEvent.rule_id == rule.id, AlertEvent.change_id == change.id)):
                continue
            alert = AlertEvent(id=uid(), rule_id=rule.id, rule_revision_id=revision.id, change_id=change.id)
            db.add(alert)
            db.flush()
            db.add(NotificationDelivery(alert_id=alert.id))


def interval_for(db: Session, job_id: str) -> int | None:
    settings = db.execute(current_rules(db, job_id).where(AlertRuleRevision.enabled.is_(True), AlertRuleRevision.archived.is_(False))).all()
    return min((row.interval_seconds for rule, row in settings
                if not rule.variant_id or contract_metadata(db, rule.variant_id)['state'] == 'current'), default=None)


def reschedule(db: Session, job: MonitorJob) -> None:
    interval = interval_for(db, job.id)
    if interval is not None:
        job.next_due_at = utc(job.last_finished_at) + timedelta(seconds=interval) if job.last_finished_at else utcnow()


def claim_job(database, now=None) -> dict | None:
    from .monitor_tasks import expire_attempts_locked, start_attempt_locked
    now = now or utcnow()
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        expire_attempts_locked(db, 'tire', now=now)
        # Only enabled rules make a job eligible. Archived jobs do not starve the queue.
        eligible = current_rules(db).where(AlertRuleRevision.enabled.is_(True), AlertRuleRevision.archived.is_(False))
        jobs = db.scalars(select(MonitorJob).where(
            MonitorJob.id.in_(eligible.with_only_columns(AlertRule.job_id)), MonitorJob.next_due_at <= now,
            (MonitorJob.lease_until.is_(None)) | (MonitorJob.lease_until <= now))
            .order_by(MonitorJob.next_due_at, MonitorJob.id)).all()
        available = []
        for candidate in jobs:
            try:
                generation = assert_source_access(db, candidate.source_id)
            except SourceAccessBlocked:
                continue
            if interval_for(db, candidate.id) is None:
                continue
            running = db.scalar(select(MonitorJob.id).where(MonitorJob.source_id == candidate.source_id, MonitorJob.lease_until > now).limit(1))
            last_finish = db.scalar(select(func.max(MonitorRun.finished_at)).join(MonitorJob, MonitorJob.id == MonitorRun.job_id).where(MonitorJob.source_id == candidate.source_id))
            if not running and (not last_finish or utc(last_finish) + timedelta(seconds=2.1) <= now):
                available.append(candidate)
                break
        jobs = available
        if not jobs:
            db.commit()  # Persist expired attempts even when every source/rule is paused.
            return None
        job = jobs[0]
        job.lease_token = uid()
        job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        claim = {"id": job.id, "source_id": job.source_id, "query": job.query,
                 "source_access_generation": generation,
                 "token": job.lease_token, "started_at": now,
                 "queue_lag_seconds": max(0, (now - utc(job.next_due_at)).total_seconds())}
        claim['attempt_id'] = start_attempt_locked(db, 'tire', claim)
        db.commit()
        return claim


def finish_job(database, claim: dict, state: str, reason: str | None = None, now=None, *, query_id=None) -> bool:
    from .monitor_tasks import finish_attempt_locked, interrupt_attempt_locked
    now = now or utcnow()
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        job = db.get(MonitorJob, claim["id"])
        if job is None or job.lease_token != claim["token"] or job.lease_until is None or utc(job.lease_until) <= now:
            interrupt_attempt_locked(db, claim, 'monitor_lease_lost', now=now)
            db.commit()
            return False
        run = MonitorRun(id=uid(), job_id=job.id, lease_token=claim["token"], state=state,
                         reason=reason, started_at=claim["started_at"], finished_at=now)
        db.add(run)
        db.flush()
        if claim.get('attempt_id') and not finish_attempt_locked(db, claim, state, reason,
                query_id=query_id, finished_at=now, run_id=run.id):
            db.rollback()
            return False
        job.last_finished_at = now
        job.lease_token = None
        job.lease_until = None
        reschedule(db, job)
        db.commit()
        return True


def revision_view(row: AlertRuleRevision) -> dict:
    return {"revision": row.revision, "name": row.name, "enabled": row.enabled, "archived": row.archived,
            "interval_seconds": row.interval_seconds, "kinds": row.kinds, "fields": row.fields,
            "conditions": row.conditions or {},
            "created_at": timestamp(row.created_at)}


def rule_view(db: Session, rule: AlertRule, row: AlertRuleRevision) -> dict:
    from .ai_models import AIDraftApplication
    job = db.get(MonitorJob, rule.job_id)
    last = db.scalar(select(MonitorRun).where(MonitorRun.job_id == job.id).order_by(desc(MonitorRun.finished_at)).limit(1))
    application = db.execute(select(AIDraftApplication.id, AIDraftApplication.draft_request_id)
                             .where(AIDraftApplication.rule_id == rule.id)).first()
    origin = None
    if application:
        # Select scalar identifiers only; never load the private natural-language
        # prompt or the reviewed draft just to show the shared rule's provenance.
        application_id, draft_id = application
        origin = {"kind": "ai_rule_draft", "draft_id": draft_id, "application_id": application_id}
    contract = contract_metadata(db, rule.variant_id) if rule.variant_id else None
    current = contract is None or contract['state'] == 'current'
    return {"identity_contract": contract, "tracking_state": 'current' if current else 'identity_review_required',
            "tracking_notice": contract['notice'] if contract and not current else None,
            "id": rule.id, "source_id": job.source_id, "query": job.query, "variant_id": rule.variant_id,
            "origin": origin,
            **revision_view(row), "job": {"id": job.id, "next_due_at": timestamp(job.next_due_at) if current and row.enabled and not row.archived else None,
            "lease_until": timestamp(job.lease_until) if job.lease_until else None,
            "last_run": {"state": last.state, "reason": last.reason, "finished_at": timestamp(last.finished_at)} if last else None}}


def find_rule(db: Session, rule_id: str, expected: int | None = None):
    result = db.execute(current_rules(db).where(AlertRule.id == rule_id)).first()
    if not result:
        raise HTTPException(404, "未找到监控规则")
    if expected is not None and result[1].revision != expected:
        raise HTTPException(409, "监控规则已更新，请重新载入")
    return result


def _require_source_size(source: dict | None, query: dict) -> None:
    if source and source.get("requires_size") and not query.get("size"):
        raise HTTPException(422, "此来源按尺寸提供规格，请填写轮胎尺寸")


def validate_rule_target(db: Session, registry, payload: RuleCreate) -> tuple[dict, dict]:
    """Validate supported source/model/SKU without acquiring locks or committing."""
    source = next((item for item in registry.sources() if item["id"] == payload.source_id), None)
    if not source or source.get("status") != "ready" or source.get("target_kind") == "recall":
        raise HTTPException(422, "请选择已接入的轮胎来源")
    query = payload.query.canonical()
    if not query.get("model") or (source.get("supported_models") is not None and query["model"] not in source["supported_models"]):
        raise HTTPException(422, "请选择此来源已接入的型号")
    _require_source_size(source, query)
    if payload.variant_id:
        variant = db.get(TireVariant, payload.variant_id)
        fact = db.scalar(select(FactVersion.id).where(FactVersion.variant_id == payload.variant_id,
                                                     FactVersion.source_id == payload.source_id).limit(1))
        if not variant or not fact:
            raise HTTPException(422, "精确 SKU 与来源或查询条件不匹配")
        identity = require_current_identity(db, payload.variant_id)
        if not matches(identity, query):
            raise HTTPException(422, "精确 SKU 与来源或查询条件不匹配")
        if not matches_conditions(identity, payload.conditions):
            raise HTTPException(422, "精确 SKU 的已声明技术与监控条件不匹配")
    return source, query


def create_rule(db: Session, registry, payload: RuleCreate, session_id: str) -> dict:
    """Caller owns the ingestion lock and transaction, including any draft receipt."""
    _source, query = validate_rule_target(db, registry, payload)
    job_id = digest({"source_id": payload.source_id, "query": query})
    job = db.get(MonitorJob, job_id)
    if job is None:
        job = MonitorJob(id=job_id, source_id=payload.source_id, query=query, next_due_at=utcnow())
        db.add(job)
        db.flush()
    rule = AlertRule(id=uid(), job_id=job.id, variant_id=payload.variant_id)
    db.add(rule)
    db.flush()
    row = AlertRuleRevision(rule_id=rule.id, revision=1, actor_session_id=session_id,
                            **payload.model_dump(include=set(RuleSettings.model_fields)))
    db.add(row)
    db.flush()
    reschedule(db, job)
    QueryService(db, None).audit(session_id, "monitor_rule_created", rule_id=rule.id)
    return rule_view(db, rule, row)


def register_monitoring_routes(app: FastAPI) -> None:
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post("/v1/alert-rules", status_code=201)
    def create(payload: RuleCreate, request: Request, db: Session = Depends(get_db)) -> dict:
        service = QueryService(db, None)
        service.lock_ingestion()
        result = create_rule(db, app.state.registry, payload, request.state.session_id)
        db.commit()
        return result

    @app.get("/v1/alert-rules")
    def listing(archived: bool = False, offset: int = Query(0, ge=0), db: Session = Depends(get_db)) -> dict:
        statement = current_rules(db).where(AlertRuleRevision.archived == archived)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.order_by(desc(AlertRule.created_at), AlertRule.id).offset(offset).limit(50)).all()
        return {"scope": "local_workspace", "items": [rule_view(db, rule, row) for rule, row in rows], "total": total, "offset": offset,
                "notice": "规则需独立 Worker 运行才会定时抓取；站内提醒仅记录规则启用后采纳的变化，非实时参数。"}

    @app.get("/v1/alert-rules/{rule_id}")
    def detail(rule_id: str, mode: Literal["history"] = Query(...), db: Session = Depends(get_db)) -> dict:
        rule, row = find_rule(db, rule_id)
        history = db.scalars(select(AlertRuleRevision).where(AlertRuleRevision.rule_id == rule.id).order_by(desc(AlertRuleRevision.revision)).limit(51)).all()
        return {**rule_view(db, rule, row), "history": [revision_view(item) for item in history[:50]], "history_truncated": len(history) > 50}

    @app.put("/v1/alert-rules/{rule_id}")
    def edit(rule_id: str, payload: RuleEdit, request: Request, db: Session = Depends(get_db)) -> dict:
        service = QueryService(db, None)
        service.lock_ingestion()
        rule, before = find_rule(db, rule_id, payload.expected_revision)
        if before.archived:
            raise HTTPException(409, "请先恢复已归档规则")
        settings = payload.model_dump(exclude={"expected_revision"})
        if "conditions" not in payload.model_fields_set:
            settings["conditions"] = before.conditions or {}
        if settings["enabled"]:
            if rule.variant_id:
                require_current_identity(db, rule.variant_id)
            job = db.get(MonitorJob, rule.job_id)
            source = next((item for item in app.state.registry.sources() if item["id"] == job.source_id), None)
            # A legacy invalid target can still be paused or archived. Only the
            # required-size capability is checked here, preserving other edits.
            _require_source_size(source, job.query)
        if all((getattr(before, key) or {} if key == "conditions" else getattr(before, key)) == value
               for key, value in settings.items()):
            return rule_view(db, rule, before)
        row = AlertRuleRevision(rule_id=rule.id, revision=before.revision + 1, actor_session_id=request.state.session_id, **settings)
        db.add(row)
        db.flush()
        reschedule(db, db.get(MonitorJob, rule.job_id))
        service.audit(request.state.session_id, "monitor_rule_edited", rule_id=rule.id, revision=row.revision)
        db.commit()
        return rule_view(db, rule, row)

    @app.post("/v1/alert-rules/{rule_id}/state")
    def state(rule_id: str, payload: RuleState, request: Request, db: Session = Depends(get_db)) -> dict:
        service = QueryService(db, None)
        service.lock_ingestion()
        rule, before = find_rule(db, rule_id, payload.expected_revision)
        archived = payload.action == "archive"
        if before.archived == archived:
            raise HTTPException(409, "规则已处于所选状态")
        settings = {key: getattr(before, key) for key in RuleSettings.model_fields}
        settings["conditions"] = before.conditions or {}
        settings["enabled"] = False  # Restoring requires explicit re-enabling.
        row = AlertRuleRevision(rule_id=rule.id, revision=before.revision + 1, archived=archived,
                                actor_session_id=request.state.session_id, **settings)
        db.add(row)
        service.audit(request.state.session_id, "monitor_rule_state_changed", rule_id=rule.id, archived=archived)
        db.flush()
        reschedule(db, db.get(MonitorJob, rule.job_id))
        db.commit()
        return rule_view(db, rule, row)

    @app.get("/v1/notifications")
    def notifications(unread: bool = False, offset: int = Query(0, ge=0), db: Session = Depends(get_db)) -> dict:
        statement = (select(NotificationDelivery, AlertEvent, ChangeEvent, AlertRuleRevision, TireVariant)
                     .join(AlertEvent, AlertEvent.id == NotificationDelivery.alert_id)
                     .join(ChangeEvent, ChangeEvent.id == AlertEvent.change_id)
                     .join(AlertRuleRevision, AlertRuleRevision.id == AlertEvent.rule_revision_id)
                     .join(TireVariant, TireVariant.id == ChangeEvent.variant_id))
        if unread:
            statement = statement.where(NotificationDelivery.read_at.is_(None))
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.order_by(desc(NotificationDelivery.delivered_at), NotificationDelivery.id).offset(offset).limit(50)).all()
        items = [{"id": delivery.id, "rule_id": alert.rule_id, "rule_name": revision.name,
                  "rule_revision": revision.revision, "read_at": timestamp(delivery.read_at) if delivery.read_at else None,
                  "rule_conditions": revision.conditions or {},
                  "delivered_at": timestamp(delivery.delivered_at), "change_id": change.id,
                  "kind": change.kind, "source_id": change.source_id, "variant_id": change.variant_id,
                  "identity_contract": contract_metadata(db, variant.id),
                  "identity": variant.identity, "changes": {key: value for key, value in change.changes.items() if not revision.fields or key in revision.fields},
                  "snapshot_id": change.snapshot_id, "previous_snapshot_id": change.previous_snapshot_id,
                  "observed_at": timestamp(change.observed_at)} for delivery, alert, change, revision, variant in rows]
        return {"scope": "local_workspace", "data_state": "local_snapshot", "items": items, "total": total, "offset": offset}

    @app.put("/v1/notifications/{delivery_id}/read")
    def mark(delivery_id: str, payload: ReadState, request: Request, db: Session = Depends(get_db)) -> dict:
        service = QueryService(db, None)
        service.lock_ingestion()
        row = db.get(NotificationDelivery, delivery_id)
        if row is None:
            raise HTTPException(404, "未找到站内提醒")
        if payload.read != (row.read_at is not None):
            row.read_at = utcnow() if payload.read else None
            service.audit(request.state.session_id, "notification_read_changed", delivery_id=row.id, read=payload.read)
            db.commit()
        return {"id": row.id, "read_at": timestamp(row.read_at) if row.read_at else None}
