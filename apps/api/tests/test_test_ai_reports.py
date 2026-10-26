"""R70 report boundary checks; synthetic evidence, private SQLite, offline exports."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.domain import digest, stable_json
from tire_api.report_models import ReportExport, ResearchReport, ResearchReportRevision
from tire_api.report_rendering import ReportRenderError, render_report
from tire_api.reports import document_for
from test_interest_review import private_api
from test_report_rendering import ParsedHTML, pdf_text, sample_document
from test_test_events import create as create_event


NOTICE = ('人工转录的本地测试记录，未经在线核验；参测对象尚未与精确SKU建立证据关联。'
          '本结果仅摘录所选字段，不代表车辆适配、性能推荐或跨测试排名。')
BOUNDARY = {'schema': 'test-analysis-boundary@1', 'policy_version': 'test-grounding@1',
    'mode': 'fact_selection_only', 'participant_identity': 'participant_only',
    'sku_link': 'not_established', 'verification_status': 'unverified', 'notice': NOTICE}


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import aiohttp
    monkeypatch.setattr(aiohttp, 'ClientSession',
        lambda *_a, **_k: pytest.fail('Report export attempted external source/model I/O'))


@pytest.fixture
def report_api(private_api, tmp_path_factory):
    client, app = private_api
    # Keep content-addressed leaves below Windows path limits, still inside this
    # run's unique private artifact directory. The real FileObjectStore is used.
    run_root = tmp_path_factory.getbasetemp().resolve()
    object_root = (run_root / ('s' + uuid4().hex[:8])).resolve()
    assert object_root.is_relative_to(run_root)
    app.state.database.object_store.root = object_root
    return client, app


def new_document():
    document = sample_document()
    document['schema_version'] = 'research-report@4'
    evidence = [
        {'id': 'e1', 'kind': 'manual_test_independent', 'label': '人工记录 · 合成同场测试',
         'event_id': 'synthetic-test-event', 'revision': 1, 'verified_at': None,
         'verification_status': 'unverified'},
        {'id': 'e2', 'kind': 'manufacturer_official', 'label': '合成精确SKU', 'variant_id': 'synthetic-sku'}]
    facts = []
    for key, participant, metric, value in [('f1', 'a', 'wet', '38.00'), ('f2', 'a', 'noise', '70'),
                                              ('f3', 'b', 'wet', '40.0')]:
        raw = {'participant_key': participant, '参测胎': {'key': participant, 'brand': 'Synthetic', 'model': 'Tire'},
               'metric_key': metric, 'raw_value': value, 'source_rank': 3 if participant == 'a' else 5}
        field = '本场成绩 ' + str(len(facts) + 1)
        facts.append({'id': key, 'evidence_id': 'e1', 'field': field, 'value': raw,
                      'field_code': 'manual_test_independent.field_' + str(len(facts) + 1),
                      'text': evidence[0]['label'] + '：' + field + ' = ' + stable_json(raw)})
    facts.append({'id': 'f4', 'evidence_id': 'e2', 'field': '尺寸', 'value': '245/40R20',
                  'text': evidence[1]['label'] + '：尺寸 = 245/40R20'})
    body = document['body']
    body.update(schema_version='research-report@4', test_boundary=deepcopy(BOUNDARY),
                evidence=evidence, facts=facts, conflicts=[])
    body['analysis']['claims'] = [
        {'type': 'fact', 'text': facts[0]['text'] + '\n' + facts[1]['text'],
         'fact_ids': ['f1', 'f2'], 'evidence_ids': ['e1']},
        {'type': 'fact', 'text': facts[3]['text'], 'fact_ids': ['f4'], 'evidence_ids': ['e2']}]
    body['analysis']['uncertainty'] = ''
    return document


def legacy_document(version):
    document = sample_document()
    document['schema_version'] = 'research-report@' + str(version)
    document['body']['evidence'][1].update(kind='manual_test_independent', event_id='synthetic-old-event', revision=1)
    return document


def rendered_text(data, format):
    return pdf_text(data) if format == 'pdf' else ''.join(ParsedHTML(data.decode()).text) if format == 'html' else data.decode().replace('\\', '')


@pytest.mark.parametrize('format', ['markdown', 'html', 'pdf'])
def test_new_test_report_exports_fixed_boundary_and_original_values_in_all_formats(format):
    document = new_document()
    before = deepcopy(document)
    data = render_report(document, format)
    content = rendered_text(data, format)
    assert NOTICE in ''.join(content.split())
    for value in ('participant_only', 'not_established', 'unverified', 'fact_selection_only',
                  'test-grounding@1', '38.00', '40.0', 'frozen-research-export@5'):
        assert value in content, (format, value)
    assert document == before


@pytest.mark.parametrize('version', [1, 2, 3])
@pytest.mark.parametrize('format,expected', [
    ('markdown', '25193d5e3b8325d0a4ddd23505efb7ca1a0d08f89e77710a11cf0d67d86d6ba2'),
    ('html', 'ae3d64e2d28fac7912ca6e5ebe9fe28f52ddfcd8cc9b3bc0b4cfb364819f6618'),
    ('pdf', '96b99637047a833ed245c8cb5266aefd88eb699b293b321726e67d17d099e749'),
])
def test_legacy_test_reports_keep_exact_export_bytes_and_no_new_boundary(version, format, expected):
    document = legacy_document(version)
    before = deepcopy(document)
    assert hashlib.sha256(render_report(document, format)).hexdigest() == expected
    assert document == before and 'test_boundary' not in document['body']


@pytest.mark.parametrize('mutation', [
    'missing_boundary', 'forged_boundary', 'boundary_extra', 'inference', 'sku_inference', 'uncertainty',
    'two_participants', 'test_plus_sku', 'two_events', 'fact_text', 'raw_value', 'downgrade', 'no_test',
])
def test_new_test_report_export_rejects_damaged_boundary_facts_or_claim_scope(mutation):
    document = new_document()
    body = document['body']
    claim = body['analysis']['claims'][0]
    if mutation == 'missing_boundary':
        del body['test_boundary']
    elif mutation == 'forged_boundary':
        body['test_boundary']['sku_link'] = 'verified'
    elif mutation == 'boundary_extra':
        body['test_boundary']['source_verified'] = True
    elif mutation in ('inference', 'sku_inference'):
        claim.update(type='inference', text='这个精确SKU湿地领先，建议安装')
        if mutation == 'sku_inference':
            claim.update(fact_ids=['f4'], evidence_ids=['e2'])
    elif mutation == 'uncertainty':
        body['analysis']['uncertainty'] = '这个精确SKU湿地领先，建议安装'
    elif mutation in ('two_participants', 'test_plus_sku', 'two_events'):
        second = body['facts'][2 if mutation != 'test_plus_sku' else 3]
        if mutation == 'two_events':
            body['evidence'].append({**deepcopy(body['evidence'][0]), 'id': 'e3', 'event_id': 'another-event'})
            second['evidence_id'] = 'e3'
        claim['fact_ids'] = ['f1', second['id']]
        claim['evidence_ids'] = ['e1'] if mutation == 'two_participants' else ['e1', second['evidence_id']]
        claim['text'] = body['facts'][0]['text'] + '\n' + second['text']
    elif mutation == 'fact_text':
        body['analysis'] = None
        body['facts'][0]['text'] = '合成SKU已确认为最佳轮胎'
    elif mutation == 'raw_value':
        body['analysis'] = None
        body['facts'][0]['value']['raw_value'] = '1.00'
    elif mutation == 'downgrade':
        document['schema_version'] = 'research-report@3'
    else:
        body['evidence'][0].pop('event_id')
        body['evidence'][0]['kind'] = 'manufacturer_official'
        for fact in body['facts']:
            fact.pop('field_code', None)
    for format in ('markdown', 'html', 'pdf'):
        with pytest.raises(ReportRenderError):
            render_report(document, format)


def prepare_test_pack(client):
    event = create_event(client)
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [
        {'kind': 'test_event', 'event_id': event['id'], 'event_revision': event['revision']}]})
    assert response.status_code == 200, response.text
    return response.json()['pack']


def save_report(client, pack, analysis_id=None):
    return client.post('/v1/reports', headers={'Idempotency-Key': str(uuid4())}, json={
        'mode': 'history', 'pack_id': pack['id'], 'analysis_id': analysis_id,
        'title': 'R70 Synthetic test report', 'notes': 'No live source or model acceptance'})


def test_new_test_report_freezes_schema_and_boundary_without_an_analysis(report_api):
    client, _app = report_api
    response = save_report(client, prepare_test_pack(client))
    assert response.status_code == 201, response.text
    report = response.json()
    assert report['body']['schema_version'] == 'research-report@4'
    assert report['body']['test_boundary'] == BOUNDARY
    assert report['body']['analysis'] is None
    for format in ('markdown', 'html', 'pdf'):
        exported = client.post('/v1/reports/' + report['id'] + '/exports', json={'revision': 1, 'format': format})
        assert exported.status_code == 201, exported.text
        metadata = exported.json()
        assert metadata['renderer_version'] == 'frozen-research-export@5'
        assert client.post('/v1/reports/' + report['id'] + '/exports', json={
            'revision': 1, 'format': format}).json()['id'] == metadata['id']
        downloaded = client.get(metadata['content_url'])
        assert downloaded.status_code == 200, downloaded.text
        assert NOTICE in ''.join(rendered_text(downloaded.content, format).split())


@pytest.mark.parametrize('failure', ['inference', 'uncertainty', 'two_participants'])
def test_new_save_revalidates_legacy_completion_and_cannot_launder_unsafe_analysis(private_api, failure):
    client, app = private_api
    pack = prepare_test_pack(client)
    selected = [fact for fact in pack['facts'] if isinstance(fact['value'], dict)
                and fact['value'].get('participant_key')]
    first = selected[0]
    claim = {'type': 'fact', 'text': first['text'], 'fact_ids': [first['id']], 'evidence_ids': [first['evidence_id']]}
    uncertainty = ''
    if failure == 'inference':
        claim.update(type='inference', text='建议把这个参测胎视为精确SKU最佳选择')
    elif failure == 'uncertainty':
        uncertainty = '建议把这个参测胎视为精确SKU最佳选择'
    else:
        second = next(fact for fact in selected if fact['value']['participant_key'] != first['value']['participant_key'])
        claim['fact_ids'].append(second['id'])
        claim['text'] += '\n' + second['text']
    with app.state.database.sessions() as db:
        original = db.get(AIEvidencePack, pack['id'])
        request = AIRequest(actor_session_id=original.actor_session_id, idempotency_key=str(uuid4()),
            request_hash=digest(failure), pack_id=pack['id'], question='Synthetic legacy analysis',
            provider='synthetic-never-called', model='synthetic', reserved_tokens=0, request_contract={'purpose': 'analysis'})
        db.add(request)
        db.flush()
        db.add(AICompletion(request_id=request.id, state='completed',
                            answer={'claims': [claim], 'uncertainty': uncertainty}))
        db.commit()
        request_id = request.id
    response = save_report(client, pack, request_id)
    assert response.status_code == 409, response.text
    with app.state.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ResearchReport)) == 0


def test_report_document_schema_comes_from_frozen_body_and_never_upgrades_legacy_test_body():
    report = SimpleNamespace(id='synthetic-report', created_at='unused', body=new_document()['body'])
    revision = SimpleNamespace(title='Synthetic', notes='', revision=1)
    from datetime import datetime, timezone
    report.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert document_for(report, revision)['schema_version'] == 'research-report@4'
    report.body = legacy_document(3)['body']
    assert document_for(report, revision)['schema_version'] == 'research-report@3'
    assert 'test_boundary' not in report.body


def completed_analysis(app, pack, claims):
    with app.state.database.sessions() as db:
        original = db.get(AIEvidencePack, pack['id'])
        request = AIRequest(actor_session_id=original.actor_session_id, idempotency_key=str(uuid4()),
            request_hash=digest(claims), pack_id=pack['id'], question='Synthetic fact selection',
            provider='synthetic-never-called', model='synthetic', reserved_tokens=0,
            request_contract={'purpose': 'analysis'})
        db.add(request)
        db.flush()
        db.add(AICompletion(request_id=request.id, state='completed', answer={'claims': claims, 'uncertainty': ''}))
        db.commit()
        return request.id


def test_new_report_accepts_fact_selection_and_reconstructs_stored_presentation(report_api):
    client, app = report_api
    pack = prepare_test_pack(client)
    fact = next(fact for fact in pack['facts'] if isinstance(fact['value'], dict)
                and fact['value'].get('participant_key'))
    claims = [{'type': 'fact', 'text': 'Untrusted legacy presentation, never rendered',
               'fact_ids': [fact['id']], 'evidence_ids': [fact['evidence_id']]}]
    analysis_id = completed_analysis(app, pack, claims)
    response = save_report(client, pack, analysis_id)
    assert response.status_code == 201, response.text
    report = response.json()
    assert report['body']['analysis']['claims'][0]['text'] == fact['text']
    assert report['body']['analysis']['uncertainty'] == ''
    assert report['body']['test_boundary'] == BOUNDARY
    exported = client.post('/v1/reports/' + report['id'] + '/exports', json={'revision': 1, 'format': 'markdown'})
    assert exported.status_code == 201, exported.text
    downloaded = client.get(exported.json()['content_url'])
    assert downloaded.status_code == 200, downloaded.text
    content = rendered_text(downloaded.content, 'markdown')
    assert 'Untrusted legacy presentation' not in content
    assert 'test-grounding@1' in content


def test_new_ordinary_report_keeps_legacy_schema_and_renderer(report_api):
    from test_ai import historical_pack
    client, _app = report_api
    response = save_report(client, historical_pack(client))
    assert response.status_code == 201, response.text
    report = response.json()
    assert 'schema_version' not in report['body'] and 'test_boundary' not in report['body']
    exported = client.post('/v1/reports/' + report['id'] + '/exports', json={'revision': 1, 'format': 'markdown'})
    assert exported.status_code == 201, exported.text
    assert exported.json()['renderer_version'] == 'frozen-research-export@4'
    with _app.state.database.sessions() as db:
        stored = db.get(ResearchReport, report['id'])
        revision = db.scalar(select(ResearchReportRevision).where(ResearchReportRevision.report_id == stored.id))
        assert document_for(stored, revision)['schema_version'] == 'research-report@3'


@pytest.mark.parametrize('format', ['markdown', 'html', 'pdf'])
def test_legacy_test_cached_export_uses_existing_receipt_and_exact_object_bytes(report_api, monkeypatch, format):
    from datetime import datetime
    from tire_api import report_rendering
    client, app = report_api
    pack = prepare_test_pack(client)
    document = legacy_document(3)
    with app.state.database.sessions() as db:
        original = db.get(AIEvidencePack, pack['id'])
        report = ResearchReport(id=document['report_id'], actor_session_id=original.actor_session_id,
            idempotency_key=str(uuid4()), request_hash=digest('synthetic legacy report'), pack_id=pack['id'],
            privacy_class='private', body=document['body'], body_hash=digest(document['body']),
            created_at=datetime.fromisoformat(document['created_at']))
        db.add(report)
        db.flush()
        db.add(ResearchReportRevision(report_id=report.id, revision=1, title=document['title'],
            notes=document['notes'], archived=False, operation='create'))
        db.commit()
        report_id = report.id
    with app.state.database.sessions() as db:
        report = db.get(ResearchReport, report_id)
        revision = db.scalar(select(ResearchReportRevision).where(ResearchReportRevision.report_id == report_id))
        frozen = document_for(report, revision)
        expected = render_report(frozen, format)
        sha256 = app.state.database.object_store.put(expected)
        receipt = ReportExport(report_id=report_id, revision=1, format=format,
            renderer_version='frozen-research-export@4', document_hash=digest(frozen),
            content_type={'markdown': 'text/markdown', 'html': 'text/html', 'pdf': 'application/pdf'}[format],
            sha256=sha256, byte_count=len(expected))
        db.add(receipt)
        db.commit()
        receipt_id = receipt.id
    monkeypatch.setattr(report_rendering, 'render_report',
        lambda *_a, **_k: pytest.fail('Cached legacy report must reuse its frozen export'))
    response = client.post('/v1/reports/' + report_id + '/exports', json={'revision': 1, 'format': format})
    assert response.status_code == 201, response.text
    metadata = response.json()
    assert metadata['id'] == receipt_id and metadata['renderer_version'] == 'frozen-research-export@4'
    downloaded = client.get(metadata['content_url'])
    assert downloaded.status_code == 200 and downloaded.content == expected
    assert 'test-grounding@1' not in rendered_text(downloaded.content, format)
    with app.state.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ReportExport)) == 1


@pytest.mark.parametrize('mutation', ['blank_participant', 'inconsistent_participant'])
def test_no_analysis_export_still_rejects_invalid_participant_binding(mutation):
    document = new_document()
    document['body']['analysis'] = None
    fact = document['body']['facts'][0]
    fact['value']['participant_key'] = '' if mutation == 'blank_participant' else 'different-participant'
    fact['text'] = document['body']['evidence'][0]['label'] + '：' + fact['field'] + ' = ' + stable_json(fact['value'])
    with pytest.raises(ReportRenderError):
        render_report(document, 'markdown')


@pytest.mark.parametrize('mutation', ['blank_participant', 'inconsistent_participant'])
def test_no_analysis_save_still_rejects_invalid_participant_binding(private_api, mutation):
    client, app = private_api
    pack = prepare_test_pack(client)
    with app.state.database.sessions() as db:
        original = db.get(AIEvidencePack, pack['id'])
        payload = deepcopy(original.payload)
        fact = next(fact for fact in payload['facts'] if isinstance(fact['value'], dict)
                    and fact['value'].get('participant_key'))
        fact['value']['participant_key'] = '' if mutation == 'blank_participant' else 'different-participant'
        source = next(item for item in payload['evidence'] if item['id'] == fact['evidence_id'])
        fact['text'] = source['label'] + '：' + fact['field'] + ' = ' + stable_json(fact['value'])
        forged = AIEvidencePack(actor_session_id=original.actor_session_id, mode=original.mode,
            data_state=original.data_state, privacy_class=original.privacy_class, payload=payload,
            fingerprint=digest(payload), expires_at=original.expires_at)
        db.add(forged)
        db.commit()
        forged_id = forged.id
    response = save_report(client, {'id': forged_id})
    assert response.status_code == 409, response.text
    with app.state.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ResearchReport)) == 0


def mixed_recall_document():
    from test_recall_reports import document as recall_document
    document = new_document()
    recall = recall_document()['body']
    for evidence in recall['evidence']:
        evidence['id'] = 'r_' + evidence['id']
    for fact in recall['facts']:
        fact['id'] = 'r_' + fact['id']
        fact['evidence_id'] = 'r_' + fact['evidence_id']
    for claim in recall['analysis']['claims']:
        claim['fact_ids'] = ['r_' + key for key in claim['fact_ids']]
        claim['evidence_ids'] = ['r_' + key for key in claim['evidence_ids']]
    document['body']['evidence'].extend(recall['evidence'])
    document['body']['facts'].extend(recall['facts'])
    document['body']['analysis']['claims'].extend(recall['analysis']['claims'])
    document['body'].update({key: recall[key] for key in ('recall_policy', 'recall_boundary')})
    return document


@pytest.mark.parametrize('format', ['markdown', 'html', 'pdf'])
def test_mixed_recall_test_export_keeps_both_boundaries_and_legal_separate_facts(format):
    document = mixed_recall_document()
    before = deepcopy(document)
    text = rendered_text(render_report(document, format), format)
    assert NOTICE in ''.join(text.split())
    for marker in ('not_assessed', 'DOT/TIN', 'test-grounding@1', 'frozen-research-export@5'):
        assert marker in text
    assert document == before


@pytest.mark.parametrize('mutation', ['recall_boundary', 'recall_record', 'recall_test_claim'])
def test_mixed_recall_test_export_enforces_both_contracts(mutation):
    document = mixed_recall_document()
    body = document['body']
    if mutation == 'recall_boundary':
        body['recall_boundary']['applicability'] = 'safe'
    elif mutation == 'recall_record':
        next(fact for fact in body['facts'] if fact.get('scope') == 'record')['record_key'] = 'forged'
    else:
        claim = body['analysis']['claims'][0]
        selected = next(fact for fact in body['facts'] if fact['id'] == 'r_f1')
        claim['fact_ids'].append(selected['id'])
        claim['evidence_ids'].append(selected['evidence_id'])
        claim['text'] += '\n' + selected['text']
    with pytest.raises(ReportRenderError):
        render_report(document, 'markdown')
