"""Local release workflow with actual children, temporary source installs and recorded HTML."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from tire_api import parser_runtime as runtime, parser_bundles as bundles
from tire_api.adapters import registry, xiaomi
from tire_api.db import FactVersion, QueryRun, RawCapture, Snapshot, Verification, uid
from tire_api.domain import LiveQueryRequest, VariantInput, digest
from tire_api.main import create_app
from tire_api.parser_release_models import (ParserBundle, ParserDeploymentRevision, ParserEvaluation,
    ParserEvaluationCompletion, ParserEvaluationReview, ParserExecution, ParserSelection)
from tire_api.parser_releases import (ParserDeploymentError, assert_selection_current, bootstrap_source,
    pin_selection, register_deployed_bundle, transition_deployment, DeploymentTransition)
from tire_api.parser_provenance import parser_identity
from tire_api.service import QueryService
from test_parser_bundles import BODY, QUERY, historical_install, mark_parser, trusted_copy
from test_golden import evaluation_reference, fixture_expected, synthetic_set

SOURCE = 'hankook-us'
SIGNED = {'operator': 'Synthetic local reviewer', 'reason': 'Recorded fixture evaluation; not production approval'}


def test_new_pirelli_bootstrap_seals_ten_sources_without_repinning_existing_nine_source_deployments(tmp_path, monkeypatch):
    source = trusted_copy(tmp_path, monkeypatch)
    catalog = runtime.source_catalog()
    historical_install(source, 9)
    app = create_app('sqlite:///' + (tmp_path / 'catalog-bootstrap.db').as_posix(), RecordedRegistry())
    with TestClient(app):
        with monkeypatch.context() as patcher:
            patcher.setattr(runtime, 'source_catalog', lambda: {key: value for key, value in catalog.items()
                                                               if key in bundles._NHTSA_SOURCES})
            with app.state.database.sessions() as db:
                old = {}
                for source_id in ('hankook-us', 'nhtsa-us-recalls'):
                    row = bootstrap_source(db, source_id)
                    old[source_id] = (row.id, row.bundle_id, row.revision, deepcopy(row.descriptor))
                old_manifest = deepcopy(db.get(ParserBundle, old['hankook-us'][1]).manifest)
        trusted_copy(tmp_path, monkeypatch)
        with app.state.database.sessions() as db:
            new = bootstrap_source(db, 'pirelli-us')
            new_id, new_bundle = new.id, new.bundle_id
            assert new.revision == 1 and new.state == 'active' and new.action == 'bootstrap'
            assert set(db.get(ParserBundle, new.bundle_id).manifest['parsers']) == set(bundles._SOURCES)
            assert new.bundle_id != old['hankook-us'][1]
            assert bootstrap_source(db, 'pirelli-us').id == new_id
            for source_id, checkpoint in old.items():
                row = bootstrap_source(db, source_id)
                assert (row.id, row.bundle_id, row.revision, row.descriptor) == checkpoint
            assert db.scalar(select(func.count()).select_from(ParserDeploymentRevision)) == 3
            assert db.get(ParserBundle, old['hankook-us'][1]).manifest == old_manifest
            assert set(old_manifest['parsers']) == set(bundles._NHTSA_SOURCES)
            assert 'adapters/pirelli.py' not in old_manifest['files']
            assert db.get(ParserBundle, new_bundle).manifest['files']['adapters/pirelli.py']['sha256']


class RecordedRegistry:
    """Transport substitute only. Selected archived Python executes in real children."""
    supports_parser_deployments = True
    sources = staticmethod(lambda: [row for row in registry.sources() if row['id'] == SOURCE])

    def __init__(self):
        self.calls, self.hook, self.invalid_receipt = [], None, False

    async def fetch(self, source_id, query, cached=None, *, on_observation, parser_selection):
        selected = deepcopy(parser_selection)
        identity = parser_identity(selected)
        self.calls.append(identity)
        observation = {'url': registry.query_url(query, source_id), 'body': BODY, 'content_type': 'text/html',
                       'parser_version': selected['parser_version'], 'parser_identity': identity}
        if self.hook:
            self.hook()
        if cached and cached.get('parser_identity') == identity:
            return {'status': 'not_modified', 'url': observation['url'], 'parser_version': selected['parser_version'],
                    'parser_identity': identity, 'etag': '"recorded"'}
        on_observation(observation)
        parsed = await runtime.parse_isolated(source_id, BODY, query, selected['parser_version'], selected['parser_digest'],
            bundle_manifest=selected['bundle_manifest'], deployment_revision=selected['deployment_revision'])
        if self.invalid_receipt:
            parsed['receipt']['input_hash'] = '0' * 64
        if self.invalid_receipt == 'missing':
            parsed['receipt'] = {}
        return {'status': 'ok', **observation, 'etag': '"recorded"', 'variants': parsed['payload'],
                'parser_receipt': parsed['receipt']}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source = trusted_copy(tmp_path, monkeypatch)
    adapter = RecordedRegistry()
    app = create_app('sqlite:///' + (tmp_path / 'releases.db').as_posix(), adapter)
    with TestClient(app) as client:
        client.get('/health')
        yield client, app.state.database, adapter, source


def live(client):
    response = client.post(f'/v1/sources/{SOURCE}/live-query', json={'query': QUERY, 'fallback_policy': 'never'})
    assert response.status_code == 200, response.text
    return response.json()


def counts(database):
    tables = (Snapshot, FactVersion, Verification, RawCapture, QueryRun, ParserSelection, ParserExecution)
    with database.sessions() as db:
        return {table.__tablename__: db.scalar(select(func.count()).select_from(table)) for table in tables}


def evaluate(client, target_id, revision=1, capture_id=None, *, expected_marker=None, golden=True):
    capture_id = capture_id or client.get('/v1/captures?mode=history').json()['items'][0]['id']
    payload = {'mode': 'history', 'source_id': SOURCE, 'target_bundle_id': target_id,
               'capture_ids': [capture_id], 'expected_deployment_revision': revision}
    if golden:
        payload.update(evaluation_reference(synthetic_set(client, [capture_id], fixture_expected(expected_marker))))
    headers = {'Idempotency-Key': str(uuid4())}
    response = client.post('/v1/parser-evaluations', json=payload, headers=headers)
    assert response.status_code == 201, response.text
    value = response.json()
    assert client.post('/v1/parser-evaluations', json=payload, headers=headers).json()['id'] == value['id']
    return value


def review(client, evaluation, **changes):
    return client.post('/v1/parser-evaluations/' + evaluation['id'] + '/reviews', json={
        'mode': 'history', 'expected_revision': evaluation['review_revision'], 'action': 'approve',
        'acknowledged': True, 'completion_fingerprint': evaluation['completion']['fingerprint'], **SIGNED, **changes})


def transition(client, action, revision, **extra):
    return client.post(f'/v1/parser-deployments/{SOURCE}/transitions', headers={'Idempotency-Key': str(uuid4())},
                       json={'action': action, 'expected_revision': revision, **SIGNED, **extra})


def import_b(database, source):
    mark_parser(source, 222)
    with database.sessions() as db:
        return register_deployed_bundle(db, **SIGNED)['id']


def test_actual_a_b_a_release_and_historical_reparse_with_unchanged_labels(setup):
    client, database, adapter, source = setup
    first = live(client)
    assert first['data_state'] == 'live'
    first_id = adapter.calls[-1]['bundle_id']
    public_source = client.get('/v1/sources').json()['sources'][0]
    assert public_source['parser_deployment']['bundle_id'] == first_id
    assert public_source['parser_deployment']['revision'] == 1
    capture_id = client.get('/v1/captures?mode=history').json()['items'][0]['id']
    # Strict matching deployment can conditionally verify without another body.
    assert live(client)['data_state'] == 'live_verified_304'
    # Bootstrap is deliberately unverified. Establish an explicit reviewed A release before testing rollback.
    first_evaluation = evaluate(client, first_id, capture_id=capture_id)
    assert review(client, first_evaluation).status_code == 201
    assert transition(client, 'activate', 1, target_bundle_id=first_id,
        evaluation_id=first_evaluation['id'], expected_review_revision=1).status_code == 201
    second_id = import_b(database, source)
    before = counts(database)
    evaluation = evaluate(client, second_id, revision=2, capture_id=capture_id, expected_marker=222)
    assert evaluation['state'] == 'completed' and evaluation['can_approve']
    assert not evaluation['completion']['reference_gaps']
    assert counts(database) == before
    assert transition(client, 'activate', 2, target_bundle_id=second_id,
        evaluation_id=evaluation['id'], expected_review_revision=1).status_code == 409
    approved = review(client, evaluation)
    assert approved.status_code == 201, approved.text
    activate = transition(client, 'activate', 2, target_bundle_id=second_id,
                          evaluation_id=evaluation['id'], expected_review_revision=1)
    assert activate.status_code == 201, activate.text
    second = live(client)
    assert second['data_state'] == 'live' and adapter.calls[-1]['deployment_revision'] == 3
    assert all(row['facts']['utqg_treadwear'] == 222 for row in second['variants'])
    # The API replays actual A while B remains current; it never changes formal facts.
    descriptors = client.get('/v1/reparse/catalog', params={'mode': 'history', 'bundle_id': first_id}).json()['parsers']
    descriptor = next(row for row in descriptors if row['source_id'] == SOURCE)
    before_reparse = counts(database)
    historical = client.post('/v1/reparse/runs', headers={'Idempotency-Key': str(uuid4())}, json={
        'mode': 'history', 'capture_id': capture_id, 'bundle_id': first_id,
        'parser_version': descriptor['parser_version'], 'parser_digest': descriptor['parser_digest']})
    assert historical.status_code == 201, historical.text
    historical = historical.json()
    assert historical['state'] == 'completed' and not historical['accepted_as_facts']
    assert historical['completion']['receipt']['bundle_id'] == first_id
    assert counts(database) == before_reparse
    assert transition(client, 'rollback', 3, target_revision=1).status_code == 409
    assert transition(client, 'rollback', 3, target_revision=2).status_code == 201
    third = live(client)
    assert third['data_state'] == 'live' and adapter.calls[-1]['deployment_revision'] == 4
    assert [row['facts'] for row in third['variants']] == [row['facts'] for row in first['variants']]
    assert adapter.calls[-1]['bundle_id'] == first_id
    execution = client.get(f"/v1/parser-executions/{third['query_id']}?mode=history").json()
    assert execution['completion']['receipt']['bundle_id'] == first_id
    assert execution['completion']['receipt']['deployment_revision'] == 4
    assert counts(database)['snapshots'] == 3
    assert counts(database)['fact_versions'] == 6
    assert counts(database)['raw_captures'] == 3
    assert counts(database)['parser_executions'] == 4


def test_inflight_a_b_a_is_rejected_by_revision_even_when_digest_returns(setup):
    client, database, adapter, source = setup
    assert live(client)['data_state'] == 'live'
    first_id = adapter.calls[-1]['bundle_id']
    first_evaluation = evaluate(client, first_id)
    assert review(client, first_evaluation).status_code == 201
    assert transition(client, 'activate', 1, target_bundle_id=first_id,
        evaluation_id=first_evaluation['id'], expected_review_revision=1).status_code == 201
    assert live(client)['data_state'] == 'live'
    second_id = import_b(database, source)
    evaluation = evaluate(client, second_id, revision=2, expected_marker=222)
    assert review(client, evaluation).status_code == 201
    before = counts(database)
    def swap():
        adapter.hook = None
        # Separate session models another local operator while fetch is in flight.
        with database.sessions() as db:
            transition_deployment(db, SOURCE, DeploymentTransition(action='activate', expected_revision=2,
                target_bundle_id=second_id, evaluation_id=evaluation['id'], expected_review_revision=1, **SIGNED),
                'concurrent-operator', str(uuid4()))
            transition_deployment(db, SOURCE, DeploymentTransition(action='rollback', expected_revision=3,
                target_revision=2, **SIGNED), 'concurrent-operator', str(uuid4()))
    adapter.hook = swap
    late = live(client)
    assert late['data_state'] == 'source_unavailable' and late['reason'] == 'parser_deployment_changed'
    after = counts(database)
    for name in ('snapshots', 'fact_versions', 'verifications'):
        assert after[name] == before[name]
    # This stale request was a conditional response; no nonexistent body is journaled.
    assert after['raw_captures'] == before['raw_captures']
    assert after['parser_executions'] == before['parser_executions'] + 1
    fresh = live(client)
    assert fresh['data_state'] == 'live'  # revision 4 cannot reuse revision 2 validators
    assert counts(database)['snapshots'] == 3 and counts(database)['fact_versions'] == 2


def test_quality_gate_and_review_revision_cannot_be_bypassed(setup):
    client, database, _, source = setup
    assert live(client)['data_state'] == 'live'
    path = source / 'adapters/hankook.py'
    with path.open('a', encoding='utf-8') as stream:
        stream.write('\n_original_parser = parse_html\ndef parse_html(body, query):\n    return _original_parser(body, query)[:1]\n')
    with database.sessions() as db:
        candidate = register_deployed_bundle(db, **SIGNED)['id']
    before = counts(database)
    evaluation = evaluate(client, candidate)
    assert any(item['code'] == 'row_loss_threshold' for item in evaluation['completion']['hard_blocks'])
    assert not evaluation['can_approve']
    assert review(client, evaluation).status_code == 409
    rejected = review(client, evaluation, action='reject')
    assert rejected.status_code == 201
    assert review(client, evaluation, action='reject').status_code == 409
    assert counts(database) == before
    assert transition(client, 'activate', 1, target_bundle_id=candidate, evaluation_id=evaluation['id'],
                      expected_review_revision=1).status_code == 409


@pytest.mark.parametrize('invalid_receipt,expected_error', [(True, 'parser_receipt_input_mismatch'),
                                                          ('missing', 'parser_receipt_invalid')])
def test_pause_damaged_package_and_reject_bad_receipt_without_facts(setup, invalid_receipt, expected_error):
    client, database, adapter, _ = setup
    adapter.invalid_receipt = invalid_receipt
    rejected = live(client)
    assert rejected['reason'] == expected_error
    assert counts(database)['snapshots'] == 0 and counts(database)['raw_captures'] == 1
    result = client.get(f"/v1/parser-executions/{rejected['query_id']}?mode=history").json()
    assert result['completion']['state'] == 'failed'
    with database.sessions() as db:
        manifest = db.get(ParserBundle, adapter.calls[0]['bundle_id']).manifest
    archived = bundles.verify_bundle(manifest)['package_root'] / 'adapters/hankook.py'
    archived.write_bytes(b'raise RuntimeError("must never run")\n')
    assert transition(client, 'pause', 1).status_code == 201
    old_calls = len(adapter.calls)
    assert live(client)['reason'] == 'parser_deployment_paused'
    assert len(adapter.calls) == old_calls  # no network action on a paused source
    assert transition(client, 'resume', 2).status_code == 503


def test_history_mode_and_no_executable_http_fields(setup):
    client, database, _, _ = setup
    assert client.get('/v1/parser-bundles').status_code == 422
    assert client.get('/v1/parser-evaluations').status_code == 422
    assert client.get(f'/v1/parser-deployments/{SOURCE}').status_code == 422
    assert client.post(f'/v1/parser-deployments/{SOURCE}/bootstrap', json={**SIGNED, 'path': 'evil.py'}).status_code == 422
    assert client.post('/v1/parser-bundles', json={'code': 'evil'}).status_code == 405
    assert counts(database)['query_runs'] == 0


def test_reference_gaps_require_explicit_acknowledgement_and_latest_review(setup):
    client, database, _, _ = setup
    from test_reparse import seed_capture
    capture_id = seed_capture(client, database, baseline=False)
    bootstrapped = client.post(f'/v1/parser-deployments/{SOURCE}/bootstrap', json=SIGNED)
    assert bootstrapped.status_code == 201
    candidate = bootstrapped.json()['bundle_id']
    evaluated = evaluate(client, candidate, capture_id=capture_id)
    assert evaluated['completion']['reference_gaps'] == [capture_id]
    assert evaluated['completion']['results'][0]['reference_kind'] == 'control_same_raw'
    assert review(client, evaluated).status_code == 422
    approved = review(client, evaluated, acknowledge_reference_gaps=True)
    assert approved.status_code == 201
    rejected = review(client, approved.json(), action='reject')
    assert rejected.status_code == 201
    assert transition(client, 'activate', 1, target_bundle_id=candidate, evaluation_id=evaluated['id'],
                      expected_review_revision=1).status_code == 409
    assert counts(database)['snapshots'] == 0


def test_vehicle_inflight_pause_keeps_raw_and_real_receipt_without_adoption(setup):
    client, database, _, _ = setup
    from test_vehicles import body
    from tire_api.vehicles import VehicleSnapshot, VehicleVerification
    raw = body()
    class VehicleAdapter:
        supports_parser_deployments = True
        candidates = staticmethod(xiaomi.candidates)
        async def fetch(self, vehicle_id, *, on_observation, parser_selection):
            selected = parser_selection
            observation = {'body': raw, 'url': xiaomi.API_URL, 'content_type': 'application/json',
                'parser_version': selected['parser_version'], 'parser_identity': parser_identity(selected)}
            on_observation(observation)
            with database.sessions() as db:
                transition_deployment(db, xiaomi.SOURCE_ID,
                    DeploymentTransition(action='pause', expected_revision=1, **SIGNED), 'concurrent-operator', str(uuid4()))
            parsed = await runtime.parse_isolated(xiaomi.SOURCE_ID, raw, {'vehicle_id': vehicle_id},
                selected['parser_version'], selected['parser_digest'], bundle_manifest=selected['bundle_manifest'],
                deployment_revision=selected['deployment_revision'])
            return {'status': 'ok', **observation, 'payload': parsed['payload'], 'parser_receipt': parsed['receipt']}
    client.app.state.vehicle_adapter = VehicleAdapter()
    result = client.post(f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments', json={'fallback_policy': 'never'}).json()
    assert result['reason'] == 'parser_deployment_changed'
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(VehicleSnapshot)) == 0
        assert db.scalar(select(func.count()).select_from(VehicleVerification)) == 0
        capture = db.scalar(select(RawCapture))
        assert capture.parser_identity['deployment_revision'] == 1
        execution = db.get(ParserExecution, result['query_id'])
        assert execution.state == 'completed' and execution.receipt['reaped']


def test_quarantine_approval_binding_changes_for_code_and_revision():
    from tire_api.quarantine_review import binding
    result = {'body': BODY, 'url': registry.query_url(QUERY, SOURCE), 'parser_version': 'same@1', 'content_type': 'text/html'}
    legacy = binding('tire', SOURCE, 'query', 'baseline', result, [], {})
    values = []
    for bundle_id, revision in [('a' * 64, 1), ('b' * 64, 2), ('a' * 64, 3)]:
        values.append(binding('tire', SOURCE, 'query', 'baseline', {**result, 'parser_identity': {
            'bundle_id': bundle_id, 'parser_digest': 'd' * 64, 'deployment_revision': revision}}, [], {}))
    assert len(set([legacy, *values])) == 4


@pytest.mark.parametrize('same_key', [False, True])
def test_concurrent_transitions_use_revision_and_idempotency_fences(setup, same_key):
    client, database, _, _ = setup
    assert client.post(f'/v1/parser-deployments/{SOURCE}/bootstrap', json=SIGNED).status_code == 201
    gate, common_key = Barrier(2), str(uuid4())
    def submit(_index):
        with database.sessions() as db:
            gate.wait(timeout=10)
            try:
                result = transition_deployment(db, SOURCE,
                    DeploymentTransition(action='pause', expected_revision=1, **SIGNED),
                    'concurrent-operator', common_key if same_key else str(uuid4()))
                return result['revision']
            except ParserDeploymentError as error:
                return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert results == [2, 2] if same_key else sorted(map(str, results)) == ['2', 'parser_deployment_revision_conflict']
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ParserDeploymentRevision)) == 2


def verify_parser_release_persistence(url, directory):
    """Shared SQLite/PostgreSQL acceptance; transport recorded, actual A/B children."""
    with pytest.MonkeyPatch.context() as patcher:
        source = trusted_copy(directory, patcher)
        adapter = RecordedRegistry()
        app = create_app(url, adapter)
        with TestClient(app) as client:
            first = live(client)
            assert first['data_state'] == 'live'
            first_id = adapter.calls[-1]['bundle_id']
            first_evaluation = evaluate(client, first_id)
            assert review(client, first_evaluation).status_code == 201
            assert transition(client, 'activate', 1, target_bundle_id=first_id,
                              evaluation_id=first_evaluation['id'], expected_review_revision=1).status_code == 201
            second_id = import_b(app.state.database, source)
            evaluation = evaluate(client, second_id, revision=2, expected_marker=222)
            assert review(client, evaluation).status_code == 201
            assert transition(client, 'activate', 2, target_bundle_id=second_id,
                              evaluation_id=evaluation['id'], expected_review_revision=1).status_code == 201
            second = live(client)
            assert second['data_state'] == 'live' and all(row['facts']['utqg_treadwear'] == 222 for row in second['variants'])
            assert transition(client, 'rollback', 3, target_revision=2).status_code == 201
            third = live(client)
            assert third['data_state'] == 'live'
            assert [row['facts'] for row in first['variants']] == [row['facts'] for row in third['variants']]
            checkpoint = {'bundle_ids': [first_id, second_id], 'source_id': SOURCE, 'revision': 4,
                'evaluation_id': evaluation['id'], 'fingerprint': evaluation['completion']['fingerprint'],
                'query_id': third['query_id'], 'facts': [row['facts'] for row in first['variants']],
                'bundle_root': str(directory / 'sealed')}
        assert_parser_release_checkpoint(url, checkpoint)
        return checkpoint


def assert_parser_release_checkpoint(url, checkpoint):
    app = create_app(url, RecordedRegistry())
    with TestClient(app) as client:
        current = client.get(f'/v1/parser-deployments/{SOURCE}?mode=history').json()
        assert current['revision'] == checkpoint['revision'] and current['bundle_id'] == checkpoint['bundle_ids'][0]
        evaluated = client.get('/v1/parser-evaluations/' + checkpoint['evaluation_id'] + '?mode=history').json()
        assert evaluated['completion']['fingerprint'] == checkpoint['fingerprint']
        before = counts(app.state.database)
        with app.state.database.sessions() as db:
            manifests = [deepcopy(db.get(ParserBundle, value).manifest) for value in checkpoint['bundle_ids']]
        from test_parser_bundles import execute_bundle
        replayed = [asyncio.run(execute_bundle(manifest, checkpoint['revision'])) for manifest in manifests]
        assert [row['facts'] for row in replayed[0]['payload']] == checkpoint['facts']
        assert all(row['facts']['utqg_treadwear'] == 222 for row in replayed[1]['payload'])
        assert all(row['receipt']['reaped'] for row in replayed)
        assert counts(app.state.database) == before
        execution = client.get('/v1/parser-executions/' + checkpoint['query_id'] + '?mode=history').json()
        assert execution['completion']['receipt']['bundle_id'] == checkpoint['bundle_ids'][0]
