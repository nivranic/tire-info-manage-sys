"""Frozen report behavior; all source and model fixtures are explicitly synthetic."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
from html.parser import HTMLParser
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.db import EvidenceDocument, EvidenceObject, FactVersion, Snapshot, utcnow
from tire_api.domain import digest
from tire_api.main import create_app
from tire_api.report_models import ReportExport, ResearchReport, ResearchReportRevision
from test_ai import ModelFixture, analyze, historical_pack
from test_ai_rule_drafts import configure
from test_core import FixtureRegistry, live


@pytest.fixture
def setup(monkeypatch):
    configure(monkeypatch)
    registry = FixtureRegistry()
    app = create_app('sqlite://', registry)
    model = ModelFixture()
    app.state.ai_adapter = model
    with TestClient(app) as client:
        yield client, registry, model, app.state.database


def save(client, pack, analysis_id=None, key=None, **changes):
    return client.post('/v1/reports', headers={'Idempotency-Key': key or str(uuid4())}, json={
        'mode': 'history', 'pack_id': pack['id'], 'analysis_id': analysis_id,
        'title': '合成证据报告', 'notes': 'Fixture notes; not real source acceptance', **changes})


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def export(client, report, format='markdown', revision=None):
    response = client.post(f'/v1/reports/{report["id"]}/exports', json={'revision': revision or report['revision'], 'format': format})
    assert response.status_code == 201, response.text
    metadata = response.json()
    data = client.get(metadata['content_url'])
    assert data.status_code == 200, data.text
    assert len(data.content) == metadata['byte_count']
    assert hashlib.sha256(data.content).hexdigest() == metadata['sha256'] == data.headers['X-Report-SHA256']
    assert data.headers['Cache-Control'] == 'no-store' and data.headers['X-Content-Type-Options'] == 'nosniff'
    assert data.headers['Content-Disposition'].startswith('attachment; filename="report-')
    return metadata, data.content


def test_report_is_historical_frozen_and_idempotent_without_external_calls(setup):
    client, registry, model, database = setup
    pack = historical_pack(client)
    analysis = analyze(client, pack).json()
    calls = (len(registry.calls), len(model.calls))
    baseline = (count(database, Snapshot), count(database, FactVersion), count(database, AIRequest))
    key = str(uuid4())
    response = save(client, pack, analysis['id'], key)
    assert response.status_code == 201, response.text
    report = response.json()
    assert report['data_state'] == report['body']['data_state'] == 'local_snapshot'
    assert report['body']['source_pack']['fingerprint'] == pack['fingerprint']
    assert report['body']['facts'] == pack['facts']
    assert report['body']['analysis']['claims'] == analysis['answer']['claims']
    assert report['body']['analysis']['model'] == analysis['model']
    assert save(client, pack, analysis['id'], key).json() == report
    assert save(client, pack, analysis['id'], key, title='different').status_code == 409
    assert count(database, ResearchReport) == 1
    assert calls == (len(registry.calls), len(model.calls))
    assert baseline == (count(database, Snapshot), count(database, FactVersion), count(database, AIRequest))
    assert client.get('/v1/reports').status_code == 422
    assert save(client, pack, mode='current').status_code == 422
    assert save(client, pack, body={'claims': ['invented']}).status_code == 422


def test_private_ownership_covers_pack_analysis_report_metadata_and_exports(setup):
    client, _, _, database = setup
    pack = historical_pack(client)
    analysis = analyze(client, pack).json()
    report = save(client, pack, analysis['id']).json()
    assert report['privacy_class'] == 'private'
    other = TestClient(client.app)
    assert save(other, pack).status_code == 404
    assert other.get('/v1/reports?mode=history').json()['items'] == []
    assert other.get(f'/v1/reports/{report["id"]}?mode=history').status_code == 404
    assert other.put(f'/v1/reports/{report["id"]}', json={'expected_revision': 1, 'title': 'attack', 'notes': ''}).status_code == 404
    assert other.post(f'/v1/reports/{report["id"]}/state', json={'expected_revision': 1, 'action': 'archive'}).status_code == 404
    assert other.post(f'/v1/reports/{report["id"]}/exports', json={'revision': 1, 'format': 'markdown'}).status_code == 404
    assert other.get(f'/v1/reports/{report["id"]}/exports/fake/content?mode=history&revision=1').status_code == 404


def test_same_user_second_session_reads_and_archives_report(setup):
    """圆桌 R2-1：详情/写/导出跟随用户 scope——同用户另一浏览器会话不再"看得到打不开"。"""
    from admin_support import ADMIN_PASSWORD, register_admin
    client, _, _, database = setup
    register_admin(client, username='alice')
    pack = historical_pack(client)
    analysis = analyze(client, pack).json()
    report = save(client, pack, analysis['id']).json()
    second = TestClient(client.app)
    assert second.post('/v1/auth/login', json={'username': 'alice', 'password': ADMIN_PASSWORD}).status_code == 200
    detail = second.get(f'/v1/reports/{report["id"]}?mode=history')
    assert detail.status_code == 200 and detail.json()['id'] == report['id']
    assert second.post(f'/v1/reports/{report["id"]}/state',
                       json={'expected_revision': 1, 'action': 'archive'}).status_code == 200
    exported = second.post(f'/v1/reports/{report["id"]}/exports', json={'revision': 1, 'format': 'markdown'})
    assert exported.status_code == 201, exported.text


def test_expired_pack_allowed_and_fact_text_rebuilt_from_bound_values(setup):
    client, _, _, database = setup
    pack = historical_pack(client)
    with database.sessions() as db:
        original = db.get(AIEvidencePack, pack['id'])
        payload = deepcopy(original.payload)
        payload['facts'][0]['text'] = 'forged presentation text'
        expired = AIEvidencePack(actor_session_id=original.actor_session_id, mode=original.mode,
            data_state=original.data_state, privacy_class=original.privacy_class, payload=payload,
            fingerprint=digest(payload), expires_at=utcnow() - timedelta(minutes=1))
        db.add(expired)
        db.commit()
        expired_id = expired.id
    response = save(client, {'id': expired_id})
    assert response.status_code == 201, response.text
    assert response.json()['body']['facts'][0]['text'] == pack['facts'][0]['text']
    assert response.json()['body']['source_pack']['expires_at'] < response.json()['created_at']


@pytest.mark.parametrize('failure', ['hash', 'orphan_fact', 'duplicate_fact', 'rule_draft'])
def test_untrusted_or_malformed_pack_cannot_be_saved(setup, failure):
    client, _, _, database = setup
    pack = historical_pack(client)
    with database.sessions() as db:
        original = db.get(AIEvidencePack, pack['id'])
        payload = deepcopy(original.payload)
        if failure == 'orphan_fact': payload['facts'][0]['evidence_id'] = 'not-found'
        if failure == 'duplicate_fact': payload['facts'].append(deepcopy(payload['facts'][0]))
        if failure == 'rule_draft': payload['purpose'] = 'rule_draft'
        malformed = AIEvidencePack(actor_session_id=original.actor_session_id, mode='history', data_state='local_snapshot',
            privacy_class='private', payload=payload, fingerprint='wrong' if failure == 'hash' else digest(payload),
            expires_at=utcnow() + timedelta(minutes=10))
        db.add(malformed)
        db.commit()
        pack_id = malformed.id
    response = save(client, {'id': pack_id})
    assert response.status_code == (422 if failure == 'rule_draft' else 409), response.text
    assert count(database, ResearchReport) == 0


def test_report_artifact_is_private_even_when_source_pack_is_public(setup):
    from test_knowledge import Sources
    client, _, _, _ = setup
    client.app.state.registry = Sources()
    pack = historical_pack(client)
    assert pack['privacy_class'] == 'public'
    report = save(client, pack, notes='Private research notes').json()
    assert report['privacy_class'] == report['body']['privacy_class'] == 'private'
    assert report['body']['source_pack']['privacy_class'] == 'public'


@pytest.mark.parametrize('failure', ['pending', 'wrong_pack', 'wrong_owner', 'unknown_fact', 'wrong_evidence', 'rule_draft'])
def test_report_rejects_uncompleted_unbound_or_forged_analysis(setup, failure):
    client, _, _, database = setup
    pack = historical_pack(client)
    other_pack = historical_pack(client)
    with database.sessions() as db:
        original = db.get(AIEvidencePack, pack['id'])
        row = AIRequest(actor_session_id='other-owner' if failure == 'wrong_owner' else original.actor_session_id,
            idempotency_key=str(uuid4()), request_hash=digest(failure), pack_id=other_pack['id'] if failure == 'wrong_pack' else pack['id'],
            question='Synthetic question', provider='synthetic', model='synthetic', reserved_tokens=100,
            request_contract={'purpose': 'rule_draft' if failure == 'rule_draft' else 'analysis'})
        db.add(row)
        db.flush()
        if failure != 'pending':
            answer = {'claims': [{'type': 'fact', 'text': 'untrusted stored text',
                'fact_ids': ['not-real' if failure == 'unknown_fact' else pack['facts'][0]['id']],
                'evidence_ids': ['not-real' if failure == 'wrong_evidence' else pack['facts'][0]['evidence_id']]}], 'uncertainty': ''}
            db.add(AICompletion(request_id=row.id, state='completed', answer=answer))
        db.commit()
        analysis_id = row.id
    response = save(client, pack, analysis_id)
    assert response.status_code == (404 if failure == 'wrong_owner' else 409), response.text
    assert count(database, ResearchReport) == 0


def test_withdrawal_blocks_new_save_but_keeps_existing_history(setup):
    from test_lifecycle import request_for
    client, _, _, _ = setup
    pack = historical_pack(client)
    report = save(client, pack).json()
    source = live(client).json()
    assert client.post(f'/v1/tire-variants/{source["variants"][0]["id"]}/lifecycle-events', json=request_for(source)).status_code == 201
    assert save(client, pack).status_code == 409
    existing = client.get(f'/v1/reports/{report["id"]}?mode=history').json()
    assert existing['body'] == report['body'] and existing['body_hash'] == report['body_hash']
    assert existing['current_lifecycle'][0]['state'] == 'revoked'


def test_metadata_append_only_and_archive_restore_preserve_body(setup):
    client, _, _, database = setup
    report = save(client, historical_pack(client)).json()
    path = '/v1/reports/' + report['id']
    edited = client.put(path, json={'expected_revision': 1, 'title': '更新标题', 'notes': '备注变化'}).json()
    assert edited['revision'] == 2 and edited['body_hash'] == report['body_hash'] and edited['body'] == report['body']
    assert client.put(path, json={'expected_revision': 1, 'title': 'stale', 'notes': ''}).status_code == 409
    archived = client.post(path + '/state', json={'expected_revision': 2, 'action': 'archive'}).json()
    assert archived['revision'] == 3 and archived['archived']
    assert client.get('/v1/reports?mode=history').json()['total'] == 0
    assert client.get('/v1/reports?mode=history&archived=true').json()['total'] == 1
    restored = client.post(path + '/state', json={'expected_revision': 3, 'action': 'restore'}).json()
    assert restored['revision'] == 4 and not restored['archived'] and restored['body'] == report['body']
    with database.sessions() as db:
        saved = db.get(ResearchReport, report['id'])
        saved.body = {}
        with pytest.raises(ValueError, match='只能追加'): db.commit()


def test_export_formats_revision_binding_and_no_original_evidence_or_knowledge_promotion(setup):
    client, registry, model, database = setup
    pack = historical_pack(client)
    analysis = analyze(client, pack).json()
    report = save(client, pack, analysis['id'], title='<script>window.reportCanary=1</script>', notes='[unsafe](javascript:alert(1))').json()
    baseline = (len(registry.calls), len(model.calls), count(database, EvidenceObject), count(database, EvidenceDocument))
    for format in ('markdown', 'html', 'pdf'):
        metadata, data = export(client, report, format)
        assert export(client, report, format)[0] == metadata
        if format == 'pdf': assert data.startswith(b'%PDF-')
        if format == 'html':
            class Links(HTMLParser):
                hrefs = []
                def handle_starttag(self, tag, attrs):
                    if tag == 'a': self.hrefs.extend(value for key, value in attrs if key == 'href')
            links = Links()
            links.feed(data.decode('utf-8'))
            assert b'<script>window.reportCanary' not in data
            assert not any(value.lower().startswith('javascript:') for value in links.hrefs)
        other = TestClient(client.app)
        assert other.get(metadata['content_url']).status_code == 404
        assert client.get(metadata['content_url'].replace('revision=1', 'revision=2')).status_code == 404
    assert count(database, ReportExport) == 3
    assert baseline == (len(registry.calls), len(model.calls), count(database, EvidenceObject), count(database, EvidenceDocument))
    items = client.post('/v1/knowledge/search', json={'mode': 'history', 'text': 'reportCanary'}).json()
    assert items['total'] == 0
    updated = client.put('/v1/reports/' + report['id'], json={'expected_revision': 1, 'title': '新标题', 'notes': ''}).json()
    old, old_bytes = export(client, updated, 'markdown', revision=1)
    new, new_bytes = export(client, updated, 'markdown', revision=2)
    assert old['sha256'] != new['sha256'] and old_bytes != new_bytes


def test_export_corrupt_object_fails_closed_without_touching_frozen_report(setup):
    client, _, _, database = setup
    report = save(client, historical_pack(client)).json()
    metadata, _ = export(client, report)
    database.object_store.path(metadata['sha256']).write_bytes(b'corrupt synthetic object')
    response = client.get(metadata['content_url'])
    assert response.status_code == 503 and b'corrupt synthetic object' not in response.content
    assert client.get(f'/v1/reports/{report["id"]}?mode=history').json()['body_hash'] == report['body_hash']


def test_export_storage_failure_creates_no_receipt_and_never_echoes_diagnostics(setup, monkeypatch):
    from tire_api.object_store import ObjectStoreError
    client, _, _, database = setup
    report = save(client, historical_pack(client)).json()
    def fail(_data): raise ObjectStoreError('synthetic-secret-diagnostic')
    monkeypatch.setattr(database.object_store, 'put', fail)
    response = client.post(f'/v1/reports/{report["id"]}/exports', json={'revision': 1, 'format': 'markdown'})
    assert response.status_code == 503 and 'synthetic-secret' not in response.text
    assert count(database, ReportExport) == 0


def verify_report_persistence(url):
    with pytest.MonkeyPatch.context() as monkeypatch:
        configure(monkeypatch)
        registry = FixtureRegistry()
        app = create_app(url, registry)
        model = ModelFixture()
        app.state.ai_adapter = model
        with TestClient(app) as client:
            pack = historical_pack(client)
            analysis = analyze(client, pack).json()
            key, barrier = str(uuid4()), Barrier(2)
            def create(_):
                barrier.wait(timeout=10)
                return save(client, pack, analysis['id'], key)
            with ThreadPoolExecutor(max_workers=2) as pool:
                values = list(pool.map(create, range(2)))
            assert all(value.status_code == 201 for value in values), [value.text for value in values]
            assert values[0].json()['id'] == values[1].json()['id']
            report = values[0].json()
            exports = []
            for format in ('markdown', 'html', 'pdf'):
                item, _ = export(client, report, format)
                exports.append(item)
            edit_gate = Barrier(2)
            def edit(index):
                edit_gate.wait(timeout=10)
                return client.put('/v1/reports/' + report['id'], json={'expected_revision': 1,
                    'title': '历史报告修订二 ' + str(index), 'notes': 'metadata only'})
            with ThreadPoolExecutor(max_workers=2) as pool:
                edits = list(pool.map(edit, range(2)))
            assert sorted(value.status_code for value in edits) == [200, 409]
            updated = next(value.json() for value in edits if value.status_code == 200)
            assert updated['revision'] == 2 and updated['body_hash'] == report['body_hash']
            item, _ = export(client, updated, 'markdown')
            exports.append(item)
            checkpoint = {'session_id': client.cookies.get('tire_local_session'), 'report_id': report['id'],
                          'body_hash': report['body_hash'], 'exports': exports}
        assert_report_checkpoint(url, checkpoint)
        return checkpoint


def assert_report_checkpoint(url, checkpoint):
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        client.cookies.set('tire_local_session', checkpoint['session_id'])
        report = client.get(f'/v1/reports/{checkpoint["report_id"]}?mode=history').json()
        assert report['body_hash'] == checkpoint['body_hash'] and report['revision'] == 2
        for metadata in checkpoint['exports']:
            response = client.get(metadata['content_url'])
            assert response.status_code == 200, response.text
            assert len(response.content) == metadata['byte_count']
            assert hashlib.sha256(response.content).hexdigest() == metadata['sha256'] == response.headers['X-Report-SHA256']


def test_report_file_database_create_export_and_restart(tmp_path):
    verify_report_persistence('sqlite:///' + (tmp_path / 'reports.db').as_posix())
