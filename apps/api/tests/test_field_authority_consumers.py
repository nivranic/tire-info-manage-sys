"""Synthetic accepted evidence and local adapters; no external model or Parser."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from tire_api.ai_models import AIEvidencePack, AIRequest
from tire_api.domain import digest, stable_json
from test_ai import analyze, count, historical_pack, setup
from test_core import VARIANT, live, success


def prepare(client, *results):
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [
        {'kind': 'tire', 'snapshot_id': result['provenance'][0]['snapshot_id'],
         'variant_id': result['variants'][0]['id']} for result in results]})
    assert response.status_code == 200, response.text
    return response.json()['pack']


def sources(registry):
    original = registry.sources
    registry.sources = lambda: [{**item, 'source_class': 'manufacturer_official'
        if item['id'] == 'fixture' else 'regulatory'} for item in original()]


def accepted_pair(client, registry, *, second_treadwear=500):
    sources(registry)
    row = deepcopy(VARIANT)
    row['facts'] = {'product_code_type': 'MSPN', 'utqg_treadwear': 300, 'eu_wet_grip': 'A'}
    registry.result = success(body='maker-field-authority', variants=[row])
    maker = live(client).json()
    row['facts'] = {**row['facts'], 'utqg_treadwear': second_treadwear, 'eu_wet_grip': 'B'}
    registry.result = success(body='regulator-field-authority', variants=[row])
    regulator = live(client, source='fixture-two').json()
    assert maker['variants'][0]['id'] == regulator['variants'][0]['id']
    return maker, regulator


def fields(resolution):
    return {item['field']: item for item in resolution['fields']}


def test_knowledge_and_ai_use_same_field_policy_but_freeze_selected_scope(setup):
    client, registry, model, database = setup
    maker, regulator = accepted_pair(client, registry)
    variant_id = maker['variants'][0]['id']
    response = client.post('/v1/knowledge/search', json={'mode': 'history', 'filters': {'variant_id': variant_id}})
    assert response.status_code == 200, response.text
    items = response.json()['items']
    assert len(items) == 2
    resolutions = [item['field_resolution'] for item in items]
    assert resolutions[0] == resolutions[1]
    assert resolutions[0]['scope'] == 'accepted_heads'
    expected = fields(resolutions[0])
    assert expected['utqg_treadwear']['default_value'] == 300
    assert expected['eu_wet_grip']['default_value'] == 'B'
    pack = prepare(client, maker, regulator)
    result, = pack['field_resolutions']
    assert result['scope'] == 'selected_evidence'
    assert result['policy'] == pack['field_policy'] == resolutions[0]['policy']
    for name in ('utqg_treadwear', 'eu_wet_grip'):
        assert fields(result)[name]['default_value'] == expected[name]['default_value']
        assert fields(result)[name]['state'] == 'conflict_preferred'
        assert len(fields(result)[name]['candidates']) == 2
    assert all(fact['field_code'] for fact in pack['facts'])
    assert {item['field'] for item in pack['conflicts'] if item['scope'] == 'selected_versions'} == {
        'utqg_treadwear', 'eu_wet_grip'}
    # A later retrieval cannot silently retrofit a frozen evidence packet.
    frozen = deepcopy(pack)
    registry.result = success(body='later-field-authority', variants=[{
        **deepcopy(VARIANT), 'facts': {'product_code_type': 'MSPN', 'utqg_treadwear': 700}}])
    live(client)
    assert client.get(f'/v1/ai/evidence-packs/{pack["id"]}?mode=history').json() == frozen
    assert not model.calls and count(database, AIRequest) == 0


def test_selected_unknown_is_gap_and_never_a_false_conflict(setup):
    client, registry, _, _ = setup
    maker, regulator = accepted_pair(client, registry, second_treadwear=None)
    pack = prepare(client, maker, regulator)
    field = fields(pack['field_resolutions'][0])['utqg_treadwear']
    assert field['state'] == 'uncontested' and field['default_value'] == 300
    assert len(field['candidates']) == 2
    assert any(item['present'] and item['value'] is None for item in field['candidates'])
    assert not any(item.get('field') == 'utqg_treadwear' for item in pack['conflicts'])


def test_ai_never_uses_unselected_candidate_or_url_for_preference(setup):
    client, registry, model, _ = setup
    maker, _ = accepted_pair(client, registry, second_treadwear=987654)
    registry.result = {**registry.result, 'body': 'outside-private-url',
                       'url': 'https://fixture.example/unselected-private-url'}
    live(client, source='fixture-two')
    original = registry.sources
    registry.sources = lambda: [{**item, 'source_class': 'unclassified'}
        if item['id'] == 'fixture-two' else item for item in original()]
    pack = prepare(client, maker)
    resolution, = pack['field_resolutions']
    assert fields(resolution)['eu_wet_grip']['default_value'] == 'A'
    assert pack['privacy_class'] == 'private'
    warnings = [item for item in pack['conflicts'] if item['scope'] == 'unselected_formal_evidence']
    assert len(warnings) == 1
    assert set(warnings[0]) == {'variant_id', 'scope', 'resolution', 'notice'}
    serialized = json.dumps(pack)
    assert '987654' not in serialized and 'fixture-two' not in serialized
    assert 'unselected-private-url' not in serialized
    assert analyze(client, pack).status_code == 200
    assert '987654' not in json.dumps(model.calls[0][1]) and 'fixture-two' not in json.dumps(model.calls[0][1])
    assert 'unselected-private-url' not in json.dumps(model.calls[0][1])


@pytest.mark.parametrize('change', ['missing_policy', 'changed_policy', 'missing_resolutions', 'missing_field_code'])
def test_old_or_changed_field_contract_rejected_before_request_and_model(setup, change):
    client, _, model, database = setup
    pack = historical_pack(client)
    content = deepcopy(pack)
    with database.sessions() as db:
        row = db.get(AIEvidencePack, pack['id'])
        content = deepcopy(row.payload)
        if change == 'missing_policy':
            content.pop('field_policy', None)
        elif change == 'changed_policy':
            content['field_policy'] = {'version': 'field-authority@obsolete', 'digest': '0' * 64}
        elif change == 'missing_resolutions':
            content.pop('field_resolutions', None)
            for key in ('field_resolution_format', 'field_resolution_materials', 'field_resolution_notice'):
                content.pop(key, None)
        else:
            for fact in content['facts']:
                fact.pop('field_code', None)
        # Direct SQL is a fixture for an intact historical pack, not production mutation.
        db.execute(update(AIEvidencePack).where(AIEvidencePack.id == row.id)
            .values(payload=content, fingerprint=digest(content)))
        db.commit()
    response = analyze(client, pack)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'ai_evidence_field_contract_stale'
    assert count(database, AIRequest) == 0 and not model.calls
    assert client.get(f'/v1/ai/evidence-packs/{pack["id"]}?mode=history').status_code == 200


def test_completed_analysis_replay_remains_readable_after_policy_changes(setup, monkeypatch):
    from tire_api import field_authority
    client, _, model, database = setup
    pack = historical_pack(client)
    key = str(uuid4())
    completed = analyze(client, pack, key).json()
    assert completed['state'] == 'completed'
    monkeypatch.setattr(field_authority, 'policy_descriptor', lambda: {
        'version': 'field-authority@changed', 'digest': 'f' * 64})
    assert analyze(client, pack, key).json() == completed
    read = client.get(f'/v1/ai/analyses/{completed["id"]}?mode=history')
    assert read.status_code == 200 and read.json()['pack'] == pack
    rejected = analyze(client, pack)
    assert rejected.status_code == 409, rejected.text
    assert count(database, AIRequest) == 1 and len(model.calls) == 1


def test_compact_contract_roundtrips_without_current_policy_or_value_reference_expansion(monkeypatch):
    from tire_api import field_authority
    from tire_api.ai_evidence import frozen_field_resolutions, shared_field_materials
    from test_field_authority import candidate
    value = {'context_ref': 'source text, not an instruction', 'material_ref': 'm1'}
    resolution = field_authority.resolve_fields([candidate(value)], variant_id='sku-1', scope='selected_evidence')
    frozen = [deepcopy(resolution)]
    encoded = shared_field_materials(frozen)
    before = deepcopy(encoded)
    monkeypatch.setattr(field_authority, 'policy_descriptor', lambda: pytest.fail('No current policy lookup during replay'))
    assert frozen_field_resolutions(encoded) == frozen
    assert encoded == before
    assert frozen_field_resolutions(encoded)[0]['fields'][0]['candidates'][0]['value'] == value


@pytest.mark.parametrize('mutation', ['dangling', 'cycle', 'wrong_type', 'changed_value'])
def test_invalid_frozen_material_rejected_before_request(setup, mutation):
    client, _, model, database = setup
    pack = historical_pack(client)
    with database.sessions() as db:
        stored = db.get(AIEvidencePack, pack['id'])
        payload = deepcopy(stored.payload)
        candidate = payload['field_resolutions'][0]['fields'][0]['candidates'][0]
        if mutation == 'dangling':
            candidate['context_ref'] = 'does-not-exist'
        elif mutation == 'cycle':
            payload['field_resolution_materials'][candidate['context_ref']] = {'context_ref': candidate['context_ref']}
        elif mutation == 'wrong_type':
            payload['field_resolution_materials'][candidate['context_ref']] = ['not a context']
        else:
            candidate['value'] = 'not the frozen decision'
        db.execute(update(AIEvidencePack).where(AIEvidencePack.id == stored.id)
                   .values(payload=payload, fingerprint=digest(payload)))
        db.commit()
    rejected = analyze(client, pack)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()['detail']['code'] == 'ai_evidence_field_contract_stale'
    assert count(database, AIRequest) == 0 and not model.calls


def test_two_source_pack_is_bounded_without_dropping_fields_or_candidates(setup):
    from tire_api.ai_evidence import frozen_field_resolutions
    client, registry, _, database = setup
    maker, regulator = accepted_pair(client, registry)
    pack = prepare(client, maker, regulator)
    with database.sessions() as db:
        stored = db.get(AIEvidencePack, pack['id'])
        assert stored.payload['field_resolution_format'] == 'shared-materials@1'
        assert len(stable_json(stored.payload).encode('utf-8')) <= 44000
        expanded = frozen_field_resolutions(stored.payload)
        assert expanded == pack['field_resolutions']
        assert sum(len(field['candidates']) for resolution in expanded for field in resolution['fields']) == 30


def test_hybrid_result_freezes_same_retrieval_sidecar_without_pg_or_embedding_call(setup, monkeypatch):
    from tire_api import dense
    from tire_api.knowledge import KnowledgeSearch
    from tire_api.knowledge_models import KnowledgeDocument
    client, registry, model, database = setup
    maker, _ = accepted_pair(client, registry)
    payload = {'mode': 'history', 'filters': {'variant_id': maker['variants'][0]['id']}}
    lexical = client.post('/v1/knowledge/search', json=payload).json()
    with database.sessions() as db:
        documents = list(db.scalars(select(KnowledgeDocument)))
        monkeypatch.setattr(dense, 'cosine_candidates', lambda *_args: [(item.id, 0.1) for item in documents])
        result = dense.hybrid_result(db, None, KnowledgeSearch(**payload), lexical['index'],
                                     (documents, {}, {}, {item.id for item in documents}), [1.0])
    assert len(result['items']) == 2
    assert all(item['field_resolution'] == lexical['items'][0]['field_resolution'] for item in result['items'])
    assert not model.calls


def test_shared_material_expansion_is_bounded():
    from tire_api.ai_evidence import frozen_field_resolutions
    # Small repeated references must not expand without a bounded total budget.
    payload = {'field_resolution_format': 'shared-materials@1',
        'field_resolution_materials': {'m1': {'source_name': 'x' * 39000}, 'm2': {}, 'm3': []},
        'field_resolutions': [{'fields': [{'reasons_ref': 'm3', 'candidates': [
            {'context_ref': 'm1', 'authority_ref': 'm2', 'dimensions': {}} for _ in range(60)]}]}]}
    assert len(stable_json(payload).encode()) < 44000
    with pytest.raises(ValueError, match='expansion_too_large'):
        frozen_field_resolutions(payload)


@pytest.mark.parametrize('format', ['markdown', 'html', 'pdf'])
def test_saved_report_and_exports_keep_frozen_field_decisions_when_policy_changes(setup, monkeypatch, format):
    from tire_api import field_authority
    from test_reports import export, save
    from test_report_rendering import ParsedHTML, pdf_text
    client, registry, _, _ = setup
    pack = prepare(client, *accepted_pair(client, registry))
    monkeypatch.setattr(field_authority, 'policy_descriptor', lambda: {
        'version': 'field-authority@newer', 'digest': 'f' * 64})
    response = save(client, pack)
    assert response.status_code == 201, response.text
    report = response.json()
    assert report['body']['field_resolutions'] == pack['field_resolutions']
    assert report['body']['field_policy'] == pack['field_policy']
    metadata, output = export(client, report, format)
    assert metadata['renderer_version'] == 'frozen-research-export@4'
    text = pdf_text(output) if format == 'pdf' else ''.join(ParsedHTML(output.decode()).text) if format == 'html' else output.decode().replace('\\', '')
    for marker in ('保存时字段默认值与权威依据', '默认展示：300', '默认展示：B', '冲突仍存在',
                   'fixture-two', 'utqg_treadwear', 'eu_wet_grip', '来源引用', pack['field_policy']['digest']):
        assert marker in text, (format, marker)
    assert 'field-authority@newer' not in text
    assert export(client, report, format) == (metadata, output)


def test_old_completed_pack_can_save_report_without_retrofitting_field_contract(setup):
    from test_reports import export, save
    client, _, model, database = setup
    pack = historical_pack(client)
    completed = analyze(client, pack).json()
    with database.sessions() as db:
        row = db.get(AIEvidencePack, pack['id'])
        payload = {key: value for key, value in row.payload.items() if not key.startswith('field_')}
        db.execute(update(AIEvidencePack).where(AIEvidencePack.id == row.id)
            .values(payload=payload, fingerprint=digest(payload)))
        db.commit()
    response = save(client, pack, completed['id'])
    assert response.status_code == 201, response.text
    report = response.json()
    assert 'field_resolutions' not in report['body'] and 'field_policy' not in report['body']
    _, rendered = export(client, report)
    assert '此历史报告未记录字段权威判定' in rendered.decode()
    assert len(model.calls) == 1


def test_ai_canonical_machine_fields_bind_candidates_to_exact_fact_values(setup):
    client, registry, _, _ = setup
    sources(registry)
    row = deepcopy(VARIANT)
    row['facts'] = {'product_code_type': 'MSPN', 'treadwear': 300, 'utqg_treadwear': 400}
    registry.result = success(body='legacy-alias-and-canonical', variants=[row])
    pack = prepare(client, live(client).json())
    field = fields(pack['field_resolutions'][0])['utqg_treadwear']
    assert field['state'] == 'conflict_tied' and not field['has_default']
    lookup = {fact['id']: fact for fact in pack['facts']}
    assert {item['source_field'] for item in field['candidates']} == {'treadwear', 'utqg_treadwear'}
    for candidate in field['candidates']:
        assert len(candidate['fact_ids']) == 1
        fact = lookup[candidate['fact_ids'][0]]
        assert fact['field_code'] == 'utqg_treadwear' and fact['value'] == candidate['value']


def test_knowledge_technology_authority_uses_its_own_field_locator(setup):
    from tire_api.field_authority import source_authority
    client, registry, _, _ = setup
    sources(registry)
    row = deepcopy(VARIANT)
    row['facts'] = {'product_code_type': 'MSPN', 'evidence_spans': {'acoustic_technology': '$.sku.acoustic'}}
    registry.result = success(body='acoustic-locator-only', variants=[row])
    live(client)
    result = client.post('/v1/knowledge/search', json={'mode': 'history', 'filters': {'field': 'run_flat'}}).json()
    item, = result['items']
    assert item['match']['authority_tier'] is None
    assert item['match']['authority_rule'] == source_authority(
        'run_flat', 'manufacturer_official', sku_specific=False)['rule']


def test_absent_selected_field_is_preserved_without_borrowing_another_fact_citation(setup):
    client, registry, _, _ = setup
    sources(registry)
    row = deepcopy(VARIANT)
    row['facts'] = {'product_code_type': 'MSPN', 'utqg_treadwear': 300}
    registry.result = success(body='present-field', variants=[row])
    maker = live(client).json()
    row['facts'] = {'product_code_type': 'MSPN'}
    registry.result = success(body='absent-field', variants=[row])
    regulator = live(client, source='fixture-two').json()
    pack = prepare(client, maker, regulator)
    field = fields(pack['field_resolutions'][0])['utqg_treadwear']
    missing, = [item for item in field['candidates'] if not item['present']]
    assert missing['value'] is None and missing['fact_ids'] == [] and missing['evidence_id'] == 'e2'
    assert field['state'] == 'uncontested' and field['default_value'] == 300


def test_304_of_older_query_head_never_removes_newer_same_source_content(setup):
    from test_core import QUERY
    client, registry, _, _ = setup
    sources(registry)
    row = deepcopy(VARIANT)
    row['facts'] = {'product_code_type': 'MSPN', 'utqg_treadwear': 300}
    registry.result = success(body='older-query-a', variants=[row])
    older = live(client).json()
    row['facts']['utqg_treadwear'] = 400
    registry.result = success(body='newer-query-b', variants=[row])
    newer = live(client, {'query': {'model': 'Fixture Tire'}, 'fallback_policy': 'ask'}).json()
    assert older['variants'][0]['id'] == newer['variants'][0]['id']
    registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product', 'etag': '"fixture-etag"'}
    verified = live(client, QUERY).json()
    assert verified['data_state'] == 'live_verified_304'
    response = client.post('/v1/knowledge/search', json={'mode': 'history',
        'filters': {'variant_id': older['variants'][0]['id']}})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['total'] == 2
    assert {item['reference']['snapshot_id'] for item in result['items']} == {
        older['provenance'][0]['snapshot_id'], newer['provenance'][0]['snapshot_id']}
    for item in result['items']:
        field = fields(item['field_resolution'])['utqg_treadwear']
        assert field['default_value'] == 400 and field['state'] == 'conflict_preferred'
        assert len(field['candidates']) == 2


def test_unselected_query_head_of_same_source_warns_without_leaking_its_values(setup):
    client, registry, _, _ = setup
    sources(registry)
    row = deepcopy(VARIANT)
    row['facts'] = {'product_code_type': 'MSPN', 'utqg_treadwear': 300}
    registry.result = success(body='selected-query-head', variants=[row])
    chosen = live(client).json()
    row['facts']['utqg_treadwear'] = 654987
    registry.result = success(body='unselected-query-head', variants=[row])
    other = live(client, {'query': {'model': 'Fixture Tire'}, 'fallback_policy': 'ask'}).json()
    pack = prepare(client, chosen)
    assert fields(pack['field_resolutions'][0])['utqg_treadwear']['default_value'] == 300
    assert any(item['scope'] == 'unselected_formal_evidence' for item in pack['conflicts'])
    encoded = stable_json(pack)
    assert '654987' not in encoded and other['provenance'][0]['snapshot_id'] not in encoded
