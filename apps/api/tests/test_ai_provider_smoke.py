"""Synthetic receipt checks for the optional real-provider smoke entry point."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

import ai_real_provider_smoke as smoke
from tire_api.ai_analysis import grounded_answer
from tire_api.ai_gateway import GatewayError, OpenAIConfig


ANSWER = {'claims': [{'type': 'fact', 'text': '', 'fact_ids': ['fact-load-1'],
    'evidence_ids': ['ev-1']}], 'uncertainty': 'Project-authored smoke fixture only.'}
USAGE = {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}


def receipt(**changes):
    return {'text': json.dumps(ANSWER), 'usage': deepcopy(USAGE), 'error': None,
        'provider_response_id': 'synthetic-provider-response', **changes}


def test_fixture_supports_production_grounding_and_fact_rendering():
    pack = SimpleNamespace(payload=deepcopy(smoke.EVIDENCE), data_state='local_snapshot')
    grounded = grounded_answer(receipt()['text'], pack)
    assert grounded['claims'][0]['text'] == smoke.EVIDENCE['facts'][0]['text']
    assert grounded['claims'][0]['text']
    assert grounded['source_state'] == 'snapshot'


def test_valid_contract_preserves_return_shape(capsys):
    assert smoke.check_contract(receipt(), 'generate') == ANSWER
    assert 'PASS generate' in capsys.readouterr().out


@pytest.mark.parametrize('mutation', ['unknown_fact', 'unknown_evidence', 'duplicate_fact',
    'duplicate_evidence', 'freeform_fact', 'empty_answer', 'unknown_key', 'malformed_json', 'non_object'])
def test_grounding_failures_are_rejected_without_raw_output(mutation, capsys):
    answer = deepcopy(ANSWER)
    claim = answer['claims'][0]
    if mutation == 'unknown_fact':
        claim['fact_ids'] = ['PRIVATE_UNKNOWN_FACT']
    elif mutation == 'unknown_evidence':
        claim['evidence_ids'] = ['PRIVATE_UNKNOWN_EVIDENCE']
    elif mutation == 'duplicate_fact':
        claim['fact_ids'] *= 2
    elif mutation == 'duplicate_evidence':
        claim['evidence_ids'] *= 2
    elif mutation == 'freeform_fact':
        claim['text'] = 'PRIVATE_MODEL_CANARY'
    elif mutation == 'empty_answer':
        answer = {'claims': [], 'uncertainty': ''}
    elif mutation == 'unknown_key':
        answer['PRIVATE_MODEL_CANARY'] = 'forbidden'
    text = '{PRIVATE_MODEL_CANARY' if mutation == 'malformed_json' else json.dumps(
        ['PRIVATE_MODEL_CANARY'] if mutation == 'non_object' else answer)
    with pytest.raises(ValueError, match='ai_grounding_validation_failed') as error:
        smoke.check_contract(receipt(text=text), 'generate')
    assert 'PRIVATE_' not in str(error.value) + capsys.readouterr().out


@pytest.mark.parametrize('answer', [
    {'claims': [], 'uncertainty': 'Fixture facts were not answered.'},
    {'claims': [{'type': 'inference', 'text': 'Synthetic inference only.',
        'fact_ids': ['fact-load-1'], 'evidence_ids': ['ev-1']}], 'uncertainty': ''}])
def test_known_fixture_requires_a_grounded_fact(answer):
    with pytest.raises(ValueError, match='smoke_fact_required'):
        smoke.check_contract(receipt(text=json.dumps(answer)), 'generate')


@pytest.mark.parametrize('usage', [None, {}, [], {**USAGE, 'input_tokens': True},
    {**USAGE, 'input_tokens': -1}, {**USAGE, 'output_tokens': '5'},
    {**USAGE, 'total_tokens': 99}, {**USAGE, 'total_tokens': 100000001}])
def test_missing_or_invalid_usage_is_rejected(usage):
    with pytest.raises(ValueError, match='ai_usage_missing_or_invalid'):
        smoke.check_contract(receipt(usage=usage), 'generate')


def test_provider_error_is_sanitized(capsys):
    with pytest.raises(ValueError, match='ai_provider_failed') as error:
        smoke.check_contract(receipt(error='PRIVATE_PROVIDER_FAILURE'), 'generate')
    assert 'PRIVATE_' not in str(error.value) + capsys.readouterr().out


class Adapter:
    def __init__(self, *, invalid_first=False, mismatched_stream=False):
        self.calls = []
        self.invalid_first = invalid_first
        self.mismatched_stream = mismatched_stream

    async def generate(self, config, body):
        self.calls.append(('generate', config, body))
        answer = deepcopy(ANSWER)
        if self.invalid_first:
            answer['claims'][0]['fact_ids'] = ['unknown-fact']
        return receipt(text=json.dumps(answer))

    async def stream(self, config, body, on_text):
        self.calls.append(('stream', config, body))
        result = receipt()
        text = 'mismatched stream' if self.mismatched_stream else result['text']
        await on_text(text[:10])
        await on_text(text[10:])
        return result


def configure(monkeypatch, adapter):
    config = OpenAIConfig(model='synthetic-responses-smoke', api_key='synthetic-never-live')
    monkeypatch.setattr(smoke, 'configured_model', lambda: config)
    monkeypatch.setattr(smoke, 'configured_adapter', lambda: adapter)


def test_main_uses_responses_envelopes_for_both_calls(monkeypatch):
    adapter = Adapter()
    configure(monkeypatch, adapter)
    assert asyncio.run(smoke.main()) == 0
    assert [call[0] for call in adapter.calls] == ['generate', 'stream']
    for _operation, config, body in adapter.calls:
        assert config.provider == 'openai_responses'
        outbound = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
        assert outbound == smoke.EVIDENCE
        assert outbound['evidence'][0]['id'] == 'ev-1'


def test_main_stops_after_invalid_first_response(monkeypatch):
    adapter = Adapter(invalid_first=True)
    configure(monkeypatch, adapter)
    with pytest.raises(ValueError, match='ai_grounding_validation_failed'):
        asyncio.run(smoke.main())
    assert [call[0] for call in adapter.calls] == ['generate']


def test_main_rejects_mismatched_stream_text(monkeypatch):
    adapter = Adapter(mismatched_stream=True)
    configure(monkeypatch, adapter)
    with pytest.raises(ValueError, match='ai_stream_text_mismatch'):
        asyncio.run(smoke.main())


def test_configuration_failure_precedes_adapter_creation(monkeypatch):
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setattr(smoke, 'configured_adapter', lambda: pytest.fail('adapter should not be created'))
    with pytest.raises(GatewayError, match='ai_disabled'):
        asyncio.run(smoke.main())
