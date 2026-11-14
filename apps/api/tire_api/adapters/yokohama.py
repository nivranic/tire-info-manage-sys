"""Fixed Yokohama Europe desktop specification tables and manufacturer label claims."""
from dataclasses import dataclass, field
from html.parser import HTMLParser
import re

from ..domain import VariantInput, parse_size

PARSER_VERSION = 'yokohama-eu-v107-tables@1.0.0'
MODEL = 'ADVAN Sport V107'
URL = 'https://www.yokohama.eu/tyres/advan-sport-v107/'
SOURCE_CONFIG = {
    'id': 'yokohama-eu', 'name': '横滨 · 欧洲官网', 'region': 'EU',
    'origin': 'https://www.yokohama.eu', 'status': 'ready',
    'model_urls': {MODEL: URL}, 'parser_version': PARSER_VERSION,
    'description': 'ADVAN Sport V107官方规格表及厂商标签声明，保留合并XL/RF与OE原文，EPREL链接待独立核验。',
}
HEADERS = ['Series', 'Size', 'XL/RF', 'OE Info', '', '', '', '', '', 'EU LABEL GRADE']
ICONS = ['fuel-efficiency-icon-header', 'wet-grip-icon-header',
         'external-noise-icon-header', 'snow-grip-icon-header', 'ice-grip-icon-header']


def _error():
    return ValueError('parser_schema_changed')


@dataclass
class _Cell:
    tag: str
    text: str = ''
    icons: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


class _TablesHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = self.section = self.row = self.cell = None
        self.titles = []
        self.in_title = False
        self.canonical = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title':
            if self.in_title:
                raise _error()
            self.in_title = True
            self.titles.append('')
        if tag == 'link' and 'canonical' in attrs.get('rel', '').split():
            self.canonical.append(attrs.get('href'))
        if tag == 'table':
            if self.table is not None or len(self.tables) >= 12:
                raise _error()
            self.table = {'thead': [], 'tbody': []}
        elif self.table is not None:
            if tag in ('thead', 'tbody'):
                if self.section is not None:
                    raise _error()
                self.section = tag
            elif tag == 'tr':
                if self.row is not None or self.section is None:
                    raise _error()
                self.row = []
            elif tag in ('td', 'th'):
                if self.row is None or self.cell is not None or any(key in attrs for key in ('rowspan', 'colspan')):
                    raise _error()
                self.cell = _Cell(tag)
            elif self.cell is not None:
                if tag == 'span':
                    self.cell.icons.extend(value for value in attrs.get('class', '').split()
                                           if value.endswith('-icon-header'))
                elif tag == 'a':
                    self.cell.links.append(attrs.get('href'))
                elif tag not in ('br',):
                    raise _error()

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        elif self.table is not None:
            if tag in ('td', 'th'):
                if self.cell is None or self.cell.tag != tag:
                    raise _error()
                self.cell.text = ' '.join(self.cell.text.split())
                self.row.append(self.cell)
                self.cell = None
            elif tag == 'tr':
                if self.cell is not None or self.row is None:
                    raise _error()
                self.table[self.section].append(self.row)
                if len(self.table[self.section]) > 501:
                    raise _error()
                self.row = None
            elif tag in ('thead', 'tbody'):
                if self.section != tag or self.row is not None:
                    raise _error()
                self.section = None
            elif tag == 'table':
                if self.section is not None:
                    raise _error()
                self.tables.append(self.table)
                self.table = None

    def handle_data(self, value):
        if self.in_title:
            self.titles[-1] += value
        if self.cell is not None:
            self.cell.text += value
            if len(self.cell.text) > 1024:
                raise _error()


def _row(cells, table_index, row_index):
    if len(cells) != 10 or any(cell.tag != 'td' for cell in cells):
        raise _error()
    values = [cell.text for cell in cells]
    match = re.fullmatch(r'(?:HL)?(\d{3}/\d{2}(?:ZR|R)\d{2}) \((\d{2,3})([A-Z]|\(Y\))\)', values[1])
    label = re.fullmatch(r'https://eprel\.ec\.europa\.eu/qr/([1-9][0-9]{0,11})',
                         cells[9].links[0]) if len(cells[9].links) == 1 else None
    if (match is None or label is None or values[0] != match[1].split('/')[1][:2]
            or any(cell.links for cell in cells[:9]) or values[9] != 'View'
            or values[2] not in ('XL/RF', '-') or not 1 <= len(values[3]) <= 100
            or any(value not in ('A', 'B', 'C', 'D', 'E', '-') for value in values[4:6])
            or any(len(value) > 100 for value in values[7:9])):
        raise _error()
    base = f'(//table)[{table_index + 1}]/tbody/tr[{row_index + 1}]'
    spans = {'model': '//title', 'size': base + '/td[2]',
             'load_index': base + '/td[2]', 'speed_rating': base + '/td[2]'}
    hl = True if values[1].startswith('HL') else None
    if hl:
        spans['hl'] = base + '/td[2]'
    facts = {}

    def fact(name, value, column):
        facts[name] = value
        spans['facts.' + name] = f'{base}/td[{column}]'

    fact('source_size_marking', values[1], 2)
    fact('source_load_marking', values[2], 3)
    fact('source_oe_info', values[3], 4)
    fact('eprel_id', label[1], 10)
    fact('source_label_url', cells[9].links[0], 10)
    for name, column in (('eu_fuel_class', 5), ('eu_wet_grip', 6)):
        if values[column - 1] != '-':
            fact(name, values[column - 1], column)
    noise = re.fullmatch(r'([1-9][0-9]|100)DB/([ABC])', values[6])
    if noise:
        fact('eu_external_noise_db', int(noise[1]), 7)
        fact('eu_noise_class', noise[2], 7)
    elif values[6] != '-':
        raise _error()
    fact('source_snow_grip_marking', values[7], 8)
    fact('source_ice_grip_marking', values[8], 9)
    facts['evidence_spans'] = spans
    return VariantInput(brand='Yokohama', model=MODEL, region='EU', size=parse_size(match[1]),
        load_index=match[2], speed_rating=match[3], hl=hl,
        source_variant_name=' | '.join((values[1], values[2], values[3], 'EPREL ' + label[1])),
        facts=facts).model_dump()


def parse_html(body: str, query: dict) -> list[dict]:
    try:
        parser = _TablesHTML()
        parser.feed(body)
        parser.close()
        if (parser.table is not None or parser.in_title or not parser.tables
                or parser.titles != [MODEL + ' tyres - Yokohama'] or parser.canonical != [URL]):
            raise _error()
        variants = []
        for table_index, table in enumerate(parser.tables):
            if len(table['thead']) != 1 or not table['tbody']:
                raise _error()
            headers = table['thead'][0]
            if ([cell.text for cell in headers] != HEADERS or any(cell.tag != 'th' for cell in headers)
                    or [cell.icons for cell in headers] != [[], [], [], [], *[[icon] for icon in ICONS], []]):
                raise _error()
            variants.extend(_row(row, table_index, index) for index, row in enumerate(table['tbody']))
        ids = [row['facts']['eprel_id'] for row in variants]
        if len(ids) > 500 or len(set(ids)) != len(ids):
            raise _error()
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError, OverflowError):
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
