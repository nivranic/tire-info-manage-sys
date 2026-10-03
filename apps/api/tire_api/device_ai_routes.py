"""Metadata-only device AI prepare routes (roundtable routes #1/#2/#3, steps 2-3).

零外联（纪要 D13）：本模块不注入 adapter_registry/recall_adapter，不 import/调用
prepare_pack、RecallService 或 embedding 服务；provider_preview 只读
model_status()/configured_model() 的环境配置与共享日预算（本地 DB 读）。P1-4a 起
接受 tire/vehicle/recall/recall_search 四域 selector（各域 projection_mode 与投影核
converter 一一对应）；test_event 域仍 fail-closed 422（DTO Literal 封闭，N27），且
投影核对 test_event/restricted 恒拒（双保险）。

payload 组装（纪要 D9/D11）：业务数值只经 device_ai_value_encoder.encode_value 进
入 payload，禁止 as_token_dto()/token_dto() 输出当 DeviceAIValue；顶层禁用仓库
field 合同伪装键与 pack_view 保留冲突键，device 专有字段收进 device_context 子
对象；canonical SHA 一律从原 AST（投影 canonical bytes 重解析）计算。replay 命中
绝不改写行；IntegrityError 统一映射 409；禁止 upsert。
"""
from datetime import timedelta
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ai_analysis import _device_request_evidence
from .ai_evidence import pack_view
from .ai_gateway import (GatewayError, MAX_REQUEST_BYTES, configured_model, model_status,
                         outbound_measurement)
from .ai_models import AIEvidencePack
from .db import EvidenceObject, utc, utcnow
from .device_ai import DeviceAIPrepareRequest, canonical_request_hash, canonical_uuid
from .device_ai_archive import ArchiveLoadError, load_actor_owned_archive
from .device_ai_models import DeviceAIPreparation
from .device_ai_projection import ProjectionError, exact_digest, parse_exact_json, project_offline_pack
from .device_ai_value_encoder import encode_value
from .domain import digest
from .embedding_budget import budget_usage
from .service import QueryService, timestamp

PREPARATION_TTL = timedelta(seconds=1800)  # history 语义（纪要 D13），勿用 current 的 2min
SELECTION_NAMESPACE = 'device-ai-selection@1'  # 提案 namespace，冻结待 Root 批准（fingerprint-spec §2）
CONTEXT_NAMESPACE = 'device-ai-context@1'      # 提案 namespace，冻结待 Root 批准（fingerprint-spec §3）
CONTEXT_SCHEMA = 'device-ai-context@1'
NUMERIC_ENCODING = 'device-number-token@1'
QUESTION_UPPER_BOUND_CODEPOINTS = 2000
QUESTION_UPPER_BOUND_BYTES = QUESTION_UPPER_BOUND_CODEPOINTS * 4  # UTF-8 上界 ≈ 8,000B（纪要 D12）
# D11：payload 顶层禁用仓库 field 合同伪装键与 pack_view 保留键（data_state 值与行
# 数据一致，不属冲突键，予以保留供 grounding 语义）。
FORBIDDEN_PAYLOAD_KEYS = frozenset({
    'field_policy', 'field_resolutions', 'field_resolution_format', 'field_resolution_materials',
    'query_id', 'consent_id', 'recall_policy', 'recall_boundary',
    'mode', 'privacy_class', 'created_at', 'expires_at', 'fingerprint', 'id'})
# 投影核在重算内部即拒绝的容量/隐私码 → 422（fail-closed，不截断）；其余投影码对
# 冻结归档而言是期望/回执不一致 → 409（对齐 device_ai_archive_expected_mismatch）。
_PROJECTION_REJECTED = frozenset({'device_ai_projection_capacity', 'device_ai_selected_restricted'})


def _canonical_key(value: str) -> str:
    try:
        return canonical_uuid(value)
    except ValueError:
        raise HTTPException(422, 'Idempotency-Key 必须是 UUID') from None


def register_device_ai_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    def _view(db: Session, row: DeviceAIPreparation) -> dict:
        """owned 精确视图；过期返回原记录+expires_at（不改写，submit 侧 gate 拒绝）。"""
        pack = db.get(AIEvidencePack, row.ai_pack_id)
        return {'id': row.id, 'created_at': timestamp(row.created_at),
                'expires_at': timestamp(row.expires_at), 'expired': utc(row.expires_at) <= utcnow(),
                'idempotency_key': row.idempotency_key, 'host_receipt_id': row.host_receipt_id,
                'intent_id': row.intent_id, 'pack_id': row.ai_pack_id,
                'offline_pack_id': row.offline_pack_id, 'question_sha256': row.question_sha256,
                'selection_sha256': row.selection_hash, 'projection_sha256': row.projection_hash,
                'projection_byte_count': row.projection_byte_count,
                'device_context_fingerprint': row.device_context_fingerprint,
                'request_hash': row.request_hash, 'contract': row.contract,
                'pack': pack_view(pack)}

    def _outbound_budget(db: Session, content: dict, data_state: str, projection_byte_count: int,
                         config) -> dict:
        """prepare 预检（纪要 D12 + D18 方案B）：与 submit 侧共用同一最小化组装与
        request_body 同式计量，真实值+上界并列。

        question 明文不在 prepare 出现，占位用 2,000 codepoints 的 UTF-8 上界；dispatch
        材料按 D18 方案B最小化组装计量（Root 2026-10-03 批准，proposal-a.json:214）：
        device_context/manifest/member_reasons 等 本机与审计细节结构性不外发，计量
        不再叠加投影 canonical 字节（策略A"全量直发上界"已废弃；projection_bytes 仅
        保留为观测量）。submit 侧对同一 pack.payload 走同一 _device_request_evidence +
        outbound_measurement，预检与真实 dispatch 不可能漂移成两个预算。预检不豁免
        submit 的真实计量；blocked 只在上界确实超限时置位并附缺口，禁止为适配容量
        的截断。
        """
        evidence = _device_request_evidence({**content, 'data_state': data_state})
        placeholder = '\U0001d546' * QUESTION_UPPER_BOUND_CODEPOINTS  # 4 字节/码点，JSON 无转义
        floor_bytes, _floor_reserve = outbound_measurement('', evidence, max_output_tokens=0)
        upper_bytes, upper_reserve = outbound_measurement(
            placeholder, evidence, max_output_tokens=config.max_output_tokens if config is not None else 0)
        result = {'basis': 'shared request_body measurement + D18 scheme-B minimal assembly',
                  'evidence_only_request_bytes': floor_bytes, 'upper_bound_request_bytes': upper_bytes,
                  'question_upper_bound_bytes': QUESTION_UPPER_BOUND_BYTES,
                  'projection_bytes': projection_byte_count, 'limit_bytes': MAX_REQUEST_BYTES,
                  'blocked': upper_bytes > MAX_REQUEST_BYTES,
                  'shortfall_bytes': max(0, upper_bytes - MAX_REQUEST_BYTES),
                  'truncated': False,
                  'reserve_tokens_upper_bound': upper_reserve if config is not None else None}
        if config is None:
            result['daily_budget'] = {'state': 'model_not_configured'}
            return result
        try:
            budget = budget_usage(db)
        except Exception:  # 预览绝不失败 prepare 本身
            result['daily_budget'] = {'state': 'unavailable'}
            return result
        result['daily_budget'] = {
            'requests': budget['requests'], 'accounted_tokens': budget['accounted_tokens'],
            'daily_request_limit': config.daily_request_limit, 'daily_token_limit': config.daily_token_limit,
            'has_pending_request': budget['has_pending_request'],
            'blocked': (budget['requests'] >= config.daily_request_limit
                        or budget['accounted_tokens'] + upper_reserve > config.daily_token_limit
                        or budget['has_pending_request'])}
        return result

    def _provider_preview(db: Session, content: dict, data_state: str, projection_byte_count: int) -> dict:
        """仅环境配置与本地 DB 读（D13 零外联）；不触发任何 Provider 调用。"""
        try:
            config = configured_model()
        except GatewayError:
            config = None
        preview = dict(model_status())
        preview['outbound_budget'] = _outbound_budget(db, content, data_state, projection_byte_count, config)
        return preview

    def _append_preparation(db: Session, payload: DeviceAIPrepareRequest, session_id: str,
                            key: str, request_hash: str) -> tuple[DeviceAIPreparation, dict]:
        # 十一步 gate（纪要 D10）：closed schema 与幂等 replay 已在 handler 完成；
        # owned archive 加载（404 先于 expected 409）→ content/SHA 校验与 exact parse
        # （loader 内 checked + parse_exact_json）→ selectors/闭包重算 → 期望投影比对
        # → privacy/rights/capacity（投影核内封死）→ 身份预检 → EvidenceObject →
        # AIEvidencePack → DeviceAIPreparation → audit → commit。
        try:
            owned = load_actor_owned_archive(db, actor_session_id=session_id,
                                             package_id=payload.package_id,
                                             expected_sha256=payload.expected_sha256,
                                             expected_byte_count=payload.expected_byte_count,
                                             expected_schema=payload.expected_schema,
                                             expected_owner_scope_id=payload.expected_owner_scope_id)
        except ArchiveLoadError as error:
            raise HTTPException(error.status_code, {'code': error.code,
                'message': '归档原件加载失败，未创建任何准备记录'}) from None
        binding = owned.binding
        selectors = [item.model_dump() for item in payload.selectors]
        closure = None if payload.approved_closure is None else [item.model_dump() for item in payload.approved_closure]
        try:
            projection = project_offline_pack(owned.raw_bytes, binding, selectors,
                                              mode=payload.projection_mode, approved_closure=closure)
        except ProjectionError as error:
            status = 422 if error.code in _PROJECTION_REJECTED else 409
            raise HTTPException(status, {'code': error.code,
                'message': '投影重算被拒绝；不改写归档、不截断材料，请重新预览选择'}) from None
        if projection.sha256 != payload.expected_projection_sha256:
            raise HTTPException(409, {'code': 'device_ai_projection_mismatch',
                'message': '期望投影摘要与服务端重算不一致，请重新预览后再试'})
        # canonical 材料一律从原 AST（投影 canonical bytes）重取，不从 DTO 反推。
        material = parse_exact_json(projection.canonical_bytes)
        observations = material['observations']
        # D10 补强一（死包预防，tire 域）：归档时身份非 current 的成员 prepare 即 fail
        # early，避免用户走完 Host 预览/一次导出/Provider 同意后 submit 恒 409 的同意
        # 空转。以投影核实际输出为准：仅 tire material 携带 frozen_identity_contract
        #（_tire 专属）；vehicle/recall/recall_search 的冻结身份就是离线引用+回执本身
        #（投影核 _receipt_evidence 已在重算内封死），无身份合同可预检。
        for observation in observations:
            identity = observation['material'].get('frozen_identity_contract')
            if isinstance(identity, dict) and identity.get('state') != 'current':
                raise HTTPException(409, {'code': 'device_ai_identity_not_current',
                    'message': '所选成员的归档身份合同不是 current，submit 将恒被拒绝；请先完成身份归并并重新导出'})
        selector_values = [observation['selector'] for observation in observations]
        selection_hash = exact_digest(selector_values, namespace=SELECTION_NAMESPACE)
        # 各域边界对象按投影核实际输出记录（recall/recall_search material 带 boundary；
        # tire material 无 boundary 对象，保持 []）。
        domain_boundaries = [{'kind': observation['selector']['reference']['kind'],
                              'boundary': observation['material']['boundary']}
                             for observation in observations
                             if isinstance(observation['material'].get('boundary'), dict)]
        context_identity = {
            'schema': CONTEXT_SCHEMA,
            'package_id': binding.package_id, 'package_schema': binding.schema,
            'package_sha256': binding.sha256, 'projection_mode': payload.projection_mode,
            'projection_sha256': projection.sha256, 'selection_sha256': selection_hash,
            'receipt_sources': [{'selector': observation['selector'],
                                 'selection_reason': observation['selection_reason'],
                                 'source': observation['source']} for observation in observations],
            'device_citations': [],   # 引用 wrapper 形状未冻结（D15/N28），本波不生成
            'domain_boundaries': domain_boundaries,
            'numeric_encoding': NUMERIC_ENCODING}
        context_hash = exact_digest(context_identity, namespace=CONTEXT_NAMESPACE)
        evidence_entries = []
        for index, observation in enumerate(observations, start=1):
            reference = observation['selector']['reference']
            entry = {'id': f'e{index}', 'member_key': observation['selector']['member_key'],
                     'observed_at': observation['source']['observed_at'],
                     'verified_at': observation['source']['verified_at']}
            if reference['kind'] == 'tire':
                identity = observation['material']['frozen_identity_contract']
                entry.update({
                    'kind': reference['kind'],
                    'snapshot_id': reference['snapshot_id'], 'variant_id': reference['variant_id'],
                    'verification_id': reference['verification_id'],
                    # 冻结身份合同 5 字段保持 gate 可消费的平铺形态；业务数值
                    # （current_identity 中的数字）只以 encode_value 的 DeviceAIValue 形态出现。
                    'identity_contract': {
                        'schema': identity['schema'], 'state': identity['state'],
                        'current_key': identity['current_key'],
                        'current_identity': encode_value(identity['current_identity']),
                        'identity_status': identity['identity_status']}})
            else:
                # 非 tire 域：冻结身份=离线引用本身，收进 reference 子对象原样落账。
                # 顶层不落 kind/recall_revision_id 等仓库 recall 合同 matcher 的别名键
                #（ai_recall_contract.is_recall_evidence 逐键匹配 evidence 顶层），确保
                # device payload 永不触发仓库 recall 合同（D17 分流：device 路径只按
                # origin/device 合同消费，不伪装仓库形状、也不借道 matcher）。
                entry['reference'] = dict(reference)
            evidence_entries.append(entry)
        # contract 冗余按域记录：tire 的对应物是 variant_ids（撤销 gate 复用）；非 tire
        # 域的对应物是 domain_references（投影核冻结引用原样，submit 侧 D4 覆盖断言消费）。
        domain_references = {}
        for observation in observations:
            reference = observation['selector']['reference']
            if reference['kind'] != 'tire':
                domain_references.setdefault(reference['kind'], []).append(dict(reference))
        content = {
            'purpose': 'device_history_analysis', 'origin': 'device_history',
            'evidence': evidence_entries,
            # fact 文本渲染属 submit 侧 Provider 组装（facts 渲染仍待后续波次），
            # 本波不展开，仅保留 grounding 最小形状顶层键（facts/evidence/conflicts/
            # source_state/data_state）；外发投影由 _device_request_evidence 白名单
            # 组装（D18 方案B，specs/d18-minimal-assembly.md）。
            'facts': [], 'conflicts': [], 'source_state': 'snapshot', 'data_state': 'local_snapshot',
            'device_context': {
                'schema': CONTEXT_SCHEMA, 'device_context_fingerprint': context_hash,
                'package_id': binding.package_id, 'package_schema': binding.schema,
                'package_sha256': binding.sha256, 'projection_mode': payload.projection_mode,
                'projection_sha256': projection.sha256,
                'projection_byte_count': len(projection.canonical_bytes),
                'selection_sha256': selection_hash, 'question_sha256': payload.question_sha256,
                'member_count': projection.member_count, 'numeric_encoding': NUMERIC_ENCODING}}
        if FORBIDDEN_PAYLOAD_KEYS & content.keys():
            raise ValueError('device payload 顶层键违反 D11 禁用清单')
        try:
            store = db.info['object_store']
            store.put(projection.canonical_bytes)
        except Exception:  # ObjectStoreError/配置失败：封闭编码，不外泄路径/凭据
            raise HTTPException(503, {'code': 'device_ai_projection_object_unavailable',
                'message': '投影对象存储不可用，未创建任何准备记录'}) from None
        if db.get(EvidenceObject, projection.sha256) is None:
            db.add(EvidenceObject(raw_hash=projection.sha256, byte_count=len(projection.canonical_bytes)))
        now = utcnow()
        pack = AIEvidencePack(actor_session_id=session_id, mode='history', data_state='local_snapshot',
                              privacy_class='private', payload=content, fingerprint=digest(content),
                              created_at=now, expires_at=now + PREPARATION_TTL)
        db.add(pack)
        db.flush()
        contract = {'schema': 'device-ai-prepare@1', 'purpose': 'device_history_analysis',
                    'projection_mode': payload.projection_mode,
                    'variant_ids': [entry['variant_id'] for entry in evidence_entries
                                    if entry.get('kind') == 'tire'],
                    'domain_references': domain_references,
                    'member_keys': [value['member_key'] for value in selector_values],
                    'question_sha256': payload.question_sha256, 'package_id': binding.package_id,
                    'package_sha256': binding.sha256, 'selection_sha256': selection_hash,
                    'projection_sha256': projection.sha256, 'device_context_fingerprint': context_hash}
        row = DeviceAIPreparation(actor_session_id=session_id, idempotency_key=key,
                                  request_hash=request_hash, offline_pack_id=binding.package_id,
                                  offline_content_hash=binding.sha256,
                                  host_receipt_id=payload.host_receipt_id, intent_id=payload.intent_id,
                                  selection_hash=selection_hash, projection_hash=projection.sha256,
                                  projection_byte_count=len(projection.canonical_bytes),
                                  device_context_fingerprint=context_hash,
                                  question_sha256=payload.question_sha256, ai_pack_id=pack.id,
                                  contract=contract, created_at=now, expires_at=now + PREPARATION_TTL)
        db.add(row)
        db.flush()
        QueryService(db, None).audit(session_id, 'device_ai_preparation_created', preparation_id=row.id,
                                     pack_id=pack.id, projection_sha256=projection.sha256,
                                     selection_sha256=selection_hash, device_context_fingerprint=context_hash)
        preview = _provider_preview(db, content, 'local_snapshot', len(projection.canonical_bytes))
        db.commit()
        return row, preview

    @app.post('/v1/ai/device-evidence-packs', status_code=201)
    def prepare_device_evidence_pack(payload: DeviceAIPrepareRequest, request: Request, response: Response,
                                     idempotency_key: str = Header(alias='Idempotency-Key', max_length=64),
                                     db: Session = Depends(get_db)) -> dict:
        session_id = request.state.session_id
        key = _canonical_key(idempotency_key)
        request_hash = canonical_request_hash(payload)
        QueryService(db, None).lock_ingestion()
        # replay 幂等先行（先于一切归档/store 数据访问）；命中绝不改写行。
        existing = db.scalar(select(DeviceAIPreparation).where(
            DeviceAIPreparation.actor_session_id == session_id,
            DeviceAIPreparation.idempotency_key == key))
        if existing is not None:
            if existing.request_hash != request_hash:
                raise HTTPException(409, {'code': 'device_ai_prepare_idempotency_mismatch',
                                          'message': '同一幂等键不能用于不同请求体'})
            response.status_code = 200
            return {**_view(db, existing), 'replayed': True}
        try:
            row, preview = _append_preparation(db, payload, session_id, key, request_hash)
        except IntegrityError:
            # (actor, host_receipt_id)/(actor, intent_id)/(actor, idempotency_key) 唯一
            # 约束兜底：统一映射 409，不外泄 IntegrityError；禁止 upsert。
            db.rollback()
            raise HTTPException(409, {'code': 'device_ai_prepare_conflict',
                'message': '该幂等键、host 回执或 intent 已绑定既有准备记录；请用 lookup 恢复'}) from None
        return {**_view(db, row), 'replayed': False, 'provider_preview': preview}

    # literal 路由必须先于参数路由注册（纪要 #2；对齐 ai_stream_routes.py 的既有形态）。
    @app.get('/v1/ai/device-evidence-packs/lookup')
    def lookup(request: Request, mode: Literal['history'] = Query(...),
               idempotency_key: str = Query(..., max_length=64), db: Session = Depends(get_db)):
        key = _canonical_key(idempotency_key)
        row = db.scalar(select(DeviceAIPreparation).where(
            DeviceAIPreparation.actor_session_id == request.state.session_id,
            DeviceAIPreparation.idempotency_key == key))
        if row is None:
            raise HTTPException(404, '未找到本会话的设备 AI 准备记录')
        return _view(db, row)

    @app.get('/v1/ai/device-evidence-packs/{prepare_id}')
    def preparation_detail(prepare_id: str, request: Request, mode: Literal['history'] = Query(...),
                           db: Session = Depends(get_db)):
        row = db.get(DeviceAIPreparation, prepare_id)
        if row is None or row.actor_session_id != request.state.session_id:
            raise HTTPException(404, '未找到本会话的设备 AI 准备记录')
        return _view(db, row)
