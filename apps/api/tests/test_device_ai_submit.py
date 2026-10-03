"""隔离路由测试：设备 AI submit/执行侧（圆桌纪要步骤4/5/6 验证段全量）。

对齐第一波 test_device_ai_routes_prepare.py 的隔离形态（文件库 + 临时对象目录 +
FixtureRegistry + producer-v2 样本），并沿用 test_ai_stream_api.py 的 HeldModel 流式
mock（TI_AI_ENABLED=0 下 monkeypatch configured_model，禁真实模型/网络）。身份/撤销
gate 需要服务端 DB 权威值：正例在本地库种 TireVariant + VariantIdentityBinding（经
_new_binding 计算 fingerprint），使 require_ai_identity/require_frozen_identity_contracts
对内嵌冻结身份合同真实比对生效。过期/撤销边界用 text() SQL 直改或直接落行模拟。
"""
import asyncio
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select, text

from tire_api import ai_analysis, ai_execution
from tire_api import ai_stream_store as store
from tire_api.ai_gateway import OpenAIConfig, request_body
from tire_api.ai_models import AIEvidencePack, AIRequest
from tire_api.db import AuditEvent, EvidenceObject, TireVariant, VariantLifecycleEvent, utc, utcnow
from tire_api.device_ai_models import DeviceAIConsentClaim, DeviceAIPreparation
from tire_api.device_ai_projection import FrozenPackBinding
from tire_api.device_ai_value_encoder import encode_value
from tire_api.domain import digest
from tire_api.identity_contract import _new_binding
from tire_api.main import create_app
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from test_core import FixtureRegistry

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / '.artifacts/query-fallback49/producer-v2-samples-a'
QUESTION = 'P225 这条轮胎的历史参数如何解读？'
OTHER_QUESTION = '这条轮胎的载重与速度级别如何解读？'
FACT_TEXT = '该观察记录的胎面宽度字段为 225（历史快照，未在线核验）'
# D18 方案B红线（specs/d18-minimal-assembly.md）：这些键不得以外发形态出现——
# device_context 本机细节、包内成员键、manifest、member_reasons、未选 contexts、
# 审计绑定哈希与计数。红线按序列化子串断言：任一出现即测试失败。
OUTBOUND_RED_LINE = ('device_context', 'member_key', 'member_reasons', 'manifest', 'contexts',
                     'profile_id', 'owner_epoch', 'slot', 'host_receipt_id', 'intent_id',
                     'package_id', 'package_schema', 'package_sha256', 'projection_mode',
                     'projection_sha256', 'projection_byte_count', 'selection_sha256',
                     'question_sha256', 'device_context_fingerprint', 'member_count',
                     'numeric_encoding', 'purpose', 'origin')


def tire_member(envelope):
    return next(member for member in envelope['members'] if member['reference']['kind'] == 'tire')


def tire_selector(envelope):
    member = tire_member(envelope)
    document = next(row for row in envelope['documents'] if row['member_key'] == member['key'])
    return {'kind': 'tire', 'member_key': member['key'], 'document_id': document['id'],
            'record_index': None, 'reference': dict(member['reference'])}


def finalize_bytes(envelope):
    raw = json.dumps(envelope, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return raw, hashlib.sha256(raw).hexdigest()


class HeldDeviceModel:
    """设备包专用合成流：device facts 为空时合法输出只有空 claims + 非空 uncertainty。

    script 可注入完整响应（grounding 正例用 fact claim）；bodies 记录每次外发请求体，
    供 D18 方案B 最小化组装断言（外发材料=剥离本机细节后的白名单投影）。
    """

    def __init__(self, script=None):
        self.calls = 0
        self.release = threading.Event()
        self.script = script or '{"claims":[],"uncertainty":"synthetic device stream"}'
        self.bodies = []

    async def stream(self, config, body, on_text):
        assert body['stream'] is True and body['store'] is False and body['background'] is False and body['tools'] == []
        self.calls += 1
        self.bodies.append(deepcopy(body))
        half = self.script[:len(self.script) // 2]
        await on_text(half)
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        await on_text(self.script[len(self.script) // 2:])
        return {'text': self.script, 'error': None,
                'usage': {'input_tokens': 320, 'output_tokens': 40, 'total_tokens': 360},
                'provider_response_id': 'resp_synthetic_device'}

    def outbound_evidence(self):
        """解析第 N 次外发 user_input，返回 (question, untrusted_evidence_pack)。"""
        user_input = self.bodies[0]['input'][1]['content']
        value = json.loads(user_input)
        return value['question'], value['untrusted_evidence_pack']


class RouteEnv:
    def __init__(self, client, app, session_id, model):
        self.client, self.app, self.session_id, self.model = client, app, session_id, model

    def seed(self, *, name='nonempty'):
        original = (SAMPLES / f'{name}-pack.json').read_bytes()
        descriptor = json.loads((SAMPLES / f'{name}-descriptor.json').read_bytes())
        envelope = json.loads(original)
        envelope['owner_scope_id'] = digest({'namespace': 'offline-owner-scope@1', 'session': self.session_id})
        raw, sha = finalize_bytes(envelope)
        descriptor.update(sha256=sha, byte_count=len(raw), owner_scope_id=envelope['owner_scope_id'])
        store_root = self.app.state.database.object_store
        assert store_root.put(raw) == sha
        with self.app.state.database.sessions() as db:
            db.add(EvidenceObject(raw_hash=sha, byte_count=len(raw)))
            db.flush()
            now = utcnow()
            db.add(OfflinePackPlan(id=descriptor['plan_id'], package_id=descriptor['id'],
                                   actor_session_id=self.session_id, fingerprint=descriptor['plan_fingerprint'],
                                   preview={}, content_hash=sha, byte_count=len(raw),
                                   created_at=now, expires_at=now + timedelta(minutes=30)))
            db.flush()
            db.add(OfflinePack(id=descriptor['id'], plan_id=descriptor['plan_id'],
                               actor_session_id=self.session_id, idempotency_key=str(uuid4()),
                               request_hash='a' * 64, content_hash=sha, byte_count=len(raw),
                               descriptor=descriptor))
            db.commit()
        return raw, descriptor, envelope

    def prepare_body(self, seeded, *, question=QUESTION):
        raw, descriptor, envelope = seeded
        chosen = tire_selector(envelope)
        binding = FrozenPackBinding(descriptor['id'], descriptor['owner_scope_id'], descriptor['sha256'],
                                    descriptor['byte_count'], envelope['schema'])
        from tire_api.device_ai_projection import project_offline_pack
        expected = project_offline_pack(raw, binding, [dict(chosen)]).sha256
        return {'package_id': descriptor['id'], 'expected_sha256': descriptor['sha256'],
                'expected_byte_count': descriptor['byte_count'], 'expected_schema': envelope['schema'],
                'expected_owner_scope_id': descriptor['owner_scope_id'], 'selectors': [chosen],
                'projection_mode': 'single_observation', 'expected_projection_sha256': expected,
                'question_sha256': hashlib.sha256(question.encode('utf-8')).hexdigest(),
                'host_receipt_id': str(uuid4()), 'intent_id': str(uuid4())}

    def prepare(self, seeded, *, question=QUESTION):
        response = self.client.post('/v1/ai/device-evidence-packs', json=self.prepare_body(seeded, question=question),
                                    headers={'Idempotency-Key': str(uuid4())})
        assert response.status_code == 201, response.text
        return response.json()

    def seed_identity(self, seeded):
        """正例前置：为归档 variant 种 TireVariant + VariantIdentityBinding，使身份/撤销 gate 真实生效。"""
        _raw, _descriptor, envelope = seeded
        member = tire_member(envelope)
        identity = member['payload']['identity_contract']
        variant_id = member['reference']['variant_id']
        with self.app.state.database.sessions() as db:
            db.add(TireVariant(id=variant_id, identity_key=identity['current_key'],
                               identity=identity['current_identity'], identity_status=identity['identity_status']))
            db.flush()
            db.add(_new_binding(variant_id=variant_id, key=identity['current_key'],
                                identity=identity['current_identity'], status=identity['identity_status'],
                                origin='source_observation', proof={'synthetic': 'device-submit-fixture'}))
            db.commit()
        return variant_id

    def count(self, model):
        with self.app.state.database.sessions() as db:
            return db.scalar(select(func.count()).select_from(model))

    def read(self, request_id):
        response = self.client.get('/v1/ai/analysis-streams/' + request_id, params={'mode': 'history'})
        assert response.status_code == 200, response.text
        return response.json()

    def until(self, request_id, predicate):
        deadline = time.monotonic() + 5
        while True:
            data = self.read(request_id)
            if predicate(data):
                return data
            assert time.monotonic() < deadline, data['execution']
            time.sleep(0.01)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv('TI_OBJECT_STORE_BACKEND', 'filesystem')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    monkeypatch.setenv('TI_OBSERVABILITY_ENABLED', '0')
    monkeypatch.setattr(ai_analysis, 'configured_model', lambda: OpenAIConfig(
        model='synthetic-device', api_key='synthetic-never-live', allow_private=True))
    app = create_app('sqlite:///' + (tmp_path / 'device-submit.sqlite').as_posix(), FixtureRegistry())
    model = HeldDeviceModel()
    app.state.ai_adapter = model  # 必须先于 lifespan：supervisor 在启动时绑定 adapter
    with TestClient(app) as client:
        client.get('/health')
        yield RouteEnv(client, app, client.cookies['tire_local_session'], model)
        model.release.set()


def submission(env, value, *, question=QUESTION, consent_changes=None, submission_changes=None):
    consent = {
        'expected_pack_fingerprint': value['pack_fingerprint'] if 'pack_fingerprint' in value else value['pack']['fingerprint'],
        'expected_device_context_fingerprint': value['device_context_fingerprint'],
        'question_sha256': hashlib.sha256(question.encode('utf-8')).hexdigest(),
        'provider': 'openai_responses',
        'model': 'synthetic-device',
        'expected_provider_policy_fingerprint': ai_analysis.device_provider_policy_fingerprint(
            ai_analysis.configured_model()),
    }
    consent.update(consent_changes or {})
    body = {'pack_id': value['pack_id'], 'question': question, 'allow_external_processing': True,
            'device_submission': {'prepare_id': value['prepare_id'] if 'prepare_id' in value else value['id'],
                                  'host_receipt_id': value['host_receipt_id'],
                                  'device_context_fingerprint': value['device_context_fingerprint'],
                                  'provider_consent': consent}}
    body.update(submission_changes or {})
    return body


def submit_stream(env, body, key=None):
    return env.client.post('/v1/ai/analysis-streams', json=body,
                           headers={'Idempotency-Key': key or str(uuid4())})


def submit_sync(env, body, key=None):
    return env.client.post('/v1/ai/analyses', json=body,
                           headers={'Idempotency-Key': key or str(uuid4())})


def prepared_chain(env):
    seeded = env.seed()
    env.seed_identity(seeded)
    return seeded, env.prepare(seeded)


# ---------------------------------------------------------------- 正例：完整链

def test_full_device_chain_prepare_submit_claim_request_execution(env):
    _seeded, value = prepared_chain(env)
    key = str(uuid4())
    response = submit_stream(env, submission(env, value), key)
    assert response.status_code == 202, response.text
    request_id = response.json()['analysis']['id']
    assert response.json()['replayed'] is False
    running = env.until(request_id, lambda v: v['execution']['state'] == 'running')
    assert running['analysis']['answer'] is None  # draft 仍非最终结论
    env.model.release.set()
    done = env.until(request_id, lambda v: v['execution']['terminal'])
    assert done['execution']['state'] == done['analysis']['state'] == 'completed'
    assert done['analysis']['answer']['claims'] == []
    assert done['analysis']['answer']['uncertainty'] == 'synthetic device stream'
    assert env.model.calls == 1
    # D18 方案B：外发请求体=最小化组装（正例链断言）。模型只看到 question + 白名单
    # 投影；本机/审计/凭据类字段结构性缺席（红线扫描），服务器侧 pack 保留完整映射。
    question, sent = env.model.outbound_evidence()
    assert question == QUESTION
    assert set(sent) == {'facts', 'evidence', 'conflicts', 'source_state', 'data_state'}
    serialized = json.dumps(sent, ensure_ascii=False)
    for forbidden in OUTBOUND_RED_LINE:
        assert forbidden not in serialized, forbidden
    assert sent['facts'] == [] and sent['conflicts'] == []
    assert sent['source_state'] == 'snapshot' and sent['data_state'] == 'local_snapshot'
    entry = sent['evidence'][0]
    assert entry['id'] == 'e1'
    assert {'kind', 'snapshot_id', 'variant_id', 'verification_id', 'observed_at',
            'verified_at', 'identity_contract'} <= set(entry)
    # 请求合同带 origin 冗余（authoritative 判别仍在 preparation 表）。
    contract = done['analysis']['request_contract']
    assert contract['origin'] == 'device_history' and contract['preparation_id'] == value['id']
    assert contract['delivery_mode'] == 'stream'
    # detail 返回 owned device pack 精确视图 + device 块（路由#8）。
    assert done['analysis']['pack']['device_context']['question_sha256'] == value['question_sha256']
    assert done['analysis']['device']['origin'] == 'device_history'
    assert done['analysis']['device']['preparation_id'] == value['id']
    assert done['analysis']['device']['claim']['analysis_key'] == key
    events = env.client.get('/v1/ai/analysis-streams/' + request_id + '/events').json()
    assert [row['type'] for row in events['items']] == ['accepted', 'started', 'uncertainty_draft', 'completed']
    with env.app.state.database.sessions() as db:
        row = db.get(AIRequest, request_id)
        assert row.actor_session_id == env.session_id and row.question == QUESTION
        assert row.provider == 'openai_responses' and row.model == 'synthetic-device'
        assert row.request_contract['origin'] == 'device_history'
        assert row.request_contract['preparation_id'] == value['id']
        claim = db.scalar(select(DeviceAIConsentClaim).where(DeviceAIConsentClaim.ai_request_id == request_id))
        assert claim is not None
        assert claim.preparation_id == value['id'] and claim.analysis_key == key
        assert claim.actor_session_id == env.session_id  # D8.6 一律取 request.state.session_id
        assert claim.provider == 'openai_responses' and claim.model == 'synthetic-device'
        assert claim.provider_policy_fingerprint == ai_analysis.device_provider_policy_fingerprint(
            ai_analysis.configured_model())
        assert len(claim.provider_consent_hash) == 64 and len(claim.request_hash) == 64
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == 'ai_request_started'))
        assert audit.session_id == env.session_id and audit.detail['request_id'] == request_id
        assert audit.detail['origin'] == 'device_history'
    assert env.count(AIRequest) == 1 and env.count(DeviceAIConsentClaim) == 1
    # lookup-first 恢复（N18）：只读，不重启模型。
    lookup = env.client.get('/v1/ai/analysis-streams/lookup', params={'mode': 'history', 'idempotency_key': key})
    assert lookup.status_code == 200 and lookup.json()['analysis']['id'] == request_id
    assert lookup.json()['analysis']['device']['claim']['analysis_key'] == key
    assert env.model.calls == 1


def test_same_key_replay_returns_detail_without_restarting_model_n18(env):
    _seeded, value = prepared_chain(env)
    key = str(uuid4())
    first = submit_stream(env, submission(env, value), key)
    assert first.status_code == 202
    request_id = first.json()['analysis']['id']
    env.model.release.set()
    env.until(request_id, lambda v: v['execution']['terminal'])
    replay = submit_stream(env, submission(env, value), key)
    assert replay.status_code == 200 and replay.json()['replayed'] is True
    assert replay.json()['analysis']['id'] == request_id
    assert replay.json()['analysis']['state'] == 'completed'
    assert replay.json()['analysis']['device']['preparation_id'] == value['id']
    assert env.model.calls == 1
    assert env.count(AIRequest) == 1 and env.count(DeviceAIConsentClaim) == 1
    # 同 key 异 body 仍被幂等闸门拒绝。
    mismatch = submit_stream(env, submission(env, value, question=OTHER_QUESTION), key)
    assert mismatch.status_code == 409 and mismatch.json()['detail']['code'] == 'idempotency_payload_mismatch'
    assert env.model.calls == 1


# ---------------------------------------------------------------- D18 方案B：最小化组装

def test_d18_minimal_assembly_red_line_strips_local_details_unit():
    """红线负例（纯函数）：payload 即便携带本机/审计/凭据类字段，组装结果也必须剥离。"""
    payload = {'purpose': 'device_history_analysis', 'origin': 'device_history',
               'facts': [{'id': 'f1', 'text': FACT_TEXT, 'evidence_id': 'e1', 'domain': 'tire',
                          'field_code': 'tire.tread_width', 'member_reasons': ['local'],
                          'raw_blob': 'local-only-material'}],
               'evidence': [{'id': 'e1', 'kind': 'tire', 'member_key': 'm' * 64,
                             'snapshot_id': 'snap', 'variant_id': 'variant-one',
                             'verification_id': 'verif', 'event_id': 'evt-1',
                             'observed_at': '2026-01-01T00:00:00Z', 'verified_at': '2026-01-01T00:00:00Z',
                             'member_reasons': ['member-reason'], 'contexts': ['unselected'],
                             'identity_contract': {'schema': 'variant-identity@2', 'state': 'current',
                                                   'current_key': 'a' * 64,
                                                   'current_identity': {'kind': 'text', 'value': 'synthetic'},
                                                   'identity_status': 'source_scoped'}}],
               'conflicts': [], 'source_state': 'snapshot', 'data_state': 'local_snapshot',
               'device_context': {'schema': 'device-ai-context@1', 'device_context_fingerprint': 'f' * 64,
                                  'profile_id': 'profile-local-1', 'owner_epoch': 7, 'slot': 'slot-local-9',
                                  'host_receipt_id': 'receipt-local-2', 'intent_id': 'intent-local-3',
                                  'package_id': 'package-local', 'package_sha256': 'a' * 64,
                                  'projection_sha256': 'b' * 64, 'selection_sha256': 'c' * 64,
                                  'question_sha256': 'd' * 64, 'member_count': 1,
                                  'numeric_encoding': 'device-number-token@1'},
               'manifest': {'complete': 'manifest-material'}, 'member_reasons': ['top-reason'],
               'contexts': ['unselected-context'], 'credentials': {'api_key': 'secret-material'}}
    minimal = ai_analysis._device_request_evidence(payload)
    assert set(minimal) == {'facts', 'evidence', 'conflicts', 'source_state', 'data_state'}
    assert set(minimal['facts'][0]) == {'id', 'text', 'evidence_id', 'domain', 'field_code'}
    assert set(minimal['evidence'][0]) == {'id', 'event_id', 'observed_at', 'verified_at', 'kind',
                                           'snapshot_id', 'variant_id', 'verification_id',
                                           'identity_contract'}
    serialized = json.dumps(minimal, ensure_ascii=False)
    for forbidden in OUTBOUND_RED_LINE + ('credentials', 'api_key', 'secret-material',
                                          'raw_blob', 'local-only-material'):
        assert forbidden not in serialized, forbidden
    # 非 tire 域：冻结身份=reference 子对象原样，顶层不落仓库别名键。
    non_tire = ai_analysis._device_request_evidence({
        'facts': [], 'evidence': [{'id': 'e1', 'member_key': 'm' * 64, 'observed_at': '2026-01-01T00:00:00Z',
                                   'verified_at': None, 'reference': {'kind': 'recall', 'snapshot_id': 's',
                                   'recall_revision_id': 'r', 'verification_id': 'v'}}],
        'conflicts': [], 'source_state': 'snapshot', 'data_state': 'local_snapshot',
        'device_context': {'schema': 'x'}})
    assert set(non_tire['evidence'][0]) == {'id', 'observed_at', 'verified_at', 'reference'}
    assert non_tire['evidence'][0]['reference']['kind'] == 'recall'


def handcrafted_rich(env, seeded):
    """直接落一对 device pack+preparation 行（绕过 prepare 路由）：facts 就绪且 payload
    携带本机/审计/凭据类禁发字段（还原方案B之前的"全量材料在服务端"形态），驱动外发
    剥离与 grounding 正例。身份合同取归档原件真值（先 seed_identity），gate 真实生效。"""
    _raw, descriptor, envelope = seeded
    member = tire_member(envelope)
    identity = member['payload']['identity_contract']
    variant_id = member['reference']['variant_id']
    q_hash = hashlib.sha256(QUESTION.encode('utf-8')).hexdigest()
    dc_hash = hashlib.sha256(b'synthetic-device-context').hexdigest()
    sel_hash = hashlib.sha256(b'synthetic-device-selection').hexdigest()
    proj_hash = hashlib.sha256(b'synthetic-device-projection').hexdigest()
    entry = {'id': 'e1', 'kind': 'tire', 'member_key': 'm' * 64,
             'snapshot_id': 'snap', 'variant_id': variant_id, 'verification_id': 'verif',
             'observed_at': '2026-01-01T00:00:00Z', 'verified_at': '2026-01-01T00:00:00Z',
             'member_reasons': ['member-reason-local'],
             'identity_contract': {'schema': identity['schema'], 'state': identity['state'],
                                   'current_key': identity['current_key'],
                                   'current_identity': encode_value(identity['current_identity']),
                                   'identity_status': identity['identity_status']}}
    content = {'purpose': 'device_history_analysis', 'origin': 'device_history',
               'evidence': [entry],
               'facts': [{'id': 'f1', 'text': FACT_TEXT, 'evidence_id': 'e1', 'domain': 'tire',
                          'field_code': 'tire.tread_width', 'member_reasons': ['local-only']}],
               'conflicts': [], 'source_state': 'snapshot', 'data_state': 'local_snapshot',
               'device_context': {'schema': 'device-ai-context@1', 'device_context_fingerprint': dc_hash,
                                  'projection_sha256': proj_hash, 'selection_sha256': sel_hash,
                                  'question_sha256': q_hash,
                                  'profile_id': 'profile-local-1', 'owner_epoch': 3,
                                  'slot': 'slot-local-7', 'host_receipt_id': str(uuid4()),
                                  'intent_id': str(uuid4()), 'package_id': 'package-local',
                                  'package_sha256': 'a' * 64, 'member_count': 1,
                                  'numeric_encoding': 'device-number-token@1'},
               'manifest': {'complete': 'manifest-material'},
               'member_reasons': ['unselected-reason'],
               'contexts': ['unselected-context'],
               'credentials': {'api_key': 'secret-material'}}
    now = utcnow()
    with env.app.state.database.sessions() as db:
        db.add(EvidenceObject(raw_hash=proj_hash, byte_count=100))
        db.flush()
        pack = AIEvidencePack(actor_session_id=env.session_id, mode='history', data_state='local_snapshot',
                              privacy_class='private', payload=content, fingerprint=digest(content),
                              created_at=now, expires_at=now + timedelta(seconds=1800))
        db.add(pack)
        db.flush()
        row = DeviceAIPreparation(actor_session_id=env.session_id, idempotency_key=str(uuid4()),
                                  request_hash='h' * 64, offline_pack_id=descriptor['id'],
                                  offline_content_hash=descriptor['sha256'], host_receipt_id=str(uuid4()),
                                  intent_id=str(uuid4()), selection_hash=sel_hash, projection_hash=proj_hash,
                                  projection_byte_count=100, device_context_fingerprint=dc_hash,
                                  question_sha256=q_hash, ai_pack_id=pack.id,
                                  contract={'schema': 'device-ai-prepare@1', 'variant_ids': [variant_id]},
                                  created_at=now, expires_at=now + timedelta(seconds=1800))
        db.add(row)
        db.commit()
        return {'pack_id': pack.id, 'pack_fingerprint': pack.fingerprint, 'prepare_id': row.id,
                'host_receipt_id': row.host_receipt_id, 'device_context_fingerprint': dc_hash}


def test_d18_minimal_outbound_keeps_grounding_and_strips_local_details(env):
    """路由级正例：payload 含禁发字段仍被剥离；facts/引用保留使流式 fact claim 落地。"""
    seeded = env.seed()
    env.seed_identity(seeded)
    value = handcrafted_rich(env, seeded)
    env.model.script = json.dumps({'claims': [{'type': 'fact', 'text': '', 'fact_ids': ['f1'],
                                               'evidence_ids': ['e1']}],
                                   'uncertainty': '仅基于本地历史快照，未在线核验'}, ensure_ascii=False)
    key = str(uuid4())
    response = submit_stream(env, submission(env, value), key)
    assert response.status_code == 202, response.text
    request_id = response.json()['analysis']['id']
    env.until(request_id, lambda v: v['execution']['state'] == 'running')
    env.model.release.set()
    done = env.until(request_id, lambda v: v['execution']['terminal'])
    assert done['analysis']['state'] == 'completed'
    # grounding 仍工作：fact claim 的文字由服务器按 pack.payload 的 facts 渲染（label→
    # device citation 映射保留在服务端），流式 claim_draft 同源校验通过。
    claim = done['analysis']['answer']['claims'][0]
    assert claim['type'] == 'fact' and claim['fact_ids'] == ['f1'] and claim['evidence_ids'] == ['e1']
    assert claim['text'] == FACT_TEXT
    events = env.client.get('/v1/ai/analysis-streams/' + request_id + '/events').json()
    assert [row['type'] for row in events['items']] == ['accepted', 'started', 'claim_draft',
                                                        'uncertainty_draft', 'completed']
    # 外发体红线：本机/审计/凭据类字段结构性缺席，facts 只剩白名单键。
    question, sent = env.model.outbound_evidence()
    assert question == QUESTION
    assert set(sent) == {'facts', 'evidence', 'conflicts', 'source_state', 'data_state'}
    serialized = json.dumps(sent, ensure_ascii=False)
    for forbidden in OUTBOUND_RED_LINE + ('credentials', 'api_key', 'secret-material',
                                          'manifest-material', 'unselected-reason',
                                          'unselected-context', 'profile-local-1', 'local-only',
                                          'member-reason-local', 'package-local'):
        assert forbidden not in serialized, forbidden
    assert sent['facts'] == [{'id': 'f1', 'text': FACT_TEXT, 'evidence_id': 'e1',
                              'domain': 'tire', 'field_code': 'tire.tread_width'}]
    assert sent['evidence'][0]['id'] == 'e1'
    assert 'identity_contract' in sent['evidence'][0]


# ---------------------------------------------------------------- 负例：伪造同意（D2/D3）

@pytest.mark.parametrize('changes', [
    {'expected_pack_fingerprint': '0' * 64},
    {'expected_device_context_fingerprint': '0' * 64},
    {'provider': 'other_provider'},
    {'model': 'other-model'},
    {'expected_provider_policy_fingerprint': '0' * 64},
])
def test_forged_consent_six_tuple_is_rejected_409(env, changes):
    _seeded, value = prepared_chain(env)
    response = submit_stream(env, submission(env, value, consent_changes=changes))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_consent_mismatch'
    assert env.count(AIRequest) == 0 and env.count(DeviceAIConsentClaim) == 0
    assert env.model.calls == 0


@pytest.mark.parametrize('mode', ['question_swapped', 'consent_swapped'])
def test_question_replacement_q1_to_q2_is_rejected_409(env, mode):
    _seeded, value = prepared_chain(env)
    if mode == 'question_swapped':
        body = submission(env, value, question=OTHER_QUESTION)  # 携带 Q2 明文，准备记录是 Q1
    else:
        body = submission(env, value, consent_changes={
            'question_sha256': hashlib.sha256(OTHER_QUESTION.encode('utf-8')).hexdigest()})
    response = submit_stream(env, body)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_question_mismatch'
    assert env.count(AIRequest) == 0 and env.count(DeviceAIConsentClaim) == 0
    assert env.model.calls == 0


def test_allow_private_disabled_rejects_device_pack_with_403(env, monkeypatch):
    monkeypatch.setattr(ai_analysis, 'configured_model', lambda: OpenAIConfig(
        model='synthetic-device', api_key='synthetic-never-live', allow_private=False))
    _seeded, value = prepared_chain(env)
    response = submit_stream(env, submission(env, value))
    assert response.status_code == 403
    assert env.count(AIRequest) == 0 and env.count(DeviceAIConsentClaim) == 0
    assert env.model.calls == 0


# ---------------------------------------------------------------- 负例：TOCTOU（D4）

def test_variant_revoked_between_prepare_and_submit_is_rejected_409(env):
    seeded, value = prepared_chain(env)
    variant_id = tire_member(seeded[2])['reference']['variant_id']
    with env.app.state.database.sessions() as db:
        db.add(VariantLifecycleEvent(variant_id=variant_id, revision=1, action='revoke',
                                     before_state='active', after_state='revoked',
                                     operator_session_id=env.session_id, operator='synthetic',
                                     reason='synthetic revocation between prepare and submit', evidence=[]))
        db.commit()
    response = submit_stream(env, submission(env, value))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_variant_revoked'
    assert env.count(AIRequest) == 0 and env.count(DeviceAIConsentClaim) == 0
    assert env.model.calls == 0
    # 冻结回执不被改写：preparation/pack 保持原样。
    detail = env.client.get(f"/v1/ai/device-evidence-packs/{value['id']}", params={'mode': 'history'})
    assert detail.status_code == 200 and detail.json()['question_sha256'] == value['question_sha256']


# ---------------------------------------------------------------- 负例：N10 三入口

def test_n10_stream_device_pack_without_submission_is_422(env):
    _seeded, value = prepared_chain(env)
    response = submit_stream(env, {'pack_id': value['pack_id'], 'question': QUESTION,
                                   'allow_external_processing': True})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'device_ai_submission_required'
    assert env.count(AIRequest) == 0


def test_n10_stream_legacy_pack_with_submission_is_422(env):
    from test_ai import historical_pack
    legacy = historical_pack(env.client)
    response = submit_stream(env, submission(env, {'pack_id': legacy['id'],
        'pack_fingerprint': legacy['fingerprint'], 'device_context_fingerprint': 'f' * 64,
        'host_receipt_id': str(uuid4()), 'id': str(uuid4())}))
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'device_ai_submission_not_allowed'
    assert env.count(AIRequest) == 0


def test_n10_sync_device_pack_without_submission_is_422(env):
    _seeded, value = prepared_chain(env)
    response = submit_sync(env, {'pack_id': value['pack_id'], 'question': QUESTION,
                                 'allow_external_processing': True})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'device_ai_submission_required'
    assert env.count(AIRequest) == 0


def test_sync_entry_device_origin_is_422_stream_only(env):
    _seeded, value = prepared_chain(env)
    response = submit_sync(env, submission(env, value))
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'device_ai_stream_only'
    assert env.count(AIRequest) == 0 and env.count(DeviceAIConsentClaim) == 0
    assert env.model.calls == 0


def test_n10_sync_legacy_pack_with_submission_is_422(env):
    from test_ai import historical_pack
    legacy = historical_pack(env.client)
    response = submit_sync(env, submission(env, {'pack_id': legacy['id'],
        'pack_fingerprint': legacy['fingerprint'], 'device_context_fingerprint': 'f' * 64,
        'host_receipt_id': str(uuid4()), 'id': str(uuid4())}))
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'device_ai_submission_not_allowed'
    assert env.count(AIRequest) == 0


def test_n10_rule_drafts_rejects_device_pack(env):
    _seeded, value = prepared_chain(env)
    response = env.client.post('/v1/ai/rule-drafts', json={'pack_id': value['pack_id'],
                                                           'allow_external_processing': True},
                               headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 409
    assert env.count(AIRequest) == 0 and env.count(DeviceAIConsentClaim) == 0
    assert env.model.calls == 0


def test_n10_rule_drafts_device_submission_shape_is_422(env):
    _seeded, value = prepared_chain(env)
    body = submission(env, value)
    response = env.client.post('/v1/ai/rule-drafts', json={'pack_id': body['pack_id'],
                                                           'allow_external_processing': True,
                                                           'device_submission': body['device_submission']},
                               headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 422  # GenerateDraft closed schema
    assert env.count(AIRequest) == 0


# ---------------------------------------------------------------- 负例：覆盖双断言（D4）

def handcrafted(env, seeded, *, evidence_entries, contract_variant_ids):
    """绕过 prepare 路由直接落一对 device pack+preparation 行，驱动覆盖断言负例。"""
    _raw, descriptor, _envelope = seeded
    q_hash = hashlib.sha256(QUESTION.encode('utf-8')).hexdigest()
    dc_hash = hashlib.sha256(b'synthetic-device-context').hexdigest()
    sel_hash = hashlib.sha256(b'synthetic-device-selection').hexdigest()
    proj_hash = hashlib.sha256(b'synthetic-device-projection').hexdigest()
    content = {'purpose': 'device_history_analysis', 'origin': 'device_history',
               'evidence': evidence_entries, 'facts': [], 'conflicts': [],
               'source_state': 'snapshot', 'data_state': 'local_snapshot',
               'device_context': {'schema': 'device-ai-context@1', 'device_context_fingerprint': dc_hash,
                                  'projection_sha256': proj_hash, 'selection_sha256': sel_hash,
                                  'question_sha256': q_hash}}
    now = utcnow()
    with env.app.state.database.sessions() as db:
        db.add(EvidenceObject(raw_hash=proj_hash, byte_count=100))
        db.flush()
        pack = AIEvidencePack(actor_session_id=env.session_id, mode='history', data_state='local_snapshot',
                              privacy_class='private', payload=content, fingerprint=digest(content),
                              created_at=now, expires_at=now + timedelta(seconds=1800))
        db.add(pack)
        db.flush()
        row = DeviceAIPreparation(actor_session_id=env.session_id, idempotency_key=str(uuid4()),
                                  request_hash='h' * 64, offline_pack_id=descriptor['id'],
                                  offline_content_hash=descriptor['sha256'], host_receipt_id=str(uuid4()),
                                  intent_id=str(uuid4()), selection_hash=sel_hash, projection_hash=proj_hash,
                                  projection_byte_count=100, device_context_fingerprint=dc_hash,
                                  question_sha256=q_hash, ai_pack_id=pack.id,
                                  contract={'schema': 'device-ai-prepare@1', 'variant_ids': contract_variant_ids},
                                  created_at=now, expires_at=now + timedelta(seconds=1800))
        db.add(row)
        db.commit()
        return {'pack_id': pack.id, 'pack_fingerprint': pack.fingerprint, 'prepare_id': row.id,
                'host_receipt_id': row.host_receipt_id, 'device_context_fingerprint': dc_hash}


def gate_entry(index, variant_id):
    return {'id': f'e{index}', 'kind': 'tire', 'member_key': f'{index}' * 64, 'snapshot_id': 'snap',
            'variant_id': variant_id, 'verification_id': 'verif',
            'observed_at': '2026-01-01T00:00:00Z', 'verified_at': '2026-01-01T00:00:00Z',
            'identity_contract': {'schema': 'variant-identity@2', 'state': 'current', 'current_key': 'a' * 64,
                                  'current_identity': {'kind': 'text', 'value': 'synthetic'},
                                  'identity_status': 'source_scoped'}}


def test_empty_embedded_evidence_cannot_bypass_non_empty_assertion(env):
    seeded = env.seed()
    value = handcrafted(env, seeded, evidence_entries=[gate_entry(1, None)],
                        contract_variant_ids=['variant-one'])
    response = submit_stream(env, submission(env, value))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_evidence_coverage'
    assert env.count(AIRequest) == 0


def test_empty_contract_variant_list_is_rejected_by_non_empty_assertion(env):
    seeded = env.seed()
    value = handcrafted(env, seeded, evidence_entries=[gate_entry(1, 'variant-one')],
                        contract_variant_ids=[])
    response = submit_stream(env, submission(env, value))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_evidence_coverage'
    assert env.count(AIRequest) == 0


def test_partial_coverage_is_rejected_by_exact_equality_assertion(env):
    seeded = env.seed()
    value = handcrafted(env, seeded, evidence_entries=[gate_entry(1, 'variant-one'), gate_entry(2, 'variant-one')],
                        contract_variant_ids=['variant-one', 'variant-two'])
    response = submit_stream(env, submission(env, value))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_evidence_coverage'
    assert env.count(AIRequest) == 0


# ---------------------------------------------------------------- 负例：回显与过期（D8）

@pytest.mark.parametrize('changes', [
    {'prepare_id': str(uuid4())},
    {'host_receipt_id': str(uuid4())},
    {'device_context_fingerprint': 'e' * 64},
])
def test_submission_echo_mismatch_is_rejected_409(env, changes):
    _seeded, value = prepared_chain(env)
    device_part = {**submission(env, value)['device_submission'], **changes}
    body = {'pack_id': value['pack_id'], 'question': QUESTION, 'allow_external_processing': True,
            'device_submission': device_part}
    response = submit_stream(env, body)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_submission_echo_mismatch'
    assert env.count(AIRequest) == 0


@pytest.mark.parametrize('expired', ['preparation', 'pack'])
def test_dual_expiry_gates_are_checked_at_submit(env, monkeypatch, expired):
    _seeded, value = prepared_chain(env)
    if expired == 'preparation':
        # 013 触发器封死对 device_ai_preparations 的一切 UPDATE（含 text()），改用时间
        # 平移模拟过期：ai_analysis.utcnow 是 prepare_analysis 过期检查的时钟源。
        real_now = utcnow
        monkeypatch.setattr(ai_analysis, 'utcnow', lambda: real_now() + timedelta(hours=1))
    else:
        # ai_evidence_packs 无 ledger 触发器，可直改 expires_at（pack 单独过期）。
        with env.app.state.database.sessions() as db:
            db.execute(text('UPDATE ai_evidence_packs SET expires_at = :later WHERE id = :id'),
                       {'later': '2000-01-01 00:30:00.000000', 'id': value['pack_id']})
            db.commit()
    response = submit_stream(env, submission(env, value))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == (f'device_ai_{expired}_expired')
    assert env.count(AIRequest) == 0 and env.model.calls == 0


# ---------------------------------------------------------------- 并发与原子性（D9/N17/N18）

def test_second_submit_same_preparation_different_key_is_409_single_claim(env):
    _seeded, value = prepared_chain(env)
    first = submit_stream(env, submission(env, value))
    assert first.status_code == 202, first.text
    second = submit_stream(env, submission(env, value), key=str(uuid4()))
    assert second.status_code == 409
    assert second.json()['detail']['code'] == 'device_ai_claim_conflict'
    assert 'UNIQUE' not in second.text and 'IntegrityError' not in second.text
    assert env.count(AIRequest) == 1 and env.count(DeviceAIConsentClaim) == 1
    env.model.release.set()
    env.until(first.json()['analysis']['id'], lambda v: v['execution']['terminal'])
    assert env.model.calls == 1


def test_reservation_hook_failure_rolls_back_all_ledgers(env, monkeypatch):
    _seeded, value = prepared_chain(env)
    original = store.create_execution_locked

    def fail(db, request, owner_token):
        original(db, request, owner_token)
        raise RuntimeError('synthetic-before-commit-failure')

    monkeypatch.setattr(store, 'create_execution_locked', fail)
    with pytest.raises(Exception):
        submit_stream(env, submission(env, value))
    assert env.count(AIRequest) == 0 and env.count(DeviceAIConsentClaim) == 0
    assert env.count(store.AIStreamExecution) == 0
    assert env.count(DeviceAIPreparation) == 1
    assert env.model.calls == 0


def test_claim_insert_failure_rolls_back_request_and_claim_together(env):
    # 复刻 test_device_ai_models.py:192 到路由级：AIRequest 已 flush、claim 写入失败，
    # 两 ledger 同归零、preparation 保留。
    _seeded, value = prepared_chain(env)

    def fail_claim(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith('INSERT INTO device_ai_consent_claims'):
            raise RuntimeError('synthetic claim write failure')

    event.listen(env.app.state.database.engine, 'before_cursor_execute', fail_claim)
    try:
        with pytest.raises(RuntimeError, match='synthetic claim write failure'):
            submit_stream(env, submission(env, value))
    finally:
        event.remove(env.app.state.database.engine, 'before_cursor_execute', fail_claim)
    assert env.count(AIRequest) == 0 and env.count(DeviceAIConsentClaim) == 0
    assert env.count(store.AIStreamExecution) == 0
    assert env.count(DeviceAIPreparation) == 1
    assert env.model.calls == 0


# ---------------------------------------------------------------- D7 结构强制

def test_d7_claim_or_nothing_when_reserve_bypasses_prepare_analysis(env):
    _seeded, value = prepared_chain(env)
    config = ai_analysis.configured_model()
    with env.app.state.database.sessions() as db:
        pack = db.get(AIEvidencePack, value['pack_id'])
        body, reserve = request_body(config, QUESTION, {**pack.payload, 'data_state': pack.data_state}, stream=True)
        with pytest.raises(HTTPException) as error:
            ai_execution.reserve_response(db, config=config, pack=pack, session_id=env.session_id,
                                          key=str(uuid4()), request_hash='a' * 64, question=QUESTION,
                                          reserve=reserve, body=body, contract={'purpose': 'analysis'})
        assert error.value.status_code == 409
        assert error.value.detail['code'] == 'device_ai_claim_required'
        db.rollback()
    assert env.count(AIRequest) == 0 and env.count(DeviceAIConsentClaim) == 0
    assert env.model.calls == 0


def test_d7_stale_claim_plan_for_another_preparation_is_rejected(env):
    _seeded, value = prepared_chain(env)
    config = ai_analysis.configured_model()
    with env.app.state.database.sessions() as db:
        # 挂一个指向其它 preparation 的计划（模拟 stale/错位注册）。
        db.info[ai_analysis.DEVICE_CLAIM_PLAN_KEY] = {'preparation_id': 'not-this-preparation',
                                                      'ai_pack_id': value['pack_id'],
                                                      'provider_consent_hash': 'c' * 64,
                                                      'provider_policy_fingerprint': 'd' * 64}
        pack = db.get(AIEvidencePack, value['pack_id'])
        body, reserve = request_body(config, QUESTION, {**pack.payload, 'data_state': pack.data_state}, stream=True)
        with pytest.raises(HTTPException) as error:
            ai_execution.reserve_response(db, config=config, pack=pack, session_id=env.session_id,
                                          key=str(uuid4()), request_hash='a' * 64, question=QUESTION,
                                          reserve=reserve, body=body, contract={'purpose': 'analysis'})
        assert error.value.status_code == 409
        assert error.value.detail['code'] == 'device_ai_claim_required'
        db.rollback()
    assert env.count(AIRequest) == 0
