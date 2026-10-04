"""Human review never itself promotes old evidence or relaxes identity/schema validation."""
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import select

from tire_api.db import (AuditEvent, QuarantineApprovalUse, QuarantineReview, Snapshot,
                         SourceQuarantine, utcnow)
from tire_api import quarantine_review as reviews
from admin_support import ADMIN_PASSWORD, register_admin
from test_quality import (QUERY, accepted_counts, count, grant, live, quarantine, reduced,
                          result, setup)
from test_vehicles import setup as vehicle_setup, live as vehicle_live
from test_vehicle_quality import remove_trim


def rejected(client, registry):
    live(client)
    registry.result = result([reduced()])
    assert live(client).json()['reason'] == 'source_quality_quarantined'
    return quarantine(client)['id']


def state(client, qid):
    response = client.get(f'/v1/quarantines/{qid}/review?mode=history')
    assert response.status_code == 200, response.text
    return response.json()


def decide(client, qid, revision=0, action='approve', **extra):
    return client.post(f'/v1/quarantines/{qid}/reviews', json={
        'action': action, 'expected_revision': revision, 'operator': 'Fixture reviewer',
        'reason': 'Synthetic confirmation of expected loss', 'confirmed_loss': True, **extra})


def test_approval_is_not_acceptance_or_consent_and_only_matching_online_fetch_applies(setup):
    client, registry, database = setup
    qid = rejected(client, registry)
    before = accepted_counts(database)
    calls = len(registry.calls)
    assert state(client, qid)['state'] == 'pending'
    saved = decide(client, qid)
    assert saved.status_code == 201, saved.text
    assert saved.json()['state'] == 'approved_waiting_online'
    assert accepted_counts(database) == before and len(registry.calls) == calls
    expected = deepcopy(registry.result)
    registry.result = {'status': 'unavailable', 'reason': 'synthetic_outage'}
    unavailable = live(client).json()
    assert unavailable['data_state'] == 'consent_required' and unavailable['variants'] == []
    consent = grant(client, unavailable['query_id']).json()
    fallback = live(client, {**QUERY, 'consent_id': consent['id']}).json()
    assert fallback['data_state'] == 'local_snapshot'
    assert fallback['variants'][0]['facts']['field_0'] == 0
    assert count(database, QuarantineApprovalUse) == 0
    registry.result = expected
    accepted = live(client).json()
    assert accepted['data_state'] == 'live' and accepted['variants'][0]['facts']['field_0'] is None
    assert count(database, QuarantineApprovalUse) == 1
    review = state(client, qid)
    assert review['state'] == 'applied_on_online_fetch' and review['applied_query_id'] == accepted['query_id']
    assert not review['can_approve']
    evidence = client.get('/v1/evidence/' + accepted['provenance'][0]['snapshot_id']).json()
    assert evidence['quality_review']['id'] == saved.json()['history'][0]['id']
    assert client.get(f'/v1/quarantines/{qid}?mode=history').json()['accepted'] is False
    assert decide(client, qid, 1, action='keep_quarantined').status_code == 409
    with database.sessions() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == 'quarantine_approval_applied'))


@pytest.mark.parametrize('change', ['body', 'parser_version', 'url', 'content_type', 'payload', 'query', 'source'])
def test_approval_is_bound_to_all_reviewed_inputs(setup, change):
    client, registry, database = setup
    qid = rejected(client, registry)
    assert decide(client, qid).status_code == 201
    if change == 'body': registry.result['body'] += ' '
    elif change == 'payload': registry.result['variants'][0]['facts']['field_7'] = 99
    elif change == 'parser_version': registry.result['parser_version'] = 'quality-fixture@2'
    elif change == 'url': registry.result['url'] += '/new'
    elif change == 'content_type': registry.result['content_type'] = 'text/plain'
    elif change == 'query':
        live(client, {'query': {'model': 'Quality Test Tire'}, 'fallback_policy': 'ask'})
        assert count(database, QuarantineApprovalUse) == 0
        return
    elif change == 'source':
        live(client, source='other-region-fixture')
        assert count(database, QuarantineApprovalUse) == 0
        return
    assert live(client).json()['reason'] == 'source_quality_quarantined'
    assert count(database, QuarantineApprovalUse) == 0


def test_repeated_identical_quarantines_share_revision_and_rejection_revokes_pending_approval(setup):
    client, registry, database = setup
    qid = rejected(client, registry)
    live(client)
    other = quarantine(client)['id']
    assert other != qid
    assert decide(client, qid).status_code == 201
    assert state(client, other)['revision'] == 1
    assert decide(client, other).status_code == 409
    assert decide(client, other, 1, 'keep_quarantined').status_code == 201
    assert state(client, qid)['state'] == 'kept_quarantined'
    assert live(client).json()['reason'] == 'source_quality_quarantined'
    assert count(database, QuarantineApprovalUse) == 0


def test_approval_expires_and_stale_baseline_requires_new_review(setup, monkeypatch):
    client, registry, database = setup
    qid = rejected(client, registry)
    decide(client, qid)
    monkeypatch.setattr(reviews, 'utcnow', lambda: utcnow() + timedelta(days=2))
    assert state(client, qid)['state'] == 'expired'
    assert live(client).json()['reason'] == 'source_quality_quarantined'
    monkeypatch.undo()
    registry.result = result(parser_version='quality-fixture@2')
    assert live(client).json()['data_state'] == 'live'
    assert state(client, qid)['state'] == 'stale_baseline'
    assert decide(client, qid, 1).status_code == 409
    registry.result = result([reduced()])
    assert live(client).json()['reason'] == 'source_quality_quarantined'
    assert count(database, QuarantineApprovalUse) == 0


@pytest.mark.parametrize('kind', ['identity', 'ambiguous', 'parser'])
def test_identity_and_invalid_schema_cannot_be_approved(setup, kind):
    client, registry, database = setup
    live(client)
    row = reduced()
    if kind == 'identity': row['speed_rating'] = None
    registry.result = result([row, row] if kind == 'ambiguous' else [row])
    if kind == 'parser':
        registry.result = {'status': 'unavailable', 'reason': 'parser_schema_changed',
                           'rejected_observation': result([row])}
    live(client)
    qid = quarantine(client)['id']
    assert decide(client, qid).status_code == 409
    assert count(database, QuarantineReview) == 0


def test_review_validation_and_append_only_history(setup):
    client, registry, database = setup
    qid = rejected(client, registry)
    assert client.get(f'/v1/quarantines/{qid}/review').status_code == 422
    for extra in ({'operator': ' '}, {'reason': 'bad\x00text'}, {'expected_revision': True}, {'action': 'force'},
                  {'confirmed_loss': False}, {'confirmed_loss': 1}):
        assert decide(client, qid, **extra).status_code == 422
    decide(client, qid, operator='<script>fixture</script>')
    with database.sessions() as db:
        item = db.scalar(select(QuarantineReview))
        item.reason = 'overwrite'
        with pytest.raises(ValueError): db.commit()
    assert state(client, qid)['history'][0]['operator'] == '<script>fixture</script>'


def test_vehicle_approval_uses_separate_baseline_and_preserves_old_fitment_evidence(vehicle_setup):
    client, adapter, database = vehicle_setup
    original = vehicle_live(client).json()
    remove_trim(adapter)
    assert vehicle_live(client).json()['reason'] == 'source_quality_quarantined'
    qid = quarantine(client)['id']
    assert decide(client, qid).status_code == 201
    accepted = vehicle_live(client).json()
    assert accepted['data_state'] == 'live' and len(accepted['fitments']) == 2
    assert len(original['fitments']) == 4
    assert state(client, qid)['state'] == 'applied_on_online_fetch'
    assert count(database, QuarantineApprovalUse) == 1
    evidence = client.get('/v1/vehicle-evidence/' + accepted['provenance'][0]['snapshot_id']).json()
    assert evidence['quality_review']['action'] == 'approve'


def test_approval_use_rolls_back_with_failed_fact_transaction(setup, monkeypatch):
    client, registry, database = setup
    qid = rejected(client, registry)
    decide(client, qid)
    from tire_api import monitoring
    def fail(*_): raise RuntimeError('synthetic downstream failure')
    monkeypatch.setattr(monitoring, 'record_alerts', fail)
    with pytest.raises(RuntimeError): live(client)
    assert count(database, QuarantineApprovalUse) == 0
    assert count(database, Snapshot) == 1
    assert state(client, qid)['state'] == 'approved_waiting_online'


@pytest.mark.parametrize('verification_status', ['ok', 'not_modified'])
def test_existing_inflight_or_304_query_cannot_consume_new_approval(setup, verification_status):
    from tire_api.db import QueryRun
    from tire_api.service import QueryService
    from tire_api.quality import SourceQualityQuarantined
    client, registry, database = setup
    qid = rejected(client, registry)
    with database.sessions() as db:
        query_id = db.get(SourceQuarantine, qid).query_id
    decide(client, qid)
    with database.sessions() as db:
        run = db.get(QueryRun, query_id)
        variants = QueryService.validate_result(registry.result, run.query)
        with pytest.raises(SourceQualityQuarantined):
            QueryService(db, registry).record_success(run, registry.result, variants, verification_status)
        db.rollback()
    assert count(database, QuarantineApprovalUse) == 0


def verify_concurrent_review(url):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    from tire_api.main import create_app
    from test_quality import FixtureRegistry
    registry = FixtureRegistry()
    app = create_app(url, registry)
    with TestClient(app) as seed:
        register_admin(seed)
        baseline_counts = {model: count(app.state.database, model)
                           for model in (QuarantineApprovalUse, QuarantineReview, Snapshot)}
        qid = rejected(seed, registry)
        barrier = Barrier(2)
        def review(_):
            with TestClient(create_app(url, registry)) as client:
                assert client.post('/v1/auth/login',
                                   json={'username': 'admin', 'password': ADMIN_PASSWORD}).status_code == 200
                barrier.wait(timeout=10)
                return decide(client, qid).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(review, range(2)))
        assert sorted(statuses) == [201, 409]
        def query(_):
            with TestClient(create_app(url, registry)) as client:
                barrier.wait(timeout=10)
                return live(client).json()['data_state']
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(query, range(2))) == ['live', 'live']
        assert count(app.state.database, QuarantineApprovalUse) == baseline_counts[QuarantineApprovalUse] + 1
        assert count(app.state.database, QuarantineReview) == baseline_counts[QuarantineReview] + 1
        assert count(app.state.database, Snapshot) == baseline_counts[Snapshot] + 2


def test_concurrent_review_and_queries_consume_one_approval(tmp_path):
    verify_concurrent_review('sqlite:///' + (tmp_path / 'reviews.db').as_posix())
