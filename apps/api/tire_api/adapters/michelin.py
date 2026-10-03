"""Parse Michelin regional public catalogues without executing page content.

US/UK/FR/DE use the productSummary property of an astro-island. CN uses
the JSON literal inside its public, fixed-path ``var specs = {...}`` asset.
The caller owns networking, evidence snapshots, and product identity resolution.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any


_SCHEMA_ERROR = "parser_schema_changed"
_SIZE = re.compile(r"(?P<load_prefix>HL)?(?P<width>\d{3})/(?P<aspect>\d{2,3})(?P<construction>ZR|R|B|D)(?P<rim>\d{2}(?:\.5)?)")
_MODEL_ALIASES = {
    "psev": "pilotsportev",
    "ps4s": "pilotsport4s",
    "ps4": "pilotsport4",
    "ps5": "pilotsport5",
}


def _schema_error() -> ValueError:
    return ValueError(_SCHEMA_ERROR)


class _ProductProps(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.summaries: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "astro-island":
            return
        props = dict(attrs).get("props")
        if props is None:
            return
        try:
            payload = json.loads(props)
        except (ValueError, RecursionError):
            return
        if isinstance(payload, dict) and "productSummary" in payload:
            self.summaries.append(payload["productSummary"])


def _decode(value: Any, depth: int = 0) -> Any:
    """Decode Astro's scalar/object and array wire tags, never JavaScript."""
    if depth > 60 or not isinstance(value, list) or len(value) != 2:
        raise _schema_error()
    kind, payload = value
    if type(kind) is not int:
        raise _schema_error()
    if kind == 0:
        if isinstance(payload, dict):
            return {key: _decode(item, depth + 1) for key, item in payload.items()}
        if payload is None or type(payload) in (str, bool, int, float):
            return payload
    if kind == 1 and isinstance(payload, list):
        return [_decode(item, depth + 1) for item in payload]
    raise _schema_error()


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _schema_error()
    return value.strip()


def _optional_bool(article: dict[str, Any], key: str) -> bool | None:
    value = article.get(key)
    if value is not None and type(value) is not bool:
        raise _schema_error()
    return value


def _size(value: Any) -> tuple[str, str]:
    normalized = re.sub(r"\s+", "", _text(value)).upper()
    match = _SIZE.fullmatch(normalized)
    if match is None:
        raise _schema_error()
    # ZR and R describe the same geometry for filtering, not entity merging.
    construction = "R" if match["construction"] in ("R", "ZR") else match["construction"]
    geometry = f"{match['width']}/{match['aspect']}{construction}{match['rim']}"
    return normalized.removeprefix("HL"), geometry


def _model(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    if normalized.startswith("michelin"):
        normalized = normalized[len("michelin"):]
    return _MODEL_ALIASES.get(normalized, normalized)


def _markings(article: dict[str, Any], key: str) -> list[dict[str, Any]] | None:
    values = article.get(key)
    if values is None:
        return None
    if not isinstance(values, list):
        raise _schema_error()
    for marking in values:
        if not isinstance(marking, dict):
            raise _schema_error()
        _text(marking.get("name"))
        for field in ("brand", "key", "type"):
            if marking.get(field) is not None:
                _text(marking[field])
    return values


def _measurements(article: dict[str, Any], key: str) -> list[dict[str, Any]] | None:
    values = article.get(key)
    if values is None:
        return None
    if not isinstance(values, list):
        raise _schema_error()
    measurements = []
    for item in values:
        if not isinstance(item, dict):
            raise _schema_error()
        unit = _text(item.get("unit"))
        value = item.get("value")
        if type(value) not in (str, int, float):
            raise _schema_error()
        try:
            number = float(value)
        except (ValueError, OverflowError):
            raise _schema_error() from None
        if not math.isfinite(number) or number < 0:
            raise _schema_error()
        measurements.append({"unit": unit, "value": number})
    return measurements


def _article(article: Any, technical: dict[str, Any], index: int, region: str) -> dict[str, Any]:
    if not isinstance(article, dict):
        raise _schema_error()
    code_keys = ("mspn",) if region == "US" else ("cai", "mspn", "ean")
    code_key = next((key for key in code_keys if article.get(key) is not None), code_keys[0])
    code = _text(article.get(code_key))
    if not code.isascii() or not code.isdigit():
        raise _schema_error()
    size, _ = _size(article.get("geoBox"))
    load = article.get("loadIndex")
    if type(load) is not int or not 0 <= load <= 279:
        raise _schema_error()
    speed = _text(article.get("speedIndex")).upper()
    if re.fullmatch(r"(?:[A-Z]|A[1-8]|\([A-Z]\))", speed) is None:
        raise _schema_error()
    source_name = _text(article.get("displaySize"))
    oe_markings = _markings(article, "oeMarkings")
    manuf_markings = _markings(article, "manufMarkings")
    facts: dict[str, Any] = {}
    base = f"productSummary.technical.articles[{index}]"
    spans = {
        "brand": "productSummary.technical.brand",
        "model": "productSummary.technical.name",
        "manufacturer_product_code": f"{base}.{code_key}",
        "size": f"{base}.geoBox",
        "load_index": f"{base}.loadIndex",
        "speed_rating": f"{base}.speedIndex",
        "source_variant_name": f"{base}.displaySize",
    }

    def fact(name: str, value: Any, source_key: str) -> None:
        facts[name] = value
        spans[f"facts.{name}"] = f"{base}.{source_key}"

    fact("product_code_type", {"mspn": "MSPN", "cai": "CAI", "ean": "EAN"}[code_key], code_key)
    for key in ("mspn", "cai"):
        if article.get(key) is not None:
            identifier = _text(article[key])
            if not identifier.isascii() or not identifier.isdigit():
                raise _schema_error()
            fact(key, identifier, key)
    if article.get("ean") is not None:
        ean = _text(article["ean"])
        if not ean.isascii() or not ean.isdigit():
            raise _schema_error()
        fact("gtin", ean, "ean")
    if article.get("structure") is not None:
        fact("construction", _text(article["structure"]), "structure")
    hl_prefix = re.sub(r"\s+", "", article["geoBox"]).upper().startswith("HL")
    if hl_prefix:
        fact("source_size_designation", article["geoBox"], "geoBox")
    if oe_markings is not None:
        fact("oe_vehicle_scope", list(dict.fromkeys(
            marking["brand"].strip() for marking in oe_markings if marking.get("brand")
        )), "oeMarkings")
        spans["oe_mark"] = f"{base}.oeMarkings"
    acoustic = None
    if manuf_markings is not None:
        fact("technology_features", [marking["name"].strip() for marking in manuf_markings], "manufMarkings")
        if any(marking["name"].strip().casefold() == "acoustic" or
               str(marking.get("key", "")).casefold() == "acoustic"
               for marking in manuf_markings):
            acoustic = "Acoustic"
            spans["acoustic_technology"] = f"{base}.manufMarkings"
    weights = _measurements(article, "weights")
    if weights:
        fact("weights", weights, "weights")
        kg = next((item["value"] for item in weights if item["unit"].casefold() == "kg"), None)
        if kg is not None:
            fact("weight_kg", kg, "weights")
    depths = _measurements(article, "treadDepths")
    if depths:
        fact("tread_depth", depths[0], "treadDepths[0]")
        fact("tread_depths", depths, "treadDepths")
    # Catalogue dates have no verified production-period semantics; retain the
    # source names, including future sentinel values, without interpreting them.
    for source_key, name in (("updateDate", "source_updated_at"), ("startDate", "source_start_date"), ("endDate", "source_end_date")):
        if article.get(source_key) is None:
            continue
        value = _text(article[source_key])
        try:
            if source_key == "updateDate":
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            else:
                date.fromisoformat(value)
        except ValueError:
            raise _schema_error() from None
        fact(name, value, source_key)
    if article.get("active") is not None:
        fact("active", _optional_bool(article, "active"), "active")
    service_key = "dimSpec" if article.get("dimSpec") is not None else "dimspec"
    if article.get(service_key) is not None:
        fact("service_description", _text(article[service_key]), service_key)
    if technical.get("season") is not None:
        season = technical["season"]
        if not isinstance(season, dict):
            raise _schema_error()
        facts["season"] = _text(season.get("key"))
        spans["facts.season"] = "productSummary.technical.season.key"

    nullable_bools = {"xl": "extraLoad", "hl": "highLoad", "run_flat": "isRunflat"}
    flags = {name: _optional_bool(article, key) for name, key in nullable_bools.items()}
    for name, key in nullable_bools.items():
        if article.get(key) is not None:
            spans[name] = f"{base}.{key}"
    if article.get("extraLoad") is not None:
        fact("source_extra_load", flags["xl"], "extraLoad")
    if article.get("highLoad") is not None:
        fact("source_high_load", flags["hl"], "highLoad")
    marking_names = {marking["name"].strip().upper() for marking in manuf_markings or []}
    conflicts: list[dict[str, Any]] = []
    for name, source_key, marking in (("xl", "extraLoad", "XL"), ("hl", "highLoad", "HL")):
        if marking not in marking_names and not (name == "hl" and hl_prefix):
            continue
        marking_source = "geoBox" if name == "hl" and hl_prefix else "manufMarkings"
        marking_value = article["geoBox"] if marking_source == "geoBox" else marking
        if flags[name] is False:
            conflicts.append({
                "field": name,
                "values": [
                    {"source_field": source_key, "value": False},
                    {"source_field": marking_source, "value": marking_value},
                ],
                "resolution": "unresolved",
            })
            flags[name] = None
        else:
            flags[name] = True
        spans[name] = f"{base}.{source_key}; {base}.{marking_source}"
    if conflicts:
        facts["source_field_conflicts"] = conflicts
        spans["facts.source_field_conflicts"] = f"{base}.extraLoad; {base}.highLoad; {base}.manufMarkings; {base}.geoBox"
    _label_facts(article, facts, spans, base)
    facts["evidence_spans"] = spans
    return {
        "brand": _text(technical.get("brand")),
        "model": _text(technical.get("name")),
        "manufacturer_product_code": code,
        "region": region,
        "size": size,
        "load_index": load,
        "speed_rating": speed,
        **flags,
        "oe_mark": ", ".join(marking["name"].strip() for marking in oe_markings) if oe_markings else None,
        "acoustic_technology": acoustic,
        "source_variant_name": source_name,
        "facts": facts,
    }


def _label_facts(article: dict[str, Any], facts: dict[str, Any], spans: dict[str, str], base: str) -> None:
    """Preserve manufacturer-published labels without claiming regulator proof."""
    labels = article.get("labelling")
    if labels is None:
        return
    if not isinstance(labels, list):
        raise _schema_error()
    entries: dict[str, str] = {}
    for label in labels:
        if not isinstance(label, dict):
            raise _schema_error()
        key, value = _text(label.get("key")), _text(label.get("value"))
        if key in entries and entries[key] != value:
            raise _schema_error()
        entries[key] = value
    if not entries:
        return
    facts["source_labelling"] = entries
    spans["facts.source_labelling"] = f"{base}.labelling"
    mapping = {
        "eu_fuel_class": ("rollingResistanceClass", "energyEfficiency"),
        "eu_wet_grip": ("wetGripClass", "wetGrip"),
        "eu_external_noise_db": ("exteriorNoiseValue", "externalRollingNoise"),
        "eu_noise_class": ("exteriorNoiseClass", "echoClass21"),
        "eu_directive_number": ("euDirectiveNumber",),
    }
    for name, aliases in mapping.items():
        values = [(key, entries[key]) for key in aliases if key in entries]
        if not values:
            continue
        if len({value for _, value in values}) > 1:
            facts.setdefault("source_field_conflicts", []).append({
                "field": name,
                "values": [{"source_field": f"labelling.{key}", "value": value} for key, value in values],
                "resolution": "unresolved",
            })
            existing = spans.get("facts.source_field_conflicts")
            spans["facts.source_field_conflicts"] = f"{existing}; {base}.labelling" if existing else f"{base}.labelling"
            continue
        value: Any = values[0][1]
        if name == "eu_external_noise_db":
            if not value.isascii() or not value.isdigit() or not 0 < int(value) < 200:
                raise _schema_error()
            value = int(value)
        elif name in ("eu_fuel_class", "eu_wet_grip", "eu_noise_class"):
            allowed = "ABC" if name == "eu_noise_class" else "ABCDEFG"
            if value not in allowed or len(value) != 1:
                raise _schema_error()
        facts[name] = value
        spans[f"facts.{name}"] = f"{base}.labelling[key={values[0][0]}]"


def _cn_catalogue(body: str) -> list[dict]:
    # The public product/index.js explicitly maps item.cai = item.c. Parse
    # only its data asset's JSON assignment; trailing code is a schema error.
    match = re.fullmatch(r"\s*var\s+specs\s*=\s*(\{.*\})\s*;?\s*", body, re.DOTALL)
    if match is None:
        raise _schema_error()
    try:
        data = json.loads(match[1])
    except (ValueError, RecursionError):
        raise _schema_error() from None
    if not isinstance(data, dict) or not data:
        raise _schema_error()
    variants: list[dict] = []
    for raw_size, models in data.items():
        if raw_size == "pno":
            if not isinstance(models, list) or any(not isinstance(model, str) or not model.strip() for model in models):
                raise _schema_error()
            continue
        size, _ = _size(raw_size)
        if not isinstance(models, dict) or not models:
            raise _schema_error()
        for raw_model, articles in models.items():
            _text(raw_model)
            if not isinstance(articles, list) or not articles:
                raise _schema_error()
            for index, article in enumerate(articles):
                if not isinstance(article, dict):
                    raise _schema_error()
                code, load, speed, rim = (_text(article.get(key)) for key in ("c", "l", "s", "d"))
                if not code.isascii() or not code.isdigit() or not load.isascii() or not load.isdigit():
                    raise _schema_error()
                if not 0 <= int(load) <= 279 or re.fullmatch(r"(?:[A-Z]|A[1-8]|\([A-Z]\))", speed) is None:
                    raise _schema_error()
                if rim != _SIZE.fullmatch(size)["rim"]:
                    raise _schema_error()
                markings, technology = article.get("m"), article.get("r")
                if not isinstance(markings, str) or not isinstance(technology, str):
                    raise _schema_error()
                # 'm' contains both OE codes and manufacturer-only markings
                # such as DT/S1. Keep it verbatim rather than label all as OE.
                base = f"specs[{json.dumps(raw_size)}][{json.dumps(raw_model)}][{index}]"
                facts = {
                    "product_code_type": "CAI",
                    "cai": code,
                    "construction": _SIZE.fullmatch(size)["construction"],
                    "source_model_name": raw_model,
                    "source_size_designation": raw_size,
                    "source_markings": markings,
                    "source_technology_marking": technology,
                    "technology_features": [technology] if technology else [],
                    "evidence_spans": {
                        "manufacturer_product_code": f"{base}.c",
                        "facts.cai": f"{base}.c",
                        "facts.product_code_type": f"{base}.c; product/index.js:item.cai=item.c",
                        "model": f"specs[{json.dumps(raw_size)}] key={json.dumps(raw_model)}",
                        "size": f"specs key={json.dumps(raw_size)}",
                        "load_index": f"{base}.l",
                        "speed_rating": f"{base}.s",
                        "facts.source_markings": f"{base}.m",
                        "facts.source_technology_marking": f"{base}.r",
                        "acoustic_technology": f"{base}.r",
                        "run_flat": f"{base}.r",
                    },
                }
                model = "Pilot Sport 4 S" if _model(raw_model) == "pilotsport4s" else raw_model
                variants.append({
                    "brand": "Michelin",
                    "model": model,
                    "manufacturer_product_code": code,
                    "region": "CN",
                    "size": size,
                    "load_index": int(load),
                    "speed_rating": speed,
                    "xl": None,
                    "hl": True if raw_size.upper().startswith("HL") else None,
                    "oe_mark": None,
                    "acoustic_technology": "Acoustic" if technology.upper() == "ACOUSTIC" else None,
                    "run_flat": True if technology.upper() == "ZP" else None,
                    "source_variant_name": " ".join(value for value in (raw_model, size, load + speed, markings, technology) if value),
                    "facts": facts,
                })
    if not variants:
        raise _schema_error()
    return variants


def _filter_variants(variants: list[dict], query: dict) -> list[dict]:
    model = query.get("model")
    if model is not None:
        if not isinstance(model, str):
            return []
        variants = [variant for variant in variants if _model(model) == _model(variant["model"])]
    requested_size = query.get("size")
    if requested_size is not None:
        try:
            _, geometry = _size(requested_size)
        except ValueError:
            return []
        variants = [variant for variant in variants if _size(variant["size"])[1] == geometry]
        if isinstance(requested_size, str) and re.sub(r"\s+", "", requested_size).upper().startswith("HL"):
            variants = [variant for variant in variants if variant["hl"] is True]
    return variants


def parse_michelin_html(body: str, query: dict, *, region: str = "US") -> list[dict]:
    """Return validated article facts matching a model and/or geometric size.

    An unknown requested model legitimately returns no matches. Missing or
    malformed product data raises parser_schema_changed even when a filter
    would otherwise hide the damaged article.
    """
    if not isinstance(body, str):
        raise _schema_error()
    if region not in ("US", "UK", "FR", "DE", "CN"):
        raise ValueError("unsupported_region")
    if region == "CN":
        return _filter_variants(_cn_catalogue(body), query)
    parser = _ProductProps()
    try:
        parser.feed(body)
        parser.close()
        summaries = [_decode(value) for value in parser.summaries]
        if not summaries or any(summary != summaries[0] for summary in summaries[1:]):
            raise _schema_error()
        summary = summaries[0]
        if not isinstance(summary, dict) or not isinstance(summary.get("technical"), dict):
            raise _schema_error()
        technical = summary["technical"]
        _text(technical.get("brand"))
        _text(technical.get("name"))
        articles = technical.get("articles")
        if not isinstance(articles, list) or not articles:
            raise _schema_error()
        variants = [_article(article, technical, index, region) for index, article in enumerate(articles)]
    except (RecursionError, OverflowError):
        raise _schema_error() from None

    return _filter_variants(variants, query)
