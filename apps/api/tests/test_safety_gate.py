"""Synthetic XML and normal API contracts for the official weekly source."""
import asyncio
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, text

from tire_api.adapters import safety_gate as source
from tire_api.captures import validated_observation
from tire_api.db import RawCapture, RejectedObservation
from tire_api.main import create_app
from tire_api import parser_runtime
from tire_api.safety_gate import SafetyGateSnapshot, SafetyGateVerification

QUERY = {'operation': 'report', 'report_id': '900001', 'reference': 'Report-2026-19'}
IDENTITY = {'bundle_id': 'a' * 64, 'parser_digest': 'b' * 64, 'deployment_revision': 1}


def report(count=1):
    root = ET.Element('Safety-Gate')
    for key, value in [('report_language', 'en'), ('report_date', '15/05/2026'),
                       ('report_year', '2026'), ('report_week', '19'), ('report_addendum', None)]:
        ET.SubElement(root, key).text = value
    for number in range(1, count + 1):
        row = ET.SubElement(root, 'notifications')
        fields = {key: 'Synthetic official text' for key in source.ALERT_FIELDS - {'pictures'}}
        fields.update(order=str(number), caseNumber=f'SR/{number:05d}/26', publicationDate='12-05-2026',
            reference=source.BASE + f'/screen/webReport/alertDetail/{900000 + number}',
            product='Synthetic truck tyre', brand='SYNTHETIC', name='Synthetic tyre',
            barcode=None, batchNumber=None, productionDates='Synthetic series 001 (0326)')
        for key, value in sorted(fields.items()):
            ET.SubElement(row, key).text = value
        ET.SubElement(ET.SubElement(row, 'pictures'), 'picture').text = source.BASE + '/public/api/notification/image/900001'
    return ET.tostring(root, encoding='unicode')


def index(reference='Report-2026-19', published='15/05/2026'):
    root = ET.Element('Safety-Gate')
    row = ET.SubElement(root, 'weeklyReport')
    year, week = reference.split('-')[1:]
    day, month, _ = published.split('/')
    values = {'report_language': 'en', 'reference': reference, 'publicationDate': published,
        'year': year, 'month': str(int(month)), 'day': str(int(day)), 'week': str(int(week)),
        'URL': source.query_url({**QUERY, 'reference': reference})}
    for key, value in values.items():
        ET.SubElement(row, key).text = value
    return ET.tostring(root, encoding='unicode')


@pytest.mark.parametrize('reference', ['Report-2026-9', 'Report-2026-09', 'Report-2026-019'])
def test_official_reference_padding_is_preserved(reference):
    value = source.parse_xml(index(reference), {'operation': 'reports'})
    assert value['reports'][0]['reference'] == reference


def test_publication_calendar_is_separate_from_native_report_identity():
    row = source.parse_xml(index('Report-2005-1', '20/01/2006'), {'operation': 'reports'})['reports'][0]
    assert row['reference'] == 'Report-2005-1' and row['published_date'] == '2006-01-20'
    value = source.parse_xml(report(), QUERY)
    assert value['report']['reference'] == 'Report-2026-19'
    assert datetime.fromisoformat(value['report']['published_date']).isocalendar().week == 20
    alert = value['alerts'][0]
    assert alert['published_date'] == '2026-05-12'
    assert alert['fields']['barcode'] is None and alert['applicability'] == 'not_assessed'
    assert alert['fields']['productionDates'] == 'Synthetic series 001 (0326)'


@pytest.mark.parametrize('mutation', [
    lambda body: body.replace('Safety-Gate', 'Other-Root'),
    lambda body: '<!DOCTYPE Safety-Gate [<!ENTITY e SYSTEM "file:///synthetic">]>' + body,
    lambda body: body.replace('<brand>', '<brand><unexpected />'),
    lambda body: body.replace('<order>1</order>', '<order>2</order>'),
    lambda body: body.replace('alertDetail/900001', 'alertDetail/0'),
    lambda body: body.replace('<barcode />', ''),
    lambda body: body.replace('<report_week>19</report_week>', '<report_week>20</report_week>'),
    lambda body: body.replace('notification/image/900001', 'notification/image/../900001'),
    lambda body: body.replace('</notifications>', '<newField>drift</newField></notifications>'),
    lambda body: body.replace('</notifications>', '</notifications></Safety-Gate>'),
])
def test_complete_report_rejects_identity_structure_and_entity_changes(mutation):
    with pytest.raises((ValueError, ET.ParseError)):
        source.parse_xml(mutation(report()), QUERY)


def test_official_nil_unknowns_and_duplicate_identity():
    body = report().replace('<barcode />', '<barcode xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true" />')
    assert source.parse_xml(body, QUERY)['alerts'][0]['fields']['barcode'] is None
    with pytest.raises(ValueError):
        source.parse_xml(body.replace('xsi:nil="true" />', 'xsi:nil="true">123</barcode>'), QUERY)
    body = report(2).replace('alertDetail/900002', 'alertDetail/900001')
    with pytest.raises(ValueError):
        source.parse_xml(body, QUERY)


def test_legacy_dto_negative_id_missing_pictures_and_unknown_product():
    root = ET.fromstring(report())
    row = root.find('notifications')
    row.set('{http://www.w3.org/2001/XMLSchema-instance}type', 'webReportXmlWeeklyReportDetailContentDto')
    row.find('reference').text = source.BASE + '/screen/webReport/alertDetail/-1782'
    row.find('product').text = None
    for name in ['companyRecallCode', 'productionDates', 'pictures']:
        row.remove(row.find(name))
    value = source.parse_xml(ET.tostring(root, encoding='unicode'), QUERY)['alerts'][0]
    assert value['alert_id'] == '-1782' and value['fields']['product'] is None
    assert value['fields']['productionDates'] is None and value['pictures'] == []


@pytest.mark.parametrize('query', [
    {'operation': 'reports', 'extra': '1'}, {'operation': 'report', 'report_id': '../900001', 'reference': 'Report-2026-19'},
    {'operation': 'report', 'report_id': 900001, 'reference': 'Report-2026-19'},
    {**QUERY, 'reference': 'Report-2026-54'}, {**QUERY, 'reference': 'Report-2026-0'},
])
def test_fixed_query_contract_rejects_extra_keys_and_bad_identity(query):
    with pytest.raises(ValueError):
        source.query_url(query)


def test_xml_capture_is_bound_to_exact_source_query_and_url():
    observation = {'url': source.query_url(QUERY), 'body': report(), 'content_type': 'application/xml', 'parser_version': source.PARSER_VERSION}
    assert validated_observation(observation, source_id=source.SOURCE_ID, query=QUERY)
    assert validated_observation(observation, source_id='nhtsa-us-recalls', query=QUERY) is None
    assert validated_observation({**observation, 'url': observation['url'] + '&extra=1'}, source_id=source.SOURCE_ID, query=QUERY) is None
    assert validated_observation(observation) is None


def test_isolated_catalog_executes_weekly_xml_and_preserves_legacy_packages(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    descriptor = parser_runtime.current_parser(source.SOURCE_ID)
    value = asyncio.run(parser_runtime.parse_isolated(source.SOURCE_ID, report(), QUERY,
        descriptor['parser_version'], descriptor['parser_digest']))
    assert value['payload']['alerts'][0]['case_number'] == 'SR/00001/26'
    assert descriptor['target_kind'] == 'recall'


def test_old_fourteen_entry_package_remains_executable(tmp_path, monkeypatch):
    from test_parser_bundles import execute_bundle, pre_safety_gate_install, trusted_copy
    from tire_api import parser_bundles
    installed = trusted_copy(tmp_path, monkeypatch)
    pre_safety_gate_install(installed)
    catalog = {key: value for key, value in parser_runtime.source_catalog().items() if key != source.SOURCE_ID}
    with monkeypatch.context() as patch:
        patch.setattr(parser_runtime, 'source_catalog', lambda: catalog)
        manifest = parser_bundles.seal_deployed_bundle()
    assert len(manifest['parsers']) == 14 and source.SOURCE_ID not in manifest['parsers']
    assert asyncio.run(execute_bundle(manifest))['payload']


class FixtureRegistry:
    def sources(self):
        return [source.source_metadata()]


class FixtureAdapter:
    def __init__(self):
        self.offline, self.not_modified, self.mutate = False, False, None
        self.calls = []

    async def fetch(self, query, cached=None, *, on_observation=None):
        self.calls.append(deepcopy(query))
        if self.offline:
            return {'status': 'unavailable', 'reason': 'synthetic_outage'}
        value = {'status': 'not_modified' if self.not_modified else 'ok', 'url': source.query_url(query),
            'content_type': 'application/xml', 'parser_version': source.PARSER_VERSION,
            'parser_identity': deepcopy(IDENTITY), 'etag': '"synthetic-weekly"'}
        if not self.not_modified:
            body = index() if query['operation'] == 'reports' else report()
            value.update(body=body, document=source.parse_xml(body, query))
            if on_observation:
                on_observation(value)
        if self.mutate:
            self.mutate(value)
        return value


@pytest.fixture
def context(tmp_path):
    app = create_app('sqlite:///' + (tmp_path / 'safety.db').as_posix(), FixtureRegistry())
    adapter = FixtureAdapter()
    app.state.safety_gate_adapter = adapter
    with TestClient(app) as client:
        yield client, adapter, app.state.database


def run(client, query=None, **options):
    response = client.post('/v1/safety-gate/query', json={'query': query or QUERY, **options})
    assert response.status_code == 200, response.text
    return response.json()


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_normal_api_captures_index_report_evidence_and_repeated_verification(context):
    client, adapter, database = context
    index_result = run(client, {'operation': 'reports'})
    first = run(client)
    repeated = run(client)
    assert index_result['document']['operation'] == 'reports'
    assert first['data_state'] == 'live' and first['document']['alerts'][0]['applicability'] == 'not_assessed'
    provenance = first['provenance'][0]
    assert repeated['provenance'][0]['snapshot_id'] == provenance['snapshot_id']
    assert count(database, SafetyGateSnapshot) == 2 and count(database, SafetyGateVerification) == 3
    assert count(database, RawCapture) == 3
    evidence = client.get(provenance['evidence_path'])
    assert evidence.status_code == 200
    assert sha256(evidence.json()['body'].encode()).hexdigest() == provenance['raw_hash']
    assert evidence.json()['license_basis']['license_uri'].endswith('/CC0')
    with database.sessions() as db:
        capture = db.scalar(select(RawCapture))
        assert capture.target_kind == 'recall' and capture.source_id == source.SOURCE_ID


def test_online_failure_exposes_no_history_before_single_use_consent(context):
    client, adapter, database = context
    first = run(client)
    adapter.offline = True
    failure = run(client)
    assert failure['data_state'] == 'consent_required' and failure['document'] is None and failure['provenance'] == []
    allowed = client.post('/v1/fallback-consents', json={'query_id': failure['query_id'], 'decision': 'allow', 'scope': 'once'})
    assert allowed.status_code == 201
    consent_id = allowed.json()['id']
    restored = run(client, consent_id=consent_id)
    assert restored['data_state'] == 'local_snapshot' and restored['document'] == first['document']
    replay = client.post('/v1/safety-gate/query', json={'query': QUERY, 'consent_id': consent_id})
    assert replay.status_code in {403, 409}
    assert run(client, fallback_policy='never')['data_state'] == 'source_unavailable'
    before = len(adapter.calls)
    history = client.get('/v1/safety-gate/history', params={**QUERY, 'mode': 'history'})
    assert history.status_code == 200 and history.json()['document'] == first['document']
    assert len(adapter.calls) == before
    assert count(database, SafetyGateVerification) == 1


def test_consent_cannot_cross_report_or_session(context):
    client, adapter, _ = context
    run(client)
    adapter.offline = True
    failure = run(client)
    consent = client.post('/v1/fallback-consents', json={'query_id': failure['query_id'], 'decision': 'allow', 'scope': 'once'}).json()['id']
    wrong = client.post('/v1/safety-gate/query', json={'query': {**QUERY, 'report_id': '900002'}, 'consent_id': consent})
    assert wrong.status_code == 403
    client.cookies.clear()
    foreign = client.post('/v1/safety-gate/query', json={'query': QUERY, 'consent_id': consent})
    assert foreign.status_code == 403


def test_changed_parent_payload_is_quarantined_without_snapshot_adoption(context):
    client, adapter, database = context
    def mutate(value):
        value['document']['alerts'][0]['source_url'] = 'https://invalid.example/alert'
    adapter.mutate = mutate
    result = run(client)
    assert result['data_state'] == 'consent_required' and result['document'] is None
    assert count(database, SafetyGateSnapshot) == 0 and count(database, RejectedObservation) == 1


def test_verified_304_requires_current_identity_and_saved_raw_bytes(context):
    client, adapter, database = context
    first = run(client)
    adapter.not_modified = True
    result = run(client)
    assert result['data_state'] == 'live_verified_304'
    assert result['provenance'][0]['snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert count(database, SafetyGateSnapshot) == 1 and count(database, SafetyGateVerification) == 2


def test_historical_snapshot_corruption_is_detected(context):
    client, _, database = context
    first = run(client)
    with database.engine.begin() as connection:
        connection.execute(text("UPDATE safety_gate_snapshots SET body = 'corrupt'"))
    evidence = client.get(first['provenance'][0]['evidence_path'])
    assert evidence.status_code == 503


def test_snapshot_and_verification_are_append_only(context):
    client, _, database = context
    run(client)
    with database.sessions() as db:
        row = db.scalar(select(SafetyGateSnapshot))
        row.body = 'changed'
        with pytest.raises(ValueError):
            db.flush()
        db.rollback()
        db.delete(db.scalar(select(SafetyGateVerification)))
        with pytest.raises(ValueError):
            db.flush()
