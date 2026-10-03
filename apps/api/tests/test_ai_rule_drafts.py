"""Synthetic Responses rule drafts never activate rules before explicit review."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
from threading import Event, Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select

from tire_api.ai_models import AIDraftApplication, AICompletion, AIEvidencePack, AIRequest
from tire_api.db import AlertRule, AlertRuleRevision, MonitorJob, utcnow
from tire_api.main import create_app
from test_ai import ModelFixture, analyze
from test_ai_monitoring import change_pack, latest_change
from test_core import FixtureRegistry, VARIANT, live, success


class DraftFixture(ModelFixture):
    async def generate(self, config, body):
        if body['text']['format']['name'] != 'monitor_rule_proposal':
            return await super().generate(config, body)
        self.calls.append((config, body))
        if self.failure: raise self.failure
        context = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
        output = {'proposal': {'name': '合成规则草稿', 'model': context['supported_models'][0], 'size': '265/40R20',
            'interval_seconds': 21600, 'kinds': ['facts_changed', 'variant_observed'], 'fields': ['utqg_treadwear'],
            'technology': 'Acoustic' if 'Acoustic' in context['instruction'] else None},
            'summary': '合成模型草稿，仅验证审核流程，尚未保存。', 'unsupported_requirements': [], 'clarifications': []}
        if self.mutation: self.mutation(output)
        return {'text': json.dumps(output), 'error': None,
                'usage': {'input_tokens': 200, 'output_tokens': 100, 'total_tokens': 300}, 'provider_response_id': 'resp_synthetic_draft'}


def configure(monkeypatch):
    monkeypatch.setenv('TI_AI_ENABLED', '1')
    monkeypatch.setenv('TI_OPENAI_MODEL', 'synthetic-responses')
    monkeypatch.setenv('TI_OPENAI_API_KEY', 'synthetic-never-live')
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '1')
    monkeypatch.setenv('TI_AI_DAILY_TOKEN_LIMIT', '1000000')
    monkeypatch.setenv('TI_AI_DAILY_REQUEST_LIMIT', '100')


@pytest.fixture
def setup(monkeypatch):
    configure(monkeypatch)
    registry = FixtureRegistry()
    app = create_app('sqlite://', registry)
    model = DraftFixture()
    app.state.ai_adapter = model
    with TestClient(app) as client:
        live(client)
        yield client, registry, model, app.state.database


def prepare(client, instruction='每6小时监控 Fixture Tire Acoustic 参数变化', source='fixture'):
    response = client.post('/v1/ai/rule-draft-packs', json={'source_id': source, 'instruction': instruction})
    assert response.status_code == 200, response.text
    return response.json()


def generate(client, pack, key=None, consent=True):
    return client.post('/v1/ai/rule-drafts', headers={'Idempotency-Key': key or str(uuid4())},
                       json={'pack_id': pack['id'], 'allow_external_processing': consent})


def apply(client, draft, rule=None, key=None, acknowledged=True):
    return client.post(f'/v1/ai/rule-drafts/{draft["id"]}/apply', headers={'Idempotency-Key': key or str(uuid4())},
                       json={'rule': rule or draft['draft']['rule'], 'acknowledged': acknowledged})


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_draft_proposal_has_no_side_effect_before_review_and_apply_is_once(setup):
    client, _, model, database = setup
    pack = prepare(client)
    assert pack['purpose'] == 'rule_draft' and pack['privacy_class'] == 'private'
    assert pack['supported_models'] == ['Fixture Tire'] and not model.calls
    key = str(uuid4())
    draft = generate(client, pack, key).json()
    assert draft['state'] == 'completed' and draft['draft']['can_apply']
    assert draft['draft']['rule']['enabled'] is False
    assert draft['draft']['rule']['conditions'] == {'technology': 'Acoustic'}
    assert count(database, AlertRule) == count(database, MonitorJob) == 0
    assert generate(client, pack, key).json() == draft and len(model.calls) == 1
    assert client.get('/v1/ai/analyses?mode=history').json()['items'] == []
    assert client.get(f'/v1/ai/analyses/{draft["id"]}?mode=history').status_code == 404
    assert analyze(client, pack).status_code == 422
    assert apply(client, draft, acknowledged=False).status_code == 422
    reviewed = {**draft['draft']['rule'], 'enabled': True, 'name': '人工已审核规则'}
    apply_key = str(uuid4())
    response = apply(client, draft, reviewed, apply_key)
    assert response.status_code == 201, response.text
    rule = response.json()
    assert rule['enabled'] is True and rule['origin']['draft_id'] == draft['id']
    assert apply(client, draft, reviewed, apply_key).json() == rule
    assert apply(client, draft, reviewed).json() == rule
    assert apply(client, draft, {**reviewed, 'name': 'different'}).status_code == 409
    assert count(database, AlertRule) == count(database, AIDraftApplication) == 1
    detail = client.get(f'/v1/ai/rule-drafts/{draft["id"]}?mode=history').json()
    assert detail['application']['reviewed_rule'] == reviewed
    assert client.get('/v1/alert-rules').json()['items'][0]['origin']['draft_id'] == draft['id']


@pytest.mark.parametrize('mutation', ['source', 'enabled', 'model', 'field', 'technology', 'interval', 'missing_key'])
def test_invalid_or_outside_capability_model_output_fails_closed(setup, mutation):
    client, _, model, database = setup
    def change(output):
        if mutation == 'missing_key':
            output['proposal'].pop('technology')
            return
        values = {'source': ('source_id', 'fixture-two'), 'enabled': ('enabled', True),
                  'model': ('model', 'Invented Tire'), 'field': ('fields', ['inventory']),
                  'technology': ('technology', 'invented technology'), 'interval': ('interval_seconds', 1)}
        key, value = values[mutation]
        output['proposal'][key] = value
    model.mutation = change
    draft = generate(client, prepare(client)).json()
    assert draft['state'] == 'failed' and draft['draft'] is None
    assert draft['error_code'] == 'ai_grounding_validation_failed'
    assert count(database, AlertRule) == 0


@pytest.mark.parametrize('instruction', ['每1小时监控 Fixture Tire Acoustic', 'Fixture Tire 价格低于500发邮件',
                                         'Fixture Tire 不含Acoustic时通知', 'Fixture Tire Acoustic 或 PNCS',
                                         'Fixture Tire 库存变为有货', '每小时监控 Fixture Tire',
                                         '每半小时监控 Fixture Tire', '每天监控 Fixture Tire', '每两天监控 Fixture Tire'])
def test_unsupported_intent_is_not_silently_broadened_to_applicable_rule(setup, instruction):
    client, _, _, database = setup
    draft = generate(client, prepare(client, instruction)).json()
    assert draft['state'] == 'completed' and not draft['draft']['can_apply']
    assert draft['draft']['unsupported_requirements'] or draft['draft']['clarifications']
    assert apply(client, draft).status_code == 409 and count(database, AlertRule) == 0


def test_model_cannot_drop_explicit_technology_and_missing_model_needs_clarification(setup):
    client, _, model, _ = setup
    model.mutation = lambda output: output['proposal'].update(technology=None)
    draft = generate(client, prepare(client)).json()
    assert not draft['draft']['can_apply'] and draft['draft']['clarifications']
    model.mutation = lambda output: output['proposal'].update(model=None)
    draft = generate(client, prepare(client)).json()
    assert draft['draft']['rule'] is None and not draft['draft']['can_apply']


def test_null_proposal_with_unsupported_intent_does_not_claim_model_is_missing(setup):
    client, _, model, _ = setup
    model.mutation = lambda output: output.update(proposal=None)
    draft = generate(client, prepare(client, '每小时监控 Fixture Tire 并发微信通知')).json()
    assert draft['state'] == 'completed' and draft['draft']['rule'] is None
    assert draft['draft']['unsupported_requirements'] and not draft['draft']['can_apply']
    assert draft['draft']['clarifications'] == []
    neutral = generate(client, prepare(client, '监控 Fixture Tire 参数变化')).json()
    assert neutral['draft']['unsupported_requirements'] == []
    assert neutral['draft']['clarifications'] == ['本次未形成完整规则，请核对需求与能力范围']


def test_private_consent_expiry_source_binding_and_session_isolation(setup, monkeypatch):
    client, _, model, _ = setup
    pack = prepare(client)
    assert generate(client, pack, consent=False).status_code == 422
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '0')
    assert generate(client, pack).status_code == 403 and not model.calls
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '1')
    other = TestClient(client.app)
    assert generate(other, pack).status_code == 404
    draft = generate(client, pack).json()
    assert other.get(f'/v1/ai/rule-drafts/{draft["id"]}?mode=history').status_code == 404
    assert other.get('/v1/ai/rule-drafts?mode=history').json()['items'] == []
    assert apply(other, draft).status_code == 404
    assert apply(client, draft, {**draft['draft']['rule'], 'source_id': 'fixture-two'}).status_code == 422
    from tire_api import ai_rule_drafts
    monkeypatch.setattr(ai_rule_drafts, 'utcnow', lambda: utcnow() + timedelta(minutes=31))
    assert apply(client, draft).status_code == 409
    assert generate(client, pack).status_code == 409


def test_changed_catalog_blocks_generate_and_apply(setup):
    client, registry, _, _ = setup
    pack = prepare(client)
    draft = generate(client, pack).json()
    original = registry.sources
    registry.sources = lambda: [{**source, 'supported_models': ['Different Tire']} for source in original()]
    assert generate(client, pack).status_code == 409
    assert apply(client, draft).status_code == 409


def test_required_size_missing_draft_needs_clarification_and_creates_no_rule(setup):
    client, registry, model, database = setup
    original = registry.sources
    registry.sources = lambda: [{**source, 'requires_size': True} for source in original()]
    model.mutation = lambda output: output['proposal'].update(size=None)
    pack = prepare(client)
    assert pack['source']['requires_size'] is True
    draft = generate(client, pack).json()
    assert draft['state'] == 'completed' and not draft['draft']['can_apply']
    assert any('尺寸' in item for item in draft['draft']['clarifications'])
    assert apply(client, draft).status_code == 409
    assert count(database, AlertRule) == count(database, MonitorJob) == count(database, AIDraftApplication) == 0


def test_required_size_review_cannot_drop_dimension_and_can_retry_after_correction(setup):
    client, registry, _, database = setup
    original = registry.sources
    registry.sources = lambda: [{**source, 'requires_size': True} for source in original()]
    draft = generate(client, prepare(client)).json()
    assert draft['draft']['can_apply']
    key = str(uuid4())
    reviewed = {**draft['draft']['rule'], 'query': {'model': 'Fixture Tire'}, 'enabled': True}
    response = apply(client, draft, reviewed, key)
    assert response.status_code == 422 and '尺寸' in response.json()['detail']
    assert count(database, AlertRule) == count(database, MonitorJob) == count(database, AIDraftApplication) == 0
    corrected = {**reviewed, 'query': {'model': 'Fixture Tire', 'size': '265/40ZR20'}}
    saved = apply(client, draft, corrected, key)
    assert saved.status_code == 201 and saved.json()['query']['size'] == '265/40ZR20'
    assert count(database, AlertRule) == count(database, MonitorJob) == count(database, AIDraftApplication) == 1


def test_legacy_frozen_catalog_survives_explicit_optional_size_metadata_without_rewriting_pack(setup):
    client, registry, model, database = setup
    pack = prepare(client)
    assert 'requires_size' not in pack['source']
    with database.sessions() as db:
        original_payload = deepcopy(db.get(AIEvidencePack, pack['id']).payload)
        original_fingerprint = db.get(AIEvidencePack, pack['id']).fingerprint
    original = registry.sources
    registry.sources = lambda: [{**source, 'requires_size': False} for source in original()]
    model.mutation = lambda output: output['proposal'].update(size=None)
    draft = generate(client, pack).json()
    assert draft['draft']['can_apply'] and draft['draft']['rule']['query']['size'] is None
    assert apply(client, draft).status_code == 201
    detail = client.get(f'/v1/ai/rule-drafts/{draft["id"]}?mode=history').json()
    assert 'requires_size' not in detail['pack']['source']
    with database.sessions() as db:
        saved = db.get(AIEvidencePack, pack['id'])
        assert saved.payload == original_payload and saved.fingerprint == original_fingerprint


def test_legacy_catalog_cannot_hide_a_new_required_size_capability(setup):
    client, registry, _, database = setup
    pack = prepare(client)
    draft = generate(client, pack).json()
    original = registry.sources
    registry.sources = lambda: [{**source, 'requires_size': True} for source in original()]
    assert generate(client, pack).status_code == 409
    assert apply(client, draft).status_code == 409
    assert count(database, AlertRule) == count(database, MonitorJob) == count(database, AIDraftApplication) == 0


def test_reviewed_human_edits_are_recorded_and_application_is_immutable(setup):
    client, _, _, database = setup
    draft = generate(client, prepare(client)).json()
    reviewed = {**draft['draft']['rule'], 'conditions': {}, 'enabled': True, 'name': '人工改为全部技术'}
    response = apply(client, draft, reviewed)
    assert response.status_code == 201 and response.json()['conditions'] == {}
    detail = client.get(f'/v1/ai/rule-drafts/{draft["id"]}?mode=history').json()
    assert detail['draft']['rule']['conditions'] == {'technology': 'Acoustic'}
    assert detail['application']['reviewed_rule'] == reviewed
    with database.sessions() as db:
        row = db.scalar(select(AIDraftApplication))
        row.payload_hash = 'overwrite'
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()


def test_application_failure_rolls_back_rule_job_and_mapping_together(setup):
    client, _, model, database = setup
    draft = generate(client, prepare(client)).json()
    key = str(uuid4())
    def fail(_connection, _cursor, statement, *_args):
        if statement.startswith('INSERT INTO ai_draft_applications'):
            raise RuntimeError('synthetic mapping failure')
    event.listen(database.engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='mapping failure'):
            apply(client, draft, key=key)
    finally:
        event.remove(database.engine, 'before_cursor_execute', fail)
    assert count(database, AlertRule) == count(database, MonitorJob) == count(database, AIDraftApplication) == 0
    assert count(database, AICompletion) == 1 and len(model.calls) == 1
    assert apply(client, draft, key=key).status_code == 201
    assert count(database, AlertRule) == count(database, AIDraftApplication) == 1


@pytest.mark.parametrize('size', [None, '265/40R20'])
def test_explicit_size_cannot_be_dropped_or_replaced(setup, size):
    client, _, model, _ = setup
    model.mutation = lambda output: output['proposal'].update(size=size)
    draft = generate(client, prepare(client, '监控 Fixture Tire 245/40R20')).json()
    assert draft['state'] == 'completed' and not draft['draft']['can_apply']
    assert any('尺寸' in item for item in draft['draft']['clarifications'])


def test_explicit_ps4s_cannot_be_replaced_by_psev_in_same_source_catalog(setup):
    client, registry, model, _ = setup
    original = registry.sources
    registry.sources = lambda: [{**source, 'supported_models': ['Pilot Sport 4 S', 'Pilot Sport EV']} for source in original()]
    model.mutation = lambda output: output['proposal'].update(model='Pilot Sport EV')
    draft = generate(client, prepare(client, '监控PS4S参数变化')).json()
    assert draft['state'] == 'completed' and not draft['draft']['can_apply']
    assert any('型号' in item for item in draft['draft']['clarifications'])


@pytest.mark.parametrize('instruction,change,expected', [
    ('只监控 Fixture Tire utqg_treadwear', {'fields': []}, '字段范围'),
    ('首次观察到 Fixture Tire Acoustic 新规格才提醒', {'kinds': ['facts_changed']}, '事件类型'),
    ('只监控 Fixture Tire 参数变化', {'kinds': ['variant_observed']}, '事件类型'),
])
def test_model_cannot_drop_explicit_field_or_event_scope(setup, instruction, change, expected):
    client, _, model, _ = setup
    model.mutation = lambda output: output['proposal'].update(change)
    draft = generate(client, prepare(client, instruction)).json()
    assert draft['state'] == 'completed' and not draft['draft']['can_apply']
    assert any(expected in item for item in draft['draft']['clarifications'])


def verify_monitor_ai_persistence(url):
    with pytest.MonkeyPatch.context() as monkeypatch:
        configure(monkeypatch)
        registry = FixtureRegistry()
        app = create_app(url, registry)
        model = DraftFixture()
        app.state.ai_adapter = model
        with TestClient(app) as client:
            live(client)
            registry.result = success('monitor-ai-fixture-new', [{**VARIANT, 'facts': {'utqg_treadwear': 425}}])
            live(client)
            pack = change_pack(client, latest_change(app.state.database)).json()['pack']
            analysis = analyze(client, pack).json()
            assert analysis['state'] == 'completed' and pack['conflicts'] == []
            draft_pack = prepare(client)
            entered, release = Event(), Event()
            class SlowFixture(DraftFixture):
                async def generate(self, config, body):
                    entered.set()
                    assert await asyncio.to_thread(release.wait, 10)
                    return await super().generate(config, body)
            slow = SlowFixture()
            app.state.ai_adapter = slow
            key = str(uuid4())
            with ThreadPoolExecutor(max_workers=2) as pool:
                running = pool.submit(generate, client, draft_pack, key)
                try:
                    assert entered.wait(10)
                    duplicate = generate(client, draft_pack, key)
                    assert duplicate.status_code == 202 and duplicate.json()['state'] == 'pending'
                    assert generate(client, draft_pack).status_code == 429
                finally:
                    release.set()
                draft = running.result(timeout=15).json()
            assert draft['state'] == 'completed' and len(slow.calls) == 1
            assert generate(client, draft_pack, key).json() == draft
            # A separately acknowledged save is the only path that creates a rule.
            reviewed = {**draft['draft']['rule'], 'enabled': True, 'name': '人工确认合成规则'}
            barrier = Barrier(2)
            apply_key = str(uuid4())
            def save(_):
                barrier.wait(timeout=10)
                return apply(client, draft, reviewed, apply_key)
            with ThreadPoolExecutor(max_workers=2) as pool:
                values = list(pool.map(save, range(2)))
            assert all(value.status_code == 201 for value in values), [value.text for value in values]
            assert values[0].json() == values[1].json()
            rule = values[0].json()
            checkpoint = {'session_id': client.cookies.get('tire_local_session'), 'request_id': draft['id'],
                'rule_id': rule['id'], 'conditions': {'technology': 'Acoustic'}, 'analysis_id': analysis['id'],
                'change_id': pack['evidence'][0]['change_id']}
        assert_monitor_ai_checkpoint(url, checkpoint)
        return checkpoint


def assert_monitor_ai_checkpoint(url, checkpoint):
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        client.cookies.set('tire_local_session', checkpoint['session_id'])
        draft = client.get(f'/v1/ai/rule-drafts/{checkpoint["request_id"]}?mode=history').json()
        assert draft['state'] == 'completed' and draft['application']['rule_id'] == checkpoint['rule_id']
        assert draft['application']['reviewed_rule']['conditions'] == checkpoint['conditions']
        rule = client.get(f'/v1/alert-rules/{checkpoint["rule_id"]}?mode=history').json()
        assert rule['conditions'] == checkpoint['conditions'] and rule['origin']['draft_id'] == checkpoint['request_id']
        assert client.get(f'/v1/ai/analyses/{checkpoint["request_id"]}?mode=history').status_code == 404
        assert checkpoint['request_id'] not in {row['id'] for row in client.get('/v1/ai/analyses?mode=history').json()['items']}
        analysis = client.get(f'/v1/ai/analyses/{checkpoint["analysis_id"]}?mode=history').json()
        assert analysis['pack']['evidence'][0]['change_id'] == checkpoint['change_id']


def test_file_database_paid_and_apply_concurrency_restart(tmp_path):
    verify_monitor_ai_persistence('sqlite:///' + (tmp_path / 'monitor-ai.db').as_posix())
