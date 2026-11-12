"""Real provider smoke: one non-stream + one stream call through the configured adapter.

Reads only environment variables (never embeds credentials) and uses the
configured TI_AI_PROVIDER adapter, defaulting to OpenAI Responses. Run from apps/api:

    ./.venv/Scripts/python.exe -B ../../scripts/ai_real_provider_smoke.py

Exit 0 = both calls returned grounded fixture facts with valid usage, and the
streamed text matched the final receipt. API consent and accounting are separate checks.
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'apps', 'api'))

from tire_api.ai_analysis import grounded_answer  # noqa: E402
from tire_api.ai_gateway import (GatewayError, configured_adapter, configured_model,  # noqa: E402
                                 request_body, safe_error, safe_usage)

QUESTION = '这条轮胎的载重指数结论是什么？请仅基于给定证据回答。'
EVIDENCE = {
    'schema': 'tire-evidence-smoke@1',
    'facts': [
        {'id': 'fact-load-1', 'type': 'load_index', 'text': '合成冒烟轮胎的载重指数为 91。', 'value': '91',
         'source': 'synthetic-smoke', 'evidence_id': 'ev-1'},
        {'id': 'fact-size-1', 'type': 'size', 'text': '合成冒烟轮胎的尺寸为 205/55R16。', 'value': '205/55R16',
         'source': 'synthetic-smoke', 'evidence_id': 'ev-1'},
    ],
    'evidence': [{'id': 'ev-1', 'title': '合成冒烟证据', 'kind': 'synthetic'}],
    'conflicts': [],
    'source_state': 'snapshot',
    'data_state': 'local_snapshot',
}


def check_contract(receipt: dict, label: str) -> dict:
    if receipt.get('error') is not None:
        raise ValueError(f'{label}: {safe_error(receipt["error"])}')
    text = receipt.get('text')
    if not isinstance(text, str) or not text:
        raise ValueError(f'{label}: ai_response_invalid')
    try:
        parsed = json.loads(text)
        answer = grounded_answer(text, SimpleNamespace(payload=EVIDENCE, data_state='local_snapshot'))
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise ValueError(f'{label}: ai_grounding_validation_failed') from None
    fact_count = sum(claim['type'] == 'fact' for claim in answer['claims'])
    if not fact_count:
        raise ValueError(f'{label}: smoke_fact_required')
    usage = safe_usage(receipt.get('usage'))
    if usage is None:
        raise ValueError(f'{label}: ai_usage_missing_or_invalid')
    print(f'PASS {label}: claims={len(parsed["claims"])} uncertainty={len(parsed["uncertainty"])}ch '
          f'grounded_facts={fact_count} usage={usage} provider_id={receipt.get("provider_response_id")}')
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
    if ''.join(streamed) != stream_receipt['text']:
        raise ValueError('stream: ai_stream_text_mismatch')
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
