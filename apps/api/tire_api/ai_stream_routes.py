"""Asynchronous acceptance; reconnectable readers never start or cancel providers."""
import asyncio
from copy import deepcopy
import time
from typing import Literal
from uuid import UUID

from fastapi import Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from .ai_analysis import AnalysisRequest, prepare_analysis
from .ai_execution import reserve_response
from .ai_gateway import analysis_contract
from .ai_models import AIRequest
from . import ai_stream_store as store
from .db import uid, utcnow
from .domain import digest
from .monitor_tasks import _frame
from .service import QueryService, timestamp

STREAM_SECONDS = 25.0
HEARTBEAT_SECONDS = 10.0
POLL_SECONDS = 1.0
MAX_STREAM_EVENTS = 500


def canonical_key(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, 'Idempotency-Key 必须是 UUID') from None


async def stream_events(database, request, request_id, session_id, after):
    started = heartbeat = time.monotonic()
    delivered = 0
    while time.monotonic() - started < STREAM_SECONDS and delivered < MAX_STREAM_EVENTS:
        if await request.is_disconnected():
            return

        def read_page():
            with database.sessions() as db:
                return store.event_page(db, request_id, session_id, after=after, limit=100)

        try:
            page = await asyncio.to_thread(read_page)
        except HTTPException as error:
            if error.status_code in (404, 409):
                yield _frame('reset', {'code': 'ai_stream_cursor_reset_required', 'server_time': timestamp(utcnow())})
                return
            raise
        for row in page['items']:
            after = row['cursor']
            delivered += 1
            yield _frame('ai_event', row, after)
            if delivered >= MAX_STREAM_EVENTS:
                break
        if time.monotonic() - heartbeat >= HEARTBEAT_SECONDS:
            yield _frame('heartbeat', {'cursor': after, 'server_time': timestamp(utcnow())})
            heartbeat = time.monotonic()
        if not page['has_more']:
            await asyncio.sleep(min(POLL_SECONDS, max(0, STREAM_SECONDS - (time.monotonic() - started))))
    yield _frame('stream_end', {'cursor': after, 'server_time': timestamp(utcnow()), 'reason': 'window_complete'})


def register_ai_stream_routes(app):
    @app.post('/v1/ai/analysis-streams', status_code=202)
    async def accept(payload: AnalysisRequest, request: Request, response: Response,
                     idempotency_key: str = Header(alias='Idempotency-Key', max_length=64)):
        key, fingerprint = canonical_key(idempotency_key), digest(payload.model_dump())
        database = app.state.database
        session_id = request.state.session_id
        def reserve_in_thread():
            with database.sessions() as db:
                QueryService(db, None).lock_ingestion()
                existing = db.scalar(select(AIRequest).where(AIRequest.actor_session_id == session_id,
                                                            AIRequest.idempotency_key == key))
                if existing:
                    if existing.request_hash != fingerprint:
                        raise HTTPException(409, {'code': 'idempotency_payload_mismatch'})
                    if existing.request_contract.get('delivery_mode') != 'stream':
                        raise HTTPException(409, {'code': 'ai_stream_mode_conflict'})
                    return {'replay': store.detail(db, existing.id, session_id)}
                pack, config, body, reserve = prepare_analysis(db, payload, session_id, stream=True)
                frozen_pack = {'payload': deepcopy(pack.payload), 'data_state': pack.data_state}
                owner_token = uid()
                row = reserve_response(db, config=config, pack=pack, session_id=session_id, key=key,
                    request_hash=fingerprint, question=payload.question, reserve=reserve, body=body,
                    contract={**analysis_contract(pack.payload),
                              'delivery_mode': 'stream'},
                    before_commit=lambda session, reserved: store.create_execution_locked(session, reserved, owner_token))
                return {'request_id': row.id, 'owner_token': owner_token, 'config': config,
                        'body': body, 'pack': frozen_pack}

        reserved = await asyncio.to_thread(reserve_in_thread)
        if 'replay' in reserved:
            result = reserved['replay']
            response.status_code = 200 if result['execution']['terminal'] else 202
            return {**result, 'replayed': True}
        request_id, owner_token = reserved['request_id'], reserved['owner_token']
        # No request Session crosses a task boundary. A crash after reservation
        # leaves an unknown result, never an automatically repeated model call.
        try:
            started = app.state.ai_stream_supervisor.start(request_id, owner_token, reserved['config'],
                                                           reserved['body'], reserved['pack'])
            if started is False:
                await asyncio.to_thread(store.finish_execution, database, request_id, owner_token,
                                        state='outcome_unknown', error_code='ai_stream_start_failed')
        except Exception:
            await asyncio.to_thread(store.finish_execution, database, request_id, owner_token,
                                    state='outcome_unknown', error_code='ai_stream_start_failed')

        def accepted_detail():
            with database.sessions() as db:
                return {**store.detail(db, request_id, session_id), 'replayed': False}
        return await asyncio.to_thread(accepted_detail)

    @app.get('/v1/ai/analysis-streams/lookup')
    def lookup(request: Request, mode: Literal['history'] = Query(...),
               idempotency_key: str = Query(..., max_length=64)):
        key = canonical_key(idempotency_key)
        with app.state.database.sessions() as db:
            row = db.scalar(select(AIRequest).where(AIRequest.actor_session_id == request.state.session_id,
                                                    AIRequest.idempotency_key == key))
            if row is None:
                raise HTTPException(404, '未找到本会话的 AI 流式分析')
            return store.detail(db, row.id, request.state.session_id)

    @app.get('/v1/ai/analysis-streams/{request_id}')
    def detail(request_id: str, request: Request, mode: Literal['history'] = Query(...)):
        with app.state.database.sessions() as db:
            return store.detail(db, request_id, request.state.session_id)

    @app.get('/v1/ai/analysis-streams/{request_id}/events')
    def events(request_id: str, request: Request, cursor: str | None = Query(None, max_length=512),
               limit: int = Query(50, ge=1, le=100)):
        with app.state.database.sessions() as db:
            return store.event_page(db, request_id, request.state.session_id, after=cursor, limit=limit)

    @app.get('/v1/ai/analysis-streams/{request_id}/events/stream')
    def stream(request_id: str, request: Request, cursor: str | None = Query(None, max_length=512),
               last_event_id: str | None = Header(None, alias='Last-Event-ID', max_length=512)):
        with app.state.database.sessions() as db:
            store.owned_request(db, request_id, request.state.session_id)
            if cursor is not None and last_event_id is not None and cursor != last_event_id:
                store.reset_cursor()
            cursor = last_event_id or cursor
            store.event_page(db, request_id, request.state.session_id, after=cursor, limit=1)
            cursor = cursor or store.cursor(request_id)
        return StreamingResponse(stream_events(app.state.database, request, request_id,
            request.state.session_id, cursor), media_type='text/event-stream', headers={
                'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no', 'X-Content-Type-Options': 'nosniff'})
