"""Deterministic projection of one accepted tire source; no inferred attributes or I/O."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

MAX_CONDITIONS = 16
PRESENCE_OPERATORS = ['is_known', 'is_unknown']
TEXT_OPERATORS = ['eq', *PRESENCE_OPERATORS]
NUMBER_OPERATORS = ['eq', 'gte', 'lte', *PRESENCE_OPERATORS]


def _field(key: str, label: str, kind: str = 'text', **metadata: Any) -> dict[str, Any]:
    return {'key': key, 'label': label, 'type': kind,
            'operators': NUMBER_OPERATORS if kind == 'number' else TEXT_OPERATORS, **metadata}


_FIELDS = [
    _field('brand', '品牌'),
    _field('family', '产品系列', description='仅匹配 facts.family 明确发布的系列，不从型号推断。'),
    _field('model', '型号'),
    _field('variant_id', '版本 ID', description='本系统已采纳版本的精确 ID。'),
    _field('region', '区域'),
    _field('manufacturer_product_code', '厂商产品代码', description='文本精确匹配，保留前导零。'),
    _field('gtin', 'GTIN', description='文本精确匹配，保留前导零。'),
    _field('eprel_id', 'EPREL 编号', description='文本精确匹配，保留前导零；不推断注册状态。'),
    _field('size', '尺寸', description='公制尺寸精确匹配，保留 R / ZR 差别。'),
    _field('construction', '结构'),
    _field('load_index', '载重指数', description='按完整文本匹配双载重指数；不提供数值排序。'),
    _field('speed_rating', '速度级别', description='按完整级别精确匹配；不按字母排序。'),
    _field('oe_mark', 'OE 标记', description='按来源完整标记文本匹配，不从 OE 推断车型适配。'),
    _field('acoustic_technology', '静音技术', description='技术名称精确匹配；Acoustic、PNCS、ContiSilent、Foam 互不等同。'),
    _field('technology_features', '技术配置', description='eq 匹配来源文本列表中的完整成员；不解析营销描述。空列表为未知。'),
    *[_field(key, label, 'boolean', options=[{'value': True, 'label': '是'}, {'value': False, 'label': '否'}],
             description='仅接受来源明确声明的布尔值，未声明不等于否。')
      for key, label in [('xl', 'XL'), ('hl', 'HL'), ('run_flat', '防爆 / 缺气保用'),
                         ('acoustic_foam', '静音棉'), ('ev_marketing_mark', 'EV 营销标识')]],
    _field('season', '季节'),
    _field('utqg_treadwear', 'UTQG 磨耗', 'number', description='仅接受来源实际数字，不转换文本、对象或单位。'),
    _field('utqg_traction', 'UTQG 抓地'),
    _field('utqg_temperature', 'UTQG 温度'),
    _field('eu_fuel_class', '欧盟能效等级'),
    _field('eu_wet_grip', '欧盟湿地抓地等级'),
    _field('eu_external_noise_db', '欧盟外部滚动噪声', 'number', unit='dB',
           description='仅接受来源实际 dB 数值，不转换文本、对象或其他单位。'),
    _field('eu_noise_class', '欧盟噪声等级'),
]
FIELDS = {field['key']: field for field in _FIELDS}
_IDENTITY_FIELDS = {'brand', 'model', 'region', 'manufacturer_product_code', 'size', 'load_index',
                    'speed_rating', 'oe_mark', 'acoustic_technology', 'xl', 'hl', 'run_flat'}
_TECHNICAL_TEXT_FIELDS = {'family', 'construction', 'load_index', 'speed_rating', 'oe_mark', 'acoustic_technology',
                          'season', 'utqg_traction', 'utqg_temperature', 'eu_fuel_class', 'eu_wet_grip', 'eu_noise_class'}
_SPEED_RATINGS = {'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8', 'B', 'C', 'D', 'E', 'F', 'G',
                  'J', 'K', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'H', 'V', 'W', 'Y', '(Y)', 'ZR'}


def catalog() -> dict[str, Any]:
    return {'version': 'tire-query-filters@1', 'max_conditions': MAX_CONDITIONS,
            'fields': deepcopy(_FIELDS),
            'notice': '所有条件同时满足才返回。文本按 Unicode 规范化、合并空白和忽略大小写精确匹配。'
                      '未声明不等于否；技术文本中的 unknown / unspecified 视为未声明（不适用于产品代码等标识）。'
                      '冲突或不合法类型无法判定。筛选仅作用于本次来源结果，不影响完整证据、入库或质量检查。'}


def _text(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError('文本筛选值必须是 1–512 字符的字符串')
    if any(unicodedata.category(character).startswith('C') for character in value):
        raise ValueError('文本筛选值不能包含控制或不可见字符')
    normalized = ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()
    if not normalized or len(normalized) > 512:
        raise ValueError('文本筛选值不能为空或超过 512 字符')
    return normalized


def _number(value: Any) -> int | float:
    if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError('数值筛选值必须是有限数字，不能是布尔值、字符串或带单位对象')
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _normalize_value(field: str, value: Any) -> str | int | float | bool:
    kind = FIELDS[field]['type']
    if kind == 'boolean':
        if type(value) is not bool:
            raise ValueError('布尔筛选值必须是 true 或 false，不能用 0/1 或文本代替')
        return value
    if kind == 'number':
        return _number(value)
    normalized = _text(value)
    if field == 'size':
        from .domain import parse_size
        normalized = parse_size(normalized)
    elif field == 'load_index' and not re.fullmatch(r'[0-9]{2,3}(?:/[0-9]{2,3})?', normalized):
        raise ValueError('载重指数必须是完整指数文本，例如 104 或 104/102')
    elif field == 'speed_rating' and normalized.upper() not in _SPEED_RATINGS:
        raise ValueError('速度级别无效')
    return normalized


class TireFilter(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    field: str
    op: Literal['eq', 'gte', 'lte', 'is_known', 'is_unknown']
    value: Any = None

    @model_validator(mode='after')
    def validate_condition(self) -> TireFilter:
        if self.field not in FIELDS:
            raise ValueError('不支持此筛选字段')
        if self.op not in FIELDS[self.field]['operators']:
            raise ValueError('此字段不支持该筛选操作')
        if self.op in PRESENCE_OPERATORS:
            if 'value' in self.model_fields_set:
                raise ValueError('已知 / 未知筛选不接受 value')
        else:
            object.__setattr__(self, 'value', _normalize_value(self.field, self.value))
        return self

    def canonical(self) -> dict[str, Any]:
        result = {'field': self.field, 'op': self.op}
        if self.op not in PRESENCE_OPERATORS:
            result['value'] = self.value
        return result


def canonical_filters(conditions: list[TireFilter]) -> list[dict[str, Any]]:
    # A stable order and scalar representation bind equivalent requests identically.
    unique = {json.dumps(condition.canonical(), sort_keys=True, ensure_ascii=False, allow_nan=False): condition.canonical()
              for condition in conditions}
    return [unique[key] for key in sorted(unique)]


def _read(row: dict[str, Any], field: str) -> tuple[str, Any]:
    facts = row.get('facts', {})
    if not isinstance(facts, dict):
        return 'invalid', None
    conflicts = facts.get('source_field_conflicts', [])
    if not isinstance(conflicts, list):
        return 'invalid', None
    for conflict in conflicts:
        if isinstance(conflict, dict) and conflict.get('field') in (field, 'facts.' + field, 'identity.' + field):
            return 'conflict', None
    value = row.get('id') if field == 'variant_id' else row.get(field) if field in _IDENTITY_FIELDS else facts.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return 'unknown', None
    try:
        if field in _TECHNICAL_TEXT_FIELDS and isinstance(value, str) and _text(value) in {'unknown', 'unspecified'}:
            return 'unknown', None
        if field == 'technology_features':
            if not isinstance(value, list):
                return 'invalid', None
            if not value:
                return 'unknown', None
            return 'known', [_text(item) for item in value]
        return 'known', _normalize_value(field, value)
    except (ValueError, TypeError):
        return 'invalid', None


def _matches(row: dict[str, Any], condition: dict[str, Any]) -> bool | None:
    status, actual = _read(row, condition['field'])
    if status in ('invalid', 'conflict'):
        return None
    op = condition['op']
    if op == 'is_known':
        return status == 'known'
    if op == 'is_unknown':
        return status == 'unknown'
    if status != 'known':
        return None
    expected = condition['value']
    if op == 'eq':
        return expected in actual if condition['field'] == 'technology_features' else actual == expected
    if op == 'gte':
        return actual >= expected
    return actual <= expected


def select_variants(rows: list[dict[str, Any]] | None, filters: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use three-valued AND; a definite false excludes even if another value is unknown."""
    filters = filters or []  # Legacy SQL NULL is the original unfiltered behavior.
    counts = {'filters': filters, 'source_count': None, 'matched_count': None,
              'excluded_count': None, 'undetermined_count': None}
    if rows is None:
        return [], counts
    counts.update(source_count=len(rows), matched_count=0, excluded_count=0, undetermined_count=0)
    selected = []
    for row in rows:
        matches = [_matches(row, condition) for condition in filters]
        if False in matches:
            counts['excluded_count'] += 1
        elif None in matches:
            counts['undetermined_count'] += 1
        else:
            counts['matched_count'] += 1
            selected.append(row)
    return selected, counts
