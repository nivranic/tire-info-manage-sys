"""Fixed Dunlop Europe model response embedded in Angular transfer state."""
from html.parser import HTMLParser
import json
import re

from ..domain import VariantInput, parse_size

PARSER_VERSION = 'dunlop-eu-rt2-transfer-state@1.0.0'
MODEL = 'SPORT MAXX RT2'
SLUG = 'sport-maxx-rt2'
URL = 'https://www.dunloptyres.com/en/tyres/' + SLUG
RESPONSE_URL = 'https://tyrecore.dunloptyres.com/tyres/en/details/' + SLUG
SOURCE_CONFIG = {
    'id': 'dunlop-eu', 'name': '邓禄普 · 欧洲官网', 'region': 'EU',
    'origin': 'https://www.dunloptyres.com', 'status': 'ready',
    'model_urls': {MODEL: URL}, 'parser_version': PARSER_VERSION,
    'description': 'SPORT MAXX RT2官方型号规格，保留Material Code、EAN和厂商EU标签声明，EPREL待独立核验。',
}


def _error():
    return ValueError('parser_schema_changed')


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _error()
        value[key] = item
    return value


def _constant(_value):
    raise _error()


def _json(value):
    return json.loads(value, object_pairs_hook=_unique_object, parse_constant=_constant)


class _StateHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titles = []
        self.canonical = []
        self.states = []
        self.in_title = self.in_state = False

    def handle_starttag(self, tag, attrs):
        attrs = _unique_object(attrs)
        if tag == 'title':
            if self.in_title:
                raise _error()
            self.in_title = True
            self.titles.append('')
        elif tag == 'link' and 'canonical' in attrs.get('rel', '').split():
            self.canonical.append(attrs.get('href'))
        elif tag == 'script' and attrs.get('id') == 'ng-state':
            if self.in_state or attrs.get('type') != 'application/json' or 'src' in attrs:
                raise _error()
            self.in_state = True
            self.states.append('')

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        elif tag == 'script':
            self.in_state = False

    def handle_data(self, value):
        if self.in_title:
            self.titles[-1] += value
        if self.in_state:
            self.states[-1] += value
            if len(self.states[-1]) > 8 * 1024 * 1024:
                raise _error()


def _row(row, index, state_key):
    if not isinstance(row, dict) or row.get('brand') != 'Dunlop' or row.get('product_segment') != 'SUMMER':
        raise _error()
    code, gtin = row.get('material'), row.get('ean_upc')
    if (not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code)
            or row.get('rep_code') != code or not isinstance(gtin, str)
            or not re.fullmatch(r'(?:[0-9]{8}|[0-9]{12,14})', gtin)):
        raise _error()
    weighted = sum(int(digit) * (3 if position % 2 == 0 else 1)
                   for position, digit in enumerate(reversed(gtin[:-1])))
    if (weighted + int(gtin[-1])) % 10:
        raise _error()
    size = parse_size(row['tyre_size'])
    geometry = re.fullmatch(r'(\d{3})/(\d{2})(ZR|R)(\d{2}(?:\.5)?)', size)
    service = re.fullmatch(r'([0-9]{2,3})([A-Z]|\(Y\))(?: (XL))?', row['li_si'])
    if (service is None or row.get('lastindex_1') != service[1]
            or row.get('geschwindigkeitsindex_1') != service[2]
            or row.get('extra_load') != service[3] or row.get('radial') != geometry[3]
            or any(row.get(key) is not None for key in
                   ('lastindex_2', 'lastindex_3', 'lastindex_4', 'geschwindigkeitsindex_2'))
            or any(type(row.get(key)) not in (int, float) or row[key] != expected for key, expected in
                   (('width_mm', int(geometry[1])), ('ratio', int(geometry[2])), ('rim_inch', float(geometry[4]))))
            or row.get('vehicle_category') not in ('CAR', 'SUV')
            or row.get('status_def') not in ('active', 'phase out')
            or row.get('is_lt') is not False or row.get('commercial_vehicle_info') is not False
            or row.get('eu_label_exempt') is not False):
        raise _error()
    ep_id = row.get('eprel_reg_nr')
    if (not isinstance(ep_id, str) or not re.fullmatch(r'[1-9][0-9]{0,11}', ep_id)
            or row.get('eprel_link') != 'https://eprel.ec.europa.eu/qr/' + ep_id):
        raise _error()
    label = row.get('eu_label')
    if (not isinstance(label, dict)
            or any(label.get(key) not in ('A', 'B', 'C', 'D', 'E') for key in
                   ('fuel_efficiency_2020_740', 'wet_grip_2020_740'))
            or label.get('external_rolling_noise_class_2020_740') not in ('A', 'B', 'C')
            or not isinstance(label.get('external_rolling_noise_db_2020_740'), str)
            or not re.fullmatch(r'[1-9][0-9]|100', label['external_rolling_noise_db_2020_740'])):
        raise _error()
    root = f'//script[@id="ng-state"]/text() JSON $["{state_key}"].b decoded $'
    base = root + f'.sizes[{index}]'
    spans = {'model': root + '.quickInfo.tyreModelname', 'size': base + '.tyre_size',
             'manufacturer_product_code': base + '.material',
             'load_index': base + '.lastindex_1', 'speed_rating': base + '.geschwindigkeitsindex_1'}
    facts = {}

    def fact(name, value, field):
        facts[name] = value
        spans['facts.' + name] = base + '.' + field

    fact('product_code_type', 'MATERIAL_CODE', 'material')
    fact('gtin', gtin, 'ean_upc')
    fact('eprel_id', ep_id, 'eprel_reg_nr')
    fact('source_label_url', row['eprel_link'], 'eprel_link')
    fact('service_description', row['li_si'], 'li_si')
    fact('source_catalog_status', row['status_def'], 'status_def')
    for name, field in (('eu_fuel_class', 'fuel_efficiency_2020_740'),
                        ('eu_wet_grip', 'wet_grip_2020_740'),
                        ('eu_noise_class', 'external_rolling_noise_class_2020_740')):
        fact(name, label[field], 'eu_label.' + field)
    fact('eu_external_noise_db', int(label['external_rolling_noise_db_2020_740']),
         'eu_label.external_rolling_noise_db_2020_740')
    for name, field in (('three_peak_mountain_snowflake', 'snowflake'),
                        ('ice_grip', 'ice'), ('source_mobility_technology', 'mobility_technology')):
        if type(row.get(field)) is not bool:
            raise _error()
        fact(name, row[field], field)
    technology = row.get('technology_info')
    if not isinstance(technology, dict) or not isinstance(technology.get('flags'), dict):
        raise _error()
    flags, tokens = technology['flags'], technology.get('tokens')
    if (type(row.get('mfs')) is not bool or any(type(flags.get(key)) is not bool for key in
            ('extended_mobility_technology', 'noise_cancellation_technology', 'ms',
             'rim_protection', 'snowflake', 'ice'))
            or any(flags[key] != row.get(field) for key, field in
                   (('extended_mobility_technology', 'mobility_technology'),
                    ('rim_protection', 'mfs'), ('snowflake', 'snowflake'), ('ice', 'ice')))
            or not isinstance(tokens, list) or len(tokens) > 20
            or any(not isinstance(value, str) or not 1 <= len(value) <= 100 for value in tokens)
            or len(set(tokens)) != len(tokens)):
        raise _error()
    fact('m_plus_s', flags['ms'], 'technology_info.flags.ms')
    fact('rim_guard', flags['rim_protection'], 'technology_info.flags.rim_protection')
    fact('technology_features', tokens, 'technology_info.tokens')
    for field in ('oem_brand', 'oe_models'):
        if row.get(field) is not None:
            if not isinstance(row[field], str) or not 1 <= len(row[field]) <= 200:
                raise _error()
            fact('source_' + field, row[field], field)
    if service[3]:
        spans['xl'] = base + '.extra_load'
    facts['evidence_spans'] = spans
    return VariantInput(brand='Dunlop', model=MODEL, region='EU',
        manufacturer_product_code=code, size=size, load_index=service[1], speed_rating=service[2],
        xl=True if service[3] else None,
        source_variant_name=f'{MODEL} {size} {row["li_si"]} {code}', facts=facts).model_dump()


def parse_html(body: str, query: dict) -> list[dict]:
    try:
        parser = _StateHTML()
        parser.feed(body)
        parser.close()
        if (parser.in_title or parser.in_state or len(parser.states) != 1
                or parser.titles != [MODEL + ' – SUMMER – Dunlop'] or parser.canonical != [URL]):
            raise _error()
        state = _json(parser.states[0])
        if not isinstance(state, dict) or len(state) > 256:
            raise _error()
        candidates = [(key, value) for key, value in state.items()
                      if isinstance(value, dict) and value.get('u') == RESPONSE_URL]
        if len(candidates) != 1:
            raise _error()
        state_key, response = candidates[0]
        if (not re.fullmatch(r'[a-f0-9]{64}', state_key) or response.get('s') != 200
                or response.get('rt') != 'text' or not isinstance(response.get('b'), str)):
            raise _error()
        data = _json(response['b'])
        info, rows = data['quickInfo'], data['sizes']
        if (not isinstance(info, dict) or info.get('tyreModelname') != MODEL
                or info.get('slug') != SLUG or info.get('languageCode') != 'en'
                or info.get('season') != 'SUMMER' or not isinstance(rows, list) or not 1 <= len(rows) <= 500):
            raise _error()
        variants = [_row(row, index, state_key) for index, row in enumerate(rows)]
        if len({row['manufacturer_product_code'] for row in variants}) != len(variants):
            raise _error()
        if len({row['facts']['gtin'] for row in variants}) != len(variants):
            raise _error()
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
