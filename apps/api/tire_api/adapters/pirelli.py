"""Pirelli US PZ4 size-page Flight data, parsed as literals without executing JS.

Only a requested public metric-size page is fetched. Marketing/model-wide
technologies, the selected DOM row and remote Flight references are not SKU data.
"""
from __future__ import annotations

import json
import math
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from ..domain import parse_size

PARSER_VERSION = "pirelli-us-pz4-flight@1.1.0"
MODEL = "P ZERO (PZ4)"
ORIGIN = "https://www.pirelli.com"
BASE_PATH = "/tires/en-us/car/catalog/product/new-p-zero"
SOURCE_CONFIG = {
    "id": "pirelli-us", "name": "倍耐力 · 美国官网", "region": "US",
    "origin": ORIGIN, "status": "ready", "requires_size": True,
    "model_urls": {MODEL: ORIGIN + BASE_PATH},
    "content_types": ("text/html",), "parser_version": PARSER_VERSION,
    "description": "P ZERO (PZ4) 美国公开尺寸页：逐 SKU 产品码、GTIN、OE、PNCS/ELECT 和防爆；须提供尺寸。",
}
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 4096
MAX_ROWS = 500
MAX_DEPTH = 80


def _error() -> ValueError:
    return ValueError("parser_schema_changed")


def _model(value: Any) -> str:
    if not isinstance(value, str):
        raise _error()
    return " ".join(value.replace("™", "").split()).casefold()


def _dimension(size: Any) -> str:
    if not isinstance(size, str):
        raise ValueError("invalid_size")
    try:
        metric = parse_size(size).replace("ZR", "R")
    except (ValueError, TypeError, AttributeError):
        raise ValueError("invalid_size") from None
    return metric.replace("/", "_").replace("R", "-r")


def build_query_url(query: dict) -> str:
    if not isinstance(query, dict):
        raise ValueError("invalid_size")
    model = query.get("model")
    if model is not None and (not isinstance(model, str) or _model(model) != _model(MODEL)):
        raise ValueError("unsupported_model")
    if query.get("size") in (None, ""):
        raise ValueError("source_size_required")
    return ORIGIN + BASE_PATH + "/" + _dimension(query["size"])


def permitted_path(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "www.pirelli.com"
                or parsed.netloc not in {"www.pirelli.com", "www.pirelli.com:443"}
                or parsed.query or parsed.fragment or "?" in url or "#" in url
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or "\\" in url):
            return False
        match = re.fullmatch(re.escape(BASE_PATH) + r"/(\d{3})_(\d{2})-r(\d{2}(?:\.5)?)", parsed.path)
        if not match:
            return False
        dimension = "_".join(match.groups()[:2]) + "-r" + match[3]
        return _dimension(f"{match[1]}/{match[2]}R{match[3]}") == dimension
    except (ValueError, TypeError, AttributeError):
        return False


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _error()
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise _error()


def _float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _error()
    return parsed


def _json(value: str) -> Any:
    result = json.loads(value, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
    stack, count = [(result, 0)], 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > MAX_DEPTH or count > 150_000:
            raise _error()
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
    return result


class _Scripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.active: list[str] | None = None
        self.attrs: dict | None = None
        self.flight: list[str] = []
        self.products: list[dict] = []
        self.script_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            if self.active is not None or len(dict(attrs)) != len(attrs):
                raise _error()
            self.script_count += 1
            if self.script_count > MAX_RECORDS:
                raise _error()
            self.active, self.attrs = [], dict(attrs)

    def handle_data(self, data: str) -> None:
        if self.active is not None:
            self.active.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "script" or self.active is None:
            return
        source = "".join(self.active)
        if self.attrs and self.attrs.get("type") == "application/ld+json":
            product = _json(source)
            if isinstance(product, dict) and product.get("@type") == "Product":
                self.products.append(product)
        else:
            # Accept exactly one literal push. Expressions and trailing JS are
            # ignored, never evaluated or partially interpreted as a push.
            match = re.fullmatch(r"\s*self\.__next_f\.push\((.*)\)\s*;?\s*", source, re.S)
            if match:
                push = _json(match[1])
                if (isinstance(push, list) and len(push) == 2
                        and type(push[0]) is int and push[0] == 1 and isinstance(push[1], str)):
                    self.flight.append(push[1])
        self.active, self.attrs = None, None


def _props(stream: str) -> dict:
    raw = stream.encode("utf-8")
    position, records, candidates, record_count = 0, set(), [], 0
    while position < len(raw):
        if raw[position:position + 1] == b"\n":
            position += 1
            continue
        header = re.match(rb"([0-9a-f]{1,8})?:", raw[position:])
        record_count += 1
        if not header or (header[1] is not None and header[1] in records) or record_count > MAX_RECORDS:
            raise _error()
        if header[1] is not None:
            records.add(header[1])
        position += header.end()
        if header[1] is None and not raw[position:].startswith(b"HL"):
            raise _error()
        if raw[position:position + 1] == b"T":
            text = re.match(rb"T([0-9a-f]{1,8}),", raw[position:])
            if not text:
                raise _error()
            position += text.end() + int(text[1], 16)
            if position > len(raw):
                raise _error()
            continue
        end = raw.find(b"\n", position)
        if end < 0:
            end = len(raw)
        value = raw[position:end].decode("utf-8")
        # Module/resource records remain data; references are never followed.
        for prefix in ("HL", "I"):
            if value.startswith(prefix):
                value = value[len(prefix):]
                break
        decoded = _json(value)
        if (isinstance(decoded, list) and len(decoded) == 4 and decoded[0] == "$"
                and isinstance(decoded[3], dict) and isinstance(decoded[3].get("sizeList"), dict)):
            candidates.append(decoded[3])
        position = end + 1
    if len(candidates) != 1:
        raise _error()
    return candidates[0]


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise _error()
    return value.strip()


def _optional_text(row: dict, field: str) -> str | None:
    value = row.get(field)
    return None if value in (None, "") else _text(value)


def _boolean(row: dict, field: str) -> bool | None:
    value = row.get(field)
    if value is not None and type(value) is not bool:
        raise _error()
    return value


def _reject_pagination(collection: dict) -> None:
    # A newly declared page/count/truncation boundary changes the collection
    # contract even when the flag is false or null. Model-wide totalSizes is
    # navigation metadata, not a SKU total, and is deliberately not matched.
    markers = {
        "hasmore", "hasnext", "hasnextpage", "hasprevious", "haspreviouspage",
        "next", "nextpage", "nextpageurl", "nextcursor", "cursor", "offset", "limit",
        "pagination", "paginationinfo", "pageinfo", "page", "pages", "pagenumber",
        "pageindex", "pagesize", "total", "totalcount", "totalpages", "totalrows",
        "totalitems", "totalresults", "totalrecords", "totalipcodes",
        "truncated", "istruncated", "partial", "ispartial", "hasremaining",
    }
    stack: list[Any] = [collection]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if any(re.sub(r"[^a-z0-9]", "", key.casefold()) in markers for key in value):
                raise _error()
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def _technology(value: Any) -> str:
    token = " ".join(unescape(_text(value)).replace("™", "").split()).upper()
    if not token:
        raise _error()
    return "RUNFLAT" if token == "RUN FLAT" else token


def _row(row: Any, index: int, dimension: str) -> dict:
    if not isinstance(row, dict) or row.get("productId") != "p-zeropz4":
        raise _error()
    spec = row.get("ipcodeTechSpec")
    if not isinstance(spec, dict) or spec.get("productName") != "P-ZERO PZ4":
        raise _error()
    code = _text(row.get("id"))
    if not re.fullmatch(r"\d{6,12}", code) or spec.get("ipcode") != code:
        raise _error()
    description = _text(row.get("description"))
    described = re.fullmatch(r"(\d{3}/\d{2}(?:ZR|R)\d{2}(?:\.5)?)\s+(\d{2,3})([A-Z])", description)
    if not described:
        raise _error()
    size = parse_size(described[1])
    structure = "ZR" if "ZR" in size else "R"
    if _dimension(size) != dimension or row.get("structure") != structure:
        raise _error()
    width, ratio, rim = re.fullmatch(r"(\d{3})/(\d{2})(?:ZR|R)(\d{2}(?:\.5)?)", size).groups()
    if (row.get("section-with") != width or row.get("serie") != ratio
            or type(row.get("rim")) not in (int, float) or row["rim"] != float(rim)):
        raise _error()
    for carrier in (row, spec):
        if _dimension(_text(carrier.get("search-description"))) != dimension:
            raise _error()
    service = _text(row.get("load_speed_rating"))
    ordinary = re.fullmatch(r"(\d{2,3})([A-Z])", service)
    parenthesized = re.fullmatch(r"\((\d{2,3})Y\)", service)
    if ordinary:
        load, speed = ordinary.groups()
    elif parenthesized:
        load, speed = parenthesized[1], "(Y)"
    else:
        raise _error()
    if load != described[2] or speed.strip("()") != described[3]:
        raise _error()
    if speed not in {"B", "C", "D", "E", "F", "G", "J", "K", "L", "M", "N", "P", "Q", "R", "S", "T", "U", "H", "V", "W", "Y", "(Y)"}:
        raise _error()
    if spec.get("lsi") is not None and spec["lsi"] != (f"({load})" if parenthesized else load):
        raise _error()
    if spec.get("speed") is not None:
        declared_speed = re.fullmatch(r"([A-Z])\s+\d+(?:\.\d+)?\s*\(km/h\)", _text(spec["speed"]))
        if not declared_speed or declared_speed[1] != speed.strip("()"):
            raise _error()
    base = f"NextFlight.mainProps.sizeList.ipcodes[{index}]"
    spans = {"brand": "script[type='application/ld+json'] Product.brand.name",
             "model": "NextFlight.mainProps.pageJson.tyre_info.productName",
             "region": "NextFlight.mainProps.genericSettings.country",
             "manufacturer_product_code": base + ".id",
             "size": base + ".description / .structure", "source_variant_name": base + ".description",
             "load_index": base + ".load_speed_rating", "speed_rating": base + ".load_speed_rating"}
    facts: dict[str, Any] = {}

    def fact(name: str, value: Any, field: str) -> None:
        facts[name] = value
        spans["facts." + name] = base + "." + field

    fact('product_code_type', 'IP_CODE', 'id')
    fact("service_description", service, "load_speed_rating")
    fact("construction", structure, "structure")
    gtin = _optional_text(row, "ean_code")
    if gtin is not None:
        if (not re.fullmatch(r"\d{13}", gtin)
                or (sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(gtin[:-1])) + int(gtin[-1])) % 10):
            raise _error()
        fact("gtin", gtin, "ean_code")
    load_class = _optional_text(spec, "load")
    if load_class not in (None, "XL", "HL", "SL"):
        raise _error()
    xl = _boolean(row, "is-xl")
    if load_class == "XL":
        if xl is False:
            raise _error()
        xl = True
    elif load_class == "SL":
        if xl is True:
            raise _error()
        xl = False
    if load_class is not None:
        fact("load_id", load_class, "ipcodeTechSpec.load")
    if xl is not None:
        spans["xl"] = base + (".is-xl" if row.get("is-xl") is not None else ".ipcodeTechSpec.load")
    hl = True if load_class == "HL" else None
    if hl is not None:
        spans["hl"] = base + ".ipcodeTechSpec.load"
    oe = _optional_text(row, "marking")
    spec_oe = _optional_text(spec, "oe_marking")
    if oe is not None and spec_oe is not None and oe != spec_oe:
        raise _error()
    if oe is None:
        oe = spec_oe
    if oe is not None:
        spans["oe_mark"] = base + (".marking" if row.get("marking") else ".ipcodeTechSpec.oe_marking")
    flags = {field: _boolean(row, field) for field in ("pncs", "elect", "run_flat")}
    enum_fields = []
    if "techEnums" in row:
        if not isinstance(row["techEnums"], list) or len(row["techEnums"]) > 30:
            raise _error()
        enum_fields.append({_text(t).upper() for t in row["techEnums"]})
    if "techs" in row:
        if not isinstance(row["techs"], list) or len(row["techs"]) > 30:
            raise _error()
        if any(not isinstance(t, dict) for t in row["techs"]):
            raise _error()
        enum_fields.append({_text(t.get("technology")).upper() for t in row["techs"]})
    if "technologies" in row:
        if not isinstance(row["technologies"], list) or len(row["technologies"]) > 30:
            raise _error()
        enum_fields.append({_technology(t) for t in row["technologies"]})
    features = []
    for field, token in (("pncs", "PNCS"), ("elect", "ELECT"), ("run_flat", "RUNFLAT")):
        value = flags[field]
        if value is not None:
            if any((token in declared) != value for declared in enum_fields):
                raise _error()
            if field != "run_flat":
                fact(field, value, field)
                if field == "elect":
                    fact("ev_marketing_mark", value, field)
            else:
                spans["run_flat"] = base + ".run_flat"
            if value:
                features.append(token)
    if features:
        fact("technology_features", features, "pncs / .elect / .run_flat")
    acoustic = "PNCS" if flags["pncs"] is True else None
    if acoustic:
        spans["acoustic_technology"] = base + ".pncs"
    for field in ("runforward", "self_sealing", "cyber"):
        value = _boolean(row, field)
        if value is not None:
            fact(field, value, field)
    raw_utqg = _optional_text(spec, "utqg")
    components = {field: _optional_text(spec, field) for field in ("treadwear", "traction", "temperature")}
    if raw_utqg is not None:
        fact("source_utqg_raw", raw_utqg, "ipcodeTechSpec.utqg")
    if any(value is not None for value in components.values()):
        fact("source_utqg_components", components, "ipcodeTechSpec")
    anomalies = []
    for field, pattern in (("treadwear", r"\d{2,4}"), ("traction", r"AA|A|B|C"), ("temperature", r"A|B|C")):
        value = components[field]
        if value is not None and not re.fullmatch(pattern, value):
            anomalies.append({"field": "utqg_" + field, "raw_value": value,
                              "reason": "source_" + field + "_outside_standard_enum",
                              "locator": base + ".ipcodeTechSpec." + field})
    if all(value is not None for value in components.values()) and raw_utqg is not None:
        if raw_utqg != "/".join(components.values()):
            anomalies.append({"field": "utqg", "raw_value": raw_utqg,
                              "reason": "source_raw_components_disagree", "locator": base + ".ipcodeTechSpec.utqg"})
        if not anomalies:
            for field, value in components.items():
                fact("utqg_" + field, int(value) if field == "treadwear" else value, "ipcodeTechSpec." + field)
    if anomalies:
        fact("source_field_anomalies", anomalies, "ipcodeTechSpec")
    labels = row.get("ecoLabelPrints", [])
    if not isinstance(labels, list) or len(labels) > 20:
        raise _error()
    for label in labels:
        if not isinstance(label, dict) or (label.get("matnr") is not None and label["matnr"] != code):
            raise _error()
    facts["evidence_spans"] = spans
    return {"brand": "Pirelli", "model": MODEL, "region": "US", "manufacturer_product_code": code,
            "size": size, "load_index": load, "speed_rating": speed, "xl": xl, "hl": hl,
            "oe_mark": oe, "acoustic_technology": acoustic, "run_flat": flags["run_flat"],
            "source_variant_name": description, "facts": facts}


def parse_html(body: str, query: dict) -> list[dict]:
    """Validate the complete observed size-page collection before any filtering."""
    try:
        expected_url = build_query_url(query)
        if not isinstance(body, str) or len(body.encode("utf-8")) > MAX_BODY_BYTES:
            raise _error()
        html = _Scripts()
        html.feed(body)
        html.close()
        if html.active is not None or not html.flight:
            raise _error()
        props = _props("".join(html.flight))
        settings, search = props.get("genericSettings"), props.get("searchParams")
        info = props.get("pageJson", {}).get("tyre_info", {})
        dimension = expected_url.rsplit("/", 1)[1]
        if (not isinstance(settings, dict) or not isinstance(search, dict) or not isinstance(info, dict)
                or settings.get("basePath") != ORIGIN or settings.get("lang") != "en-us"
                or settings.get("country") != "US" or settings.get("countryCode") != "en_US"
                or settings.get("pathname") != urlsplit(expected_url).path
                or search.get("product") != "new-p-zero" or search.get("lang") != "en-us"
                or search.get("size") != dimension or props.get("productID") != "p-zeropz4"
                or _model(info.get("productName")) != _model(MODEL)
                or info.get("b2cProductId") != "p-zeropz4" or info.get("productLink") != BASE_PATH
                or props.get("theUrl") != BASE_PATH or props.get("querySize") != dimension
                or props.get("queryDetails") is not None or props.get("queryIpcode") is not None
                or _dimension(props.get("sizeSelected")) != dimension):
            raise _error()
        if len(html.products) != 1:
            raise _error()
        product = html.products[0]
        if (not isinstance(product.get("brand"), dict) or product["brand"].get("name") != "Pirelli"
                or _model(product.get("name")) != _model(MODEL) or product.get("url") != BASE_PATH):
            raise _error()
        size_list = props["sizeList"]
        _reject_pagination(size_list)
        rows = size_list.get("ipcodes")
        if not isinstance(rows, list) or not rows or len(rows) > MAX_ROWS:
            raise _error()
        variants = [_row(row, i, dimension) for i, row in enumerate(rows)]
        codes = [row["manufacturer_product_code"] for row in variants]
        gtins = [row["facts"]["gtin"] for row in variants if "gtin" in row["facts"]]
        if len(set(codes)) != len(codes) or len(set(gtins)) != len(gtins):
            raise _error()
        return variants
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError, UnicodeError):
        raise _error() from None
