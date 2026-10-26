"""Fresh authenticated sessions cannot borrow another session's candidate preferences."""
from candidate_interpretation_support import candidate_case, interpret, request_body
from test_test_preference_routes import save_preference


def test_fresh_actor_requires_own_saved_preferences(candidate_case):
    case = candidate_case
    original = interpret(case)
    assert original.status_code == 200
    fresh = case.reviewer
    assert fresh.get('/v1/driving-preferences').json()['weights'] is None
    rejected = interpret(case, client=fresh)
    assert rejected.status_code == 409
    assert rejected.json()['detail']['code'] == 'test_candidate_preference_missing'
    assert rejected.headers['cache-control'] == 'no-store'
    preference = save_preference(fresh, weights=case.preference['weights'])
    payload = request_body(case, expected_preference_revision=preference['revision'],
                           expected_preference_fingerprint=preference['fingerprint'])
    own = interpret(case, payload=payload, client=fresh)
    assert own.status_code == 200
    assert own.json()['binding']['preference']['fingerprint'] == preference['fingerprint']
    assert own.json()['binding']['interpretation_fingerprint'] != original.json()['binding']['interpretation_fingerprint']
