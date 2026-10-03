"""Local, single-user PoC API. Bind to loopback; production identity is not implemented."""

from __future__ import annotations

import asyncio
import os
import re
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .db import ChangeEvent, Database, Snapshot, UserSession, Verification, WatchItem, utc, utcnow, uid
from .domain import CompareRequest, ConsentRequest, LiveQueryRequest, WatchRequest, digest
from .service import QueryService, provenance, timestamp
from .telemetry import TelemetryRuntime, observe

SESSION_COOKIE = "tire_local_session"
SESSION_TTL = timedelta(days=14)
DEFAULT_DATABASE = "sqlite:///" + (Path(__file__).resolve().parents[3] / "data" / "dev.db").as_posix()
OBSERVABILITY_PATHS = frozenset({"/v1/observability", "/v1/observability/metrics"})
OFFLINE_SYNC_OWNER_HEADER = "X-Tire-Offline-Owner-Scope"


def offline_sync_route(request: Request) -> bool:
    path, method = request.url.path, request.method
    if method == "POST":
        return path in {"/v1/offline-pack-updates:prepare", "/v1/offline-packs"}
    return (method == "GET" and re.fullmatch(r"/v1/offline-packs/[^/]+(?:/download)?", path) is not None
            and request.query_params.getlist("mode") == ["history"])


def offline_sync_error(status, code, owner_scope=None):
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if owner_scope is not None:
        headers[OFFLINE_SYNC_OWNER_HEADER] = owner_scope
    return JSONResponse(status_code=status, content={"detail": {"code": code}}, headers=headers)


class RequestTelemetryMiddleware:
    """Measure completed HTTP requests without recording request-controlled content."""

    def __init__(self, app: ASGIApp, runtime: TelemetryRuntime):
        self.app, self.runtime = app, runtime

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").rstrip("/") in OBSERVABILITY_PATHS:
            await self.app(scope, receive, send)
            return
        status = 500
        started = False

        async def record_status(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                status, started = message["status"], True
            await send(message)

        with self.runtime.scope(), observe("api.request", component="api") as span:
            outcome = "error"
            try:
                await self.app(scope, receive, record_status)
                outcome = "success" if status < 400 else "rejected" if status < 500 else "error"
            except asyncio.CancelledError:
                outcome = "cancelled"
                if not started:
                    status = 499
                raise
            finally:
                # The router supplies a registered template. Never use path/query fallback.
                route = getattr(scope.get("route"), "path", "unknown")
                span.finish(outcome, http_status=status, route=route)


def allowed_origins() -> list[str]:
    origins = os.getenv("TIRE_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    result = []
    for origin in origins:
        origin = origin.strip().rstrip("/")
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("本地 PoC 的 CORS 只能配置 loopback origin")
        if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("CORS origin 不得包含路径或身份信息")
        result.append(origin)
    return result


def create_app(database_url: str | None = None, adapter_registry: Any = None) -> FastAPI:
    if adapter_registry is None:
        from .adapters import registry
        adapter_registry = registry
    database = Database(database_url or os.getenv("TIRE_DATABASE_URL") or os.getenv("DATABASE_URL") or DEFAULT_DATABASE)
    origins = allowed_origins()
    telemetry = TelemetryRuntime.from_env("tire-api")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            database.initialize()
            from .ai_streaming import AIStreamSupervisor
            app.state.ai_stream_supervisor = AIStreamSupervisor(database, app.state.ai_adapter)
            yield
        finally:
            try:
                supervisor = getattr(app.state, 'ai_stream_supervisor', None)
                if supervisor is not None:
                    await supervisor.shutdown()
            finally:
                try:
                    database.close()
                finally:
                    telemetry.shutdown()

    app = FastAPI(title="轮胎证据工作台 API", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, error: RequestValidationError) -> JSONResponse:
        # Do not echo rejected bodies: non-finite JSON values also cannot be
        # serialized by the default handler, turning a client error into a 500.
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
            for item in error.errors()[:20]]})
    app.state.database = database
    app.state.registry = adapter_registry
    app.state.telemetry = telemetry
    from .auth import register_auth_routes
    register_auth_routes(app)
    from .source_settings import register_source_setting_routes
    register_source_setting_routes(app)
    from .vehicles import register_vehicle_routes
    register_vehicle_routes(app)
    from .recalls import register_recall_routes
    register_recall_routes(app)
    from .recall_discovery import register_recall_discovery_routes
    register_recall_discovery_routes(app)
    from .recall_discovery_monitor_routes import register_recall_discovery_monitor_routes
    register_recall_discovery_monitor_routes(app)
    from .recall_monitoring import register_recall_monitoring_routes
    register_recall_monitoring_routes(app)
    from .quality import register_quality_routes
    register_quality_routes(app)
    from .curation import register_curation_routes
    register_curation_routes(app)
    from .field_reviews import register_field_routes
    register_field_routes(app)
    from .captures import register_capture_routes
    register_capture_routes(app)
    from .reparse import register_reparse_routes
    register_reparse_routes(app)
    from .parser_releases import register_parser_release_routes
    register_parser_release_routes(app)
    from .golden import register_golden_routes
    register_golden_routes(app)
    from .identity_contract import register_identity_contract_routes
    register_identity_contract_routes(app)
    from .lifecycle import register_lifecycle_routes
    register_lifecycle_routes(app)
    from .identity_resolution import register_identity_routes
    register_identity_routes(app)
    from .fitment_relations import register_fitment_relation_routes
    register_fitment_relation_routes(app)
    from .garage import register_garage_routes
    register_garage_routes(app)
    from .research import register_research_routes
    register_research_routes(app)
    from .monitoring import register_monitoring_routes
    register_monitoring_routes(app)
    from .monitor_tasks import register_monitor_task_routes
    register_monitor_task_routes(app)
    from .documents import register_document_routes
    register_document_routes(app)
    from .quarantine_review import register_review_routes
    register_review_routes(app)
    from .test_events import register_test_event_routes
    register_test_event_routes(app)
    from .ai_analysis import register_ai_routes
    register_ai_routes(app)
    from .ai_stream_routes import register_ai_stream_routes
    register_ai_stream_routes(app)
    from .ai_rule_drafts import register_rule_draft_routes
    register_rule_draft_routes(app)
    from .device_ai_routes import register_device_ai_routes
    register_device_ai_routes(app)
    from .reports import register_report_routes
    register_report_routes(app)
    from .knowledge import register_knowledge_routes
    register_knowledge_routes(app)
    from .embedding_api import register_embedding_routes
    register_embedding_routes(app)
    from .offline_packs import register_offline_routes
    register_offline_routes(app)
    from .query_fallback_policies import register_query_fallback_routes
    register_query_fallback_routes(app)

    @app.middleware("http")
    async def local_session(request: Request, call_next: Any) -> Response:
        if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse(status_code=403, content={"detail": "当前 PoC 仅允许本机访问"})
        origin = request.headers.get("origin")
        same_origin = str(request.base_url).rstrip("/")
        if origin and origin not in origins and origin != same_origin:
            return JSONResponse(status_code=403, content={"detail": "不允许此请求来源"})
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(status_code=403, content={"detail": "不允许跨站请求"})
        sync_markers = request.headers.getlist("x-tire-offline-sync")
        expected_owners = request.headers.getlist("x-tire-offline-expected-owner")
        offline_sync = bool(sync_markers or expected_owners)
        fallback_metadata = request.url.path.startswith('/v1/query-fallback-policies')
        source_metadata = request.method == 'GET' and request.url.path.rstrip('/') == '/v1/source-settings'
        if offline_sync:
            if (sync_markers != ["1"] or len(expected_owners) != 1
                    or re.fullmatch(r"[0-9a-f]{64}", expected_owners[0]) is None):
                return offline_sync_error(422, "offline_sync_headers_invalid")
            if not offline_sync_route(request):
                return offline_sync_error(400, "offline_sync_route_invalid")
        if request.url.path.rstrip("/") in OBSERVABILITY_PATHS:
            # Process diagnostics must not bootstrap a business session or touch the DB.
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        new_session = False
        owner_scope = None
        with database.sessions() as db:
            cookie = request.cookies.get(SESSION_COOKIE)
            session = db.get(UserSession, cookie) if cookie and len(cookie) <= 64 else None
            if not session or utc(session.expires_at) <= utcnow():
                if offline_sync or fallback_metadata:
                    return offline_sync_error(401, "offline_sync_session_required" if offline_sync else
                                               "query_fallback_session_required")
                session = UserSession(id=uid(), expires_at=utcnow() + SESSION_TTL)
                db.add(session)
                db.commit()
                new_session = True
            if offline_sync:
                owner_scope = digest({'namespace': 'offline-owner-scope@1', 'session': session.id})
                if expected_owners[0] != owner_scope:
                    return offline_sync_error(409, "offline_sync_owner_mismatch", owner_scope)
            elif source_metadata:
                owner_scope = digest({'namespace': 'offline-owner-scope@1', 'session': session.id})
            request.state.session_id = session.id
        response = await call_next(request)
        if offline_sync:
            response.headers[OFFLINE_SYNC_OWNER_HEADER] = owner_scope
        elif source_metadata and 200 <= response.status_code < 300:
            response.headers[OFFLINE_SYNC_OWNER_HEADER] = owner_scope
        if new_session:
            response.set_cookie(SESSION_COOKIE, request.state.session_id, httponly=True,
                                samesite="strict", secure=request.url.scheme == "https",
                                max_age=int(SESSION_TTL.total_seconds()))
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Content-Type", "Idempotency-Key", "X-Tire-Offline-Sync",
                                      "X-Tire-Offline-Expected-Owner"],
                       expose_headers=[OFFLINE_SYNC_OWNER_HEADER])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
    app.add_middleware(RequestTelemetryMiddleware, runtime=telemetry)

    def get_db():
        with database.sessions() as db:
            yield db

    # Session dependencies are explicit defaults because local closure aliases are not
    # resolved by postponed annotations in FastAPI's signature introspection.
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "local_single_user_poc", "database": database.backend}

    @app.get("/v1/observability")
    def observability() -> dict[str, Any]:
        return telemetry.status()

    @app.get("/v1/observability/metrics")
    def observability_metrics() -> Response:
        return Response(content=telemetry.metrics(), media_type="text/plain; version=0.0.4; charset=utf-8",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.get("/v1/sources")
    def sources(db: Session = Depends(get_db)) -> dict[str, Any]:
        values = adapter_registry.sources()
        if getattr(adapter_registry, 'supports_parser_deployments', False) is True:
            from .parser_releases import current_deployment
            for index, value in enumerate(values):
                selected = current_deployment(db, value['id'])
                if selected:
                    values[index] = {**value, 'installed_parser_version': value.get('parser_version'),
                        'parser_version': selected.descriptor['parser_version'],
                        'parser_deployment': {'revision': selected.revision, 'state': selected.state,
                            'bundle_id': selected.bundle_id, 'parser_digest': selected.descriptor['parser_digest']}}
        from .source_settings import source_setting
        values = [{**value, 'status': setting['effective_status'], 'source_setting': setting}
                  for value in values
                  for setting in [source_setting(db, value['id'], registry=adapter_registry)]]
        return {"sources": values}

    @app.get("/v1/tire-query-filters")
    def tire_query_filters() -> dict[str, Any]:
        from .query_filters import catalog
        return catalog()

    @app.post("/v1/sources/{source_id}/live-query")
    async def live_query(source_id: str, payload: LiveQueryRequest, request: Request,
                         db: Session = Depends(get_db)) -> dict[str, Any]:
        return await QueryService(db, adapter_registry).execute(source_id, payload, request.state.session_id,
                                                              audience='programmatic')

    @app.post("/v1/fallback-consents", status_code=201)
    def consent(payload: ConsentRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
        return QueryService(db, adapter_registry).create_consent(payload, request.state.session_id)

    @app.get("/v1/evidence/{snapshot_id}")
    def evidence(snapshot_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
        snapshot = db.get(Snapshot, snapshot_id)
        if snapshot is None:
            raise HTTPException(404, "未找到证据快照")
        verified = db.scalar(select(Verification.verified_at).where(Verification.snapshot_id == snapshot.id)
                             .order_by(desc(Verification.verified_at)).limit(1))
        service = QueryService(db, adapter_registry)
        service.audit(request.state.session_id, "evidence_history_read", snapshot_id=snapshot.id)
        db.commit()
        from .quarantine_review import snapshot_review
        return {"id": snapshot.id, **provenance(snapshot), "verified_at": timestamp(verified),
                "content_type": snapshot.content_type, "body": snapshot.body,
                "quality_review": snapshot_review(db, snapshot.id),
                "data_state": "local_snapshot"}

    @app.get("/v1/tire-variants/{variant_id}")
    def variant_history(variant_id: str, request: Request,
                        mode: Literal["history"] = Query(...), db: Session = Depends(get_db)) -> dict[str, Any]:
        service = QueryService(db, adapter_registry)
        result = service.historical_variant(variant_id)
        service.audit(request.state.session_id, "variant_history_read", variant_id=variant_id)
        db.commit()
        return result

    @app.post("/v1/compare")
    def compare(payload: CompareRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
        service = QueryService(db, adapter_registry)
        from .research import comparison_view
        service.lock_ingestion()
        from .identity_contract import require_current_identity
        for variant_id in payload.variant_ids:
            require_current_identity(db, variant_id)
        result = comparison_view(db, payload, registry=adapter_registry)
        service.audit(request.state.session_id, "compare_history_read", variant_ids=payload.variant_ids,
                      include_manual=payload.include_manual, resolve_identities=payload.resolve_identities)
        db.commit()
        return result

    @app.get("/v1/watchlists")
    def watches(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
        from .auth import session_scope
        scope = session_scope(db, request.state.session_id)
        items = db.scalars(select(WatchItem).where(WatchItem.session_id.in_(scope))
                          .order_by(desc(WatchItem.created_at))).all()
        service = QueryService(db, adapter_registry)
        from .identity_contract import contract_metadata
        return {"data_state": "local_snapshot", "items": [
            {"identity_contract": contract_metadata(db, item.variant_id), "id": item.id, "variant_id": item.variant_id, "created_at": timestamp(item.created_at),
             "variant": service.historical_variant(item.variant_id)} for item in items],
            "monitoring_enabled": False}

    @app.post("/v1/watchlists", status_code=201)
    def add_watch(payload: WatchRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
        service = QueryService(db, adapter_registry)
        from .identity_contract import require_current_identity
        service.lock_ingestion()
        require_current_identity(db, payload.variant_id)
        variant = service.historical_variant(payload.variant_id)
        item = db.scalar(select(WatchItem).where(WatchItem.session_id == request.state.session_id,
                                                WatchItem.variant_id == payload.variant_id))
        if not item:
            item = WatchItem(session_id=request.state.session_id, variant_id=payload.variant_id)
            db.add(item)
            service.audit(request.state.session_id, "watch_added", variant_id=payload.variant_id)
            db.commit()
        return {"id": item.id, "variant_id": item.variant_id, "created_at": timestamp(item.created_at),
                "variant": variant, "monitoring_enabled": False}

    @app.delete("/v1/watchlists/{watch_id}", status_code=204)
    def remove_watch(watch_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
        from .auth import session_scope
        item = db.get(WatchItem, watch_id)
        if not item or item.session_id not in session_scope(db, request.state.session_id):
            raise HTTPException(404, "当前账户不存在此关注项")
        QueryService(db, adapter_registry).audit(request.state.session_id, "watch_removed", variant_id=item.variant_id)
        db.delete(item)
        db.commit()
        return Response(status_code=204)

    @app.get("/v1/changes")
    def changes(request: Request, limit: int = Query(default=50, ge=1, le=200),
                db: Session = Depends(get_db)) -> dict[str, Any]:
        from .auth import session_scope
        scope = session_scope(db, request.state.session_id)
        rows = db.scalars(select(ChangeEvent).join(WatchItem, WatchItem.variant_id == ChangeEvent.variant_id)
                          .where(WatchItem.session_id.in_(scope))
                          .order_by(desc(ChangeEvent.observed_at)).limit(limit)).all()
        from .identity_contract import contract_metadata
        return {"data_state": "local_snapshot", "items": [
            {"identity_contract": contract_metadata(db, row.variant_id), "id": row.id, "variant_id": row.variant_id, "source_id": row.source_id,
             "snapshot_id": row.snapshot_id, "previous_snapshot_id": row.previous_snapshot_id,
             "kind": row.kind, "changes": row.changes, "observed_at": timestamp(row.observed_at)}
            for row in rows], "monitoring_enabled": False}

    telemetry.set_routes(route.path for route in app.routes if hasattr(route, "path"))
    return app


app = create_app()
