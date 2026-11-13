"""Fixed Chinese public SC7 specifications with provisional source identities."""
from __future__ import annotations

import json
import re

from ..domain import VariantInput, parse_size

PARSER_VERSION = 'continental-cn-sc7-json@1.0.0'
MODEL = 'SportContact SC7'
SOURCE_CONFIG = {
    'id': 'continental-cn', 'name': '马牌 · 中国官网', 'region': 'CN',
    'origin': 'https://www.continental-tires.cn', 'status': 'ready',
    'model_urls': {MODEL: 'https://www.continental-tires.cn/tpservice/Search/getTireData?tire=SportContact%20SC7'},
    'product_page_urls': {MODEL: 'https://www.continental-tires.cn/tires/sportcontact-sc7'},
    'content_types': ('application/json',), 'parser_version': PARSER_VERSION,
    'description': 'SportContact SC7 中国官方规格：载重速度、XL与逐行静音声明；产品代码未知，身份限定于来源观察。',
}
_FIELDS = frozenset({'size', 'level', 'load', 'protect', 'ems', 'silent', 'type', 'pattern'})


def _error():
    return ValueError('parser_schema_changed')


def _unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise _error()
    return result


def _row(row, rim, index):
    if (not isinstance(row, dict) or set(row) != _FIELDS
            or any(not isinstance(value, str) or len(value) > 100 for value in row.values())):
        raise _error()
    size = parse_size(row['size'])
    service = re.fullmatch(r'(\d{2,3})([A-Z]|\(Y\)|A[1-8])', row['level'])
    if (size.split('R')[-1] != rim or service is None or row['load'] not in ('', 'XL')
            or row['protect'] not in ('', 'FR') or row['ems'] != ''
            or row['silent'] not in ('', '是') or row['type'] != 'CAR/SUV' or row['pattern'] != ''):
        raise _error()
    base = f'$["{rim}"][{index}]'
    spans = {'model': '$ (SportContact SC7 fixed request)', 'size': base + '.size',
             'load_index': base + '.level', 'speed_rating': base + '.level',
             'source_variant_name': base + ' (source row)'}
    facts = {}

    def fact(name, value, field):
        facts[name] = value
        spans['facts.' + name] = base + '.' + field

    fact('service_description', row['level'], 'level')
    fact('vehicle_type', row['type'], 'type')
    if row['load']:
        spans['xl'] = base + '.load'
        fact('load_id', row['load'], 'load')
    if row['protect']:
        fact('rim_guard', True, 'protect')
    if row['silent']:
        spans['acoustic_technology'] = base + '.silent'
    facts['evidence_spans'] = spans
    name = ' '.join(value for value in (MODEL, size, row['level'], row['load'], row['protect'],
                                        'ContiSilent' if row['silent'] else '') if value)
    value = {'brand': 'Continental', 'model': MODEL, 'region': 'CN',
            'manufacturer_product_code': None, 'size': size, 'load_index': service[1],
            'speed_rating': service[2], 'xl': True if row['load'] else None,
            'hl': None, 'oe_mark': None, 'run_flat': None,
            'acoustic_technology': 'ContiSilent' if row['silent'] else None,
            'source_variant_name': name, 'facts': facts}
    return VariantInput.model_validate(value).model_dump()


def parse_html(body: str, query: dict) -> list[dict]:
    try:
        groups = json.loads(body, object_pairs_hook=_unique_object)
        if not isinstance(groups, dict) or not groups or len(groups) > 21:
            raise _error()
        variants, seen = [], set()
        for rim, rows in groups.items():
            if (re.fullmatch(r'(?:1[0-9]|2[0-9]|30)', rim) is None
                    or not isinstance(rows, list) or not rows or len(rows) > 500):
                raise _error()
            for index, row in enumerate(rows):
                variant = _row(row, rim, index)
                identity = json.dumps(row, sort_keys=True, ensure_ascii=False)
                if identity in seen or len(variants) >= 500:
                    raise _error()
                seen.add(identity)
                variants.append(variant)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise _error() from None
    if query.get('model') is not None:
        model = query['model']
        if not isinstance(model, str) or ' '.join(model.split()).casefold() != MODEL.casefold():
            return []
    if query.get('size') is not None:
        try:
            size = parse_size(query['size']).replace('ZR', 'R')
        except (ValueError, TypeError, AttributeError):
            return []
        variants = [row for row in variants if row['size'].replace('ZR', 'R') == size]
    return variants
