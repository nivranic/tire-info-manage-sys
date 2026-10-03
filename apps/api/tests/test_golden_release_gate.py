"""Private captures and real isolated Parser children; synthetic signatures only."""
from types import SimpleNamespace
from pathlib import Path

import pytest
from sqlalchemy import func, select

from tire_api import parser_runtime as runtime
from tire_api.parser_release_models import ParserEvaluation, ParserEvaluationReview
from test_golden import (SIGNED, case_payload, evaluation_reference, fixture_expected, post,
                         sign_case, synthetic_set)
from test_parser_releases import SOURCE, evaluate, live, review, setup, transition
from test_reparse import seed_capture


def current_bundle(client):
    return client.get(f'/v1/parser-deployments/{SOURCE}?mode=history').json()['bundle_id']


@pytest.mark.parametrize('source_id,kinds,applicable', [
    ('nhtsa-us-recalls', ['recall'], False), ('nhtsa-us-recalls', ['recall', 'tire'], True),
    ('hankook-us', ['recall'], True), ('unknown-source', ['recall'], True),
])
def test_only_confirmed_recall_scope_uses_existing_non_golden_gate(source_id, kinds, applicable):
    from tire_api.parser_releases import _golden_gate
    evaluation = SimpleNamespace(source_id=source_id, bindings=[{'input': {'target_kind': kind}} for kind in kinds])
    gate = _golden_gate(None, evaluation, None)
    assert gate['applicable'] is applicable
    assert gate['state'] == ('unverified' if applicable else 'not_applicable')
    if not applicable:
        assert gate['scope'] == 'legacy_recall_regression'


def test_legacy_relative_regression_is_readable_but_cannot_approve_or_publish(setup):
    client, db, _, _ = setup
    assert live(client)['data_state'] == 'live'
    bundle = current_bundle(client)
    result = evaluate(client, bundle, golden=False)
    assert result['state'] == 'completed' and not result['completion']['hard_blocks']
    assert result['golden_gate']['state'] == 'unverified' and not result['can_approve']
    rejected = review(client, result, acknowledge_reference_gaps=True)
    assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'golden_set_required'
    assert transition(client, 'activate', 1, target_bundle_id=bundle,
        evaluation_id=result['id'], expected_review_revision=1).status_code == 409
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ParserEvaluationReview)) == 0


def test_tire_bootstrap_cannot_resume_or_rollback_as_a_reviewed_release(setup):
    client, _, _, _ = setup
    initial = client.post(f'/v1/parser-deployments/{SOURCE}/bootstrap', json=SIGNED).json()
    assert initial['golden_gate']['state'] == 'unverified' and initial['golden_gate']['applicable']
    assert transition(client, 'pause', 1).status_code == 201
    for action, kwargs in [('resume', {}), ('rollback', {'target_revision': 1})]:
        result = transition(client, action, 2, **kwargs)
        assert result.status_code == 409 and result.json()['detail']['code'] == 'golden_release_review_required'


def test_golden_mismatch_cannot_be_acknowledged_as_a_reference_gap(setup):
    client, db, _, _ = setup
    capture = seed_capture(client, db)
    bundle = client.post(f'/v1/parser-deployments/{SOURCE}/bootstrap', json=SIGNED).json()['bundle_id']
    frozen = synthetic_set(client, [capture], fixture_expected(marker=999))
    response = post(client, '/v1/parser-evaluations', {'mode': 'history', 'source_id': SOURCE,
        'target_bundle_id': bundle, 'capture_ids': [capture], 'expected_deployment_revision': 1,
        **evaluation_reference(frozen)})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['completion']['reference_gaps'] == [capture]
    assert result['golden_gate']['state'] == 'failed'
    assert any(item['code'] == 'golden_assertions_failed' for item in result['completion']['hard_blocks'])
    assert review(client, result, acknowledge_reference_gaps=True).status_code == 409


def test_frozen_set_members_cannot_be_omitted_from_evaluation(setup):
    client, db, _, _ = setup
    a, b = seed_capture(client, db), seed_capture(client, db)
    frozen = synthetic_set(client, [a, b])
    bundle = client.post(f'/v1/parser-deployments/{SOURCE}/bootstrap', json=SIGNED).json()['bundle_id']
    response = post(client, '/v1/parser-evaluations', {'mode': 'history', 'source_id': SOURCE,
        'target_bundle_id': bundle, 'capture_ids': [a], 'expected_deployment_revision': 1,
        **evaluation_reference(frozen)})
    assert response.status_code == 422 and response.json()['detail']['code'] == 'golden_set_capture_mismatch'
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ParserEvaluation)) == 0


def test_review_revocation_invalidates_approved_release_and_all_restore_paths(setup):
    client, _, _, _ = setup
    assert live(client)['data_state'] == 'live'
    bundle = current_bundle(client)
    evaluated = evaluate(client, bundle)
    assert evaluated['golden_gate']['state'] == 'passed'
    assert evaluated['golden_gate']['report']['wrong_merge_count'] == 0
    assert review(client, evaluated).status_code == 201
    released = transition(client, 'activate', 1, target_bundle_id=bundle,
        evaluation_id=evaluated['id'], expected_review_revision=1)
    assert released.status_code == 201 and released.json()['golden_gate']['state'] == 'passed'
    case_id = evaluated['bindings'][0]['golden']['case']['case_id']
    case = client.get(f'/v1/golden/cases/{case_id}?mode=history').json()
    sign_case(client, case, 'revoke')
    updated = client.get(f'/v1/parser-deployments/{SOURCE}?mode=history').json()
    assert updated['golden_gate']['state'] == 'stale'
    assert transition(client, 'pause', 2).status_code == 201
    assert transition(client, 'resume', 3).status_code == 409
    assert transition(client, 'rollback', 3, target_revision=2).status_code == 409
    frozen = client.get(f"/v1/parser-evaluations/{evaluated['id']}?mode=history").json()
    assert frozen['completion']['fingerprint'] == evaluated['completion']['fingerprint']
    assert frozen['golden_gate']['state'] == 'stale'


@pytest.mark.parametrize('already_released', [False, True])
def test_host_only_execution_digest_drift_invalidates_golden_gate(setup, monkeypatch, already_released):
    client, _, _, _ = setup
    assert live(client)['data_state'] == 'live'
    bundle = current_bundle(client)
    evaluated = evaluate(client, bundle)
    approved = review(client, evaluated)
    assert approved.status_code == 201, approved.text
    if already_released:
        assert transition(client, 'activate', 1, target_bundle_id=bundle,
            evaluation_id=evaluated['id'], expected_review_revision=1).status_code == 201
        assert transition(client, 'pause', 2).status_code == 201
    original_digest = runtime._host_digest()
    monkeypatch.setattr(runtime, '_host_digest', lambda: 'f' * 64 if original_digest != 'f' * 64 else '0' * 64)
    updated = client.get(f"/v1/parser-evaluations/{evaluated['id']}?mode=history").json()
    assert updated['golden_gate']['state'] == 'stale' and not updated['can_approve']
    assert updated['golden_gate']['blockers'] == ['golden_parser_execution_changed']
    if already_released:
        for action, kwargs in [('resume', {}), ('rollback', {'target_revision': 2})]:
            result = transition(client, action, 3, **kwargs)
            assert result.status_code == 409 and result.json()['detail']['code'] == 'golden_parser_execution_changed'
    else:
        repeated = review(client, approved.json())
        assert repeated.status_code == 409 and repeated.json()['detail']['code'] == 'golden_parser_execution_changed'
        result = transition(client, 'activate', 1, target_bundle_id=bundle,
            evaluation_id=evaluated['id'], expected_review_revision=1)
        assert result.status_code == 409 and result.json()['detail']['code'] == 'golden_parser_execution_changed'


def test_comparison_contract_change_requires_new_evaluation(setup, monkeypatch):
    client, _, _, _ = setup
    from tire_api import golden_checks
    assert live(client)['data_state'] == 'live'
    bundle = current_bundle(client)
    evaluated = evaluate(client, bundle)
    assert review(client, evaluated).status_code == 201
    descriptor = golden_checks.contract_descriptor()
    monkeypatch.setattr(golden_checks, 'contract_descriptor', lambda: {**descriptor, 'digest': '0' * 64})
    result = transition(client, 'activate', 1, target_bundle_id=bundle,
        evaluation_id=evaluated['id'], expected_review_revision=1)
    assert result.status_code == 409 and result.json()['detail']['code'] == 'golden_contract_or_source_changed'


def test_host_validation_file_drift_invalidates_existing_golden_evaluation(setup, monkeypatch):
    """One real evaluation, then three host-only byte changes without touching its sealed package."""
    client, db, _, _ = setup
    assert live(client)['data_state'] == 'live'
    bundle = current_bundle(client)
    evaluated = evaluate(client, bundle)
    approved = review(client, evaluated)
    assert approved.status_code == 201, approved.text
    original_read = Path.read_bytes
    installed_root = Path(runtime.__file__).resolve().parent
    for name in ('reparse.py', 'vehicles.py', 'service.py'):
        target = installed_root / name
        reads = []
        def altered_host_bytes(path):
            value = original_read(path)
            if path.resolve() == target:
                reads.append(name)
                return value + b'\n# synthetic host-validation revision for a gate test\n'
            return value
        with monkeypatch.context() as patcher:
            patcher.setattr(Path, 'read_bytes', altered_host_bytes)
            current = client.get(f"/v1/parser-evaluations/{evaluated['id']}?mode=history").json()
            assert current['golden_gate']['state'] == 'stale', name
            assert current['golden_gate']['blockers'] == ['golden_contract_or_source_changed'], name
            assert not current['can_approve'] and reads, name
            repeated = review(client, approved.json())
            assert repeated.status_code == 409 and repeated.json()['detail']['code'] == 'golden_contract_or_source_changed', name
            activated = transition(client, 'activate', 1, target_bundle_id=bundle,
                evaluation_id=evaluated['id'], expected_review_revision=1)
            assert activated.status_code == 409 and activated.json()['detail']['code'] == 'golden_contract_or_source_changed', name
    assert client.get(f"/v1/parser-evaluations/{evaluated['id']}?mode=history").json()['golden_gate']['state'] == 'passed'
    with db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ParserEvaluationReview)) == 1


def test_valid_legacy_vehicle_is_not_exempted_from_human_golden_gate(setup):
    client, db, _, _ = setup
    from tire_api.adapters import xiaomi
    from test_vehicles import body
    raw = body()
    capture = seed_capture(client, db, body=raw, source=xiaomi.SOURCE_ID)
    bundle = client.post(f'/v1/parser-deployments/{xiaomi.SOURCE_ID}/bootstrap', json=SIGNED).json()['bundle_id']
    response = post(client, '/v1/parser-evaluations', {'mode': 'history', 'source_id': xiaomi.SOURCE_ID,
        'target_bundle_id': bundle, 'capture_ids': [capture], 'expected_deployment_revision': 1})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['state'] == 'completed' and result['golden_gate']['applicable']
    assert result['golden_gate']['state'] == 'unverified' and not result['can_approve']
    assert review(client, result, acknowledge_reference_gaps=True).status_code == 409


def test_reviewed_vehicle_structure_runs_without_claiming_sku_merge_coverage(setup):
    client, db, _, _ = setup
    from tire_api.adapters import xiaomi
    from test_golden import freeze_cases
    from test_vehicles import body
    raw = body()
    capture = seed_capture(client, db, body=raw, source=xiaomi.SOURCE_ID)
    parsed = xiaomi.parse_config(raw)  # Synthetic workflow scaffold, not a claimed manual ground truth.
    expected = {key: parsed[key] for key in ('vehicle', 'trims', 'fitments')}
    response = post(client, '/v1/golden/cases', {**case_payload(capture), 'kind': 'vehicle',
        'source_id': xiaomi.SOURCE_ID, 'expected': expected, 'title': 'Synthetic vehicle axle case'})
    assert response.status_code == 201, response.text
    frozen = freeze_cases(client, [sign_case(client, response.json())])
    bundle = client.post(f'/v1/parser-deployments/{xiaomi.SOURCE_ID}/bootstrap', json=SIGNED).json()['bundle_id']
    result = post(client, '/v1/parser-evaluations', {'mode': 'history', 'source_id': xiaomi.SOURCE_ID,
        'target_bundle_id': bundle, 'capture_ids': [capture], 'expected_deployment_revision': 1,
        **evaluation_reference(frozen)})
    assert result.status_code == 201, result.text
    result = result.json()
    assert result['golden_gate']['state'] == 'passed' and result['can_approve']
    assert result['golden_gate']['report']['wrong_merge_count'] is None
    assert review(client, result, acknowledge_reference_gaps=True).status_code == 201
