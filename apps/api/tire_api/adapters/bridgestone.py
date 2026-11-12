"""Fixed Bridgestone JP S007A specification tables, with per-row attribution."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re

from ..domain import parse_size

PARSER_VERSION = 'bridgestone-jp-s007a-table@1.0.0'
MODEL = 'POTENZA S007A'
SOURCE_CONFIG = {
    'id': 'bridgestone-jp', 'name': '普利司通 · 日本官网', 'region': 'JP',
    'origin': 'https://tire.bridgestone.co.jp', 'status': 'ready',
    'model_urls': {MODEL: 'https://tire.bridgestone.co.jp/potenza/s007a/size.html'},
    'product_page_urls': {MODEL: 'https://tire.bridgestone.co.jp/potenza/s007a/'},
    'parser_version': PARSER_VERSION, 'content_types': ('text/html',),
    'description': 'POTENZA S007A 日本规格表：PSR产品代码、载重速度、XL、尺寸与日本标签等级。',
}
_HEADERS = ['購入', '偏平率(%)', 'タイヤサイズ', 'エクストラロード', 'メーカー希望小売価格',
            '転がり抵抗係数', 'ウェットグリップ性能', '低車外音タイヤ', 'リムガード',
            '外径(mm)', '標準リム幅(インチ)', 'タイヤ幅(mm)', '注記', '商品コード']


def _error():
    return ValueError('parser_schema_changed')


@dataclass
class _Cell:
    tag: str
    attrs: dict
    parts: list[str] = field(default_factory=list)

    def text(self):
        return ' '.join(''.join(self.parts).split())

    def has_class(self, value):
        return value in (self.attrs.get('class') or '').split()


@dataclass
class _Table:
    headers: list[list[_Cell]] = field(default_factory=list)
    rows: list[list[_Cell]] = field(default_factory=list)


class _TablesHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self.table = None
        self.section = None
        self.row = None
        self.cell = None
        self.in_title = False
        self.titles: list[list[str]] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title':
            if self.in_title:
                raise _error()
            self.in_title = True
            self.titles.append([])
        if tag == 'table':
            if self.table is not None:
                raise _error()
            if 'table_sizeList01' in (attrs.get('class') or '').split():
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
            elif tag in ('th', 'td'):
                if self.row is None or self.cell is not None:
                    raise _error()
                self.cell = _Cell(tag, attrs)
            elif tag == 'img' and self.cell is not None:
                self.cell.parts.append(attrs.get('alt') or '')
            elif tag in ('script', 'style', 'template'):
                raise _error()

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if self.table is None:
            return
        if tag in ('th', 'td'):
            if self.cell is None or self.cell.tag != tag or len(self.cell.text()) > 1024:
                raise _error()
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr':
            if self.cell is not None or not self.row or len(self.row) > 20:
                raise _error()
            target = self.table.rows if self.section == 'tbody' else self.table.headers
            target.append(self.row)
            if len(target) > 500:
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
            if len(self.tables) > 20:
                raise _error()
            self.table = None

    def handle_data(self, value):
        if self.in_title:
            self.titles[-1].append(value)
        if self.cell is not None:
            self.cell.parts.append(value)


def _positive_integer(value):
    if not re.fullmatch(r'[1-9][0-9]{0,4}', value):
        raise _error()
    return int(value)


def _row(cells, table_index, row_index):
    size_columns = [index for index, cell in enumerate(cells) if cell.has_class('tiresize')]
    if len(size_columns) != 1:
        raise _error()
    offset = size_columns[0]
    if (offset not in (1, 2) or not cells[0].has_class('ec')
            or offset == 2 and not cells[1].has_class('flatness') or len(cells) - offset != 13
            or any(cell.tag != 'td' for cell in cells)):
        raise _error()
    values = [cell.text() for cell in cells[offset:]]
    size_text, xl, _, _, rolling, wet, noise, guard, diameter, rim, width, note, code = values
    match = re.fullmatch(r'(\d{3}/\d{2}(?:ZR|R)\d{2}(?:\.5)?)\s+(\d{2,3})([A-Z]|\(Y\)|A[1-8])', size_text)
    if (match is None or not re.fullmatch(r'PSR[0-9]{5}', code) or xl not in ('', 'XL')
            or rolling not in ('', 'AAA', 'AA', 'A', 'B', 'C') or wet not in ('', 'a', 'b', 'c', 'd')
            or noise not in ('', '◎') or guard not in ('', '●')
            or not re.fullmatch(r'[1-9][0-9]?(?:½|\.5)?', rim)):
        raise _error()
    size = parse_size(match[1])
    base = f'(//table[contains(concat(" ", normalize-space(@class), " "), " table_sizeList01 ")])[{table_index + 1}]/tbody/tr[{row_index + 1}]'

    def locator(index):
        return f'{base}/td[{offset + index + 1}]'

    spans = {'model': '/html/head/title', 'manufacturer_product_code': locator(12),
             'size': locator(0), 'load_index': locator(0), 'speed_rating': locator(0),
             'source_variant_name': locator(0)}
    facts = {}

    def fact(name, value, index):
        facts[name] = value
        spans['facts.' + name] = locator(index)

    fact('product_code_type', 'PRODUCT_CODE', 12)
    fact('service_description', match[2] + match[3], 0)
    if rolling:
        fact('jp_rolling_resistance_grade', rolling, 4)
    if wet:
        fact('jp_wet_grip_grade', wet, 5)
    fact('overall_diameter_mm', _positive_integer(diameter), 8)
    fact('standard_rim_width_in', float(rim.replace('½', '.5')), 9)
    fact('overall_width_mm', _positive_integer(width), 10)
    if xl:
        spans['xl'] = locator(1)
        fact('load_id', 'XL', 1)
    if noise:
        fact('jp_low_external_noise', True, 6)
    if guard:
        fact('rim_guard', True, 7)
    if note:
        fact('source_note', note, 11)
    facts['evidence_spans'] = spans
    return {'brand': 'Bridgestone', 'model': MODEL, 'region': 'JP',
            'manufacturer_product_code': code, 'size': size, 'load_index': match[2],
            'speed_rating': match[3], 'xl': True if xl else None, 'hl': None,
            'oe_mark': None, 'acoustic_technology': None, 'run_flat': None,
            'source_variant_name': size_text, 'facts': facts}


def parse_html(body: str, query: dict) -> list[dict]:
    try:
        parser = _TablesHTML()
        parser.feed(body)
        parser.close()
        if (parser.table is not None or parser.in_title or len(parser.titles) != 1
                or not ''.join(parser.titles[0]).strip().startswith(MODEL + ' -') or not parser.tables):
            raise _error()
        variants = []
        for table_index, table in enumerate(parser.tables):
            headers = [[re.sub(r'\s+', '', cell.text()) for cell in row] for row in table.headers]
            if headers != [_HEADERS, ['税込', '(本体価格)']] or not table.rows:
                raise _error()
            variants.extend(_row(row, table_index, row_index) for row_index, row in enumerate(table.rows))
        codes = [row['manufacturer_product_code'] for row in variants]
        if len(codes) > 500 or len(codes) != len(set(codes)):
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
