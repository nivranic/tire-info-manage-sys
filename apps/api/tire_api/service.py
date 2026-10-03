"""Online-first query orchestration; local facts have an explicit authorization gate."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any, Callable

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import desc, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import (
    AuditEvent, ChangeEvent, FactVersion, FallbackConsent, QueryRun, Snapshot,
    SourceQuarantine, TireVariant, Verification, utc, utcnow, uid,
)
from .domain import ConsentRequest, LiveQueryRequest, VariantInput, digest
from .query_filters import canonical_filters, select_variants
from .identity_contract import IdentityContractError, resolve_variant, schema_version
from .quality import QUALITY_REASON, SourceQualityQuarantined, assess_quality, metrics
from .captures import before_parse_recorder, retain_rejected_response
from .parser_provenance import check_result_identity, execution_outcome, verified_observation_recorder
from .source_settings import SourceAccessBlocked, assert_source_access, assert_source_run_access

CONSENT_TTL = timedelta(minutes=5)
EVIDENCE_METADATA = {"evidence_spans", "source_updated_at", "source_start_date", "source_end_date"}


def business_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Keep parser locators and catalog timestamps on snapshots, outside parameter diff."""
    return {key: value for key, value in facts.items() if key not in EVIDENCE_METADATA}


def timestamp(value: Any) -> str | None:
    return utc(value).isoformat() if value is not None else None


def provenance(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.id,
        "source_id": snapshot.source_id,
        "source_url": snapshot.source_url,
        "parser_version": snapshot.parser_version,
        "parser_identity": snapshot.parser_identity,
        "observed_at": timestamp(snapshot.observed_at),
        "raw_hash": snapshot.raw_hash,
    }


class QueryService:
    def __init__(self, db: Session, registry: Any, *, ingestion_guard: Callable[[Session], None] | None = None):
        self.db = db
        self.registry = registry
        self.ingestion_guard = ingestion_guard

    def audit(self, session_id: str, action: str, query_id: str | None = None,
              consent_id: str | None = None, **detail: Any) -> None:
        self.db.add(AuditEvent(session_id=session_id, action=action, query_id=query_id,
                               consent_id=consent_id, detail=detail))

    def require_source(self, source_id: str) -> None:
        if source_id not in {source["id"] for source in self.registry.sources()}:
            raise HTTPException(404, "未知来源")

    def pin_source_access(self, run: QueryRun) -> None:
        """Admit one online operation without holding a transaction over I/O."""
        self.lock_ingestion()
        if self.ingestion_guard is not None:
            self.ingestion_guard(self.db)
        run.source_access_generation = assert_source_access(self.db, run.source_id, registry=self.registry)
        self.db.commit()

    def assert_source_access(self, run: QueryRun) -> None:
        """Caller owns the ingestion lock; this check never commits."""
        assert_source_run_access(self.db, run, registry=self.registry)

    def block_source_access(self, run: QueryRun, error: SourceAccessBlocked) -> None:
        # The raw journal committed independently before parsing. Roll back any
        # attempted adoption, and expose neither cached facts nor a fallback offer.
        self.db.rollback()
        run.state, run.reason = 'source_unavailable', error.code
        self.audit(run.session_id, 'source_access_blocked', run.id,
                   source_id=run.source_id, reason=error.code)
        self.db.commit()

    def transport_cache(self, source_id: str, query_key: str) -> dict[str, Any] | None:
        # Deliberately select transport columns only. parsed_variants and fact_versions
        # must not be read to answer a failed ordinary query before consent.
        row = self.db.execute(
            select(Snapshot.id, Snapshot.source_url, Snapshot.body, Snapshot.raw_hash,
                   Snapshot.content_type, Verification.etag, Verification.last_modified, Snapshot.parser_version,
                   Verification.parser_identity, Snapshot.identity_contract_version)
            .join(Verification, Verification.snapshot_id == Snapshot.id)
            .where(Verification.source_id == source_id, Verification.query_key == query_key)
            .order_by(desc(Verification.verified_at)).limit(1)
        ).first()
        if row is None or row.identity_contract_version != schema_version():
            return None
        return {"snapshot_id": row.id, "url": row.source_url, "body": row.body,
                "raw_hash": row.raw_hash, "content_type": row.content_type,
                "etag": row.etag, "last_modified": row.last_modified,
                "parser_version": row.parser_version, "parser_identity": row.parser_identity,
                "identity_contract_version": row.identity_contract_version}

    def create_consent(self, request: ConsentRequest, session_id: str) -> dict[str, Any]:
        self.lock_ingestion()
        run = self.db.get(QueryRun, request.query_id)
        if not run or run.session_id != session_id:
            raise HTTPException(404, "当前会话不存在此查询")
        self.assert_source_access(run)
        if run.state != "consent_required" or run.fallback_policy != "ask":
            raise HTTPException(409, "该查询不处于等待离线授权状态")
        if utc(run.created_at) + CONSENT_TTL <= utcnow():
            raise HTTPException(410, "查询授权窗口已过期，请重新发起在线查询")
        existing = self.db.scalar(select(FallbackConsent).where(FallbackConsent.query_id == run.id))
        if existing:
            raise HTTPException(409, "该查询已作出授权决定")
        consent = FallbackConsent(id=uid(), query_id=run.id, session_id=session_id,
                                  decision=request.decision, scope=request.scope,
                                  expires_at=utc(run.created_at) + CONSENT_TTL)
        self.db.add(consent)
        self.audit(session_id, f"fallback_{request.decision}", run.id, consent.id)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(409, "该查询已作出授权决定") from None
        return {"id": consent.id, "decision": consent.decision,
                "scope": consent.scope, "expires_at": timestamp(consent.expires_at)}

    async def execute(self, source_id: str, request: LiveQueryRequest, session_id: str, *,
                      audience: str = 'internal') -> dict[str, Any]:
        from .telemetry import observe
        source = source_id if source_id in {
            'michelin-us', 'michelin-cn', 'michelin-uk', 'michelin-fr', 'michelin-de',
            'toyo-us', 'hankook-us', 'pirelli-us'} else 'unknown'
        with observe('source.query', component='crawler', source=source) as operation:
            result = await self._execute(source_id, request, session_id, audience=audience)
            operation.finish(result['data_state'])
            return result

    async def _execute(self, source_id: str, request: LiveQueryRequest, session_id: str, *,
                       audience: str = 'internal') -> dict[str, Any]:
        self.require_source(source_id)
        query = request.query.canonical()
        query_key = digest(query)
        if request.consent_id:
            return self.consume_consent(source_id, request, session_id, query_key, audience=audience)

        run = QueryRun(id=uid(), session_id=session_id, source_id=source_id,
                       query_key=query_key, query=query, fallback_policy=request.fallback_policy,
                       selection_filters=canonical_filters(request.filters))
        self.db.add(run)
        self.audit(session_id, "online_query_started", run.id, source_id=source_id)
        self.db.commit()
        try:
            self.pin_source_access(run)
        except SourceAccessBlocked as error:
            self.block_source_access(run, error)
            return self.result(run)
        from .parser_releases import (ParserDeploymentError, pin_selection,
                                      record_execution)
        selection = None
        cached = self.transport_cache(source_id, query_key)
        # Network I/O must not keep a SQLite read transaction open while a worker
        # commits newer observations; a later lock upgrade would otherwise fail.
        self.db.commit()
        try:
            kwargs = {}
            recorder = before_parse_recorder(self.db, run)
            if (getattr(self.registry, 'supports_parser_deployments', False) is True
                    and any(row['id'] == source_id and row['status'] == 'ready' for row in self.registry.sources())):
                selection = pin_selection(self.db, run.id, source_id)
                kwargs['parser_selection'] = selection
                recorder = verified_observation_recorder(recorder, selection)
            result = await self.registry.fetch(source_id, query, cached=cached,
                                               on_observation=recorder, **kwargs)
        except ParserDeploymentError as error:
            self.db.rollback()
            result = {"status": "unavailable", "reason": error.code}
        except Exception:
            # Do not return exception strings: transport errors can contain credentials
            # or internal network details. Server logs can be added without raw payloads.
            result = {"status": "unavailable", "reason": "source_fetch_failed"}
        if selection is not None:
            try:
                record_execution(self.db, run.id, execution_outcome(result))
            except ParserDeploymentError as error:
                if not error.execution_recorded:
                    self.db.rollback()
                result = {"status": "unavailable", "reason": error.code}
            self.db.commit()
        if result.get("status") == "not_modified":
            if self.valid_304(cached, result, require_identity=selection is not None):
                snapshot = self.db.get(Snapshot, cached["snapshot_id"])
                assert snapshot is not None
                variants = [VariantInput.model_validate({key: value for key, value in row.items()
                            if key in VariantInput.model_fields}) for row in snapshot.parsed_variants]
                try:
                    snapshot, verified_at, current_variants = self.record_success(run, {
                        "body": snapshot.body, "url": snapshot.source_url,
                        "content_type": snapshot.content_type, "parser_version": snapshot.parser_version,
                        "parser_identity": result.get('parser_identity'),
                        "etag": cached.get("etag"), "last_modified": cached.get("last_modified"),
                    }, variants, verification_status="not_modified", parser_selection=selection)
                except SourceAccessBlocked as error:
                    self.block_source_access(run, error)
                    return self.result(run)
                except IdentityContractError as error:
                    self.db.rollback()
                    result = {"status": "unavailable", "reason": error.code}
                except ParserDeploymentError as error:
                    result = {"status": "unavailable", "reason": error.code}
                except SourceQualityQuarantined:
                    result = {"status": "unavailable", "reason": QUALITY_REASON}
                else:
                    run.state = "live_verified_304"
                    self.audit(session_id, "online_verified_304", run.id, snapshot_id=snapshot.id)
                    self.db.commit()
                    return self.result(run, snapshot, verified_at=verified_at, current_variants=current_variants)
            else:
                result = {"status": "unavailable", "reason": "invalid_304_without_matching_evidence"}

        if result.get("status") == "ok":
            try:
                variants = self.validate_result(result, query)
            except (ValidationError, ValueError, TypeError, KeyError):
                retain_rejected_response(self.db, run, result, "schema")
                result = {"status": "unavailable", "reason": "source_schema_validation_failed"}
            else:
                try:
                    snapshot, verified_at, current_variants = self.record_success(run, result, variants,
                                                                                 parser_selection=selection)
                except SourceAccessBlocked as error:
                    self.block_source_access(run, error)
                    return self.result(run)
                except IdentityContractError as error:
                    self.db.rollback()
                    result = {"status": "unavailable", "reason": error.code}
                except ParserDeploymentError as error:
                    result = {"status": "unavailable", "reason": error.code}
                except SourceQualityQuarantined:
                    result = {"status": "unavailable", "reason": QUALITY_REASON}
                else:
                    run.state = "live"
                    self.audit(session_id, "online_query_succeeded", run.id, snapshot_id=snapshot.id,
                               variants=len(variants))
                    self.db.commit()
                    return self.result(run, snapshot, verified_at=verified_at, current_variants=current_variants)

        if result.get("rejected_observation") is not None:
            retain_rejected_response(self.db, run, result["rejected_observation"], "parser")
        self.lock_ingestion()
        try:
            self.assert_source_access(run)
        except SourceAccessBlocked as error:
            self.block_source_access(run, error)
            return self.result(run)
        run.state = "consent_required" if request.fallback_policy == "ask" else "source_unavailable"
        run.reason = str(result.get("reason") or "source_unavailable")[:200]
        self.audit(session_id, "online_query_failed", run.id, reason=run.reason,
                   fallback_policy=request.fallback_policy)
        self.db.commit()
        from .query_fallback_policies import claim_policy_use, authorized_result
        use = claim_policy_use(self.db, self.registry, run, 'tire', audience)
        if use is not None:
            snapshot = self.db.scalar(select(Snapshot).join(Verification, Verification.snapshot_id == Snapshot.id)
                .where(Verification.source_id == source_id, Verification.query_key == query_key)
                .order_by(desc(Verification.verified_at)).limit(1))
            self.audit(session_id, 'policy_local_snapshot_read', run.id, use_id=use.id,
                       snapshot_id=snapshot.id if snapshot else None)
            return authorized_result(self.db, self.registry, run, use, self.result(run, snapshot))
        return self.result(run)

    @staticmethod
    def valid_304(cached: dict[str, Any] | None, result: dict[str, Any], *, require_identity=False,
                  require_tire_identity_contract=True) -> bool:
        if (not cached or (require_tire_identity_contract and cached.get("identity_contract_version") != schema_version())
                or not cached["body"] or not (cached.get("etag") or cached.get("last_modified"))):
            return False
        if result.get("url") != cached["url"]:
            return False
        if hashlib.sha256(cached["body"].encode("utf-8")).hexdigest() != cached["raw_hash"]:
            return False
        if result.get("parser_version") and result["parser_version"] != cached["parser_version"]:
            return False
        from .parser_provenance import parser_identity
        identity = parser_identity(result.get('parser_identity'))
        if (require_identity or cached.get('parser_identity') is not None or result.get('parser_identity') is not None):
            if identity is None or identity != parser_identity(cached.get('parser_identity')):
                return False
        if result.get("etag") and cached.get("etag") and result["etag"] != cached["etag"]:
            return False
        if result.get("last_modified") and cached.get("last_modified") and result["last_modified"] != cached["last_modified"]:
            return False
        return True

    @staticmethod
    def validate_result(result: dict[str, Any], query: dict[str, str]) -> list[VariantInput]:
        if not isinstance(result.get("body"), str) or not result["body"]:
            raise ValueError("缺少原始证据")
        if len(result["body"].encode("utf-8")) > 8 * 1024 * 1024:
            raise ValueError("原始证据过大")
        if not isinstance(result.get("url"), str) or not result["url"].startswith("https://"):
            raise ValueError("缺少 HTTPS 来源")
        if not result.get("parser_version") or not result.get("content_type"):
            raise ValueError("缺少解析器版本或内容类型")
        raw_variants = result.get("variants")
        if not isinstance(raw_variants, list) or len(raw_variants) > 500:
            raise ValueError("无效轮胎版本集合")
        variants = [VariantInput.model_validate(value) for value in raw_variants]
        identified: dict[str, dict[str, Any]] = {}
        for variant in variants:
            # R/ZR remain part of identity, while the dimension search may return both.
            if query.get("size") and variant.size.replace("ZR", "R") != query["size"].replace("ZR", "R"):
                raise ValueError("来源记录尺寸与查询不匹配")
            if query.get("model") and query["model"].casefold() not in variant.model.casefold():
                raise ValueError("来源记录型号与查询不匹配")
            if variant.manufacturer_product_code and variant.identity().get("product_code_type") is not None:
                key = digest(variant.identity())
                if key in identified and identified[key] != variant.facts:
                    raise ValueError("来源内相同精确版本包含冲突事实")
                identified[key] = variant.facts
        return variants

    def record_success(self, run: QueryRun, result: dict[str, Any],
                       variants: list[VariantInput], verification_status: str = "ok", *,
                       parser_selection: dict | None = None) -> tuple[Snapshot, Any, list[dict[str, Any]]]:
        self.lock_ingestion()
        self.assert_source_access(run)
        if self.ingestion_guard is not None:
            self.ingestion_guard(self.db)
        if parser_selection is not None:
            from .parser_releases import assert_selection_current
            assert_selection_current(self.db, parser_selection)
            check_result_identity(parser_selection, result)
        raw_hash = hashlib.sha256(result["body"].encode("utf-8")).hexdigest()
        verified_at = utcnow()
        snapshot = self.db.scalar(select(Snapshot).join(Verification, Verification.snapshot_id == Snapshot.id)
                                  .where(Verification.source_id == run.source_id,
                                         Verification.query_key == run.query_key)
                                  .order_by(desc(Verification.verified_at)).limit(1))
        candidates = [variant.model_dump() for variant in variants]
        quality = assess_quality(snapshot.parsed_variants if snapshot else None, candidates)
        applied_review = None
        if quality["reason_codes"] and snapshot is not None and verification_status == 'ok':
            from .quarantine_review import consume_approval
            applied_review = consume_approval(self.db, run, 'tire', snapshot, result, candidates, quality)
        if quality["reason_codes"] and not applied_review:
            assert snapshot is not None
            quarantine = SourceQuarantine(id=uid(), query_id=run.id, source_id=run.source_id,
                                          query_key=run.query_key, previous_snapshot_id=snapshot.id,
                                          source_url=result["url"], raw_hash=raw_hash, body=result["body"],
                                          content_type=result["content_type"], parser_version=result["parser_version"],
                                          parser_identity=result.get('parser_identity'),
                                          observed_at=verified_at, candidates=candidates, quality=quality)
            self.db.add(quarantine)
            self.audit(run.session_id, "source_quality_quarantined", run.id, quarantine_id=quarantine.id,
                       previous_snapshot_id=snapshot.id, reason_codes=quality["reason_codes"], metrics=metrics(quality))
            # No accepted snapshot, variant, fact, change or verification has been
            # written. The caller commits only this rejection plus query/audit state.
            raise SourceQualityQuarantined()
        if snapshot and (snapshot.identity_contract_version != schema_version() or applied_review or snapshot.raw_hash != raw_hash or snapshot.parser_version != result["parser_version"]
                         or snapshot.parser_identity != result.get('parser_identity')
                         or snapshot.source_url != result["url"]):
            snapshot = None
        is_new_snapshot = snapshot is None
        if is_new_snapshot:
            snapshot = Snapshot(id=uid(), source_id=run.source_id, query_key=run.query_key,
                                source_url=result["url"], raw_hash=raw_hash, body=result["body"],
                                content_type=result["content_type"], parser_version=result["parser_version"],
                                parser_identity=result.get('parser_identity'), identity_contract_version=schema_version(),
                                observed_at=verified_at, etag=result.get("etag"),
                                last_modified=result.get("last_modified"), parsed_variants=[])
        # Raw snapshot reuse and current facts are separate concerns. Another query
        # may have changed this SKU since this query's cached snapshot was observed.
        # Reconcile even on a verified 304, preserving the original raw timestamp.
        assert snapshot is not None
        pending_facts: list[FactVersion | ChangeEvent] = []
        parsed: list[dict[str, Any]] = []
        seen: set[str] = set()
        identity_context = {}
        for index, variant in enumerate(variants):
            identity_key, identity_status = variant.identity_key(run.source_id, run.query_key, index)
            if identity_key in seen:
                previous_row = next(row for row in parsed if row["identity_key"] == identity_key)
                if previous_row["facts"] != variant.facts:
                    raise HTTPException(502, "来源同时返回同一版本的冲突参数，需要解析器审查")
                continue
            seen.add(identity_key)
            stored, identity_key, identity_status = resolve_variant(
                self.db, variant, run.source_id, run.query_key, index, snapshot.id, context=identity_context)
            previous = self.db.scalar(select(FactVersion).where(
                FactVersion.variant_id == stored.id, FactVersion.source_id == run.source_id,
            ).order_by(desc(FactVersion.version)).limit(1))
            facts = business_facts(variant.facts)
            facts_hash = digest(facts)
            version = previous.version if previous else 0
            if previous is None or previous.facts_hash != facts_hash:
                version += 1
                pending_facts.append(FactVersion(variant_id=stored.id, source_id=run.source_id,
                                                 snapshot_id=snapshot.id, facts=facts,
                                                 facts_hash=facts_hash, version=version,
                                                 observed_at=verified_at))
                changes = {key: {"before": previous.facts.get(key) if previous else None,
                                 "after": facts.get(key),
                                 "before_present": key in previous.facts if previous else False,
                                 "after_present": key in facts}
                           for key in sorted(set(facts) | (set(previous.facts) if previous else set()))
                           if not previous or (key in previous.facts) != (key in facts)
                           or previous.facts.get(key) != facts.get(key)}
                pending_facts.append(ChangeEvent(variant_id=stored.id, source_id=run.source_id,
                                                 snapshot_id=snapshot.id,
                                                 previous_snapshot_id=previous.snapshot_id if previous else None,
                                                 kind="facts_changed" if previous else "variant_observed",
                                                 changes=changes, observed_at=verified_at))
            parsed.append({**variant.model_dump(), "id": stored.id, "identity_key": identity_key,
                           "identity_status": identity_status, "identity_contract_version": schema_version(), "fact_version": version,
                           "snapshot_id": snapshot.id})
        if is_new_snapshot:
            snapshot.parsed_variants = parsed
            self.db.add(snapshot)
            self.db.flush()
        self.db.add_all(pending_facts)
        self.db.flush()
        from .monitoring import record_alerts
        record_alerts(self.db, [item for item in pending_facts if isinstance(item, ChangeEvent)])
        self.db.add(Verification(snapshot_id=snapshot.id, query_id=run.id,
                                 source_id=run.source_id, query_key=run.query_key,
                                 status=verification_status, verified_at=verified_at,
                                 parser_identity=result.get('parser_identity'),
                                 etag=result.get("etag"), last_modified=result.get("last_modified")))
        return snapshot, verified_at, parsed

    def lock_ingestion(self) -> None:
        """Serialize the short revision write across API and worker processes."""
        from .telemetry import observe
        with observe('db.ingestion_lock', component='database'):
            self._lock_ingestion()

    def _lock_ingestion(self) -> None:
        self.db.commit()
        dialect = self.db.get_bind().dialect.name
        if dialect == "sqlite":
            self.db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        elif dialect == "postgresql":
            # All source identities can converge on the same complete SKU. One
            # transaction lock avoids cross-source insert and version races in PoC.
            self.db.connection().exec_driver_sql("SELECT pg_advisory_xact_lock(821741905)")

    def consume_consent(self, source_id: str, request: LiveQueryRequest,
                        session_id: str, query_key: str, *, audience: str = 'internal') -> dict[str, Any]:
        self.lock_ingestion()
        consent = self.db.get(FallbackConsent, request.consent_id)
        if not consent or consent.session_id != session_id:
            raise HTTPException(403, "离线授权不属于当前会话")
        run = self.db.get(QueryRun, consent.query_id)
        if (not run or run.source_id != source_id or run.query_key != query_key or request.fallback_policy != "ask"
                or (run.selection_filters or []) != canonical_filters(request.filters)):
            raise HTTPException(403, "离线授权的来源、查询、筛选条件或策略不匹配")
        try:
            self.assert_source_access(run)
        except SourceAccessBlocked as error:
            self.block_source_access(run, error)
            return self.result(run)
        if consent.decision != "allow":
            raise HTTPException(403, "此查询已拒绝使用本地快照")
        if utc(consent.expires_at) <= utcnow():
            raise HTTPException(410, "离线授权已过期")
        from .query_fallback_policies import assert_once_policy
        assert_once_policy(self.db, self.registry, run, 'tire', audience)
        consumed_at = utcnow()
        claimed = self.db.execute(update(FallbackConsent).where(
            FallbackConsent.id == consent.id, FallbackConsent.used_at.is_(None),
            FallbackConsent.expires_at > consumed_at, FallbackConsent.decision == "allow",
            FallbackConsent.scope == "once", FallbackConsent.session_id == session_id,
        ).values(used_at=consumed_at).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            raise HTTPException(409, "离线授权已经使用")
        # The first actual read of local answer data is after this atomic claim.
        snapshot = self.db.scalar(select(Snapshot).join(Verification, Verification.snapshot_id == Snapshot.id)
                                  .where(Verification.source_id == source_id, Verification.query_key == query_key)
                                  .order_by(desc(Verification.verified_at)).limit(1))
        run.state = "local_snapshot"
        self.audit(session_id, "local_snapshot_read", run.id, consent.id,
                   snapshot_id=snapshot.id if snapshot else None)
        self.db.commit()
        assert_once_policy(self.db, self.registry, run, 'tire', audience)
        result = self.result(run, snapshot, consent_id=consent.id)
        if audience == 'programmatic':
            self.db.commit()
        return result

    def result(self, run: QueryRun, snapshot: Snapshot | None = None,
               verified_at: Any = None, consent_id: str | None = None,
               current_variants: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if snapshot and verified_at is None:
            verified_at = self.db.scalar(select(Verification.verified_at)
                                         .where(Verification.snapshot_id == snapshot.id)
                                         .order_by(desc(Verification.verified_at)).limit(1))
        from .lifecycle import annotate_variants
        selected, selection = select_variants(
            (current_variants if current_variants is not None else snapshot.parsed_variants) if snapshot else None,
            run.selection_filters)
        visible_variants = annotate_variants(self.db, selected)
        if snapshot:
            from .field_authority import resolve_fields
            from .field_evidence import snapshot_field_candidates
            from .identity_contract import contract_context
            context = {'contracts': contract_context(self.db, [row['id'] for row in visible_variants])}
            for row in visible_variants:
                candidates = snapshot_field_candidates(self.db, snapshot.id, row['id'], self.registry,
                    row=row, verified_at=verified_at, context=context)
                row['field_resolution'] = resolve_fields(candidates, variant_id=row['id'],
                    scope='current_source', data_state=run.state)
        return {"query_id": run.id, "source_id": run.source_id, "data_state": run.state,
                "reason": run.reason if snapshot or run.state != "local_snapshot" else "no_matching_local_snapshot",
                "verified_at": timestamp(verified_at),
                "snapshot_observed_at": timestamp(snapshot.observed_at) if snapshot else None,
                "snapshot_age_seconds": max(0, int((utcnow() - utc(snapshot.observed_at)).total_seconds())) if snapshot else None,
                "consent_id": consent_id,
                "variants": visible_variants, "selection": selection,
                "provenance": [provenance(snapshot)] if snapshot else [],
                # A live/single-source consent cannot authorize other sources' history.
                # Cross-source conflicts belong to the explicit historical comparison.
                "conflicts": self.current_source_conflicts(selected, run.source_id)
                    if snapshot else []}

    @staticmethod
    def current_source_conflicts(variants: list[dict[str, Any]], source_id: str) -> list[dict[str, Any]]:
        """Surface contradictions in this exact observed page, never historical lookups."""
        results = []
        for variant in variants:
            conflicts = variant.get("facts", {}).get("source_field_conflicts", [])
            if not isinstance(conflicts, list):
                continue
            for conflict in conflicts[:50]:
                if isinstance(conflict, dict) and isinstance(conflict.get("field"), str):
                    results.append({**conflict, "variant_id": variant["id"], "source_id": source_id,
                                    "snapshot_id": variant["snapshot_id"], "scope": "same_source_snapshot"})
        return results

    def conflicts(self, variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from .field_evidence import resolution_conflicts, variant_field_resolution
        return resolution_conflicts([row.get('field_resolution') or
            variant_field_resolution(self.db, self.registry, row['id']) for row in variants])

    def historical_variant(self, variant_id: str) -> dict[str, Any]:
        from .lifecycle import annotate_variants
        variant = self.db.get(TireVariant, variant_id)
        if not variant:
            raise HTTPException(404, "未找到轮胎版本")
        revisions = self.db.scalars(select(FactVersion).where(FactVersion.variant_id == variant_id)
                                    .order_by(desc(FactVersion.observed_at))).all()
        latest = revisions[0] if revisions else None
        recorded_contract = self.db.scalar(select(Snapshot.identity_contract_version).where(
            Snapshot.id == latest.snapshot_id)) if latest else None
        return annotate_variants(self.db, [{"id": variant.id, **variant.identity, "identity_status": variant.identity_status,
                "identity_contract_version": recorded_contract,
                "source_id": latest.source_id if latest else None,
                "facts": latest.facts if latest else {}, "fact_version": latest.version if latest else None,
                "snapshot_id": latest.snapshot_id if latest else None,
                "observed_at": timestamp(latest.observed_at) if latest else None,
                "data_state": "local_snapshot",
                "versions": [{"id": row.id, "version": row.version, "source_id": row.source_id,
                              "snapshot_id": row.snapshot_id, "observed_at": timestamp(row.observed_at),
                              "facts": row.facts} for row in revisions]}])[0]
