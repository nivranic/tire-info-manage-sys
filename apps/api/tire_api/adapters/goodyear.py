"""Singapore AS6 declarations checked against both official table layouts."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
import re

from ..domain import VariantInput, parse_size

PARSER_VERSION = 'goodyear-sg-as6-tables@1.0.0'
MODELS = ('Eagle F1 Asymmetric 6', 'Eagle F1 Asymmetric 6 SUV')
URL = 'https://www.goodyear.com.sg/tyres/goodyear-eagle-f1-asymmetric-6'
SOURCE_CONFIG = {
    'id': 'goodyear-sg', 'name': '固特异 · 新加坡官网', 'region': 'SG',
    'origin': 'https://www.goodyear.com.sg', 'status': 'ready',
    'model_urls': dict.fromkeys(MODELS, URL), 'content_types': ('text/html',),
    'parser_version': PARSER_VERSION,
    'description': 'Eagle F1 Asymmetric 6与SUV版官方三表规格，缺失速度与原始标记独立保留，产品代码未知。',
}
_HEADERS = ['Pattern', 'Rim', 'Size', 'Load', 'Speed', 'XL']
_LOAD_MARKINGS = {'', 'XL', 'XL (EDR)', 'XL FP', '(EDR)', 'RO XL', 'MO XL', 'X (EDR)'}


def _error():
    return ValueError('parser_schema_changed')


@dataclass
class _Cell:
    tag: str
    attrs: dict
    text: str = ''


@dataclass
class _Table:
    headers: list = field(default_factory=list)
    rows: list = field(default_factory=list)


class _TablesHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = self.section = self.row = self.cell = None
        self.in_title = False
        self.titles = []

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            if self.in_title:
                raise _error()
            self.in_title = True
            self.titles.append('')
        if tag == 'table':
            if self.table is not None or len(self.tables) >= 3:
                raise _error()
            self.table = _Table()
        elif self.table is not None:
            if tag in ('thead', 'tbody'):
                if self.section is not None:
                    raise _error()
                self.section = tag
            elif tag == 'tr':
                if self.section is None or self.row is not None:
                    raise _error()
                self.row = []
            elif tag in ('td', 'th'):
                if self.row is None or self.cell is not None:
                    raise _error()
                self.cell = _Cell(tag, dict(attrs))
            elif tag in ('script', 'style', 'template', 'table'):
                raise _error()

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if self.table is None:
            return
        if tag in ('td', 'th'):
            if self.cell is None or self.cell.tag != tag:
                raise _error()
            self.cell.text = ' '.join(self.cell.text.split())
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr':
            if self.cell is not None or not self.row or len(self.row) > 6:
                raise _error()
            target = self.table.headers if self.section == 'thead' else self.table.rows
            target.append(self.row)
            if len(target) > 510:
                raise _error()
            self.row = None
        elif tag in ('thead', 'tbody'):
            if self.section != tag or self.row is not None:
                raise _error()
            self.section = None
        elif tag == 'table':
            if self.section is not None or self.row is not None or self.cell is not None:
                raise _error()
            self.tables.append(self.table)
            self.table = None

    def handle_data(self, value):
        if self.in_title:
            self.titles[-1] += value
        if self.cell is not None:
            self.cell.text += value
            if len(self.cell.text) > 512:
                raise _error()


def _row(cells, model, model_locator, row_index):
    if len(cells) != 5 or any(cell.tag != 'td' or 'colspan' in cell.attrs or 'rowspan' in cell.attrs for cell in cells):
        raise _error()
    rim, size_text, load, speed_text, markings = [cell.text for cell in cells]
    size = parse_size(size_text)
    speed = re.fullmatch(r'([A-Z]|\(Y\)|A[1-8])(?:\s*(?:\*|I\*|\(\+\)))?', speed_text) if speed_text else None
    if (rim != size.split('R')[-1] or re.fullmatch(r'[1-9][0-9]{1,2}', load) is None
            or speed_text and speed is None or markings not in _LOAD_MARKINGS):
        raise _error()
    base = f'(//table)[1]/tbody/tr[{row_index + 1}]'

    def locator(index):
        return f'{base}/td[{index + 1}]'

    spans = {'model': model_locator, 'size': locator(1), 'load_index': locator(2),
             'source_variant_name': base}
    facts = {}

    def fact(name, value, index):
        facts[name] = value
        spans['facts.' + name] = locator(index)

    if speed:
        spans['speed_rating'] = locator(3)
        fact('source_speed_marking', speed_text, 3)
    if markings:
        fact('source_load_marking', markings, 4)
    xl = 'XL' in markings.split()
    if xl:
        spans['xl'] = locator(4)
        fact('load_id', 'XL', 4)
    facts['evidence_spans'] = spans
    name = ' '.join(f'{size_text} {load}{speed_text} {markings}'.split())
    value = VariantInput(brand='Goodyear', model=model, region='SG', size=size,
        load_index=load, speed_rating=speed[1] if speed else None, xl=True if xl else None,
        source_variant_name=name, facts=facts).model_dump()
    return value


def _variants(tables):
    primary, *layouts = tables
    if (len(primary.headers) != 1 or [cell.text for cell in primary.headers[0]] != _HEADERS
            or any(cell.tag != 'th' for cell in primary.headers[0])):
        raise _error()
    groups = {}
    model = model_locator = None
    for index, cells in enumerate(primary.rows):
        if len(cells) == 1:
            label = cells[0].text
            if not label and cells[0].attrs.get('colspan') == '7':
                continue
            expected = next((value for value in MODELS if value.upper() == label), None)
            if cells[0].tag != 'td' or expected is None or expected in groups:
                raise _error()
            model = expected
            model_locator = f'(//table)[1]/tbody/tr[{index + 1}]/td[1]'
            groups[model] = []
        else:
            if model is None:
                raise _error()
            groups[model].append(_row(cells, model, model_locator, index))
    if list(groups) != list(MODELS):
        raise _error()
    variants = []
    for rows, table in zip(groups.values(), layouts):
        names = [row['source_variant_name'] for row in rows]
        if not names or len(names) > 500 or len(set(names)) != len(names):
            raise _error()
        if (len(table.headers) != 1 or not table.headers[0]
                or any(cell.tag != 'th' or re.fullmatch(r'Tyre Rim:\s*\d{2}"', cell.text) is None for cell in table.headers[0])):
            raise _error()
        if any(cell.tag != 'td' for row in table.rows for cell in row):
            raise _error()
        if Counter(cell.text for row in table.rows for cell in row) != Counter(names):
            raise _error()
        variants.extend(rows)
    return variants


def parse_html(body: str, query: dict) -> list[dict]:
    try:
        parser = _TablesHTML()
        parser.feed(body)
        parser.close()
        if (parser.table is not None or parser.in_title or len(parser.tables) != 3
                or parser.titles != ['Goodyear Eagle F1 Asymmetric 6 | Goodyear Singapore']):
            raise _error()
        variants = _variants(parser.tables)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise _error() from None
    if query.get('model') is not None:
        model = ' '.join(query['model'].split()).casefold()
        variants = [row for row in variants if row['model'].casefold() == model]
    if query.get('size') is not None:
        try:
            size = parse_size(query['size']).replace('ZR', 'R')
        except (ValueError, TypeError, AttributeError):
            return []
        variants = [row for row in variants if row['size'].replace('ZR', 'R') == size]
    return variants
