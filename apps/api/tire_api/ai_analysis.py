"""Grounded analysis with explicit data scope, idempotency and durable usage accounting."""
from datetime import timedelta
import json
import re
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import Field, StrictBool
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session, load_only

from .ai_evidence import PreparePack, pack_view, prepare_pack
from .ai_gateway import (GatewayError, analysis_contract, configured_adapter, configured_model, model_status,
                         request_body)
from .ai_recall_contract import (recall_boundary, validate_recall_claim, validate_recall_payload)
from .ai_models import AICompletion, AIEvidencePack, AIRequest
from .device_ai import DeviceSubmission, question_digest
from .device_ai_models import DeviceAIPreparation
from .ai_execution import execute_response, reserve_response
from .db import utc, utcnow
from .domain import StrictModel, digest, stable_json
from .research import DescriptionText
from .service import QueryService, timestamp

PENDING_WINDOW = timedelta(seconds=120)
CURRENT_WORDS = re.compile(r'当前|最新|现在|今天|目前|现售|还有没有|\b(?:current|latest|today|now)\b', re.I)
DEVICE_ORIGIN = 'device_history'
# reserve_response 在同一 session/事务内消费该计划（D7 claim-or-nothing / D9 原子追加）。
DEVICE_CLAIM_PLAN_KEY = 'device_ai_claim'

# D18 方案B（Root 2026-10-03 批准，specs/d18-minimal-assembly.md）：device 分支的
# Provider 请求体从"投影材料全量直发"（策略A）改为 facts/回执最小化组装，兑现
# proposal-a.json:214 的 provider_payload_minimization 承诺。发送白名单 =
# grounded_answer 实际消费的 grounding 下界（facts[].id/text/evidence_id、
# evidence[].id/event_id、顶层 conflicts/source_state/data_state）
# + 原始 source 回执（observed_at/verified_at，provenance_time 语义）与冻结身份/引用
# （tire 平铺 kind/snapshot_id/variant_id/verification_id + identity_contract；非 tire
# 域冻结身份=reference 子对象）。禁发（结构性白名单排除，非逐字段删除）：
# device_context 本机细节（哈希/包绑定/计数/回执指针）、member_key（包内成员键）、
# manifest、member_reasons、未选 contexts、任何凭据类字段——服务端 pack.payload
# 保留完整 label→device citation 映射（grounded_answer/审计/detail 视图消费）。
DEVICE_FACT_PROJECTION_KEYS = ('id', 'text', 'evidence_id', 'domain', 'field_code')
DEVICE_RECEIPT_PROJECTION_KEYS = ('id', 'event_id', 'observed_at', 'verified_at')
DEVICE_CITATION_PROJECTION_KEYS = ('kind', 'snapshot_id', 'variant_id', 'verification_id')


def _device_request_evidence(payload: dict) -> dict:
    """D18 方案B：把 device pack payload 组装成最小化 untrusted_evidence_pack。

    输入是 {**pack.payload, 'data_state': pack.data_state} 的合并形态；输出只含
    Provider grounding 必需的白名单键。device_ai_routes._outbound_budget 复用本函数
    做预检计量（真实值+上界并列），预检与 submit 不可能漂移成两个预算（D12 反漂移
    延伸：同一组装函数 + 同一 outbound_measurement）。facts 的 id/evidence_id 供
    claim 引用绑定，text 供服务器渲染 fact 类 claim；evidence 的 event_id 供跨事件
    推断约束。grounding 校验始终在服务端对完整 pack.payload 执行——本函数只决定
    "模型能看到什么"，不参与任何授权或校验判定。
    """
    facts = [{key: item[key] for key in DEVICE_FACT_PROJECTION_KEYS if key in item}
             for item in payload.get('facts') or [] if isinstance(item, dict)]
    evidence = []
    for item in payload.get('evidence') or []:
        if not isinstance(item, dict):
            continue
        entry = {key: item[key] for key in DEVICE_RECEIPT_PROJECTION_KEYS if key in item}
        if isinstance(item.get('reference'), dict):
            # 非 tire 域：冻结身份=离线引用本身，reference 子对象原样（不伪造仓库
            # recall 合同的顶层别名键，D17 分流不受影响）。
            entry['reference'] = item['reference']
        else:
            entry.update({key: item[key] for key in DEVICE_CITATION_PROJECTION_KEYS if key in item})
            if isinstance(item.get('identity_contract'), dict):
                # 数值仍以 encode_value 的 DeviceAIValue token DTO 形态上线（无损合同）。
                entry['identity_contract'] = item['identity_contract']
        evidence.append(entry)
    return {'facts': facts, 'evidence': evidence, 'conflicts': payload.get('conflicts') or [],
            'source_state': payload['source_state'], 'data_state': payload['data_state']}


class AnalysisRequest(StrictModel):
    pack_id: str = Field(min_length=1, max_length=64)
    question: DescriptionText = Field(min_length=2, max_length=2000)
    allow_external_processing: StrictBool
    # 第50轮设备AI桥接（纪要 D1/D8）：closed 可选判别字段。DB 结构判别为权威——
    # device 包缺 device_submission 或 legacy 包携带它都 422（N10 双向）。actor 一律
    # 取 request.state.session_id，DTO 不携带 actor 字段（DeviceSubmission 已 closed）。
    device_submission: DeviceSubmission | None = None

    def model_dump(self, **kwargs):
        # 幂等摘要的 legacy 字节不变量：device_submission 为 None（全部既有请求）时
        # 不进入 dump——request_hash 与改动前逐字节一致；device 提交则完整参与摘要
        # （D6/D8），两个入口都经现有 digest(payload.model_dump()) 计算而无需改造。
        value = super().model_dump(**kwargs)
        if value.get('device_submission') is None:
            value.pop('device_submission')
        return value


class Claim(StrictModel):
    type: Literal['fact', 'inference']
    text: str = Field(max_length=2000)
    fact_ids: list[str] = Field(min_length=1, max_length=24)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)


class ModelAnswer(StrictModel):
    claims: list[Claim] = Field(max_length=12)
    uncertainty: str = Field(max_length=2000)


def grounded_answer(text: str, pack: AIEvidencePack) -> dict:
    model = ModelAnswer.model_validate(json.loads(text))
    # D17 分流（P1-4a 落地）：device 包的 evidence/facts 形状与仓库 recall 合同不同源
    #（非 tire 域身份键收进 reference 子对象，顶层无 kind/recall_revision_id 别名键），
    # 且 origin 标记只在 device payload 出现（仓库 payload 从不携带），按 origin 跳过
    # 仓库 recall 合同校验——device 路径的 grounding 语义不因 recall 域选择而改变。
    if pack.payload.get('origin') == DEVICE_ORIGIN:
        recall = False
    else:
        recall = validate_recall_payload(pack.payload)
    if recall and model.uncertainty:
        raise ValueError('recall_freeform_not_allowed')
    facts = {item['id']: item for item in pack.payload['facts']}
    evidence = {item['id']: item for item in pack.payload['evidence']}
    if not recall and not model.claims and not model.uncertainty:
        raise ValueError('empty_answer')
    claims = []
    for claim in model.claims:
        if (len(set(claim.fact_ids)) != len(claim.fact_ids) or not set(claim.fact_ids) <= facts.keys()
                or len(set(claim.evidence_ids)) != len(claim.evidence_ids)
                or set(claim.evidence_ids) != {facts[key]['evidence_id'] for key in claim.fact_ids}):
            raise ValueError('unbound_citation')
        if recall:
            validate_recall_claim(claim, facts, evidence)
        if claim.type == 'fact':
            if claim.text:
                raise ValueError('freeform_fact_not_allowed')
            rendered = '\n'.join(facts[key]['text'] for key in claim.fact_ids)
        else:
            if not claim.text:
                raise ValueError('empty_inference')
            events = {evidence[key]['event_id'] for key in claim.evidence_ids if evidence[key].get('event_id')}
            if len(events) > 1:
                raise ValueError('cross_event_inference_not_allowed')
            rendered = claim.text
        claims.append({**claim.model_dump(), 'text': rendered})
    result = {'answer': '\n\n'.join(c['text'] for c in claims), 'claims': claims,
            'uncertainty': model.uncertainty, 'conflicts': pack.payload['conflicts'],
            'source_state': pack.payload['source_state'], 'data_state': pack.data_state,
            'notice': '事实文字由所选证据字段生成；模型推断与不确定性仍需核对，不是来源事实或安全适配认证。'}
    if recall:
        result['recall_boundary'] = recall_boundary(pack.payload)
        result['notice'] = result['recall_boundary']['notice']
    return result


def owned_pack(db, pack_id, session_id):
    pack = db.get(AIEvidencePack, pack_id)
    if pack is None or pack.actor_session_id != session_id:
        raise HTTPException(404, '未找到本会话的 AI 证据包')
    if digest(pack.payload) != pack.fingerprint:
        raise HTTPException(409, '证据包完整性校验失败，请重新准备')
    return pack


def run_state(db, row, completion=None, *, prefetched=False, include_answer=True):
    if not prefetched:
        completion = db.get(AICompletion, row.id)
    state = completion.state if completion else ('outcome_unknown' if utc(row.created_at) + PENDING_WINDOW <= utcnow() else 'pending')
    if completion is None and row.request_contract.get('delivery_mode') == 'stream':
        from .ai_stream_models import AIStreamExecution
        execution = db.get(AIStreamExecution, row.id)
        if execution is not None and utc(execution.deadline_at) <= utcnow():
            state = 'outcome_unknown'
    return {'id': row.id, 'pack_id': row.pack_id, 'question': row.question,
            'provider': row.provider, 'model': row.model, 'created_at': timestamp(row.created_at),
            'request_contract': row.request_contract,
            'state': state, 'reserved_tokens': row.reserved_tokens,
            'usage': completion.usage if completion else None,
            'error_code': completion.error_code if completion else None,
            'answer': completion.answer if completion and include_answer else None,
            'completed_at': timestamp(completion.created_at) if completion else None}


def budget_usage(db):
    from .embedding_budget import budget_usage as shared_budget_usage
    return shared_budget_usage(db)


def device_provider_policy_fingerprint(config) -> str:
    """D2：服务端按 sanitized provider+model+allow_private 白名单+prompt/grounding 版本重算的同意指纹。

    只读 configured_model() 派生值与代码内冻结常量，不含任何客户端输入；客户端的
    expected_provider_policy_fingerprint 只有与当前服务端策略逐字节一致才通过。
    """
    from .ai_gateway import OUTPUT_SCHEMA, PROMPT_VERSION
    return digest({'provider': 'openai_responses', 'model': config.model,
                   'allow_private': bool(config.allow_private),
                   'allowed_privacy_classes': ['public', 'private'] if config.allow_private else ['public'],
                   'prompt_version': PROMPT_VERSION, 'grounding_schema': digest(OUTPUT_SCHEMA)})


def _prepare_device_analysis(db, payload, pack, preparation, *, stream=False):
    """步骤4 device 分支【封高1-高4】：锁内（lock_ingestion 后、reserve_response 前）完成
    D8 回显等值/双过期、D3 question 三重绑定、D2 六元组服务端权威复算、D4 非空+精确
    覆盖与撤销 gate 重跑，并把 claim 计划挂到本 session 供 reserve_response 原子落账。"""
    submission = payload.device_submission
    # D8.4 回显等值：绑定值全取 DB，仅显式比对（封审计/回执链错位）。
    if (submission.prepare_id != preparation.id
            or submission.host_receipt_id != preparation.host_receipt_id
            or submission.device_context_fingerprint != preparation.device_context_fingerprint):
        raise HTTPException(409, {'code': 'device_ai_submission_echo_mismatch',
            'message': '提交回显与按证据包反查的准备记录不一致，请重新预览后再试'})
    # D8.5 双过期检查：preparation 与 pack 是两个语义 gate，边界为 <= now 即过期。
    if utc(preparation.expires_at) <= utcnow():
        raise HTTPException(409, {'code': 'device_ai_preparation_expired',
            'message': '设备 AI 准备记录已过期，请重新预览并生成新的准备记录'})
    if utc(pack.expires_at) <= utcnow():
        raise HTTPException(409, {'code': 'device_ai_pack_expired',
            'message': '设备 AI 证据包已过期，请重新预览并生成新的准备记录'})
    # D10 补强三：device pack 行数据必须是 history（N20 freshness gate 的开关条件）。
    if pack.mode != 'history':
        raise HTTPException(409, {'code': 'device_ai_pack_mode_invalid',
            'message': '设备 AI 证据包模式无效，请重新预览并生成新的准备记录'})
    if CURRENT_WORDS.search(payload.question):
        raise HTTPException(409, '问题要求当前信息，请选择先在线核验；历史证据不能回答当前状态')
    # allow_external_processing 在 device 分支只接受字面 true（closed branch）。
    if payload.allow_external_processing is not True:
        raise HTTPException(422, '分析需要明确允许将问题和所选证据发送到 OpenAI')
    try:
        config = configured_model()
        # 隐私 gate 与 legacy 同式（device pack 投影核恒 private，restricted 仍双重拒绝）。
        if pack.privacy_class == 'restricted' or pack.privacy_class != 'public' and not config.allow_private:
            raise HTTPException(403, '当前模型策略不允许发送这类非公开工作区证据')
    except GatewayError as error:
        raise HTTPException(503, str(error)) from None
    # D3 question 三重绑定：digest(trim_once(question)) == preparation.question_sha256 == consent.question_sha256。
    # AnalysisRequest 模型层 str_strip_whitespace 已恰好 trim 一次，payload.question 即规范化串。
    consent = submission.provider_consent
    if (question_digest(payload.question) != preparation.question_sha256
            or consent.question_sha256 != preparation.question_sha256):
        raise HTTPException(409, {'code': 'device_ai_question_mismatch',
            'message': '提交的问题与准备记录、Provider 同意绑定的摘要不一致；请按预览的问题重新提交'})
    # D2 六元组服务端权威复算：全部比对材料取 DB/config 当前值；provider_consent_hash
    # 只作幂等比对与审计材料，绝不作为授权依据。
    policy_fingerprint = device_provider_policy_fingerprint(config)
    if (consent.expected_pack_fingerprint != pack.fingerprint
            or consent.expected_device_context_fingerprint != preparation.device_context_fingerprint
            or consent.provider != 'openai_responses' or consent.model != config.model
            or consent.expected_provider_policy_fingerprint != policy_fingerprint):
        raise HTTPException(409, {'code': 'device_ai_consent_mismatch',
            'message': 'Provider 同意六元组与服务端权威复算不一致；同意对象不成立，请重新预览授权'})
    # D4 非空+精确覆盖双断言按域适配（P1-4a）：tire 以 variant_id 集合断言（撤销 gate
    # 复用该集合；ai_execution 冻结侧消费平铺 variant_id+identity_contract，形状不变）。
    # vehicle/recall/recall_search 的归档引用没有 variant_id——以投影核冻结 reference 为
    # 身份键断言，不伪造 variant_id。仓库对这些域不存在可撤销生命周期（VehicleSnapshot/
    # RecallSnapshot 及其回执追加不可变、无 revoked 事件），覆盖断言即 device 分支内这些
    # 域的 D4 等价权利 gate：拒绝时只 409 不改写任何冻结事实。
    evidence = pack.payload.get('evidence')
    entries = [item for item in evidence if isinstance(item, dict)] if isinstance(evidence, list) else []
    contract = preparation.contract or {}
    expected_variants = {value for value in contract.get('variant_ids') or [] if value}
    expected_domains = {kind: {stable_json(ref) for ref in refs if isinstance(ref, dict)}
                        for kind, refs in (contract.get('domain_references') or {}).items()
                        if isinstance(refs, list)}
    embedded_variants = {item['variant_id'] for item in entries
                         if item.get('kind') == 'tire' and item.get('variant_id')}
    embedded_domains = {}
    for item in entries:
        if item.get('kind') == 'tire':
            continue
        reference = item.get('reference')
        if not isinstance(reference, dict) or not reference.get('kind'):
            raise HTTPException(409, {'code': 'device_ai_evidence_coverage',
                'message': '设备证据覆盖不完整：内嵌成员引用必须非空且精确覆盖准备记录的全部成员'})
        embedded_domains.setdefault(reference['kind'], set()).add(stable_json(reference))
    if (not entries or not (expected_variants or expected_domains)
            or embedded_variants != expected_variants or embedded_domains != expected_domains):
        raise HTTPException(409, {'code': 'device_ai_evidence_coverage',
            'message': '设备证据覆盖不完整：内嵌成员引用必须非空且精确覆盖准备记录的全部成员'})
    # D4 撤销 gate 在 claim 事务内重跑（与 legacy submit 闸门同语义；仅 tire 域有撤销
    # 生命周期；拒绝不改写冻结事实）。非 tire 域空集合为显式允许语义（仓库无对应实体）。
    from .lifecycle import annotate_variants
    if any(v['lifecycle']['state'] == 'revoked'
           for v in annotate_variants(db, [{'id': value} for value in sorted(embedded_variants)])):
        raise HTTPException(409, {'code': 'device_ai_variant_revoked',
            'message': '所选版本状态已撤销，请重新预览并生成新的准备记录'})
    try:
        # D18 方案B（Root 2026-10-03 批准）：Provider 请求体按 proposal-a.json:214 最小化
        # 组装，不再全量直发 pack.payload——device_context/manifest/member_reasons 等
        # 本机与审计细节结构性禁发；幂等不受影响（request_hash 只对 DTO 摘要，
        # request_contract.body_hash 是只写审计字段，无任何相等性消费方）。
        body, reserve = request_body(config, payload.question,
                                     _device_request_evidence({**pack.payload, 'data_state': pack.data_state}),
                                     stream=stream)
    except GatewayError as error:
        raise HTTPException(503, str(error)) from None
    # D9：claim 计划挂到本事务 session（同一 lock_ingestion 临界区内），由 reserve_response
    # 在 AIRequest flush 之后、commit 之前原子追加 DeviceAIConsentClaim。
    db.info[DEVICE_CLAIM_PLAN_KEY] = {'preparation_id': preparation.id, 'ai_pack_id': pack.id,
                                      'provider_consent_hash': digest(consent.model_dump()),
                                      'provider_policy_fingerprint': policy_fingerprint}
    return pack, config, body, reserve


def prepare_analysis(db, payload, session_id, *, stream=False):
    """Shared authorization for synchronous and asynchronously accepted analysis."""
    pack = owned_pack(db, payload.pack_id, session_id)
    if pack.payload.get('purpose') == 'rule_draft':
        raise HTTPException(422, '规则草稿须使用独立的生成和人工审核接口')
    # D1 DB 结构判别 device origin（ai_pack_id unique FK 是 authoritative discriminator）；
    # 不依赖 payload 字段形状，与 DTO 双向强制（N10）。
    preparation = db.scalar(select(DeviceAIPreparation).where(
        DeviceAIPreparation.ai_pack_id == pack.id, DeviceAIPreparation.actor_session_id == session_id))
    if preparation is not None and payload.device_submission is None:
        raise HTTPException(422, {'code': 'device_ai_submission_required',
            'message': '设备 AI 证据包必须携带 device_submission 提交'})
    if preparation is None and payload.device_submission is not None:
        raise HTTPException(422, {'code': 'device_ai_submission_not_allowed',
            'message': '常规证据包不能携带 device_submission'})
    if preparation is not None:
        if not stream:
            # 同步入口 device origin 一律 422 stream_only（proposal L181；路由#5）。
            raise HTTPException(422, {'code': 'device_ai_stream_only',
                'message': '设备 AI 分析仅支持流式入口提交（stream_only）'})
        return _prepare_device_analysis(db, payload, pack, preparation, stream=stream)
    try:
        validate_recall_payload(pack.payload)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(409, {'code': 'ai_recall_contract_stale',
            'message': '召回证据合同无效，请重新准备证据包'}) from None
    if utc(pack.expires_at) <= utcnow():
        raise HTTPException(409, '证据包已过期，请重新核对；当前查询会再次在线验证')
    if pack.mode == 'history' and CURRENT_WORDS.search(payload.question):
        raise HTTPException(409, '问题要求当前信息，请选择先在线核验；历史证据不能回答当前状态')
    if not payload.allow_external_processing:
        raise HTTPException(422, '分析需要明确允许将问题和所选证据发送到 OpenAI')
    try:
        config = configured_model()
        if pack.privacy_class == 'restricted' or pack.privacy_class != 'public' and not config.allow_private:
            raise HTTPException(403, '当前模型策略不允许发送这类非公开工作区证据')
        from .lifecycle import annotate_variants
        ids = [e['variant_id'] for e in pack.payload['evidence'] if e.get('variant_id')]
        if any(v['lifecycle']['state'] == 'revoked' for v in annotate_variants(db, [{'id': value} for value in ids])):
            raise HTTPException(409, '所选版本状态已撤销，请重新核对证据')
        from .test_events import latest
        for evidence in pack.payload['evidence']:
            if evidence.get('event_id'):
                event = latest(db, evidence['event_id'], evidence['revision'])
                if event.state == 'revoked':
                    raise HTTPException(409, '测试事件已撤销，请重新核对')
        body, reserve = request_body(config, payload.question, {**pack.payload, 'data_state': pack.data_state}, stream=stream)
    except GatewayError as error:
        raise HTTPException(503, str(error)) from None
    return pack, config, body, reserve


def register_ai_routes(app: FastAPI):
    app.state.ai_adapter = configured_adapter()

    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/ai/status')
    def status(db: Session = Depends(get_db)):
        return {'model': model_status(), 'budget': budget_usage(db), 'retrieval': 'exact_structured_lookup',
                'supports': ['selected_tire_evidence', 'historical_vehicle_evidence', 'historical_test_events',
                             'selected_recall_announcement_facts'],
                'notice': '配置状态不等于已连接验证。金额未估算；token 预算不是供应商账单金额上限。'}

    @app.get('/v1/ai/usage/history')
    def usage_history(days: int = Query(default=14, ge=1, le=90), db: Session = Depends(get_db)):
        from .embedding_budget import budget_history
        return budget_history(db, days)

    @app.post('/v1/ai/evidence-packs')
    async def prepare(payload: PreparePack, request: Request, db: Session = Depends(get_db)):
        return await prepare_pack(db, app.state.registry, payload, request.state.session_id,
                                  recall_adapter=getattr(app.state, 'recall_adapter', None))

    @app.get('/v1/ai/evidence-packs/{pack_id}')
    def evidence(pack_id: str, request: Request, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        return pack_view(owned_pack(db, pack_id, request.state.session_id))

    @app.post('/v1/ai/analyses')
    def analyze(payload: AnalysisRequest, request: Request, response: Response,
                      idempotency_key: str = Header(alias='Idempotency-Key', max_length=64), db: Session = Depends(get_db)):
        try:
            key = str(UUID(idempotency_key))
        except ValueError:
            raise HTTPException(422, 'Idempotency-Key 必须是 UUID') from None
        request_hash = digest(payload.model_dump())
        shared = QueryService(db, None)
        shared.lock_ingestion()
        existing = db.scalar(select(AIRequest).where(AIRequest.actor_session_id == request.state.session_id,
                                                    AIRequest.idempotency_key == key))
        if existing:
            if existing.request_hash != request_hash or existing.request_contract.get('purpose') == 'rule_draft':
                raise HTTPException(409, '同一幂等键不能用于不同问题或证据包')
            value = run_state(db, existing)
            db.commit()
            response.status_code = 202 if value['state'] == 'pending' else 200
            return value
        pack, config, body, reserve = prepare_analysis(db, payload, request.state.session_id)
        row = reserve_response(db, config=config, pack=pack, session_id=request.state.session_id, key=key,
            request_hash=request_hash, question=payload.question, reserve=reserve, body=body,
            contract=analysis_contract(pack.payload))
        execute_response(db, app, row, config, body, lambda value: grounded_answer(value, pack))
        return run_state(db, row)

    @app.get('/v1/ai/analyses/{request_id}')
    def get_analysis(request_id: str, request: Request, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        row = db.get(AIRequest, request_id)
        if row is None or row.actor_session_id != request.state.session_id or row.request_contract.get('purpose') == 'rule_draft':
            raise HTTPException(404, '未找到本会话的 AI 调用记录')
        return {**run_state(db, row), 'pack': pack_view(owned_pack(db, row.pack_id, request.state.session_id))}

    @app.get('/v1/ai/analyses')
    def history(request: Request, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        rows = db.execute(select(AIRequest, AICompletion)
            .outerjoin(AICompletion, AICompletion.request_id == AIRequest.id)
            .options(load_only(AICompletion.request_id, AICompletion.state, AICompletion.error_code,
                               AICompletion.usage, AICompletion.created_at))
            .where(AIRequest.actor_session_id == request.state.session_id)
            .where(or_(AIRequest.request_contract['purpose'].as_string().is_(None),
                       AIRequest.request_contract['purpose'].as_string() != 'rule_draft'))
            .order_by(desc(AIRequest.created_at), desc(AIRequest.id)).limit(20)).all()
        return {'scope': 'browser_session', 'items': [run_state(db, row, completion, prefetched=True,
                include_answer=False) for row, completion in rows]}
