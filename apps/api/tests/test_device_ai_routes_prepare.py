"""隔离路由测试：设备 AI prepare 三端点（圆桌纪要步骤2/3 验证段）。

对齐 test_ai.py 的隔离形态：内存库 + 临时对象目录 + FixtureRegistry，不触正常库、
不启动 Provider、不访问网络。归档原件取 producer-v2 样本的合成归属副本（样本字节
仅 owner_scope_id 替换为测试会话的派生值，长度不变；样本身份由既有 97/92 测试锚定）。
过期读用时间平移（monkeypatch device_ai_routes.utcnow 越过 expires_at）模拟时间流逝；
013 账本触发器对一切 UPDATE（含 text() TextClause）RAISE FAIL，行必须保持零改动。
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from tire_api.ai_models import AIEvidencePack
from tire_api.db import AuditEvent, EvidenceObject, utc, utcnow
from tire_api.device_ai_models import DeviceAIPreparation
from tire_api.device_ai_projection import (FrozenPackBinding, ProjectionError, exact_digest,
                                           parse_exact_json, project_offline_pack)
from tire_api.domain import digest
from tire_api.main import create_app
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from test_core import FixtureRegistry

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / '.artifacts/query-fallback49/producer-v2-samples-a'
QUESTION = 'P225 这条轮胎的历史参数如何解读？'
FORBIDDEN_KEYS = {'field_policy', 'field_resolutions', 'field_resolution_format',
                  'field_resolution_materials', 'query_id', 'consent_id', 'recall_policy',
                  'recall_boundary', 'mode', 'privacy_class', 'created_at', 'expires_at',
                  'fingerprint', 'id'}


def tire_member(envelope):
    return next(member for member in envelope['members'] if member['reference']['kind'] == 'tire')


def tire_selector(envelope):
    member = tire_member(envelope)
    document = next(row for row in envelope['documents'] if row['member_key'] == member['key'])
    return {'kind': 'tire', 'member_key': member['key'], 'document_id': document['id'],
            'record_index': None, 'reference': deepcopy(member['reference'])}


def finalize_bytes(envelope):
    raw = json.dumps(envelope, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return raw, hashlib.sha256(raw).hexdigest()


def inflate_fields(envelope, copies):
    """复制合法 field 条目（改名保证唯一）撑大投影；候选回执不变故仍唯一命中成员。"""
    if copies <= 0:
        return
    member = tire_member(envelope)
    fields = member['payload']['field_resolution']['fields']
    template = deepcopy(fields[0])
    extra = []
    for index in range(copies):
        copy = deepcopy(template)
        copy['field'] = f'synthetic.field_{index}'
        for candidate in copy['candidates']:
            candidate['field'] = copy['field']
        extra.append(copy)
    member['payload']['field_resolution']['fields'] = fields + extra


def projected_size(base_envelope, selector, copies):
    envelope = deepcopy(base_envelope)
    inflate_fields(envelope, copies)
    raw, sha = finalize_bytes(envelope)
    try:
        return len(project_offline_pack(raw, FrozenPackBinding(envelope['package_id'],
                                                               envelope['owner_scope_id'], sha, len(raw),
                                                               envelope['schema']),
                                        [deepcopy(selector)]).canonical_bytes)
    except ProjectionError as error:
        if error.code == 'device_ai_projection_capacity':
            return 44_001  # 超限即视为达到目标，二分继续收敛
        raise


def copies_reaching(base_envelope, selector, target_bytes):
    """二分查找使投影 canonical 首次达到目标字节的复制份数（投影大小随份数单调）。"""
    high = 1
    while projected_size(base_envelope, selector, high) < target_bytes:
        high *= 2
    low = 0
    while low < high:
        middle = (low + high) // 2
        if projected_size(base_envelope, selector, middle) < target_bytes:
            low = middle + 1
        else:
            high = middle
    return low


class RouteEnv:
    def __init__(self, client, app, session_id):
        self.client, self.app, self.session_id = client, app, session_id

    def seed(self, *, mutate=None, name='nonempty'):
        original = (SAMPLES / f'{name}-pack.json').read_bytes()
        descriptor = json.loads((SAMPLES / f'{name}-descriptor.json').read_bytes())
        envelope = json.loads(original)
        envelope['owner_scope_id'] = digest({'namespace': 'offline-owner-scope@1', 'session': self.session_id})
        if mutate is not None:
            mutate(envelope)
        raw, sha = finalize_bytes(envelope)
        descriptor.update(sha256=sha, byte_count=len(raw), owner_scope_id=envelope['owner_scope_id'])
        store = self.app.state.database.object_store
        assert store.put(raw) == sha
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

    def body(self, seeded, *, question=QUESTION, selector=None, **overrides):
        raw, descriptor, envelope = seeded
        chosen = selector or tire_selector(envelope)
        binding = FrozenPackBinding(descriptor['id'], descriptor['owner_scope_id'], descriptor['sha256'],
                                    descriptor['byte_count'], envelope['schema'])
        try:
            expected = project_offline_pack(raw, binding, [deepcopy(chosen)]).sha256
        except ProjectionError:
            expected = '0' * 64
        value = {'package_id': descriptor['id'], 'expected_sha256': descriptor['sha256'],
                 'expected_byte_count': descriptor['byte_count'], 'expected_schema': envelope['schema'],
                 'expected_owner_scope_id': descriptor['owner_scope_id'], 'selectors': [chosen],
                 'projection_mode': 'single_observation', 'expected_projection_sha256': expected,
                 'question_sha256': hashlib.sha256(question.encode('utf-8')).hexdigest(),
                 'host_receipt_id': str(uuid4()), 'intent_id': str(uuid4())}
        value.update(overrides)
        return value

    def post(self, payload, key=None):
        return self.client.post('/v1/ai/device-evidence-packs',
                                headers={'Idempotency-Key': key or str(uuid4())}, json=payload)

    def count(self, model):
        with self.app.state.database.sessions() as db:
            return db.scalar(select(func.count()).select_from(model))


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv('TI_OBJECT_STORE_BACKEND', 'filesystem')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    monkeypatch.setenv('TI_OBSERVABILITY_ENABLED', '0')
    app = create_app('sqlite://', FixtureRegistry())
    with TestClient(app) as client:
        client.get('/health')
        yield RouteEnv(client, app, client.cookies['tire_local_session'])


def created_and_viewed(env, seeded):
    response = env.post(env.body(seeded))
    assert response.status_code == 201, response.text
    return response.json()


def test_prepare_creates_pack_preparation_audit_and_projection_object(env):
    seeded = env.seed()
    payload = env.body(seeded)
    selector = payload['selectors'][0]
    binding = FrozenPackBinding(seeded[1]['id'], seeded[1]['owner_scope_id'], seeded[1]['sha256'],
                                seeded[1]['byte_count'], seeded[2]['schema'])
    projection = project_offline_pack(seeded[0], binding, [deepcopy(selector)])
    response = env.post(payload)
    assert response.status_code == 201, response.text
    value = response.json()
    assert value['replayed'] is False and value['expired'] is False
    assert response_headers_nostore(env) is True
    material = parse_exact_json(projection.canonical_bytes)
    observations = material['observations']
    expected_selection = exact_digest([item['selector'] for item in observations],
                                      namespace='device-ai-selection@1')
    expected_context = exact_digest({
        'schema': 'device-ai-context@1', 'package_id': seeded[1]['id'],
        'package_schema': seeded[2]['schema'], 'package_sha256': seeded[1]['sha256'],
        'projection_mode': 'single_observation', 'projection_sha256': projection.sha256,
        'selection_sha256': expected_selection,
        'receipt_sources': [{'selector': item['selector'], 'selection_reason': item['selection_reason'],
                             'source': item['source']} for item in observations],
        'device_citations': [], 'domain_boundaries': [], 'numeric_encoding': 'device-number-token@1'},
        namespace='device-ai-context@1')
    with env.app.state.database.sessions() as db:
        row = db.get(DeviceAIPreparation, value['id'])
        assert row.projection_hash == projection.sha256 == value['projection_sha256']
        assert row.projection_byte_count == len(projection.canonical_bytes)
        assert row.selection_hash == expected_selection
        assert row.device_context_fingerprint == expected_context
        assert row.question_sha256 == payload['question_sha256']
        assert row.offline_pack_id == seeded[1]['id'] and row.offline_content_hash == seeded[1]['sha256']
        assert row.host_receipt_id == payload['host_receipt_id'] and row.intent_id == payload['intent_id']
        assert utc(row.expires_at) - utc(row.created_at) == timedelta(seconds=1800)
        assert row.contract['variant_ids'] == [selector['reference']['variant_id']]
        assert row.contract['member_keys'] == [selector['member_key']]
        pack = db.get(AIEvidencePack, row.ai_pack_id)
        assert pack.mode == 'history' and pack.data_state == 'local_snapshot'
        assert pack.privacy_class == 'private'
        assert utc(pack.expires_at) - utc(pack.created_at) == timedelta(seconds=1800)
        assert pack.fingerprint == digest(pack.payload)
        assert pack.payload['source_state'] == 'snapshot' and pack.payload['data_state'] == 'local_snapshot'
        assert pack.payload['purpose'] == 'device_history_analysis'
        assert pack.payload['origin'] == 'device_history'
        assert not (FORBIDDEN_KEYS & pack.payload.keys())
        assert pack.payload['conflicts'] == [] and pack.payload['facts'] == []
        assert pack.payload['device_context']['projection_sha256'] == projection.sha256
        assert pack.payload['device_context']['question_sha256'] == payload['question_sha256']
        entry = pack.payload['evidence'][0]
        assert entry['id'] == 'e1' and entry['kind'] == 'tire'
        assert entry['snapshot_id'] == selector['reference']['snapshot_id']
        assert entry['variant_id'] == selector['reference']['variant_id']
        assert entry['verification_id'] == selector['reference']['verification_id']
        assert sorted(entry['identity_contract']) == ['current_identity', 'current_key',
                                                      'identity_status', 'schema', 'state']
        assert entry['identity_contract']['state'] == 'current'
        dimensions = entry['identity_contract']['current_identity']
        assert dimensions['kind'] == 'structured'
        assert {'brand', 'size'} <= {item['name'] for item in dimensions['fields']}
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == 'device_ai_preparation_created'))
        assert audit.session_id == env.session_id and audit.detail['preparation_id'] == row.id
        assert audit.detail['projection_sha256'] == projection.sha256
        stored = db.get(EvidenceObject, projection.sha256)
    assert stored.byte_count == len(projection.canonical_bytes)
    # 无截断：对象存储逐字节等于投影 canonical。
    assert env.app.state.database.object_store.get(projection.sha256,
                                                   len(projection.canonical_bytes)) == projection.canonical_bytes
    # 数字只以 DeviceAIValue token DTO 形态出现（禁 as_token_dto）。
    def walk(node):
        if isinstance(node, dict):
            if node.get('kind') == 'number':
                assert node['value']['schema'] == 'device-number-token@1'
                assert isinstance(node['value']['token'], str)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(pack.payload)
    # pack_view 保留键来自行数据，不被 payload 覆盖（D11）。
    assert value['pack']['id'] == pack.id and value['pack']['mode'] == 'history'
    assert value['pack']['data_state'] == 'local_snapshot' and value['pack']['fingerprint'] == pack.fingerprint
    preview = value['provider_preview']
    assert preview['state'] == 'ai_disabled' and preview['connection_verified'] is False
    budget = preview['outbound_budget']
    assert budget['basis'] == 'shared request_body measurement + D18 scheme-B minimal assembly'
    assert budget['blocked'] is False
    assert budget['truncated'] is False
    assert budget['evidence_only_request_bytes'] < 48_000


def response_headers_nostore(env):
    return env.client.get(f"/v1/ai/device-evidence-packs/lookup?mode=history&idempotency_key={uuid4()}"
                          ).headers.get('cache-control') == 'no-store'


def test_replay_same_body_returns_original_without_touching_archive(env):
    seeded = env.seed()
    payload = env.body(seeded)
    key = str(uuid4())
    first, second = env.post(payload, key), env.post(payload, key)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()['replayed'] is True and first.json()['replayed'] is False
    assert second.json()['id'] == first.json()['id']
    assert second.json()['created_at'] == first.json()['created_at']
    assert second.json()['expires_at'] == first.json()['expires_at']
    assert env.count(DeviceAIPreparation) == 1 and env.count(AIEvidencePack) == 1
    assert env.count(OfflinePack) == 1


def test_same_key_with_different_body_is_rejected(env):
    seeded = env.seed()
    key = str(uuid4())
    assert env.post(env.body(seeded), key).status_code == 201
    response = env.post(env.body(seeded, question='另一个完全不同的问题'), key)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_prepare_idempotency_mismatch'
    assert env.count(DeviceAIPreparation) == 1


@pytest.mark.parametrize('field', ['host_receipt_id', 'intent_id'])
def test_reuse_of_receipt_or_intent_with_new_key_maps_unique_violation_to_closed_409(env, field):
    seeded = env.seed()
    payload = env.body(seeded)
    first = env.post(payload)
    assert first.status_code == 201, first.text
    reused = dict(payload)
    reused[field] = first.json()[field]
    second = env.post(reused)
    assert second.status_code == 409
    assert second.json()['detail']['code'] == 'device_ai_prepare_conflict'
    assert 'UNIQUE' not in second.text and 'IntegrityError' not in second.text
    assert env.count(DeviceAIPreparation) == 1


def test_expected_projection_mismatch_is_409_without_any_row(env):
    seeded = env.seed()
    payload = env.body(seeded, expected_projection_sha256='0' * 64)
    response = env.post(payload)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_projection_mismatch'
    assert env.count(DeviceAIPreparation) == 0 and env.count(AIEvidencePack) == 0


def test_restricted_member_selection_is_rejected_closed(env):
    def restricted(envelope):
        member = tire_member(envelope)
        member['privacy_class'] = 'restricted'
        for document in envelope['documents']:
            if document['member_key'] == member['key']:
                document['privacy_class'] = 'restricted'
    seeded = env.seed(mutate=restricted)
    response = env.post(env.body(seeded))
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'device_ai_selected_restricted'
    assert env.count(DeviceAIPreparation) == 0 and env.count(AIEvidencePack) == 0


def test_projection_over_44k_is_rejected_without_truncation(env):
    probe = json.loads((SAMPLES / 'nonempty-pack.json').read_bytes())
    copies = copies_reaching(probe, tire_selector(probe), 44_001)
    seeded = env.seed(mutate=lambda envelope: inflate_fields(envelope, copies))
    response = env.post(env.body(seeded))
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'device_ai_projection_capacity'
    assert env.count(DeviceAIPreparation) == 0 and env.count(AIEvidencePack) == 0


def test_legacy_identity_fails_early_before_any_row(env):
    def legacy(envelope):
        identity = tire_member(envelope)['payload']['identity_contract']
        identity.update(state='legacy_unbound', current_key=None, current_identity=None,
                        identity_status=None, tracking_state='identity_review_required')
    seeded = env.seed(mutate=legacy)
    response = env.post(env.body(seeded))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_identity_not_current'
    assert env.count(DeviceAIPreparation) == 0 and env.count(AIEvidencePack) == 0


def test_test_event_selector_domain_is_unsupported_422(env):
    """P1-4a 后四域放开；test_event 仍不进 selector Literal（N27 封闭，DTO 层 422）。"""
    seeded = env.seed()
    _raw, _descriptor, envelope = seeded
    event = next(member for member in envelope['members'] if member['reference']['kind'] == 'test_event')
    payload = env.body(seeded, selector={'kind': 'test_event', 'member_key': event['key'],
                                         'document_id': None, 'record_index': None,
                                         'reference': dict(event['reference'])},
                       projection_mode='complete_event_context')
    response = env.post(payload)
    assert response.status_code == 422
    assert env.count(DeviceAIPreparation) == 0


def test_archive_not_found_and_expected_mismatch_keep_closed_codes(env):
    seeded = env.seed()
    missing = env.body(seeded, package_id='missing-package')
    assert env.post(missing).status_code == 404
    assert env.post(missing).json()['detail']['code'] == 'device_ai_archive_not_found'
    wrong_owner = env.body(seeded, expected_owner_scope_id='e' * 64)
    response = env.post(wrong_owner)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'device_ai_archive_expected_mismatch'
    assert env.count(DeviceAIPreparation) == 0


def test_non_uuid_idempotency_key_is_422(env):
    seeded = env.seed()
    response = env.post(env.body(seeded), key='not-a-uuid')
    assert response.status_code == 422
    assert env.count(DeviceAIPreparation) == 0


def test_prepare_makes_zero_external_calls(env, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('prepare 阶段不得触发外联调用')

    async def no_provider(*args, **kwargs):
        raise AssertionError('prepare 阶段不得调用 Provider')

    import tire_api.ai_evidence as ai_evidence
    import tire_api.embedding_service as embedding_service
    import tire_api.recalls as recalls
    from tire_api import device_ai_routes
    from tire_api.ai_gateway import OpenAIResponsesAdapter
    monkeypatch.setattr(ai_evidence, 'prepare_pack', forbidden)
    monkeypatch.setattr(recalls, 'RecallService', forbidden)
    monkeypatch.setattr(embedding_service, 'prepare_plan', forbidden)
    monkeypatch.setattr(embedding_service, 'reserve_request', forbidden)
    monkeypatch.setattr(OpenAIResponsesAdapter, 'generate', no_provider)
    monkeypatch.setattr(OpenAIResponsesAdapter, 'stream', no_provider)
    assert not hasattr(device_ai_routes, 'prepare_pack')
    assert not hasattr(device_ai_routes, 'RecallService')
    assert created_and_viewed(env, env.seed())['replayed'] is False


def test_lookup_literal_route_precedes_parameter_route_and_recovers(env):
    paths = [route.path for route in env.app.routes
             if getattr(route, 'path', '').startswith('/v1/ai/device-evidence-packs')]
    assert paths.index('/v1/ai/device-evidence-packs/lookup') < paths.index(
        '/v1/ai/device-evidence-packs/{prepare_id}')
    value = created_and_viewed(env, env.seed())
    lookup = env.client.get('/v1/ai/device-evidence-packs/lookup', params={
        'mode': 'history', 'idempotency_key': value['idempotency_key']})
    assert lookup.status_code == 200 and lookup.json()['id'] == value['id']
    assert lookup.headers['cache-control'] == 'no-store'
    missing = env.client.get('/v1/ai/device-evidence-packs/lookup', params={
        'mode': 'history', 'idempotency_key': str(uuid4())})
    assert missing.status_code == 404
    detail = env.client.get(f"/v1/ai/device-evidence-packs/{value['id']}", params={'mode': 'history'})
    assert detail.status_code == 200 and detail.json()['pack']['id'] == value['pack_id']
    assert env.client.get(f"/v1/ai/device-evidence-packs/{uuid4()}", params={'mode': 'history'}).status_code == 404


def test_detail_is_owned_and_foreign_session_gets_404(env):
    value = created_and_viewed(env, env.seed())
    env.client.cookies.clear()
    assert env.client.get(f"/v1/ai/device-evidence-packs/{value['id']}",
                          params={'mode': 'history'}).status_code == 404


def test_expired_preparation_reads_return_original_record_without_rewrite(env, monkeypatch):
    from tire_api import device_ai_routes

    seeded = env.seed()
    key = str(uuid4())
    payload = env.body(seeded)
    first = env.post(payload, key)
    assert first.status_code == 201
    value = first.json()
    # 013 账本触发器封死一切 UPDATE（含 text() 直改 created_at/expires_at），改用时间
    # 平移：行保持零改动，只把 device_ai_routes.utcnow 推到 expires_at 之后，读取与
    # replay 仍走真实过期分支（replay 命中即返回，不会触 _append_preparation 的 now）。
    future = utc(datetime.fromisoformat(value['expires_at'])) + timedelta(seconds=1)
    monkeypatch.setattr(device_ai_routes, 'utcnow', lambda: future)
    detail = env.client.get(f"/v1/ai/device-evidence-packs/{value['id']}", params={'mode': 'history'})
    assert detail.status_code == 200
    assert detail.json()['expired'] is True
    assert detail.json()['expires_at'] == value['expires_at']
    assert detail.json()['created_at'] == value['created_at']
    replay = env.post(payload, key)
    assert replay.status_code == 200 and replay.json()['replayed'] is True
    assert replay.json()['id'] == value['id'] and replay.json()['expired'] is True
    assert replay.json()['expires_at'] == detail.json()['expires_at']
    assert replay.json()['created_at'] == detail.json()['created_at']
    assert env.count(DeviceAIPreparation) == 1


def test_outbound_budget_vector_minimal_assembly_far_below_48k_gate_without_truncation(env):
    """D18 方案B向量：44k 级投影的外发按最小化组装计量，远低于 48k gate 且无截断。

    策略A（全量直发上界）下 40k 投影 + 8k问题上界曾确实超限（blocked=true）；
    方案B后 device_context/manifest/成员理由结构性不外发，计量只覆盖白名单组装
    （回执+身份+引用标签+question占位），预检与 submit 共用同一组装函数（D12 反漂移）。
    """
    probe = json.loads((SAMPLES / 'nonempty-pack.json').read_bytes())
    selector = tire_selector(probe)
    copies = copies_reaching(probe, selector, 40_000)
    seeded = env.seed(mutate=lambda envelope: inflate_fields(envelope, copies))
    payload = env.body(seeded)
    binding = FrozenPackBinding(seeded[1]['id'], seeded[1]['owner_scope_id'], seeded[1]['sha256'],
                                seeded[1]['byte_count'], seeded[2]['schema'])
    projection = project_offline_pack(seeded[0], binding, [deepcopy(payload['selectors'][0])])
    assert 39_000 < len(projection.canonical_bytes) <= 44_000
    response = env.post(payload)
    assert response.status_code == 201, response.text
    value = response.json()
    budget = value['provider_preview']['outbound_budget']
    assert budget['basis'] == 'shared request_body measurement + D18 scheme-B minimal assembly'
    assert budget['projection_bytes'] == len(projection.canonical_bytes)
    assert budget['question_upper_bound_bytes'] == 8_000
    # 方案B显著下降：44k 投影的外发上界远小于 48k gate（策略A下此处 >48k 且 blocked）。
    assert budget['upper_bound_request_bytes'] < 12_000 < 48_000
    assert budget['evidence_only_request_bytes'] < budget['upper_bound_request_bytes']
    assert budget['blocked'] is False
    assert budget['shortfall_bytes'] == 0
    assert budget['truncated'] is False
    # D12 反漂移：预检计量=submit 侧对同一 pack 走同一 _device_request_evidence +
    # outbound_measurement 的真实值（真实 evidence 下界与问题上界逐字节相等）。
    with env.app.state.database.sessions() as db:
        row = db.get(DeviceAIPreparation, value['id'])
        pack = db.get(AIEvidencePack, row.ai_pack_id)
        from tire_api.ai_analysis import _device_request_evidence
        from tire_api.ai_gateway import outbound_measurement
        minimal = _device_request_evidence({**pack.payload, 'data_state': pack.data_state})
        expected_floor, _unused = outbound_measurement('', minimal, max_output_tokens=0)
        placeholder = '\U0001d546' * 2_000
        expected_upper, _unused = outbound_measurement(placeholder, minimal, max_output_tokens=0)
        assert budget['evidence_only_request_bytes'] == expected_floor
        assert budget['upper_bound_request_bytes'] == expected_upper
        # 计量材料红线：本机/审计字段不进外发组装（44k 投影本体只落对象存储与行账）。
        serialized = json.dumps(minimal, ensure_ascii=False)
        for forbidden in ('device_context', 'member_key', 'package_sha256', 'projection_sha256',
                          'selection_sha256', 'question_sha256', 'numeric_encoding',
                          'purpose', 'origin'):
            assert forbidden not in serialized, forbidden
        # 无截断：落账投影与重算投影逐字节一致，且行数据完整。
        stored = env.app.state.database.object_store.get(value['projection_sha256'],
                                                         value['projection_byte_count'])
        assert stored == projection.canonical_bytes
        assert row.projection_byte_count == len(projection.canonical_bytes)
        assert pack.fingerprint == digest(pack.payload)
        assert len(pack.payload['device_context']['projection_sha256']) == 64
