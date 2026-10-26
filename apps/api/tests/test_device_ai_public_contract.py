"""Public TS SDK/Python DTO field parity; no app, DB, provider or network."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tire_api.device_ai import DeviceAIPrepareRequest, DeviceSubmission, ProviderConsent

ROOT = Path(__file__).resolve().parents[3]


def test_public_sdk_exports_match_closed_server_dto_fields():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Cross-language public contract check requires the monorepo Node runtime')
    script = """
import {
  DEVICE_AI_WIRE_CONTRACT,
  DEVICE_AI_PREPARE_REQUEST_FIELDS,
  DEVICE_AI_SUBMISSION_FIELDS,
  DEVICE_AI_PROVIDER_CONSENT_FIELDS,
  DEVICE_AI_PREPARE_PROJECTION_MODES,
  DeviceAiHostClient,
} from '@tire/api-client';
if (typeof DeviceAiHostClient !== 'function') throw new Error('Public Host SDK is missing');
console.log(JSON.stringify({
  wire_frozen: DEVICE_AI_WIRE_CONTRACT.wire_frozen,
  prepare: [...DEVICE_AI_PREPARE_REQUEST_FIELDS].sort(),
  submission: [...DEVICE_AI_SUBMISSION_FIELDS].sort(),
  consent: [...DEVICE_AI_PROVIDER_CONSENT_FIELDS].sort(),
  modes: [...DEVICE_AI_PREPARE_PROJECTION_MODES].sort(),
}));
"""
    result = subprocess.run([
        node, '--experimental-transform-types', '--import',
        './packages/api-client/tests/device-ai/json-esm-hook.mjs',
        '--input-type=module', '-e', script,
    ], cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8', timeout=30)
    public = json.loads(result.stdout)
    assert public['wire_frozen'] is True
    assert public['prepare'] == sorted(DeviceAIPrepareRequest.model_fields)
    assert public['submission'] == sorted(DeviceSubmission.model_fields)
    assert public['consent'] == sorted(ProviderConsent.model_fields)
    mode_schema = DeviceAIPrepareRequest.model_json_schema()['properties']['projection_mode']
    assert public['modes'] == sorted(mode_schema['enum'])
