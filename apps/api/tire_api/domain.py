"""Small, explicit domain boundary. Unknown technical attributes remain unknown."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from .query_filters import MAX_CONDITIONS, TireFilter, canonical_filters

IDENTITY_CONTRACT_VERSION = 'variant-identity@2'


def product_code_namespace(value: Any) -> str | None:
    """An explicit source identifier namespace; never infer it from a code or source."""
    if value is None:
        return None
    if (type(value) is not str or not value or value != value.strip()
            or len(value) > 100 or not value.isprintable()):
        raise ValueError('产品代码类型必须是明确的非空字符串或null，不能包含空白边界或控制字符')
    return value


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def parse_size(value: str) -> str:
    """Accept passenger metric sizes only; never silently erase ZR construction."""
    compact = re.sub(r"\s+", "", value.upper())
    match = re.fullmatch(r"(\d{3})/(\d{2})(ZR|R)(\d{2}(?:\.5)?)", compact)
    if not match:
        raise ValueError("尺寸必须是公制乘用车格式，例如 265/40R20 或 265/40ZR20")
    width, aspect, construction, rim = match.groups()
    if not (100 <= int(width) <= 455 and 20 <= int(aspect) <= 95 and 10 <= float(rim) <= 30):
        raise ValueError("尺寸超出当前乘用车 / SUV 支持范围")
    return f"{int(width)}/{int(aspect)}{construction}{rim}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TireQuery(StrictModel):
    size: str | None = Field(default=None, max_length=24)
    model: str | None = Field(default=None, max_length=120)

    @field_validator("size")
    @classmethod
    def normalize_size(cls, value: str | None) -> str | None:
        return parse_size(value) if value else None

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str | None) -> str | None:
        if not value:
            return None
        normalized = " ".join(value.split())
        alias = re.sub(r"^michelin\s+", "", normalized.casefold())
        return {"psev": "Pilot Sport EV", "pilot sport ev": "Pilot Sport EV",
                "ps4s": "Pilot Sport 4 S", "pilot sport 4 s": "Pilot Sport 4 S"}.get(alias, normalized)

    @model_validator(mode="after")
    def require_query(self) -> TireQuery:
        if not self.size and not self.model:
            raise ValueError("请提供轮胎尺寸或型号")
        return self

    def canonical(self) -> dict[str, str]:
        return self.model_dump(exclude_none=True)


class LiveQueryRequest(StrictModel):
    query: TireQuery
    filters: list[TireFilter] = Field(default_factory=list, max_length=MAX_CONDITIONS)
    fallback_policy: Literal["ask", "never"] = "ask"
    consent_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("filters")
    @classmethod
    def normalize_filters(cls, values: list[TireFilter]) -> list[TireFilter]:
        return [TireFilter.model_validate(value) for value in canonical_filters(values)]


class ConsentRequest(StrictModel):
    query_id: str = Field(min_length=1, max_length=64)
    decision: Literal["allow", "deny"]
    scope: Literal["once"] = "once"


class CompareRequest(StrictModel):
    variant_ids: list[str] = Field(min_length=1, max_length=6)
    include_manual: StrictBool = False
    resolve_identities: StrictBool = False

    @field_validator("variant_ids")
    @classmethod
    def unique_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(not value or len(value) > 64 for value in values):
            raise ValueError("比较项必须是 1–6 个不同的版本 ID")
        return values


class WatchRequest(StrictModel):
    variant_id: str = Field(min_length=1, max_length=64)


class VariantInput(StrictModel):
    brand: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200)
    manufacturer_product_code: str | None = Field(default=None, max_length=100)
    region: str = Field(min_length=1, max_length=40)
    size: str = Field(max_length=24)
    load_index: str | None = Field(default=None, max_length=12)
    speed_rating: str | None = Field(default=None, max_length=12)
    xl: StrictBool | None = None
    hl: StrictBool | None = None
    oe_mark: str | None = Field(default=None, max_length=100)
    acoustic_technology: str | None = Field(default=None, max_length=100)
    run_flat: StrictBool | None = None
    source_variant_name: str | None = Field(default=None, max_length=400)
    facts: dict[str, Any] = Field(default_factory=dict)

    @field_validator("manufacturer_product_code")
    @classmethod
    def valid_product_code(cls, value: str | None) -> str | None:
        if value is not None and (not value or not value.isprintable()):
            raise ValueError('产品代码必须是非空可打印字符串；未知使用null')
        return value

    @field_validator("size")
    @classmethod
    def normalize_size(cls, value: str) -> str:
        return parse_size(value)

    @field_validator("load_index", mode="before")
    @classmethod
    def normalize_load_index(cls, value: Any) -> str | None:
        if isinstance(value, int) and not isinstance(value, bool):
            value = str(value)
        if value is not None and not re.fullmatch(r"\d{2,3}(?:/\d{2,3})?", value):
            raise ValueError("载重指数格式无效")
        return value

    @field_validator("speed_rating")
    @classmethod
    def normalize_speed(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.upper()
            if value not in {"A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "B", "C", "D", "E", "F", "G", "J", "K", "L", "M", "N", "P", "Q", "R", "S", "T", "U", "H", "V", "W", "Y", "(Y)", "ZR"}:
                raise ValueError("速度级别无效")
        return value

    @field_validator("facts")
    @classmethod
    def bounded_json_facts(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 100 or len(stable_json(value)) > 100_000:
            raise ValueError("事实集合超过限制")
        product_code_namespace(value.get('product_code_type'))
        return value

    def legacy_identity(self) -> dict[str, Any]:
        """Reproduce the original projection only to verify immutable old evidence."""
        identity = self.model_dump(exclude={"facts", "source_variant_name"})
        for key in ("gtin", "technology_features", "eprel_id"):
            if self.facts.get(key) is not None:
                value = self.facts[key]
                identity[key] = sorted(value, key=stable_json) if isinstance(value, list) else value
        return identity

    def legacy_identity_key(self, source_id: str, query_key: str, row_index: int) -> tuple[str, str]:
        """Do not use this key for new ingestion, merging or current identity claims."""
        identity = self.legacy_identity()
        if all(value is not None for value in identity.values()):
            return digest(identity), "complete"
        scope: dict[str, Any] = {"source_id": source_id, "identity": identity}
        if not self.manufacturer_product_code:
            scope.update(query_key=query_key, source_variant_name=self.source_variant_name, row_index=row_index)
        return digest(scope), "source_scoped"

    def identity(self) -> dict[str, Any]:
        return {**self.legacy_identity(), 'product_code_type': product_code_namespace(self.facts.get('product_code_type'))}

    def identity_key(self, source_id: str, query_key: str, row_index: int) -> tuple[str, str]:
        identity = self.identity()
        if self.manufacturer_product_code and all(value is not None for value in identity.values()):
            return digest({'contract': IDENTITY_CONTRACT_VERSION, 'identity': identity}), 'complete'
        scope: dict[str, Any] = {'contract': IDENTITY_CONTRACT_VERSION, 'source_id': source_id, 'identity': identity}
        # With no namespace the same code may refer to different identifier systems,
        # even within one source. Preserve each query/row's provisional observation.
        if not self.manufacturer_product_code or identity['product_code_type'] is None:
            scope.update(query_key=query_key, source_variant_name=self.source_variant_name, row_index=row_index)
        return digest(scope), 'source_scoped'
