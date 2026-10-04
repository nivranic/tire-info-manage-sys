"""Private synthetic workflow data; none of these signatures assert real human ground truth."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, update

from tire_api.adapters import hankook
from tire_api.db import CaptureObject, RawCapture
from tire_api.domain import VariantInput
from tire_api.golden import CaseReviewCreate, GoldenError, review_case
from tire_api.golden_models import GoldenCase, GoldenCaseRevision, GoldenCaseReview, GoldenSetRevision
from tire_api.main import create_app
from admin_support import register_admin
from test_core import FixtureRegistry
from test_reparse import BODY, QUERY, seed_capture, totals

SOURCE = 'hankook-us'
SIGNED = {'operator': 'Synthetic Golden reviewer', 'reason': 'Synthetic workflow only; not genuine human-reviewed truth'}


def fixture_expected(marker=None):
    """Scaffold for workflow tests. Correctness and adversarial expectations live in test_golden_checks."""
    values = [VariantInput.model_validate(row).model_dump() for row in hankook.parse_html(BODY, QUERY)]
    if marker is not None:
        for value in values:
            value['facts']['utqg_treadwear'] = marker
    return {'records': [{'golden_sku_id': f'synthetic-sku-{index}', 'value': value} for index, value in enumerate(values)]}


def post(client, path, value, key=None):
    return client.post(path, json=value, headers={'Idempotency-Key': key or str(uuid4())})


def case_payload(capture_id, expected=None):
    return {'kind': 'tire', 'source_id': SOURCE, 'title': 'Synthetic run-flat pair', 'capture_id': capture_id,
        'evidence_note': 'Saved synthetic-test excerpt: two specification rows; no real human review is claimed.',
        'expected': expected or fixture_expected(), 'expected_revision': 0, 'expected_fingerprint': None, **SIGNED}


def create_case(client, capture_id, expected=None):
    response = post(client, '/v1/golden/cases', case_payload(capture_id, expected))
    assert response.status_code == 201, response.text
    return response.json()


def review_payload(case, action='approve'):
    return {'case_revision': case['revision'], 'case_fingerprint': case['fingerprint'],
        'expected_revision': case['review_revision'], 'expected_fingerprint': case['review_fingerprint'],
        'action': action, 'acknowledged': True, **SIGNED}


def sign_case(client, case, action='approve'):
    response = post(client, f"/v1/golden/cases/{case['id']}/reviews", review_payload(case, action))
    assert response.status_code == 201, response.text
    return response.json()


def case_ref(case):
    return {'case_id': case['id'], 'case_revision': case['revision'], 'case_fingerprint': case['fingerprint'],
        'review_revision': case['review_revision'], 'review_fingerprint': case['review_fingerprint']}


def set_payload(cases):
    return {'title': 'Synthetic bounded Golden set', 'source_id': cases[0]['source_id'],
        'case_refs': [case_ref(case) for case in cases], 'expected_revision': 0, 'expected_fingerprint': None,
        'acknowledged': True, **SIGNED}


def freeze_cases(client, cases):
    response = post(client, '/v1/golden/sets', set_payload(cases))
    assert response.status_code == 201, response.text
    return response.json()


def synthetic_set(client, capture_ids, expected=None):
    cases = [sign_case(client, create_case(client, capture, expected)) for capture in capture_ids]
    return freeze_cases(client, cases)


def evaluation_reference(frozen):
    return {'golden_set_id': frozen['id'], 'expected_golden_set_revision': frozen['revision'],
            'golden_set_fingerprint': frozen['fingerprint']}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def prohibited(*_args, **_kwargs):
        pytest.fail('Golden CRUD must not resolve/execute a Parser, fetch, or accept facts')
    from tire_api import parser_runtime, parser_bundles
    monkeypatch.setattr(parser_runtime, 'current_parser', prohibited)
    monkeypatch.setattr(parser_runtime, 'parse_isolated', prohibited)
    monkeypatch.setattr(parser_bundles, 'verify_bundle', prohibited)
    app = create_app('sqlite:///' + (tmp_path / 'golden.db').as_posix(), FixtureRegistry())
    with TestClient(app) as client:
        register_admin(client)
        capture_id = seed_capture(client, app.state.database)
        yield client, app.state.database, capture_id


def test_manual_case_review_freeze_is_append_only_and_never_accepts_facts(setup):
    client, db, capture_id = setup
    before = totals(db)
    draft = create_case(client, capture_id)
    assert draft['status'] == 'pending' and draft['review_revision'] == 0
    assert draft['expected']['records'][0]['value']['xl'] is True
    fake_ref = {**case_ref(draft), 'review_revision': 1, 'review_fingerprint': '0' * 64}
    assert post(client, '/v1/golden/sets', {**set_payload([draft]), 'case_refs': [fake_ref]}).status_code == 409
    approved = sign_case(client, draft)
    frozen = freeze_cases(client, [approved])
    assert approved['status'] == 'approved' and frozen['eligible'] and frozen['capture_ids'] == [capture_id]
    assert frozen['data_state'] == 'local_snapshot' and not frozen['accepted_as_facts']
    assert not frozen['test_event_supported']
    assert totals(db) == before
    assert 'actor_session_id' not in str(frozen) and 'actor_session_id' not in str(approved)
    assert client.get('/v1/golden/cases?mode=history').json()['total'] == 1
    assert client.get('/v1/golden/sets?mode=history').json()['total'] == 1


def test_idempotent_writes_bind_payload_and_review_revision(setup):
    client, db, capture = setup
    payload, key = case_payload(capture), str(uuid4())
    first = post(client, '/v1/golden/cases', payload, key).json()
    assert post(client, '/v1/golden/cases', payload, key).json()['id'] == first['id']
    assert post(client, '/v1/golden/cases', {**payload, 'title': 'different'}, key).status_code == 409
    review, review_key = review_payload(first), str(uuid4())
    path = f"/v1/golden/cases/{first['id']}/reviews"
    approved = post(client, path, review, review_key).json()
    assert post(client, path, review, review_key).json()['review_revision'] == 1
    assert post(client, path, review).status_code == 409
    assert post(client, path, {**review_payload(approved), 'expected_fingerprint': '0' * 64}).status_code == 409
    assert post(client, path, {**review_payload(approved), 'acknowledged': False}).status_code == 422
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(GoldenCaseRevision)) == 1
        assert session.scalar(select(func.count()).select_from(GoldenCaseReview)) == 1


def test_new_case_revision_invalidates_frozen_set_even_when_content_returns(setup):
    client, _, capture = setup
    initial = sign_case(client, create_case(client, capture))
    frozen = freeze_cases(client, [initial])
    payload = case_payload(capture)
    payload.pop('kind'); payload.pop('source_id')
    payload.update(expected_revision=initial['revision'], expected_fingerprint=initial['fingerprint'])
    changed = post(client, f"/v1/golden/cases/{initial['id']}/revisions", payload)
    assert changed.status_code == 201, changed.text
    changed = changed.json()
    assert changed['status'] == 'pending' and changed['revision'] == 2
    assert changed['fingerprint'] != initial['fingerprint']
    stale = client.get(f"/v1/golden/sets/{frozen['id']}?mode=history").json()
    assert not stale['eligible'] and 'golden_case_stale' in stale['blockers']
    sign_case(client, changed)
    assert not client.get(f"/v1/golden/sets/{frozen['id']}?mode=history").json()['eligible']
    historical = client.get(f"/v1/golden/cases/{initial['id']}?mode=history&revision=1").json()
    assert historical['expected'] == initial['expected'] and not historical['is_current']


def test_review_revoke_reapprove_does_not_resurrect_old_frozen_revision(setup):
    client, _, capture = setup
    case = sign_case(client, create_case(client, capture))
    frozen = freeze_cases(client, [case])
    revoked = sign_case(client, case, 'revoke')
    assert not client.get(f"/v1/golden/sets/{frozen['id']}?mode=history").json()['eligible']
    restored = sign_case(client, revoked)
    assert not client.get(f"/v1/golden/sets/{frozen['id']}?mode=history").json()['eligible']
    payload = {**set_payload([restored]), 'action': 'freeze', 'expected_revision': 1,
               'expected_fingerprint': frozen['fingerprint']}
    refreshed = post(client, f"/v1/golden/sets/{frozen['id']}/revisions", payload)
    assert refreshed.status_code == 201, refreshed.text
    assert refreshed.json()['eligible'] and refreshed.json()['revision'] == 2


def test_set_revoke_and_idempotent_replay_keep_old_event_stale(setup):
    client, _, capture = setup
    case = sign_case(client, create_case(client, capture))
    payload, key = set_payload([case]), str(uuid4())
    frozen = post(client, '/v1/golden/sets', payload, key).json()
    revoked = post(client, f"/v1/golden/sets/{frozen['id']}/revisions", {**payload, 'case_refs': [],
        'action': 'revoke', 'expected_revision': 1, 'expected_fingerprint': frozen['fingerprint']})
    assert revoked.status_code == 201 and revoked.json()['state'] == 'revoked'
    replay = post(client, '/v1/golden/sets', payload, key).json()
    assert replay['revision'] == 1 and not replay['eligible']
    current = client.get(f"/v1/golden/sets/{frozen['id']}?mode=history").json()
    assert current['revision'] == 2 and current['state'] == 'revoked'


def test_duplicate_capture_and_partial_unreviewed_members_are_not_frozen(setup):
    client, db, capture = setup
    a = sign_case(client, create_case(client, capture))
    duplicate = sign_case(client, create_case(client, capture))
    response = post(client, '/v1/golden/sets', set_payload([a, duplicate]))
    assert response.status_code == 422 and response.json()['detail']['code'] == 'golden_set_coverage_invalid'
    second_capture = seed_capture(client, db)
    b = sign_case(client, create_case(client, second_capture))
    frozen = freeze_cases(client, [a, b])
    assert len(frozen['capture_ids']) == 2


@pytest.mark.parametrize('mutation', [
    {'kind': 'test_event'}, {'evidence_note': '  '}, {'operator': ' '}, {'code': 'print(1)'},
    {'expected_revision': 1, 'expected_fingerprint': None}, {'expected': {'records': []}},
])
def test_invalid_drafts_are_rejected_without_writing(setup, mutation):
    client, db, capture = setup
    response = post(client, '/v1/golden/cases', {**case_payload(capture), **mutation})
    assert response.status_code == 422, response.text
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(GoldenCase)) == 0


def test_history_mode_uuid_and_exact_content_fingerprint_are_required(setup):
    client, _, capture = setup
    assert client.get('/v1/golden/cases').status_code == 422
    assert client.get('/v1/golden/sets').status_code == 422
    assert client.post('/v1/golden/cases', json=case_payload(capture)).status_code == 422
    assert post(client, '/v1/golden/cases', case_payload(capture), 'invalid').status_code == 422
    case = create_case(client, capture)
    assert post(client, f"/v1/golden/cases/{case['id']}/reviews",
                {**review_payload(case), 'case_fingerprint': '0' * 64}).status_code == 409


def test_missing_object_never_falls_back_to_retained_database_body(setup, monkeypatch):
    client, db, capture = setup
    case = create_case(client, capture)
    with db.sessions() as session:
        assert session.get(CaptureObject, capture) is not None
        assert session.get(RawCapture, capture).raw_body
    def missing(*_args, **_kwargs):
        raise OSError('synthetic missing object')
    monkeypatch.setattr(db.object_store, 'get', missing)
    response = post(client, f"/v1/golden/cases/{case['id']}/reviews", review_payload(case))
    assert response.status_code == 503 and response.json()['detail']['code'] == 'golden_capture_integrity_failed'
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(GoldenCaseReview)) == 0


@pytest.mark.parametrize('model', [GoldenCase, GoldenCaseRevision, GoldenCaseReview, GoldenSetRevision])
def test_model_history_cannot_be_updated_or_deleted(setup, model):
    client, db, capture = setup
    frozen = synthetic_set(client, [capture])
    assert frozen['eligible']
    with db.sessions() as session:
        row = session.scalar(select(model))
        session.delete(row)
        with pytest.raises(ValueError, match='只能追加'):
            session.commit()
        session.rollback()


def test_bypassing_orm_content_tamper_is_detected_by_fingerprint(setup):
    client, db, capture = setup
    case = create_case(client, capture)
    with db.engine.begin() as connection:
        connection.execute(update(GoldenCaseRevision).where(GoldenCaseRevision.case_id == case['id']).values(title='tampered'))
    result = client.get(f"/v1/golden/cases/{case['id']}?mode=history")
    assert result.status_code == 503 and result.json()['detail']['code'] == 'golden_content_integrity_failed'


def test_concurrent_human_reviews_use_compare_and_swap(setup):
    client, db, capture = setup
    case = create_case(client, capture)
    payload, gate = CaseReviewCreate.model_validate(review_payload(case)), Barrier(2)
    def submit(_index):
        with db.sessions() as session:
            gate.wait(timeout=10)
            try:
                return review_case(session, case['id'], payload, 'synthetic-concurrent-reviewer', str(uuid4()))['review_revision']
            except GoldenError as error:
                return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert sorted(map(str, results)) == ['1', 'golden_review_revision_conflict']
