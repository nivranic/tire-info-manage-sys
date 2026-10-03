"""Hankook US server-rendered per-SKU specification cards, scoped by model tab.

Marketing copy, common tire-finder examples, and vehicle search results are not
evidence. OEM manufacturer names are not invented sidewall OE homologation marks.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from ..domain import parse_size

PARSER_VERSION = "hankook-us-spec-cards@1.1.0"
SOURCE_CONFIG = {
    "id": "hankook-us", "name": "韩泰 · 美国官网", "region": "US",
    "origin": "https://www.hankooktire.com", "status": "ready",
    "model_urls": {
        "Ventus S1 evo3": "https://www.hankooktire.com/us/en/tire/ventus/s1evo3-k127.html",
        "Ventus S1 evo3 SUV": "https://www.hankooktire.com/us/en/tire/ventus/s1evo3suv-k127a.html",
        "Ventus S1 evo3 EV": "https://www.hankooktire.com/us/en/tire/ventus/s1evo3ev.html",
    },
    "content_types": ("text/html",), "parser_version": PARSER_VERSION,
    "description": "Ventus S1 evo3 / SUV / EV 美国规格卡：Material Code、UTQG、静音棉、防爆及 OEM 适用品牌。",
}
_MODELS = set(SOURCE_CONFIG["model_urls"])
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def _error() -> ValueError:
    return ValueError("parser_schema_changed")


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str | None]
    children: list[Any] = field(default_factory=list)

    def has_class(self, name: str) -> bool:
        return name in (self.attrs.get("class") or "").split()

    def text(self) -> str:
        return " ".join(" ".join(child.text() if isinstance(child, _Node) else child
                                 for child in self.children).split())

    def find(self, tag: str, class_name: str) -> list[_Node]:
        found = []
        for child in self.children:
            if isinstance(child, _Node):
                if child.tag == tag and child.has_class(class_name):
                    found.append(child)
                found.extend(child.find(tag, class_name))
        return found


class _SpecHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[_Node] = []
        self.stack: list[_Node] = []
        self.titles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, dict(attrs))
        if tag == "meta" and node.attrs.get("property") == "og:title":
            self.titles.append(node.attrs.get("content") or "")
        if not self.stack:
            if tag != "section" or not node.has_class("ltdsrp"):
                return
            self.sections.append(node)
        else:
            self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)
        if len(self.stack) > 80:
            raise _error()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.stack:
            self.stack[-1].children.append(data)


def _one(nodes: list[_Node]) -> _Node:
    if len(nodes) != 1:
        raise _error()
    return nodes[0]


def _number(value: str) -> float:
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise _error() from None
    if not math.isfinite(result) or result < 0:
        raise _error()
    return result


def _model(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold()).removeprefix("hankook")


def _row(card: _Node, model: str, tab_id: str, index: int) -> dict[str, Any]:
    source_name = _one(card.find("div", "accordion-top")).text()
    match = re.fullmatch(r"([0-9]{3}/[0-9]{2}(?:ZR|R)[0-9]{2}(?:\.5)?)(?:\s+(XL|HL))?", source_name)
    if not match:
        raise _error()
    size = parse_size(match[1])
    fields: dict[str, str] = {}
    for spec in card.find("li", "spec"):
        name = _one(spec.find("span", "dt")).text()
        value = _one(spec.find("span", "dd")).text()
        if not name or name in fields:
            raise _error()
        fields[name] = value
    code, load, speed = (fields.get(key, "") for key in ("Material Code", "Load Index", "Speed Symbol"))
    if (not re.fullmatch(r"[0-9]{6,12}", code) or not re.fullmatch(r"[0-9]{2,3}", load)
            or not re.fullmatch(r"[A-Z]|\(Y\)|A[1-8]", speed)):
        raise _error()
    base = f"section.ltdsrp #{tab_id} ul.spec-accordion > li:nth-child({index + 1})"

    def location(label: str) -> str:
        return f"{base} li.spec[dt={label!r}] span.dd"

    spans = {"manufacturer_product_code": location("Material Code"),
             "model": f"section.ltdsrp a.tab[href='#{tab_id}']",
             "size": f"{base} .accordion-top", "source_variant_name": f"{base} .accordion-top",
             "load_index": location("Load Index"), "speed_rating": location("Speed Symbol")}
    facts: dict[str, Any] = {}

    def present(label: str) -> bool:
        return fields.get(label) not in (None, "", "-", "N/A")

    def fact(name: str, value: Any, label: str) -> None:
        facts[name] = value
        spans[f"facts.{name}"] = location(label)

    fact('product_code_type', 'MATERIAL_CODE', 'Material Code')

    def boolean(label: str) -> bool | None:
        if not present(label):
            return None
        if fields[label] not in ("Y", "N"):
            raise _error()
        return fields[label] == "Y"

    run_flat = boolean("Run Flat")
    if run_flat is not None:
        spans["run_flat"] = location("Run Flat")
    foam = boolean("Foam")
    if foam is not None:
        fact("acoustic_foam", foam, "Foam")
        if foam:
            spans["acoustic_technology"] = location("Foam")
    for label, name in (("M+S", "m_plus_s"), ("3PMSF", "three_peak_mountain_snowflake"),
                        ("Sealant", "sealant"), ("Studded", "studded")):
        value = boolean(label)
        if value is not None:
            fact(name, value, label)
    if present("UTQG - Tread Wear"):
        if not re.fullmatch(r"[0-9]{2,4}", fields["UTQG - Tread Wear"]):
            raise _error()
        fact("utqg_treadwear", int(fields["UTQG - Tread Wear"]), "UTQG - Tread Wear")
    for label, name, valid in (("UTQG - Traction", "utqg_traction", {"AA", "A", "B", "C"}),
                               ("UTQG - Temperature", "utqg_temperature", {"A", "B", "C"})):
        if present(label):
            if fields[label] not in valid:
                raise _error()
            fact(name, fields[label], label)
    for label, name in (("Max Load(lbs.)", "max_load_lb"), ("Tire Weight(lbs.)", "weight_lb"),
                        ("Revs/MI", "revolutions_per_mile"), ("Ply Rating", "ply_rating"),
                        ("Recommended Rim Width", "recommended_rim_width_in")):
        if present(label):
            fact(name, _number(fields[label]), label)
    if present("Tread Depth(32nds)"):
        fact("tread_depth", {"unit": "1/32 in", "value": _number(fields["Tread Depth(32nds)"])}, "Tread Depth(32nds)")
    for label, name in (("Origin", "manufacturing_origin"), ("Sidewall Color", "sidewall_code"),
                        ("Rim Width Range", "rim_width_range_in")):
        if present(label):
            fact(name, fields[label], label)
    if present("OEM"):
        fact("oe_vehicle_scope", [name.strip() for name in fields["OEM"].split(",") if name.strip()], "OEM")
    marker = match[2]
    if marker:
        spans[marker.casefold()] = f"{base} .accordion-top"
    facts["evidence_spans"] = spans
    return {"brand": "Hankook", "model": model, "region": "US", "manufacturer_product_code": code,
            "size": size, "load_index": load, "speed_rating": speed,
            "xl": True if marker == "XL" else None, "hl": True if marker == "HL" else None,
            "oe_mark": None, "acoustic_technology": "Foam" if foam else None,
            "run_flat": run_flat, "source_variant_name": source_name, "facts": facts}


def parse_html(body: str, query: dict) -> list[dict]:
    """Validate every spec card before filtering; preserve each model tab and SKU."""
    if not isinstance(body, str):
        raise _error()
    parser = _SpecHTML()
    try:
        parser.feed(body)
        parser.close()
        section = _one(parser.sections)
        if parser.stack:
            raise _error()
        tabs: dict[str, str] = {}
        for tab in section.find("a", "tab"):
            href = tab.attrs.get("href") or ""
            model = tab.text()
            if not re.fullmatch(r"#tab[0-9]+", href) or href[1:] in tabs or model not in _MODELS:
                raise _error()
            tabs[href[1:]] = model
        bodies = section.find("div", "tab-body")
        single_model = not tabs
        if single_model:
            # The dedicated EV page has one specification tab and publishes the
            # model in og:title instead of a tab label. Never infer it from query.
            if len(bodies) != 1 or len(parser.titles) != 1:
                raise _error()
            title_model = parser.titles[0].split(" - ", 1)[0]
            matches = [name for name in _MODELS if _model(name) == _model(title_model)]
            if len(matches) != 1 or bodies[0].attrs.get("id") != "tab1":
                raise _error()
            tabs["tab1"] = matches[0]
        if not tabs or len(bodies) != len(tabs):
            raise _error()
        variants = []
        seen_tabs: set[str] = set()
        for tab in bodies:
            tab_id = tab.attrs.get("id")
            if tab_id not in tabs or tab_id in seen_tabs:
                raise _error()
            seen_tabs.add(tab_id)
            cards = _one(tab.find("ul", "spec-accordion"))
            rows = [node for node in cards.children if isinstance(node, _Node) and node.tag == "li"]
            if not rows:
                raise _error()
            variants.extend(_row(row, tabs[tab_id], tab_id, index) for index, row in enumerate(rows))
        if single_model:
            for variant in variants:
                variant["facts"]["evidence_spans"]["model"] = "meta[property='og:title']@content (model prefix)"
        codes = [row["manufacturer_product_code"] for row in variants]
        if not variants or len(variants) > 500 or len(codes) != len(set(codes)):
            raise _error()
    except (TypeError, KeyError, ValueError, RecursionError, OverflowError):
        raise _error() from None
    if query.get("model") is not None:
        if not isinstance(query["model"], str):
            return []
        variants = [row for row in variants if _model(row["model"]) == _model(query["model"])]
    if query.get("size") is not None:
        try:
            size = parse_size(query["size"]).replace("ZR", "R")
        except (ValueError, TypeError, AttributeError):
            return []
        variants = [row for row in variants if row["size"].replace("ZR", "R") == size]
    return variants


parse_hankook_html = parse_html
