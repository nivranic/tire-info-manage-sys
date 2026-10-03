"""Deterministic assertions against explicitly reviewed expectations, never a truth generator."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from .domain import VariantInput, digest, stable_json

CONTRACT_VERSION = 'golden-exact@1'
# Candidate normalization and the surrounding release-quality rules run in the
# current host, outside the sealed parser. Bind them too, so an old report
# cannot authorize a release under changed validation semantics.
CONTRACT_FILES = ('golden_checks.py', 'domain.py', 'reparse.py', 'service.py', 'vehicles.py',
                  'quality.py', 'vehicle_quality.py', 'golden.py', 'parser_releases.py')
MAX_EXPECTED_BYTES = 512_000
MAX_RECORDS = 300
MAX_DIFFS = 100
_MISSING = object()
_METADATA = frozenset({'evidence_spans', 'evidence_locator'})


def contract_descriptor() -> dict:
    directory = Path(__file__).resolve().parent
    return {'version': CONTRACT_VERSION, 'digest': digest({
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in CONTRACT_FILES})}


def _json_tree(value, depth=0):
    if depth > 24:
        raise ValueError('Golden JSON nesting exceeds the supported bound')
    if value is None or type(value) in {bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('Golden JSON numbers must be finite')
        return
    if type(value) is str:
        if '\x00' in value:
            raise ValueError('Golden JSON cannot contain null characters')
        value.encode('utf-8', errors='strict')
        return
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError('Golden JSON object keys must be strings')
        for key, child in value.items():
            _json_tree(key, depth + 1)
            _json_tree(child, depth + 1)
        return
    if type(value) is list:
        for child in value:
            _json_tree(child, depth + 1)
        return
    raise ValueError('Golden expectations must contain JSON values only')


def _without_locators(value):
    if isinstance(value, dict):
        return {key: _without_locators(child) for key, child in value.items() if key not in _METADATA}
    if isinstance(value, list):
        return [_without_locators(child) for child in value]
    return value


def _tire_value(value, *, expected=False):
    if expected and (type(value) is not dict or set(value) != set(VariantInput.model_fields)):
        raise ValueError('Each Golden tire must explicitly include every VariantInput field; use null for unknown')
    model = VariantInput.model_validate(value)
    result = _without_locators(model.model_dump())
    features = result['facts'].get('technology_features')
    if isinstance(features, list):
        result['facts']['technology_features'] = sorted(features, key=stable_json)
    return result


def _tire_identity(value):
    identity = VariantInput.model_validate(value).identity()
    # Domain v2 maps missing/null namespaces to the same unknown category, while
    # Golden assertions retain the original JSON field-presence claim.
    identity['_golden_product_code_type_present'] = 'product_code_type' in value['facts']
    if 'product_code_type' in value['facts']:
        identity['product_code_type'] = value['facts']['product_code_type']
    if not value['manufacturer_product_code']:
        identity['source_variant_name'] = value['source_variant_name']
    return stable_json(identity)


def _vehicle_value(value):
    if type(value) is not dict or set(value) != {'vehicle', 'trims', 'fitments'}:
        raise ValueError('Golden vehicle requires the complete vehicle, trims and fitments structure')
    vehicle = value['vehicle']
    if type(vehicle) is not dict or not {'id', 'manufacturer', 'model', 'generation', 'model_year', 'region'} <= set(vehicle):
        raise ValueError('Golden vehicle must explicitly identify generation, year and market')
    if (any(type(vehicle[key]) is not str or not vehicle[key].strip()
            for key in ('id', 'model', 'generation', 'region'))
            or (vehicle['model_year'] is not None and type(vehicle['model_year']) is not int)):
        raise ValueError('Golden vehicle scope values must have explicit valid types')
    manufacturer = vehicle['manufacturer']
    if (type(manufacturer) is not dict or not {'id', 'name'} <= set(manufacturer)
            or any(type(manufacturer[key]) is not str or not manufacturer[key].strip() for key in ('id', 'name'))):
        raise ValueError('Golden vehicle must explicitly identify its manufacturer')
    result = _without_locators(deepcopy(value))
    for group in ('trims', 'fitments'):
        rows = result[group]
        if type(rows) is not list or not 1 <= len(rows) <= MAX_RECORDS:
            raise ValueError('Golden vehicle groups must be nonempty and bounded')
        ids = [row.get('id') if type(row) is dict else None for row in rows]
        if any(type(key) is not str or not key.strip() or len(key) > 160 for key in ids) or len(set(ids)) != len(ids):
            raise ValueError('Golden vehicle record IDs must be unique and explicit')
        result[group] = sorted(rows, key=lambda row: row['id'])
    for trim in result['trims']:
        references = trim.get('wheel_option_ids')
        if (type(references) is not list or not references
                or any(type(key) is not str or not key.strip() for key in references)
                or len(set(references)) != len(references)):
            raise ValueError('Golden trim wheel references must be unique and explicit')
        if set(references) != {row['id'] for row in result['fitments'] if row.get('trim_id') == trim['id']}:
            raise ValueError('Golden trim wheel references must cover exactly its fitments')
        trim['wheel_option_ids'] = sorted(references)
    trims = {row['id'] for row in result['trims']}
    for row in result['fitments']:
        if row.get('trim_id') not in trims or not {'front', 'rear', 'availability', 'wheel_diameter_inches'} <= set(row):
            raise ValueError('Golden fitment must identify its trim, wheel, availability and both axles')
        if any(type(row[axis]) is not dict or 'size' not in row[axis] for axis in ('front', 'rear')):
            raise ValueError('Golden fitment axes must have explicit sizes')
    return result


def validate_expected(kind: str, expected) -> dict:
    """Validate/canonicalize user assertions; never derive them from actual output."""
    _json_tree(expected)
    if len(stable_json(expected).encode('utf-8')) > MAX_EXPECTED_BYTES:
        raise ValueError('Golden expectation exceeds the supported size')
    if kind == 'tire':
        if type(expected) is not dict or set(expected) != {'records'}:
            raise ValueError('Golden tire expectations require records')
        rows = expected['records']
        if type(rows) is not list or not 1 <= len(rows) <= MAX_RECORDS:
            raise ValueError('Golden tire records must be nonempty and bounded')
        normalized, identities, groups = [], set(), set()
        for row in rows:
            if type(row) is not dict or set(row) != {'golden_sku_id', 'value'}:
                raise ValueError('Each record needs golden_sku_id and value')
            group = row['golden_sku_id']
            if type(group) is not str or not group.strip() or group != group.strip() or len(group) > 100:
                raise ValueError('Golden SKU IDs must be explicit nonblank labels')
            value = _tire_value(row['value'], expected=True)
            identity = _tire_identity(value)
            if identity in identities or group in groups:
                raise ValueError('One captured result must contain uniquely identifiable distinct Golden SKUs')
            identities.add(identity)
            groups.add(group)
            normalized.append({'golden_sku_id': group, 'value': value})
        return {'records': normalized}
    if kind == 'vehicle':
        return _vehicle_value(expected)
    raise ValueError('Golden Parser expectations currently support tire and vehicle only')


def _display(value):
    if value is _MISSING:
        return {'present': False}
    text = stable_json(value)
    if len(text) <= 1000:
        return {'present': True, 'value': value}
    return {'present': True, 'preview': text[:1000], 'truncated': True, 'sha256': digest(value)}


class _Differences:
    def __init__(self):
        self.items, self.count = [], 0

    def add(self, code, path, expected=_MISSING, actual=_MISSING):
        self.count += 1
        if len(self.items) < MAX_DIFFS:
            self.items.append({'code': code, 'path': path,
                'expected': _display(expected), 'actual': _display(actual)})

    def compare(self, expected, actual, path):
        if type(expected) is dict and type(actual) is dict:
            for key in sorted(set(expected) | set(actual)):
                self.compare(expected.get(key, _MISSING), actual.get(key, _MISSING), f'{path}/{key}')
        elif type(expected) is list and type(actual) is list:
            for index in range(max(len(expected), len(actual))):
                self.compare(expected[index] if index < len(expected) else _MISSING,
                             actual[index] if index < len(actual) else _MISSING, f'{path}/{index}')
        elif expected is _MISSING or actual is _MISSING:
            if expected is not actual:
                self.add('golden_field_presence_mismatch', path, expected, actual)
        elif type(expected) in {int, float} and type(actual) in {int, float}:
            # JSON has one numeric type. Browser JSON.stringify serializes 19.0
            # as 19; compare its value without equating booleans or strings.
            if expected != actual:
                self.add('golden_value_mismatch', path, expected, actual)
        elif type(expected) is not type(actual) or expected != actual:
            self.add('golden_value_mismatch', path, expected, actual)


def compare_case(kind: str, expected, actual, source_input: dict) -> dict:
    expected = validate_expected(kind, expected)
    differences = _Differences()
    bindings = []
    case_id = source_input.get('case_id') or source_input.get('capture_id')
    result = {'kind': kind, 'case_id': case_id, 'contract': contract_descriptor(),
        'scope': 'exact_case_fields', 'state': 'failed', 'identity_bindings': bindings}
    if kind == 'tire':
        expected_rows = expected['records']
        actual_rows, indexes = [], defaultdict(list)
        if type(actual) is not list or not 1 <= len(actual) <= MAX_RECORDS:
            differences.add('golden_actual_records_invalid', '/records', len(expected_rows), None)
        else:
            for index, row in enumerate(actual):
                try:
                    _json_tree(row)
                    value = _tire_value(row)
                    indexes[_tire_identity(value)].append(index)
                    actual_rows.append(value)
                except (ValueError, TypeError, KeyError, RecursionError):
                    actual_rows.append(None)
                    differences.add('golden_actual_record_invalid', f'/records/{index}')
        used = set()
        for index, row in enumerate(expected_rows):
            matches = indexes.get(_tire_identity(row['value']), [])
            binding = {'case_id': case_id, 'record_index': index, 'golden_sku_id': row['golden_sku_id'],
                'actual_index': None, 'identity_key': None, 'expected_identity': _tire_identity(row['value'])}
            bindings.append(binding)
            if len(matches) != 1:
                differences.add('golden_identity_missing' if not matches else 'golden_identity_ambiguous',
                    f'/records/{index}', row['value'], [actual_rows[item] for item in matches])
                continue
            actual_index = matches[0]
            used.add(actual_index)
            value = actual_rows[actual_index]
            binding['actual_index'] = actual_index
            differences.compare(row['value'], value, f'/records/{index}/value')
            source, query = source_input.get('source_id'), source_input.get('query_key')
            if type(source) is not str or not source or type(query) is not str or not query:
                differences.add('golden_identity_scope_missing', f'/records/{index}')
                continue
            binding['identity_key'], binding['identity_scope'] = VariantInput.model_validate(value).identity_key(
                source, query, actual_index)
        for index, row in enumerate(actual_rows):
            if index not in used and row is not None:
                differences.add('golden_unexpected_identity', f'/actual_records/{index}', actual=row)
        result.update(expected_records=len(expected_rows), actual_records=len(actual) if isinstance(actual, list) else None,
            matched_records=len(used))
    else:
        try:
            _json_tree(actual)
            # Coverage flags, document links and footnotes remain in the saved
            # candidate; this contract asserts the three core vehicle groups.
            if type(actual) is not dict:
                raise ValueError('Golden actual vehicle must be an object')
            normalized_actual = _vehicle_value({key: actual[key] for key in ('vehicle', 'trims', 'fitments')})
            if source_input.get('query', {}).get('vehicle_id') != expected['vehicle']['id']:
                differences.add('golden_vehicle_scope_mismatch', '/vehicle/id')
            differences.compare(expected['vehicle'], normalized_actual['vehicle'], '/vehicle')
            for group in ('trims', 'fitments'):
                previous = {row['id']: row for row in expected[group]}
                current = {row['id']: row for row in normalized_actual[group]}
                differences.compare(previous, current, '/' + group)
            result.update(expected_records=len(expected['fitments']), actual_records=len(actual['fitments']))
        except (ValueError, TypeError, KeyError, RecursionError):
            differences.add('golden_actual_vehicle_invalid', '/')
            result.update(expected_records=len(expected['fitments']), actual_records=None)
    pairs, checked, wrong = _distinct_counts(bindings)
    if wrong:
        differences.add('golden_wrong_merge', '/records', 0, wrong)
    result.update(state='failed' if differences.count else 'passed', failures=differences.items,
        failure_count=differences.count, failures_truncated=differences.count > len(differences.items))
    result.update(expected_distinct_pairs=pairs, checked_distinct_pairs=checked,
                  wrong_merge_count=wrong if pairs and pairs == checked else None)
    return result


def _distinct_counts(bindings):
    expected = checked = wrong = 0
    for index, left in enumerate(bindings):
        for right in bindings[index + 1:]:
            if left['golden_sku_id'] == right['golden_sku_id']:
                continue
            expected += 1
            if left['identity_key'] is not None and right['identity_key'] is not None:
                checked += 1
                if left['identity_key'] == right['identity_key']:
                    wrong += 1
    return expected, checked, wrong


def aggregate_reports(reports: list, *, expected_case_count: int) -> dict:
    """All frozen members must be represented; unknown cannot produce a zero-error gate."""
    failures, bindings = [], []
    descriptor = contract_descriptor()
    if (type(expected_case_count) is not int or not 1 <= expected_case_count <= 3
            or type(reports) is not list or len(reports) != expected_case_count):
        failures.append('golden_case_coverage_incomplete')
    valid = [row for row in reports if isinstance(row, dict)] if isinstance(reports, list) else []
    if len(valid) != expected_case_count:
        failures.append('golden_case_execution_incomplete')
    kinds, case_ids = set(), set()
    for report in valid:
        kinds.add(report.get('kind'))
        case_id = report.get('case_id')
        if not case_id or case_id in case_ids:
            failures.append('golden_case_coverage_invalid')
        case_ids.add(case_id)
        if report.get('contract') != descriptor:
            failures.append('golden_comparison_contract_changed')
        if report.get('state') != 'passed' or report.get('failure_count') != 0:
            failures.append('golden_case_failed')
        bindings.extend(report.get('identity_bindings', []))
    group_identities = defaultdict(set)
    for binding in bindings:
        group_identities[binding['golden_sku_id']].add(binding.get('expected_identity'))
    if any(None in identities or len(identities) != 1 for identities in group_identities.values()):
        failures.append('golden_sku_label_conflict')
    if len(kinds) != 1 or not kinds <= {'tire', 'vehicle'}:
        failures.append('golden_case_kind_mismatch')
    pairs, checked, wrong = _distinct_counts(bindings)
    kind = next(iter(kinds)) if len(kinds) == 1 else None
    if kind == 'tire' and checked != pairs:
        failures.append('golden_distinct_coverage_incomplete')
    if wrong:
        failures.append('golden_wrong_merge')
    state = 'failed' if failures else 'inconclusive' if kind == 'tire' and pairs == 0 else 'passed'
    if state == 'inconclusive':
        failures.append('golden_distinct_cases_required')
    return {'state': state, 'scope': 'golden_sku_identity_and_fields' if kind == 'tire' else 'vehicle_structure',
        'contract': descriptor, 'expected_case_count': expected_case_count, 'completed_case_count': len(valid),
        'expected_distinct_pairs': pairs, 'checked_distinct_pairs': checked,
        'wrong_merge_count': wrong if kind == 'tire' and pairs and pairs == checked else None,
        'failure_codes': sorted(set(failures)), 'case_ids': sorted(case_ids)}
