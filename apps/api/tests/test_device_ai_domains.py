"""第50轮 P1-4a 隔离路由测试：设备 AI prepare/submit 从 tire-only 扩展到
vehicle/recall/recall_search 三域（test_event 维持投影核 restricted 恒拒）。

形态对齐 test_device_ai_submit.py（文件库 + 临时对象目录 + FixtureRegistry +
producer-v2 样本 + HeldModel 流式 mock）。nonempty 样本包本身含全部五域成员
（1 tire + 1 vehicle + 2 recall + 1 recall_search + 1 restricted test_event），
多域 fixture 直接按 reference.kind 取成员构造 selector，mode 与投影核 converter
一一对应（DOMAIN_MODES）。D17 专项：device recall 包的 payload 不触发仓库 recall
合同（contains_recall/is_recall_evidence 逐条断言），submit 不被
ai_recall_contract_stale 拒、正常走 claim 链并完成流式 grounding。
"""
import asyncio
import hashlib
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from tire_api import ai_analysis
from tire_api.ai_gateway import OpenAIConfig
from tire_api.ai_models import AIEvidencePack, AIRequest
from tire_api.ai_recall_contract import contains_recall, is_recall_evidence
from tire_api.db import EvidenceObject, utcnow
from tire_api.device_ai_models import DeviceAIConsentClaim, DeviceAIPreparation
from tire_api.device_ai_projection import (FrozenPackBinding, ProjectionError, exact_digest,
                                           parse_exact_json, project_offline_pack)
from tire_api.domain import digest
from tire_api.main import create_app
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from test_core import FixtureRegistry

from datetime import timedelta

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / '.artifacts/query-fallback49/producer-v2-samples-a'
QUESTION = '这份归档里保存的配置与公告记录如何解读？'
# 投影核 converter ↔ 投影模式一一对应（device_ai_projection.py:753-765）。
DOMAIN_MODES = {'tire': 'single_observation', 'vehicle': 'complete_observation',
                'recall': 'complete_formal_observation', 'recall_search': 'candidate_page_context'}


class HeldDeviceModel:
    """设备包专用合成流：device facts 为空，合法输出只有空 claims + 非空 uncertainty。"""

    def __init__(self):
        self.calls = 0
        self.release = threading.Event()

    async def stream(self, config, body, on_text):
        assert body['stream'] is True and body['store'] is False and body['background'] is False and body['tools'] == []
        self.calls += 1
        text = '{"claims":[],"uncertainty":"synthetic device stream"}'
        await on_text('{"claims":[],')
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        await on_text('"uncertainty":"synthetic device stream"}')
        return {'text': text, 'error': None,
                'usage': {'input_tokens': 300, 'output_tokens': 40, 'total_tokens': 340},
                'provider_response_id': 'resp_synthetic_device_domain'}


def member_of(envelope, kind, *, predicate=None):
    for member in envelope['members']:
        if member['reference']['kind'] == kind and (predicate is None or predicate(member)):
            return member
    raise AssertionError(f'样本包缺少 {kind} 成员')


def domain_selector(envelope, kind, *, with_record=False):
    """按域构造合法 selector；recall 默认取带 recall_revision_id 的正式公告成员。"""
    predicate = (lambda member: member['reference']['recall_revision_id'] is not None
                 and member['payload']['records']) if kind == 'recall' else None
    member = member_of(envelope, kind, predicate=predicate)
    selector = {'kind': kind, 'member_key': member['key'], 'document_id': None,
                'record_index': None, 'reference': dict(member['reference'])}
    if with_record:
        document = next(row for row in envelope['documents']
                        if row['member_key'] == member['key'] and row['record_index'] is not None)
        selector['document_id'] = document['id']
        selector['record_index'] = document['record_index']
    return selector


class RouteEnv:
    def __init__(self, client, app, session_id, model):
        self.client, self.app, self.session_id, self.model = client, app, session_id, model

    def seed(self, *, name='nonempty', mutate=None):
        original = (SAMPLES / f'{name}-pack.json').read_bytes()
        descriptor = json.loads((SAMPLES / f'{name}-descriptor.json').read_bytes())
        envelope = json.loads(original)
        envelope['owner_scope_id'] = digest({'namespace': 'offline-owner-scope@1', 'session': self.session_id})
        if mutate is not None:
            mutate(envelope)
        raw = json.dumps(envelope, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        sha = hashlib.sha256(raw).hexdigest()
        descriptor.update(sha256=sha, byte_count=len(raw), owner_scope_id=envelope['owner_scope_id'])
        assert self.app.state.database.object_store.put(raw) == sha
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

    def prepare_body(self, seeded, selector, mode, *, question=QUESTION, **overrides):
        raw, descriptor, envelope = seeded
        binding = FrozenPackBinding(descriptor['id'], descriptor['owner_scope_id'], descriptor['sha256'],
                                    descriptor['byte_count'], envelope['schema'])
        try:
            expected = project_offline_pack(raw, binding, [dict(selector)], mode=mode).sha256
        except ProjectionError:
            expected = '0' * 64
        value = {'package_id': descriptor['id'], 'expected_sha256': descriptor['sha256'],
                 'expected_byte_count': descriptor['byte_count'], 'expected_schema': envelope['schema'],
                 'expected_owner_scope_id': descriptor['owner_scope_id'], 'selectors': [selector],
                 'projection_mode': mode, 'expected_projection_sha256': expected,
                 'question_sha256': hashlib.sha256(question.encode('utf-8')).hexdigest(),
                 'host_receipt_id': str(uuid4()), 'intent_id': str(uuid4())}
        value.update(overrides)
        return value

    def prepare(self, seeded, selector, mode, *, question=QUESTION, key=None):
        response = self.client.post('/v1/ai/device-evidence-packs',
                                    json=self.prepare_body(seeded, selector, mode, question=question),
                                    headers={'Idempotency-Key': key or str(uuid4())})
        assert response.status_code == 201, response.text
        return response.json()

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
    app = create_app('sqlite:///' + (tmp_path / 'device-domains.sqlite').as_posix(), FixtureRegistry())
    model = HeldDeviceModel()
    app.state.ai_adapter = model  # 必须先于 lifespan：supervisor 在启动时绑定 adapter
    with TestClient(app) as client:
        client.get('/health')
        yield RouteEnv(client, app, client.cookies['tire_local_session'], model)
        model.release.set()


def submission(env, value, *, question=QUESTION):
    consent = {
        'expected_pack_fingerprint': value['pack']['fingerprint'],
        'expected_device_context_fingerprint': value['device_context_fingerprint'],
        'question_sha256': hashlib.sha256(question.encode('utf-8')).hexdigest(),
        'provider': 'openai_responses',
        'model': 'synthetic-device',
        'expected_provider_policy_fingerprint': ai_analysis.device_provider_policy_fingerprint(
            ai_analysis.configured_model()),
    }
    return {'pack_id': value['pack_id'], 'question': question, 'allow_external_processing': True,
            'device_submission': {'prepare_id': value['id'],
                                  'host_receipt_id': value['host_receipt_id'],
                                  'device_context_fingerprint': value['device_context_fingerprint'],
                                  'provider_consent': consent}}


def submit_stream(env, body, key=None):
    return env.client.post('/v1/ai/analysis-streams', json=body,
                           headers={'Idempotency-Key': key or str(uuid4())})


def full_chain(env, kind, *, with_record=False, seed_mutate=None):
    seeded = env.seed(mutate=seed_mutate)
    selector = domain_selector(seeded[2], kind, with_record=with_record)
    value = env.prepare(seeded, selector, DOMAIN_MODES[kind])
    response = submit_stream(env, submission(env, value))
    assert response.status_code == 202, response.text
    return seeded, value, selector, response.json()['analysis']['id']


# ---------------------------------------------------------------- 正例：各域完整链

def test_vehicle_domain_full_chain_needs_no_tire_identity_seeding(env):
    """vehicle 域：无 variant_id（不伪造）、无需种 TireVariant/身份绑定；D4 gate 以冻结
    reference 为身份键，仓库对该域无可撤销生命周期，覆盖断言即等价权利 gate。"""
    _seeded, value, selector, request_id = full_chain(env, 'vehicle')
    # prepare 侧各域记录：contract 冗余（variant_ids 空 + domain_references 冻结引用）。
    with env.app.state.database.sessions() as db:
        row = db.get(DeviceAIPreparation, value['id'])
        assert row.contract['variant_ids'] == []
        assert row.contract['domain_references'] == {'vehicle': [selector['reference']]}
        pack = db.get(AIEvidencePack, row.ai_pack_id)
        entry = pack.payload['evidence'][0]
        # 非 tire 条目身份键收进 reference 子对象；顶层无 kind/recall_revision_id 别名键。
        assert entry['id'] == 'e1' and entry['member_key'] == selector['member_key']
        assert entry['reference'] == selector['reference'] and 'kind' not in entry
        assert 'identity_contract' not in entry and 'variant_id' not in entry
    env.model.release.set()
    done = env.until(request_id, lambda v: v['execution']['terminal'])
    assert done['analysis']['state'] == 'completed'
    assert done['analysis']['answer']['uncertainty'] == 'synthetic device stream'
    assert done['analysis']['request_contract']['origin'] == 'device_history'
    claim = env.count(DeviceAIConsentClaim)
    assert claim == 1 and env.model.calls == 1


def test_recall_search_domain_full_chain(env):
    _seeded, value, selector, request_id = full_chain(env, 'recall_search', with_record=True)
    with env.app.state.database.sessions() as db:
        row = db.get(DeviceAIPreparation, value['id'])
        assert row.contract['domain_references'].keys() == {'recall_search'}
        assert row.contract['domain_references']['recall_search'] == [selector['reference']]
    env.model.release.set()
    done = env.until(request_id, lambda v: v['execution']['terminal'])
    assert done['analysis']['state'] == 'completed'
    assert env.count(DeviceAIConsentClaim) == 1 and env.model.calls == 1


def test_recall_empty_observation_full_chain(env):
    """空公告观察（records 空、recall_revision_id null）同样可投影可提交。"""
    seeded = env.seed()
    member = member_of(seeded[2], 'recall',
                       predicate=lambda m: m['reference']['recall_revision_id'] is None)
    selector = {'kind': 'recall', 'member_key': member['key'], 'document_id': None,
                'record_index': None, 'reference': dict(member['reference'])}
    value = env.prepare(seeded, selector, DOMAIN_MODES['recall'])
    response = submit_stream(env, submission(env, value))
    assert response.status_code == 202, response.text
    env.model.release.set()
    done = env.until(response.json()['analysis']['id'], lambda v: v['execution']['terminal'])
    assert done['analysis']['state'] == 'completed'


def test_recall_domain_context_fingerprint_binds_domain_boundary(env):
    """recall 域 context 指纹按投影核实际输出记录 domain_boundaries（公告边界入指纹）。"""
    seeded = env.seed()
    selector = domain_selector(seeded[2], 'recall', with_record=True)
    raw, descriptor, envelope = seeded
    binding = FrozenPackBinding(descriptor['id'], descriptor['owner_scope_id'], descriptor['sha256'],
                                descriptor['byte_count'], envelope['schema'])
    projection = project_offline_pack(raw, binding, [dict(selector)], mode=DOMAIN_MODES['recall'])
    observations = parse_exact_json(projection.canonical_bytes)['observations']
    expected_selection = exact_digest([item['selector'] for item in observations],
                                      namespace='device-ai-selection@1')
    expected_context = exact_digest({
        'schema': 'device-ai-context@1', 'package_id': descriptor['id'],
        'package_schema': envelope['schema'], 'package_sha256': descriptor['sha256'],
        'projection_mode': DOMAIN_MODES['recall'], 'projection_sha256': projection.sha256,
        'selection_sha256': expected_selection,
        'receipt_sources': [{'selector': item['selector'], 'selection_reason': item['selection_reason'],
                             'source': item['source']} for item in observations],
        'device_citations': [],
        'domain_boundaries': [{'kind': item['selector']['reference']['kind'],
                               'boundary': item['material']['boundary']}
                              for item in observations
                              if isinstance(item['material'].get('boundary'), dict)],
        'numeric_encoding': 'device-number-token@1'}, namespace='device-ai-context@1')
    value = env.prepare(seeded, selector, DOMAIN_MODES['recall'])
    assert value['device_context_fingerprint'] == expected_context
    assert value['projection_sha256'] == projection.sha256


# ---------------------------------------------------------------- D17 专项验证

def test_d17_device_recall_pack_never_triggers_warehouse_recall_contract(env):
    """D17：device recall 投影走 device 路径——submit 不被 ai_recall_contract_stale 拒、
    正常走 claim 链并完成流式 grounding；payload 全程不触发仓库 recall 合同
    （contains_recall/is_recall_evidence/grounded_answer 三处消费点逐条断言）。"""
    _seeded, value, _selector, request_id = full_chain(env, 'recall', with_record=True)
    with env.app.state.database.sessions() as db:
        pack = db.get(AIEvidencePack, value['pack_id'])
        # 1) payload 不含仓库 recall 合同 matcher 的任何触发键。
        assert contains_recall(pack.payload) is False
        assert not any(is_recall_evidence(item) for item in pack.payload['evidence'])
        assert pack.payload['purpose'] == 'device_history_analysis'
        # 2) ai_analysis.py 的 grounding 消费点按 origin 分流：device recall 包按普通
        #    device 包 grounding（不进仓库 recall 合同/边界渲染）。
        result = ai_analysis.grounded_answer('{"claims":[],"uncertainty":"专项"}', pack)
        assert result['claims'] == [] and 'recall_boundary' not in result
        # 3) claim 链：DeviceAIConsentClaim 已按 preparation 绑定落账。
        claim = db.scalar(select(DeviceAIConsentClaim).where(
            DeviceAIConsentClaim.preparation_id == value['id']))
        assert claim is not None and claim.actor_session_id == env.session_id
    # 4) 流式完成：projector/append_event/finish 的 recall 合同咨询点对 device payload
    #    均不触发（否则将以 ai_grounding_validation_failed 失败）。
    env.model.release.set()
    done = env.until(request_id, lambda v: v['execution']['terminal'])
    assert done['execution']['state'] == done['analysis']['state'] == 'completed'
    assert done['analysis']['answer']['uncertainty'] == 'synthetic device stream'
    assert env.model.calls == 1


# ---------------------------------------------------------------- 负例：域封闭与投影核语义

def test_test_event_selector_is_unsupported_422(env):
    """test_event 不进 selector Literal（N27 封闭）；投影核对 test_event 亦恒拒。"""
    seeded = env.seed()
    member = member_of(seeded[2], 'test_event')
    payload = env.prepare_body(seeded, {'kind': 'test_event', 'member_key': member['key'],
                                        'document_id': None, 'record_index': None,
                                        'reference': dict(member['reference'])},
                               'complete_event_context')
    response = env.client.post('/v1/ai/device-evidence-packs', json=payload,
                               headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 422
    assert env.count(DeviceAIPreparation) == 0 and env.count(AIEvidencePack) == 0


@pytest.mark.parametrize('kind', ['vehicle', 'recall', 'recall_search'])
def test_restricted_member_selection_is_rejected_per_domain(env, kind):
    def restricted(envelope, target):
        # 与 domain_selector 同一 predicate，保证限制的是被选中的那个成员。
        predicate = (lambda member: member['reference']['recall_revision_id'] is not None
                     and member['payload']['records']) if target == 'recall' else None
        member = member_of(envelope, target, predicate=predicate)
        member['privacy_class'] = 'restricted'
        for document in envelope['documents']:
            if document['member_key'] == member['key']:
                document['privacy_class'] = 'restricted'

    seeded = env.seed(mutate=lambda envelope: restricted(envelope, kind))
    selector = domain_selector(seeded[2], kind)
    payload = env.prepare_body(seeded, selector, DOMAIN_MODES[kind])
    response = env.client.post('/v1/ai/device-evidence-packs', json=payload,
                               headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'device_ai_selected_restricted'
    assert env.count(DeviceAIPreparation) == 0 and env.count(AIEvidencePack) == 0


@pytest.mark.parametrize('kind', ['vehicle', 'recall', 'recall_search'])
def test_expected_projection_mismatch_is_409_per_domain(env, kind):
    seeded = env.seed()
    selector = domain_selector(seeded[2], kind)
    payload = env.prepare_body(seeded, selector, DOMAIN_MODES[kind],
                               expected_projection_sha256='0' * 64)
    response = env.client.post('/v1/ai/device-evidence-packs', json=payload,
                               headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_projection_mismatch'
    assert env.count(DeviceAIPreparation) == 0 and env.count(AIEvidencePack) == 0


def test_mode_kind_mismatch_is_rejected_by_projection_core(env):
    """vehicle selector 配 tire 模式：投影核 converter 模式排他 → 409 封闭编码。"""
    seeded = env.seed()
    selector = domain_selector(seeded[2], 'vehicle')
    payload = env.prepare_body(seeded, selector, 'single_observation')
    response = env.client.post('/v1/ai/device-evidence-packs', json=payload,
                               headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_projection_mode_unsupported'
    assert env.count(DeviceAIPreparation) == 0


@pytest.mark.parametrize('modes', ['tire+vehicle', 'vehicle+recall'])
def test_mixed_domain_selectors_in_one_request_are_rejected(env, modes):
    """同请求多域 selector：四域投影模式两两互斥，投影核恒拒（不产生任何行）。"""
    seeded = env.seed()
    if modes == 'tire+vehicle':
        tire = member_of(seeded[2], 'tire')
        first = {'kind': 'tire', 'member_key': tire['key'], 'document_id': None,
                 'record_index': None, 'reference': dict(tire['reference'])}
        second = domain_selector(seeded[2], 'vehicle')
        mode = 'single_observation'
    else:
        first = domain_selector(seeded[2], 'vehicle')
        second = domain_selector(seeded[2], 'recall')
        mode = 'complete_observation'
    payload = env.prepare_body(seeded, first, mode)
    payload['selectors'] = [first, second]
    response = env.client.post('/v1/ai/device-evidence-packs', json=payload,
                               headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_projection_mode_unsupported'
    assert env.count(DeviceAIPreparation) == 0 and env.count(AIEvidencePack) == 0


# ---------------------------------------------------------------- 负例：D4 覆盖 gate（非 tire 域）

def handcrafted(env, seeded, *, evidence_entries, contract):
    """绕过 prepare 路由直接落一对 device pack+preparation 行，驱动非 tire 域覆盖断言负例。"""
    _raw, descriptor, _envelope = seeded
    q_hash = hashlib.sha256(QUESTION.encode('utf-8')).hexdigest()
    dc_hash = hashlib.sha256(b'synthetic-device-context-domain').hexdigest()
    content = {'purpose': 'device_history_analysis', 'origin': 'device_history',
               'evidence': evidence_entries, 'facts': [], 'conflicts': [],
               'source_state': 'snapshot', 'data_state': 'local_snapshot',
               'device_context': {'schema': 'device-ai-context@1', 'device_context_fingerprint': dc_hash,
                                  'projection_sha256': hashlib.sha256(b'p').hexdigest(),
                                  'selection_sha256': hashlib.sha256(b's').hexdigest(),
                                  'question_sha256': q_hash}}
    now = utcnow()
    with env.app.state.database.sessions() as db:
        proj_hash = hashlib.sha256(b'p').hexdigest()
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
                                  intent_id=str(uuid4()),
                                  selection_hash=hashlib.sha256(b's').hexdigest(),
                                  projection_hash=proj_hash,
                                  projection_byte_count=100, device_context_fingerprint=dc_hash,
                                  question_sha256=q_hash, ai_pack_id=pack.id,
                                  contract={'schema': 'device-ai-prepare@1', **contract},
                                  created_at=now, expires_at=now + timedelta(seconds=1800))
        db.add(row)
        db.commit()
        return {'pack_id': pack.id, 'pack': {'fingerprint': pack.fingerprint}, 'id': row.id,
                'host_receipt_id': row.host_receipt_id, 'device_context_fingerprint': dc_hash}


def domain_entry(index, reference):
    return {'id': f'e{index}', 'member_key': f'{index}' * 64,
            'observed_at': '2026-01-01T00:00:00Z', 'verified_at': '2026-01-01T00:00:00Z',
            'reference': dict(reference)}


def vehicle_reference(snapshot='snap-vehicle'):
    return {'kind': 'vehicle', 'snapshot_id': snapshot, 'verification_id': 'verif'}


def test_non_tire_entry_without_contract_references_is_rejected(env):
    """空 domain_references（预期侧空）+ 内嵌非 tire 条目 → 非空断言拒绝（封静默 no-op）。"""
    seeded = env.seed()
    value = handcrafted(env, seeded, evidence_entries=[domain_entry(1, vehicle_reference())],
                        contract={'variant_ids': [], 'domain_references': {}})
    response = submit_stream(env, submission(env, value))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_evidence_coverage'
    assert env.count(AIRequest) == 0 and env.count(DeviceAIConsentClaim) == 0
    assert env.model.calls == 0


def test_non_tire_reference_drift_is_rejected_by_exact_equality(env):
    """内嵌 reference 与 contract 冻结引用不一致（snapshot 漂移）→ 精确覆盖断言拒绝。"""
    seeded = env.seed()
    value = handcrafted(env, seeded, evidence_entries=[domain_entry(1, vehicle_reference('snap-other'))],
                        contract={'variant_ids': [], 'domain_references': {'vehicle': [vehicle_reference()]}})
    response = submit_stream(env, submission(env, value))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_evidence_coverage'
    assert env.count(AIRequest) == 0


def test_cross_domain_smuggling_into_tire_contract_is_rejected(env):
    """contract 只登记 tire，evidence 混入 vehicle 条目 → 域集合精确相等断言拒绝。"""
    seeded = env.seed()
    tire_entry = {'id': 'e1', 'kind': 'tire', 'member_key': '1' * 64, 'snapshot_id': 'snap',
                  'variant_id': 'variant-one', 'verification_id': 'verif',
                  'observed_at': '2026-01-01T00:00:00Z', 'verified_at': '2026-01-01T00:00:00Z',
                  'identity_contract': {'schema': 'variant-identity@2', 'state': 'current',
                                        'current_key': 'a' * 64,
                                        'current_identity': {'kind': 'text', 'value': 'synthetic'},
                                        'identity_status': 'source_scoped'}}
    value = handcrafted(env, seeded, evidence_entries=[tire_entry, domain_entry(2, vehicle_reference())],
                        contract={'variant_ids': ['variant-one'], 'domain_references': {}})
    response = submit_stream(env, submission(env, value))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_evidence_coverage'
    assert env.count(AIRequest) == 0
