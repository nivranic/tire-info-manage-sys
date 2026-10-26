"""Explicit workload planning from frozen manual price versions; no Provider calls."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, Request
from pydantic import ConfigDict, Field, StrictInt, field_validator, model_validator
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError

from .ai_pricing_models import AIPriceVersion
from .auth import current_user, make_admin_guard, require_admin
from .db import utc, utcnow
from .domain import StrictModel, digest
from .service import QueryService

RATE_PATTERN = re.compile(r'(0|[1-9][0-9]{0,8})(\.[0-9]{1,8})?')
TIME_PATTERN = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z')
UUID_PATTERN = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
FORMULA = ('request_count * (input_tokens_per_request * input_per_million + '
           'output_tokens_per_request * output_per_million) / 1000000')
EXCLUSIONS = ('cached_input', 'tools', 'long_context', 'images_audio_video', 'tax', 'fx', 'supplier_adjustments')
NOTICE = '仅按所选人工价格规划标准文本费用，来源未在线核验；结果不是实际消费、供应商账单或金额硬预算。'
INVALID_REQUEST_MESSAGE = '费用规划请求格式不正确，请核对填写内容。'


def timestamp(value):
    return utc(value).isoformat().replace('+00:00', 'Z') if value is not None else None


def parse_time(value):
    if type(value) is not str or not TIME_PATTERN.fullmatch(value):
        raise ValueError('时间必须为含秒的 UTC Z 格式，最多六位小数秒')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('时间日历值不正确') from None


def uuid_string(value):
    if type(value) is not str or not UUID_PATTERN.fullmatch(value):
        raise ValueError('必须为标准 UUID 字符串')
    return str(UUID(value))


def fail(code, message, status=422, *, item_index=None):
    detail = {'code': code, 'message': message}
    if item_index is not None:
        detail['item_index'] = item_index
    raise HTTPException(status, detail)


class PricingRequest(StrictModel):
    # StrictModel normally strips every string. Prices, exact models and dates
    # must be checked as submitted, and only human prose is trimmed explicitly.
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)


class AIPriceVersionCreate(PricingRequest):
    vendor_label: str = Field(min_length=1, max_length=100)
    provider: Literal['openai_responses', 'openai_chat', 'anthropic', 'openai_embeddings']
    model: str = Field(min_length=1, max_length=120, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$')
    currency: str = Field(min_length=3, max_length=3, pattern=r'^[A-Z]{3}$')
    input_per_million: str = Field(max_length=18)
    output_per_million: str = Field(max_length=18)
    source_note: str = Field(min_length=1, max_length=1000)
    source_url: str | None = Field(max_length=2048)
    effective_from: str
    effective_until: str | None

    @field_validator('vendor_label', 'source_note', mode='before')
    @classmethod
    def trim_prose(cls, value):
        return value.strip() if type(value) is str else value

    @field_validator('input_per_million', 'output_per_million', mode='before')
    @classmethod
    def plain_rate(cls, value):
        if type(value) is not str or not RATE_PATTERN.fullmatch(value):
            raise ValueError('费率必须为非负普通十进制字符串，最多九位整数和八位小数')
        return value

    @field_validator('model', mode='before')
    @classmethod
    def exact_model(cls, value):
        if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,119}', value):
            raise ValueError('模型标识格式不正确')
        return value

    @field_validator('effective_from', 'effective_until', mode='before')
    @classmethod
    def utc_time(cls, value):
        return timestamp(parse_time(value)) if value is not None else None

    @field_validator('source_url', mode='before')
    @classmethod
    def source_reference(cls, value):
        if value is None:
            return None
        if (type(value) is not str or '\\' in value
                or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError('来源链接必须为无凭据的绝对 HTTP(S) URL')
        try:
            parts = urlsplit(value)
            if (parts.scheme not in ('http', 'https') or not parts.hostname
                    or parts.username is not None or parts.password is not None):
                raise ValueError
            _port = parts.port
        except ValueError:
            raise ValueError('来源链接必须为无凭据的绝对 HTTP(S) URL') from None
        return value

    @model_validator(mode='after')
    def valid_version(self):
        if self.effective_until is not None and parse_time(self.effective_until) <= parse_time(self.effective_from):
            raise ValueError('价格结束时间必须晚于开始时间')
        if self.provider == 'openai_embeddings' and Decimal(self.output_per_million) != 0:
            raise ValueError('Embeddings 的输出费率必须为零')
        return self


class AIPricePlanningItem(PricingRequest):
    price_version_id: str
    request_count: StrictInt = Field(ge=1, le=1_000_000)
    input_tokens_per_request: StrictInt = Field(ge=0, le=100_000_000)
    output_tokens_per_request: StrictInt = Field(ge=0, le=100_000_000)

    @field_validator('price_version_id', mode='before')
    @classmethod
    def exact_version(cls, value):
        return uuid_string(value)


class AIPricePlanningRequest(PricingRequest):
    planned_for: str
    items: list[AIPricePlanningItem] = Field(min_length=1, max_length=50)

    @field_validator('planned_for', mode='before')
    @classmethod
    def utc_time(cls, value):
        return timestamp(parse_time(value))


def version_view(row):
    # Deliberate allowlist: session cookie identity, key and hash stay private.
    return {'id': row.id, 'vendor_label': row.vendor_label, 'provider': row.provider,
            'model': row.model, 'currency': row.currency, 'input_per_million': row.input_per_million,
            'output_per_million': row.output_per_million, 'source_note': row.source_note,
            'source_url': row.source_url, 'effective_from': timestamp(row.effective_from),
            'effective_until': timestamp(row.effective_until), 'recorded_at': timestamp(row.recorded_at),
            'actor_user_id': row.actor_user_id}


def _replay(db, actor_user_id, key, request_hash):
    row = db.scalar(select(AIPriceVersion).where(AIPriceVersion.actor_user_id == actor_user_id,
                                               AIPriceVersion.idempotency_key == key))
    if row is not None and row.request_hash != request_hash:
        fail('ai_price_idempotency_conflict', '此幂等键已用于不同价格内容。', 409)
    return row


def create_version(db, payload, request, idempotency_key):
    try:
        key = uuid_string(idempotency_key)
    except ValueError:
        fail('ai_price_invalid_request', INVALID_REQUEST_MESSAGE)
    QueryService(db, None).lock_ingestion()
    require_admin(request, db)
    actor_user_id = current_user(db, request.state.session_id).id
    values = payload.model_dump()
    request_hash = digest(values)
    previous = _replay(db, actor_user_id, key, request_hash)
    if previous is not None:
        return version_view(previous)
    row = AIPriceVersion(**{**values, 'effective_from': parse_time(values['effective_from']),
        'effective_until': parse_time(values['effective_until']) if values['effective_until'] else None},
        actor_user_id=actor_user_id, actor_session_id=request.state.session_id,
        idempotency_key=key, request_hash=request_hash)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = _replay(db, actor_user_id, key, request_hash)
        if previous is not None:
            return version_view(previous)
        fail('ai_price_write_conflict', '价格记录发生写入冲突，请重试。', 409)
    return version_view(row)


def exact_string(value):
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def plan_prices(db, payload):
    planned_for = parse_time(payload.planned_for)
    selected = []
    # Validate every row before computing any amount. Missing prices are errors.
    for index, item in enumerate(payload.items):
        row = db.get(AIPriceVersion, item.price_version_id)
        if row is None:
            fail('ai_price_version_not_found', '所选价格版本不存在。', 404, item_index=index)
        if (planned_for < utc(row.effective_from)
                or row.effective_until is not None and planned_for >= utc(row.effective_until)):
            fail('ai_price_version_not_effective', '所选价格版本不覆盖规划时点。', 409, item_index=index)
        if row.provider == 'openai_embeddings' and item.output_tokens_per_request != 0:
            fail('ai_price_invalid_request', INVALID_REQUEST_MESSAGE, item_index=index)
        selected.append(row)
    results = []
    with localcontext() as context:
        context.prec = 80
        for index, (item, row) in enumerate(zip(payload.items, selected, strict=True)):
            count = Decimal(item.request_count)
            input_total = count * Decimal(item.input_tokens_per_request) * Decimal(row.input_per_million) / Decimal(1_000_000)
            output_total = count * Decimal(item.output_tokens_per_request) * Decimal(row.output_per_million) / Decimal(1_000_000)
            total = input_total + output_total
            results.append({'item_index': index, 'price_version': version_view(row),
                'request_count': item.request_count, 'input_tokens_per_request': item.input_tokens_per_request,
                'output_tokens_per_request': item.output_tokens_per_request,
                'exact_input_total': exact_string(input_total), 'exact_output_total': exact_string(output_total),
                'exact_total': exact_string(total),
                'rounded_total': format(total.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP), 'f'),
                'formula': FORMULA})
    return {'planned_for': payload.planned_for, 'calculated_at': timestamp(utcnow()),
            'calculation_version': 'standard-text-v1', 'scale': 6, 'rounding': 'ROUND_HALF_UP',
            'items': results, 'exclusions': list(EXCLUSIONS), 'notice': NOTICE}


def register_ai_pricing_routes(app):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    def login_guard(request: Request, db=Depends(get_db)):
        if current_user(db, request.state.session_id) is None:
            fail('login_required', '费用规划需要先登录。', 401)

    admin_guard = make_admin_guard(get_db)

    @app.get('/v1/ai/price-versions', dependencies=[Depends(login_guard)])
    def versions(offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=25), db=Depends(get_db)):
        rows = db.scalars(select(AIPriceVersion).order_by(desc(AIPriceVersion.recorded_at),
            desc(AIPriceVersion.id)).offset(offset).limit(limit + 1)).all()
        has_more = len(rows) > limit
        return {'items': [version_view(row) for row in rows[:limit]], 'offset': offset, 'limit': limit,
                'has_more': has_more, 'next_offset': offset + limit if has_more else None}

    @app.post('/v1/ai/price-versions', dependencies=[Depends(admin_guard)])
    def create(payload: AIPriceVersionCreate, request: Request,
               idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return create_version(db, payload, request, idempotency_key)

    @app.post('/v1/ai/price-planning', dependencies=[Depends(login_guard)])
    def planning(payload: AIPricePlanningRequest, db=Depends(get_db)):
        return plan_prices(db, payload)
