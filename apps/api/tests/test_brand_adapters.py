"""Synthetic fixtures test parsers; optional saved live captures test real replay.

Synthetic rows are intentionally not official or Golden SKU evidence. Network
canaries are separate, stored under ignored .artifacts/canary and never fabricated.
"""

from html import escape
import hashlib
import json
from pathlib import Path

import pytest

from tire_api.adapters import hankook, toyo
from tire_api.domain import VariantInput

REAL_FIXTURES = Path(__file__).parent / "fixtures" / "brand_sources"


def toyo_row(**changes):
    row = {"pattern_id": "PXSP", "product_code": "999001", "tire_size": "265/40ZR20",
           "product_name": "SYNTHETIC PXSP 265/40ZR20 X", "load_index_ss": "104(Y)",
           "load_range_pr": "XL", "rd_xl": "XL", "ean": "9999999999999",
           "utqg": "240 AA A", "weight__lbs__": "25.5", "tread_depth": "9.5",
           "max_load_single": "1984", "max_psi_single": "50", "for_sale": "Y",
           "construction": "NONE", "rim_width": "9.0-(9.5)-10.5", "sidewall": "B"}
    row.update(changes)
    return row


def toyo_body(rows=None):
    return json.dumps({"success": True, "data": {"layout": ["Tire Size|Tire Size"],
                                               "tires": [toyo_row()] if rows is None else rows}})


def hankook_fields(**changes):
    row = {"Material Code": "9990001", "Load Index": "104", "Speed Symbol": "Y",
           "UTQG - Tread Wear": "300", "UTQG - Traction": "AA", "UTQG - Temperature": "A",
           "Foam": "Y", "Run Flat": "N", "OEM": "BMW, Audi", "Tire Weight(lbs.)": "28",
           "Tread Depth(32nds)": "9.5", "Max Load(lbs.)": "1984", "M+S": "N",
           "3PMSF": "N", "Origin": "Korea", "Sealant": "N"}
    row.update(changes)
    return row


def hankook_card(fields=None, size="265/40R20 XL"):
    fields = hankook_fields() if fields is None else fields
    specs = "".join(f'<li class="spec"><span class="dt">{escape(k)}</span>'
                    f'<span class="dd">{escape(str(v))}</span></li>' for k, v in fields.items())
    return f'<li><div class="accordion-top js-size">{escape(size)}</div><div class="accordion-body"><ul class="specs">{specs}</ul></div></li>'


def hankook_body(tabs=None, *, single=False):
    tabs = [("Ventus S1 evo3", [hankook_card()])] if tabs is None else tabs
    navigation = "" if single else "".join(f'<a class="tab" href="#tab{i}">{escape(model)}</a>'
                                           for i, (model, _) in enumerate(tabs, 1))
    cards = "".join(f'<div class="tab-body" id="tab{i}"><ul class="spec-accordion">'
                    + "".join(rows) + "</ul></div>" for i, (_, rows) in enumerate(tabs, 1))
    return ('<html><head><meta property="og:title" content="Ventus S1 evo 3 ev - Ventus | Hankook Tire USA"></head>'
            f'<body><section class="ltdsr ltdsrp">{navigation}{cards}</section></body></html>')


def test_toyo_preserves_product_gtin_zr_service_and_sku_utqg():
    row = toyo.parse_html(toyo_body(), {"model": "Proxes Sport", "size": "265/40R20"})[0]
    VariantInput.model_validate(row)
    assert row["manufacturer_product_code"] == "999001"
    assert row['facts']['product_code_type'] == 'PRODUCT_CODE'
    assert row['facts']['evidence_spans']['facts.product_code_type'] == '$.data.tires[0].product_code'
    assert VariantInput.model_validate(row).identity()['product_code_type'] == 'PRODUCT_CODE'
    assert row["size"] == "265/40ZR20"
    assert (row["load_index"], row["speed_rating"], row["xl"]) == ("104", "(Y)", True)
    assert row["facts"]["gtin"] == "9999999999999"
    assert row["facts"]["utqg_treadwear"] == 240
    assert row["facts"]["utqg_traction"] == "AA"
    assert row["facts"]["tread_depth"] == {"unit": "1/32 in", "value": 9.5}
    assert "$.data.tires[0].utqg" == row["facts"]["evidence_spans"]["facts.utqg_treadwear"]
    assert "construction" not in row["facts"]  # NONE is not a radial construction claim.
    for key in ("hl", "oe_mark", "acoustic_technology", "run_flat"):
        assert row[key] is None


def test_toyo_sl_is_explicit_but_missing_load_id_remains_unknown():
    assert toyo.parse_html(toyo_body([toyo_row(load_range_pr="SL", rd_xl="SL")]), {})[0]["xl"] is False
    row = toyo.parse_html(toyo_body([toyo_row(load_range_pr=None, rd_xl=None, ean=None, utqg=None)]), {})[0]
    assert row["xl"] is None
    assert "gtin" not in row["facts"] and "utqg_treadwear" not in row["facts"]


@pytest.mark.parametrize("changes", [
    {"product_code": None}, {"product_code": "12/3"}, {"pattern_id": "UNKNOWN"},
    {"tire_size": "265/40??20"}, {"load_index_ss": "104FAST"}, {"load_range_pr": "standard"},
    {"rd_xl": "SL"}, {"utqg": "AA A"}, {"utqg": "240 ZZ A"}, {"ean": 123},
    {"weight__lbs__": "NaN"}, {"weight__lbs__": True}, {"for_sale": "true"},
])
def test_toyo_rejects_damaged_rows_before_filtering(changes):
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        toyo.parse_html(toyo_body([toyo_row(), toyo_row(**changes)]), {"model": "unmatched"})


@pytest.mark.parametrize("body", ["<html>challenge</html>", "{}", "null", '{"success":false}', toyo_body([])])
def test_toyo_rejects_missing_schema(body):
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        toyo.parse_html(body, {})


def test_toyo_does_not_collapse_duplicate_codes_or_mixed_models():
    for rows in ([toyo_row(), toyo_row(utqg="500 A A")],
                 [toyo_row(), toyo_row(product_code="999002", pattern_id="PXAS")]):
        with pytest.raises(ValueError, match="^parser_schema_changed$"):
            toyo.parse_html(toyo_body(rows), {})
    assert toyo.parse_html(toyo_body(), {"model": "Proxes Sport A/S"}) == []
    assert toyo.parse_html(toyo_body(), {"size": "225/45R18"}) == []


def test_hankook_preserves_same_size_runflat_skus_and_oem_semantics():
    first = hankook_fields(**{"Run Flat": "Y"})
    second = hankook_fields(**{"Material Code": "9990002", "Run Flat": "N"})
    rows = hankook.parse_html(hankook_body([("Ventus S1 evo3", [hankook_card(first), hankook_card(second)])]),
                              {"model": "Ventus S1 evo3", "size": "265/40ZR20"})
    assert [row["run_flat"] for row in rows] == [True, False]
    for row in rows:
        VariantInput.model_validate(row)
        assert row["oe_mark"] is None
        assert row["facts"]["oe_vehicle_scope"] == ["BMW", "Audi"]
        assert row["acoustic_technology"] == "Foam"
        assert row["facts"]["acoustic_foam"] is True
        assert row["facts"]["utqg_treadwear"] == 300
        assert row['facts']['product_code_type'] == 'MATERIAL_CODE'
        assert row['facts']['evidence_spans']['facts.product_code_type'] == row['facts']['evidence_spans']['manufacturer_product_code']
        assert "li.spec[dt='Material Code']" in row["facts"]["evidence_spans"]["manufacturer_product_code"]
    assert VariantInput.model_validate(rows[0]).identity() != VariantInput.model_validate(rows[1]).identity()


def test_hankook_tabs_are_source_models_not_query_labels():
    body = hankook_body([
        ("Ventus S1 evo3", [hankook_card()]),
        ("Ventus S1 evo3 SUV", [hankook_card(hankook_fields(**{"Material Code": "9990002"}))]),
        ("Ventus S1 evo3 EV", [hankook_card(hankook_fields(**{"Material Code": "9990003"}))]),
    ])
    assert len(hankook.parse_html(body, {})) == 3
    rows = hankook.parse_html(body, {"model": "Ventus S1 evo3 SUV"})
    assert len(rows) == 1 and rows[0]["manufacturer_product_code"] == "9990002"
    assert hankook.parse_html(body, {"model": "Ventus S1"}) == []


def test_hankook_single_model_page_uses_explicit_title():
    body = hankook_body(single=True)
    rows = hankook.parse_html(body, {"model": "Ventus S1 evo3 EV"})
    assert rows[0]["model"] == "Ventus S1 evo3 EV"
    assert rows[0]["facts"]["evidence_spans"]["model"].startswith("meta[property=")
    assert hankook.parse_html(body, {"model": "Ventus S1 evo3"}) == []
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        hankook.parse_html(body.replace("Ventus S1 evo 3 ev - Ventus", "Unrelated product"), {})


def test_hankook_missing_optional_fields_and_unmarked_size_remain_unknown():
    fields = {key: value for key, value in hankook_fields().items()
              if key in {"Material Code", "Load Index", "Speed Symbol"}}
    row = hankook.parse_html(hankook_body([("Ventus S1 evo3", [hankook_card(fields, "265/40R20")])]), {})[0]
    for key in ("xl", "hl", "run_flat", "oe_mark", "acoustic_technology"):
        assert row[key] is None
    assert set(row["facts"]) == {"evidence_spans", 'product_code_type'}
    assert row['facts']['product_code_type'] == 'MATERIAL_CODE'


@pytest.mark.parametrize("field,value", [("Material Code", ""), ("Load Index", "XL"),
    ("Speed Symbol", "FAST"), ("Run Flat", "yes"), ("Foam", "false"),
    ("UTQG - Tread Wear", "abc"), ("UTQG - Traction", "AAA"), ("Tire Weight(lbs.)", "NaN")])
def test_hankook_rejects_damaged_card_before_filtering(field, value):
    body = hankook_body([("Ventus S1 evo3", [hankook_card(hankook_fields(**{field: value}))])])
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        hankook.parse_html(body, {"size": "225/45R18"})


def test_hankook_rejects_duplicate_or_missing_specification_scope():
    bodies = ["<html>challenge</html>", hankook_body([]),
              hankook_body([("Ventus S1 evo3", [hankook_card(), hankook_card()])]),
              hankook_body().replace("ltdsrp", "unrelated"),
              hankook_body().replace("class=\"dt\">Load Index", "class=\"dt\">Material Code")]
    for body in bodies:
        with pytest.raises(ValueError, match="^parser_schema_changed$"):
            hankook.parse_html(body, {})


def test_hankook_ignores_scripts_and_common_page_marketing():
    injection = '<script>throw Error("never execute");</script><p>All tires have runflat and Foam.</p>'
    body = injection + hankook_body([("Ventus S1 evo3", [hankook_card(hankook_fields(**{"Foam": "N"}))])])
    row = hankook.parse_html(body, {})[0]
    assert row["run_flat"] is False and row["acoustic_technology"] is None


def test_committed_real_excerpts_match_provenance_hashes():
    manifest = json.loads((REAL_FIXTURES / "provenance.json").read_bytes())
    assert {"toyo-proxes-sport-excerpt.json", "hankook-runflat-pair-excerpt.html"} <= {
        entry["file"] for entry in manifest["fixtures"]}
    for entry in manifest["fixtures"]:
        raw = (REAL_FIXTURES / entry["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["fixture_sha256"]
        assert len(raw) < entry["original_body_bytes"]
        assert len(entry["original_body_sha256"]) == 64
        assert entry["source_url"].startswith("https://")
        assert entry["observed_at"] and entry["transformation"]


def test_committed_toyo_real_specification_rows():
    body = (REAL_FIXTURES / "toyo-proxes-sport-excerpt.json").read_bytes().decode("utf-8")
    variants = toyo.parse_html(body, {"model": "Proxes Sport"})
    assert [row["manufacturer_product_code"] for row in variants] == ["136130", "132860"]
    assert [(row["size"], row["load_index"], row["speed_rating"]) for row in variants] == [
        ("225/45ZR17", "94", "Y"), ("255/40ZR18", "99", "(Y)")]
    assert [row["facts"]["gtin"] for row in variants] == ["4981910788867", "4981910500896"]
    assert all(row["facts"]["utqg_treadwear"] == 240 for row in variants)
    for row in variants:
        VariantInput.model_validate(row)


def test_committed_hankook_real_same_size_runflat_pair():
    body = (REAL_FIXTURES / "hankook-runflat-pair-excerpt.html").read_bytes().decode("utf-8")
    variants = hankook.parse_html(body, {"model": "Ventus S1 evo3", "size": "205/45R17"})
    assert [row["manufacturer_product_code"] for row in variants] == ["1022631", "1022632"]
    assert [row["run_flat"] for row in variants] == [True, False]
    assert [row["facts"]["weight_lb"] for row in variants] == [19, 17]
    assert [row["facts"]["tread_depth"]["value"] for row in variants] == [8.5, 8]
    for row in variants:
        VariantInput.model_validate(row)
        assert (row["load_index"], row["speed_rating"], row["xl"]) == ("88", "W", True)
        assert row["facts"]["oe_vehicle_scope"] == ["BMW"] and row["oe_mark"] is None


@pytest.mark.parametrize("module,name,model,count", [
    (toyo, "toyo-proxes-sport-specs.json", "Proxes Sport", 9),
    (toyo, "toyo-proxes-sport-as-specs.json", "Proxes Sport A/S", 77),
    (hankook, "hankook-ventus-s1-evo3.html", "Ventus S1 evo3", 25),
    (hankook, "hankook-ventus-s1-evo3-suv.html", "Ventus S1 evo3 SUV", 18),
    (hankook, "hankook-ventus-s1-evo3-ev.html", "Ventus S1 evo3 EV", 8),
])
def test_saved_real_response_replay_when_present(module, name, model, count):
    capture = Path(__file__).resolve().parents[3] / ".artifacts" / "canary" / name
    if not capture.is_file():
        pytest.skip("independent live capture unavailable; synthetic tests are not a canary")
    variants = module.parse_html(capture.read_bytes().decode("utf-8"), {"model": model})
    assert len(variants) == count
    for variant in variants:
        VariantInput.model_validate(variant)
        assert variant["facts"]["evidence_spans"]
