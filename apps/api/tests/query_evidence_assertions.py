"""Frozen source evidence remains exact while response verification metadata advances."""
from copy import deepcopy
from datetime import datetime

from tire_api.domain import digest


def assert_frozen_query_evidence(original, current, *, expected_state, reverified=False):
    assert original['data_state'] == 'live'
    assert current['data_state'] == expected_state
    assert current['provenance'] == original['provenance']
    assert current['snapshot_observed_at'] == original['snapshot_observed_at']
    if reverified:
        assert datetime.fromisoformat(current['verified_at']) > datetime.fromisoformat(original['verified_at'])
    else:
        assert current['verified_at'] == original['verified_at']
    assert len(current['variants']) == len(original['variants']) > 0
    for before, after in zip(original['variants'], current['variants'], strict=True):
        # All source facts, identity fields and proof references retain their full shape.
        assert {key: value for key, value in after.items() if key != 'field_resolution'} == {
            key: value for key, value in before.items() if key != 'field_resolution'}
        prior = before['field_resolution']
        actual = after['field_resolution']
        for resolution, state in ((prior, original['data_state']), (actual, expected_state)):
            assert resolution['data_state'] == state
            assert resolution['fingerprint'] == digest({
                key: value for key, value in resolution.items() if key != 'fingerprint'})
        expected = deepcopy(prior)
        expected['data_state'] = expected_state
        if reverified:
            for field in expected['fields']:
                for candidate in field['candidates']:
                    candidate['verified_at'] = current['verified_at']
                    candidate['dimensions']['time']['verified_at'] = current['verified_at']
        expected['fingerprint'] = digest({key: value for key, value in expected.items() if key != 'fingerprint'})
        # Comparing the whole resolution also freezes candidate IDs, source proofs,
        # locators, content time, defaults, exclusions and authority decisions.
        assert actual == expected
        if reverified or expected_state != original['data_state']:
            assert actual['fingerprint'] != prior['fingerprint']
