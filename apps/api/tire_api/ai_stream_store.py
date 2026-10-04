"""Fenced AI stream writes and read-only, session-scoped cursor projections."""
import base64
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import re

from fastapi import HTTPException
from sqlalchemy import desc, select

from .ai_models import AICompletion, AIEvidencePack, AIRequest
from .ai_stream_models import AIStreamEvent, AIStreamExecution
from .db import uid, utc, utcnow
from .domain import stable_json
from .service import QueryService, timestamp

SCHEMA = 'ai-streams@1'
OWNER_SECONDS = 90
MAX_EVENT_BYTES = 64 * 1024
TERMINAL = {'completed', 'failed', 'outcome_unknown'}
STREAM_ERRORS = {'ai_grounding_validation_failed', 'ai_stream_interrupted', 'ai_stream_owner_expired',
                 'ai_stream_start_failed', 'ai_stream_shutdown', 'ai_stream_invalid', 'ai_stream_too_large'}


def safe_stream_error(value):
    from .ai_gateway import safe_error
    return value if isinstance(value, str) and value in STREAM_ERRORS else safe_error(value)


def _token_hash(value):
    if not isinstance(value, str) or not 16 <= len(value) <= 128:
        raise ValueError('invalid_ai_stream_owner')
    return hashlib.sha256(value.encode()).hexdigest()


def _latest(db, request_id):
    return db.scalar(select(AIStreamEvent).where(AIStreamEvent.request_id == request_id)
                     .order_by(desc(AIStreamEvent.sequence)).limit(1))


def _append(db, request_id, event_type, payload, event_key):
    if len(stable_json(payload).encode('utf-8')) > MAX_EVENT_BYTES:
        raise ValueError('ai_stream_event_too_large')
    existing = db.scalar(select(AIStreamEvent).where(AIStreamEvent.request_id == request_id,
                                                    AIStreamEvent.event_key == event_key))
    if existing:
        return None
    last = _latest(db, request_id)
    sequence = last.sequence + 1 if last else 1
    if sequence > 64:
        raise ValueError('ai_stream_event_limit')
    row = AIStreamEvent(id=uid(), request_id=request_id, sequence=sequence, event_key=event_key,
                        type=event_type, payload=deepcopy(payload))
    db.add(row)
    db.flush()
    return row


def create_execution_locked(db, request, owner_token, deadline_at=None):
    """Reservation hook: caller holds the lock and commits both ledgers together."""
    row = AIStreamExecution(request_id=request.id, owner_token_hash=_token_hash(owner_token),
                            deadline_at=deadline_at or utcnow() + timedelta(seconds=OWNER_SECONDS))
    db.add(row)
    db.flush()
    _append(db, request.id, 'accepted', {}, 'accepted')
    return row


def _owned(db, request_id, owner_token):
    row = db.get(AIStreamExecution, request_id)
    return row if row and row.owner_token_hash == _token_hash(owner_token) else None


def start_execution(database, request_id, owner_token):
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        execution = _owned(db, request_id, owner_token)
        if (execution is None or utc(execution.deadline_at) <= utcnow()
                or db.get(AICompletion, request_id) is not None):
            return False
        if _append(db, request_id, 'started', {}, 'started') is None:
            return False
        if utc(execution.deadline_at) <= utcnow():
            db.rollback()
            return False
        db.commit()
        return True


def _grounded_claim(db, request_id, claim):
    from .ai_analysis import grounded_answer
    row = db.get(AIRequest, request_id)
    pack = db.get(AIEvidencePack, row.pack_id)
    raw = deepcopy(claim)
    if raw.get('type') == 'fact':
        raw['text'] = ''
    result = grounded_answer(json.dumps({'claims': [raw], 'uncertainty': ''}), pack)['claims'][0]
    if result != claim:
        raise ValueError('ai_stream_claim_not_grounded')
    return result


def append_event(database, request_id, owner_token, type, payload):
    if type not in {'claim_draft', 'uncertainty_draft'} or not isinstance(payload, dict):
        raise ValueError('invalid_ai_stream_draft')
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        execution = _owned(db, request_id, owner_token)
        if (execution is None or utc(execution.deadline_at) <= utcnow()
                or db.get(AICompletion, request_id) is not None):
            return False
        if db.scalar(select(AIStreamEvent.id).where(AIStreamEvent.request_id == request_id,
                                                   AIStreamEvent.event_key == 'started')) is None:
            return False
        if type == 'claim_draft':
            if (set(payload) != {'index', 'claim'} or payload['index'].__class__ is not int
                    or not 0 <= payload['index'] < 12 or not isinstance(payload['claim'], dict)):
                raise ValueError('invalid_ai_stream_claim')
            payload = {'index': payload['index'], 'claim': _grounded_claim(db, request_id, payload['claim'])}
            key = 'claim:' + str(payload['index'])
        else:
            if set(payload) != {'text'} or not isinstance(payload['text'], str) or len(payload['text']) > 2000:
                raise ValueError('invalid_ai_stream_uncertainty')
            from .ai_recall_contract import validate_recall_uncertainty
            row = db.get(AIRequest, request_id)
            validate_recall_uncertainty(payload['text'], db.get(AIEvidencePack, row.pack_id).payload)
            key = 'uncertainty'
        if _append(db, request_id, type, payload, key) is None:
            return False
        if utc(execution.deadline_at) <= utcnow():
            db.rollback()
            return False
        db.commit()
        return True


def finish_execution(database, request_id, owner_token, *, state, error_code=None,
                     answer=None, usage=None, provider_response_id=None):
    from .ai_analysis import grounded_answer
    from .ai_gateway import safe_usage
    if state not in TERMINAL:
        raise ValueError('invalid_ai_stream_completion_state')
    with database.sessions() as db:
        service = QueryService(db, None)
        service.lock_ingestion()
        execution = _owned(db, request_id, owner_token)
        if execution is None or db.get(AICompletion, request_id) is not None:
            return False
        if utc(execution.deadline_at) <= utcnow() and state != 'outcome_unknown':
            return False
        row = db.get(AIRequest, request_id)
        if state == 'completed':
            if db.scalar(select(AIStreamEvent.id).where(AIStreamEvent.request_id == request_id,
                                                       AIStreamEvent.event_key == 'started')) is None:
                return False
            if not isinstance(answer, dict):
                raise ValueError('invalid_ai_stream_answer')
            claims = deepcopy(answer.get('claims'))
            for claim in claims:
                if claim.get('type') == 'fact':
                    claim['text'] = ''
            validated = grounded_answer(json.dumps({'claims': claims, 'uncertainty': answer.get('uncertainty')}),
                                        db.get(AIEvidencePack, row.pack_id))
            if answer != validated:
                raise ValueError('ai_stream_answer_not_grounded')
            error_code = None
        else:
            answer = None
            error_code = safe_stream_error(error_code)
        if not isinstance(provider_response_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', provider_response_id):
            provider_response_id = None
        completion = AICompletion(request_id=request_id, state=state, error_code=error_code,
            answer=deepcopy(answer), usage=safe_usage(usage) if state != 'outcome_unknown' else None,
            provider_response_id=provider_response_id)
        db.add(completion)
        _append(db, request_id, state, {'state': state, 'error_code': error_code}, 'terminal')
        service.audit(row.actor_session_id, 'ai_request_finished', request_id=request_id,
                      state=state, error_code=error_code)
        db.flush()
        if utc(execution.deadline_at) <= utcnow() and state != 'outcome_unknown':
            db.rollback()
            return False
        db.commit()
        return True


def owned_request(db, request_id, session_id):
    from .auth import session_scope
    row = db.get(AIRequest, request_id)
    if (row is None or row.actor_session_id not in session_scope(db, session_id)
            or row.request_contract.get('delivery_mode') != 'stream'
            or row.request_contract.get('purpose') == 'rule_draft'
            or db.get(AIStreamExecution, request_id) is None):
        raise HTTPException(404, '未找到本账户的 AI 流式分析')
    return row


def cursor(request_id, event=None):
    value = [1, request_id, event.sequence if event else 0, event.id if event else None]
    return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')


def reset_cursor():
    raise HTTPException(409, {'code': 'ai_stream_cursor_reset_required', 'message': '流事件游标已失效，请重新读取分析详情'})


def _anchor(db, request_id, value):
    if value is None:
        return 0
    try:
        if not isinstance(value, str) or not value or len(value) > 512:
            reset_cursor()
        parts = json.loads(base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True))
        if (not isinstance(parts, list) or len(parts) != 4 or parts[:2] != [1, request_id]
                or parts[0].__class__ is not int or parts[2].__class__ is not int or not 0 <= parts[2] <= 64):
            reset_cursor()
        if parts[2] == 0:
            if parts[3] is not None:
                reset_cursor()
        elif not isinstance(parts[3], str) or db.scalar(select(AIStreamEvent.id).where(
                AIStreamEvent.request_id == request_id, AIStreamEvent.sequence == parts[2],
                AIStreamEvent.id == parts[3])) is None:
            reset_cursor()
        return parts[2]
    except (ValueError, TypeError, UnicodeError):
        reset_cursor()


def event_view(row):
    return {'id': row.id, 'request_id': row.request_id, 'sequence': row.sequence, 'cursor': cursor(row.request_id, row),
            'type': row.type, 'payload': deepcopy(row.payload), 'created_at': timestamp(row.created_at)}


def execution_view(db, request_id, last=None, *, completion=None, prefetched=False):
    execution = db.get(AIStreamExecution, request_id)
    if not prefetched:
        completion = db.get(AICompletion, request_id)
    last = last or _latest(db, request_id)
    expired = completion is None and utc(execution.deadline_at) <= utcnow()
    state = (completion.state if completion else 'outcome_unknown' if expired else
             'accepted' if last is None or last.type == 'accepted' else 'running')
    return {'state': state, 'terminal': state in TERMINAL, 'deadline_at': timestamp(execution.deadline_at),
            'last_event_at': timestamp(last.created_at) if last else None, 'projection_only': expired}


def device_view(preparation, claim):
    """路由#8：device origin 请求的 owned 精确视图（draft 仍非最终结论）。

    键名规避（D11）已由第一波 payload 实现：device 专有字段收进 device_context 子对象，
    顶层保留键/仓库专属键在 prepare 侧被禁用，pack_view 展开无碰撞。
    """
    return {'origin': 'device_history', 'preparation_id': preparation.id,
            'host_receipt_id': preparation.host_receipt_id, 'intent_id': preparation.intent_id,
            'question_sha256': preparation.question_sha256,
            'device_context_fingerprint': preparation.device_context_fingerprint,
            'selection_sha256': preparation.selection_hash, 'projection_sha256': preparation.projection_hash,
            'expires_at': timestamp(preparation.expires_at), 'expired': utc(preparation.expires_at) <= utcnow(),
            'claim': {'id': claim.id, 'analysis_key': claim.analysis_key, 'provider': claim.provider,
                      'model': claim.model, 'created_at': timestamp(claim.created_at)}}


def detail(db, request_id, session_id):
    from .ai_analysis import run_state, owned_pack
    from .auth import session_scope
    from .ai_evidence import pack_view
    from .device_ai_models import DeviceAIConsentClaim, DeviceAIPreparation
    row = owned_request(db, request_id, session_id)
    # Read the anchor before projections so a concurrent writer cannot be skipped.
    last = _latest(db, request_id)
    anchor = cursor(request_id, last)
    completion = db.get(AICompletion, request_id)
    execution = execution_view(db, request_id, last, completion=completion, prefetched=True)
    analysis = {**run_state(db, row, completion, prefetched=True),
                'pack': pack_view(owned_pack(db, row.pack_id, session_scope(db, session_id)))}
    # D1/D9：device origin 由 preparation 表权威判别；读取路径同时断言 AIRequest 与 claim
    # 双 ledger 一致（replay/lookup 一致性，结构上不可能孤儿，防御性 fail closed）。
    preparation = db.scalar(select(DeviceAIPreparation).where(DeviceAIPreparation.ai_pack_id == row.pack_id,
        DeviceAIPreparation.actor_session_id == session_id))
    if preparation is not None:
        claim = db.scalar(select(DeviceAIConsentClaim).where(DeviceAIConsentClaim.preparation_id == preparation.id))
        if claim is None or claim.ai_request_id != row.id:
            raise HTTPException(409, {'code': 'device_ai_ledger_inconsistent',
                'message': '设备 AI 调用记录与同意记录不一致，读取被拒绝'})
        analysis['device'] = device_view(preparation, claim)
    analysis['state'] = 'pending' if execution['state'] in {'accepted', 'running'} else execution['state']
    drafts = db.scalars(select(AIStreamEvent).where(AIStreamEvent.request_id == request_id,
        AIStreamEvent.sequence <= (last.sequence if last else 0),
        AIStreamEvent.type.in_(['claim_draft', 'uncertainty_draft'])).order_by(AIStreamEvent.sequence)).all()
    active = not execution['terminal']
    return {'schema': SCHEMA, 'scope': 'session', 'analysis': analysis, 'execution': execution,
        'draft_claims': [deepcopy(event.payload) for event in drafts if event.type == 'claim_draft'] if active else [],
        'draft_uncertainty': next((event.payload['text'] for event in drafts if event.type == 'uncertainty_draft'), None) if active else None,
        'cursor': anchor, 'server_time': timestamp(utcnow())}


def event_page(db, request_id, session_id, *, after=None, limit=50):
    owned_request(db, request_id, session_id)
    sequence = _anchor(db, request_id, after)
    last = _latest(db, request_id)
    upper = last.sequence if last else 0
    rows = db.scalars(select(AIStreamEvent).where(AIStreamEvent.request_id == request_id,
        AIStreamEvent.sequence > sequence, AIStreamEvent.sequence <= upper)
        .order_by(AIStreamEvent.sequence).limit(limit + 1)).all()
    selected = rows[:limit]
    return {'schema': SCHEMA, 'scope': 'session', 'request_id': request_id,
        'items': [event_view(row) for row in selected], 'next_cursor': cursor(request_id, selected[-1]) if selected else after or cursor(request_id),
        'latest_cursor': cursor(request_id, last), 'has_more': len(rows) > limit,
        'execution': execution_view(db, request_id, last), 'server_time': timestamp(utcnow())}
