"""Synthetic test evidence must never become an unbridged SKU recommendation."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tire_api.ai_analysis import grounded_answer
from tire_api.ai_gateway import GatewayError, OpenAIConfig, analysis_contract, request_body
from tire_api.ai_stream_parser import StructuredDraftProjector


def payload():
    return {'source_state': 'snapshot', 'conflicts': [], 'evidence': [
        {'id': 'e1', 'kind': 'manual_test_independent', 'event_id': 'synthetic-test'},
        {'id': 'e2', 'kind': 'manufacturer_official', 'variant_id': 'synthetic-sku'}],
        'facts': [
            {'id': 'f1', 'evidence_id': 'e1', 'field_code': 'manual_test_independent.field_8',
             'value': {'participant_key': 'a', '参测胎': {'key': 'a'}, 'raw_value': '38.00'},
             'text': 'Synthetic event: A = 38.00 m'},
            {'id': 'f2', 'evidence_id': 'e1', 'field_code': 'manual_test_independent.field_9',
             'value': {'participant_key': 'b', '参测胎': {'key': 'b'}, 'raw_value': '40.00'},
             'text': 'Synthetic event: B = 40.00 m'},
            {'id': 'f3', 'evidence_id': 'e2', 'value': 245, 'text': 'Synthetic SKU width = 245'}]}


def claim(ids=('f1',), evidence=('e1',), *, kind='fact', text=''):
    return {'type': kind, 'text': text, 'fact_ids': list(ids), 'evidence_ids': list(evidence)}


def answer(data, claims, uncertainty=''):
    return grounded_answer(json.dumps({'claims': claims, 'uncertainty': uncertainty}),
                           SimpleNamespace(payload=data, data_state='local_snapshot'))


@pytest.mark.parametrize('ids,refs', [(('f1', 'f3'), ('e1', 'e2')), (('f1',), ('e1',)), (('f3',), ('e2',))])
def test_test_pack_blocks_sku_recommendation_even_with_valid_or_single_side_citations(ids, refs):
    with pytest.raises(ValueError):
        answer(payload(), [claim(ids, refs, kind='inference', text='推荐此SKU，实测优于其他轮胎。')])


def test_test_pack_blocks_uncertainty_recommendation_and_cross_participant_fact():
    with pytest.raises(ValueError):
        answer(payload(), [claim()], '此SKU可能最适合此车型。')
    with pytest.raises(ValueError):
        answer(payload(), [claim(('f1', 'f2'))])


@pytest.mark.parametrize('whitespace', [' ', '\n'])
def test_test_selection_rejects_raw_whitespace_instead_of_normalizing_it(whitespace):
    with pytest.raises(ValueError, match='test_freeform_not_allowed'):
        answer(payload(), [claim()], whitespace)
    with pytest.raises(ValueError, match='test_freeform_not_allowed'):
        answer(payload(), [claim(text=whitespace)])


def test_test_facts_remain_separate_and_empty_selection_has_fixed_boundary():
    result = answer(payload(), [claim(), claim(('f2',)), claim(('f3',), ('e2',))])
    assert result['claims'][0]['text'] == payload()['facts'][0]['text']
    assert result['test_boundary']['schema'] == 'test-analysis-boundary@1'
    assert result['test_boundary']['sku_link'] == 'not_established'
    assert answer(payload(), [])['test_boundary'] == result['test_boundary']


@pytest.mark.parametrize('fragment', [
    '{"uncertainty":"此SKU适合您的车型",',
    '{"claims":[' + json.dumps(claim(kind='inference', text='此SKU最优')) + ',',
    '{"claims":[' + json.dumps(claim(('f1', 'f2'))) + ',',
])
def test_invalid_test_stream_content_never_leaves_as_draft(fragment):
    projector = StructuredDraftProjector({'payload': payload(), 'data_state': 'local_snapshot'})
    with pytest.raises(GatewayError, match='ai_grounding_validation_failed'):
        projector.feed(fragment)


@pytest.mark.parametrize('provider', ['openai_responses', 'openai_chat', 'anthropic'])
def test_every_provider_receives_test_fact_selection_schema_and_bound_contract(provider):
    config = OpenAIConfig(model='synthetic-model', api_key='synthetic-never-live', provider=provider,
                          response_format='json_schema')
    body, _reserve = request_body(config, 'Synthetic question', payload(), stream=True)
    if provider == 'openai_responses':
        schema = body['text']['format']
    elif provider == 'openai_chat':
        schema = body['response_format']['json_schema']
    else:
        assert 'test_evidence_answer' not in body['system'] or 'fact' in body['system']
        assert '"enum":["fact"]' in body['system']
        schema = None
    if schema:
        assert schema['name'] == 'test_evidence_answer'
        assert schema['schema']['properties']['claims']['items']['properties']['type']['enum'] == ['fact']
    contract = analysis_contract(payload())
    assert contract['prompt_version'] == 'test-grounding@1'
    assert contract['test_boundary']['participant_identity'] == 'participant_only'


def test_plain_sku_and_device_contracts_keep_existing_inference_behavior():
    plain = payload()
    plain['evidence'] = [plain['evidence'][1]]
    plain['facts'] = [plain['facts'][2]]
    assert answer(plain, [claim(('f3',), ('e2',), kind='inference', text='Synthetic limited inference')])['claims']
    assert 'test_boundary' not in analysis_contract(plain)
    device = deepcopy(plain)
    device.update(origin='device_history')
    device['evidence'][0]['event_id'] = 'device-independent-event-id'
    assert answer(device, [claim(('f3',), ('e2',), kind='inference', text='Synthetic device inference')])['claims']
    assert 'test_boundary' not in analysis_contract(device)
