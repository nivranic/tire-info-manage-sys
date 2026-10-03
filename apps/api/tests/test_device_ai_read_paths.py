"""隔离读取路径测试：旧 GET 入口对 device pack 的 origin 标记视图（步骤7 验证段）。

对齐 test_device_ai_routes_prepare 的隔离形态：内存库 + 临时对象目录 + FixtureRegistry，
不触正常库、不启动 Provider。device pack 用第一波 prepare 路由创建；legacy 仓库
history 包分别用真实仓库 prepare 路由与直插行对照，锁定“旧仓库包不追溯标注、不改旧
DTO”（圆桌路由 #10 / D11）。
"""
from datetime import timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from tire_api.ai_models import AIEvidencePack
from tire_api.db import utcnow
from tire_api.device_ai_models import DeviceAIPreparation
from tire_api.domain import digest
from tire_api.main import create_app
from test_core import FixtureRegistry, live
from test_device_ai_routes_prepare import RouteEnv, created_and_viewed

# D11：仓库 field 合同伪装键与仓库专属键（device payload 顶层禁用）。
WAREHOUSE_KEYS = {'field_policy', 'field_resolutions', 'field_resolution_format',
                  'field_resolution_materials', 'query_id', 'consent_id',
                  'recall_policy', 'recall_boundary'}


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


def get_pack(env, pack_id):
    return env.client.get(f'/v1/ai/evidence-packs/{pack_id}', params={'mode': 'history'})


def test_device_pack_get_returns_origin_marked_manifest_view(env):
    value = created_and_viewed(env, env.seed())
    response = get_pack(env, value['pack_id'])
    assert response.status_code == 200, response.text
    view = response.json()
    # 保留键一律来自行数据；origin 由 preparation 回查（D1 结构判别）服务端派生。
    assert view['id'] == value['pack_id']
    assert view['origin'] == 'device_history'
    assert view['mode'] == 'history' and view['data_state'] == 'local_snapshot'
    assert view['privacy_class'] == 'private'
    assert view['fingerprint'] == value['pack']['fingerprint']
    assert view['created_at'] == value['pack']['created_at']
    assert view['purpose'] == 'device_history_analysis'
    assert view['source_state'] == 'snapshot'
    assert view['device_context']['schema'] == 'device-ai-context@1'
    assert view['device_context']['question_sha256'] == value['question_sha256']
    assert view['evidence'] and view['evidence'][0]['identity_contract']['state'] == 'current'
    assert view['facts'] == [] and view['conflicts'] == []
    # 键名负例：device 视图不携带仓库 field 合同伪装键（第一波已保证，读取路径锁定）。
    assert not (WAREHOUSE_KEYS & view.keys())


def test_warehouse_history_pack_view_stays_unmarked_and_unchanged(env):
    result = live(env.client).json()
    created = env.client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [
        {'kind': 'tire', 'snapshot_id': result['provenance'][0]['snapshot_id'],
         'variant_id': result['variants'][0]['id']}]})
    assert created.status_code == 200, created.text
    pack = created.json()['pack']
    response = get_pack(env, pack['id'])
    assert response.status_code == 200, response.text
    view = response.json()
    assert 'origin' not in view          # 旧仓库包不追溯标注 device origin。
    assert view == pack                  # 旧 DTO 逐键不变（含 field_resolutions 展开形状）。
    assert 'field_policy' in view and 'field_resolutions' in view
    assert view['retrieval'] == 'exact_structured_lookup'
    env.client.cookies.clear()
    assert get_pack(env, pack['id']).status_code == 404


def test_synthetic_warehouse_pack_view_is_exactly_the_legacy_dto(env):
    payload = {'retrieval': 'exact_structured_lookup', 'evidence': [], 'facts': [],
               'field_policy': {'synthetic': 'policy'}, 'conflicts': [], 'query_id': None,
               'consent_id': None, 'source_state': 'snapshot'}
    with env.app.state.database.sessions() as db:
        row = AIEvidencePack(actor_session_id=env.session_id, mode='history', data_state='local_snapshot',
                             privacy_class='private', payload=payload, fingerprint=digest(payload),
                             expires_at=utcnow() + timedelta(minutes=30))
        db.add(row)
        db.commit()
        pack_id = row.id
    response = get_pack(env, pack_id)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view == {'id': pack_id, 'mode': 'history', 'data_state': 'local_snapshot',
                    'privacy_class': 'private', 'created_at': view['created_at'],
                    'expires_at': view['expires_at'], 'fingerprint': digest(payload), **payload}
    assert 'origin' not in view


def test_device_pack_get_is_owned_and_foreign_session_gets_404(env):
    value = created_and_viewed(env, env.seed())
    env.client.cookies.clear()
    assert get_pack(env, value['pack_id']).status_code == 404


def test_device_payload_and_evidence_carry_no_warehouse_shapes(env):
    value = created_and_viewed(env, env.seed())
    with env.app.state.database.sessions() as db:
        row = db.scalar(select(DeviceAIPreparation).where(DeviceAIPreparation.id == value['id']))
        pack = db.get(AIEvidencePack, row.ai_pack_id)
        assert not (WAREHOUSE_KEYS & pack.payload.keys())
        assert pack.payload['origin'] == 'device_history'
        for entry in pack.payload['evidence']:
            assert not ({'candidates', 'context_ref', 'reasons_ref'} & entry.keys())
    view = get_pack(env, value['pack_id']).json()
    assert not (WAREHOUSE_KEYS & view.keys())
