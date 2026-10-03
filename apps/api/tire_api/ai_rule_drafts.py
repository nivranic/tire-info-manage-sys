"""Draft-only Responses workflow; applying a reviewed rule is a separate command."""
from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import Field, StrictBool
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, load_only

from .ai_analysis import owned_pack, run_state
from .ai_evidence import pack_view
from .ai_execution import execute_response, reserve_response
from .ai_gateway import GatewayError, configured_model, request_body
from .ai_models import AIDraftApplication, AICompletion, AIEvidencePack, AIRequest
from .ai_rule_contract import RULE_PROMPT_VERSION, SYSTEM_PROMPT, output_schema, source_catalog, validate_draft
from .db import uid, utc, utcnow
from .domain import StrictModel, digest, stable_json
from .monitoring import RuleCreate, create_rule, validate_rule_target
from .research import DescriptionText
from .service import QueryService, timestamp


class PrepareDraft(StrictModel):
    source_id: str = Field(min_length=1, max_length=80)
    instruction: DescriptionText = Field(min_length=2, max_length=2000)


class GenerateDraft(StrictModel):
    pack_id: str = Field(min_length=1, max_length=64)
    allow_external_processing: StrictBool


class ApplyDraft(StrictModel):
    rule: RuleCreate
    acknowledged: StrictBool


def key_value(value):
    try:
        return str(UUID(value))
    except ValueError:
        raise HTTPException(422, 'Idempotency-Key 必须是 UUID') from None


def owned_draft(db, run_id, session_id):
    row = db.get(AIRequest, run_id)
    if row is None or row.actor_session_id != session_id or row.request_contract.get('purpose') != 'rule_draft':
        raise HTTPException(404, '未找到本会话的规则草稿')
    return row


def draft_view(db, row, completion=None, *, prefetched=False, include_draft=True):
    value = run_state(db, row, completion, prefetched=prefetched, include_answer=include_draft)
    return {key: value[key] for key in ('id', 'pack_id', 'state', 'usage', 'reserved_tokens', 'error_code', 'created_at', 'completed_at')} | {
        'draft': value['answer']}


def application_view(row):
    return {'id': row.id, 'rule_id': row.rule_id, 'created_at': timestamp(row.created_at),
            'reviewed_rule': row.reviewed_rule, 'payload_hash': row.payload_hash}


def checked_catalog(db, registry, pack):
    if pack.payload.get('purpose') != 'rule_draft' or utc(pack.expires_at) <= utcnow():
        raise HTTPException(409, '草稿上下文已过期或类型不符，请重新准备')
    catalog = source_catalog(db, registry, pack.payload['source']['id'])
    if catalog['catalog_hash'] != pack.payload['catalog_hash']:
        raise HTTPException(409, '来源目录或支持能力已变化，请重新准备并审核草稿')


def register_rule_draft_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/ai/rule-draft-packs')
    def prepare(payload: PrepareDraft, request: Request, db: Session = Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        catalog = source_catalog(db, app.state.registry, payload.source_id)
        content = {'purpose': 'rule_draft', 'retrieval': 'frozen_monitor_capability_catalog',
            'instruction': payload.instruction, **catalog, 'evidence': [], 'facts': [], 'conflicts': [],
            'source_state': 'snapshot', 'query_id': None, 'consent_id': None}
        if len(stable_json(content).encode('utf-8')) > 44000:
            raise HTTPException(422, '来源目录过大，不能无损准备本次草稿上下文')
        pack = AIEvidencePack(actor_session_id=request.state.session_id, mode='history', data_state='local_snapshot',
            privacy_class='private', payload=content, fingerprint=digest(content), expires_at=utcnow() + timedelta(minutes=30))
        db.add(pack)
        db.flush()
        QueryService(db, None).audit(request.state.session_id, 'ai_rule_draft_pack_created', pack_id=pack.id,
                                   source_id=payload.source_id, catalog_hash=catalog['catalog_hash'])
        db.commit()
        return pack_view(pack)

    @app.post('/v1/ai/rule-drafts')
    def generate(payload: GenerateDraft, request: Request, response: Response,
                 idempotency_key: str = Header(alias='Idempotency-Key', max_length=64), db: Session = Depends(get_db)):
        key = key_value(idempotency_key)
        request_hash = digest({'purpose': 'rule_draft', **payload.model_dump()})
        QueryService(db, None).lock_ingestion()
        existing = db.scalar(select(AIRequest).where(AIRequest.actor_session_id == request.state.session_id, AIRequest.idempotency_key == key))
        if existing:
            if existing.request_hash != request_hash or existing.request_contract.get('purpose') != 'rule_draft':
                raise HTTPException(409, '同一幂等键不能用于不同任务或草稿')
            value = draft_view(db, existing)
            db.commit()
            response.status_code = 202 if value['state'] == 'pending' else 200
            return value
        pack = owned_pack(db, payload.pack_id, request.state.session_id)
        checked_catalog(db, app.state.registry, pack)
        if not payload.allow_external_processing:
            raise HTTPException(422, '需要明确允许将监控意图和所选目录发送到 OpenAI')
        try:
            config = configured_model()
            if not config.allow_private:
                raise HTTPException(403, '监控意图属于私有工作区数据，当前模型策略不允许外发')
            body, reserve = request_body(config, pack.payload['instruction'], pack.payload,
                system_prompt=SYSTEM_PROMPT, output_schema=output_schema(pack.payload), schema_name='monitor_rule_proposal')
        except GatewayError as error:
            raise HTTPException(503, str(error)) from None
        row = reserve_response(db, config=config, pack=pack, session_id=request.state.session_id, key=key,
            request_hash=request_hash, question=pack.payload['instruction'], reserve=reserve, body=body,
            contract={'purpose': 'rule_draft', 'prompt_version': RULE_PROMPT_VERSION, 'catalog_hash': pack.payload['catalog_hash']})
        completion = execute_response(db, app, row, config, body, lambda value: validate_draft(value, pack.payload))
        return draft_view(db, row, completion, prefetched=True)

    @app.get('/v1/ai/rule-drafts')
    def listing(request: Request, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        from .auth import session_scope
        rows = db.execute(select(AIRequest, AICompletion).outerjoin(AICompletion, AICompletion.request_id == AIRequest.id)
            .options(load_only(AICompletion.request_id, AICompletion.state, AICompletion.error_code, AICompletion.usage, AICompletion.created_at))
            .where(AIRequest.actor_session_id.in_(session_scope(db, request.state.session_id)), AIRequest.request_contract['purpose'].as_string() == 'rule_draft')
            .order_by(desc(AIRequest.created_at), desc(AIRequest.id)).limit(20)).all()
        return {'scope': 'browser_session', 'items': [draft_view(db, row, completion, prefetched=True, include_draft=False) for row, completion in rows]}

    @app.get('/v1/ai/rule-drafts/{run_id}')
    def detail(run_id: str, request: Request, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        row = owned_draft(db, run_id, request.state.session_id)
        application = db.scalar(select(AIDraftApplication).where(AIDraftApplication.draft_request_id == row.id))
        return {**draft_view(db, row), 'pack': pack_view(owned_pack(db, row.pack_id, request.state.session_id)),
                'application': application_view(application) if application else None}

    @app.post('/v1/ai/rule-drafts/{run_id}/apply', status_code=201)
    def apply(run_id: str, payload: ApplyDraft, request: Request,
              idempotency_key: str = Header(alias='Idempotency-Key', max_length=64), db: Session = Depends(get_db)):
        key = key_value(idempotency_key)
        if not payload.acknowledged:
            raise HTTPException(422, '请先审核完整规则并明确确认保存')
        QueryService(db, None).lock_ingestion()
        row = owned_draft(db, run_id, request.state.session_id)
        reviewed = payload.rule.model_dump(mode='json')
        payload_hash = digest({'draft_id': run_id, 'rule': reviewed})
        same_key = db.scalar(select(AIDraftApplication).where(AIDraftApplication.actor_session_id == request.state.session_id,
                                                             AIDraftApplication.idempotency_key == key))
        previous = db.scalar(select(AIDraftApplication).where(AIDraftApplication.draft_request_id == run_id))
        for existing in (same_key, previous):
            if existing and (existing.draft_request_id != run_id or existing.payload_hash != payload_hash):
                raise HTTPException(409, '草稿已应用或幂等键已用于不同人工审核内容')
        if previous:
            result = previous.rule_snapshot
            db.commit()
            return result
        completion = db.get(AICompletion, row.id)
        if not completion or completion.state != 'completed' or not completion.answer or not completion.answer.get('can_apply'):
            raise HTTPException(409, '草稿未完成或仍有未解决需求，不能保存为规则')
        pack = owned_pack(db, row.pack_id, request.state.session_id)
        checked_catalog(db, app.state.registry, pack)
        if payload.rule.source_id != pack.payload['source']['id'] or payload.rule.query.model not in pack.payload['supported_models']:
            raise HTTPException(422, '审核规则的来源与型号必须属于准备时明确选择的目录')
        if set(payload.rule.fields) - {item['key'] for item in pack.payload['capabilities']['fields']}:
            raise HTTPException(422, '规则包含本次支持能力之外的字段')
        validate_rule_target(db, app.state.registry, payload.rule)
        result = create_rule(db, app.state.registry, payload.rule, request.state.session_id)
        application_id = uid()
        result['origin'] = {'kind': 'ai_rule_draft', 'draft_id': row.id, 'application_id': application_id}
        db.add(AIDraftApplication(id=application_id, draft_request_id=row.id, rule_id=result['id'],
            actor_session_id=request.state.session_id, idempotency_key=key, reviewed_rule=reviewed,
            payload_hash=payload_hash, rule_snapshot=result))
        QueryService(db, None).audit(request.state.session_id, 'ai_rule_draft_applied', draft_id=row.id,
            application_id=application_id, rule_id=result['id'], payload_hash=payload_hash, enabled=payload.rule.enabled)
        db.commit()
        return result
