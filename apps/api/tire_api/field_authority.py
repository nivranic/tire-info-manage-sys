"""Deterministic display policy over caller-authorized evidence, never a facts writer."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import math
from pathlib import Path

from .domain import digest

POLICY_VERSION = 'field-authority@1'
ALIASES = {'treadwear': 'utqg_treadwear', 'traction': 'utqg_traction', 'temperature': 'utqg_temperature'}
IDENTITY_FIELDS = {'brand', 'model', 'region', 'size', 'manufacturer_product_code', 'product_code_type',
                   'gtin', 'eprel_id', 'load_index', 'speed_rating', 'xl', 'hl', 'oe_mark',
                   'acoustic_technology', 'run_flat', 'technology_features'}
SOURCE_SCOPED = {'for_sale', 'price', 'inventory', 'stock'}
NOTICE = ('默认值仅是所声明证据范围内的展示选择，不修改来源事实、人工值或SKU身份；'
          '有偏好的冲突仍须保留。核验时间不等于新事实的发布时间。')

# Explicit field domains: evidence locators, parser metadata and arbitrary names
# cannot accidentally become a technical conflict or acquire authority.
FIELD_SPECS = {
    'brand': ('品牌', '', 'sku'), 'model': ('型号', '', 'sku'),
    'region': ('地区', '', 'sku'), 'size': ('尺寸', '', 'specification'),
    'manufacturer_product_code': ('厂商产品代码', '', 'sku'),
    'product_code_type': ('产品代码类型', '', 'sku'), 'gtin': ('GTIN', '', 'sku'),
    'eprel_id': ('EPREL 记录', '', 'eu_label'),
    'load_index': ('载重指数', '', 'specification'), 'speed_rating': ('速度级别', '', 'specification'),
    'xl': ('XL', '', 'specification'), 'hl': ('HL', '', 'specification'),
    'oe_mark': ('OE 标记', '', 'oe_fitment'), 'oe_vehicle_scope': ('OE 车型范围', '', 'oe_fitment'),
    'acoustic_technology': ('静音技术', '', 'sku_technology'),
    'run_flat': ('防爆', '', 'sku_technology'), 'technology_features': ('技术配置', '', 'sku_technology'),
    'ev_marketing': ('EV 标识', '', 'sku_technology'),
    'utqg_treadwear': ('UTQG 磨耗指数', '', 'utqg'),
    'utqg_traction': ('UTQG 牵引力等级', '', 'utqg'),
    'utqg_temperature': ('UTQG 耐热等级', '', 'utqg'),
    'eu_fuel_class': ('欧盟能效等级', '', 'eu_label'), 'eu_wet_grip': ('欧盟湿地抓地等级', '', 'eu_label'),
    'eu_external_noise_db': ('欧盟外部滚动噪声', 'dB', 'eu_label'),
    'eu_noise_class': ('欧盟噪声等级', '', 'eu_label'),
    'noise_db': ('来源声明外部噪声', 'dB', 'specification'),
    'weight_lb': ('重量', 'lb', 'specification'), 'weight_kg': ('重量', 'kg', 'specification'),
    'max_load_lb': ('最大载重', 'lb', 'specification'), 'max_load_kg': ('最大载重', 'kg', 'specification'),
    'max_pressure_psi': ('最大胎压', 'psi', 'specification'),
    'overall_diameter_in': ('外径', 'in', 'specification'),
    'overall_width_in': ('断面宽度', 'in', 'specification'),
    'revolutions_per_mile': ('每英里转数', '', 'specification'),
    'recommended_rim_width_in': ('推荐轮辋宽度', 'in', 'specification'),
    'rim_width_range_in': ('轮辋宽度范围', 'in', 'specification'),
    'tread_depth': ('胎纹深度', '', 'specification'), 'ply_rating': ('层级', '', 'specification'),
    'warranty_miles': ('里程质保', 'mile', 'specification'),
    'manufacturing_origin': ('制造地', '', 'specification'), 'season': ('季节', '', 'specification'),
    'for_sale': ('来源标记在售', '', 'availability'), 'price': ('报价', '', 'commerce'),
    'inventory': ('库存', '', 'commerce'), 'stock': ('库存状态', '', 'commerce'),
}
CATEGORIES = {
    'eu_label': ('EU Label', {'regulatory': 1, 'manufacturer_official': 2}),
    'utqg': ('UTQG', {'manufacturer_official': 1, 'high_quality_distributor': 2}),
    'sku': ('产品代码与SKU', {'manufacturer_official': 1, 'oem_fitment': 2, 'authorized_retailer': 2}),
    'oe_fitment': ('OE适配', {'oem_fitment': 1, 'manufacturer_official': 2}),
    'sku_technology': ('具体SKU技术', {'manufacturer_official': 1, 'oem_fitment': 2}),
    'specification': ('厂商规格', {'manufacturer_official': 1, 'high_quality_distributor': 2}),
    'availability': ('来源自身在售声明', {'manufacturer_official': 1, 'authorized_retailer': 1}),
    'commerce': ('价格与库存', {'authorized_retailer': 1, 'official_store': 2}),
    'recall': ('召回', {'regulatory': 1, 'oem_fitment': 1, 'manufacturer_official': 2}),
    'independent_test': ('独立性能测试', {'original_test_organization': 1, 'professional_media': 2}),
    'commissioned_test': ('厂商委托测试', {'commissioned_lab_report': 1, 'manufacturer_official': 2}),
}


def canonical_field(field):
    return ALIASES.get(field, field)


def policy_descriptor():
    return {'version': POLICY_VERSION, 'digest': digest({
        'code': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'categories': CATEGORIES, 'fields': FIELD_SPECS, 'aliases': ALIASES,
        'identity_fields': sorted(IDENTITY_FIELDS), 'source_scoped': sorted(SOURCE_SCOPED)})}


def policy_catalog():
    fields = []
    for field in sorted(set(FIELD_SPECS) | set(ALIASES)):
        canonical = canonical_field(field)
        label, unit, category = FIELD_SPECS[canonical]
        fields.append({'field': field, 'canonical_field': canonical, 'label': label, 'unit': unit,
                       'category': category, 'identity_bound': canonical in IDENTITY_FIELDS,
                       'source_scope_only': canonical in SOURCE_SCOPED})
    return {'policy': policy_descriptor(), 'fields': fields,
            'information_categories': [{'id': key, 'label': label, 'source_tiers': deepcopy(tiers),
                'projection_available': any(spec[2] == key for spec in FIELD_SPECS.values())}
                for key, (label, tiers) in CATEGORIES.items()],
            'criteria': ['字段权威等级', '精确SKU或本次明确采用的有效合并', '地区匹配',
                         '可靠发表时间或原文观察时间', '字段证据完整度'],
            'coverage': '当前投影为已接入轮胎参数；规则目录不表示监管、零售或测试来源已接入。',
            'notice': NOTICE}


def source_authority(field, source_class, *, sku_specific=False):
    field = canonical_field(field)
    if field not in FIELD_SPECS:
        return {'tier': None, 'rule': 'field_not_supported', 'explanation': '该字段尚无可核对的权威规则'}
    category = FIELD_SPECS[field][2]
    if category == 'sku_technology' and not sku_specific:
        return {'tier': None, 'rule': 'sku_evidence_required', 'explanation': '技术声明缺少具体SKU字段证据，不按官方SKU参数加权'}
    label, tiers = CATEGORIES[category]
    tier = tiers.get(source_class)
    return {'tier': tier, 'rule': category + ':' + (source_class if tier else 'unclassified'),
            'explanation': f'{label}采用已登记来源类别的第{tier}层依据' if tier else
                           f'{label}的来源权威层级未确认；不根据来源名称或人工填写的组织名称推断'}


def _value_key(value):
    if value is None:
        return ('null',)
    if type(value) is bool:
        return ('boolean', value)
    if type(value) in (int, float):
        if type(value) is float and not math.isfinite(value):
            raise ValueError('Non-finite evidence number')
        # Decimal equality preserves JSON number semantics without context-based
        # rounding of long integers; bool already took its own branch above.
        return ('number', Decimal(str(value)))
    if isinstance(value, str):
        return ('string', value)
    if isinstance(value, list):
        return ('array', tuple(_value_key(item) for item in value))
    if isinstance(value, dict):
        return ('object', tuple((key, _value_key(item)) for key, item in sorted(value.items())))
    raise ValueError('Evidence values must be JSON values')


def evidence_value_key(value):
    """Hashable comparison key, not a wire value; never coerce bool or strings."""
    return _value_key(value)


def known_values_differ(values):
    """Unknown is an evidence gap, rather than an opposing factual value."""
    return len({_value_key(value) for value in values if value is not None}) > 1


def _time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _evaluate(raw, variant_id):
    item = deepcopy(raw)
    item['source_field'] = raw.get('source_field', raw['field'])
    item['field'] = canonical_field(raw['field'])
    item.setdefault('id', digest({key: value for key, value in raw.items() if key != 'id'}))
    item['present'] = raw.get('present') is True
    item.setdefault('value', None)
    _value_key(item['value'])
    exclusions = []
    identity = item.get('identity_match', 'unverified')
    region = item.get('region_match', 'unverified')
    if identity not in {'exact', 'reviewed_merge'}:
        exclusions.append('精确SKU身份尚未核对或不匹配')
    if identity == 'reviewed_merge' and not item.get('equivalence_event_id'):
        exclusions.append('缺少本次明确采用的有效合并记录')
    if item.get('variant_id') != variant_id and identity != 'reviewed_merge':
        exclusions.append('不同实体未取得本次显式合并依据')
    if region != 'exact':
        exclusions.append('地区尚未核对或不匹配')
    if item.get('evidence_valid') is not True:
        exclusions.append('正式证据完整性校验未通过')
    if item.get('source_conflicted') is True:
        exclusions.append('来源自身对该字段存在矛盾，不能默选其中一个值')
    if not item['present'] or item['value'] is None:
        exclusions.append('字段未提供' if not item['present'] else '来源明确未知')
    authority = source_authority(item['field'], item.get('source_class', 'unclassified'),
                                 sku_specific=item.get('sku_specific') is True)
    observed, published = _time(item.get('observed_at')), _time(item.get('published_at'))
    # A publication time later than receipt cannot establish content freshness.
    use_published = published is not None and observed is not None and published <= observed
    chosen = published if use_published else observed
    missing = sorted(set(item.get('missing_evidence') or []))
    if not item.get('evidence_locator') and 'field_locator' not in missing:
        missing.append('field_locator')
    item.update(eligible=not exclusions, exclusion_reasons=exclusions, authority=authority,
        dimensions={'authority': authority,
            'identity': {'match': identity, 'explanation': '保留原实体引用；仅本次有效合并可作为明确的展示分组依据'},
            'region': {'match': region, 'source_region': item.get('source_region'), 'explanation': '不同地区版本不自动比较成同一SKU'},
            'time': {'ranked_at': chosen.isoformat() if chosen else None,
                'basis': 'published_at' if use_published else 'observed_at' if observed else 'unknown',
                'verified_at': item.get('verified_at'), 'verification_used_for_rank': False},
            'evidence': {'valid': item.get('evidence_valid') is True, 'missing': sorted(missing),
                'explanation': '核对正式原文、字段定位和出处；不以摘录长度或虚构概率代替证据'}})
    rank = (authority['tier'] or 999, 0 if identity == 'exact' else 1,
            0 if region == 'exact' else 1, -chosen.timestamp() if chosen else float('inf'), len(missing))
    return item, rank


def resolve_fields(candidates, *, variant_id, scope, data_state='local_snapshot'):
    groups = {}
    seen = {}
    for raw in candidates:
        field = canonical_field(raw['field'])
        if field not in FIELD_SPECS:
            continue
        item, rank = _evaluate(raw, variant_id)
        fingerprint = digest(item)
        if item['id'] in seen:
            if seen[item['id']] != fingerprint:
                raise ValueError('Candidate identifier has conflicting evidence')
            continue
        seen[item['id']] = fingerprint
        groups.setdefault(field, []).append((item, rank))
    fields = []
    for field, entries in sorted(groups.items()):
        entries.sort(key=lambda pair: pair[0]['id'])
        items = [item for item, _rank in entries]
        eligible = [(item, rank) for item, rank in entries if item['eligible']]
        sources = {item.get('source_id') for item in items}
        reasons = []
        if field in SOURCE_SCOPED and len(sources) > 1:
            eligible = []
            for item in items:
                item['eligible'] = False
                item['exclusion_reasons'].append('不同来源的交易范围尚未对应同一Offering')
            reasons.append('在售、报价或库存属于各来源的交易范围；尚未建立同一Offering，不能当作SKU参数冲突或跨来源默认值')
        values = {_value_key(item['value']) for item, _rank in eligible}
        source_conflict = any(item.get('source_conflicted') is True for item in items)
        defaults = []
        if eligible:
            best = min(rank for _item, rank in eligible)
            leaders = [item for item, rank in eligible if rank == best]
            if len({_value_key(item['value']) for item in leaders}) == 1:
                defaults = leaders
                state = 'conflict_preferred' if len(values) > 1 or source_conflict else 'uncontested'
                reasons.append('按字段权威、SKU、地区、内容时间和证据完整度逐层比较；并列相同值共同支持默认展示')
            else:
                state = 'conflict_tied'
                reasons.append('最高层级候选仍有不同取值，没有可核对的依据继续区分；不按ID或输入顺序选择')
        elif source_conflict:
            state = 'conflict_tied'
            reasons.append('来源内部存在矛盾且没有可用的默认候选')
        elif all(not item['present'] or item['value'] is None for item in items):
            state = 'unknown'
            reasons.append('仅有缺失或明确未知，不与其它已知值构造事实冲突')
        else:
            state = 'unavailable'
            if not reasons:
                reasons.append('候选不满足身份、地区或证据条件，保留记录但不给默认值')
        if any(not item['present'] or item['value'] is None for item in items):
            reasons.append('缺失与明确未知分别保留；它们不是反对已知值的证据')
        if state == 'conflict_preferred':
            reasons.append('默认展示偏好不表示冲突已解决，仍需核对全部来源')
        label, unit, category = FIELD_SPECS[field]
        fields.append({'field': field, 'label': label, 'unit': unit, 'category': category,
            'identity_bound': field in IDENTITY_FIELDS, 'source_scope_only': field in SOURCE_SCOPED,
            'state': state, 'has_default': bool(defaults),
            'default_value': deepcopy(defaults[0]['value']) if defaults else None,
            'default_candidate_ids': [item['id'] for item in defaults], 'candidates': items, 'reasons': reasons})
    result = {'policy': policy_descriptor(), 'variant_id': variant_id, 'scope': scope,
              'data_state': data_state, 'fields': fields, 'notice': NOTICE}
    return {**result, 'fingerprint': digest(result)}
