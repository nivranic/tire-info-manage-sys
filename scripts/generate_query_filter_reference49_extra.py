"""Supplement the immutable Round49 oracle with exact Unicode tire-size vectors."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from generate_query_filter_reference49 import ROOT, encoded
from pydantic import ValidationError
from tire_api.domain import LiveQueryRequest, TireQuery
from tire_api.query_filters import _matches, _read, catalog, select_variants


SIZES = ['٢٤٥/٤٠R20', '245/40R٢٠', '۲۴۵/۴۰ZR۲۰', '२४५/४०R२०',
         '２４５／４０Ｒ２０．５', '245/40R٢٠.5', '245/40R20.٥', '245/40R٢٠.٥',
         '245/40R２０.5', '𝟚𝟜𝟝/𝟜𝟘R𝟚𝟘', '245\u2003/40\u00a0R20',
         '245/40R20\u200b', '245/40R20.۵', '٢٤٥/٤٠R20.5']


def build_reference():
    primary_path = ROOT / 'apps/api/tests/data/query-filters49.json'
    primary = json.loads(primary_path.read_text(encoding='utf-8'))
    cases, query_sizes = [], []
    rows = [{'id': 'row:' + str(index), 'size': value, 'facts': {}}
            for index, value in enumerate(SIZES + ['245/40R20', '245/40ZR20', '245/40R20.5'])]
    for index, size in enumerate(SIZES):
        filters = [{'field': 'size', 'op': 'eq', 'value': size}]
        item = {'id': 'size-nd:' + str(index), 'input_filters': filters, 'rows': rows,
                'input_filters_json': encoded(filters), 'rows_json': encoded(rows)}
        try:
            request = LiveQueryRequest.model_validate({'query': {'model': 'Reference'}, 'filters': filters})
        except ValidationError as error:
            item.update(canonical_filters=None, canonical_filters_json=None,
                        validation_error=[{'type': part['type'], 'loc': list(part['loc'])}
                                          for part in error.errors(include_url=False)], expected=None)
        else:
            canonical = [condition.canonical() for condition in request.filters]
            selected, selection = select_variants(rows, canonical)
            per_row = []
            for position, row in enumerate(rows):
                conditions = []
                for condition in canonical:
                    status, value = _read(row, condition['field'])
                    conditions.append({'status': status, 'value': value, 'value_json': encoded(value),
                                       'matched': _matches(row, condition)})
                per_row.append({'row_index': position, 'id': row['id'], 'conditions': conditions})
            expected = {'matched_ids': [row['id'] for row in selected],
                        'matched_row_indexes': [position for position, row in enumerate(rows)
                                                if any(row is match for match in selected)],
                        'selection': selection, 'per_row': per_row}
            item.update(canonical_filters=canonical, canonical_filters_json=encoded(canonical),
                        validation_error=None, expected=expected, expected_json=encoded(expected))
        cases.append(item)
        try:
            query = TireQuery.model_validate({'size': size}).canonical()
        except ValidationError:
            query_sizes.append({'input_size': size, 'canonical_query': None, 'invalid': True})
        else:
            query_sizes.append({'input_size': size, 'canonical_query': query, 'invalid': False})
    return {'schema': 'tire-query-filter-reference@1', 'catalog': catalog(), 'metadata': primary['metadata'],
            'supplements': {'primary_path': 'apps/api/tests/data/query-filters49.json',
                            'primary_sha256': hashlib.sha256(primary_path.read_bytes()).hexdigest(),
                            'reason': 'Unicode Nd width/aspect normalize to ASCII; original two-digit rim tokens remain; fractional .5 is literal ASCII after filter NFKC',
                            'query_size_boundary': 'TireQuery.parse_size is separate from filter NFKC/category-C normalization'},
            'cases': cases, 'query_size_cases': query_sizes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'apps/api/tests/data/query-filters49-extra.json')
    args = parser.parse_args()
    payload = (json.dumps(build_reference(), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(json.dumps({'path': str(args.output), 'cases': len(build_reference()['cases']),
                      'sha256': hashlib.sha256(payload).hexdigest(),
                      'primary_sha256': build_reference()['supplements']['primary_sha256']}))


if __name__ == '__main__':
    main()
