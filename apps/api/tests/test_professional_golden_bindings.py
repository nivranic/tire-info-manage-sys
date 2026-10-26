"""Independent scope/reference mutations of explicitly supplied R76 HTTP bytes.

The shared fixtures only load the pinned oracle and one explicit observed set.
No application/database import or product projection constructs expected values.
"""
from copy import deepcopy
import hashlib
import json

from tire_api import professional_golden_checks as checks
from test_professional_golden_review import frozen_cases, observed_set  # noqa: F401


def _sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _pair(observed_set):
    cases, actuals = observed_set
    return deepcopy(cases['synthetic-exact-two']), deepcopy(actuals['synthetic-exact-two'])


def _reject(case, actual):
    result = checks.evaluate_case(case, actual)
    if hasattr(result, 'model_dump'):
        result = result.model_dump(mode='json', by_alias=True)
    assert result['state'] == 'failed', result
    assert result['failure_count'] >= 1


def test_preview_current_binding_cannot_reference_another_event(observed_set):
    case, actual = _pair(observed_set)
    observation = actual['bridge_results'][0]['preview']
    assert observation['http_status'] == 200
    body = observation['response_body']
    body['binding']['test']['event_id'] += '-another-event'
    body['binding_hash'] = _sha(body['binding'])
    observation['response_sha256'] = _sha(body)
    _reject(case, actual)


def test_preview_current_identity_binding_cannot_replace_the_exact_sku(observed_set):
    case, actual = _pair(observed_set)
    observation = actual['bridge_results'][0]['preview']
    assert observation['http_status'] == 200
    body = observation['response_body']
    body['binding']['identity_contract']['identity']['brand'] += '-another-brand'
    body['binding_hash'] = _sha(body['binding'])
    observation['response_sha256'] = _sha(body)
    _reject(case, actual)


def test_decision_link_id_must_match_its_revision_chain(observed_set):
    case, actual = _pair(observed_set)
    observation = actual['bridge_results'][0]['decisions'][0]
    assert observation['http_status'] == 201
    assert observation['request_body']['action'] == 'create'
    observation['response_body']['link']['id'] += '-another-link'
    observation['response_sha256'] = _sha(observation['response_body'])
    _reject(case, actual)


def test_decision_summary_must_reference_its_response_link_revision(observed_set):
    case, actual = _pair(observed_set)
    observation = actual['bridge_results'][0]['decisions'][0]
    assert observation['http_status'] == 201
    observation['response_body']['event']['revision_id'] += '-another-revision'
    observation['response_sha256'] = _sha(observation['response_body'])
    _reject(case, actual)


def test_captured_event_state_cannot_contradict_active_bridges(observed_set):
    case, actual = _pair(observed_set)
    assert actual['event_snapshot']['state'] == 'active'
    # event_snapshot has no independent HTTP observation/hash envelope.
    actual['event_snapshot']['state'] = 'revoked'
    _reject(case, actual)


def test_captured_event_scope_remains_local_workspace(observed_set):
    case, actual = _pair(observed_set)
    assert actual['event_snapshot']['scope'] == 'local_workspace'
    actual['event_snapshot']['scope'] = 'public'
    _reject(case, actual)


def test_exact_bridge_cannot_erase_all_assertion_checks(observed_set):
    case, actual = _pair(observed_set)
    observation = actual['bridge_results'][0]['preview']
    assert observation['response_body']['checks']
    observation['response_body']['checks'] = []
    observation['response_sha256'] = _sha(observation['response_body'])
    _reject(case, actual)


def test_exact_bridge_cannot_relabel_a_matched_assertion_as_conflicting(observed_set):
    case, actual = _pair(observed_set)
    observation = actual['bridge_results'][0]['preview']
    check = next(row for row in observation['response_body']['checks'] if row['status'] == 'match')
    check['status'] = 'conflict'
    observation['response_sha256'] = _sha(observation['response_body'])
    _reject(case, actual)


def test_exact_bridge_requires_the_captured_complete_identity_status(observed_set):
    case, actual = _pair(observed_set)
    observation = actual['bridge_results'][0]['preview']
    tire = observation['response_body']['frozen_evidence']['tire']
    assert tire['identity_status'] == 'complete'
    tire['identity_status'] = 'source_scoped'
    observation['response_sha256'] = _sha(observation['response_body'])
    _reject(case, actual)


def test_exact_bridge_cannot_claim_an_unknown_identity_contract_version(observed_set):
    case, actual = _pair(observed_set)
    observation = actual['bridge_results'][0]['preview']
    tire = observation['response_body']['frozen_evidence']['tire']
    assert tire['identity_contract_version'] == 'variant-identity@2'
    tire['identity_contract_version'] = 'variant-identity@unknown'
    observation['response_sha256'] = _sha(observation['response_body'])
    _reject(case, actual)
