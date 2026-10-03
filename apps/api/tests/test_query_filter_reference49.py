"""Keep the shared host oracle bound to the original pure Python semantics."""
import importlib.util
import json
from pathlib import Path


def generator():
    path = Path(__file__).resolve().parents[3] / 'scripts/generate_query_filter_reference49.py'
    spec = importlib.util.spec_from_file_location('query_filter_reference49', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_reference_is_reproducible_and_covers_all_existing_fields():
    saved = json.loads((Path(__file__).parent / 'data/query-filters49.json').read_text(encoding='utf-8'))
    assert generator().build_reference() == saved
    assert len(saved['catalog']['fields']) == 28
    assert saved['catalog']['max_conditions'] == 16
    names = {case['id'] for case in saved['cases']}
    for field in saved['catalog']['fields']:
        for operator in field['operators']:
            assert field['key'] + ':' + operator in names


def test_reference_retains_numeric_tokens_and_false_over_unknown_boundary():
    saved = generator().build_reference()
    cases = {case['id']: case for case in saved['cases']}
    assert '-0.0' in cases['numeric:-0.0:eq']['input_filters_json']
    huge = cases['numeric:1e+308:eq']
    assert '1e+308' in huge['input_filters_json'] and '1e+308' not in huge['canonical_filters_json']
    assert len(str(huge['canonical_filters'][0]['value'])) == 309
    assert cases['16-duplicate-bound']['validation_error'] is None
    assert cases['17-duplicate-bound']['validation_error'] is not None
    selection = cases['AND:false-over-unknown']['expected']['selection']
    assert (selection['matched_count'], selection['excluded_count'], selection['undetermined_count']) == (1, 2, 1)


def test_supplement_is_reproducible_without_rewriting_primary(monkeypatch):
    path = Path(__file__).resolve().parents[3] / 'scripts/generate_query_filter_reference49_extra.py'
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location('query_filter_reference49_extra', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    saved = json.loads((Path(__file__).parent / 'data/query-filters49-extra.json').read_text(encoding='utf-8'))
    assert module.build_reference() == saved
    assert len(saved['cases']) == 14
