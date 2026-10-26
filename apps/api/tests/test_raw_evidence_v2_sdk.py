"""Reviewed synthetic SDK behavior; no app, DB, provider or network."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_raw_evidence_v2_sdk_behavior():
    node = shutil.which('node')
    if node is None:
        pytest.fail('Raw evidence SDK behavior requires the monorepo Node runtime')
    node = str(Path(node).resolve(strict=True))
    script = "await import('regression:raw-evidence-v2-sdk');"
    result = subprocess.run([
        node, '--experimental-transform-types',
        '--import', './packages/api-client/tests/device-ai/no-artifacts-hook.mjs',
        '--import', './packages/api-client/tests/device-ai/json-esm-hook.mjs',
        '--input-type=module', '-e', script,
    ], cwd=ROOT, check=False, shell=False, capture_output=True, text=True,
        encoding='utf-8', timeout=30)
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        'R93 synthetic SDK assertions completed; this is not real HTTP, UI or Native acceptance.'
    ]
