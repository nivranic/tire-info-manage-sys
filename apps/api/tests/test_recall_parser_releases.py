"""Real sealed recall A/B/A children; transport always uses recorded local JSON."""
import asyncio
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from tire_api import parser_runtime as runtime, parser_bundles as bundles
from tire_api.adapters import nhtsa
from tire_api.captures import checked_capture_bytes
from tire_api.db import QueryRun, RawCapture
from tire_api.domain import digest
from tire_api.main import create_app
from tire_api.parser_provenance import parser_identity
from tire_api.parser_release_models import ParserBundle, ParserExecution
from tire_api.parser_releases import (DeploymentTransition, register_deployed_bundle, transition_deployment,
                                    _reference_snapshot)
from tire_api.recall_models import RecallSnapshot, RecallVerification
from tire_api.recall_discovery import RecallSearchSnapshot, RecallSearchVerification
from admin_support import register_admin
from test_core import FixtureRegistry
from test_parser_bundles import historical_install, trusted_copy
from test_recall_reparse import (BODIES, QUERIES, SOURCE, formal_counts, seed_recall, create_reparse)

SIGNED = {'operator': 'Synthetic recall reviewer', 'reason': 'Recorded fixtures; local parser approval only'}
PERSIST_QUERIES = {'campaign': {'campaign_number': '26T777777'},
                   'search': {'search': 'PG RECALL PARSER', 'offset': '0'}}


def body_for(query):
    kind = 'search' if 'search' in query else 'campaign'
    value = json.loads(BODIES[kind])
    if kind == 'campaign':
        for row in value['results']:
            row['NHTSACampaignNumber'] = query['campaign_number']
    else:
        value['meta']['pagination']['currentUrl'] = nhtsa.query_url(query)
    return json.dumps(value)


class RecordedRecalls:
    supports_parser_deployments = True

    def __init__(self):
        self.calls, self.hook = [], None

    async def fetch(self, query, cached=None, *, on_observation, parser_selection):
        selected = deepcopy(parser_selection)
        identity = parser_identity(selected)
        self.calls.append({'query': deepcopy(query), **identity})
        observation = {'body': body_for(query), 'url': nhtsa.query_url(query), 'content_type': 'application/json',
            'parser_version': selected['parser_version'], 'parser_identity': identity, 'etag': '"recorded-recall"'}
        if cached and cached.get('parser_identity') == identity:
            return {key: value for key, value in observation.items() if key != 'body'} | {'status': 'not_modified'}
        on_observation(observation)
        if self.hook:
            self.hook()
        parsed = await runtime.parse_isolated(SOURCE, observation['body'], query,
            selected['parser_version'], selected['parser_digest'], bundle_manifest=selected['bundle_manifest'],
            deployment_revision=selected['deployment_revision'])
        return {'status': 'ok', **observation, 'discovery' if 'search' in query else 'records': parsed['payload'],
                'parser_receipt': parsed['receipt']}


def live(client, query):
    route = '/v1/recalls/search' if 'search' in query else '/v1/recalls/live-query'
    request_query = {**query, 'offset': int(query['offset'])} if 'search' in query else query
    response = client.post(route, json={'query': request_query, 'fallback_policy': 'never'})
    assert response.status_code == 200, response.text
    return response.json()


def payload_of(response, kind):
    return ({key: response[key] for key in ('products', 'pagination')} if kind == 'search'
            else response['records'])


def capture_for(database, query_id):
    with database.sessions() as db:
        return db.scalar(select(RawCapture.id).where(RawCapture.query_id == query_id))


def mark_recall(source, *, loss=False):
    path = source / 'adapters/nhtsa.py'
    with path.open('a', encoding='utf-8') as stream:
        stream.write('\n_original_recall_parser = parse_json\ndef parse_json(body, query):\n'
            '    value = _original_recall_parser(body, query)\n'
            '    rows = [row for product in value["products"] for row in product["campaigns"]] if isinstance(value, dict) else value\n'
            f'    for row in rows: row["remedy"] = {repr("" if loss else "Synthetic parser B corrected remedy")}\n'
            '    return value\n')


def import_b(database, source, *, loss=False):
    mark_recall(source, loss=loss)
    with database.sessions() as db:
        return register_deployed_bundle(db, **SIGNED)['id']


def evaluate(client, bundle_id, captures, revision=1):
    request = {'mode': 'history', 'source_id': SOURCE, 'target_bundle_id': bundle_id,
               'capture_ids': captures, 'expected_deployment_revision': revision}
    headers = {'Idempotency-Key': str(uuid4())}
    response = client.post('/v1/parser-evaluations', headers=headers, json=request)
    assert response.status_code == 201, response.text
    result = response.json()
    assert client.post('/v1/parser-evaluations', headers=headers, json=request).json()['id'] == result['id']
    return result


def review(client, evaluated, **changes):
    return client.post('/v1/parser-evaluations/' + evaluated['id'] + '/reviews', json={
        'mode': 'history', 'action': 'approve', 'expected_revision': evaluated['review_revision'],
        'acknowledged': True, 'completion_fingerprint': evaluated['completion']['fingerprint'], **SIGNED, **changes})


def transition(client, action, revision, **extra):
    return client.post('/v1/parser-deployments/' + SOURCE + '/transitions',
        headers={'Idempotency-Key': str(uuid4())},
        json={'action': action, 'expected_revision': revision, **SIGNED, **extra})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source = trusted_copy(tmp_path, monkeypatch)
    adapter = RecordedRecalls()
    app = create_app('sqlite:///' + (tmp_path / 'recall-release.db').as_posix(), FixtureRegistry())
    app.state.recall_adapter = adapter
    with TestClient(app) as client:
        register_admin(client)
        yield client, app.state.database, adapter, source


def run_lifecycle(client, database, adapter, source, queries):
    first = {kind: live(client, query) for kind, query in queries.items()}
    assert all(row['data_state'] == 'live' for row in first.values())
    first_id = adapter.calls[-1]['bundle_id']
    captures = [capture_for(database, row['query_id']) for row in first.values()]
    assert live(client, queries['campaign'])['data_state'] == 'live_verified_304'
    second_id = import_b(database, source)
    before = formal_counts(database)
    evaluated = evaluate(client, second_id, captures)
    assert evaluated['state'] == 'completed' and evaluated['can_approve']
    assert not evaluated['completion']['reference_gaps'] and not evaluated['completion']['hard_blocks']
    assert {binding['input']['query_key'] for binding in evaluated['bindings']} == {digest(q) for q in queries.values()}
    assert all(row['reference_kind'] == 'accepted_same_raw' for row in evaluated['completion']['results'])
    assert all(row['candidate_receipt']['reaped'] and row['control_receipt']['reaped']
               for row in evaluated['completion']['results'])
    assert formal_counts(database) == before
    assert transition(client, 'activate', 1, target_bundle_id=second_id,
        evaluation_id=evaluated['id'], expected_review_revision=1).status_code == 409
    assert review(client, evaluated, completion_fingerprint='0' * 64).status_code == 409
    assert review(client, evaluated).status_code == 201
    assert review(client, evaluated).status_code == 409
    assert transition(client, 'activate', 1, target_bundle_id=second_id,
        evaluation_id=evaluated['id'], expected_review_revision=1).status_code == 201
    second = {kind: live(client, query) for kind, query in queries.items()}
    assert all(row['data_state'] == 'live' for row in second.values())
    assert all(payload_of(first[kind], kind) != payload_of(second[kind], kind) for kind in queries)
    before_history = formal_counts(database)
    histories = [create_reparse(client, capture, bundle_id=first_id).json() for capture in captures]
    assert all(row['state'] == 'completed' and row['accepted_as_facts'] is False for row in histories), [
        {'state': row['state'], 'error': row['completion']['error_code'], 'receipt': row['completion']['receipt']}
        for row in histories]
    assert all(row['completion']['receipt']['bundle_id'] == first_id for row in histories)
    assert formal_counts(database) == before_history
    assert transition(client, 'rollback', 2, target_revision=1).status_code == 201
    third = {kind: live(client, query) for kind, query in queries.items()}
    assert all(row['data_state'] == 'live' for row in third.values())
    assert all(payload_of(first[kind], kind) == payload_of(third[kind], kind) for kind in queries)
    assert adapter.calls[-1]['deployment_revision'] == 3 and adapter.calls[-1]['bundle_id'] == first_id
    return {'bundle_ids': [first_id, second_id], 'revision': 3, 'source_id': SOURCE, 'queries': queries,
        'evaluation_id': evaluated['id'], 'fingerprint': evaluated['completion']['fingerprint'],
        'capture_ids': captures, 'query_ids': {kind: row['query_id'] for kind, row in third.items()},
        'payloads': {kind: payload_of(row, kind) for kind, row in first.items()},
        'candidate_payloads': {kind: payload_of(row, kind) for kind, row in second.items()},
        'reparse_fingerprints': {row['id']: row['completion']['fingerprint'] for row in histories}}


def test_actual_two_shape_a_b_a_and_historical_candidates(setup):
    client, database, adapter, source = setup
    checkpoint = run_lifecycle(client, database, adapter, source, QUERIES)
    assert len(checkpoint['reparse_fingerprints']) == 2


@pytest.mark.parametrize('kind', QUERIES)
def test_inflight_pause_keeps_receipt_and_capture_but_cannot_adopt(setup, kind):
    client, database, adapter, _ = setup
    def pause():
        adapter.hook = None
        with database.sessions() as db:
            transition_deployment(db, SOURCE, DeploymentTransition(action='pause', expected_revision=1, **SIGNED),
                                  'concurrent-reviewer', str(uuid4()))
    before = formal_counts(database)
    adapter.hook = pause
    result = live(client, QUERIES[kind])
    assert result['reason'] == 'parser_deployment_changed' and formal_counts(database) == before
    with database.sessions() as db:
        capture = db.scalar(select(RawCapture).where(RawCapture.query_id == result['query_id']))
        execution = db.get(ParserExecution, result['query_id'])
        assert capture.parser_identity['deployment_revision'] == 1
        assert execution.state == 'completed' and execution.receipt['reaped']


def test_safety_loss_blocks_approval_for_both_shapes(setup):
    client, database, _, source = setup
    captures = [capture_for(database, live(client, query)['query_id']) for query in QUERIES.values()]
    candidate = import_b(database, source, loss=True)
    before = formal_counts(database)
    evaluated = evaluate(client, candidate, captures)
    assert not evaluated['can_approve']
    assert all('recall_safety_field_loss' in row['quality']['reason_codes']
               for row in evaluated['completion']['results'])
    assert review(client, evaluated).status_code == 409 and formal_counts(database) == before


def test_damaged_control_can_be_repaired_using_same_raw_accepted_evidence(setup):
    client, database, adapter, source = setup
    captures = [capture_for(database, live(client, query)['query_id']) for query in QUERIES.values()]
    first_id = adapter.calls[-1]['bundle_id']
    candidate = import_b(database, source)
    with database.sessions() as db:
        original = deepcopy(db.get(ParserBundle, first_id).manifest)
    archived = bundles.verify_bundle(original)['package_root'] / 'adapters/nhtsa.py'
    archived.write_text('raise RuntimeError("damaged control must never run")\n', encoding='utf-8')
    before = formal_counts(database)
    evaluated = evaluate(client, candidate, captures)
    assert evaluated['can_approve'] and not evaluated['completion']['reference_gaps']
    assert all(row['control_error'] == 'parser_bundle_integrity_failed'
               and row['reference_kind'] == 'accepted_same_raw' for row in evaluated['completion']['results'])
    assert review(client, evaluated).status_code == 201
    assert transition(client, 'activate', 1, target_bundle_id=candidate,
        evaluation_id=evaluated['id'], expected_review_revision=1).status_code == 201
    assert transition(client, 'rollback', 2, target_revision=1).status_code == 503
    assert formal_counts(database) == before


@pytest.mark.parametrize('kind', QUERIES)
def test_reference_is_same_request_raw_while_history_baseline_is_latest(setup, kind):
    client, database, _, _ = setup
    first = seed_recall(client, database, kind)
    newer = nhtsa.parse_json(BODIES[kind], QUERIES[kind])
    row = newer[0] if kind == 'campaign' else newer['products'][0]['campaigns'][0]
    row['remedy'] = 'Later accepted text'
    seed_recall(client, database, kind, payload=newer)
    with database.sessions() as db:
        capture = db.get(RawCapture, first)
        reference = _reference_snapshot(db, capture)
        original = nhtsa.parse_json(BODIES[kind], QUERIES[kind])
        assert reference['payload'] == original
    historical = create_reparse(client, first).json()
    assert historical['baseline']['payload'] == newer
    # A retained rejected raw response cannot borrow another request's acceptance,
    # even where query and raw hash are byte-for-byte identical.
    rejected = seed_recall(client, database, kind, accepted=False)
    with database.sessions() as db:
        assert _reference_snapshot(db, db.get(RawCapture, rejected)) is None


@pytest.mark.parametrize('kind', QUERIES)
def test_reference_gap_requires_acknowledgement_and_does_not_create_facts(setup, kind):
    client, database, _, _ = setup
    capture = seed_recall(client, database, kind, accepted=False)
    bootstrap = client.post('/v1/parser-deployments/' + SOURCE + '/bootstrap', json=SIGNED).json()
    before = formal_counts(database)
    evaluated = evaluate(client, bootstrap['bundle_id'], [capture])
    assert evaluated['completion']['reference_gaps'] == [capture]
    assert evaluated['completion']['results'][0]['reference_kind'] == 'control_same_raw'
    assert review(client, evaluated).status_code == 422
    assert review(client, evaluated, acknowledge_reference_gaps=True).status_code == 201
    assert formal_counts(database) == before


@pytest.mark.parametrize('field,value', [('raw_hash', '0' * 64), ('source_id', 'foreign'),
    ('query_key', '0' * 64), ('source_url', 'https://example.invalid/'), ('content_type', 'text/plain')])
def test_reference_rejects_snapshot_binding_drift(setup, field, value):
    client, database, _, _ = setup
    capture = seed_recall(client, database, 'campaign')
    with database.engine.begin() as connection:
        connection.execute(update(RecallSnapshot).values(**{field: value}))
    with database.sessions() as db:
        assert _reference_snapshot(db, db.get(RawCapture, capture)) is None


def verify_recall_parser_persistence(url, directory):
    """Reusable SQLite/PostgreSQL acceptance with distinct queries and own-ID checks."""
    with pytest.MonkeyPatch.context() as patcher:
        source = trusted_copy(directory, patcher)
        adapter = RecordedRecalls()
        app = create_app(url, FixtureRegistry())
        app.state.recall_adapter = adapter
        with TestClient(app) as client:
            register_admin(client)
            checkpoint = run_lifecycle(client, app.state.database, adapter, source, PERSIST_QUERIES)
            checkpoint['bundle_root'] = str(directory / 'sealed')
        assert_recall_parser_checkpoint(url, checkpoint)
        return checkpoint


def assert_recall_parser_checkpoint(url, checkpoint):
    """Restart/backup-restore check; caller selects the archive root through the env."""
    with pytest.MonkeyPatch.context() as patcher:
        app = create_app(url, FixtureRegistry())
        with TestClient(app) as client:
            current = client.get('/v1/parser-deployments/' + SOURCE + '?mode=history').json()
            assert current['revision'] == checkpoint['revision'] and current['bundle_id'] == checkpoint['bundle_ids'][0]
            evaluated = client.get('/v1/parser-evaluations/' + checkpoint['evaluation_id'] + '?mode=history').json()
            assert evaluated['completion']['fingerprint'] == checkpoint['fingerprint']
            before = formal_counts(app.state.database)
            for run_id, fingerprint in checkpoint['reparse_fingerprints'].items():
                history = client.get('/v1/reparse/runs/' + run_id + '?mode=history').json()
                assert history['completion']['fingerprint'] == fingerprint
            with app.state.database.sessions() as db:
                manifests = [deepcopy(db.get(ParserBundle, value).manifest) for value in checkpoint['bundle_ids']]
                captured = {}
                for capture_id in checkpoint['capture_ids']:
                    capture = db.get(RawCapture, capture_id)
                    query = db.get(QueryRun, capture.query_id).query
                    kind = 'search' if 'search' in query else 'campaign'
                    raw, _ = checked_capture_bytes(db, capture)
                    assert query == checkpoint['queries'][kind] and raw == body_for(query).encode('utf-8')
                    captured[kind] = raw
                for kind, query_id in checkpoint['query_ids'].items():
                    snapshot_type, verification_type, field = ((RecallSnapshot, RecallVerification, 'records')
                        if kind == 'campaign' else (RecallSearchSnapshot, RecallSearchVerification, 'discovery'))
                    snapshot = db.scalar(select(snapshot_type).join(verification_type)
                        .where(verification_type.query_id == query_id))
                    assert getattr(snapshot, field) == checkpoint['payloads'][kind]
                    execution = db.get(ParserExecution, query_id)
                    assert execution.receipt['bundle_id'] == checkpoint['bundle_ids'][0]
                    assert execution.receipt['deployment_revision'] == checkpoint['revision']
            for manifest in manifests:
                descriptor = bundles.bundle_descriptor(manifest, SOURCE)
                for kind, query in checkpoint['queries'].items():
                    parsed = asyncio.run(runtime.parse_isolated(SOURCE, captured[kind], query,
                        descriptor['parser_version'], descriptor['parser_digest'], bundle_manifest=manifest,
                        deployment_revision=checkpoint['revision']))
                    assert parsed['receipt']['reaped']
                    expected = checkpoint['payloads'] if manifest is manifests[0] else checkpoint['candidate_payloads']
                    assert parsed['payload'] == expected[kind]
            assert formal_counts(app.state.database) == before


def test_sqlite_restart_checkpoint(tmp_path):
    verify_recall_parser_persistence('sqlite:///' + (tmp_path / 'restart.db').as_posix(), tmp_path)


def test_legacy_eight_source_catalog_stays_executable_and_does_not_invent_recall(setup, monkeypatch):
    client, database, _, source = setup
    current_specs = runtime._specs
    historical_install(source, 8)
    with monkeypatch.context() as patcher:
        patcher.setattr(runtime, '_specs', lambda: {key: value for key, value in current_specs().items()
                                                if key in bundles._LEGACY_SOURCES})
        with database.sessions() as db:
            registered = register_deployed_bundle(db, **SIGNED)
            manifest = deepcopy(db.get(ParserBundle, registered['id']).manifest)
    assert 'adapters/nhtsa.py' not in manifest['files'] and 'adapters/pirelli.py' not in manifest['files']
    catalog = client.get('/v1/reparse/catalog', params={'mode': 'history', 'bundle_id': registered['id']})
    assert catalog.status_code == 200 and len(catalog.json()['parsers']) == 8
    assert SOURCE not in {row['source_id'] for row in catalog.json()['parsers']}
    assert len(client.get('/v1/reparse/catalog?mode=history').json()['parsers']) == 10
    from test_parser_bundles import execute_bundle
    replay = asyncio.run(execute_bundle(manifest))
    assert replay['payload'] and replay['receipt']['reaped']
    capture = seed_recall(client, database, 'campaign')
    response = client.post('/v1/reparse/runs', headers={'Idempotency-Key': str(uuid4())}, json={
        'mode': 'history', 'capture_id': capture, 'bundle_id': registered['id'],
        'parser_version': nhtsa.PARSER_VERSION, 'parser_digest': 'a' * 64})
    assert response.status_code == 422 and response.json()['detail']['code'] == 'unsupported_reparse_source'
