"""Generate the shared filter oracle from the existing Python implementation only.

No database, network, parser or model is initialized. JSON string columns preserve
original numeric tokens; consumers must not re-encode them to verify fingerprints.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps' / 'api'))

from pydantic import ValidationError
from tire_api.domain import LiveQueryRequest
from tire_api.query_filters import FIELDS, _IDENTITY_FIELDS, _matches, _read, catalog, select_variants


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def valid_value(field):
    kind = FIELDS[field]['type']
    if kind == 'boolean':
        return True
    if kind == 'number':
        return 350
    return {'size': '245/40ZR20', 'load_index': '104/102', 'speed_rating': '(Y)',
            'technology_features': 'Acoustic'}.get(field, 'Reference Value')


def row(field, value, label='known', *, conflict=None):
    result = {'id': label, 'facts': {}}
    target = result if field in _IDENTITY_FIELDS or field == 'variant_id' else result['facts']
    key = 'id' if field == 'variant_id' else field
    target[key] = deepcopy(value)
    if conflict is not None:
        result['facts']['source_field_conflicts'] = conflict
    return result


def build_reference():
    cases = []

    def add(identifier, filters, rows):
        case = {'id': identifier, 'input_filters': deepcopy(filters), 'rows': deepcopy(rows),
                'input_filters_json': encoded(filters), 'rows_json': encoded(rows)}
        try:
            request = LiveQueryRequest.model_validate({'query': {'model': 'Reference'}, 'filters': filters})
        except ValidationError as error:
            case.update(canonical_filters=None, canonical_filters_json=None,
                        validation_error=[{'type': item['type'], 'loc': list(item['loc'])}
                                          for item in error.errors(include_url=False)], expected=None)
        else:
            canonical = [condition.canonical() for condition in request.filters]
            selected, selection = select_variants(rows, canonical)
            per_row = []
            for index, item in enumerate(rows):
                conditions = []
                for condition in canonical:
                    status, value = _read(item, condition['field'])
                    conditions.append({'status': status, 'value': value, 'value_json': encoded(value),
                                       'matched': _matches(item, condition)})
                per_row.append({'row_index': index, 'id': item.get('id'), 'conditions': conditions})
            expected = {'matched_ids': [item.get('id') for item in selected],
                        'matched_row_indexes': [index for index, item in enumerate(rows)
                                                if any(item is found for found in selected)],
                        'selection': selection, 'per_row': per_row}
            case.update(canonical_filters=canonical, canonical_filters_json=encoded(canonical),
                        validation_error=None, expected=expected, expected_json=encoded(expected))
        cases.append(case)

    for field, metadata in FIELDS.items():
        value = valid_value(field)
        actual = [value, 'ÉCHO'] if field == 'technology_features' else value
        invalid = 1 if metadata['type'] == 'boolean' else '350' if metadata['type'] == 'number' else {'invalid': True}
        samples = [row(field, actual), row(field, None, 'unknown'), row(field, invalid, 'invalid'),
                   row(field, actual, 'conflict', conflict=[{'field': field}])]
        for op in metadata['operators']:
            condition = {'field': field, 'op': op}
            if op not in {'is_known', 'is_unknown'}:
                condition['value'] = value
            add(field + ':' + op, [condition], samples)
        add(field + ':invalid-filter-type', [{'field': field, 'op': 'eq', 'value': {'unit': value}}], samples)
        for prefix in ('facts.', 'identity.'):
            add(field + ':conflict:' + prefix, [{'field': field, 'op': 'is_unknown'}],
                [row(field, actual, conflict=[{'field': prefix + field}])])

    for field in ('xl', 'hl', 'run_flat', 'acoustic_foam', 'ev_marketing_mark'):
        add(field + ':false-is-known', [{'field': field, 'op': 'eq', 'value': False}],
            [row(field, False), row(field, None, 'unknown'), row(field, 0, 'numeric-zero'),
             row(field, 'false', 'text-false')])
    for value in (0, -0.0, 5e-324, 1.25e-100, 1.5e20, 1e308, 9007199254740993,
                  -9007199254740993, 1.0000000000000002, -1.5e-10):
        for op in ('eq', 'gte', 'lte'):
            add('numeric:' + encoded(value) + ':' + op,
                [{'field': 'utqg_treadwear', 'op': op, 'value': value}],
                [row('utqg_treadwear', value), row('utqg_treadwear', 0, 'zero'),
                 row('utqg_treadwear', 9007199254740992, 'exact-int'),
                 row('utqg_treadwear', float(9007199254740993), 'rounded-float')])

    text_pairs = [('Straße', 'STRASSE'), ('Σ', 'ς'), ('İ', 'i\u0307'), ('ı', 'I'),
                  ('ﬃ', 'FFI'), ('Ｆｏａｍ', 'foam'), ('\u13a0', '\uab70'),
                  ('ÉCHO', 'écho'), ('  A\u2003B\u00a0C  ', 'a b c')]
    for index, (actual, expected) in enumerate(text_pairs):
        add('unicode:' + str(index), [{'field': 'brand', 'op': 'eq', 'value': expected}],
            [row('brand', actual), row('brand', expected, 'canonical')])
    for codepoint in (0, 0x1F, 0x7F, 0x200B, 0x200D, 0xE000, 0x378):
        value = 'A' + chr(codepoint) + 'B'
        add('category-c-filter:' + str(codepoint), [{'field': 'brand', 'op': 'eq', 'value': value}], [])
        add('category-c-row:' + str(codepoint), [{'field': 'brand', 'op': 'is_known'}], [row('brand', value)])
    add('size:R-ZR', [{'field': 'size', 'op': 'eq', 'value': '245 / 40 zr 20'}],
        [row('size', '245/40ZR20'), row('size', '245/40R20', 'R')])
    add('unknown-technical', [{'field': 'season', 'op': 'is_unknown'}],
        [row('season', ' unknown '), row('season', 'UNSPECIFIED', 'unspecified'), row('season', 'summer', 'known')])
    add('unknown-code-not-technical', [{'field': 'manufacturer_product_code', 'op': 'is_known'}],
        [row('manufacturer_product_code', 'unknown')])
    add('technology-list', [{'field': 'technology_features', 'op': 'eq', 'value': 'écho'}],
        [row('technology_features', ['Acoustic', 'ÉCHO']), row('technology_features', [], 'empty'),
         row('technology_features', [None], 'invalid'), row('technology_features', 'ÉCHO', 'scalar')])
    add('AND:false-over-unknown', [{'field': 'brand', 'op': 'eq', 'value': 'yes'},
                                  {'field': 'utqg_treadwear', 'op': 'gte', 'value': 300}],
        [{'id': 'excluded', 'brand': 'no', 'facts': {}}, {'id': 'undetermined', 'brand': 'yes', 'facts': {}},
         {'id': 'matched', 'brand': 'yes', 'facts': {'utqg_treadwear': 300}},
         {'id': 'zero-excluded', 'brand': 'yes', 'facts': {'utqg_treadwear': 0}}])
    add('malformed-facts', [{'field': 'brand', 'op': 'is_unknown'}],
        [{'id': 'bad-facts', 'brand': 'value', 'facts': []},
         {'id': 'bad-conflicts', 'brand': 'value', 'facts': {'source_field_conflicts': {}}}])
    same = {'field': 'brand', 'op': 'eq', 'value': ' YES '}
    add('16-duplicate-bound', [same] * 16, [row('brand', 'yes')])
    add('17-duplicate-bound', [same] * 17, [row('brand', 'yes')])
    add('stable-dedupe-sort', [{'field': 'brand', 'op': 'eq', 'value': 'Σ'}, same,
                             {'field': 'brand', 'op': 'eq', 'value': 'yes'}], [row('brand', 'yes')])
    add('presence-value-forbidden', [{'field': 'brand', 'op': 'is_known', 'value': None}], [])
    add('unknown-field', [{'field': 'not_registered', 'op': 'eq', 'value': 'x'}], [])
    add('operator-invalid-for-text', [{'field': 'brand', 'op': 'gte', 'value': 'x'}], [])
    source = ROOT / 'apps/api/tire_api/query_filters.py'
    return {'schema': 'tire-query-filter-reference@1', 'catalog': catalog(),
            'metadata': {'python_version': platform.python_version(), 'unicode_version': unicodedata.unidata_version,
                         'source': 'apps/api/tire_api/query_filters.py',
                         'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                         'canonical_sort': 'json.dumps(sort_keys=True, ensure_ascii=False, allow_nan=False)',
                         'number_policy': 'Python exact integers and finite binary64 floats; preserve JSON token string columns',
                         'fingerprint_policy': 'Never verify a Python fingerprint by host JSON re-encoding'},
            'cases': cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'apps/api/tests/data/query-filters49.json')
    args = parser.parse_args()
    payload = (json.dumps(build_reference(), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    fixture = json.loads(payload)
    print(json.dumps({'path': str(args.output), 'cases': len(fixture['cases']),
                      'fields': len(fixture['catalog']['fields']), 'sha256': hashlib.sha256(payload).hexdigest()}))


if __name__ == '__main__':
    main()
