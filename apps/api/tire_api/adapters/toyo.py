"""Toyo US public product-page specification resource; never execute page scripts.

The product pages explicitly link these JSON resources through #Specs[data-url].
The resources are outside the site's robots-disallowed /specs/ subtree.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from ..domain import parse_size

PARSER_VERSION = "toyo-us-specifications@1.1.0"
_MODELS = {"PXSP": "Proxes Sport", "PXAS": "Proxes Sport A/S"}
SOURCE_CONFIG = {
    "id": "toyo-us", "name": "东洋 · 美国官网", "region": "US",
    "origin": "https://www.toyotires.com", "status": "ready",
    "model_urls": {
        "Proxes Sport": "https://www.toyotires.com/tire/pattern/specs/PXSP",
        "Proxes Sport A/S": "https://www.toyotires.com/tire/pattern/specs/PXAS",
    },
    "product_page_urls": {
        "Proxes Sport": "https://www.toyotires.com/product/proxes-sport/",
        "Proxes Sport A/S": "https://www.toyotires.com/product/proxes-sport-as/",
    },
    "content_types": ("application/json",), "parser_version": PARSER_VERSION,
    "description": "Proxes Sport / Sport A/S 官方规格：产品代码、EAN、载重速度、XL 和逐 SKU UTQG。",
}


def _error() -> ValueError:
    return ValueError("parser_schema_changed")


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error()
    return value.strip()


def _number(value: Any) -> float:
    if type(value) not in (str, int, float):
        raise _error()
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise _error() from None
    if not math.isfinite(result) or result < 0:
        raise _error()
    return result


def _model(value: str) -> str:
    value = re.sub(r"[^a-z0-9]", "", value.casefold())
    return value.removeprefix("toyotires").removeprefix("toyo")


def _row(row: Any, index: int) -> dict[str, Any]:
    if not isinstance(row, dict) or row.get("pattern_id") not in _MODELS:
        raise _error()
    code = _text(row.get("product_code"))
    if not re.fullmatch(r"[0-9]{1,20}", code):
        raise _error()
    size = parse_size(_text(row.get("tire_size")))
    service = _text(row.get("load_index_ss")).upper()
    match = re.fullmatch(r"([0-9]{2,3})([A-Z]|\(Y\)|A[1-8])", service)
    if not match:
        raise _error()
    load_id = row.get("load_range_pr")
    if load_id not in (None, "", "SL", "XL"):
        raise _error()
    if row.get("rd_xl") not in (None, "", load_id):
        raise _error()
    base = f"$.data.tires[{index}]"
    spans = {
        "manufacturer_product_code": f"{base}.product_code",
        "model": f"{base}.pattern_id (official product-page pattern mapping)",
        "size": f"{base}.tire_size", "load_index": f"{base}.load_index_ss",
        "speed_rating": f"{base}.load_index_ss", "source_variant_name": f"{base}.product_name",
    }
    facts: dict[str, Any] = {}

    def fact(name: str, value: Any, field: str) -> None:
        facts[name] = value
        spans[f"facts.{name}"] = f"{base}.{field}"

    fact('product_code_type', 'PRODUCT_CODE', 'product_code')
    fact("service_description", service, "load_index_ss")
    if load_id:
        fact("load_id", load_id, "load_range_pr")
        spans["xl"] = f"{base}.load_range_pr"
    if row.get("ean") not in (None, ""):
        gtin = _text(row["ean"])
        if not re.fullmatch(r"(?:[0-9]{8}|[0-9]{12,14})", gtin):
            raise _error()
        fact("gtin", gtin, "ean")
    if row.get("utqg") not in (None, ""):
        utqg = re.fullmatch(r"([0-9]{2,4})\s+(AA|A|B|C)\s+(A|B|C)", _text(row["utqg"]))
        if not utqg:
            raise _error()
        for name, value in zip(("utqg_treadwear", "utqg_traction", "utqg_temperature"),
                               (int(utqg[1]), utqg[2], utqg[3])):
            fact(name, value, "utqg")
    for field, name in (("weight__lbs__", "weight_lb"), ("max_load_single", "max_load_lb"),
                        ("max_psi_single", "max_pressure_psi"), ("oad", "overall_diameter_in"),
                        ("oaw", "overall_width_in"), ("revs_mile", "revolutions_per_mile")):
        if row.get(field) not in (None, ""):
            fact(name, _number(row[field]), field)
    if row.get("tread_depth") not in (None, ""):
        fact("tread_depth", {"unit": "1/32 in", "value": _number(row["tread_depth"])}, "tread_depth")
    for field, name in (("rim_width", "rim_width_range_in"), ("sidewall", "sidewall_code"),
                        ("tread_construction", "tread_construction"),
                        ("sidewall_construction", "sidewall_construction")):
        if row.get(field) not in (None, ""):
            fact(name, _text(row[field]), field)
    if row.get("for_sale") not in (None, ""):
        if row["for_sale"] not in ("Y", "N"):
            raise _error()
        fact("for_sale", row["for_sale"] == "Y", "for_sale")
    facts["evidence_spans"] = spans
    return {"brand": "Toyo", "model": _MODELS[row["pattern_id"]], "region": "US",
            "manufacturer_product_code": code, "size": size, "load_index": match[1],
            "speed_rating": match[2], "xl": None if not load_id else load_id == "XL",
            "hl": None, "oe_mark": None, "acoustic_technology": None, "run_flat": None,
            "source_variant_name": _text(row.get("product_name")), "facts": facts}


def parse_html(body: str, query: dict) -> list[dict]:
    """Parse only the fixed official JSON specifications resource, despite API name."""
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise _error()
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("layout"), list):
            raise _error()
        rows = data.get("tires")
        if not isinstance(rows, list) or not rows or len(rows) > 500:
            raise _error()
        variants = [_row(row, index) for index, row in enumerate(rows)]
        if len({row["model"] for row in variants}) != 1:
            raise _error()
        codes = [row["manufacturer_product_code"] for row in variants]
        if len(codes) != len(set(codes)):
            raise _error()
    except (TypeError, KeyError, ValueError, RecursionError, OverflowError):
        raise _error() from None
    if query.get("model") is not None:
        if not isinstance(query["model"], str) or _model(query["model"]) != _model(variants[0]["model"]):
            return []
    if query.get("size") is not None:
        try:
            size = parse_size(query["size"]).replace("ZR", "R")
        except (ValueError, TypeError, AttributeError):
            return []
        variants = [row for row in variants if row["size"].replace("ZR", "R") == size]
    return variants


parse_toyo_json = parse_html
