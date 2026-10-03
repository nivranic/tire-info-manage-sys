"""Real provider smoke: one non-stream + one stream call through the configured adapter.

Reads only environment variables (never embeds credentials); works for every
TI_AI_PROVIDER (openai_responses / openai_chat / anthropic). Run from apps/api:

    ./.venv/Scripts/python.exe -B ../../scripts/ai_real_provider_smoke.py

Exit 0 = both calls returned contract-shaped JSON with accounted usage.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'apps', 'api'))

from tire_api.ai_gateway import GatewayError, configured_adapter, configured_model, request_body  # noqa: E402

QUESTION = '这条轮胎的载重指数结论是什么？请仅基于给定证据回答。'
EVIDENCE = {
    'schema': 'tire-evidence-smoke@1',
    'facts': [
        {'id': 'fact-load-1', 'type': 'load_index', 'text': '', 'value': '91',
         'source': 'synthetic-smoke', 'evidence_ids': ['ev-1']},
        {'id': 'fact-size-1', 'type': 'size', 'text': '', 'value': '205/55R16',
         'source': 'synthetic-smoke', 'evidence_ids': ['ev-1']},
    ],
    'evidences': [{'id': 'ev-1', 'title': '合成冒烟证据', 'kind': 'synthetic'}],
}


def check_contract(receipt: dict, label: str) -> dict:
    assert receipt.get('error') is None, f'{label}: adapter error {receipt["error"]}'
    text = receipt.get('text')
    assert isinstance(text, str) and text, f'{label}: empty text'
    parsed = json.loads(text)
    assert set(parsed) == {'claims', 'uncertainty'}, f'{label}: contract keys {set(parsed)}'
    assert isinstance(parsed['claims'], list), f'{label}: claims not a list'
    assert isinstance(parsed['uncertainty'], str), f'{label}: uncertainty not a string'
    usage = receipt.get('usage')
    assert usage is None or set(usage) == {'input_tokens', 'output_tokens', 'total_tokens'}, label
    print(f'PASS {label}: claims={len(parsed["claims"])} uncertainty={len(parsed["uncertainty"])}ch '
          f'usage={usage} provider_id={receipt.get("provider_response_id")}')
    if parsed['claims']:
        claim = parsed['claims'][0]
        print(f'     first claim: type={claim.get("type")} fact_ids={claim.get("fact_ids")} '
              f'text={str(claim.get("text"))[:60]}')
    return parsed


async def main() -> int:
    config = configured_model()
    adapter = configured_adapter()
    print(f'provider={config.provider} model={config.model} endpoint={config.endpoint}')
    results = {}
    body, reserve = request_body(config, QUESTION, EVIDENCE)
    print(f'request bytes gate ok; token reserve={reserve}')
    receipt = await adapter.generate(config, body)
    results['generate'] = check_contract(receipt, 'generate')

    streamed = []

    async def on_text(delta):
        streamed.append(delta)

    stream_body, _ = request_body(config, QUESTION, EVIDENCE, stream=True)
    stream_receipt = await adapter.stream(config, stream_body, on_text)
    results['stream'] = check_contract(stream_receipt, 'stream')
    assert ''.join(streamed) == stream_receipt['text'], 'stream deltas != final text'
    print(f'PASS stream: {len(streamed)} deltas rejoined == final text')
    print('SMOKE OK')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except GatewayError as error:
        print(f'SMOKE FAILED: gateway error {error}')
        raise SystemExit(2)
    except (AssertionError, ValueError, TypeError) as error:
        print(f'SMOKE FAILED: {error}')
        raise SystemExit(3)
