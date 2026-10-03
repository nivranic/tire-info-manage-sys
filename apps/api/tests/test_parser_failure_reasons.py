"""Synthetic Parser failures through the real registry/API; no network or children."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from tire_api import parser_bundles, parser_runtime
from tire_api.adapters import registry
from tire_api.adapters.robots import RobotsPolicy
from tire_api.adapters.transport import FetchResult, USER_AGENT
from tire_api.db import (ChangeEvent, FactVersion, QueryRun, RawCapture, RejectedObservation,
                         Snapshot, SourceQuarantine, TireVariant, Verification)
from tire_api.main import create_app
from tire_api.parser_release_models import ParserExecution


SOURCE = 'michelin-us'
QUERY = {'model': 'PSEV', 'size': '265/40R20'}
BODY = '<html><body>明确合成的 Parser 失败正文，不是官网规格。</body></html>'


class SyntheticFailureRegistry:
    """Only transport/Parser boundaries are replaced; production orchestration runs."""
    supports_parser_deployments = True

    def __init__(self, code, exception=None):
        self.code, self.exception = code, exception
        self.last_result, self.last_receipt = None, None
        self.parse_calls, self.transport_calls = 0, 0

    @staticmethod
    def sources():
        return [row for row in registry.sources() if row['id'] == SOURCE]

    async def fetch(self, *args, **kwargs):
        self.last_result = await registry.fetch(*args, **kwargs)
        return self.last_result


def configure_synthetic_parser_failure(monkeypatch, work_root, code='parser_timeout', *, exception=None):
    """Reusable private QA setup; all objects/bundles stay under the supplied root."""
    root = Path(work_root)
    adapter = SyntheticFailureRegistry(code, exception)
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(root / 'bundles'))
    monkeypatch.setenv('TI_OBJECT_STORE_BACKEND', 'filesystem')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(root / 'objects'))
    monkeypatch.setenv('TI_DISABLED_SOURCES', '')
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    monkeypatch.setattr(registry, '_states', {})

    class Transport:
        def __init__(self, *_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get(self, url, **_):
            adapter.transport_calls += 1
            return FetchResult(200, url, BODY, 'text/html', None, None)

    async def robots(*_):
        return RobotsPolicy('User-agent: *\nAllow: /', USER_AGENT)

    async def fail_parser(source_id, body, query, parser_version, parser_digest, **options):
        adapter.parse_calls += 1
        if adapter.exception is not None:
            raise adapter.exception
        manifest = options['bundle_manifest']
        descriptor = parser_bundles.bundle_descriptor(manifest, source_id)
        request = {'run_id': uuid4().hex, 'source_id': source_id, 'parser_version': parser_version,
                   'parser_digest': parser_digest, 'bundle_id': manifest['bundle_id'],
                   'execution_digest': descriptor['execution_digest'],
                   'deployment_revision': options['deployment_revision'], 'query': query}
        # A synthetic pre-spawn receipt explicitly records that no PID ever existed.
        receipt = {key: value for key, value in request.items() if key != 'query'}
        receipt.update(input_hash=parser_runtime.input_hash(request, body.encode('utf-8')),
                       pid=None, exit_code=None, reaped=False, elapsed_ms=0,
                       stdout_bytes=0, stderr_bytes=0, isolation='process_fault_isolation',
                       network_enforced=False, python_network_guard=True, limits=descriptor['limits'])
        adapter.last_receipt = deepcopy(receipt)
        raise parser_runtime.ParserRunError(adapter.code, receipt)

    def no_child(*_, **__):
        raise AssertionError('synthetic failure checks must never create a Parser child')

    monkeypatch.setattr(registry, 'SafeHttpClient', Transport)
    monkeypatch.setattr(registry, '_robots_policy', robots)
    monkeypatch.setattr(registry, 'parse_isolated', fail_parser)
    monkeypatch.setattr(parser_runtime.subprocess, 'Popen', no_child)
    return adapter


@pytest.fixture
def setup(tmp_path, monkeypatch):
    adapter = configure_synthetic_parser_failure(monkeypatch, tmp_path)
    app = create_app('sqlite:///' + (tmp_path / 'failure-reasons.db').as_posix(), adapter)
    with TestClient(app) as client:
        yield client, app.state.database, adapter


@pytest.mark.parametrize('code,expected', [
    ('parser_timeout', 'parser_timeout'),
    ('parser_cancelled', 'parser_cancelled'),
    ('parser_isolation_unavailable', 'parser_isolation_unavailable'),
    ('parser_bundle_integrity_failed', 'parser_bundle_integrity_failed'),
    ('parser_crashed', 'parser_crashed'),
    ('parser_schema_changed', 'parser_schema_changed'),
    ('private_parser_detail_do_not_expose', 'parser_failed'),
])
def test_parser_failure_reason_is_consistent_across_api_capture_and_execution(setup, code, expected):
    client, database, adapter = setup
    adapter.code = code
    response = client.post(f'/v1/sources/{SOURCE}/live-query',
                           json={'query': QUERY, 'fallback_policy': 'ask'})
    assert response.status_code == 200
    data = response.json()
    assert data['data_state'] == 'consent_required' and data['reason'] == expected
    assert not data['variants'] and data['provenance'] == []
    assert adapter.last_result['reason'] == adapter.last_result['parser_error'] == expected
    assert adapter.last_result['rejected_observation']['parser_error'] == expected
    assert adapter.last_result['parser_receipt'] == adapter.last_receipt
    assert adapter.parse_calls == adapter.transport_calls == 1

    with database.sessions() as db:
        run = db.get(QueryRun, data['query_id'])
        received = db.scalar(select(RawCapture).where(RawCapture.query_id == run.id))
        rejected = db.scalar(select(RejectedObservation).where(RejectedObservation.query_id == run.id))
        executed = db.get(ParserExecution, run.id)
        assert run.reason == rejected.reason == executed.error_code == expected
        assert rejected.stage == 'parser' and executed.state == 'failed'
        assert received.raw_body == rejected.raw_body == BODY.encode('utf-8')
        assert received.raw_hash == rejected.raw_hash == hashlib.sha256(BODY.encode('utf-8')).hexdigest()
        assert received.parser_identity == rejected.parser_identity == adapter.last_result['parser_identity']
        assert executed.receipt == adapter.last_receipt
        assert executed.receipt['pid'] is None and executed.receipt['reaped'] is False
        for model in (Snapshot, TireVariant, FactVersion, Verification, ChangeEvent, SourceQuarantine):
            assert db.scalar(select(func.count()).select_from(model)) == 0

    metadata = client.get('/v1/quarantines').json()['items'][0]
    assert metadata['kind'] == 'response_rejected' and metadata['stage'] == 'parser'
    assert metadata['reason_codes'] == [expected] and metadata['metrics'] is None
    health = next(row for row in client.get('/v1/source-health').json()['sources'] if row['source_id'] == SOURCE)
    assert health['status'] == 'degraded' and health['last_reason'] == expected
    assert health['failures'] == health['rejected_count'] == 1
    assert health['quarantined_count'] == 0
    if code != expected:
        assert code not in json.dumps(data, ensure_ascii=False)
        assert code not in json.dumps(adapter.last_result, ensure_ascii=False)


def test_schema_validation_exception_keeps_schema_classification(setup):
    client, database, adapter = setup
    adapter.exception = ValueError('synthetic parser schema validation failure')
    response = client.post(f'/v1/sources/{SOURCE}/live-query',
                           json={'query': QUERY, 'fallback_policy': 'never'})
    assert response.status_code == 200
    data = response.json()
    assert data['data_state'] == 'source_unavailable' and data['reason'] == 'parser_schema_changed'
    assert not data['variants'] and data['provenance'] == []
    with database.sessions() as db:
        rejected = db.scalar(select(RejectedObservation).where(RejectedObservation.query_id == data['query_id']))
        assert rejected.reason == 'parser_schema_changed' and rejected.stage == 'parser'
        assert db.scalar(select(func.count()).select_from(SourceQuarantine)) == 0


def test_task_cancellation_is_not_converted_into_parser_failure(setup):
    _, _, adapter = setup
    adapter.exception = asyncio.CancelledError('synthetic task cancellation')
    observed = []
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(registry.fetch(SOURCE, QUERY, on_observation=observed.append))
    assert len(observed) == adapter.parse_calls == adapter.transport_calls == 1
    assert adapter.last_result is None and adapter.last_receipt is None
    state = registry._states[registry.SPECS[SOURCE].origin]
    assert state['busy'] is False and state['failures'] == 0
