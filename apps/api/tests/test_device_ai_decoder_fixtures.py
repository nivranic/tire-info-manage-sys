"""E5 统一 closed-decoder fixtures 回放（Python 服务端参考端，decoder-spec 4.3-3）。

回放 .artifacts/device-ai50/specs/decoder-fixtures-a/fixtures.json 的逐条向量：

- 文件自洽（schema/counts/by_matrix/唯一 id/expected 键集）先于回放；
- expected.py='validation_error'：pydantic ValidationError（服务端 fail-closed 422 路径）；
- expected.py=null（verdict=accept）与 expected.py='accept'（verdict=reject 但服务端为
  2.6 D1 已裁决的接收侧历史超集）：model_validate 均成功，prepare_body 消息同时锁定
  host_receipt_id 规范化为 canonical 小写（UUID 大写/无连字符拼写收敛，M6/D1）。

fixtures 由 tests/generate_device_ai_decoder_fixtures.py 生成（expected 各端错误码
从四端实现读出，不猜）。纯 DTO 校验：无 DB、无 app、无网络、无环境变更。
"""
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from tire_api.device_ai import DeviceAIPrepareRequest, ProviderConsent

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_FILE = REPO_ROOT / '.artifacts/device-ai50/specs/decoder-fixtures-a/fixtures.json'
PAYLOAD = json.loads(FIXTURE_FILE.read_text(encoding='utf-8'))
CASES = PAYLOAD['cases']
CANONICAL_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')
MODELS = {'prepare_body': DeviceAIPrepareRequest, 'provider_consent': ProviderConsent}


def test_fixture_file_schema_counts_and_internal_consistency():
    assert PAYLOAD['schema'] == 'device-ai-decoder-fixtures@1'
    counts = PAYLOAD['counts']
    assert counts['total'] == len(CASES) == len({item['id'] for item in CASES})
    assert counts['accept'] == sum(1 for item in CASES if item['verdict'] == 'accept')
    assert counts['reject'] == sum(1 for item in CASES if item['verdict'] == 'reject')
    by_matrix: dict[str, int] = {}
    for item in CASES:
        assert item['verdict'] in {'accept', 'reject'}
        assert item['message'] in MODELS
        assert set(item['expected']) == {'py', 'ts', 'rs', 'jv'}
        if item['verdict'] == 'accept':
            assert all(code is None for code in item['expected'].values()), item['id']
        else:
            assert item['expected']['py'] in {'validation_error', 'accept'}, item['id']
        by_matrix[item['matrix_ref']] = by_matrix.get(item['matrix_ref'], 0) + 1
    assert by_matrix == counts['by_matrix']


@pytest.mark.parametrize('item', CASES, ids=lambda item: item['id'])
def test_decoder_fixture_replays_on_the_python_reference(item):
    model = MODELS[item['message']]
    if item['expected']['py'] == 'validation_error':
        with pytest.raises(ValidationError):
            model.model_validate(item['payload'])
        return
    # expected.py 为 null（verdict=accept）或 'accept'（2.6 D1 接收侧历史超集）：
    # 服务端一律接受；prepare_body 消息同时钉住 UUID 的 canonical 小写规范化。
    value = model.model_validate(item['payload'])
    if item['message'] == 'prepare_body':
        assert CANONICAL_UUID.fullmatch(value.host_receipt_id), value.host_receipt_id
