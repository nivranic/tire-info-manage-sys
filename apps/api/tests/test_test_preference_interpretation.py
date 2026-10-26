"""Pure numerical and evidence invariants, with no database or network."""
from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from tire_api.domain import digest
from tire_api.test_preference_interpretation import PreferenceInterpretationRequest, interpret_test_preferences


def snapshot():
    payload = {
        'title': 'Synthetic selected observations', 'organization': 'Fixture Lab',
        'relationship': 'manufacturer_commissioned', 'publication_date': '2026-09-01',
        'source_url': 'https://fixture.example/test', 'rights_basis': 'Project-authored synthetic data',
        'tested_size': '225/50R17', 'vehicle': None, 'surface': None, 'conditions': 'Synthetic only',
        'coverage': 'selected_results', 'reported_participants': 12,
        'participants': [{'key': key, 'brand': key.upper(), 'model': 'Fixture', 'source_designation': ''}
                         for key in ('b', 'a', 'c')],
        'metrics': [
            {'key': 'wet', 'label': 'Wet braking', 'unit': 'm', 'protocol': 'Fixture wet method', 'direction': 'lower'},
            {'key': 'dry', 'label': 'Dry traction', 'unit': 'points', 'protocol': 'Fixture dry method', 'direction': 'higher'},
            {'key': 'noise', 'label': '<script>fixture only</script>', 'unit': 'dB', 'protocol': 'Fixture noise', 'direction': 'unspecified'},
        ],
        'measurements': [
            {'participant_key': p, 'metric_key': metric, 'raw_value': raw, 'source_rank': rank,
             'evidence_span': f'{p}: {raw}', 'evidence_locator': f'Synthetic {metric} row {p}'}
            for p, metric, raw, rank in [('a', 'wet', '38.00', 3), ('b', 'wet', '40.0', 5),
                                        ('a', 'dry', '-0', None), ('b', 'dry', '0', 8),
                                        ('c', 'dry', '1.000', 4), ('a', 'noise', '70', None)]
        ],
    }
    event = {'id': 'event-1', 'revision_id': 'revision-1', 'revision': 1,
             'fingerprint': digest(payload), 'recorded_at': '2026-10-18T00:00:00Z', 'event': payload}
    weights = {'dry': 30, 'wet': 40, 'quiet': 20, 'comfort': 5, 'wear': 5, 'energy': 0, 'appearance': 0}
    preference = {'revision': 9, 'weights': weights,
                  'fingerprint': digest({'schema': 'driving-preference-state@1', 'revision': 9, 'weights': weights})}
    return event, preference


def request(event, preference, **changes):
    return PreferenceInterpretationRequest.model_validate({
        'expected_event_revision': event['revision'], 'expected_event_fingerprint': event['fingerprint'],
        'expected_preference_revision': preference['revision'],
        'expected_preference_fingerprint': preference['fingerprint'],
        'participant_ids': [f'{event["id"]}:{p["key"]}' for p in event['event']['participants']],
        'metric_dimensions': [{'metric_key': 'wet', 'dimension': 'wet'},
                              {'metric_key': 'dry', 'dimension': 'dry'},
                              {'metric_key': 'noise', 'dimension': 'quiet'}], **changes,
    })


def calculate(**changes):
    event, preference = snapshot()
    return interpret_test_preferences(event, preference, request(event, preference, **changes))


def test_original_evidence_is_complete_preserved_and_unmodified():
    event, preference = snapshot()
    original = deepcopy((event, preference))
    result = interpret_test_preferences(event, preference, request(event, preference))
    source = result['source_evidence']
    assert result['scope'] == 'actor' and result['evidence_scope'] == 'local_workspace'
    assert source['event'] == {k: v for k, v in event['event'].items() if k not in {'participants', 'metrics', 'measurements'}}
    assert source['metrics'] == event['event']['metrics']
    assert [p['key'] for p in source['participants']] == ['b', 'a', 'c']
    assert all(p['identity_status'] == 'participant_only' for p in source['participants'])
    fields = set(event['event']['measurements'][0])
    assert [{k: m[k] for k in fields} for m in source['measurements']] == event['event']['measurements']
    assert source['recorded_participant_count'] == source['selected_participant_count'] == 3
    assert (event, preference) == original
    # The response must not retain mutable references into persisted snapshots.
    source['metrics'][0]['label'] = 'changed response'
    result['personal_interpretation']['weights']['wet'] = 0
    assert (event, preference) == original


def test_missing_unknown_direction_and_null_rank_have_independent_meanings():
    result = calculate()
    wet, dry, noise = result['personal_interpretation']['metrics']
    assert wet['observed_participant_ids'] == ['event-1:b', 'event-1:a']
    assert wet['missing_participant_ids'] == ['event-1:c']
    assert wet['observation_comparison']['favorable_participant_ids'] == ['event-1:a']
    assert wet['limitations'] == ['missing_measurements'] and not wet['complete_comparable']
    assert dry['complete_comparable'] and dry['observation_comparison']['favorable_participant_ids'] == ['event-1:c']
    assert noise['limitations'] == ['missing_measurements', 'direction_unspecified', 'insufficient_observations']
    assert noise['observation_comparison'] is None
    assert 'event-1:a' in dry['observed_participant_ids']  # rank null still has real -0.
    assert result['personal_interpretation']['coverage'] == {
        'mapped_weight': 90, 'fully_comparable_weight': 30, 'unmapped_weight': 10,
        'mapped_not_fully_comparable_weight': 60,
    }


def test_decimal_precision_is_not_float_and_all_signed_zero_ties_are_preserved():
    event, preference = snapshot()
    values = event['event']['measurements']
    values[0]['raw_value'] = '999999999999.12345678'
    values[1]['raw_value'] = '999999999999.12345677'
    # Above differ below a double's precision, so lower must select only b.
    result = interpret_test_preferences(event, preference, request(event, preference, participant_ids=['event-1:a', 'event-1:b']))
    wet, dry, _ = result['personal_interpretation']['metrics']
    assert wet['observation_comparison']['favorable_participant_ids'] == ['event-1:b']
    assert dry['observation_comparison']['favorable_participant_ids'] == ['event-1:b', 'event-1:a']
    assert [m['raw_value'] for m in result['source_evidence']['measurements'] if m['metric_key'] == 'dry'] == ['-0', '0']


def test_weight_is_counted_once_and_zero_weight_keeps_evidence():
    result = calculate(metric_dimensions=[{'metric_key': key, 'dimension': dimension}
                                         for key, dimension in [('wet', 'wet'), ('dry', 'wet'), ('noise', 'energy')]])
    personal = result['personal_interpretation']
    assert personal['coverage'] == {'mapped_weight': 40, 'fully_comparable_weight': 40,
                                    'unmapped_weight': 60, 'mapped_not_fully_comparable_weight': 0}
    wet = next(d for d in personal['dimensions'] if d['dimension'] == 'wet')
    assert wet['metric_keys'] == ['wet', 'dry'] and wet['complete_comparable_metric_keys'] == ['dry']
    assert next(d for d in personal['dimensions'] if d['dimension'] == 'energy')['metric_keys'] == ['noise']
    assert len(result['source_evidence']['measurements']) == 6
    assert [d['dimension'] for d in personal['dimensions']] == ['wet', 'dry', 'quiet', 'comfort', 'wear', 'energy', 'appearance']


def test_all_null_is_valid_but_does_not_synthesize_personal_comparisons():
    result = calculate(metric_dimensions=[{'metric_key': k, 'dimension': None} for k in ('wet', 'dry', 'noise')])
    personal = result['personal_interpretation']
    assert personal['coverage'] == {'mapped_weight': 0, 'fully_comparable_weight': 0,
                                    'unmapped_weight': 100, 'mapped_not_fully_comparable_weight': 0}
    assert all(m['observation_comparison'] is None and not m['complete_comparable'] for m in personal['metrics'])
    assert all('excluded_by_user' in m['limitations'] for m in personal['metrics'])
    assert len(result['source_evidence']['measurements']) == 6


def test_no_observations_creates_no_evidence_and_no_extrema():
    event, preference = snapshot()
    # This is a valid event: a's noise result exists, but a is not selected.
    event['event']['metrics'][2]['direction'] = 'lower'
    event['fingerprint'] = digest(event['event'])
    result = interpret_test_preferences(event, preference, request(event, preference, participant_ids=['event-1:c', 'event-1:b']))
    noise = result['personal_interpretation']['metrics'][2]
    assert noise['observed_participant_ids'] == noise['evidence_ids'] == []
    assert noise['missing_participant_ids'] == ['event-1:b', 'event-1:c']
    assert noise['limitations'] == ['missing_measurements', 'insufficient_observations']
    assert noise['observation_comparison'] is None


def test_binding_is_order_invariant_and_evidence_is_independent_of_preferences():
    event, preference = snapshot()
    one = request(event, preference)
    reordered = request(event, preference, participant_ids=list(reversed(one.participant_ids)),
                        metric_dimensions=list(reversed([m.model_dump() for m in one.metric_dimensions])))
    original = interpret_test_preferences(event, preference, one)
    assert original == interpret_test_preferences(event, preference, reordered)
    changed = deepcopy(preference)
    changed['revision'] += 1
    changed['fingerprint'] = 'd' * 64
    revised = interpret_test_preferences(event, changed, request(event, changed))
    assert original['binding']['interpretation_fingerprint'] != revised['binding']['interpretation_fingerprint']
    assert original['source_evidence']['measurements'] == revised['source_evidence']['measurements']
    event['revision'] += 1
    event['revision_id'] = 'revision-2'
    other_revision = interpret_test_preferences(event, preference, request(event, preference))
    assert original['source_evidence']['measurements'][0]['evidence_id'] != other_revision['source_evidence']['measurements'][0]['evidence_id']
    first = original['source_evidence']['measurements'][0]
    assert first['reference'] == {'event_id': 'event-1', 'revision': 1, 'participant_id': 'event-1:a', 'metric_key': 'wet'}


@pytest.mark.parametrize('changes', [
    {'participant_ids': ['event-1:a', 'other-event:b']},
    {'participant_ids': ['event-1:a', 'event-1:a']},
    {'metric_dimensions': [{'metric_key': 'wet', 'dimension': 'wet'}]},
    {'metric_dimensions': [{'metric_key': key, 'dimension': 'wet'} for key in ('wet', 'wet', 'noise')]},
    {'metric_dimensions': [{'metric_key': key, 'dimension': 'wet'} for key in ('wet', 'dry', 'foreign')]},
])
def test_semantic_selection_is_closed(changes):
    with pytest.raises(HTTPException) as error:
        calculate(**changes)
    assert error.value.status_code == 422
    assert error.value.detail['code'] == 'invalid_preference_interpretation'


@pytest.mark.parametrize('changes', [
    {'expected_event_revision': True}, {'expected_preference_revision': 1.0},
    {'expected_event_fingerprint': 'A' * 64}, {'expected_event_fingerprint': 'a' * 64 + '\n'},
    {'actor': 'someone'}, {'weights': {'wet': 100}}, {'participant_ids': ['event-1:a']},
    {'metric_dimensions': [{'metric_key': 'wet'}]},
])
def test_shape_rejects_implicit_mapping_coercion_and_client_overrides(changes):
    event, preference = snapshot()
    with pytest.raises(ValidationError):
        request(event, preference, **changes)
