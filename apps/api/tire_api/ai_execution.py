"""Shared Responses reservation and completion, independent of the output task."""
import asyncio
import json
import re

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .ai_gateway import GatewayError, safe_error, safe_usage
from .ai_models import AICompletion, AIRequest
from .db import uid
from .domain import digest
from .embedding_budget import budget_usage
from .service import QueryService

# 仓库 field 合同的 evidence 形状字段（D11：device evidence[] 必需但不得携带仓库形状）。
WAREHOUSE_EVIDENCE_KEYS = frozenset({'candidates', 'context_ref', 'reasons_ref', 'authority_ref', 'material_ref'})


def _decode_device_value(node):
    """device_ai_value_encoder.encode_value 的无损逆映射（仅用于 gate 比对，不是 wire 解码器）。

    device payload 的冻结身份合同里 current_identity 以 DeviceAIValue 编码形态落账
    （D15：数值只以 token DTO 出现）；require_frozen_identity_contracts 比对的是 DB 绑定
    的原值形态，故在进入 gate 前解码回原 JSON 值。number token 是原 exact lexeme，按
    JSON 数值解析后与 DB 中的解析值同形（"1.2300" 与 1.23 在两侧都归一到同一解析值）。
    """
    if not isinstance(node, dict):
        raise ValueError('invalid_device_identity_encoding')
    kind = node.get('kind')
    if kind == 'null':
        return None
    if kind in {'boolean', 'text'}:
        return node.get('value')
    if kind == 'number':
        token = node.get('value')
        if not isinstance(token, dict) or not isinstance(token.get('token'), str):
            raise ValueError('invalid_device_identity_encoding')
        try:
            return json.loads(token['token'])
        except (ValueError, TypeError):
            raise ValueError('invalid_device_identity_encoding') from None
    if kind == 'array':
        items = node.get('items')
        if not isinstance(items, list):
            raise ValueError('invalid_device_identity_encoding')
        return [_decode_device_value(child) for child in items]
    if kind == 'structured':
        fields = node.get('fields')
        if not isinstance(fields, list):
            raise ValueError('invalid_device_identity_encoding')
        value = {}
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get('name'), str):
                raise ValueError('invalid_device_identity_encoding')
            value[field['name']] = _decode_device_value(field.get('value'))
        return value
    raise ValueError('invalid_device_identity_encoding')


def _device_gate_evidence(payload):
    """D4：内嵌 evidence[] 的冻结身份合同解码回原值，使身份/撤销 gate 真实比对而非空转。"""
    result = []
    for item in payload.get('evidence', []):
        if not isinstance(item, dict) or not item.get('variant_id'):
            continue
        contract = item.get('identity_contract')
        if not isinstance(contract, dict) or 'current_identity' not in contract:
            result.append(item)
            continue
        try:
            decoded = _decode_device_value(contract['current_identity'])
        except ValueError:
            raise HTTPException(409, {'code': 'device_ai_identity_encoding_invalid',
                'message': '设备证据的冻结身份合同编码无效，请重新预览并生成新的准备记录'}) from None
        result.append({**item, 'identity_contract': {**contract, 'current_identity': decoded}})
    return result


def _device_preparation(db, pack, session_id):
    """D1/D5：按 ai_pack_id unique FK 回查 preparation——存在即 device origin。"""
    from .device_ai_models import DeviceAIPreparation
    return db.scalar(select(DeviceAIPreparation).where(DeviceAIPreparation.ai_pack_id == pack.id,
                                                       DeviceAIPreparation.actor_session_id == session_id))


def _require_device_preparation_contract(pack, preparation):
    """D5 替代合同：device 分支跳过仓库 require_frozen_field_contract，改为断言 preparation 的
    projection_hash/selection_hash/幂等绑定已 immutable 落账且本次提交与之一致；并执行
    D11 键名禁用（顶层仓库伪装键与 evidence[] 仓库形状字段）。"""
    from .device_ai_routes import FORBIDDEN_PAYLOAD_KEYS
    payload = pack.payload
    if FORBIDDEN_PAYLOAD_KEYS & payload.keys():
        raise HTTPException(409, {'code': 'device_ai_payload_keys_forbidden',
            'message': '设备证据包顶层含保留键或仓库合同伪装键，拒绝外发'})
    context = payload.get('device_context')
    if (not isinstance(context, dict) or context.get('projection_sha256') != preparation.projection_hash
            or context.get('selection_sha256') != preparation.selection_hash
            or context.get('device_context_fingerprint') != preparation.device_context_fingerprint):
        raise HTTPException(409, {'code': 'device_ai_preparation_contract_stale',
            'message': '设备证据包与准备记录的投影/选择/上下文绑定不一致，请重新预览并生成新的准备记录'})
    for item in payload.get('evidence', []):
        if isinstance(item, dict) and WAREHOUSE_EVIDENCE_KEYS & item.keys():
            raise HTTPException(409, {'code': 'device_ai_payload_keys_forbidden',
                'message': '设备证据条目携带仓库字段合同形状，拒绝外发'})


def reserve_response(db, *, config, pack, session_id, key, request_hash, question, reserve, body, contract, before_commit=None):
    from .ai_evidence import require_frozen_field_contract, require_frozen_identity_contracts
    from .identity_resolution import require_ai_identity
    from .ai_analysis import DEVICE_CLAIM_PLAN_KEY
    preparation = _device_preparation(db, pack, session_id)
    plan = None
    if preparation is not None:
        # D7 claim-or-nothing：本事务未注册 DeviceAIConsentClaim 追加计划则一律 409——
        # 对 ai_analysis/ai_stream_routes/ai_rule_drafts 三调用点结构强制，不依赖 purpose 标签。
        plan = db.info.pop(DEVICE_CLAIM_PLAN_KEY, None)
        if (not isinstance(plan, dict) or plan.get('preparation_id') != preparation.id
                or plan.get('ai_pack_id') != pack.id):
            raise HTTPException(409, {'code': 'device_ai_claim_required',
                'message': '设备 AI 材料必须经流式提交完成 Provider 同意绑定后才能外发'})
        # D9 锁内预查：同 preparation 第二个不同 analysis_key → 409（勿留 IntegrityError→500）。
        from .device_ai_models import DeviceAIConsentClaim
        claimed = db.scalar(select(DeviceAIConsentClaim).where(DeviceAIConsentClaim.preparation_id == preparation.id))
        if claimed is not None and claimed.analysis_key != key:
            raise HTTPException(409, {'code': 'device_ai_claim_conflict',
                'message': '该设备准备记录已被一次分析消费，请重新预览并生成新的准备记录'})
        # D4/D5：身份/当前权利 gate 经内嵌 evidence 真实生效；仓库字段合同由 preparation 绑定断言替代。
        gate_evidence = _device_gate_evidence(pack.payload)
        require_ai_identity(db, [item['variant_id'] for item in gate_evidence if item.get('variant_id')])
        require_frozen_identity_contracts(db, gate_evidence)
        _require_device_preparation_contract(pack, preparation)
    else:
        require_ai_identity(db, [item['variant_id'] for item in pack.payload.get('evidence', []) if item.get('variant_id')])
        require_frozen_identity_contracts(db, pack.payload.get('evidence', []))
        require_frozen_field_contract(pack.payload)
    budget = budget_usage(db)
    if budget['requests'] >= config.daily_request_limit or budget['accounted_tokens'] + reserve > config.daily_token_limit:
        raise HTTPException(429, '本地 AI 当日预算不足，未调用模型')
    if budget['has_pending_request']:
        raise HTTPException(429, '已有 AI 请求尚未确认完成，请先查看调用记录')
    extra_contract = {'origin': 'device_history', 'preparation_id': preparation.id} if preparation is not None else {}
    row = AIRequest(actor_session_id=session_id, idempotency_key=key, request_hash=request_hash,
        pack_id=pack.id, question=question, provider='openai_responses', model=config.model, reserved_tokens=reserve,
        request_contract={**contract, **extra_contract, 'body_hash': digest(body), 'max_output_tokens': config.max_output_tokens, 'store': False})
    db.add(row)
    db.flush()
    QueryService(db, None).audit(session_id, 'ai_request_started', request_id=row.id,
                               pack_id=pack.id, question_hash=digest(question), reserved_tokens=reserve,
                               **({'origin': 'device_history'} if preparation is not None else {}))
    if before_commit is not None:
        before_commit(db, row)
    if preparation is not None:
        # D9：AIRequest flush 之后、commit 之前，与 before_commit（create_execution_locked）
        # 同一事务原子追加 DeviceAIConsentClaim；禁止 upsert；IntegrityError 统一 409。
        from .device_ai_models import DeviceAIConsentClaim
        db.add(DeviceAIConsentClaim(id=uid(), actor_session_id=session_id, preparation_id=preparation.id,
            ai_request_id=row.id, analysis_key=key, request_hash=request_hash,
            provider_consent_hash=plan['provider_consent_hash'], provider='openai_responses',
            model=config.model, provider_policy_fingerprint=plan['provider_policy_fingerprint']))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, {'code': 'device_ai_claim_conflict',
                'message': '该设备准备记录已被一次分析消费，请重新预览并生成新的准备记录'}) from None
    db.commit()
    return row


def execute_response(db, app, row, config, body, validator):
    """Called in a FastAPI worker, after the durable reservation has committed."""
    from .telemetry import observe
    with observe('ai.response', component='ai') as operation:
        result = _execute_response(db, app, row, config, body, validator)
        operation.finish(result.state)
        return result


def _execute_response(db, app, row, config, body, validator):
    receipt = {'usage': None, 'provider_response_id': None}
    answer, error = None, None
    try:
        receipt = asyncio.run(app.state.ai_adapter.generate(config, body))
        error = safe_error(receipt['error']) if receipt.get('error') else None
        if not error:
            answer = validator(receipt['text'])
    except GatewayError as cause:
        error = safe_error(str(cause))
    except (ValidationError, ValueError, TypeError, KeyError, RecursionError):
        error = 'ai_grounding_validation_failed'
    except Exception:
        error = 'ai_provider_failed'
    if not isinstance(receipt, dict):
        receipt = {}
    response_id = receipt.get('provider_response_id')
    if not isinstance(response_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', response_id):
        response_id = None
    completion = AICompletion(request_id=row.id, state='failed' if error else 'completed',
        error_code=error, answer=answer, usage=safe_usage(receipt.get('usage')), provider_response_id=response_id)
    from .telemetry import record_ai_usage
    record_ai_usage('openai_responses', completion.usage)
    db.add(completion)
    QueryService(db, None).audit(row.actor_session_id, 'ai_request_finished', request_id=row.id,
                               state=completion.state, error_code=error)
    db.commit()
    return completion
